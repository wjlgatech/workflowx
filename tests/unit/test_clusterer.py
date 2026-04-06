"""Tests for workflow session clustering."""

from datetime import datetime, timedelta

from workflowx.inference.clusterer import FOCUS_WINDOW_SECONDS, cluster_into_sessions
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


def test_screenpipe_multiwindow_noise_denoised():
    """Background-window frames with sparse OCR don't inflate switch counts.

    A focused VS Code window generates rich code text; a background Chrome tab
    (static page) generates minimal OCR. Activity weighting means VS Code wins
    each bucket even when Chrome fires more *frames*.
    """
    base = datetime(2026, 2, 26, 10, 0)
    events = []
    # 10-minute session: VS Code is focused (rich OCR), Chrome is background (sparse)
    for sec in range(0, 600, 15):
        # VS Code: active window, dense code text
        events.append(RawEvent(
            timestamp=base + timedelta(seconds=sec),
            source=EventSource.SCREENPIPE,
            app_name="VSCode",
            window_title="main.py",
            ocr_text="def cluster_into_sessions(events):\n    for e in events:\n        pass" * 5,
        ))
        # Chrome: two background frames per VS Code frame, but nearly empty OCR
        for offset in [5, 10]:
            events.append(RawEvent(
                timestamp=base + timedelta(seconds=sec + offset),
                source=EventSource.SCREENPIPE,
                app_name="Chrome",
                window_title="New Tab",
                ocr_text="New Tab",  # static background page — almost no content
            ))

    sessions = cluster_into_sessions(events, gap_minutes=5)
    assert len(sessions) == 1
    # Chrome fires 2× more frames, but VS Code has far more OCR activity → 0 switches
    assert sessions[0].context_switches == 0
    assert sessions[0].friction_level == FrictionLevel.LOW


def test_genuine_sustained_switching_is_high_friction():
    """Persistent focus changes (every few minutes) register as HIGH/CRITICAL friction."""
    base = datetime(2026, 2, 26, 10, 0)
    events = []
    # Bounce between VSCode and Chrome every 2 minutes for 20 minutes.
    # Each 2-minute chunk: 5 frames clearly dominated by one app.
    chunks = ["VSCode", "Chrome"] * 5
    for i, app in enumerate(chunks):
        for j in range(5):
            events.append(RawEvent(
                timestamp=base + timedelta(minutes=i * 2, seconds=j * 20),
                source=EventSource.SCREENPIPE,
                app_name=app,
                window_title="",
            ))

    sessions = cluster_into_sessions(events, gap_minutes=5)
    assert len(sessions) == 1
    assert sessions[0].friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
    # Sanity: much fewer switches than raw event count
    assert sessions[0].context_switches < len(events) // 2
