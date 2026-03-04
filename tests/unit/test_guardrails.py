"""Unit tests for guardrails module."""

import pytest
from datetime import datetime

from workflowx.models import ReplacementProposal, WorkflowSession, FrictionLevel
from workflowx.guardrails import (
    MechanismValidator,
    SavingsEstimateValidator,
    apply_confidence_floor,
)


# Helper to create a minimal valid session
def create_test_session(duration_minutes: float = 30) -> WorkflowSession:
    """Create a minimal valid WorkflowSession for testing."""
    now = datetime.now()
    return WorkflowSession(
        id="test-session",
        start_time=now,
        end_time=now,
        total_duration_minutes=duration_minutes,
        apps_used=["Slack", "Gmail"],
        context_switches=5,
        friction_level=FrictionLevel.HIGH,
        friction_details="Context switching between multiple tools",
    )


class TestMechanismValidator:
    """Test MechanismValidator."""

    def test_mechanism_valid_proposal(self):
        """Valid proposal with concrete tool mention should pass."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Read Slack messages",
            proposed_workflow="Automated Slack reader",
            mechanism="Python script reads Slack API directly and filters by keywords",
            estimated_time_after_minutes=5.0,
            estimated_savings_minutes_per_week=100.0,
            confidence=0.8,
        )
        passed, reason = MechanismValidator.validate(proposal)
        assert passed is True
        assert reason == "OK"

    def test_mechanism_vague_leverage_ai(self):
        """Vague mechanism with 'leverage ai' should fail."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Email processing",
            proposed_workflow="AI-powered email processor",
            mechanism="Leverage AI to automate email classification",
            estimated_time_after_minutes=5.0,
            estimated_savings_minutes_per_week=50.0,
            confidence=0.7,
        )
        passed, reason = MechanismValidator.validate(proposal)
        assert passed is False
        assert "vague" in reason.lower()

    def test_mechanism_vague_streamline(self):
        """Vague mechanism with 'streamline the process' should fail."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Report generation",
            proposed_workflow="Streamlined reports",
            mechanism="Streamline the process with automation",
            estimated_time_after_minutes=10.0,
            estimated_savings_minutes_per_week=60.0,
            confidence=0.6,
        )
        passed, reason = MechanismValidator.validate(proposal)
        assert passed is False
        assert "vague" in reason.lower()

    def test_mechanism_no_named_tool(self):
        """Mechanism with no known tool should fail."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Data processing",
            proposed_workflow="Automated data processing",
            mechanism="Use software to process and transform the data",
            estimated_time_after_minutes=5.0,
            estimated_savings_minutes_per_week=40.0,
            confidence=0.7,
        )
        passed, reason = MechanismValidator.validate(proposal)
        assert passed is False
        assert "named tool" in reason.lower()

    def test_mechanism_multiple_tools(self):
        """Mechanism mentioning multiple tools should pass."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Data pipeline",
            proposed_workflow="Automated pipeline",
            mechanism="Python script uses GitHub API to fetch repos, then Claude analyzes code quality",
            estimated_time_after_minutes=15.0,
            estimated_savings_minutes_per_week=75.0,
            confidence=0.85,
        )
        passed, reason = MechanismValidator.validate(proposal)
        assert passed is True
        assert reason == "OK"


class TestSavingsEstimateValidator:
    """Test SavingsEstimateValidator."""

    def test_savings_valid(self):
        """Valid savings estimate should pass."""
        session = create_test_session(duration_minutes=30)
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Manual task",
            proposed_workflow="Automated task",
            mechanism="Python script reads Slack API",
            estimated_time_after_minutes=10.0,
            estimated_savings_minutes_per_week=80.0,
            confidence=0.8,
        )
        passed, reason = SavingsEstimateValidator.validate(proposal, session)
        assert passed is True
        assert reason == "OK"

    def test_savings_after_exceeds_before(self):
        """Replacement slower than original should fail."""
        session = create_test_session(duration_minutes=30)
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Manual task",
            proposed_workflow="Automated task",
            mechanism="Python script reads Slack API",
            estimated_time_after_minutes=50.0,  # Slower than original!
            estimated_savings_minutes_per_week=0.0,
            confidence=0.7,
        )
        passed, reason = SavingsEstimateValidator.validate(proposal, session)
        assert passed is False
        assert "must be faster" in reason.lower()

    def test_savings_inflated_3x(self):
        """Savings exceeding 3× weekly observed should fail."""
        session = create_test_session(duration_minutes=30)
        # 30 min * 4 (weekly) = 120 min/week observed
        # 3× = 360 min/week max savings
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Manual task",
            proposed_workflow="Automated task",
            mechanism="Python script reads Slack API",
            estimated_time_after_minutes=5.0,
            estimated_savings_minutes_per_week=500.0,  # Too high!
            confidence=0.8,
        )
        passed, reason = SavingsEstimateValidator.validate(proposal, session)
        assert passed is False
        assert "exceed" in reason.lower()

    def test_savings_outlier_capped(self):
        """Session > 120 min should be capped at 120 min."""
        session = create_test_session(duration_minutes=200)
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Long task",
            proposed_workflow="Automated task",
            mechanism="Python script reads Slack API",
            estimated_time_after_minutes=60.0,
            estimated_savings_minutes_per_week=180.0,  # 120 * 4 * 3 = 1440 max, so 180 is OK
            confidence=0.8,
        )
        passed, reason = SavingsEstimateValidator.validate(proposal, session)
        assert passed is True
        assert reason == "OK"


class TestConfidenceFloor:
    """Test apply_confidence_floor function."""

    def test_confidence_floor_pass(self):
        """Confidence 0.7 above floor should pass."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Task",
            proposed_workflow="Automated task",
            mechanism="Python script",
            estimated_time_after_minutes=10.0,
            estimated_savings_minutes_per_week=50.0,
            confidence=0.7,
        )
        passed, reason = apply_confidence_floor(proposal, floor=0.55)
        assert passed is True
        assert reason == "OK"

    def test_confidence_floor_fail(self):
        """Confidence 0.3 below floor should fail."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Task",
            proposed_workflow="Automated task",
            mechanism="Python script",
            estimated_time_after_minutes=10.0,
            estimated_savings_minutes_per_week=50.0,
            confidence=0.3,
        )
        passed, reason = apply_confidence_floor(proposal, floor=0.55)
        assert passed is False
        assert reason == "suppressed"

    def test_confidence_floor_exact(self):
        """Confidence exactly at floor should pass."""
        proposal = ReplacementProposal(
            diagnosis_id="diag-1",
            original_workflow="Task",
            proposed_workflow="Automated task",
            mechanism="Python script",
            estimated_time_after_minutes=10.0,
            estimated_savings_minutes_per_week=50.0,
            confidence=0.55,
        )
        passed, reason = apply_confidence_floor(proposal, floor=0.55)
        assert passed is True
        assert reason == "OK"
