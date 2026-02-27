"""Workflow session clusterer — groups raw events into coherent workflow sessions.

The core heuristic: events within a gap threshold belong to the same session.
Context switches (focus changes) within a session are tracked as friction signals.

NOTE on Screenpipe's capture model:
Screenpipe fires OCR frames from every *visible* window, not just the focused one.
If Chrome, VS Code, and Slack are all on screen, each capture cycle emits three
events with three different app_names — even when the user hasn't moved their focus.
Naive consecutive-event counting would register a "switch" on every frame, inflating
the count by 10–50×. We denoise using 30-second time-window bucketing instead.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta
from typing import Sequence

import structlog

from workflowx.models import FrictionLevel, RawEvent, WorkflowSession

logger = structlog.get_logger()

DEFAULT_GAP_MINUTES = 5   # Gap > 5 min = new session
MIN_SESSION_EVENTS = 2    # Ignore single-event "sessions"
FOCUS_WINDOW_SECONDS = 30  # Bucket size for focus-switch denoising


def cluster_into_sessions(
    events: Sequence[RawEvent],
    gap_minutes: float = DEFAULT_GAP_MINUTES,
    min_events: int = MIN_SESSION_EVENTS,
) -> list[WorkflowSession]:
    """Cluster a sorted list of raw events into workflow sessions.

    Algorithm:
    1. Walk events in chronological order
    2. If gap between consecutive events > gap_minutes, start new session
    3. Track app switches within each session as context_switches
    4. Compute friction level based on switch frequency and duration
    """
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: e.timestamp)
    sessions: list[WorkflowSession] = []
    current_events: list[RawEvent] = [sorted_events[0]]
    current_app = sorted_events[0].app_name

    for prev, curr in zip(sorted_events[:-1], sorted_events[1:]):
        gap = (curr.timestamp - prev.timestamp).total_seconds() / 60.0

        if gap > gap_minutes:
            # Close current session
            session = _build_session(current_events)
            if len(current_events) >= min_events:
                sessions.append(session)
            current_events = [curr]
            current_app = curr.app_name
        else:
            current_events.append(curr)

    # Don't forget the last session
    if len(current_events) >= min_events:
        sessions.append(_build_session(current_events))

    logger.info(
        "sessions_clustered",
        total_events=len(sorted_events),
        sessions_created=len(sessions),
    )
    return sessions


def _activity_weight(e: RawEvent) -> int:
    """Score how much real user activity an OCR frame likely represents.

    A static background window (YouTube playing, Slack sidebar) generates frames
    with short, unchanging OCR snippets. The window the user is actively working
    in generates rich, dense text (code, prose, chat). We use OCR text length as
    a proxy: more content = more likely to be the real focus window.

    Weight is capped at 5 to prevent a single large document frame from
    completely dominating a bucket.
    """
    text_len = len((e.ocr_text or "").strip())
    return min(text_len // 200 + 1, 5)


def _count_focus_switches(events: list[RawEvent]) -> tuple[int, list[str]]:
    """Count genuine app-focus switches, denoised for Screenpipe's capture model.

    Screenpipe fires OCR frames from every visible window — not just the focused
    one — so naive consecutive-event counting inflates switches by 10–50×.

    Fix: divide the session into FOCUS_WINDOW_SECONDS buckets. Each bucket's
    "active app" is the activity-weighted winner: the app whose frames carry the
    most OCR content (a proxy for real user activity vs. static background windows).
    A switch is counted only when adjacent buckets have different winners.

    Returns (switch_count, apps_in_order_of_first_focus).
    """
    if not events:
        return 0, []

    start = events[0].timestamp
    buckets: dict[int, Counter] = {}
    for e in events:
        if not e.app_name or e.app_name == "audio":
            continue
        idx = int((e.timestamp - start).total_seconds() // FOCUS_WINDOW_SECONDS)
        if idx not in buckets:
            buckets[idx] = Counter()
        buckets[idx][e.app_name] += _activity_weight(e)

    if not buckets:
        return 0, []

    focus_timeline = [
        buckets[i].most_common(1)[0][0] for i in sorted(buckets)
    ]
    switches = sum(1 for a, b in zip(focus_timeline, focus_timeline[1:]) if a != b)
    unique_apps = list(dict.fromkeys(focus_timeline))
    return switches, unique_apps


def _build_session(events: list[RawEvent]) -> WorkflowSession:
    """Build a WorkflowSession from a list of events."""
    switches, apps = _count_focus_switches(events)

    start = events[0].timestamp
    end = events[-1].timestamp
    duration_min = (end - start).total_seconds() / 60.0

    # Friction: focus switches per minute (window-denoised).
    # Calibrated for knowledge work:
    #   CRITICAL  > 0.5/min  — switching every 2 min, genuinely chaotic
    #   HIGH      > 0.2/min  — switching every 5 min, frequent interruption
    #   MEDIUM    > 0.1/min  — switching every 10 min, moderate distraction
    #   LOW       ≤ 0.1/min  — stable deep-work cadence
    switches_per_min = switches / max(duration_min, 1.0)
    if switches_per_min > 0.5:
        friction = FrictionLevel.CRITICAL
    elif switches_per_min > 0.2:
        friction = FrictionLevel.HIGH
    elif switches_per_min > 0.1:
        friction = FrictionLevel.MEDIUM
    else:
        friction = FrictionLevel.LOW

    # Deterministic ID: same session window always gets the same ID.
    # Prevents duplicates when capture is run multiple times on the same day.
    session_key = f"{start.date().isoformat()}_{start.strftime('%H%M%S')}"
    session_id = hashlib.md5(session_key.encode()).hexdigest()[:12]

    return WorkflowSession(
        id=session_id,
        start_time=start,
        end_time=end,
        events=events,
        apps_used=apps,
        total_duration_minutes=round(duration_min, 1),
        context_switches=switches,
        friction_level=friction,
    )
