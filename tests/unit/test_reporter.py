"""Tests for report generation."""

from datetime import datetime, timedelta

from workflowx.inference.reporter import (
    generate_daily_report,
    generate_weekly_report,
    format_weekly_summary,
)
from workflowx.models import FrictionLevel, WorkflowSession


def _make_session(
    hour: int,
    duration: int,
    friction: str = "low",
    intent: str = "",
    switches: int = 2,
) -> WorkflowSession:
    start = datetime(2026, 2, 26, hour, 0)
    end = start + timedelta(minutes=duration)
    return WorkflowSession(
        id=f"sess_{hour}",
        start_time=start,
        end_time=end,
        total_duration_minutes=float(duration),
        apps_used=["VSCode", "Chrome"],
        context_switches=switches,
        friction_level=FrictionLevel(friction),
        inferred_intent=intent,
        confidence=0.85 if intent else 0.0,
    )


def test_daily_report_empty():
    report = generate_daily_report([])
    assert "No workflow sessions" in report


def test_daily_report_with_sessions():
    sessions = [
        _make_session(9, 45, "low", "coding"),
        _make_session(10, 60, "critical", "research", switches=20),
        _make_session(11, 30, "medium", "slack triage"),
    ]
    report = generate_daily_report(sessions)

    assert "DAILY WORKFLOW REPORT" in report
    assert "3" in report  # 3 sessions
    assert "135" in report  # 135 min total
    assert "HIGH-FRICTION" in report  # has high friction sessions


def test_daily_report_no_friction():
    sessions = [
        _make_session(9, 45, "low", "coding"),
        _make_session(10, 60, "low", "writing"),
    ]
    report = generate_daily_report(sessions)
    assert "low friction" in report


def test_weekly_report_structure():
    sessions = [
        _make_session(9, 45, "low", "coding"),
        _make_session(10, 60, "high", "research", switches=15),
        _make_session(14, 30, "critical", "data entry", switches=25),
    ]
    report = generate_weekly_report(sessions)

    assert report.total_sessions == 3
    assert report.total_hours_tracked > 0
    assert report.total_estimated_savings_minutes > 0
    assert len(report.top_friction_points) > 0


def test_weekly_report_format():
    sessions = [
        _make_session(9, 45, "low", "coding"),
        _make_session(10, 60, "high", "research", switches=15),
    ]
    report = generate_weekly_report(sessions)
    text = format_weekly_summary(report)

    assert "WEEKLY WORKFLOW REPORT" in text
    assert "POTENTIAL SAVINGS" in text
    assert "workflowx propose" in text
