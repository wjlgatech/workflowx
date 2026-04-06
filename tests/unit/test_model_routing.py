"""Tests for model selection and cost tracking."""

import os
import pytest

from workflowx.reasoning import DecisionType, select_model, log_model_call
from workflowx.reasoning.cost_logger import get_tracker, reset_tracker


class TestDecisionType:
    """Test DecisionType enum."""

    def test_all_decision_types_exist(self):
        """Test that all expected decision types are defined."""
        assert DecisionType.INTENT_INFERENCE
        assert DecisionType.FRICTION_CLASSIFY
        assert DecisionType.PROPOSAL_GENERATION
        assert DecisionType.SAVINGS_ESTIMATE
        assert DecisionType.PATTERN_SYNTHESIS
        assert DecisionType.WEEKLY_NARRATIVE
        assert DecisionType.STUCK_INTENT_PROPOSAL
        assert DecisionType.MULTI_SYSTEM_DIAGNOSIS

    def test_decision_type_values(self):
        """Test that decision type values are strings."""
        for decision_type in DecisionType:
            assert isinstance(decision_type.value, str)
            assert len(decision_type.value) > 0


class TestSelectModel:
    """Test model selection logic."""

    def test_select_model_anthropic_intent(self):
        """Test that intent inference selects Haiku."""
        model = select_model(DecisionType.INTENT_INFERENCE, provider="anthropic")
        assert model == "claude-haiku-4-5-20251001"

    def test_select_model_anthropic_friction(self):
        """Test that friction classification selects Haiku."""
        model = select_model(DecisionType.FRICTION_CLASSIFY, provider="anthropic")
        assert model == "claude-haiku-4-5-20251001"

    def test_select_model_anthropic_proposal(self):
        """Test that proposal generation selects Sonnet."""
        model = select_model(
            DecisionType.PROPOSAL_GENERATION, provider="anthropic"
        )
        assert model == "claude-sonnet-4-5-20250929"

    def test_select_model_anthropic_stuck(self):
        """Test that stuck intent proposals select Opus."""
        model = select_model(
            DecisionType.STUCK_INTENT_PROPOSAL, provider="anthropic"
        )
        assert model == "claude-opus-4-5-20251101"

    def test_select_model_anthropic_multi_system(self):
        """Test that multi-system diagnosis selects Opus."""
        model = select_model(
            DecisionType.MULTI_SYSTEM_DIAGNOSIS, provider="anthropic"
        )
        assert model == "claude-opus-4-5-20251101"

    def test_select_model_openai_intent(self):
        """Test OpenAI intent model."""
        model = select_model(DecisionType.INTENT_INFERENCE, provider="openai")
        assert model == "gpt-4o-mini"

    def test_select_model_openai_proposal(self):
        """Test OpenAI proposal model."""
        model = select_model(
            DecisionType.PROPOSAL_GENERATION, provider="openai"
        )
        assert model == "gpt-4o"

    def test_select_model_openai_stuck(self):
        """Test OpenAI stuck intent model."""
        model = select_model(
            DecisionType.STUCK_INTENT_PROPOSAL, provider="openai"
        )
        assert model == "o3"

    def test_select_model_override(self):
        """Test explicit model override parameter."""
        model = select_model(
            DecisionType.INTENT_INFERENCE,
            provider="anthropic",
            override="custom-model-xyz",
        )
        assert model == "custom-model-xyz"

    def test_select_model_env_override(self):
        """Test WORKFLOWX_MODEL_OVERRIDE environment variable."""
        # Save original env
        original = os.environ.get("WORKFLOWX_MODEL_OVERRIDE")

        try:
            os.environ["WORKFLOWX_MODEL_OVERRIDE"] = "env-override-model"
            model = select_model(
                DecisionType.INTENT_INFERENCE, provider="anthropic"
            )
            assert model == "env-override-model"
        finally:
            # Restore original env
            if original is not None:
                os.environ["WORKFLOWX_MODEL_OVERRIDE"] = original
            else:
                os.environ.pop("WORKFLOWX_MODEL_OVERRIDE", None)

    def test_select_model_fallback(self):
        """Test fallback to standard tier for unknown decision type."""
        # This test would need to use a decision type not in routing,
        # so we'll create a mock one indirectly
        # For now, we verify that all defined types have routing
        for decision_type in DecisionType:
            model = select_model(decision_type, provider="anthropic")
            assert model is not None
            assert len(model) > 0


class TestCostLogger:
    """Test cost tracking."""

    def setup_method(self):
        """Reset tracker before each test."""
        reset_tracker()

    def test_log_model_call_basic(self):
        """Test basic model call logging."""
        record = log_model_call(
            model="claude-sonnet-4-5-20250929",
            decision_type="test_decision",
            input_tokens=1000,
            output_tokens=500,
            duration_ms=1500.0,
        )

        assert record.model == "claude-sonnet-4-5-20250929"
        assert record.decision_type == "test_decision"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.duration_ms == 1500.0
        assert record.cost_usd > 0

    def test_cost_calculation_sonnet(self):
        """Test cost calculation for Sonnet model."""
        record = log_model_call(
            model="claude-sonnet-4-5-20250929",
            decision_type="test",
            input_tokens=1_000_000,  # 1M tokens
            output_tokens=1_000_000,  # 1M tokens
        )

        # Input: 1M * 3.00 = 3.00, Output: 1M * 15.00 = 15.00
        expected_cost = 3.00 + 15.00
        assert abs(record.cost_usd - expected_cost) < 0.01

    def test_cost_calculation_haiku(self):
        """Test cost calculation for Haiku model."""
        record = log_model_call(
            model="claude-haiku-4-5-20251001",
            decision_type="test",
            input_tokens=1_000_000,  # 1M tokens
            output_tokens=1_000_000,  # 1M tokens
        )

        # Input: 1M * 0.80 = 0.80, Output: 1M * 4.00 = 4.00
        expected_cost = 0.80 + 4.00
        assert abs(record.cost_usd - expected_cost) < 0.01

    def test_cost_calculation_opus(self):
        """Test cost calculation for Opus model."""
        record = log_model_call(
            model="claude-opus-4-5-20251101",
            decision_type="test",
            input_tokens=1_000_000,  # 1M tokens
            output_tokens=1_000_000,  # 1M tokens
        )

        # Input: 1M * 15.00 = 15.00, Output: 1M * 75.00 = 75.00
        expected_cost = 15.00 + 75.00
        assert abs(record.cost_usd - expected_cost) < 0.01

    def test_cost_tracker_accumulates(self):
        """Test that cost tracker accumulates multiple calls."""
        reset_tracker()

        log_model_call(
            model="claude-haiku-4-5-20251001",
            decision_type="intent",
            input_tokens=1000,
            output_tokens=500,
        )
        log_model_call(
            model="claude-sonnet-4-5-20250929",
            decision_type="proposal",
            input_tokens=5000,
            output_tokens=2000,
        )

        tracker = get_tracker()
        assert tracker.total_calls == 2
        assert tracker.total_cost > 0

    def test_cost_tracker_summary_by_type(self):
        """Test cost breakdown by decision type."""
        reset_tracker()

        log_model_call(
            model="claude-haiku-4-5-20251001",
            decision_type="intent_inference",
            input_tokens=1000,
            output_tokens=500,
        )
        log_model_call(
            model="claude-sonnet-4-5-20250929",
            decision_type="proposal_generation",
            input_tokens=5000,
            output_tokens=2000,
        )

        tracker = get_tracker()
        summary = tracker.summary_by_type()

        assert "intent_inference" in summary
        assert "proposal_generation" in summary
        assert summary["intent_inference"] > 0
        assert summary["proposal_generation"] > summary["intent_inference"]

    def test_cost_tracker_reset(self):
        """Test that reset clears all records."""
        log_model_call(
            model="claude-sonnet-4-5-20250929",
            decision_type="test",
            input_tokens=1000,
            output_tokens=500,
        )

        tracker = get_tracker()
        assert tracker.total_calls == 1

        reset_tracker()
        tracker = get_tracker()
        assert tracker.total_calls == 0
        assert tracker.total_cost == 0

    def test_format_summary_empty(self):
        """Test summary formatting for empty tracker."""
        reset_tracker()
        tracker = get_tracker()
        summary = tracker.format_summary()
        assert "No model calls recorded" in summary

    def test_format_summary_with_calls(self):
        """Test summary formatting with logged calls."""
        reset_tracker()

        log_model_call(
            model="claude-haiku-4-5-20251001",
            decision_type="intent",
            input_tokens=1000,
            output_tokens=500,
        )

        tracker = get_tracker()
        summary = tracker.format_summary()

        assert "Model calls: 1" in summary
        assert "intent" in summary
        assert "$" in summary  # Should include cost

    def test_zero_token_cost(self):
        """Test handling of zero token costs."""
        record = log_model_call(
            model="claude-haiku-4-5-20251001",
            decision_type="test",
            input_tokens=0,
            output_tokens=0,
        )

        assert record.cost_usd == 0.0

    def test_unknown_model_cost(self):
        """Test handling of unknown model names."""
        record = log_model_call(
            model="unknown-model-xyz",
            decision_type="test",
            input_tokens=1000,
            output_tokens=500,
        )

        # Should still create a record, cost will be 0
        assert record.cost_usd == 0.0
        assert record.model == "unknown-model-xyz"

    def test_cost_tracker_record_order(self):
        """Test that records are stored in order."""
        reset_tracker()

        log_model_call(
            model="claude-haiku-4-5-20251001",
            decision_type="first",
            input_tokens=100,
        )
        log_model_call(
            model="claude-sonnet-4-5-20250929",
            decision_type="second",
            input_tokens=200,
        )

        tracker = get_tracker()
        assert tracker.records[0].decision_type == "first"
        assert tracker.records[1].decision_type == "second"
