"""Proposal history tracking with similarity search.

Local proposal history with no cloud dependencies. Uses string similarity
to find past proposals with similar intents and track rejection patterns.
"""

from difflib import SequenceMatcher
import logging

from workflowx.models import ReplacementOutcome

logger = logging.getLogger(__name__)


class ProposalHistory:
    """Local proposal history with similarity search. No cloud dependencies."""

    SIMILARITY_THRESHOLD = 0.55

    def __init__(self, outcomes: list[ReplacementOutcome]):
        """Initialize with a list of past outcomes.

        Args:
            outcomes: List of ReplacementOutcome objects to track.
        """
        self.outcomes = outcomes

    def find_similar(self, intent: str, top_k: int = 3) -> list[ReplacementOutcome]:
        """Find past outcomes with similar intents using string similarity.

        Args:
            intent: The intent to search for.
            top_k: Maximum number of similar outcomes to return.

        Returns:
            List of ReplacementOutcome objects with similar intents, ranked by similarity.
        """
        scored = []
        for outcome in self.outcomes:
            sim = SequenceMatcher(None, intent.lower(), outcome.intent.lower()).ratio()
            if sim >= self.SIMILARITY_THRESHOLD:
                scored.append((sim, outcome))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [outcome for _, outcome in scored[:top_k]]

    def rejection_count(self, intent: str) -> int:
        """Count how many similar proposals were rejected.

        Args:
            intent: The intent to count rejections for.

        Returns:
            Number of similar outcomes with status="rejected".
        """
        similar = self.find_similar(intent)
        return sum(1 for o in similar if o.status == "rejected")

    def is_stuck_intent(self, intent: str, threshold: int = 3) -> bool:
        """Check if an intent has too many rejections.

        Args:
            intent: The intent to check.
            threshold: Number of rejections that indicates "stuck" (default: 3).

        Returns:
            True if rejection_count >= threshold.
        """
        return self.rejection_count(intent) >= threshold

    def get_rejection_reasons(self, intent: str) -> list[str]:
        """Get rejection reasons for similar past proposals.

        Args:
            intent: The intent to get rejection reasons for.

        Returns:
            List of rejection reason strings (e.g., ["too_complex", "wrong_tools"]).
        """
        similar = self.find_similar(intent)
        reasons = []
        for o in similar:
            if o.status == "rejected" and o.rejection_reason:
                reason_val = (
                    o.rejection_reason.value
                    if hasattr(o.rejection_reason, "value")
                    else str(o.rejection_reason)
                )
                reasons.append(reason_val)
        return reasons

    def build_history_context(self, intent: str) -> str:
        """Build context string for LLM about past proposals for this intent.

        Args:
            intent: The intent to build context for.

        Returns:
            Formatted string describing past proposals for this intent, or empty string if none found.
        """
        similar = self.find_similar(intent)
        if not similar:
            return ""

        lines = [f"PROPOSAL HISTORY ({len(similar)} similar past proposals):"]
        for o in similar:
            status = o.status
            if status == "rejected" and o.rejection_reason:
                reason_val = (
                    o.rejection_reason.value
                    if hasattr(o.rejection_reason, "value")
                    else str(o.rejection_reason)
                )
                status = f"rejected ({reason_val})"
            lines.append(f"  - Intent: {o.intent} | Status: {status}")
            if o.rejection_notes:
                lines.append(f"    Notes: {o.rejection_notes}")

        return "\n".join(lines)
