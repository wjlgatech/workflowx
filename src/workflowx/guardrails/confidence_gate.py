"""Confidence floor gate — suppresses low-confidence proposals."""

from workflowx.models import ReplacementProposal


def apply_confidence_floor(proposal: ReplacementProposal, floor: float = 0.55) -> tuple[bool, str]:
    """Check if proposal meets minimum confidence threshold.

    Args:
        proposal: The replacement proposal to validate.
        floor: Minimum confidence required (default 0.55).

    Returns:
        (True, "OK") if confidence >= floor.
        (False, "suppressed") if confidence < floor.
    """
    if proposal.confidence < floor:
        return (False, "suppressed")
    return (True, "OK")
