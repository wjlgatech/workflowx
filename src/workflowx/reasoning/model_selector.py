"""Model selection based on decision complexity.

Routes different types of decisions to appropriate model tiers:
- Fast path: intent inference, friction classification → Haiku/4o-mini
- Standard path: proposals, analysis → Sonnet/4o
- Complex path: stuck intents, multi-system diagnosis → Opus/o3
"""

from enum import Enum
import os
import logging

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    """Types of decisions that require model calls."""

    # Fast path — lightweight model
    INTENT_INFERENCE = "intent_inference"
    FRICTION_CLASSIFY = "friction_classify"

    # Standard path — balanced model
    PROPOSAL_GENERATION = "proposal_generation"
    SAVINGS_ESTIMATE = "savings_estimate"
    PATTERN_SYNTHESIS = "pattern_synthesis"
    WEEKLY_NARRATIVE = "weekly_narrative"

    # Complex path — strongest model
    STUCK_INTENT_PROPOSAL = "stuck_intent"
    MULTI_SYSTEM_DIAGNOSIS = "multi_system"


# Anthropic-native routing (no OpenAI dependency)
ANTHROPIC_ROUTING = {
    DecisionType.INTENT_INFERENCE: "claude-haiku-4-5-20251001",
    DecisionType.FRICTION_CLASSIFY: "claude-haiku-4-5-20251001",
    DecisionType.PROPOSAL_GENERATION: "claude-sonnet-4-5-20250929",
    DecisionType.SAVINGS_ESTIMATE: "claude-sonnet-4-5-20250929",
    DecisionType.PATTERN_SYNTHESIS: "claude-sonnet-4-5-20250929",
    DecisionType.WEEKLY_NARRATIVE: "claude-sonnet-4-5-20250929",
    DecisionType.STUCK_INTENT_PROPOSAL: "claude-opus-4-5-20251101",
    DecisionType.MULTI_SYSTEM_DIAGNOSIS: "claude-opus-4-5-20251101",
}

# OpenAI routing (alternative)
OPENAI_ROUTING = {
    DecisionType.INTENT_INFERENCE: "gpt-4o-mini",
    DecisionType.FRICTION_CLASSIFY: "gpt-4o-mini",
    DecisionType.PROPOSAL_GENERATION: "gpt-4o",
    DecisionType.SAVINGS_ESTIMATE: "gpt-4o",
    DecisionType.PATTERN_SYNTHESIS: "o4-mini",
    DecisionType.WEEKLY_NARRATIVE: "o4-mini",
    DecisionType.STUCK_INTENT_PROPOSAL: "o3",
    DecisionType.MULTI_SYSTEM_DIAGNOSIS: "o3",
}


def select_model(
    decision_type: DecisionType,
    provider: str = "anthropic",
    override: str | None = None,
) -> str:
    """Select the appropriate model for a decision type.

    Routes decisions to the right model tier based on complexity:
    - Fast decisions → Haiku/4o-mini (cheapest, fastest)
    - Standard decisions → Sonnet/4o (balanced)
    - Complex decisions → Opus/o3 (strongest reasoning)

    Args:
        decision_type: What kind of decision is being made.
        provider: "anthropic" or "openai".
        override: Explicit model override (env var WORKFLOWX_MODEL_OVERRIDE).

    Returns:
        Model identifier string.
    """
    # Check env override first
    env_override = os.environ.get("WORKFLOWX_MODEL_OVERRIDE")
    if env_override:
        logger.info(
            f"Model override from env: {env_override} (was: {decision_type.value})"
        )
        return env_override

    if override:
        return override

    routing = ANTHROPIC_ROUTING if provider == "anthropic" else OPENAI_ROUTING
    model = routing.get(decision_type)

    if model is None:
        # Fallback to standard tier
        model = routing[DecisionType.PROPOSAL_GENERATION]
        logger.warning(
            f"No routing for {decision_type}, falling back to {model}"
        )

    return model
