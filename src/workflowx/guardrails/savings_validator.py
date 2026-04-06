"""Validates that savings estimates are realistic and don't contradict observed data."""

from workflowx.models import ReplacementProposal, WorkflowSession


class SavingsEstimateValidator:
    """Validates that savings estimates are grounded in reality."""

    @staticmethod
    def validate(proposal: ReplacementProposal, session: WorkflowSession) -> tuple[bool, str]:
        """Validate a proposal's savings estimates.

        Args:
            proposal: The replacement proposal to validate.
            session: The original workflow session.

        Returns:
            (True, "OK") if savings estimates are valid.
            (False, reason) if they violate bounds.
        """
        # Cap outlier sessions at 120 minutes
        observed_time = min(session.total_duration_minutes, 120.0)

        # estimated_time_after must be < observed time
        if proposal.estimated_time_after_minutes >= observed_time:
            return (
                False,
                f"Replacement ({proposal.estimated_time_after_minutes:.0f}m) must be faster "
                f"than original ({observed_time:.0f}m)",
            )

        # Calculate weekly observed (default 4x per week)
        weekly_observed = observed_time * 4  # Default frequency

        # estimated_savings_minutes_per_week must not exceed 3× weekly observed
        max_savings = weekly_observed * 3
        if proposal.estimated_savings_minutes_per_week > max_savings:
            return (
                False,
                f"Savings ({proposal.estimated_savings_minutes_per_week:.0f}m/week) exceed "
                f"3× weekly observed ({max_savings:.0f}m/week)",
            )

        return (True, "OK")
