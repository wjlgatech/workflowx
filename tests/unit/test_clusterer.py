"""Tests for workflow session clustering."""

from datetime import datetime, timedelta

from workflowx.inference.clusterer import cluster_into_sessions
from workflowx.models import EventSource, FrictionLevel, RawEvent


def _make_event(minutes_offset: int, app: str = "VSCode", title: str = "code") -> RawEvent:
    """Helper to create events at specific time offsets."""
    return RawEvent(
        timestamp=datetime(2026, 2, 26, 10, 0) + timedelta(minutes=minutes_offset),
        source=EventSource.SCREENPIPE,
        app_name=app,
        window_title=title,
    )


def test_empty_events():
    assert cluster_into_sessions([]) == []


def test_single_event_ignored():
    """Single events don't form a session (below min_events threshold)."""
    events = [_make_event(0)]
    sessions = cluster_into_sessions(events, min_events=2)
    assert len(sessions) == 0


def test_continuous_events_one_session():
    """Events within gap threshold form one session."""
    events = [
        _make_event(0, "VSCode"),
        _make_event(1, "VSCode"),
        _make_event(2, "VSCode"),
        _make_event(3, "VSCode"),
    ]
    sessions = cluster_into_sessions(events, gap_minutes=5)
    assert len(sessions) == 1
    assert sessions[0].total_duration_minutes == 3.0


def test_gap_splits_sessions():
    """A gap > threshold creates separate sessions."""
    events = [
        _make_event(0, "VSCode"),
        _make_event(1, "VSCode"),
        # 10-minute gap
        _make_event(11, "Chrome"),
        _make_event(12, "Chrome"),
    ]
    sessions = cluster_into_sessions(events, gap_minutes=5)
    assert len(sessions) == 2


def test_context_switches_counted():
    """App changes within a session are counted as context switches."""
    events = [
        _make_event(0, "VSCode"),
        _make_event(1, "Chrome"),
        _make_event(2, "Slack"),
        _make_event(3, "VSCode"),
    ]
    sessions = cluster_into_sessions(events, gap_minutes=5)
    assert len(sessions) == 1
    assert sessions[0].context_switches == 3


def test_high_friction_from_rapid_switching():
    """Rapid app switching produces high friction score."""
    events = [
        _make_event(0, "VSCode"),
        _make_event(0, "Chrome"),
        _make_event(0, "Slack"),
        _make_event(0, "VSCode"),
        _make_event(1, "Chrome"),
        _make_event(1, "Notion"),
        _make_event(1, "Slack"),
        _make_event(1, "VSCode"),
    ]
    sessions = cluster_into_sessions(events, gap_minutes=5)
    assert len(sessions) == 1
    assert sessions[0].friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)


def test_apps_used_tracks_transitions():
    """Apps list tracks each transition (re-entries are signal, not noise)."""
    events = [
        _make_event(0, "VSCode"),
        _make_event(1, "Chrome"),
        _make_event(2, "VSCode"),
        _make_event(3, "Slack"),
    ]
    sessions = cluster_into_sessions(events, gap_minutes=5)
    apps = sessions[0].apps_used
    assert "VSCode" in apps
    assert "Chrome" in apps
    assert "Slack" in apps
    assert len(apps) >= 3
