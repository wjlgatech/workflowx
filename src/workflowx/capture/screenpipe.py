"""Screenpipe adapter — reads events from Screenpipe's local SQLite database.

Screenpipe (https://github.com/mediar-ai/screenpipe) captures screen OCR,
audio transcription, and app metadata 24/7. We read its output — we don't
rebuild the capture layer.

The adapter converts Screenpipe's raw data into WorkflowX RawEvent objects.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

import structlog

from workflowx.models import EventSource, RawEvent

logger = structlog.get_logger()

# Default Screenpipe DB locations by platform
SCREENPIPE_DB_PATHS = {
    "darwin": Path.home() / ".screenpipe" / "db.sqlite",
    "linux": Path.home() / ".screenpipe" / "db.sqlite",
    "win32": Path.home() / ".screenpipe" / "db.sqlite",
}


class ScreenpipeAdapter:
    """Read events from Screenpipe's local SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            import sys
            db_path = SCREENPIPE_DB_PATHS.get(sys.platform)
            if db_path is None:
                raise RuntimeError(f"Unsupported platform: {sys.platform}")
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            logger.warning("screenpipe_db_not_found", path=str(self.db_path))

    def is_available(self) -> bool:
        """Check if Screenpipe database exists and is readable."""
        return self.db_path.exists()

    def read_events(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[RawEvent]:
        """Read raw events from Screenpipe within a time window."""
        if not self.is_available():
            logger.error("screenpipe_not_available", path=str(self.db_path))
            return []

        events: list[RawEvent] = []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

            # Read OCR frames (screen captures)
            events.extend(self._read_ocr_frames(conn, since, until, limit))

            # Read audio transcriptions
            events.extend(self._read_audio(conn, since, until, limit))

            conn.close()
        except sqlite3.Error as e:
            logger.error("screenpipe_db_error", error=str(e))

        events.sort(key=lambda e: e.timestamp)
        logger.info("screenpipe_events_read", count=len(events))
        return events

    def _read_ocr_frames(
        self,
        conn: sqlite3.Connection,
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> list[RawEvent]:
        """Read OCR screen capture events."""
        query = """
            SELECT f.timestamp, f.app_name, f.window_name, ot.text AS text_output
            FROM ocr_text ot
            JOIN frames f ON ot.frame_id = f.id
            WHERE 1=1
        """
        params: list[str | int] = []

        if since:
            query += " AND f.timestamp >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND f.timestamp <= ?"
            params.append(until.isoformat())

        query += " ORDER BY f.timestamp DESC LIMIT ?"
        params.append(limit)

        events = []
        try:
            cursor = conn.execute(query, params)
            for row in cursor:
                events.append(
                    RawEvent(
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        source=EventSource.SCREENPIPE,
                        app_name=row["app_name"] or "",
                        window_title=row["window_name"] or "",
                        ocr_text=row["text_output"] or "",
                    )
                )
        except sqlite3.Error:
            # Table might not exist yet if Screenpipe hasn't captured anything
            logger.debug("screenpipe_ocr_table_missing")

        return events

    def _read_audio(
        self,
        conn: sqlite3.Connection,
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> list[RawEvent]:
        """Read audio transcription events."""
        query = """
            SELECT timestamp, transcription, device
            FROM audio_transcriptions
            WHERE 1=1
        """
        params: list[str | int] = []

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND timestamp <= ?"
            params.append(until.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        events = []
        try:
            cursor = conn.execute(query, params)
            for row in cursor:
                events.append(
                    RawEvent(
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        source=EventSource.SCREENPIPE,
                        app_name="audio",
                        window_title=row["device"] or "",
                        ocr_text=row["transcription"] or "",
                        metadata={"type": "audio_transcription"},
                    )
                )
        except sqlite3.Error:
            logger.debug("screenpipe_audio_table_missing")

        return events


def iter_events_from_screenpipe(
    db_path: str | Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    batch_size: int = 500,
) -> Iterator[RawEvent]:
    """Stream events from Screenpipe in batches. Memory-efficient for large datasets."""
    adapter = ScreenpipeAdapter(db_path)

    while True:
        events = adapter.read_events(since=since, until=until, limit=batch_size)
        if not events:
            break
        yield from events
        if len(events) < batch_size:
            break
