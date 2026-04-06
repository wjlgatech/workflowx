"""TASKS.md updater — appends action items from meeting debriefs.

After a debrief, action items owned by Wu are written to TASKS.md
so the task-management system picks them up automatically.

Usage:
    from workflowx.meeting.tasks_updater import append_actions_to_tasks

    append_actions_to_tasks(
        actions=[ActionItem(owner="Wu", action="Send proposal", deadline="2026-04-10")],
        meeting_context="Meeting with John Smith (Client) 2026-04-06",
        tasks_file="/path/to/TASKS.md",
    )
"""

from __future__ import annotations

import pathlib
from datetime import date
from typing import Optional

import structlog

from workflowx.meeting.debrief_agent import ActionItem

logger = structlog.get_logger()

# Default TASKS.md location — relative to Projects root
DEFAULT_TASKS_PATH = "/Users/jialiang.wu/Documents/Projects/TASKS.md"


def append_actions_to_tasks(
    actions: list[ActionItem],
    meeting_context: str,
    tasks_file: str = DEFAULT_TASKS_PATH,
    owner_filter: str = "Wu",
) -> int:
    """Append Wu's action items from a debrief to TASKS.md.

    Only appends items where owner matches owner_filter (case-insensitive).
    Items are tagged with the meeting context and today's date.

    Args:
        actions: List of ActionItem from the debrief.
        meeting_context: Human-readable meeting context (e.g., "John Smith 2026-04-06").
        tasks_file: Path to TASKS.md.
        owner_filter: Only add items for this owner. Defaults to "Wu".

    Returns:
        Number of tasks appended.
    """
    wu_actions = [
        a for a in actions
        if owner_filter.lower() in a.owner.lower()
    ]

    if not wu_actions:
        logger.info("tasks_no_wu_actions", total_actions=len(actions))
        return 0

    tasks_path = pathlib.Path(tasks_file)

    # Build the new entries
    today = date.today().isoformat()
    lines = [
        f"\n<!-- Meeting: {meeting_context} — {today} -->",
    ]
    for action in wu_actions:
        deadline_note = f" (by {action.deadline})" if action.deadline and action.deadline != "TBD" else ""
        lines.append(f"- [ ] {action.action}{deadline_note}")

    new_content = "\n".join(lines) + "\n"

    if tasks_path.exists():
        existing = tasks_path.read_text(encoding="utf-8")
        tasks_path.write_text(existing + new_content, encoding="utf-8")
        logger.info("tasks_appended", count=len(wu_actions), file=tasks_file)
    else:
        # Create file with header
        header = f"# Tasks\n*Auto-managed by Chief-OS*\n\n## Pending\n"
        tasks_path.write_text(header + new_content, encoding="utf-8")
        logger.info("tasks_created", count=len(wu_actions), file=tasks_file)

    return len(wu_actions)


def format_actions_as_markdown_table(actions: list[ActionItem]) -> str:
    """Format actions as a clean markdown table for display."""
    if not actions:
        return "_No action items identified._"

    rows = ["| Owner | Action | Deadline |", "|-------|--------|----------|"]
    for a in actions:
        rows.append(f"| {a.owner} | {a.action} | {a.deadline or 'TBD'} |")
    return "\n".join(rows)
