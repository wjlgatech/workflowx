"""Tests for before/after measurement and ROI tracking."""

from datetime import datetime, timedelta

from workflowx.measurement import (
    compute_roi_summary,
    create_outcome,
    format_roi_report,
    measure_outcome,
)
from workflowx.models import (
    FrictionLevel,
    ReplacementOutcome,
    ReplacementProposal,
    WorkflowSession,
)


def _make_proposal(intent: str = "competitive research") -> ReplacementProposal:
    return ReplacementProposal(
        diagnosis_id=f"diag_{intent.replace(' ', '_')}",
        original_workflow=intent,
        proposed_workflow="automated monitoring",
        mechanism="Use an agent to do it",
        estimated_time_after_minutes=5.0,
        estimated_savings_minutes_per_week=45.0,
    )


def _make_session(
    intent: str,
    duration: int,
    hours_ago: int = 0,
) -> WorkflowSession:
    now = datetime.now()
    start = now - timedelta(hours=hours_ago, minutes=duration)
    end = now - timedelta(hours=hours_ago)
    return WorkflowSession(
        id=f"sess_{intent}_{hours_ago}",
        start_time=start,
        end_time=end,
        total_duration_minutes=float(duration),
        inferred_intent=intent,
        confidence=0.9,
        friction_level=FrictionLevel.HIGH,
    )


# ── create_outcome ───────────────────────────────────────────


def test_create_outcome():
    proposal = _make_proposal("data entry")
    outcome = create_outcome(proposal, before_minutes_per_week=120.0)

    assert outcome.adopted is True
    assert outcome.before_minutes_per_week == 120.0
    assert outcome.status == "measuring"
    assert outcome.intent == "data entry"
    assert outcome.adopted_date is not None


# ── measure_outcome ──────────────────────────────────────────


def test_measure_outcome_with_matching_sessions():
    proposal = _make_proposal("competitive research")
    outcome = create_outcome(proposal, before_minutes_per_week=50.0)

    # Recent sessions show 15 min of competitive research in the last 7 days
    recent = [
        _make_session("competitive research", 10, hours_ago=24),
        _make_session("competitive research", 5, hours_ago=48),
        _make_session("coding", 60, hours_ago=12),  # Different intent
    ]

    updated = measure_outcome(outcome, recent, lookback_days=7)
    assert updated.after_minutes_per_week == 15.0  # 15 min in 7 days = 15 min/week
    assert updated.actual_savings_minutes == 35.0  # 50 - 15 = 35
    assert updated.status == "adopted"  # Savings > 0


def test_measure_outcome_no_improvement():
    proposal = _make_proposal("email triage")
    outcome = create_outcome(proposal, before_minutes_per_week=30.0)
    outcome.weeks_tracked = 2  # Already tracked for 2 weeks

    # Still spending 30+ min/week
    recent = [
        _make_session("email triage", 20, hours_ago=24),
        _make_session("email triage", 15, hours_ago=72),
    ]

    updated = measure_outcome(outcome, recent, lookback_days=7)
    assert updated.after_minutes_per_week == 35.0  # 35 min in 7 days
    assert updated.actual_savings_minutes == -5.0  # Got worse
    assert updated.status == "rejected"  # 2+ weeks, no improvement


def test_measure_outcome_no_matching_sessions():
    proposal = _make_proposal("report generation")
    outcome = create_outcome(proposal, before_minutes_per_week=60.0)

    # No matching sessions at all
    recent = [
        _make_session("coding", 120, hours_ago=12),
    ]

    updated = measure_outcome(outcome, recent, lookback_days=7)
    assert updated.after_minutes_per_week == 0.0
    assert updated.actual_savings_minutes == 60.0  # All time saved


# ── compute_roi_summary ──────────────────────────────────────


def test_compute_roi_summary_empty():
    summary = compute_roi_summary([])
    assert summary["total_outcomes"] == 0
    assert summary["adoption_rate"] == 0.0


def test_compute_roi_summary_mixed():
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
        ReplacementOutcome(
            id="out_2",
            proposal_id="p2",
            intent="email",
            status="rejected",
            before_minutes_per_week=30,
            after_minutes_per_week=35,
            actual_savings_minutes=-5,
            cumulative_savings_minutes=-10,
            weeks_tracked=2,
        ),
        ReplacementOutcome(
            id="out_3",
            proposal_id="p3",
            intent="reports",
            status="measuring",
            before_minutes_per_week=60,
            after_minutes_per_week=0,
            actual_savings_minutes=0,
            weeks_tracked=0,
        ),
    ]

    summary = compute_roi_summary(outcomes)
    assert summary["total_outcomes"] == 3
    assert summary["adopted"] == 1
    assert summary["rejected"] == 1
    assert summary["measuring"] == 1
    assert summary["total_weekly_savings_minutes"] == 40.0  # Only adopted counts
    assert len(summary["outcomes"]) == 3


# ── format_roi_report ────────────────────────────────────────


def test_format_roi_report_empty():
    text = format_roi_report([])
    assert "No replacement outcomes" in text


def test_format_roi_report_with_data():
    outcomes = [
        ReplacementOutcome(
            id="out_1",
            proposal_id="p1",
            intent="competitive research",
            status="adopted",
            before_minutes_per_week=50,
            after_minutes_per_week=10,
            actual_savings_minutes=40,
            cumulative_savings_minutes=120,
            weeks_tracked=3,
        ),
    ]
    text = format_roi_report(outcomes, hourly_rate=100.0)
    assert "ROI DASHBOARD" in text
    assert "WEEKLY SAVINGS" in text
    assert "CUMULATIVE" in text
