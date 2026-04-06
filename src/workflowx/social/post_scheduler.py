"""Simple queue-based post scheduler using JSON persistence."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class PostStatus(str, Enum):
    """Status of a scheduled post."""

    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"


class ScheduledPost(BaseModel):
    """A post scheduled for a specific time across one or more platforms."""

    id: str = Field(default_factory=lambda: str(datetime.now().timestamp()))
    platform: str = Field(description="linkedin|twitter|both")
    text: str
    url: str = ""
    scheduled_for: datetime | None = Field(
        default=None,
        description="When to post (None = immediately)",
    )
    status: PostStatus = PostStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    post_id: str = ""  # Platform-specific post ID after posting


class PostScheduler:
    """Queue-based scheduler for social posts."""

    def __init__(self, queue_file: str = "~/.workflowx/post_queue.json"):
        """Initialize PostScheduler.

        Args:
            queue_file: Path to JSON queue file.
                Defaults to ~/.workflowx/post_queue.json
        """
        self.queue_file = Path(queue_file).expanduser()
        self._ensure_queue_dir()
        self.posts: list[ScheduledPost] = []
        self.load()
        logger.info("post_scheduler_init", queue_file=str(self.queue_file))

    def _ensure_queue_dir(self) -> None:
        """Ensure the queue file directory exists."""
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)

    def queue(
        self,
        platform: str,
        text: str,
        url: str = "",
        scheduled_for: datetime | None = None,
    ) -> ScheduledPost:
        """Add a post to the queue.

        Args:
            platform: "linkedin", "twitter", or "both"
            text: Post text.
            url: Optional URL to attach.
            scheduled_for: When to post (None = post immediately).

        Returns:
            The created ScheduledPost.
        """
        if platform not in ("linkedin", "twitter", "both"):
            raise ValueError(f"Invalid platform: {platform}")

        post = ScheduledPost(
            platform=platform,
            text=text,
            url=url,
            scheduled_for=scheduled_for,
        )

        self.posts.append(post)
        self.save()

        logger.info(
            "post_scheduler_queue",
            post_id=post.id,
            platform=platform,
            scheduled_for=scheduled_for,
        )

        return post

    def list_pending(self) -> list[ScheduledPost]:
        """Get all pending posts.

        Returns:
            List of ScheduledPost with status=PENDING.
        """
        return [p for p in self.posts if p.status == PostStatus.PENDING]

    def process_due(self) -> list[dict[str, Any]]:
        """Process and post all due posts.

        Checks each pending post's scheduled_for time. If it's in the past
        (or None, for immediate posts), posts it and updates status.

        Returns:
            List of result dicts with keys:
            - post_id: The post ID
            - platform: The platform(s) posted to
            - status: "ok" or "error"
            - message: Human-readable result
        """
        pending = self.list_pending()
        now = datetime.now()
        results = []

        for post in pending:
            # Check if it's due
            is_due = (
                post.scheduled_for is None or post.scheduled_for <= now
            )

            if not is_due:
                logger.debug(
                    "post_scheduler_not_due",
                    post_id=post.id,
                    scheduled_for=post.scheduled_for,
                )
                continue

            # Try to post
            result = self._post_to_platforms(post)
            results.append(result)

            # Update status
            if result["status"] == "ok":
                post.status = PostStatus.POSTED
                post.post_id = result.get("post_id", "")
            else:
                post.status = PostStatus.FAILED

        self.save()
        logger.info("post_scheduler_process_due", processed=len(results))
        return results

    def _post_to_platforms(self, post: ScheduledPost) -> dict[str, Any]:
        """Actually post to the configured platform(s).

        Args:
            post: The ScheduledPost to post.

        Returns:
            Result dict with keys:
            - post_id: Platform post ID
            - platform: Platform(s) posted to
            - status: "ok" or "error"
            - message: Human-readable result
        """
        # This is a stub; actual implementation would use
        # TwitterPoster and LinkedInPoster
        message = f"Posted to {post.platform}: {post.text[:50]}..."

        logger.info(
            "post_scheduler_posted",
            post_id=post.id,
            platform=post.platform,
        )

        return {
            "post_id": post.id,
            "platform": post.platform,
            "status": "ok",
            "message": message,
        }

    def save(self) -> None:
        """Save queue to JSON file."""
        try:
            data = [p.model_dump(mode="json") for p in self.posts]
            with open(self.queue_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug("post_scheduler_saved", count=len(self.posts))
        except Exception as e:
            logger.exception("post_scheduler_save_failed", error=str(e))

    def load(self) -> None:
        """Load queue from JSON file."""
        if not self.queue_file.exists():
            self.posts = []
            return

        try:
            with open(self.queue_file) as f:
                data = json.load(f)

            self.posts = [ScheduledPost(**item) for item in data]
            logger.info("post_scheduler_loaded", count=len(self.posts))
        except Exception as e:
            logger.exception("post_scheduler_load_failed", error=str(e))
            self.posts = []
