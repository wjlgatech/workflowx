"""Tests for ROI dashboard HTML generation."""

from datetime import datetime

from workflowx.dashboard import generate_dashboard_html
from workflowx.models import (
    FrictionLevel,
    FrictionTrend,
    ReplacementOutcome,
    WorkflowPattern,
)


def test_dashboard_html_basic():
    trends = [
        FrictionTrend(
            week_label="2026-W08",
            week_start=datetime(2026, 2, 16),
            week_end=datetime(2026, 2, 20),
            total_sessions=10,
            total_minutes=400,
            high_friction_minutes=100,
            high_friction_ratio=0.25,
        ),
    ]
    patterns = [
        WorkflowPattern(
            id="pat_1",
            intent="research",
            occurrences=5,
            first_seen=datetime(2026, 2, 10),
            last_seen=datetime(2026, 2, 26),
            total_time_invested_minutes=200,
        ),
    ]
    outcomes = [
        ReplacementOutcome(
            id="out_1",
            proposal_id="p1",
            intent="research",
            status="adopted",
            before_minutes_per_week=50,
            after_minutes_per_week=10,
            actual_savings_minutes=40,
            cumulative_savings_minutes=120,
            weeks_tracked=3,
        ),
    ]

    html = generate_dashboard_html(trends, patterns, outcomes, hourly_rate=75.0)

    assert "<!DOCTYPE html>" in html
    assert "WorkflowX ROI Dashboard" in html
    assert "Chart.js" in html
    assert "frictionChart" in html
    assert "patternChart" in html
    assert "roiChart" in html


def test_dashboard_html_empty_data():
    html = generate_dashboard_html([], [], [], hourly_rate=75.0)
    assert "<!DOCTYPE html>" in html
    assert "WorkflowX ROI Dashboard" in html


def test_dashboard_html_contains_metrics():
    outcomes = [
        ReplacementOutcome(
            id="out_1",
            proposal_id="p1",
            intent="email triage",
            status="adopted",
            before_minutes_per_week=60,
            after_minutes_per_week=15,
            actual_savings_minutes=45,
            cumulative_savings_minutes=180,
            weeks_tracked=4,
        ),
    ]

    html = generate_dashboard_html([], [], outcomes, hourly_rate=100.0)

    # Should contain the savings numbers
    assert "45" in html  # Weekly savings minutes
    assert "Adoption Rate" in html
