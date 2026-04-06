"""Consent Guard — prevents sidebar activation for external meetings.

LEGAL: Two-party/all-party consent required in CA, FL, IL, MA, PA, WA, MD,
NH, OR, MT, CT, NV. Silent AI transcription of external parties is illegal
in these states without disclosure.

Rule: Sidebar only activates for INTERNAL meetings (all attendees share
Wu's domain). For mixed/external meetings, user must add "AI may assist"
to the meeting description OR explicitly override.

Usage:
    guard = ConsentGuard(wu_domain="accenture.com")
    result = guard.check(attendees=["alice@accenture.com", "bob@accenture.com"])
    # result.approved == True (all internal)

    result = guard.check(attendees=["alice@accenture.com", "client@external.com"])
    # result.approved == False, result.reason explains why
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# States requiring all-party consent for recording
TWO_PARTY_CONSENT_STATES = {
    "CA", "FL", "IL", "MA", "PA", "WA", "MD", "NH", "OR", "MT", "CT", "NV"
}

# Domains considered "internal" — no consent issue
INTERNAL_DOMAINS = {"accenture.com", "wjlgatech@gmail.com"}


@dataclass
class ConsentCheckResult:
    approved: bool
    reason: str
    external_attendees: list[str]
    can_override: bool = False


class ConsentGuard:
    """Enforces consent rules before sidebar activation."""

    def __init__(
        self,
        wu_domain: str = "accenture.com",
        additional_internal_domains: Optional[list[str]] = None,
    ):
        self.internal_domains = INTERNAL_DOMAINS.copy()
        self.internal_domains.add(wu_domain)
        if additional_internal_domains:
            self.internal_domains.update(additional_internal_domains)

    def check(
        self,
        attendees: list[str],
        meeting_description: str = "",
        explicit_override: bool = False,
    ) -> ConsentCheckResult:
        """Check if sidebar can activate for this meeting.

        Args:
            attendees: List of attendee email addresses.
            meeting_description: Calendar event description (checked for consent disclosure).
            explicit_override: User explicitly approved AI assistance for this meeting.

        Returns:
            ConsentCheckResult with approved flag and reason.
        """
        if explicit_override:
            return ConsentCheckResult(
                approved=True,
                reason="User explicitly approved AI assistance.",
                external_attendees=[],
            )

        # Check for disclosure in meeting description
        disclosure_keywords = [
            "ai may assist", "ai assistance", "claude may assist",
            "ai transcription", "ai note-taking",
        ]
        has_disclosure = any(
            kw in meeting_description.lower()
            for kw in disclosure_keywords
        )

        if has_disclosure:
            return ConsentCheckResult(
                approved=True,
                reason="Meeting description includes AI assistance disclosure.",
                external_attendees=[],
            )

        # Identify external attendees
        external = []
        for email in attendees:
            if "@" not in email:
                continue
            domain = email.split("@")[-1].lower()
            if domain not in self.internal_domains:
                external.append(email)

        if not external:
            return ConsentCheckResult(
                approved=True,
                reason="All attendees are internal — no consent issue.",
                external_attendees=[],
            )

        # External attendees present without disclosure
        return ConsentCheckResult(
            approved=False,
            reason=(
                f"External attendees present ({', '.join(external)}). "
                f"Two-party consent laws apply in {len(TWO_PARTY_CONSENT_STATES)} states. "
                f"To activate sidebar: add 'AI may assist' to meeting description, "
                f"or use explicit_override=True after disclosing to attendees."
            ),
            external_attendees=external,
            can_override=True,
        )
