"""Synthetic data generator + full pipeline demo.

This is the proof-of-life module. When someone clones WorkflowX and runs
`workflowx demo`, they should see the full pipeline in action within 10 seconds:

  Synthetic capture → cluster → infer intent → detect patterns →
  compute trends → diagnose → propose replacements → measure ROI → dashboard

No Screenpipe needed. No LLM API key needed. Pure local demonstration.

The synthetic data is realistic: it models a knowledge worker's week with
recognizable patterns (morning email, deep coding, afternoon meetings,
competitive research, context-switching admin work).
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence

import structlog

from workflowx.models import (
    EventSource,
    FrictionLevel,
    RawEvent,
    ReplacementOutcome,
    ReplacementProposal,
    WorkflowDiagnosis,
    WorkflowSession,
)

logger = structlog.get_logger()

# ── Workflow Archetypes ──────────────────────────────────────
# Each archetype defines a realistic workflow pattern a knowledge worker does.
# These become the sessions. Some are high-friction (many apps, rapid switching).
# Some are low-friction (deep focus, single app).

ARCHETYPES = [
    {
        "intent": "morning email triage",
        "apps": ["Gmail", "Slack", "Calendar", "Notion"],
        "duration_range": (15, 45),
        "switches_per_min": 2.5,
        "friction": "high",
        "frequency": 5,  # times per week
        "time_range": (8, 10),  # hour of day
    },
    {
        "intent": "deep coding session",
        "apps": ["VSCode", "Terminal", "Chrome"],
        "duration_range": (60, 180),
        "switches_per_min": 0.3,
        "friction": "low",
        "frequency": 5,
        "time_range": (10, 13),
    },
    {
        "intent": "competitive research and analysis",
        "apps": ["Chrome", "Notion", "Google Sheets", "ChatGPT", "Slack"],
        "duration_range": (30, 75),
        "switches_per_min": 3.2,
        "friction": "critical",
        "frequency": 3,
        "time_range": (14, 16),
    },
    {
        "intent": "PR review and code feedback",
        "apps": ["GitHub", "VSCode", "Slack", "Terminal"],
        "duration_range": (20, 50),
        "switches_per_min": 1.8,
        "friction": "high",
        "frequency": 4,
        "time_range": (11, 14),
    },
    {
        "intent": "afternoon team standup + sync",
        "apps": ["Zoom", "Notion", "Slack"],
        "duration_range": (15, 30),
        "switches_per_min": 0.8,
        "friction": "medium",
        "frequency": 5,
        "time_range": (14, 15),
    },
    {
        "intent": "writing documentation",
        "apps": ["Notion", "VSCode", "Chrome"],
        "duration_range": (30, 90),
        "switches_per_min": 0.4,
        "friction": "low",
        "frequency": 2,
        "time_range": (15, 17),
    },
    {
        "intent": "expense reports and admin tasks",
        "apps": ["Expensify", "Gmail", "Google Sheets", "Slack", "Chrome"],
        "duration_range": (20, 60),
        "switches_per_min": 4.0,
        "friction": "critical",
        "frequency": 1,
        "time_range": (16, 18),
    },
    {
        "intent": "customer support ticket triage",
        "apps": ["Zendesk", "Slack", "Notion", "Chrome"],
        "duration_range": (25, 50),
        "switches_per_min": 2.2,
        "friction": "high",
        "frequency": 3,
        "time_range": (9, 11),
    },
    {
        "intent": "weekly metrics dashboard review",
        "apps": ["Looker", "Google Sheets", "Slack", "Notion"],
        "duration_range": (20, 40),
        "switches_per_min": 1.5,
        "friction": "medium",
        "frequency": 1,
        "time_range": (10, 12),
    },
    {
        "intent": "design review in Figma",
        "apps": ["Figma", "Slack", "Notion"],
        "duration_range": (30, 60),
        "switches_per_min": 0.6,
        "friction": "low",
        "frequency": 2,
        "time_range": (13, 15),
    },
]


def _make_id(prefix: str, *parts) -> str:
    """Deterministic ID from parts."""
    raw = "_".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.md5(raw.encode()).hexdigest()[:10]}"


def _friction_from_str(s: str) -> FrictionLevel:
    return {
        "low": FrictionLevel.LOW,
        "medium": FrictionLevel.MEDIUM,
        "high": FrictionLevel.HIGH,
        "critical": FrictionLevel.CRITICAL,
    }[s]


# ── Session Generator ────────────────────────────────────────


def generate_synthetic_sessions(
    num_days: int = 14,
    base_date: date | None = None,
    seed: int = 42,
) -> list[WorkflowSession]:
    """Generate realistic synthetic workflow sessions across multiple days.

    Returns sessions that look like a real knowledge worker's 2-week history.
    Includes variation: not every archetype fires every day, durations vary,
    friction levels occasionally shift (some days are worse than others).
    """
    rng = random.Random(seed)
    base = base_date or (date.today() - timedelta(days=num_days))
    sessions: list[WorkflowSession] = []

    for day_offset in range(num_days):
        current_date = base + timedelta(days=day_offset)

        # Skip weekends (roughly)
        if current_date.weekday() >= 5:
            continue

        for arch in ARCHETYPES:
            # Probabilistic: does this archetype fire today?
            weekly_freq = arch["frequency"]
            daily_prob = weekly_freq / 5.0  # 5 work days
            if rng.random() > daily_prob:
                continue

            # Generate session
            duration = rng.randint(*arch["duration_range"])
            hour = rng.randint(*arch["time_range"])
            minute = rng.randint(0, 45)

            start = datetime(current_date.year, current_date.month, current_date.day, hour, minute)
            end = start + timedelta(minutes=duration)

            switches = int(duration * arch["switches_per_min"] * rng.uniform(0.7, 1.3))

            # Friction can vary day to day
            base_friction = arch["friction"]
            if rng.random() < 0.15:  # 15% chance of friction shift
                levels = ["low", "medium", "high", "critical"]
                idx = levels.index(base_friction)
                shift = rng.choice([-1, 1])
                idx = max(0, min(3, idx + shift))
                base_friction = levels[idx]

            # Trend: later days might be slightly worse (to show worsening trend)
            if day_offset > num_days * 0.7 and arch["friction"] in ("high", "critical"):
                if rng.random() < 0.3:
                    base_friction = "critical"

            # Generate synthetic events
            events = _generate_events(arch, start, duration, rng)

            # Confidence varies
            confidence = rng.uniform(0.65, 0.95)

            # Friction details
            friction_points = _generate_friction_details(arch, rng)

            session = WorkflowSession(
                id=_make_id("sess", current_date, hour, arch["intent"]),
                start_time=start,
                end_time=end,
                events=events,
                inferred_intent=arch["intent"],
                confidence=round(confidence, 2),
                apps_used=arch["apps"],
                total_duration_minutes=float(duration),
                context_switches=switches,
                friction_level=_friction_from_str(base_friction),
                friction_details="; ".join(friction_points),
                user_validated=rng.random() < 0.4,
                user_label=arch["intent"] if rng.random() < 0.3 else "",
            )
            sessions.append(session)

    sessions.sort(key=lambda s: s.start_time)

    logger.info(
        "synthetic_sessions_generated",
        count=len(sessions),
        days=num_days,
    )
    return sessions


def _generate_events(
    archetype: dict,
    start: datetime,
    duration_min: int,
    rng: random.Random,
) -> list[RawEvent]:
    """Generate synthetic raw events for a session."""
    events = []
    num_events = min(20, max(3, int(duration_min * archetype["switches_per_min"])))

    for i in range(num_events):
        offset_sec = int((duration_min * 60 / num_events) * i)
        ts = start + timedelta(seconds=offset_sec)
        app = rng.choice(archetype["apps"])

        events.append(RawEvent(
            timestamp=ts,
            source=EventSource.SCREENPIPE,
            app_name=app,
            window_title=f"{app} — {archetype['intent']}",
            duration_seconds=float(rng.randint(10, 120)),
        ))

    return events


def _generate_friction_details(archetype: dict, rng: random.Random) -> list[str]:
    """Generate realistic friction point descriptions."""
    friction_library = {
        "high": [
            "repeated context switches between chat and work",
            "waiting for slow page loads",
            "searching for information across multiple tools",
            "copy-pasting data between apps",
            "re-reading same content after interruption",
        ],
        "critical": [
            "lost context after interruption — restarted task from scratch",
            "spent 10+ minutes finding the right document",
            "manual data entry that could be automated",
            "switching between 5+ apps for a single decision",
            "re-doing work because data was in wrong format",
        ],
        "medium": [
            "minor context switch overhead",
            "waiting for tool to load",
            "scrolling through long documents",
        ],
        "low": [
            "smooth flow, minimal interruptions",
        ],
    }

    level = archetype["friction"]
    options = friction_library.get(level, ["no friction noted"])
    k = min(len(options), rng.randint(1, 3))
    return rng.sample(options, k)


# ── Replacement Proposals ────────────────────────────────────


SYNTHETIC_REPLACEMENTS = {
    "morning email triage": {
        "proposed": "AI email classifier with priority inbox + auto-drafted responses",
        "mechanism": "LLM scans incoming email, classifies into action/FYI/delegate, "
                     "drafts responses for action items, surfaces only decisions to you",
        "time_after": 5,
        "tools": ["Agenticom email agent", "LLM classifier"],
    },
    "competitive research and analysis": {
        "proposed": "Automated competitor monitoring agent with weekly digest",
        "mechanism": "Agent scrapes competitor sites, pricing pages, job posts, and "
                     "social media daily. Produces a structured diff report. You review "
                     "the digest instead of doing manual research.",
        "time_after": 10,
        "tools": ["Agenticom scraping agent", "Notion API"],
    },
    "expense reports and admin tasks": {
        "proposed": "Receipt scanner + auto-categorized expense agent",
        "mechanism": "Photo of receipt → OCR → auto-categorize → draft expense report. "
                     "You approve the batch once per week instead of manual entry.",
        "time_after": 5,
        "tools": ["OCR agent", "Expensify API"],
    },
    "PR review and code feedback": {
        "proposed": "AI pre-review agent that surfaces only meaningful review items",
        "mechanism": "Agent runs static analysis, checks test coverage, reviews for "
                     "patterns/anti-patterns, and summarizes changes. You review the "
                     "summary + 2-3 key decisions instead of reading every diff.",
        "time_after": 10,
        "tools": ["Claude Code", "GitHub Actions"],
    },
    "customer support ticket triage": {
        "proposed": "Auto-triage + draft-response agent with human approval",
        "mechanism": "Agent classifies tickets (P1-P4), matches to KB articles, drafts "
                     "response. P3/P4 auto-resolve with canned response. P1/P2 surface "
                     "to you with draft + context.",
        "time_after": 8,
        "tools": ["Zendesk API agent", "KB search agent"],
    },
}


def generate_synthetic_proposals(
    sessions: Sequence[WorkflowSession],
) -> list[tuple[WorkflowDiagnosis, ReplacementProposal]]:
    """Generate synthetic replacement proposals for high-friction workflows."""
    from workflowx.inference.intent import diagnose_workflow

    results = []
    seen_intents: set[str] = set()

    for session in sessions:
        intent = session.inferred_intent
        if intent not in SYNTHETIC_REPLACEMENTS or intent in seen_intents:
            continue
        seen_intents.add(intent)

        diag = diagnose_workflow(session, hourly_rate_usd=75.0)
        repl = SYNTHETIC_REPLACEMENTS[intent]

        proposal = ReplacementProposal(
            diagnosis_id=diag.session_id,
            original_workflow=f"{intent} ({diag.total_time_minutes:.0f}min, "
                            f"friction: {', '.join(diag.friction_points[:2])})",
            proposed_workflow=repl["proposed"],
            mechanism=repl["mechanism"],
            estimated_time_after_minutes=float(repl["time_after"]),
            estimated_savings_minutes_per_week=max(
                0, diag.total_time_minutes - repl["time_after"]
            ),
            confidence=0.82,
            requires_new_tools=repl["tools"],
        )
        results.append((diag, proposal))

    return results


def generate_synthetic_outcomes(
    proposals: Sequence[tuple[WorkflowDiagnosis, ReplacementProposal]],
    seed: int = 42,
) -> list[ReplacementOutcome]:
    """Generate synthetic outcomes showing mixed adoption results."""
    rng = random.Random(seed)
    outcomes = []

    for i, (diag, proposal) in enumerate(proposals):
        # Some adopted, some rejected, some still measuring
        roll = rng.random()
        if roll < 0.5:
            status = "adopted"
            after = proposal.estimated_time_after_minutes * rng.uniform(0.8, 1.5)
            savings = diag.total_time_minutes - after
            weeks = rng.randint(2, 6)
        elif roll < 0.75:
            status = "rejected"
            after = diag.total_time_minutes * rng.uniform(0.9, 1.2)
            savings = diag.total_time_minutes - after
            weeks = rng.randint(1, 3)
        else:
            status = "measuring"
            after = 0.0
            savings = 0.0
            weeks = 0

        outcome = ReplacementOutcome(
            id=_make_id("out", proposal.diagnosis_id),
            proposal_id=proposal.diagnosis_id,
            intent=diag.intent,
            adopted=status == "adopted",
            adopted_date=datetime.now() - timedelta(weeks=weeks) if status != "measuring" else None,
            before_minutes_per_week=round(diag.total_time_minutes, 1),
            after_minutes_per_week=round(after, 1),
            actual_savings_minutes=round(savings, 1),
            cumulative_savings_minutes=round(savings * weeks, 1),
            weeks_tracked=weeks,
            status=status,
        )
        outcomes.append(outcome)

    return outcomes


# ── Full Demo Pipeline ────────────────────────────────────────


def run_demo_pipeline(
    output_dir: Path | None = None,
    num_days: int = 14,
    seed: int = 42,
) -> dict:
    """Run the complete WorkflowX pipeline on synthetic data.

    Returns paths to all generated artifacts.
    """
    from workflowx.dashboard import generate_dashboard_html
    from workflowx.inference.patterns import (
        compute_friction_trends,
        detect_patterns,
    )
    from workflowx.measurement import compute_roi_summary

    output_dir = output_dir or Path(".")

    # 1. Generate synthetic sessions
    sessions = generate_synthetic_sessions(num_days=num_days, seed=seed)

    # 2. Detect patterns
    patterns = detect_patterns(sessions, min_occurrences=2)

    # 3. Compute friction trends
    trends = compute_friction_trends(sessions, num_weeks=4)

    # 4. Generate proposals
    proposals = generate_synthetic_proposals(sessions)

    # 5. Generate outcomes
    outcomes = generate_synthetic_outcomes(proposals, seed=seed)

    # 6. Generate dashboard HTML
    html = generate_dashboard_html(
        trends=trends,
        patterns=patterns,
        outcomes=outcomes,
        hourly_rate=75.0,
    )
    dashboard_path = output_dir / "workflowx-demo-dashboard.html"
    dashboard_path.write_text(html)

    # 7. Compute ROI summary
    roi = compute_roi_summary(outcomes)

    return {
        "sessions": len(sessions),
        "patterns": len(patterns),
        "trends": len(trends),
        "proposals": len(proposals),
        "outcomes": len(outcomes),
        "dashboard_path": str(dashboard_path),
        "roi": roi,
        "top_patterns": [
            {"intent": p.intent, "occurrences": p.occurrences, "total_min": p.total_time_invested_minutes}
            for p in patterns[:5]
        ],
        "friction_trajectory": "worsening" if len(trends) >= 2 and trends[-1].high_friction_ratio > trends[0].high_friction_ratio + 0.05 else
                              "improving" if len(trends) >= 2 and trends[-1].high_friction_ratio < trends[0].high_friction_ratio - 0.05 else
                              "stable",
    }
