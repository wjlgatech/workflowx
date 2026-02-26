"""ActivityWatch adapter — reads events via the ActivityWatch REST API.

ActivityWatch (https://activitywatch.net/) is an open-source, privacy-first
time tracker. It runs a local server on port 5600 with a REST API.

This adapter converts ActivityWatch bucket events into WorkflowX RawEvent objects.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from workflowx.models import EventSource, RawEvent

logger = structlog.get_logger()

DEFAULT_HOST = "http://localhost:5600"
DEFAULT_BUCKETS = [
    "aw-watcher-window_",   # Active window (app + title)
    "aw-watcher-afk_",      # AFK detection
    "aw-watcher-web-",      # Browser URLs
]


class ActivityWatchAdapter:
    """Read events from ActivityWatch's local REST API."""

    def __init__(self, host: str = DEFAULT_HOST) -> None:
        self.host = host.rstrip("/")
        self._httpx = None

    def _get_client(self):
        """Lazy-load httpx to avoid import cost when not using AW."""
        if self._httpx is None:
            try:
                import httpx
                self._httpx = httpx
            except ImportError:
                raise RuntimeError(
                    "httpx required for ActivityWatch adapter. "
                    "Install: pip install workflowx[replacement]"
                )
        return self._httpx

    def is_available(self) -> bool:
        """Check if ActivityWatch server is running."""
        httpx = self._get_client()
        try:
            r = httpx.get(f"{self.host}/api/0/info", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def _list_buckets(self) -> dict[str, Any]:
        """Get all available buckets."""
        httpx = self._get_client()
        try:
            r = httpx.get(f"{self.host}/api/0/buckets/", timeout=5.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("aw_list_buckets_failed", error=str(e))
            return {}

    def _find_bucket_id(self, prefix: str, buckets: dict[str, Any]) -> str | None:
        """Find the first bucket matching a prefix."""
        for bucket_id in buckets:
            if bucket_id.startswith(prefix):
                return bucket_id
        return None

    def read_events(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[RawEvent]:
        """Read raw events from ActivityWatch within a time window."""
        if not self.is_available():
            logger.warning("activitywatch_not_available", host=self.host)
            return []

        httpx = self._get_client()
        buckets = self._list_buckets()
        all_events: list[RawEvent] = []

        # Default time window: last 24 hours
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        if until is None:
            until = datetime.now(timezone.utc)

        for prefix in DEFAULT_BUCKETS:
            bucket_id = self._find_bucket_id(prefix, buckets)
            if not bucket_id:
                continue

            try:
                params = {
                    "start": since.isoformat(),
                    "end": until.isoformat(),
                    "limit": limit,
                }
                r = httpx.get(
                    f"{self.host}/api/0/buckets/{bucket_id}/events",
                    params=params,
                    timeout=10.0,
                )
                r.raise_for_status()
                raw_events = r.json()

                for raw in raw_events:
                    event = self._convert_event(raw, bucket_id)
                    if event:
                        all_events.append(event)

            except Exception as e:
                logger.error(
                    "aw_bucket_read_failed",
                    bucket=bucket_id,
                    error=str(e),
                )

        all_events.sort(key=lambda e: e.timestamp)
        logger.info("aw_events_read", count=len(all_events))
        return all_events

    def _convert_event(self, raw: dict[str, Any], bucket_id: str) -> RawEvent | None:
        """Convert an ActivityWatch event to a WorkflowX RawEvent."""
        try:
            data = raw.get("data", {})
            timestamp_str = raw.get("timestamp", "")
            duration = raw.get("duration", 0.0)

            # Parse ISO timestamp
            ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

            # Window watcher events have 'app' and 'title'
            app_name = data.get("app", "")
            title = data.get("title", "")

            # Web watcher events have 'url' and 'title'
            url = data.get("url", "")
            if url and not app_name:
                app_name = "browser"

            # AFK watcher events have 'status'
            status = data.get("status", "")
            if status and not app_name:
                app_name = f"afk:{status}"

            return RawEvent(
                timestamp=ts,
                source=EventSource.ACTIVITYWATCH,
                app_name=app_name,
                window_title=title,
                url=url,
                duration_seconds=float(duration),
                metadata={"bucket": bucket_id, "raw_data": data},
            )
        except Exception as e:
            logger.debug("aw_event_convert_failed", error=str(e))
            return None
