"""Tests for intent inference — retry logic, JSON parsing, fence stripping."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from workflowx.inference.intent import _strip_fences, infer_intent
from workflowx.models import EventSource, FrictionLevel, RawEvent, WorkflowSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(session_id: str = "abc123") -> WorkflowSession:
    base = datetime(2026, 2, 26, 10, 0)
    events = [
        RawEvent(
            timestamp=base,
            source=EventSource.SCREENPIPE,
            app_name="VSCode",
            window_title="main.py",
            ocr_text="def foo(): pass",
        )
    ]
    return WorkflowSession(
        id=session_id,
        start_time=base,
        end_time=base,
        events=events,
        apps_used=["VSCode"],
        total_duration_minutes=30.0,
        context_switches=5,
        friction_level=FrictionLevel.HIGH,
    )


def _anthropic_client(response_text: str) -> MagicMock:
    """Mock Anthropic client returning a fixed text response."""
    client = MagicMock()
    client.messages = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    client.messages.create = AsyncMock(return_value=msg)
    return client


def _valid_json_response(intent: str = "Test intent", confidence: float = 0.8) -> str:
    return json.dumps({
        "intent": intent,
        "friction_points": ["point A", "point B"],
        "confidence": confidence,
        "question": None,
    })


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------

def test_strip_fences_plain():
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_block():
    s = "```json\n{\"a\": 1}\n```"
    assert _strip_fences(s) == '{"a": 1}'


def test_strip_fences_plain_block():
    s = "```\n{\"a\": 1}\n```"
    assert _strip_fences(s) == '{"a": 1}'


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_infer_intent_success():
    """Clean JSON response → session fields populated."""
    client = _anthropic_client(_valid_json_response("Write unit tests", 0.85))
    session = _make_session()
    result_session, question = asyncio.run(infer_intent(session, client))

    assert result_session.inferred_intent == "Write unit tests"
    assert result_session.confidence == 0.85
    assert question is None  # confidence >= 0.7, no question


def test_infer_intent_with_question_low_confidence():
    """Confidence < 0.7 + question present → ClassificationQuestion returned."""
    response = json.dumps({
        "intent": "Debug audio issue",
        "friction_points": [],
        "confidence": 0.5,
        "question": {"text": "What were you testing?", "options": ["a", "b", "c"]},
    })
    client = _anthropic_client(response)
    session = _make_session()
    _, question = asyncio.run(infer_intent(session, client))

    assert question is not None
    assert question.question == "What were you testing?"


def test_infer_intent_strips_markdown_fences():
    """LLM wrapping response in ```json``` fences is handled."""
    raw = f"```json\n{_valid_json_response()}\n```"
    client = _anthropic_client(raw)
    session = _make_session()
    result, _ = asyncio.run(infer_intent(session, client))
    assert result.inferred_intent != "inference_failed"


# ---------------------------------------------------------------------------
# Retry on truncated JSON
# ---------------------------------------------------------------------------

def test_infer_intent_retries_on_json_truncation():
    """Truncated JSON on attempt 0 → retry on attempt 1 → success."""
    truncated = '{"intent": "Build dashboard", "friction_points": ["missing close'
    valid = _valid_json_response("Build dashboard after retry", 0.9)

    client = MagicMock()
    client.messages = MagicMock()
    msg_fail = MagicMock()
    msg_fail.content = [MagicMock(text=truncated)]
    msg_ok = MagicMock()
    msg_ok.content = [MagicMock(text=valid)]
    client.messages.create = AsyncMock(side_effect=[msg_fail, msg_ok])

    session = _make_session()
    result, _ = asyncio.run(infer_intent(session, client))

    assert result.inferred_intent == "Build dashboard after retry"
    assert client.messages.create.call_count == 2  # one retry happened


def test_infer_intent_fails_after_two_truncations():
    """Two consecutive truncations → inference_failed, not an exception."""
    truncated = '{"intent": "something", "friction'

    client = MagicMock()
    client.messages = MagicMock()
    bad_msg = MagicMock()
    bad_msg.content = [MagicMock(text=truncated)]
    client.messages.create = AsyncMock(return_value=bad_msg)

    session = _make_session()
    result, question = asyncio.run(infer_intent(session, client))

    assert result.inferred_intent == "inference_failed"
    assert result.confidence == 0.0
    assert question is None
    assert client.messages.create.call_count == 2


def test_infer_intent_no_retry_on_non_json_error():
    """Network/auth errors don't trigger retry — fail immediately."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("connection refused"))

    session = _make_session()
    result, _ = asyncio.run(infer_intent(session, client))

    assert result.inferred_intent == "inference_failed"
    assert client.messages.create.call_count == 1  # no retry


def test_retry_uses_larger_token_budget():
    """Second attempt uses max_tokens=1200, first uses 1024."""
    truncated = '{"intent": "x", "friction'
    valid = _valid_json_response("x", 0.8)

    client = MagicMock()
    client.messages = MagicMock()
    bad = MagicMock()
    bad.content = [MagicMock(text=truncated)]
    ok = MagicMock()
    ok.content = [MagicMock(text=valid)]
    client.messages.create = AsyncMock(side_effect=[bad, ok])

    session = _make_session()
    asyncio.run(infer_intent(session, client))

    calls = client.messages.create.call_args_list
    assert calls[0].kwargs["max_tokens"] == 1024
    assert calls[1].kwargs["max_tokens"] == 1200
