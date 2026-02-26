"""Tests for Phase 2/3 storage additions: patterns and outcomes."""

from datetime import datetime

from workflowx.models import (
    FrictionLevel,
    ReplacementOutcome,
    WorkflowPattern,
)
from workflowx.storage import LocalStore


def test_save_and_load_patterns(tmp_path):
    store = LocalStore(tmp_path)
    patterns = [
        WorkflowPattern(
            id="pat_1",
            intent="competitive research",
            occurrences=5,
            first_seen=datetime(2026, 2, 20),
            last_seen=datetime(2026, 2, 26),
            avg_duration_minutes=45.0,
            most_common_friction=FrictionLevel.HIGH,
            total_time_invested_minutes=225.0,
            apps_involved=["Chrome", "Notion"],
        ),
    ]

    store.save_patterns(patterns)
    loaded = store.load_patterns()

    assert len(loaded) == 1
    assert loaded[0].id == "pat_1"
    assert loaded[0].intent == "competitive research"
    assert loaded[0].occurrences == 5


def test_save_and_load_outcomes(tmp_path):
    store = LocalStore(tmp_path)
    outcomes = [
        ReplacementOutcome(
            id="out_1",
            proposal_id="diag_research",
            intent="competitive research",
            adopted=True,
            adopted_date=datetime(2026, 2, 25),
            before_minutes_per_week=50.0,
            after_minutes_per_week=10.0,
            actual_savings_minutes=40.0,
            cumulative_savings_minutes=120.0,
            weeks_tracked=3,
            status="adopted",
        ),
    ]

    store.save_outcomes(outcomes)
    loaded = store.load_outcomes()

    assert len(loaded) == 1
    assert loaded[0].id == "out_1"
    assert loaded[0].status == "adopted"
    assert loaded[0].actual_savings_minutes == 40.0


def test_update_existing_outcome(tmp_path):
    store = LocalStore(tmp_path)

    outcome = ReplacementOutcome(
        id="out_1",
        proposal_id="p1",
        intent="email",
        status="measuring",
        weeks_tracked=0,
    )
    store.save_outcomes([outcome])

    # Update
    outcome.status = "adopted"
    outcome.weeks_tracked = 2
    outcome.actual_savings_minutes = 30.0
    store.save_outcomes([outcome])

    loaded = store.load_outcomes()
    assert len(loaded) == 1
    assert loaded[0].status == "adopted"
    assert loaded[0].weeks_tracked == 2


def test_empty_patterns_and_outcomes(tmp_path):
    store = LocalStore(tmp_path)
    assert store.load_patterns() == []
    assert store.load_outcomes() == []


def test_load_sessions_range(tmp_path):
    """Test the fixed load_sessions_range using timedelta."""
    from datetime import date, timedelta
    from workflowx.models import WorkflowSession

    store = LocalStore(tmp_path)

    # Save sessions across 3 days
    for offset in range(3):
        d = date(2026, 2, 26) + timedelta(days=offset)
        session = WorkflowSession(
            id=f"sess_day_{offset}",
            start_time=datetime(2026, 2, 26 + offset, 10, 0),
            end_time=datetime(2026, 2, 26 + offset, 11, 0),
            total_duration_minutes=60.0,
        )
        store.save_sessions([session], d)

    # Load range
    loaded = store.load_sessions_range(date(2026, 2, 26), date(2026, 2, 28))
    assert len(loaded) == 3
