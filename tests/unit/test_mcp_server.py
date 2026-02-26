"""Tests for MCP server handlers — verifies the agentic loop works."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from workflowx.mcp_server import (
    TOOL_REGISTRY,
    handle_adopt,
    handle_capture,
    handle_diagnose_workflow,
    handle_get_friction,
    handle_get_patterns,
    handle_get_roi,
    handle_get_sessions,
    handle_get_trends,
    handle_measure,
    handle_status,
)
from workflowx.models import FrictionLevel, WorkflowSession


# ── Fixtures ────────────────────────────────────────────────

def _make_session(intent: str, friction: FrictionLevel, minutes: float = 30.0, switches: int = 5) -> WorkflowSession:
    now = datetime.now()
    return WorkflowSession(
        id=f"test_{intent.replace(' ', '_')[:20]}",
        start_time=now - timedelta(minutes=minutes),
        end_time=now,
        events=[],
        inferred_intent=intent,
        confidence=0.9,
        apps_used=["VSCode", "Chrome"],
        total_duration_minutes=minutes,
        context_switches=switches,
        friction_level=friction,
    )


SAMPLE_SESSIONS = [
    _make_session("email triage", FrictionLevel.HIGH, 28, 12),
    _make_session("deep coding", FrictionLevel.LOW, 120, 3),
    _make_session("expense admin", FrictionLevel.CRITICAL, 45, 15),
    _make_session("PR review", FrictionLevel.MEDIUM, 35, 8),
]


# ── Registry ────────────────────────────────────────────────

def test_tool_registry_has_12_tools():
    assert len(TOOL_REGISTRY) == 12


def test_all_tools_have_handlers():
    for name, entry in TOOL_REGISTRY.items():
        assert "handler" in entry, f"{name} missing handler"
        assert callable(entry["handler"]), f"{name} handler not callable"
        assert "description" in entry, f"{name} missing description"


# ── Handlers with mocked store ──────────────────────────────

@patch("workflowx.mcp_server._sessions_for_period", return_value=SAMPLE_SESSIONS)
def test_handle_get_sessions(mock_sessions):
    result = handle_get_sessions("today")
    assert result["total_sessions"] == 4
    assert result["total_minutes"] > 0
    assert len(result["sessions"]) == 4


@patch("workflowx.mcp_server._sessions_for_period", return_value=SAMPLE_SESSIONS)
def test_handle_get_friction_filters_high(mock_sessions):
    with patch("workflowx.mcp_server._get_store") as mock_store:
        from workflowx.config import WorkflowXConfig
        mock_store.return_value = (None, WorkflowXConfig())
        result = handle_get_friction("week")
        # Should only include HIGH and CRITICAL
        assert result["high_friction_sessions"] == 2
        assert result["total_friction_minutes"] > 0


@patch("workflowx.mcp_server._sessions_for_period", return_value=SAMPLE_SESSIONS)
def test_handle_get_patterns_finds_patterns(mock_sessions):
    result = handle_get_patterns()
    assert "patterns_found" in result
    # Each unique intent = 1 pattern (min_occurrences=2 won't group singletons,
    # but the handler calls detect_patterns which handles this)
    assert isinstance(result["patterns"], list)


@patch("workflowx.mcp_server._sessions_for_period", return_value=SAMPLE_SESSIONS)
def test_handle_get_trends_returns_structure(mock_sessions):
    result = handle_get_trends()
    assert "trajectory" in result
    assert result["trajectory"] in ("stable", "improving", "worsening")


@patch("workflowx.mcp_server._get_store")
def test_handle_get_roi_empty(mock_store):
    from workflowx.config import WorkflowXConfig
    from workflowx.storage import LocalStore
    store = LocalStore(Path("/tmp/workflowx_test_mcp"))
    mock_store.return_value = (store, WorkflowXConfig())
    result = handle_get_roi()
    assert result["total_outcomes"] == 0


@patch("workflowx.mcp_server._get_store")
def test_handle_adopt_starts_tracking(mock_store):
    from workflowx.config import WorkflowXConfig
    from workflowx.storage import LocalStore
    store = LocalStore(Path("/tmp/workflowx_test_mcp_adopt"))
    mock_store.return_value = (store, WorkflowXConfig())

    result = handle_adopt("email triage", 28.0)
    assert result["status"] == "tracking_started"
    assert result["intent"] == "email triage"
    assert result["baseline_minutes_per_week"] == 28.0


@patch("workflowx.mcp_server._sessions_for_period", return_value=SAMPLE_SESSIONS)
@patch("workflowx.mcp_server._get_store")
def test_handle_diagnose_workflow(mock_store, mock_sessions):
    from workflowx.config import WorkflowXConfig
    mock_store.return_value = (None, WorkflowXConfig())
    result = handle_diagnose_workflow(0, "today")
    assert "session" in result
    assert "diagnosis" in result
    assert result["diagnosis"]["automation_potential"] >= 0


def test_handle_status_returns_structure():
    with patch("workflowx.mcp_server._get_store") as mock_store:
        from workflowx.config import WorkflowXConfig
        from workflowx.storage import LocalStore
        store = LocalStore(Path("/tmp/workflowx_test_mcp_status"))
        mock_store.return_value = (store, WorkflowXConfig())

        result = handle_status()
        assert "screenpipe_connected" in result
        assert "today_sessions" in result
        assert "data_dir" in result
