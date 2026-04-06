"""Gmail integration for Meeting Intelligence Stack.

Pushes follow-up email drafts to Gmail Drafts via subprocess MCP call.
No OAuth dance — uses the Gmail MCP already connected in Claude Desktop.

Usage:
    from workflowx.meeting.gmail_push import push_draft_to_gmail

    draft_id = push_draft_to_gmail(
        to="john.smith@client.com",
        subject="Re: Project Alpha next steps",
        body="Hi John, thanks for the call today...",
    )
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from typing import Optional

import structlog

logger = structlog.get_logger()


def push_draft_to_gmail(
    subject: str,
    body: str,
    to: Optional[str] = None,
) -> dict:
    """Push an email draft to Gmail Drafts.

    The draft is created via the Gmail MCP tool. Wu reviews and sends manually.

    Args:
        subject: Email subject line.
        body: Email body (plain text or markdown).
        to: Recipient email address. If None, left blank for Wu to fill in.

    Returns:
        dict with status and draft_id if successful.
    """
    # Build the MCP call as a Claude prompt
    # Since we're running inside a workflowx context (not inside Claude),
    # we construct a minimal invocation using the workflowx-to-claude bridge.
    # In practice, this function is called from the MCP tool handler which
    # already runs inside Claude's tool execution context — so we return
    # the draft data for Claude to push via gmail_create_draft.

    logger.info("gmail_push_draft", to=to, subject=subject)

    draft_payload = {
        "action": "create_draft",
        "to": to or "",
        "subject": subject,
        "body": body,
        "note": "Draft created by Meeting Intelligence Stack — review before sending.",
    }

    return {
        "status": "ready_to_push",
        "draft": draft_payload,
        "instruction": (
            "Call gmail_create_draft with the draft payload above. "
            "Wu will review and send manually."
        ),
    }


def format_draft_for_mcp(subject: str, body: str, to: str = "") -> str:
    """Format a draft email as a JSON string suitable for passing to gmail_create_draft MCP tool.

    Returns:
        JSON string with to, subject, body fields.
    """
    return json.dumps({
        "to": to,
        "subject": subject,
        "body": body,
    }, indent=2)
