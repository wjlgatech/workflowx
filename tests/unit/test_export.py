"""Tests for JSON/CSV export."""

import csv
import io
import json
from datetime import datetime, timedelta

from workflowx.export import (
    patterns_to_csv,
    patterns_to_json,
    sessions_to_csv,
    sessions_to_json,
    trends_to_csv,
    trends_to_json,
)
from workflowx.models import (
    FrictionLevel,
    FrictionTrend,
    WorkflowPattern,
    WorkflowSession,
)


def _make_session(hour: int, duration: int, intent: str = "coding") -> WorkflowSession:
    start = datetime(2026, 2, 26, hour, 0)
    end = start + timedelta(minutes=duration)
    return WorkflowSession(
        id=f"sess_{hour}",
        start_time=start,
        end_time=end,
        total_duration_minutes=float(duration),
        apps_used=["VSCode", "Chrome"],
        context_switches=5,
        friction_level=FrictionLevel.MEDIUM,
        inferred_intent=intent,
        confidence=0.85,
    )


# ── Sessions Export ──────────────────────────────────────────


def test_sessions_to_json():
    sessions = [_make_session(9, 45), _make_session(14, 30)]
    result = sessions_to_json(sessions)
    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["inferred_intent"] == "coding"
    # Events should be stripped
    assert "events" not in data[0]


def test_sessions_to_csv():
    sessions = [_make_session(9, 45, "coding"), _make_session(14, 30, "research")]
    result = sessions_to_csv(sessions)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert rows[0][0] == "id"  # Header
    assert len(rows) == 3  # Header + 2 data rows
    assert rows[1][7] == "coding"  # inferred_intent column


# ── Patterns Export ──────────────────────────────────────────


def test_patterns_to_json():
    patterns = [
        WorkflowPattern(
            id="pat_1",
            intent="competitive research",
            occurrences=3,
            first_seen=datetime(2026, 2, 20),
            last_seen=datetime(2026, 2, 26),
            avg_duration_minutes=45.0,
            total_time_invested_minutes=135.0,
        )
    ]
    result = patterns_to_json(patterns)
    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["intent"] == "competitive research"


def test_patterns_to_csv():
    patterns = [
        WorkflowPattern(
            id="pat_1",
            intent="research",
            occurrences=5,
            first_seen=datetime(2026, 2, 20),
            last_seen=datetime(2026, 2, 26),
            avg_duration_minutes=40.0,
            total_time_invested_minutes=200.0,
            apps_involved=["Chrome", "Notion"],
        )
    ]
    result = patterns_to_csv(patterns)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert rows[0][0] == "id"
    assert len(rows) == 2


# ── Trends Export ────────────────────────────────────────────


def test_trends_to_json():
    trends = [
        FrictionTrend(
            week_label="2026-W09",
            week_start=datetime(2026, 2, 23),
            week_end=datetime(2026, 2, 27),
            total_sessions=10,
            total_minutes=450.0,
            high_friction_minutes=120.0,
            high_friction_ratio=0.267,
        )
    ]
    result = trends_to_json(trends)
    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["week_label"] == "2026-W09"


def test_trends_to_csv():
    trends = [
        FrictionTrend(
            week_label="2026-W08",
            week_start=datetime(2026, 2, 16),
            week_end=datetime(2026, 2, 20),
            total_sessions=8,
            total_minutes=360.0,
            high_friction_minutes=90.0,
            high_friction_ratio=0.25,
        ),
        FrictionTrend(
            week_label="2026-W09",
            week_start=datetime(2026, 2, 23),
            week_end=datetime(2026, 2, 27),
            total_sessions=12,
            total_minutes=500.0,
            high_friction_minutes=150.0,
            high_friction_ratio=0.30,
        ),
    ]
    result = trends_to_csv(trends)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 3  # Header + 2 data rows
