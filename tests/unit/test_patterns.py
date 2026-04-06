"""Tests for pattern detection and friction trends."""

from datetime import datetime, timedelta

from workflowx.inference.patterns import (
    _intent_similarity,
    compute_friction_trends,
    detect_patterns,
    format_patterns_report,
    format_trends_report,
)
from workflowx.models import FrictionLevel, WorkflowSession


def _make_session(
    day_offset: int,
    hour: int,
    duration: int,
    intent: str,
    friction: str = "low",
    switches: int = 2,
) -> WorkflowSession:
    """Create a session on a specific day relative to today."""
    base = datetime(2026, 2, 20)  # Fixed base for deterministic tests
    start = base + timedelta(days=day_offset, hours=hour)
    end = start + timedelta(minutes=duration)
    return WorkflowSession(
        id=f"sess_d{day_offset}_h{hour}",
        start_time=start,
        end_time=end,
        total_duration_minutes=float(duration),
        apps_used=["Chrome", "Notion"],
        context_switches=switches,
        friction_level=FrictionLevel(friction),
        inferred_intent=intent,
        confidence=0.85,
    )


# ── Intent Similarity ────────────────────────────────────────


def test_intent_similarity_identical():
    assert _intent_similarity("competitive research", "competitive research") == 1.0


def test_intent_similarity_similar():
    sim = _intent_similarity("competitive research", "competitor analysis")
    assert sim > 0.4  # Should be somewhat similar


def test_intent_similarity_different():
    sim = _intent_similarity("coding python", "cooking dinner recipes")
    assert sim < 0.5


def test_intent_similarity_empty():
    assert _intent_similarity("", "something") == 0.0
    assert _intent_similarity("something", "") == 0.0


# ── Pattern Detection ────────────────────────────────────────


def test_detect_patterns_basic():
    sessions = [
        _make_session(0, 9, 45, "competitive research", "high", 15),
        _make_session(1, 10, 50, "competitive research", "high", 18),
        _make_session(2, 9, 40, "competitive research", "critical", 20),
    ]
    patterns = detect_patterns(sessions, min_occurrences=2)
    assert len(patterns) == 1
    assert patterns[0].occurrences == 3
    assert patterns[0].intent == "competitive research"
    assert patterns[0].total_time_invested_minutes == 135.0


def test_detect_patterns_groups_similar_intents():
    sessions = [
        _make_session(0, 9, 45, "competitive research", "high"),
        _make_session(1, 9, 50, "competitive research", "high"),
        _make_session(0, 14, 30, "coding feature", "low"),
        _make_session(1, 14, 35, "coding feature", "low"),
    ]
    patterns = detect_patterns(sessions, min_occurrences=2)
    assert len(patterns) == 2


def test_detect_patterns_ignores_unanalyzed():
    sessions = [
        _make_session(0, 9, 45, "", "low"),  # No intent
        _make_session(1, 9, 50, "inference_failed", "low"),
    ]
    patterns = detect_patterns(sessions, min_occurrences=1)
    assert len(patterns) == 0


def test_detect_patterns_min_occurrences():
    sessions = [
        _make_session(0, 9, 45, "one-off task", "high"),
    ]
    patterns = detect_patterns(sessions, min_occurrences=2)
    assert len(patterns) == 0


def test_detect_patterns_sorted_by_time():
    sessions = [
        _make_session(0, 9, 10, "quick email check", "low"),
        _make_session(1, 9, 10, "quick email check", "low"),
        _make_session(0, 14, 60, "deep competitive research", "high"),
        _make_session(1, 14, 60, "deep competitive research", "high"),
    ]
    patterns = detect_patterns(sessions, min_occurrences=2)
    assert len(patterns) == 2
    # Research should be first (more total time)
    assert patterns[0].intent == "deep competitive research"


def test_detect_patterns_trend():
    # First occurrences low friction, later ones high
    sessions = [
        _make_session(0, 9, 45, "research", "low"),
        _make_session(1, 9, 45, "research", "low"),
        _make_session(5, 9, 45, "research", "high"),
        _make_session(6, 9, 45, "research", "critical"),
    ]
    patterns = detect_patterns(sessions, min_occurrences=2)
    assert len(patterns) == 1
    assert patterns[0].trend == "worsening"


# ── Friction Trends ──────────────────────────────────────────


def test_compute_friction_trends_basic():
    # Sessions across 2 different ISO weeks
    sessions = [
        _make_session(0, 9, 45, "coding", "low", 2),      # Week of Feb 20 (Fri)
        _make_session(0, 14, 60, "research", "high", 15),
        _make_session(3, 9, 45, "coding", "low", 2),       # Week of Feb 23 (Mon)
        _make_session(3, 14, 30, "meeting", "medium", 5),
    ]
    trends = compute_friction_trends(sessions, num_weeks=4)
    assert len(trends) >= 1
    # Each trend should have valid fields
    for t in trends:
        assert t.total_sessions > 0
        assert t.total_minutes > 0
        assert 0.0 <= t.high_friction_ratio <= 1.0


def test_compute_friction_trends_empty():
    trends = compute_friction_trends([], num_weeks=4)
    assert trends == []


def test_friction_trends_ratio():
    # All high friction
    sessions = [
        _make_session(0, 9, 60, "pain", "high", 20),
        _make_session(0, 14, 60, "more pain", "critical", 25),
    ]
    trends = compute_friction_trends(sessions, num_weeks=4)
    assert len(trends) == 1
    assert trends[0].high_friction_ratio == 1.0  # 100% high friction


# ── Formatting ───────────────────────────────────────────────


def test_format_patterns_report_empty():
    text = format_patterns_report([])
    assert "No recurring patterns" in text


def test_format_patterns_report_with_data():
    sessions = [
        _make_session(0, 9, 45, "competitive research", "high", 15),
        _make_session(1, 9, 50, "competitive research", "high", 18),
    ]
    patterns = detect_patterns(sessions, min_occurrences=2)
    text = format_patterns_report(patterns)
    assert "RECURRING WORKFLOW PATTERNS" in text
    assert "competitive research" in text


def test_format_trends_report_empty():
    text = format_trends_report([])
    assert "No trend data" in text


def test_format_trends_report_with_data():
    sessions = [
        _make_session(0, 9, 60, "coding", "low", 2),
        _make_session(0, 14, 60, "research", "high", 15),
    ]
    trends = compute_friction_trends(sessions)
    text = format_trends_report(trends)
    assert "FRICTION TREND REPORT" in text
