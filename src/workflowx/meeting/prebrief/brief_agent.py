"""Pre-Meeting Brief Agent — Phase 2 of Meeting Intelligence Stack.

Orchestrates:
  1. calendar_scanner → upcoming external meetings
  2. context_gatherer → Gmail + Drive + web context per meeting
  3. Claude Haiku → 1-page cheat sheet per meeting
  4. Save to workflowx/briefs/YYYY-MM-DD-[client].md

Run nightly at 11 PM via scheduled task, or on-demand:
    from workflowx.meeting.prebrief.brief_agent import run_prebrief

    briefs = run_prebrief(target_date="2026-04-07")
    # Returns list of (meeting_info, brief_markdown) tuples
"""

from __future__ import annotations

import os
import pathlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import anthropic
import structlog

from workflowx.meeting.prompt_templates import PREBRIEF_SYSTEM, PREBRIEF_USER

logger = structlog.get_logger()

# Where briefs are saved
BRIEFS_DIR = pathlib.Path(__file__).parents[5] / "briefs"


@dataclass
class MeetingInfo:
    """Upcoming meeting from Google Calendar."""
    event_id: str
    title: str
    start_time: str
    end_time: str
    attendees: list[str] = field(default_factory=list)
    description: str = ""
    is_external: bool = False


@dataclass
class MeetingContext:
    """Gathered context for a meeting."""
    email_context: str = "No prior email history found."
    drive_context: str = "No relevant Drive documents found."
    research_context: str = "No company information available."
    attendee_names: str = ""
    company: str = "Unknown"


@dataclass
class PrebriefResult:
    meeting: MeetingInfo
    context: MeetingContext
    brief_markdown: str
    saved_path: Optional[str] = None


def _call_haiku(system: str, user: str) -> str:
    """Call Claude Haiku for brief generation."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": user}],
        system=system,
    )
    return message.content[0].text


def _is_external_meeting(attendees: list[str], wu_domain: str = "accenture.com") -> bool:
    """Returns True if any attendee is outside Wu's domain."""
    internal_domains = {wu_domain, "gmail.com", "wjlgatech@gmail.com"}
    for email in attendees:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain and domain not in internal_domains:
            return True
    return False


def _extract_company_from_attendees(attendees: list[str]) -> str:
    """Best-effort company extraction from email domains."""
    for email in attendees:
        if "@" in email:
            domain = email.split("@")[-1].lower()
            # Skip common personal/internal domains
            if domain not in {"gmail.com", "yahoo.com", "hotmail.com", "accenture.com"}:
                # Convert domain to company name heuristic
                company = domain.split(".")[0].replace("-", " ").title()
                return company
    return "Unknown"


def generate_brief(meeting: MeetingInfo, context: MeetingContext) -> str:
    """Generate a pre-meeting brief using Claude Haiku."""
    user_prompt = PREBRIEF_USER.format(
        attendee_names=context.attendee_names or ", ".join(meeting.attendees),
        company=context.company,
        meeting_time=meeting.start_time,
        meeting_subject=meeting.title,
        email_context=context.email_context,
        research_context=context.research_context,
        drive_context=context.drive_context,
    )
    return _call_haiku(PREBRIEF_SYSTEM, user_prompt)


def save_brief(meeting: MeetingInfo, brief_markdown: str, briefs_dir: pathlib.Path = BRIEFS_DIR) -> str:
    """Save brief to filesystem. Returns path."""
    briefs_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize for filename
    safe_title = re.sub(r"[^\w\s-]", "", meeting.title).strip().replace(" ", "-")[:40]
    date_str = meeting.start_time[:10] if len(meeting.start_time) >= 10 else date.today().isoformat()
    filename = f"{date_str}-{safe_title}.md"
    filepath = briefs_dir / filename

    filepath.write_text(brief_markdown, encoding="utf-8")
    logger.info("brief_saved", path=str(filepath))
    return str(filepath)


def run_prebrief(
    meetings: list[MeetingInfo],
    contexts: Optional[dict[str, MeetingContext]] = None,
) -> list[PrebriefResult]:
    """Generate pre-meeting briefs for a list of meetings.

    In MCP context, meetings come from calendar_scanner (gcal MCP).
    Contexts come from context_gatherer (Gmail + Drive + web).

    Args:
        meetings: List of MeetingInfo from calendar scanner.
        contexts: Optional dict mapping event_id → MeetingContext.
                  If None, minimal context is used.

    Returns:
        List of PrebriefResult, one per meeting.
    """
    results = []
    contexts = contexts or {}

    for meeting in meetings:
        logger.info("brief_start", meeting=meeting.title, time=meeting.start_time)

        context = contexts.get(meeting.event_id, MeetingContext(
            attendee_names=", ".join(meeting.attendees),
            company=_extract_company_from_attendees(meeting.attendees),
        ))

        try:
            brief_md = generate_brief(meeting, context)
            saved_path = save_brief(meeting, brief_md)
            results.append(PrebriefResult(
                meeting=meeting,
                context=context,
                brief_markdown=brief_md,
                saved_path=saved_path,
            ))
        except Exception as e:
            logger.error("brief_failed", meeting=meeting.title, error=str(e))

    logger.info("prebrief_complete", total=len(results))
    return results
