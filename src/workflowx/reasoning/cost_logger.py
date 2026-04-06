"""Cost tracking for LLM calls.

Logs and accumulates model call costs with per-decision-type breakdowns.
Approximate costs as of March 2026.
"""

import logging
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)


# Approximate costs per 1M input tokens (USD, as of March 2026)
COST_PER_1M_INPUT = {
    # Anthropic
    "claude-haiku-4-5-20251001": 0.80,
    "claude-sonnet-4-5-20250929": 3.00,
    "claude-opus-4-5-20251101": 15.00,
    # Shorthand aliases
    "claude-haiku": 0.80,
    "claude-sonnet": 3.00,
    "claude-opus": 15.00,
    # OpenAI
    "gpt-4o-mini": 0.15,
    "gpt-4o": 2.50,
    "o4-mini": 1.10,
    "o3": 15.00,
}

COST_PER_1M_OUTPUT = {
    "claude-haiku-4-5-20251001": 4.00,
    "claude-sonnet-4-5-20250929": 15.00,
    "claude-opus-4-5-20251101": 75.00,
    "claude-haiku": 4.00,
    "claude-sonnet": 15.00,
    "claude-opus": 75.00,
    "gpt-4o-mini": 0.60,
    "gpt-4o": 10.00,
    "o4-mini": 4.40,
    "o3": 60.00,
}


@dataclass
class ModelCallRecord:
    """Record of a single model call with costs."""

    model: str
    decision_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: float


@dataclass
class CostTracker:
    """Tracks cumulative model call costs within a session."""

    records: list[ModelCallRecord] = field(default_factory=list)

    def add(self, record: ModelCallRecord):
        """Add a record to the tracker."""
        self.records.append(record)

    @property
    def total_cost(self) -> float:
        """Total cost across all records."""
        return sum(r.cost_usd for r in self.records)

    @property
    def total_calls(self) -> int:
        """Total number of model calls."""
        return len(self.records)

    def summary_by_type(self) -> dict[str, float]:
        """Get cost breakdown by decision type."""
        result = {}
        for r in self.records:
            result[r.decision_type] = result.get(r.decision_type, 0) + r.cost_usd
        return result

    def format_summary(self) -> str:
        """Format cost summary as readable text."""
        if not self.records:
            return "No model calls recorded."

        lines = [
            f"Model calls: {self.total_calls} | Total cost: ${self.total_cost:.4f}"
        ]
        for dtype, cost in self.summary_by_type().items():
            lines.append(f"  {dtype}: ${cost:.4f}")
        return "\n".join(lines)


# Global tracker (reset per pipeline run)
_tracker = CostTracker()


def get_tracker() -> CostTracker:
    """Get the global cost tracker."""
    return _tracker


def reset_tracker():
    """Reset the global cost tracker."""
    global _tracker
    _tracker = CostTracker()


def log_model_call(
    model: str,
    decision_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: float = 0.0,
) -> ModelCallRecord:
    """Log a model call with estimated cost.

    Args:
        model: Model identifier (e.g., "claude-sonnet-4-5-20250929").
        decision_type: Type of decision being made.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        duration_ms: Call duration in milliseconds.

    Returns:
        ModelCallRecord with the logged information.
    """
    input_cost = (input_tokens / 1_000_000) * COST_PER_1M_INPUT.get(model, 0)
    output_cost = (output_tokens / 1_000_000) * COST_PER_1M_OUTPUT.get(model, 0)
    total_cost = input_cost + output_cost

    record = ModelCallRecord(
        model=model,
        decision_type=decision_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )

    _tracker.add(record)

    logger.info(
        f"MODEL_CALL model={model} decision={decision_type} "
        f"tokens={input_tokens}+{output_tokens} cost=${total_cost:.4f} "
        f"duration={duration_ms:.0f}ms"
    )

    return record
