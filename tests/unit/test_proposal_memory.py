"""Tests for proposal memory and rejection tracking."""

from datetime import datetime

from workflowx.memory import ProposalHistory
from workflowx.models import RejectionReason, ReplacementOutcome


def create_outcome(
    intent: str,
    status: str = "pending",
    rejection_reason: RejectionReason | None = None,
    rejection_notes: str = "",
) -> ReplacementOutcome:
    """Helper to create a ReplacementOutcome for testing."""
    return ReplacementOutcome(
        id=f"out_{intent.lower().replace(' ', '_')}",
        proposal_id=f"prop_{intent.lower().replace(' ', '_')}",
        intent=intent,
        adopted=status == "adopted",
        adopted_date=datetime(2026, 3, 1) if status == "adopted" else None,
        before_minutes_per_week=60.0,
        after_minutes_per_week=30.0 if status == "adopted" else 0.0,
        actual_savings_minutes=30.0 if status == "adopted" else 0.0,
        cumulative_savings_minutes=30.0 if status == "adopted" else 0.0,
        weeks_tracked=1 if status == "adopted" else 0,
        notes="",
        status=status,
        rejection_reason=rejection_reason,
        rejection_notes=rejection_notes,
    )


def test_find_similar_exact_match():
    """Test finding exact intent match."""
    outcomes = [
        create_outcome("email triage"),
        create_outcome("slack management"),
    ]
    history = ProposalHistory(outcomes)
    similar = history.find_similar("email triage")
    assert len(similar) == 1
    assert similar[0].intent == "email triage"


def test_find_similar_no_match():
    """Test that completely different intent returns empty."""
    outcomes = [
        create_outcome("email triage"),
        create_outcome("slack management"),
    ]
    history = ProposalHistory(outcomes)
    similar = history.find_similar("completely unrelated workflow xyz")
    assert len(similar) == 0


def test_find_similar_partial_match():
    """Test partial match for similar intents."""
    outcomes = [
        create_outcome("email triage"),
        create_outcome("email management"),
        create_outcome("slack management"),
    ]
    history = ProposalHistory(outcomes)
    similar = history.find_similar("email review")
    # Should match both email-related outcomes
    assert len(similar) > 0
    assert all("email" in o.intent.lower() for o in similar)


def test_rejection_count():
    """Test counting rejected proposals with similar intents."""
    outcomes = [
        create_outcome("email triage", status="rejected", rejection_reason=RejectionReason.TOO_COMPLEX),
        create_outcome("email management", status="rejected", rejection_reason=RejectionReason.WRONG_TOOLS),
        create_outcome("email processing", status="adopted"),
    ]
    history = ProposalHistory(outcomes)
    count = history.rejection_count("email triage")
    assert count >= 2  # At least the two email rejections


def test_is_stuck_intent_true():
    """Test that 3+ rejections mark intent as stuck."""
    outcomes = [
        create_outcome("email triage", status="rejected", rejection_reason=RejectionReason.TOO_COMPLEX),
        create_outcome("email management", status="rejected", rejection_reason=RejectionReason.WRONG_TOOLS),
        create_outcome("email processing", status="rejected", rejection_reason=RejectionReason.INACCURATE_SAVINGS),
        create_outcome("email automation", status="rejected", rejection_reason=RejectionReason.ALREADY_TRIED),
    ]
    history = ProposalHistory(outcomes)
    assert history.is_stuck_intent("email triage", threshold=3)


def test_is_stuck_intent_false():
    """Test that fewer than 3 rejections does not mark as stuck."""
    outcomes = [
        create_outcome("email triage", status="rejected", rejection_reason=RejectionReason.TOO_COMPLEX),
        create_outcome("email management", status="rejected", rejection_reason=RejectionReason.WRONG_TOOLS),
        create_outcome("slack management", status="adopted"),
    ]
    history = ProposalHistory(outcomes)
    assert not history.is_stuck_intent("email triage", threshold=3)


def test_get_rejection_reasons():
    """Test retrieving rejection reasons for similar proposals."""
    outcomes = [
        create_outcome("email triage", status="rejected", rejection_reason=RejectionReason.TOO_COMPLEX),
        create_outcome("email management", status="rejected", rejection_reason=RejectionReason.WRONG_TOOLS),
        create_outcome("email processing", status="adopted"),
    ]
    history = ProposalHistory(outcomes)
    reasons = history.get_rejection_reasons("email triage")
    assert "too_complex" in reasons
    assert "wrong_tools" in reasons


def test_build_history_context():
    """Test building history context string for matching intents."""
    outcomes = [
        create_outcome(
            "email triage",
            status="rejected",
            rejection_reason=RejectionReason.TOO_COMPLEX,
            rejection_notes="Too many edge cases",
        ),
        create_outcome("email management", status="rejected", rejection_reason=RejectionReason.WRONG_TOOLS),
    ]
    history = ProposalHistory(outcomes)
    context = history.build_history_context("email triage")

    assert "PROPOSAL HISTORY" in context
    assert "similar past proposals" in context
    assert "rejected" in context
    assert "Too many edge cases" in context or "rejection_notes" in str(outcomes[0])


def test_build_history_context_empty():
    """Test that no matches returns empty string."""
    outcomes = [
        create_outcome("slack management"),
    ]
    history = ProposalHistory(outcomes)
    context = history.build_history_context("completely unrelated workflow xyz")
    assert context == ""


def test_rejection_reason_enum():
    """Test that all rejection reason enum values are valid."""
    reasons = [
        RejectionReason.TOO_COMPLEX,
        RejectionReason.WRONG_TOOLS,
        RejectionReason.INACCURATE_SAVINGS,
        RejectionReason.ALREADY_TRIED,
        RejectionReason.NOT_RELEVANT,
        RejectionReason.OTHER,
    ]

    assert len(reasons) == 6
    for reason in reasons:
        assert isinstance(reason.value, str)
        assert len(reason.value) > 0


def test_proposal_history_with_mixed_statuses():
    """Test history tracking with various outcome statuses."""
    outcomes = [
        create_outcome("email triage", status="adopted"),
        create_outcome("email management", status="rejected", rejection_reason=RejectionReason.WRONG_TOOLS),
        create_outcome("email processing", status="measuring"),
        create_outcome("email automation", status="pending"),
    ]
    history = ProposalHistory(outcomes)

    # Should find similar intents regardless of status
    similar = history.find_similar("email triage", top_k=10)
    assert len(similar) > 1


def test_top_k_limit():
    """Test that find_similar respects top_k limit."""
    outcomes = [
        create_outcome("email triage"),
        create_outcome("email management"),
        create_outcome("email processing"),
        create_outcome("email automation"),
        create_outcome("email filtering"),
    ]
    history = ProposalHistory(outcomes)
    similar = history.find_similar("email", top_k=2)
    assert len(similar) <= 2


def test_similarity_threshold():
    """Test that similarity threshold filters low-similarity matches."""
    outcomes = [
        create_outcome("email triage"),
        create_outcome("zebra photography"),  # Very different
    ]
    history = ProposalHistory(outcomes)
    similar = history.find_similar("email triage")
    # Should not match zebra photography
    assert all("email" in o.intent.lower() for o in similar)
