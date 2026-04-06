"""Tests for core domain models."""

from datetime import datetime

from workflowx.models import (
    EventSource,
    FrictionLevel,
    RawEvent,
    WorkflowSession,
    ClassificationQuestion,
    WorkflowDiagnosis,
    ReplacementProposal,
)


def test_raw_event_creation():
    event = RawEvent(
        timestamp=datetime(2026, 2, 26, 10, 0, 0),
        source=EventSource.SCREENPIPE,
        app_name="VSCode",
        window_title="main.py - workflowx",
    )
    assert event.app_name == "VSCode"
    assert event.source == EventSource.SCREENPIPE


def test_workflow_session_defaults():
    session = WorkflowSession(
        id="test123",
        start_time=datetime(2026, 2, 26, 10, 0),
        end_time=datetime(2026, 2, 26, 10, 30),
    )
    assert session.total_duration_minutes == 0.0
    assert session.context_switches == 0
    assert session.friction_level == FrictionLevel.LOW
    assert not session.user_validated


def test_classification_question():
    q = ClassificationQuestion(
        session_id="abc",
        question="What were you doing?",
        options=["Research", "Code review", "Slack browsing"],
    )
    assert len(q.options) == 3
    assert not q.answered


def test_workflow_diagnosis():
    diag = WorkflowDiagnosis(
        session_id="abc",
        intent="competitive research",
        total_time_minutes=45.0,
        friction_points=["manual copy-paste", "tab switching"],
        estimated_cost_usd=56.25,
        automation_potential=0.7,
    )
    assert diag.automation_potential == 0.7
    assert len(diag.friction_points) == 2


def test_replacement_proposal():
    prop = ReplacementProposal(
        diagnosis_id="diag1",
        original_workflow="Manual browser research + copy to Notion",
        proposed_workflow="Agenticom research-and-summarize workflow",
        mechanism="LLM agent scrapes sources, generates structured brief, saves to Notion via API",
        estimated_time_after_minutes=5.0,
        estimated_savings_minutes_per_week=160.0,
        confidence=0.8,
    )
    assert prop.estimated_savings_minutes_per_week == 160.0
    assert "Agenticom" in prop.proposed_workflow
