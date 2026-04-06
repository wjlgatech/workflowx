"""Context Gatherer — collects Gmail + Drive + web context for pre-meeting briefs.

This module is the intelligence layer for Phase 2. Given a meeting's attendees,
it gathers:
  1. Prior email threads with those attendees (Gmail MCP)
  2. Relevant Drive documents (Drive MCP)
  3. Company/people research (WebSearch)

In MCP context, the actual API calls are made by Claude using the connected
Gmail/Drive/WebSearch tools. This module defines the data structures and
orchestration logic that Claude follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ContextRequest:
    """Request spec for context gathering. Passed to Claude as instructions."""
    attendee_emails: list[str]
    attendee_names: list[str]
    company: str
    meeting_subject: str
    max_emails: int = 5
    max_drive_docs: int = 3


def build_gmail_search_query(attendee_emails: list[str], max_results: int = 5) -> str:
    """Build a Gmail search query for prior threads with attendees.

    Returns:
        Search query string for gmail_search_messages.
    """
    if not attendee_emails:
        return ""
    # Search for emails from/to any of these addresses
    email_parts = " OR ".join(f"from:{e} OR to:{e}" for e in attendee_emails[:3])
    return f"({email_parts})"


def build_drive_search_query(company: str, meeting_subject: str) -> str:
    """Build a Drive search query for relevant documents.

    Returns:
        Search query string for google_drive_search.
    """
    # Search for docs mentioning the company or meeting subject keywords
    keywords = []
    if company and company != "Unknown":
        keywords.append(company)
    # Extract key nouns from meeting subject
    subject_words = [w for w in meeting_subject.split() if len(w) > 4][:3]
    keywords.extend(subject_words)
    return " ".join(keywords)


def build_web_research_queries(company: str, attendee_names: list[str]) -> list[str]:
    """Build web search queries for company and attendee research.

    Returns:
        List of search queries to run.
    """
    queries = []
    if company and company != "Unknown":
        queries.append(f"{company} news 2026")
        queries.append(f"{company} recent funding product launch")
    for name in attendee_names[:2]:
        if name:
            queries.append(f"{name} {company} LinkedIn")
    return queries


def format_email_context(email_threads: list[dict]) -> str:
    """Format email thread data into a concise context string for the brief prompt."""
    if not email_threads:
        return "No prior email history found."

    lines = []
    for thread in email_threads[:5]:
        subject = thread.get("subject", "No subject")
        date = thread.get("date", "Unknown date")
        snippet = thread.get("snippet", "")[:200]
        lines.append(f"- [{date}] {subject}: {snippet}...")

    return "\n".join(lines)


def format_drive_context(docs: list[dict]) -> str:
    """Format Drive document metadata into context string."""
    if not docs:
        return "No relevant Drive documents found."

    lines = []
    for doc in docs[:3]:
        name = doc.get("name", "Unnamed")
        modified = doc.get("modifiedTime", "Unknown date")
        url = doc.get("webViewLink", "")
        lines.append(f"- {name} (modified: {modified}){' — ' + url if url else ''}")

    return "\n".join(lines)


def format_research_context(search_results: list[dict]) -> str:
    """Format web search results into context string."""
    if not search_results:
        return "No company information available."

    lines = []
    for result in search_results[:5]:
        title = result.get("title", "")
        snippet = result.get("snippet", "")[:150]
        if title:
            lines.append(f"- {title}: {snippet}")

    return "\n".join(lines) if lines else "No relevant results found."


# ── MCP Orchestration Instructions ────────────────────────────────────────────
# These strings are used in the MCP tool handler to tell Claude
# exactly what to do with its connected tools.

GATHER_CONTEXT_INSTRUCTIONS = """To gather context for this meeting:

1. **Gmail:** Search for prior threads:
   Query: {gmail_query}
   Tool: gmail_search_messages
   Take the top {max_emails} results. Extract: subject, date, snippet.

2. **Drive:** Search for relevant documents:
   Query: {drive_query}
   Tool: google_drive_search
   Take top {max_drive_docs} results. Extract: name, modifiedTime, webViewLink.

3. **Web research:** Run these searches:
{web_queries}
   Tool: WebSearch
   For each, extract: title, snippet (first 150 chars).

Once gathered, pass all context to the brief generator.
"""
