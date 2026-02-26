"""WorkflowX background daemon.

Runs the full pipeline on a smart schedule — invisible unless something needs
your attention, then it tells you exactly what to do.

  health:  every 5 min        — Screenpipe liveness; notifies if down
  capture: 12:55 + 17:55 WD  — Roll up last 4h of Screenpipe events
  analyze: 13:00 + 18:00 WD  — LLM intent inference; event-triggers propose
  propose: event-driven       — Notifies when HIGH/CRITICAL sessions need attention
  measure: 07:00 daily        — Adaptive ROI measurement (weekly→monthly cadence)
  brief:   08:30 WD           — Morning summary: yesterday's friction + pending actions

Architecture: one asyncio process, one coroutine per job loop.
All pure logic (scheduling, trigger decisions, message formatting) is isolated
in plain functions with no I/O — fully unit-testable without asyncio.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from workflowx.models import FrictionLevel, ReplacementOutcome, WorkflowSession

logger = structlog.get_logger()

# ── Schedule constants ────────────────────────────────────────────────────────

CAPTURE_TIMES = [time(12, 55), time(17, 55), time(22, 55)]  # 5 min before analyze
ANALYZE_TIMES = [time(13, 0),  time(18, 0),  time(23, 0)]   # +late evening slot
MEASURE_TIMES = [time(7, 0)]
BRIEF_TIMES   = [time(8, 30)]
HEALTH_INTERVAL_SECONDS = 300  # 5 minutes


# ── Pure scheduling logic (no I/O — fully unit-testable) ─────────────────────


def next_fire_time(
    times: list[time],
    weekdays_only: bool = False,
    now: datetime | None = None,
) -> datetime:
    """Return the next datetime any of the given clock times will fire.

    Scans up to 8 days forward so we always find Monday morning from Friday.
    Raises RuntimeError if no time found (shouldn't happen in practice).
    """
    now = now or datetime.now()
    for day_offset in range(8):
        d = now.date() + timedelta(days=day_offset)
        if weekdays_only and d.weekday() >= 5:   # 5=Sat, 6=Sun
            continue
        for t in sorted(times):
            dt = datetime.combine(d, t)
            if dt > now:
                return dt
    raise RuntimeError(f"No fire time found in next 8 days for {times}")


def seconds_until(target: datetime, now: datetime | None = None) -> float:
    """Seconds until target datetime. Returns 0.0 if target is in the past."""
    now = now or datetime.now()
    return max(0.0, (target - now).total_seconds())


def should_measure(
    outcome: ReplacementOutcome,
    now: datetime | None = None,
) -> bool:
    """Adaptive measure cadence: weekly for first 30 days, monthly after.

    Uses `weeks_tracked` (how many times measured so far) vs expected count
    given the outcome's age.  No extra model fields required.

      < 7 days old       → skip (no signal yet)
      7–30 days old      → weekly: expect 1 measurement per 7 days
      > 30 days old      → monthly: expect 4 + 1 per additional 30 days
    """
    now = now or datetime.now()
    if outcome.adopted_date is None:
        return False

    age_days = (now.date() - outcome.adopted_date.date()).days
    if age_days < 7:
        return False

    if age_days <= 30:
        expected = age_days // 7
    else:
        expected = 4 + (age_days - 30) // 30

    return outcome.weeks_tracked < expected


def should_propose(
    session: WorkflowSession,
    proposed_session_ids: dict[str, str],
    now: datetime | None = None,
) -> bool:
    """Event-driven proposal trigger.

    Returns True when a session warrants a replacement notification:
      - Friction is HIGH or CRITICAL
      - Intent has been inferred (analysis ran)
      - Session hasn't already triggered a notification (per-ID dedup)
    """
    now = now or datetime.now()  # noqa: F841 — reserved for future TTL logic
    if session.friction_level not in (FrictionLevel.HIGH, FrictionLevel.CRITICAL):
        return False
    if not session.inferred_intent:
        return False
    if session.id in proposed_session_ids:
        return False
    return True


def format_morning_brief(
    sessions: list[WorkflowSession],
    outcomes: list[ReplacementOutcome],
    pending_questions: int,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Format a concise morning brief as (title, message) for notification.

    Only counts *yesterday's* sessions — today's day hasn't started yet.
    """
    now = now or datetime.now()
    yesterday = now.date() - timedelta(days=1)
    yesterday_sessions = [s for s in sessions if s.start_time.date() == yesterday]

    critical = sum(1 for s in yesterday_sessions if s.friction_level == FrictionLevel.CRITICAL)
    high     = sum(1 for s in yesterday_sessions if s.friction_level == FrictionLevel.HIGH)
    measuring = sum(1 for o in outcomes if o.status == "measuring")

    parts: list[str] = []
    if critical:
        parts.append(f"{critical} CRITICAL")
    if high:
        parts.append(f"{high} HIGH friction")
    if pending_questions:
        parts.append(f"{pending_questions} pending validation{'s' if pending_questions != 1 else ''}")
    if measuring:
        parts.append(f"{measuring} replacement{'s' if measuring != 1 else ''} in progress")

    if not yesterday_sessions:
        title = "WorkflowX Morning Brief"
        msg   = "No data yet — run 'workflowx capture' to start."
    else:
        n     = len(yesterday_sessions)
        title = f"WorkflowX — {n} session{'s' if n != 1 else ''} yesterday"
        msg   = " | ".join(parts) if parts else "All sessions low friction ✓"

    return title, msg


# ── Daemon state ──────────────────────────────────────────────────────────────


class JobState(BaseModel):
    last_run:      datetime | None = None
    next_run:      datetime | None = None
    last_status:   str = "pending"   # "pending" | "ok" | "error" | "skipped"
    error_message: str = ""


class DaemonState(BaseModel):
    started_at:           datetime            = Field(default_factory=datetime.now)
    jobs:                 dict[str, JobState] = Field(default_factory=dict)
    proposed_session_ids: dict[str, str]      = Field(default_factory=dict)
    screenpipe_healthy:   bool                = True
    screenpipe_last_checked: datetime | None  = None


def read_state(path: Path) -> DaemonState:
    """Load daemon state from disk, returning a fresh default on any error."""
    if path.exists():
        try:
            return DaemonState.model_validate_json(path.read_text())
        except Exception:
            pass
    return DaemonState()


def write_state(state: DaemonState, path: Path) -> None:
    """Persist daemon state to disk."""
    path.write_text(state.model_dump_json(indent=2))


# ── PID management ────────────────────────────────────────────────────────────


def write_pid(path: Path) -> None:
    """Write the current process PID to a file."""
    path.write_text(str(os.getpid()))


def read_pid(path: Path) -> int | None:
    """Read PID from file. Returns None if file missing or not an integer."""
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def is_daemon_running(pid_path: Path) -> bool:
    """Check if a daemon is running by probing the PID from the pid file.

    Uses signal 0 — existence check, no actual signal sent.
    """
    pid = read_pid(pid_path)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # Process exists but we can't signal it


# ── macOS launchd integration ─────────────────────────────────────────────────

PLIST_LABEL = "com.workflowx.daemon"
PLIST_PATH  = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _find_workflowx_bin() -> str:
    """Locate the workflowx executable (venv-aware)."""
    import shutil
    found = shutil.which("workflowx")
    if found:
        return found
    # Fallback: same bin directory as the running Python interpreter
    candidate = Path(sys.executable).parent / "workflowx"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError(
        "Cannot find workflowx binary. "
        "Make sure it is installed: pip install -e ."
    )


def generate_plist(log_path: Path) -> str:
    """Generate a launchd plist XML string for the WorkflowX daemon."""
    workflowx_bin = _find_workflowx_bin()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Capture key environment variables so the daemon inherits the user's env
    env_keys = [
        "PATH", "HOME",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "WORKFLOWX_DATA_DIR", "WORKFLOWX_HOURLY_RATE",
    ]
    env_entries: list[str] = []
    for key in env_keys:
        val = os.environ.get(key, "")
        if val:
            env_entries.append(
                f"        <key>{key}</key>\n"
                f"        <string>{val}</string>"
            )

    env_block = ""
    if env_entries:
        env_block = (
            "    <key>EnvironmentVariables</key>\n"
            "    <dict>\n"
            + "\n".join(env_entries)
            + "\n    </dict>\n"
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{workflowx_bin}</string>
        <string>daemon</string>
        <string>run</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_path}</string>

    <key>StandardErrorPath</key>
    <string>{log_path}</string>

{env_block}</dict>
</plist>"""


def install_launchd_plist(log_path: Path) -> Path:
    """Write plist to ~/Library/LaunchAgents/ and return its path."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(generate_plist(log_path))
    return PLIST_PATH


def uninstall_launchd_plist() -> bool:
    """Remove the launchd plist. Returns True if it existed."""
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        return True
    return False


# ── Job runners (async, but I/O-bound — no CPU blocking) ─────────────────────


async def run_health_job(config: Any) -> bool:
    """Check Screenpipe health endpoint. Returns True if healthy.

    Sends a macOS notification if Screenpipe is offline or dropping frames.
    """
    import urllib.error
    import urllib.request

    url = "http://localhost:3030/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        drop_rate = float(data.get("frame_drop_rate", 0.0))
        if drop_rate >= 0.9:
            from workflowx.notifications import notify
            notify(
                "WorkflowX — Screenpipe Issue",
                f"Frame drop rate: {drop_rate:.0%}. Vision capture may be broken.",
                subtitle="Check ffmpeg setup",
            )
            logger.warning("screenpipe_high_drop_rate", drop_rate=drop_rate)
            return False
        return True
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        from workflowx.notifications import notify
        notify(
            "WorkflowX — Screenpipe Offline",
            "Screenpipe not responding on port 3030.",
            subtitle="Run: npx screenpipe@latest record",
        )
        logger.warning("screenpipe_not_responding")
        return False


async def run_capture_job(config: Any, store: Any) -> int:
    """Capture last 4 hours of Screenpipe events. Returns event count."""
    from workflowx.capture.screenpipe import ScreenpipeAdapter
    from workflowx.inference.clusterer import cluster_into_sessions

    sp = ScreenpipeAdapter(db_path=config.screenpipe_db_path)
    if not sp.is_available():
        logger.warning("daemon_capture_skipped", reason="screenpipe_not_available")
        return 0

    since = datetime.now() - timedelta(hours=4)
    events = sp.read_events(since=since)
    if not events:
        return 0

    sessions = cluster_into_sessions(
        events,
        gap_minutes=config.session_gap_minutes,
        min_events=config.min_session_events,
    )
    store.save_sessions(sessions)
    logger.info("daemon_capture_done", events=len(events), sessions=len(sessions))
    return len(events)


async def run_analyze_job(config: Any, store: Any) -> list[WorkflowSession]:
    """Run LLM intent inference on unanalyzed sessions.

    Returns the full updated session list for today.
    Sends a notification if classification questions are pending.
    """
    from workflowx.inference.intent import infer_intent

    sessions = store.load_sessions(date.today())
    to_analyze = [
        s for s in sessions
        if not s.inferred_intent or s.inferred_intent == "inference_failed"
    ]

    if not to_analyze:
        logger.info("daemon_analyze_skipped", reason="all_sessions_analyzed")
        return sessions

    try:
        client = config.get_llm_client()
    except RuntimeError:
        logger.warning("daemon_analyze_skipped", reason="no_api_key")
        return sessions

    questions = []
    for session in to_analyze:
        updated, question = await infer_intent(session, client, model=config.llm_model)
        if question:
            questions.append(question)
        for j, s in enumerate(sessions):
            if s.id == updated.id:
                sessions[j] = updated

    store.save_sessions(sessions)
    if questions:
        store.save_questions(questions)
        from workflowx.notifications import notify
        n = len(questions)
        notify(
            "WorkflowX — Your Input Needed",
            f"{n} workflow classification question{'s' if n != 1 else ''} waiting.",
            subtitle="Run: workflowx validate",
        )

    logger.info("daemon_analyze_done", analyzed=len(to_analyze), questions=len(questions))
    return sessions


async def run_propose_job(
    new_sessions: list[WorkflowSession],
    state: DaemonState,
) -> int:
    """Notify user about high-friction sessions that warrant replacement proposals.

    Marks sessions as proposed in state to prevent repeat notifications.
    The actual proposal text is generated lazily when user runs `workflowx propose`.
    Returns count of sessions notified.
    """
    if not new_sessions:
        return 0

    now_iso = datetime.now().isoformat()
    for s in new_sessions:
        state.proposed_session_ids[s.id] = now_iso

    # Prune entries older than 30 days to prevent unbounded growth
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    state.proposed_session_ids = {
        sid: ts
        for sid, ts in state.proposed_session_ids.items()
        if ts >= cutoff
    }

    count        = len(new_sessions)
    levels       = [s.friction_level.value.upper() for s in new_sessions[:3]]
    intents      = [s.inferred_intent[:30] for s in new_sessions[:2]]

    from workflowx.notifications import notify
    notify(
        f"WorkflowX — {count} High-Friction Session{'s' if count != 1 else ''}",
        f"{', '.join(intents)}",
        subtitle="Run: workflowx propose",
    )
    logger.info("daemon_propose_notified", count=count, levels=levels)
    return count


async def run_measure_job(config: Any, store: Any) -> int:
    """Run adaptive ROI measurement for outcomes that are due.

    Returns count of outcomes measured.
    """
    from workflowx.measurement import measure_outcome

    outcomes  = store.load_outcomes()
    to_measure = [o for o in outcomes if should_measure(o)]

    if not to_measure:
        logger.info("daemon_measure_skipped", reason="nothing_due")
        return 0

    today          = date.today()
    recent_sessions: list[WorkflowSession] = []
    for i in range(7):
        recent_sessions.extend(store.load_sessions(today - timedelta(days=i)))

    for outcome in to_measure:
        outcome = measure_outcome(outcome, recent_sessions, lookback_days=7)
        store.save_outcome(outcome)

    logger.info("daemon_measure_done", measured=len(to_measure))
    return len(to_measure)


async def run_brief_job(config: Any, store: Any) -> None:
    """Send the morning brief notification."""
    today = date.today()
    all_sessions: list[WorkflowSession] = []
    for i in range(2):
        all_sessions.extend(store.load_sessions(today - timedelta(days=i)))

    outcomes          = store.load_outcomes()
    pending_questions = len(store.load_pending_questions())

    title, msg = format_morning_brief(all_sessions, outcomes, pending_questions)
    from workflowx.notifications import notify
    notify(title, msg, subtitle="WorkflowX Daily Brief")
    logger.info("daemon_brief_sent")


# ── Async job loops ───────────────────────────────────────────────────────────


async def health_loop(config: Any, state_path: Path) -> None:
    """Health check: runs every HEALTH_INTERVAL_SECONDS."""
    while True:
        await asyncio.sleep(HEALTH_INTERVAL_SECONDS)
        state = read_state(state_path)
        try:
            healthy = await run_health_job(config)
            state.screenpipe_healthy      = healthy
            state.screenpipe_last_checked = datetime.now()
            state.jobs["health"]          = JobState(
                last_run=datetime.now(),
                last_status="ok" if healthy else "error",
                next_run=datetime.now() + timedelta(seconds=HEALTH_INTERVAL_SECONDS),
            )
        except Exception as e:
            state.jobs["health"] = JobState(
                last_run=datetime.now(), last_status="error", error_message=str(e)
            )
        write_state(state, state_path)


async def capture_loop(config: Any, store: Any, state_path: Path) -> None:
    """Capture loop: fires at CAPTURE_TIMES every day (including weekends)."""
    while True:
        target = next_fire_time(CAPTURE_TIMES, weekdays_only=False)
        state  = read_state(state_path)
        state.jobs.setdefault("capture", JobState()).next_run = target
        write_state(state, state_path)

        await asyncio.sleep(seconds_until(target))

        state = read_state(state_path)
        try:
            n = await run_capture_job(config, store)
            state.jobs["capture"] = JobState(
                last_run=datetime.now(),
                last_status="ok" if n > 0 else "skipped",
                next_run=next_fire_time(CAPTURE_TIMES, weekdays_only=False),
            )
        except Exception as e:
            logger.error("capture_loop_error", error=str(e))
            state.jobs["capture"] = JobState(
                last_run=datetime.now(), last_status="error", error_message=str(e)
            )
        write_state(state, state_path)


async def analyze_loop(config: Any, store: Any, state_path: Path) -> None:
    """Analyze loop: fires at ANALYZE_TIMES every day, then event-triggers propose."""
    while True:
        target = next_fire_time(ANALYZE_TIMES, weekdays_only=False)
        state  = read_state(state_path)
        state.jobs.setdefault("analyze", JobState()).next_run = target
        write_state(state, state_path)

        await asyncio.sleep(seconds_until(target))

        # Re-read state fresh (other loops may have written while we slept)
        state = read_state(state_path)
        try:
            sessions = await run_analyze_job(config, store)

            # Event-driven: find sessions that need a proposal notification
            to_propose = [s for s in sessions if should_propose(s, state.proposed_session_ids)]
            if to_propose:
                await run_propose_job(to_propose, state)

            state = read_state(state_path)   # re-read after propose may have updated
            state.jobs["analyze"] = JobState(
                last_run=datetime.now(),
                last_status="ok",
                next_run=next_fire_time(ANALYZE_TIMES, weekdays_only=False),
            )
        except Exception as e:
            logger.error("analyze_loop_error", error=str(e))
            state = read_state(state_path)
            state.jobs["analyze"] = JobState(
                last_run=datetime.now(), last_status="error", error_message=str(e)
            )
        write_state(state, state_path)


async def measure_loop(config: Any, store: Any, state_path: Path) -> None:
    """Measure loop: fires at MEASURE_TIMES every day (weekends included)."""
    while True:
        target = next_fire_time(MEASURE_TIMES, weekdays_only=False)
        state  = read_state(state_path)
        state.jobs.setdefault("measure", JobState()).next_run = target
        write_state(state, state_path)

        await asyncio.sleep(seconds_until(target))

        state = read_state(state_path)
        try:
            n = await run_measure_job(config, store)
            state.jobs["measure"] = JobState(
                last_run=datetime.now(),
                last_status="ok" if n > 0 else "skipped",
                next_run=next_fire_time(MEASURE_TIMES, weekdays_only=False),
            )
        except Exception as e:
            logger.error("measure_loop_error", error=str(e))
            state.jobs["measure"] = JobState(
                last_run=datetime.now(), last_status="error", error_message=str(e)
            )
        write_state(state, state_path)


async def brief_loop(config: Any, store: Any, state_path: Path) -> None:
    """Morning brief loop: fires at BRIEF_TIMES on weekdays."""
    while True:
        target = next_fire_time(BRIEF_TIMES, weekdays_only=True)
        state  = read_state(state_path)
        state.jobs.setdefault("brief", JobState()).next_run = target
        write_state(state, state_path)

        await asyncio.sleep(seconds_until(target))

        state = read_state(state_path)
        try:
            await run_brief_job(config, store)
            state.jobs["brief"] = JobState(
                last_run=datetime.now(),
                last_status="ok",
                next_run=next_fire_time(BRIEF_TIMES, weekdays_only=True),
            )
        except Exception as e:
            logger.error("brief_loop_error", error=str(e))
            state.jobs["brief"] = JobState(
                last_run=datetime.now(), last_status="error", error_message=str(e)
            )
        write_state(state, state_path)


# ── Main entry point ──────────────────────────────────────────────────────────


async def _daemon_async(config: Any, store: Any, state_path: Path) -> None:
    """Run all job loops concurrently."""
    state = read_state(state_path)
    state.started_at = datetime.now()
    write_state(state, state_path)

    logger.info("daemon_started", pid=os.getpid())

    await asyncio.gather(
        health_loop(config, state_path),
        capture_loop(config, store, state_path),
        analyze_loop(config, store, state_path),
        measure_loop(config, store, state_path),
        brief_loop(config, store, state_path),
    )


def run_daemon(config: Any, store: Any, state_path: Path, pid_path: Path) -> None:
    """Start the daemon. Blocks until Ctrl+C or SIGTERM."""
    write_pid(pid_path)
    try:
        asyncio.run(_daemon_async(config, store, state_path))
    finally:
        if pid_path.exists():
            pid_path.unlink()
        logger.info("daemon_stopped")
