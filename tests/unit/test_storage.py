"""Tests for local JSON storage."""

from datetime import date, datetime

from workflowx.models import (
    ClassificationQuestion,
    FrictionLevel,
    WorkflowSession,
)
from workflowx.storage import LocalStore


def test_save_and_load_sessions(tmp_path):
    store = LocalStore(tmp_path)
    sessions = [
        WorkflowSession(
            id="sess1",
            start_time=datetime(2026, 2, 26, 10, 0),
            end_time=datetime(2026, 2, 26, 10, 30),
            inferred_intent="competitive research",
            total_duration_minutes=30.0,
            apps_used=["Chrome", "Notion"],
            context_switches=5,
            friction_level=FrictionLevel.MEDIUM,
        ),
        WorkflowSession(
            id="sess2",
            start_time=datetime(2026, 2, 26, 11, 0),
            end_time=datetime(2026, 2, 26, 11, 45),
            total_duration_minutes=45.0,
            apps_used=["VSCode"],
        ),
    ]

    d = date(2026, 2, 26)
    store.save_sessions(sessions, d)
    loaded = store.load_sessions(d)

    assert len(loaded) == 2
    assert loaded[0].id == "sess1"
    assert loaded[0].inferred_intent == "competitive research"
    assert loaded[1].id == "sess2"


def test_update_existing_session(tmp_path):
    store = LocalStore(tmp_path)
    d = date(2026, 2, 26)

    # Save initial session
    session = WorkflowSession(
        id="sess1",
        start_time=datetime(2026, 2, 26, 10, 0),
        end_time=datetime(2026, 2, 26, 10, 30),
        total_duration_minutes=30.0,
    )
    store.save_sessions([session], d)

    # Update with intent
    session.inferred_intent = "debugging auth flow"
    session.confidence = 0.85
    store.save_sessions([session], d)

    loaded = store.load_sessions(d)
    assert len(loaded) == 1
    assert loaded[0].inferred_intent == "debugging auth flow"


def test_classification_questions(tmp_path):
    store = LocalStore(tmp_path)

    questions = [
        ClassificationQuestion(
            session_id="sess1",
            question="What were you doing?",
            options=["Research", "Code review", "Browsing"],
        ),
    ]
    store.save_questions(questions)

    pending = store.load_pending_questions()
    assert len(pending) == 1
    assert pending[0].session_id == "sess1"

    # Answer question
    store.answer_question("sess1", "Research")
    pending = store.load_pending_questions()
    assert len(pending) == 0


def test_empty_store(tmp_path):
    store = LocalStore(tmp_path)
    assert store.load_sessions() == []
    assert store.load_pending_questions() == []
