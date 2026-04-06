"""Tests for Meeting Intelligence Stack — Phase 1, 2, and 3.

These tests run WITHOUT calling Claude API (no cost).
They test parsing, structuring, and consent logic only.
"""

from __future__ import annotations

import pytest

from workflowx.meeting.debrief_agent import _parse_actions, _parse_email
from workflowx.meeting.tasks_updater import append_actions_to_tasks, format_actions_as_markdown_table
from workflowx.meeting.prebrief.context_gatherer import (
    build_gmail_search_query,
    build_drive_search_query,
    build_web_research_queries,
)
from workflowx.meeting.sidebar.consent_guard import ConsentGuard


# ── Sample debrief markdown for parsing tests ──────────────────────────────

SAMPLE_DEBRIEF = """
## Meeting: John Smith (Acme Corp) — 2026-04-06

### Discussed
- Reviewed current integration progress and identified two blockers.
- John confirmed their DevOps team can support Docker deployment by end of month.
- Discussed pricing model adjustment for enterprise tier.

### Commitments
**Wu committed to:**
- Send updated API documentation by April 8.
- Schedule a follow-up call with Acme's CTO.

**They committed to:**
- Provide access to staging environment by April 10.

### Action Items
| Owner | Action | Deadline |
|-------|--------|----------|
| Wu | Send updated API documentation | April 8 |
| Wu | Schedule follow-up with CTO | April 9 |
| John | Provide staging environment access | April 10 |

### Follow-up Email
Subject: Re: Integration next steps — API docs incoming

Hi John, great talking today. I'll have the updated API documentation
to you by Wednesday, April 8. Looking forward to connecting with your
CTO team — I'll send a calendar invite once you've confirmed availability.

Best,
Wu
"""


# ── Parsing tests ────────────────────────────────────────────────────────────

class TestDebriefParsing:
    def test_parse_actions_finds_all_rows(self):
        actions = _parse_actions(SAMPLE_DEBRIEF)
        assert len(actions) == 3

    def test_parse_actions_extracts_owner(self):
        actions = _parse_actions(SAMPLE_DEBRIEF)
        owners = [a.owner for a in actions]
        assert "Wu" in owners
        assert "John" in owners

    def test_parse_actions_extracts_deadline(self):
        actions = _parse_actions(SAMPLE_DEBRIEF)
        wu_actions = [a for a in actions if a.owner == "Wu"]
        assert any("April 8" in a.deadline for a in wu_actions)

    def test_parse_email_extracts_subject(self):
        email = _parse_email(SAMPLE_DEBRIEF)
        assert email is not None
        assert "Integration next steps" in email.subject

    def test_parse_email_extracts_body(self):
        email = _parse_email(SAMPLE_DEBRIEF)
        assert email is not None
        assert "API documentation" in email.body

    def test_parse_actions_empty_markdown(self):
        actions = _parse_actions("No action items here.")
        assert actions == []

    def test_parse_email_no_email_section(self):
        email = _parse_email("### Summary\n- Something happened")
        assert email is None


# ── Tasks updater tests ──────────────────────────────────────────────────────

class TestTasksUpdater:
    def test_format_actions_table(self):
        from workflowx.meeting.debrief_agent import ActionItem
        actions = [
            ActionItem(owner="Wu", action="Send docs", deadline="April 8"),
            ActionItem(owner="John", action="Grant access", deadline="April 10"),
        ]
        table = format_actions_as_markdown_table(actions)
        assert "Wu" in table
        assert "Send docs" in table
        assert "| Owner |" in table

    def test_format_actions_empty(self):
        result = format_actions_as_markdown_table([])
        assert "_No action items identified._" in result

    def test_append_only_wu_actions(self, tmp_path):
        from workflowx.meeting.debrief_agent import ActionItem
        actions = [
            ActionItem(owner="Wu", action="Send docs", deadline="April 8"),
            ActionItem(owner="John", action="Grant access", deadline="April 10"),
        ]
        tasks_file = str(tmp_path / "TASKS.md")
        count = append_actions_to_tasks(
            actions=actions,
            meeting_context="Test meeting",
            tasks_file=tasks_file,
            owner_filter="Wu",
        )
        assert count == 1  # Only Wu's action

        content = open(tasks_file).read()
        assert "Send docs" in content
        assert "Grant access" not in content  # John's action excluded

    def test_append_creates_tasks_file(self, tmp_path):
        from workflowx.meeting.debrief_agent import ActionItem
        actions = [ActionItem(owner="Wu", action="Follow up", deadline="TBD")]
        tasks_file = str(tmp_path / "NEW_TASKS.md")
        count = append_actions_to_tasks(
            actions=actions,
            meeting_context="New meeting",
            tasks_file=tasks_file,
        )
        assert count == 1
        assert (tmp_path / "NEW_TASKS.md").exists()


# ── Context gatherer tests ────────────────────────────────────────────────────

class TestContextGatherer:
    def test_gmail_query_single_email(self):
        query = build_gmail_search_query(["john@acme.com"])
        assert "john@acme.com" in query

    def test_gmail_query_multiple_emails(self):
        query = build_gmail_search_query(["a@x.com", "b@y.com"])
        assert "a@x.com" in query
        assert "b@y.com" in query

    def test_gmail_query_empty(self):
        query = build_gmail_search_query([])
        assert query == ""

    def test_drive_query_includes_company(self):
        query = build_drive_search_query("Acme Corp", "API integration planning")
        assert "Acme Corp" in query

    def test_web_queries_include_company_news(self):
        queries = build_web_research_queries("Acme", ["John Smith"])
        assert any("Acme" in q and "2026" in q for q in queries)

    def test_web_queries_include_attendee(self):
        queries = build_web_research_queries("Acme", ["John Smith"])
        assert any("John Smith" in q for q in queries)


# ── Consent guard tests ────────────────────────────────────────────────────────

class TestConsentGuard:
    def setup_method(self):
        self.guard = ConsentGuard(wu_domain="accenture.com")

    def test_all_internal_approved(self):
        result = self.guard.check(
            attendees=["alice@accenture.com", "bob@accenture.com"]
        )
        assert result.approved is True
        assert result.external_attendees == []

    def test_external_attendee_blocked(self):
        result = self.guard.check(
            attendees=["alice@accenture.com", "client@externalcorp.com"]
        )
        assert result.approved is False
        assert "client@externalcorp.com" in result.external_attendees
        assert result.can_override is True

    def test_disclosure_in_description_approves(self):
        result = self.guard.check(
            attendees=["alice@accenture.com", "client@externalcorp.com"],
            meeting_description="AI may assist during this session.",
        )
        assert result.approved is True

    def test_explicit_override_approves(self):
        result = self.guard.check(
            attendees=["alice@accenture.com", "client@externalcorp.com"],
            explicit_override=True,
        )
        assert result.approved is True

    def test_empty_attendees_approved(self):
        result = self.guard.check(attendees=[])
        assert result.approved is True

    def test_case_insensitive_disclosure(self):
        result = self.guard.check(
            attendees=["alice@accenture.com", "client@externalcorp.com"],
            meeting_description="NOTE: AI ASSISTANCE may be active.",
        )
        # "ai assistance" matches
        assert result.approved is True
