"""Real-time Sidebar Agent — Phase 3 of Meeting Intelligence Stack.

Runs a 30-second loop:
  1. Pull latest audio chunk from Screenpipe
  2. Transcribe via Whisper (local, no cloud)
  3. Maintain rolling 90-second context window
  4. Call Claude Haiku for suggestion
  5. Update the overlay display

Usage:
    from workflowx.meeting.sidebar.sidebar_agent import SidebarAgent

    agent = SidebarAgent(attendees=["alice@accenture.com", "bob@accenture.com"])
    agent.start()   # runs until agent.stop() or KeyboardInterrupt
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import anthropic
import structlog

from workflowx.meeting.prompt_templates import SIDEBAR_SYSTEM, SIDEBAR_USER
from workflowx.meeting.sidebar.consent_guard import ConsentGuard, ConsentCheckResult

logger = structlog.get_logger()

# Rolling context window: last 3 chunks = ~90 seconds
CONTEXT_WINDOW_CHUNKS = 3
REFRESH_INTERVAL_SECONDS = 30


@dataclass
class TranscriptChunk:
    timestamp: datetime
    text: str
    speaker: str = "Unknown"


@dataclass
class SidebarUpdate:
    timestamp: datetime
    suggestion: str
    commitments: list[str] = field(default_factory=list)
    is_all_clear: bool = False


class SidebarAgent:
    """30-second refresh meeting assistant. Internal meetings only."""

    def __init__(
        self,
        attendees: list[str],
        participants: str = "Meeting participants",
        wu_domain: str = "accenture.com",
        on_update: Optional[Callable[[SidebarUpdate], None]] = None,
        explicit_consent_override: bool = False,
    ):
        self.attendees = attendees
        self.participants = participants
        self.on_update = on_update or self._default_display

        self._guard = ConsentGuard(wu_domain=wu_domain)
        self._consent_result: Optional[ConsentCheckResult] = None
        self._explicit_override = explicit_consent_override

        self._transcript_buffer: deque[TranscriptChunk] = deque(maxlen=CONTEXT_WINDOW_CHUNKS)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    def _check_consent(self) -> bool:
        """Verify consent before starting. Returns True if approved."""
        self._consent_result = self._guard.check(
            attendees=self.attendees,
            explicit_override=self._explicit_override,
        )
        if not self._consent_result.approved:
            logger.warning(
                "sidebar_consent_blocked",
                reason=self._consent_result.reason,
                external=self._consent_result.external_attendees,
            )
            print(f"\n⚠️  SIDEBAR BLOCKED: {self._consent_result.reason}\n")
            return False
        logger.info("sidebar_consent_approved", reason=self._consent_result.reason)
        return True

    def _get_latest_transcript_chunk(self) -> Optional[TranscriptChunk]:
        """Pull latest audio from Screenpipe and transcribe via Whisper.

        In Phase 3 this calls the Screenpipe API directly.
        For now, returns None (stub — requires Screenpipe installation).
        """
        try:
            from workflowx.capture.screenpipe import ScreenpipeAdapter
            # ScreenpipeAdapter.get_recent_audio() → transcribed text
            # This is Phase 3 Week 3 work (Screenpipe + Whisper setup)
            # Placeholder until Screenpipe is installed and configured
            return None
        except ImportError:
            return None

    def _call_haiku(self, transcript_text: str) -> str:
        """Call Claude Haiku with current transcript context."""
        user_prompt = SIDEBAR_USER.format(
            transcript_chunk=transcript_text,
            participants=self.participants,
        )
        try:
            message = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,  # Hard cap — sidebar is terse
                messages=[{"role": "user", "content": user_prompt}],
                system=SIDEBAR_SYSTEM,
            )
            return message.content[0].text
        except Exception as e:
            logger.error("sidebar_haiku_error", error=str(e))
            return "All clear — keep listening."

    def _parse_update(self, haiku_response: str) -> SidebarUpdate:
        """Parse Haiku response into structured SidebarUpdate."""
        is_all_clear = "all clear" in haiku_response.lower()
        commitments = []

        # Simple commitment detection: lines mentioning "will", "by Friday/Monday/etc"
        for line in haiku_response.split("\n"):
            if any(kw in line.lower() for kw in ["will ", "by friday", "by monday", "committed to", "promised"]):
                commitments.append(line.strip())

        return SidebarUpdate(
            timestamp=datetime.now(),
            suggestion=haiku_response,
            commitments=commitments,
            is_all_clear=is_all_clear,
        )

    @staticmethod
    def _default_display(update: SidebarUpdate) -> None:
        """Default: print to terminal. Replace with overlay in Phase 3."""
        if update.is_all_clear:
            return
        print(f"\n── Sidebar [{update.timestamp.strftime('%H:%M:%S')}] ──")
        print(update.suggestion)
        if update.commitments:
            print("📌 Commitments:", "; ".join(update.commitments))
        print()

    def _run_loop(self) -> None:
        """Main 30-second refresh loop."""
        logger.info("sidebar_loop_start")
        while self._running:
            chunk = self._get_latest_transcript_chunk()
            if chunk:
                self._transcript_buffer.append(chunk)

            if self._transcript_buffer:
                # Build rolling context window from last 3 chunks
                context_text = "\n".join(c.text for c in self._transcript_buffer)
                haiku_response = self._call_haiku(context_text)
                update = self._parse_update(haiku_response)
                self.on_update(update)

            time.sleep(REFRESH_INTERVAL_SECONDS)

        logger.info("sidebar_loop_stop")

    def start(self) -> bool:
        """Start the sidebar. Returns False if consent check fails."""
        if not self._check_consent():
            return False

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("sidebar_started", participants=self.participants)
        return True

    def stop(self) -> None:
        """Stop the sidebar."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("sidebar_stopped")

    def inject_transcript(self, text: str, speaker: str = "Unknown") -> None:
        """Manually inject transcript text (for testing or manual transcript mode)."""
        chunk = TranscriptChunk(
            timestamp=datetime.now(),
            text=text,
            speaker=speaker,
        )
        self._transcript_buffer.append(chunk)
