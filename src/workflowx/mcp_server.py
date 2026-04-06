"""MCP Server — the agentic interface to WorkflowX.

This isn't a dashboard. It's the bridge that turns Claude (or Cursor, or any
MCP client) into your workflow analyst. Claude can:

  1. OBSERVE  — capture fresh events, view sessions
  2. UNDERSTAND — detect patterns, compute friction trends
  3. REPLACE  — propose replacements, adopt them
  4. MEASURE  — track ROI, verify savings are real

The full observe→understand→replace→measure loop, driven by conversation.

Usage:
    workflowx mcp          # Start MCP server on stdio (Claude Desktop / Claude Code)
    workflowx mcp --http   # Start on HTTP (localhost:8765)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()


def _run_async(coro):
    """Run an async coroutine, handling both sync and async calling contexts.

    When called from the MCP server (which runs its own event loop),
    asyncio.run() fails. We detect this and use the existing loop instead.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (MCP server context).
        # Create a task and run it via nest_asyncio or a thread.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


# ── Shared Helpers ──────────────────────────────────────────


def _get_store():
    """Lazy-load store to avoid import-time side effects."""
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()
    return LocalStore(config.data_dir), config


def _sessions_for_period(period: str = "today") -> list:
    """Load sessions for a named period."""
    store, _ = _get_store()

    ranges = {
        "today": 1,
        "yesterday": 1,
        "week": 7,
        "month": 30,
    }
    days = ranges.get(period, 1)

    if period == "yesterday":
        return store.load_sessions(date.today() - timedelta(days=1))

    sessions = []
    for i in range(days):
        d = date.today() - timedelta(days=i)
        sessions.extend(store.load_sessions(d))
    return sessions


# ── Tool Handlers ───────────────────────────────────────────
# Each returns a dict that gets JSON-serialized as the MCP response.
# Claude reads these and reasons over the data in conversation.


def handle_status() -> dict[str, Any]:
    """Check WorkflowX health: capture sources, data counts, config."""
    store, config = _get_store()

    # Check Screenpipe
    screenpipe_ok = False
    try:
        from workflowx.capture.screenpipe import ScreenpipeAdapter
        sp = ScreenpipeAdapter(db_path=config.screenpipe_db_path)
        screenpipe_ok = sp.is_available()
    except Exception:
        pass

    today_sessions = store.load_sessions(date.today())
    patterns = store.load_patterns()
    outcomes = store.load_outcomes()

    return {
        "screenpipe_connected": screenpipe_ok,
        "screenpipe_db": config.screenpipe_db_path,
        "llm_provider": config.llm_provider,
        "llm_model": config.llm_model,
        "has_api_key": bool(config.anthropic_api_key or config.openai_api_key),
        "data_dir": config.data_dir,
        "today_sessions": len(today_sessions),
        "patterns_tracked": len(patterns),
        "outcomes_tracked": len(outcomes),
        "hourly_rate_usd": config.hourly_rate_usd,
    }


def handle_capture(hours: int = 8) -> dict[str, Any]:
    """Capture fresh events from Screenpipe, cluster into sessions, and store.

    Args:
        hours: Hours of history to read (default: 8, a workday).

    This is the OBSERVE step. Run this to pull in your latest screen activity.
    """
    from workflowx.config import load_config
    from workflowx.inference.clusterer import cluster_into_sessions
    from workflowx.storage import LocalStore

    config = load_config()
    since = datetime.now() - timedelta(hours=hours)
    all_events = []

    # Screenpipe
    try:
        from workflowx.capture.screenpipe import ScreenpipeAdapter
        sp = ScreenpipeAdapter(db_path=config.screenpipe_db_path)
        if sp.is_available():
            events = sp.read_events(since=since)
            all_events.extend(events)
    except Exception as e:
        logger.warning("capture_screenpipe_error", error=str(e))

    # ActivityWatch
    try:
        from workflowx.capture.activitywatch import ActivityWatchAdapter
        aw = ActivityWatchAdapter(host=config.activitywatch_host)
        if aw.is_available():
            events = aw.read_events(since=since)
            all_events.extend(events)
    except Exception:
        pass

    if not all_events:
        return {
            "status": "no_events",
            "message": "No events captured. Is Screenpipe or ActivityWatch running?",
            "events": 0,
            "sessions": 0,
        }

    all_events.sort(key=lambda e: e.timestamp)

    sessions = cluster_into_sessions(
        all_events,
        gap_minutes=config.session_gap_minutes,
        min_events=config.min_session_events,
    )

    store = LocalStore(config.data_dir)
    store.save_sessions(sessions)

    return {
        "status": "ok",
        "events_captured": len(all_events),
        "sessions_created": len(sessions),
        "time_range": f"last {hours} hours",
        "sessions": [
            {
                "time": f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
                "duration_min": round(s.total_duration_minutes, 1),
                "apps": s.apps_used[:5],
                "switches": s.context_switches,
                "friction": s.friction_level.value,
                "intent": s.inferred_intent or "(needs analysis)",
            }
            for s in sessions[:15]
        ],
    }


def handle_analyze(period: str = "today") -> dict[str, Any]:
    """Run LLM intent inference on unanalyzed sessions.

    Args:
        period: "today" or "yesterday".

    This is the UNDERSTAND step — the LLM reads your app/window context
    and infers what you were trying to accomplish in each session.
    Requires an API key (ANTHROPIC_API_KEY or OPENAI_API_KEY).
    """
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    d = date.today() if period == "today" else date.today() - timedelta(days=1)
    sessions = store.load_sessions(d)

    if not sessions:
        return {"status": "no_sessions", "message": f"No sessions for {period}. Run capture first."}

    to_analyze = [s for s in sessions if not s.inferred_intent or s.inferred_intent == "inference_failed"]

    if not to_analyze:
        return {
            "status": "already_analyzed",
            "total_sessions": len(sessions),
            "sessions": [
                {
                    "time": f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
                    "intent": s.inferred_intent,
                    "confidence": s.confidence,
                    "friction": s.friction_level.value,
                }
                for s in sessions
            ],
        }

    if not config.anthropic_api_key and not config.openai_api_key:
        return {
            "status": "no_api_key",
            "message": "Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable intent inference.",
            "unanalyzed_sessions": len(to_analyze),
        }

    try:
        client = config.get_llm_client()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    from workflowx.inference.intent import infer_intent

    analyzed = []

    async def _run():
        for session in to_analyze:
            updated, _ = await infer_intent(session, client, model=config.llm_model)
            for j, s in enumerate(sessions):
                if s.id == updated.id:
                    sessions[j] = updated
            analyzed.append(updated)

    _run_async(_run())
    store.save_sessions(sessions, d)

    return {
        "status": "ok",
        "analyzed": len(analyzed),
        "total_sessions": len(sessions),
        "sessions": [
            {
                "time": f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
                "intent": s.inferred_intent or "(failed)",
                "confidence": round(s.confidence, 2) if s.confidence else 0,
                "friction": s.friction_level.value,
                "apps": s.apps_used[:5],
            }
            for s in sessions
        ],
    }


def handle_get_sessions(period: str = "today") -> dict[str, Any]:
    """Get workflow sessions for a time period.

    Args:
        period: "today", "yesterday", "week", or "month"

    Returns sessions with intents, friction levels, apps, and time data.
    """
    sessions = _sessions_for_period(period)

    return {
        "period": period,
        "total_sessions": len(sessions),
        "total_minutes": round(sum(s.total_duration_minutes for s in sessions), 1),
        "sessions": [
            {
                "time": f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
                "date": s.start_time.strftime("%Y-%m-%d"),
                "duration_min": round(s.total_duration_minutes, 1),
                "intent": s.inferred_intent or "(unknown)",
                "friction": s.friction_level.value,
                "apps": s.apps_used[:5],
                "switches": s.context_switches,
            }
            for s in sessions
        ],
    }


def handle_get_friction(period: str = "week") -> dict[str, Any]:
    """Get high-friction workflows with cost estimates.

    Args:
        period: "today", "yesterday", "week", or "month"

    Returns only sessions with HIGH or CRITICAL friction, sorted by cost.
    Use this to find what's bleeding your time.
    """
    sessions = _sessions_for_period(period)
    from workflowx.models import FrictionLevel

    high_friction = [
        s for s in sessions
        if s.friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
    ]
    high_friction.sort(key=lambda s: s.total_duration_minutes, reverse=True)

    _, config = _get_store()
    rate = config.hourly_rate_usd

    return {
        "period": period,
        "high_friction_sessions": len(high_friction),
        "total_friction_minutes": round(sum(s.total_duration_minutes for s in high_friction), 1),
        "estimated_weekly_cost_usd": round(
            sum(s.total_duration_minutes for s in high_friction) / 60.0 * rate, 2
        ),
        "sessions": [
            {
                "intent": s.inferred_intent or "(unknown)",
                "duration_min": round(s.total_duration_minutes, 1),
                "friction": s.friction_level.value,
                "apps": s.apps_used[:5],
                "switches": s.context_switches,
                "cost_usd": round(s.total_duration_minutes / 60.0 * rate, 2),
            }
            for s in high_friction[:10]
        ],
    }


def handle_get_patterns() -> dict[str, Any]:
    """Detect recurring workflow patterns across the last 30 days.

    Finds workflows you repeat daily/weekly, ranks by total time invested.
    Shows whether each pattern's friction is improving, worsening, or stable.
    """
    sessions = _sessions_for_period("month")
    from workflowx.inference.patterns import detect_patterns

    patterns = detect_patterns(sessions)

    return {
        "patterns_found": len(patterns),
        "total_sessions_analyzed": len(sessions),
        "patterns": [
            {
                "intent": p.intent,
                "occurrences": p.occurrences,
                "avg_duration_min": round(p.avg_duration_minutes, 1),
                "total_time_min": round(p.total_time_invested_minutes, 1),
                "friction": p.most_common_friction.value,
                "trend": p.trend,
                "apps": p.apps_involved[:5],
            }
            for p in patterns
        ],
    }


def handle_get_trends() -> dict[str, Any]:
    """Get weekly friction trends for the last 4 weeks.

    Shows whether your workflow friction is getting better or worse over time.
    Tracks: friction ratio, context switches, and top friction sources.
    """
    sessions = _sessions_for_period("month")
    from workflowx.inference.patterns import compute_friction_trends

    trends = compute_friction_trends(sessions, num_weeks=4)

    trajectory = "stable"
    if len(trends) >= 2:
        diff = trends[-1].high_friction_ratio - trends[0].high_friction_ratio
        if diff > 0.1:
            trajectory = "worsening"
        elif diff < -0.1:
            trajectory = "improving"

    return {
        "weeks": len(trends),
        "trajectory": trajectory,
        "trends": [
            {
                "week": t.week_label,
                "sessions": t.total_sessions,
                "total_min": round(t.total_minutes, 1),
                "friction_ratio": round(t.high_friction_ratio, 3),
                "avg_switches": round(t.avg_switches_per_session, 1),
                "top_friction": t.top_friction_intents[:3],
            }
            for t in trends
        ],
    }


def handle_propose(top: int = 3) -> dict[str, Any]:
    """Generate AI replacement proposals for your highest-friction workflows.

    Args:
        top: Number of top friction workflows to propose replacements for (default: 3).

    This is the REPLACE step. The LLM reimagines each workflow from its goal,
    not just automating existing steps. Requires an API key.
    """
    from workflowx.config import load_config
    from workflowx.inference.intent import diagnose_workflow
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    # Load recent sessions with intents
    sessions = _sessions_for_period("week")
    analyzed = [s for s in sessions if s.inferred_intent]

    if not analyzed:
        return {
            "status": "no_data",
            "message": "No analyzed sessions. Run capture + analyze first.",
        }

    if not config.anthropic_api_key and not config.openai_api_key:
        # Return diagnoses without LLM proposals
        diagnoses = [diagnose_workflow(s, config.hourly_rate_usd) for s in analyzed]
        ranked = sorted(
            zip(diagnoses, analyzed),
            key=lambda pair: pair[0].automation_potential * pair[0].total_time_minutes,
            reverse=True,
        )[:top]

        return {
            "status": "diagnoses_only",
            "message": "No API key set. Showing friction diagnoses without AI proposals. Set ANTHROPIC_API_KEY for full proposals.",
            "diagnoses": [
                {
                    "intent": d.intent,
                    "time_min": round(d.total_time_minutes, 1),
                    "friction_points": d.friction_points[:3],
                    "automation_potential": round(d.automation_potential, 2),
                    "estimated_cost_usd": round(d.estimated_cost_usd, 2),
                    "recommended_approach": d.recommended_approach,
                }
                for d, _ in ranked
            ],
        }

    # Full LLM-powered proposals
    try:
        client = config.get_llm_client()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    from workflowx.replacement.engine import propose_replacement

    diagnoses = [diagnose_workflow(s, config.hourly_rate_usd) for s in analyzed]
    ranked = sorted(
        zip(diagnoses, analyzed),
        key=lambda pair: pair[0].automation_potential * pair[0].total_time_minutes,
        reverse=True,
    )[:top]

    proposals = []

    async def _run():
        for diag, session in ranked:
            proposal = await propose_replacement(diag, session, client, config.llm_model)
            proposals.append((diag, proposal))

    _run_async(_run())

    return {
        "status": "ok",
        "proposals": [
            {
                "intent": d.intent,
                "original": p.original_workflow,
                "proposed": p.proposed_workflow,
                "mechanism": p.mechanism,
                "time_before_min": round(d.total_time_minutes, 1),
                "time_after_min": round(p.estimated_time_after_minutes, 1),
                "savings_per_week_min": round(p.estimated_savings_minutes_per_week, 1),
                "confidence": round(p.confidence, 2),
                "new_tools_needed": p.requires_new_tools,
                "diagnosis_id": d.session_id,
            }
            for d, p in proposals
        ],
    }


def handle_adopt(intent: str, before_minutes: float) -> dict[str, Any]:
    """Mark a workflow replacement as adopted and start tracking ROI.

    Args:
        intent: The workflow intent to track (e.g., "email triage").
        before_minutes: How many minutes/week this workflow took BEFORE the replacement.

    This starts the MEASURE step. WorkflowX will compare your pre-adoption
    baseline against actual time spent going forward.
    """
    from workflowx.config import load_config
    from workflowx.measurement import create_outcome
    from workflowx.models import ReplacementProposal
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)

    proposal = ReplacementProposal(
        diagnosis_id=f"adopted_{intent.lower().replace(' ', '_')[:30]}",
        original_workflow=intent,
        proposed_workflow="(user-adopted replacement)",
        mechanism="User confirmed adoption via Claude",
    )

    outcome = create_outcome(proposal, before_minutes_per_week=before_minutes)
    store.save_outcome(outcome)

    return {
        "status": "tracking_started",
        "intent": intent,
        "baseline_minutes_per_week": before_minutes,
        "outcome_id": outcome.id,
        "message": f"Now tracking '{intent}'. Will measure actual time and compare against {before_minutes:.0f} min/week baseline.",
    }


def handle_measure(days: int = 7) -> dict[str, Any]:
    """Measure actual ROI of adopted replacements against recent sessions.

    Args:
        days: Days of recent data to measure against (default: 7).

    Compares pre-adoption baseline against actual time spent on each
    tracked workflow. Updates status: adopted (working), rejected (not working),
    or measuring (still gathering data).
    """
    from workflowx.config import load_config
    from workflowx.measurement import compute_roi_summary, measure_outcome
    from workflowx.storage import LocalStore

    config = load_config()
    store = LocalStore(config.data_dir)
    outcomes = store.load_outcomes()

    if not outcomes:
        return {
            "status": "no_outcomes",
            "message": "No outcomes tracked yet. Use adopt to start tracking a replacement.",
        }

    # Load recent sessions
    recent = []
    for i in range(days):
        d = date.today() - timedelta(days=i)
        recent.extend(store.load_sessions(d))

    active = [o for o in outcomes if o.status in ("measuring", "adopted")]
    for outcome in active:
        outcome = measure_outcome(outcome, recent, lookback_days=days)
        store.save_outcome(outcome)

    # Reload and summarize
    outcomes = store.load_outcomes()
    return compute_roi_summary(outcomes)


def handle_get_roi() -> dict[str, Any]:
    """Get ROI summary from replacement outcomes (no re-measurement).

    Returns current state of all tracked replacements:
    adoption rate, weekly/cumulative savings, per-outcome breakdown.
    """
    store, _ = _get_store()
    from workflowx.measurement import compute_roi_summary

    outcomes = store.load_outcomes()
    return compute_roi_summary(outcomes)


def handle_screenshot_dashboard(
    url: str = "http://localhost:7788",
    full_page: bool = True,
) -> dict[str, Any]:
    """Screenshot the WorkflowX dashboard using a headless browser.

    Returns the screenshot file path — view it without leaving Claude.
    Requires Playwright: pip install playwright && playwright install chromium

    Args:
        url: Dashboard URL to screenshot (default: http://localhost:7788).
             Make sure `workflowx serve` is running first.
        full_page: Capture full scrollable page, not just the viewport (default: True).

    Typical loop:
        1. workflowx serve  (in a separate terminal)
        2. ask Claude to edit the dashboard HTML
        3. call workflowx_screenshot — see the result inline without switching to Chrome
        4. iterate
    """
    import tempfile

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "status": "error",
            "message": (
                "Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=15000)
            tmp = tempfile.mktemp(suffix=".png", prefix="workflowx_screenshot_")
            page.screenshot(path=tmp, full_page=full_page)
            browser.close()

        return {
            "status": "ok",
            "screenshot_path": tmp,
            "url": url,
            "message": f"Screenshot saved to {tmp} — open this file to view the dashboard.",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": (
                f"Screenshot failed: {e}. "
                "Is the dashboard server running? Start it with: workflowx serve"
            ),
        }


def handle_diagnose_workflow(session_index: int = 0, period: str = "today") -> dict[str, Any]:
    """Deep-dive diagnosis of a specific workflow session.

    Args:
        session_index: Which session to diagnose (0 = most recent, 1 = next, etc.)
        period: Time period to look in.

    Returns detailed friction analysis: friction points, automation potential,
    estimated cost, and recommended approach.
    """
    sessions = _sessions_for_period(period)
    analyzed = [s for s in sessions if s.inferred_intent]

    if not analyzed:
        return {"status": "no_data", "message": "No analyzed sessions found."}

    # Sort by time, most recent first
    analyzed.sort(key=lambda s: s.start_time, reverse=True)

    if session_index >= len(analyzed):
        return {
            "status": "index_out_of_range",
            "message": f"Only {len(analyzed)} sessions available.",
            "available_sessions": len(analyzed),
        }

    session = analyzed[session_index]
    from workflowx.inference.intent import diagnose_workflow
    _, config = _get_store()

    diag = diagnose_workflow(session, config.hourly_rate_usd)

    return {
        "session": {
            "time": f"{session.start_time.strftime('%H:%M')}-{session.end_time.strftime('%H:%M')}",
            "date": session.start_time.strftime("%Y-%m-%d"),
            "intent": session.inferred_intent,
            "apps": session.apps_used,
            "switches": session.context_switches,
            "duration_min": round(session.total_duration_minutes, 1),
        },
        "diagnosis": {
            "friction_level": session.friction_level.value,
            "friction_points": diag.friction_points,
            "automation_potential": round(diag.automation_potential, 2),
            "estimated_cost_usd": round(diag.estimated_cost_usd, 2),
            "recommended_approach": diag.recommended_approach,
        },
    }


def handle_reject(intent: str, reason: str, notes: str = "") -> dict[str, Any]:
    """Reject a proposal with a reason and optional notes.

    Args:
        intent: The workflow intent to reject.
        reason: Rejection reason (too_complex, wrong_tools, inaccurate_savings, already_tried, not_relevant, other).
        notes: Optional notes explaining the rejection.

    Records the rejection in the outcomes store and updates any matching outcomes.
    """
    from workflowx.memory import ProposalHistory
    from workflowx.models import RejectionReason

    store, _ = _get_store()
    outcomes = store.load_outcomes()

    # Find matching outcome by intent similarity
    history = ProposalHistory(outcomes)
    similar = history.find_similar(intent, top_k=1)

    if not similar:
        return {
            "status": "no_match",
            "message": f"No matching proposal found for intent: {intent}",
            "similar_intents": [o.intent for o in outcomes[-5:]],
        }

    outcome = similar[0]

    # Update rejection info
    outcome.status = "rejected"
    try:
        outcome.rejection_reason = RejectionReason(reason)
    except ValueError:
        outcome.rejection_reason = RejectionReason.OTHER
        logger.warning(f"Invalid rejection reason: {reason}, using OTHER")

    outcome.rejection_notes = notes

    # Save back to store
    store.save_outcome(outcome)

    return {
        "status": "ok",
        "message": f"Proposal for '{outcome.intent}' rejected",
        "outcome_id": outcome.id,
        "rejection_reason": reason,
        "rejection_notes": notes,
    }


# ── Meeting Intelligence Stack Handlers ─────────────────────────────────────


def handle_meeting_debrief(
    raw_notes: str,
    attendees: str = "Unknown",
    meeting_date: str = "",
    push_to_gmail: bool = True,
    update_tasks: bool = True,
) -> dict[str, Any]:
    """Run a post-meeting debrief.

    Takes raw meeting notes and produces structured output:
    - What was discussed (3-5 bullets)
    - Commitments made (Wu vs them)
    - Action items with owners and deadlines
    - Follow-up email draft → Gmail Drafts

    Args:
        raw_notes: Raw meeting notes, any format (prose, bullets, partial transcript).
        attendees: Who was in the meeting (names/companies).
        meeting_date: ISO date string (default: today).
        push_to_gmail: If True, returns Gmail draft payload for Claude to push.
        update_tasks: If True, Wu's action items are appended to TASKS.md.
    """
    from workflowx.meeting.debrief_agent import run_debrief, save_debrief
    from workflowx.meeting.gmail_push import push_draft_to_gmail
    from workflowx.meeting.tasks_updater import append_actions_to_tasks

    result = run_debrief(
        raw_notes=raw_notes,
        attendees=attendees,
        meeting_date=meeting_date or None,
    )

    # Save debrief to filesystem
    saved_path = save_debrief(result, output_dir="debriefs")

    # Build response
    response: dict[str, Any] = {
        "status": "ok",
        "debrief_markdown": result.markdown,
        "actions_found": len(result.actions),
        "saved_to": saved_path,
    }

    # Gmail draft payload
    if push_to_gmail and result.email_draft:
        gmail_payload = push_draft_to_gmail(
            subject=result.email_draft.subject,
            body=result.email_draft.body,
        )
        response["gmail_draft"] = gmail_payload
        response["instruction"] = (
            "Call gmail_create_draft with the subject and body from gmail_draft.draft. "
            "Leave 'to' blank — Wu will fill in the recipient."
        )

    # TASKS.md update
    if update_tasks and result.actions:
        count = append_actions_to_tasks(
            actions=result.actions,
            meeting_context=f"{attendees} {result.meeting_date}",
        )
        response["tasks_appended"] = count

    return response


def handle_prebrief(
    attendee_emails: list[str],
    attendee_names: str = "",
    company: str = "",
    meeting_subject: str = "",
    meeting_time: str = "",
) -> dict[str, Any]:
    """Generate a pre-meeting brief.

    Returns a 1-page cheat sheet with:
    - Who's in the meeting (profiles)
    - Last touchpoint
    - Open items
    - Company pulse
    - Suggested agenda
    - One thing to say, one thing to ask

    To use fully: also call gmail_search_messages and google_drive_search
    with the context_gathering_instructions returned, then call this tool
    again with the gathered context.

    Args:
        attendee_emails: List of attendee email addresses.
        attendee_names: Comma-separated display names (optional).
        company: Company name (optional — auto-detected from email domain).
        meeting_subject: Calendar event subject.
        meeting_time: Meeting start time (ISO or human-readable).
    """
    from workflowx.meeting.prebrief.context_gatherer import (
        build_gmail_search_query,
        build_drive_search_query,
        build_web_research_queries,
        GATHER_CONTEXT_INSTRUCTIONS,
    )

    # Auto-detect company from email domain
    if not company:
        for email in attendee_emails:
            if "@" in email:
                domain = email.split("@")[-1].lower()
                if domain not in {"gmail.com", "yahoo.com", "hotmail.com", "accenture.com"}:
                    company = domain.split(".")[0].replace("-", " ").title()
                    break
        company = company or "Unknown"

    names = attendee_names or ", ".join(
        e.split("@")[0].replace(".", " ").title() for e in attendee_emails
    )

    gmail_query = build_gmail_search_query(attendee_emails)
    drive_query = build_drive_search_query(company, meeting_subject)
    web_queries = build_web_research_queries(company, names.split(","))

    web_query_text = "\n".join(f"   - {q}" for q in web_queries)
    gather_instructions = GATHER_CONTEXT_INSTRUCTIONS.format(
        gmail_query=gmail_query,
        max_emails=5,
        drive_query=drive_query,
        max_drive_docs=3,
        web_queries=web_query_text,
    )

    return {
        "status": "context_gathering_required",
        "meeting": {
            "attendees": attendee_emails,
            "names": names,
            "company": company,
            "subject": meeting_subject,
            "time": meeting_time,
        },
        "context_gathering_instructions": gather_instructions,
        "next_step": (
            "Follow context_gathering_instructions to collect Gmail, Drive, and web context. "
            "Then call workflowx_generate_brief with the gathered context."
        ),
    }


def handle_generate_brief(
    attendee_names: str,
    company: str,
    meeting_subject: str,
    meeting_time: str,
    email_context: str = "No prior email history found.",
    drive_context: str = "No relevant Drive documents found.",
    research_context: str = "No company information available.",
) -> dict[str, Any]:
    """Generate the pre-meeting brief once context has been gathered.

    Call this after workflowx_prebrief has guided you through context gathering.

    Args:
        attendee_names: Display names of attendees.
        company: Company name.
        meeting_subject: Meeting subject/title.
        meeting_time: Meeting start time.
        email_context: Formatted prior email context (from gmail_search_messages).
        drive_context: Formatted Drive doc context (from google_drive_search).
        research_context: Formatted web research context (from WebSearch).
    """
    from workflowx.meeting.prebrief.brief_agent import (
        MeetingInfo, MeetingContext, generate_brief, save_brief
    )

    meeting = MeetingInfo(
        event_id="manual",
        title=meeting_subject,
        start_time=meeting_time,
        end_time="",
        attendees=attendee_names.split(","),
    )
    context = MeetingContext(
        email_context=email_context,
        drive_context=drive_context,
        research_context=research_context,
        attendee_names=attendee_names,
        company=company,
    )

    brief_md = generate_brief(meeting, context)
    saved_path = save_brief(meeting, brief_md)

    return {
        "status": "ok",
        "brief_markdown": brief_md,
        "saved_to": saved_path,
    }


def handle_sidebar_check(
    attendee_emails: list[str],
    meeting_description: str = "",
) -> dict[str, Any]:
    """Check if real-time sidebar can activate for this meeting.

    Returns consent status and instructions. Internal meetings only.
    External meetings require AI disclosure in the meeting description.

    Args:
        attendee_emails: List of attendee email addresses.
        meeting_description: Calendar event description (checked for AI disclosure).
    """
    from workflowx.meeting.sidebar.consent_guard import ConsentGuard

    guard = ConsentGuard()
    result = guard.check(
        attendees=attendee_emails,
        meeting_description=meeting_description,
    )

    return {
        "approved": result.approved,
        "reason": result.reason,
        "external_attendees": result.external_attendees,
        "can_override": result.can_override,
        "override_instructions": (
            "To enable sidebar for external meetings: add 'AI may assist' "
            "to the calendar event description AND inform attendees at meeting start."
        ) if not result.approved else None,
    }


# ── MCP Server Setup ─────────────────────────────────────────


TOOL_REGISTRY = {
    # ── OBSERVE ──
    "workflowx_status": {
        "handler": handle_status,
        "description": "Check WorkflowX health: capture sources, data counts, config",
    },
    "workflowx_capture": {
        "handler": handle_capture,
        "description": "Capture fresh events from Screenpipe, cluster into workflow sessions",
    },
    "workflowx_analyze": {
        "handler": handle_analyze,
        "description": "Run LLM intent inference on unanalyzed sessions (requires API key)",
    },
    "workflowx_sessions": {
        "handler": handle_get_sessions,
        "description": "Get workflow sessions for a time period (today/yesterday/week/month)",
    },
    # ── UNDERSTAND ──
    "workflowx_friction": {
        "handler": handle_get_friction,
        "description": "Get high-friction workflows with cost estimates",
    },
    "workflowx_patterns": {
        "handler": handle_get_patterns,
        "description": "Detect recurring workflow patterns across the last 30 days",
    },
    "workflowx_trends": {
        "handler": handle_get_trends,
        "description": "Get weekly friction trends (is friction improving or worsening?)",
    },
    "workflowx_diagnose": {
        "handler": handle_diagnose_workflow,
        "description": "Deep-dive friction diagnosis of a specific session",
    },
    "workflowx_screenshot": {
        "handler": handle_screenshot_dashboard,
        "description": "Screenshot the live dashboard — see it without switching to Chrome",
    },
    # ── REPLACE ──
    "workflowx_propose": {
        "handler": handle_propose,
        "description": "Generate AI replacement proposals for highest-friction workflows",
    },
    "workflowx_adopt": {
        "handler": handle_adopt,
        "description": "Adopt a replacement and start tracking ROI (before/after measurement)",
    },
    "workflowx_reject": {
        "handler": handle_reject,
        "description": "Reject a proposal with a reason",
    },
    # ── MEASURE ──
    "workflowx_measure": {
        "handler": handle_measure,
        "description": "Re-measure ROI of adopted replacements against recent sessions",
    },
    "workflowx_roi": {
        "handler": handle_get_roi,
        "description": "Get ROI summary from adopted workflow replacements",
    },
    # ── MEETING INTELLIGENCE STACK ──
    "workflowx_meeting_debrief": {
        "handler": handle_meeting_debrief,
        "description": (
            "Post-meeting debrief: raw notes → structured output + Gmail draft + TASKS.md update. "
            "Phase 1 of Meeting Intelligence Stack."
        ),
    },
    "workflowx_prebrief": {
        "handler": handle_prebrief,
        "description": (
            "Start pre-meeting brief generation. Returns context-gathering instructions "
            "for Gmail/Drive/web. Then call workflowx_generate_brief with gathered context."
        ),
    },
    "workflowx_generate_brief": {
        "handler": handle_generate_brief,
        "description": (
            "Generate 1-page pre-meeting cheat sheet from gathered context. "
            "Call after workflowx_prebrief has guided context collection."
        ),
    },
    "workflowx_sidebar_check": {
        "handler": handle_sidebar_check,
        "description": (
            "Check if real-time meeting sidebar can activate. "
            "Internal meetings only — returns consent status and instructions."
        ),
    },
}


def create_mcp_server():
    """Create and configure the MCP server with all 13 tools.

    Uses FastMCP for tool registration. Each tool maps to a handler
    in the observe→understand→replace→measure loop.
    """
    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("workflowx")

        # ── OBSERVE ──

        @mcp.tool()
        def workflowx_status() -> str:
            """Check WorkflowX health: capture sources, data counts, config."""
            return json.dumps(handle_status(), default=str)

        @mcp.tool()
        def workflowx_capture(hours: int = 8) -> str:
            """Capture fresh events from Screenpipe, cluster into sessions."""
            return json.dumps(handle_capture(hours), default=str)

        @mcp.tool()
        def workflowx_analyze(period: str = "today") -> str:
            """Run LLM intent inference on unanalyzed sessions."""
            return json.dumps(handle_analyze(period), default=str)

        @mcp.tool()
        def workflowx_sessions(period: str = "today") -> str:
            """Get workflow sessions for a time period."""
            return json.dumps(handle_get_sessions(period), default=str)

        # ── UNDERSTAND ──

        @mcp.tool()
        def workflowx_friction(period: str = "week") -> str:
            """Get high-friction workflows with cost estimates."""
            return json.dumps(handle_get_friction(period), default=str)

        @mcp.tool()
        def workflowx_patterns() -> str:
            """Detect recurring workflow patterns across 30 days."""
            return json.dumps(handle_get_patterns(), default=str)

        @mcp.tool()
        def workflowx_trends() -> str:
            """Get weekly friction trends."""
            return json.dumps(handle_get_trends(), default=str)

        @mcp.tool()
        def workflowx_diagnose(session_index: int = 0, period: str = "today") -> str:
            """Deep-dive friction diagnosis of a specific session."""
            return json.dumps(handle_diagnose_workflow(session_index, period), default=str)

        @mcp.tool()
        def workflowx_screenshot(url: str = "http://localhost:7788", full_page: bool = True) -> str:
            """Screenshot the live dashboard — see it without switching to Chrome.

            Returns a file path to the PNG screenshot. Requires `workflowx serve` running.
            Use this to review dashboard edits without leaving the Claude interface.
            """
            return json.dumps(handle_screenshot_dashboard(url, full_page), default=str)

        # ── REPLACE ──

        @mcp.tool()
        def workflowx_propose(top: int = 3) -> str:
            """Generate AI replacement proposals for top friction workflows."""
            return json.dumps(handle_propose(top), default=str)

        @mcp.tool()
        def workflowx_adopt(intent: str, before_minutes: float) -> str:
            """Adopt a replacement and start tracking ROI."""
            return json.dumps(handle_adopt(intent, before_minutes), default=str)

        @mcp.tool()
        def workflowx_reject(intent: str, reason: str, notes: str = "") -> str:
            """Reject a proposal with a reason. Provide the intent and a reason."""
            return json.dumps(handle_reject(intent, reason, notes), default=str)

        # ── MEASURE ──

        @mcp.tool()
        def workflowx_measure(days: int = 7) -> str:
            """Re-measure ROI of adopted replacements against recent data."""
            return json.dumps(handle_measure(days), default=str)

        @mcp.tool()
        def workflowx_roi() -> str:
            """Get ROI from adopted replacements."""
            return json.dumps(handle_get_roi(), default=str)

        # ── MEETING INTELLIGENCE STACK ──

        @mcp.tool()
        def workflowx_meeting_debrief(
            raw_notes: str,
            attendees: str = "Unknown",
            meeting_date: str = "",
            push_to_gmail: bool = True,
            update_tasks: bool = True,
        ) -> str:
            """Post-meeting debrief: raw notes → structured output + Gmail draft + TASKS.md.

            Produces: what was discussed, commitments, action items, follow-up email.
            Gmail draft is ready to send. Wu's action items go into TASKS.md.
            """
            return json.dumps(
                handle_meeting_debrief(raw_notes, attendees, meeting_date, push_to_gmail, update_tasks),
                default=str,
            )

        @mcp.tool()
        def workflowx_prebrief(
            attendee_emails: list[str],
            attendee_names: str = "",
            company: str = "",
            meeting_subject: str = "",
            meeting_time: str = "",
        ) -> str:
            """Start pre-meeting brief. Returns instructions for Gmail/Drive/web context gathering.

            Step 1 of 2: call this to get context-gathering instructions.
            Step 2 of 2: gather context, then call workflowx_generate_brief.
            """
            return json.dumps(
                handle_prebrief(attendee_emails, attendee_names, company, meeting_subject, meeting_time),
                default=str,
            )

        @mcp.tool()
        def workflowx_generate_brief(
            attendee_names: str,
            company: str,
            meeting_subject: str,
            meeting_time: str,
            email_context: str = "No prior email history found.",
            drive_context: str = "No relevant Drive documents found.",
            research_context: str = "No company information available.",
        ) -> str:
            """Generate 1-page pre-meeting cheat sheet from gathered context.

            Call after workflowx_prebrief has guided Gmail/Drive/web context collection.
            Returns brief_markdown (save or display) and saved_to path.
            """
            return json.dumps(
                handle_generate_brief(
                    attendee_names, company, meeting_subject, meeting_time,
                    email_context, drive_context, research_context,
                ),
                default=str,
            )

        @mcp.tool()
        def workflowx_sidebar_check(
            attendee_emails: list[str],
            meeting_description: str = "",
        ) -> str:
            """Check if real-time meeting sidebar can activate for this meeting.

            Internal meetings only. External meetings require 'AI may assist' disclosure.
            Returns approved flag, reason, and override instructions if blocked.
            """
            return json.dumps(
                handle_sidebar_check(attendee_emails, meeting_description),
                default=str,
            )

        return mcp

    except ImportError:
        logger.warning("fastmcp_not_installed", msg="Install mcp package: pip install 'workflowx[mcp]'")
        return None


def run_mcp_stdio():
    """Run MCP server on stdio (for Claude Desktop / Claude Code integration)."""
    server = create_mcp_server()
    if server is None:
        raise RuntimeError(
            "MCP server requires the 'mcp' package. "
            "Install with: pip install 'workflowx[mcp]'"
        )
    server.run()


def run_mcp_http(host: str = "localhost", port: int = 8765):
    """Run MCP server on HTTP (for remote or web-based MCP clients)."""
    server = create_mcp_server()
    if server is None:
        raise RuntimeError("MCP server requires the 'mcp' package.")
    server.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    run_mcp_stdio()
