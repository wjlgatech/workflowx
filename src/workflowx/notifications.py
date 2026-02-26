"""macOS native notification wrapper.

Uses `osascript` to fire UserNotifications — no extra dependencies.
Falls back silently on non-macOS or if osascript is unavailable.
"""

from __future__ import annotations

import platform
import subprocess

import structlog

logger = structlog.get_logger()


def notify(title: str, message: str, subtitle: str = "") -> None:
    """Fire a macOS native notification. No-op on other platforms.

    Args:
        title:    Bold header line (app name / event type).
        message:  Body text — the actionable detail.
        subtitle: Optional second line between title and body.
    """
    if platform.system() != "Darwin":
        logger.info("notification_skipped", reason="not_macos", title=title)
        return

    def _esc(s: str) -> str:
        """Escape for embedding in an AppleScript double-quoted string."""
        return s.replace("\\", "\\\\").replace('"', '\\"')

    subtitle_clause = f' subtitle "{_esc(subtitle)}"' if subtitle else ""
    script = (
        f'display notification "{_esc(message)}"'
        f' with title "{_esc(title)}"'
        f"{subtitle_clause}"
    )

    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
            check=False,
        )
        logger.debug("notification_sent", title=title)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("notification_failed", error=str(e), title=title)
