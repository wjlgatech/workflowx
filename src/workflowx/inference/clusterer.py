"""Workflow session clusterer — groups raw events into coherent workflow sessions.

The core heuristic: events within a gap threshold belong to the same session.
Context switches (app changes) within a session are tracked as friction signals.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Sequence

import structlog

from workflowx.models import FrictionLevel, RawEvent, WorkflowSession

logger = structlog.get_logger()

DEFAULT_GAP_MINUTES = 5  # Gap > 5 min = new session
MIN_SESSION_EVENTS = 2   # Ignore single-event "sessions"


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


def _build_session(events: list[RawEvent]) -> WorkflowSession:
    """Build a WorkflowSession from a list of events."""
    apps = []
    switches = 0
    prev_app = ""

    for e in events:
        if e.app_name and e.app_name != prev_app:
            if prev_app:
                switches += 1
            apps.append(e.app_name)
            prev_app = e.app_name

    start = events[0].timestamp
    end = events[-1].timestamp
    duration_min = (end - start).total_seconds() / 60.0

    # Friction heuristic: switches per minute
    switches_per_min = switches / max(duration_min, 0.1)
    if switches_per_min > 3:
        friction = FrictionLevel.CRITICAL
    elif switches_per_min > 1.5:
        friction = FrictionLevel.HIGH
    elif switches_per_min > 0.5:
        friction = FrictionLevel.MEDIUM
    else:
        friction = FrictionLevel.LOW

    unique_apps = list(dict.fromkeys(apps))  # preserve order, dedupe

    # Deterministic ID: same session window always gets the same ID.
    # Prevents duplicates when capture is run multiple times on the same day.
    session_key = f"{start.date().isoformat()}_{start.strftime('%H%M%S')}"
    session_id = hashlib.md5(session_key.encode()).hexdigest()[:12]

    return WorkflowSession(
        id=session_id,
        start_time=start,
        end_time=end,
        events=events,
        apps_used=unique_apps,
        total_duration_minutes=round(duration_min, 1),
        context_switches=switches,
        friction_level=friction,
    )
