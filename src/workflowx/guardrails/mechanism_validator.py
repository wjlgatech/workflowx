"""Validates that a mechanism is specific, not vague hand-waving."""

from workflowx.models import ReplacementProposal


# Patterns that indicate vague, unspecific mechanisms
VAGUE_MECHANISM_PATTERNS = [
    "leverage ai",
    "use automation",
    "automate this",
    "streamline the process",
    "use llm to handle",
    "ai can",
    "simply use",
    "just create an agent",
]

# Known tools that count as concrete implementations
KNOWN_TOOLS = [
    "claude",
    "gpt",
    "python",
    "zapier",
    "make.com",
    "slack api",
    "gmail api",
    "notion api",
    "github api",
    "openai",
    "anthropic",
    "cron",
    "webhook",
    "script",
    "selenium",
    "playwright",
    "browserbase",
    "recall.ai",
]


class MechanismValidator:
    """Validates that a mechanism is concrete and specific."""

    @staticmethod
    def validate(proposal: ReplacementProposal) -> tuple[bool, str]:
        """Validate a proposal's mechanism.

        Args:
            proposal: The replacement proposal to validate.

        Returns:
            (True, "OK") if mechanism is valid.
            (False, reason) if mechanism is vague or lacks concrete tools.
        """
        mechanism = proposal.mechanism.lower()

        # Check for vague patterns
        for pattern in VAGUE_MECHANISM_PATTERNS:
            if pattern in mechanism:
                return (False, f"Mechanism is too vague: contains '{pattern}'")

        # Check for at least one named tool
        has_tool = any(tool.lower() in mechanism for tool in KNOWN_TOOLS)
        if not has_tool:
            return (False, "Mechanism must mention at least one named tool (e.g., Claude, Python, Slack API)")

        return (True, "OK")
