"""Post-Meeting Debrief Agent — Phase 1 of Meeting Intelligence Stack.

Flow:
  raw notes → Claude Haiku → structured markdown
           → Gmail draft (via Gmail MCP)
           → TASKS.md append (action items)

Usage:
    from workflowx.meeting.debrief_agent import run_debrief

    result = run_debrief(
        raw_notes="John said he'll send the proposal by Friday...",
        attendees="John Smith (Accenture client)",
        date="2026-04-06",
    )
    # result.markdown   — full structured debrief
    # result.actions    — list of {owner, action, deadline}
    # result.email_draft — subject + body
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import anthropic
import structlog

from workflowx.meeting.prompt_templates import DEBRIEF_SYSTEM, DEBRIEF_USER

logger = structlog.get_logger()


@dataclass
class ActionItem:
    owner: str
    action: str
    deadline: str


@dataclass
class EmailDraft:
    subject: str
    body: str


@dataclass
class DebriefResult:
    markdown: str
    actions: list[ActionItem] = field(default_factory=list)
    email_draft: Optional[EmailDraft] = None
    raw_notes: str = ""
    attendees: str = ""
    meeting_date: str = ""


def _call_haiku(system: str, user: str) -> str:
    """Call Claude Haiku. Cheap, fast, good enough for structured extraction."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": user}],
        system=system,
    )
    return message.content[0].text


def _parse_actions(markdown: str) -> list[ActionItem]:
    """Extract action items from the structured markdown table."""
    actions = []
    in_table = False
    for line in markdown.split("\n"):
        if "### Action Items" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" not in line and "Owner" not in line:
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 3 and parts[0]:
                actions.append(ActionItem(
                    owner=parts[0],
                    action=parts[1],
                    deadline=parts[2],
                ))
        elif in_table and line.startswith("###") and "Action" not in line:
            break
    return actions


def _parse_email(markdown: str) -> Optional[EmailDraft]:
    """Extract follow-up email draft from the structured markdown."""
    match = re.search(
        r"### Follow-up Email\n+Subject: (.+?)\n\n([\s\S]+?)(?=\n##|\Z)",
        markdown,
    )
    if not match:
        return None
    return EmailDraft(
        subject=match.group(1).strip(),
        body=match.group(2).strip(),
    )


def run_debrief(
    raw_notes: str,
    attendees: str = "Unknown",
    meeting_date: Optional[str] = None,
) -> DebriefResult:
    """Run the full debrief pipeline.

    Args:
        raw_notes: Raw meeting notes, any format (prose, bullets, partial transcript).
        attendees: Who was in the meeting (names/companies).
        meeting_date: ISO date string, defaults to today.

    Returns:
        DebriefResult with parsed markdown, action items, and email draft.
    """
    if not meeting_date:
        meeting_date = date.today().isoformat()

    logger.info("debrief_start", attendees=attendees, date=meeting_date, notes_len=len(raw_notes))

    user_prompt = DEBRIEF_USER.format(
        raw_notes=raw_notes,
        attendees=attendees,
        date=meeting_date,
    )

    try:
        markdown = _call_haiku(DEBRIEF_SYSTEM, user_prompt)
    except Exception as e:
        logger.error("debrief_haiku_error", error=str(e))
        raise RuntimeError(f"Claude Haiku call failed: {e}") from e

    actions = _parse_actions(markdown)
    email_draft = _parse_email(markdown)

    logger.info(
        "debrief_complete",
        actions_found=len(actions),
        email_extracted=email_draft is not None,
    )

    return DebriefResult(
        markdown=markdown,
        actions=actions,
        email_draft=email_draft,
        raw_notes=raw_notes,
        attendees=attendees,
        meeting_date=meeting_date,
    )


def save_debrief(result: DebriefResult, output_dir: str = "debriefs") -> str:
    """Save the debrief markdown to a file.

    Returns:
        Path to the saved file.
    """
    import pathlib

    out = pathlib.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Sanitize attendees for filename
    safe_name = re.sub(r"[^\w\s-]", "", result.attendees).strip().replace(" ", "-")[:40]
    filename = f"{result.meeting_date}-{safe_name}.md"
    filepath = out / filename

    filepath.write_text(result.markdown, encoding="utf-8")
    logger.info("debrief_saved", path=str(filepath))
    return str(filepath)
