"""MCP handler functions for social media posting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from workflowx.social.linkedin_poster import LinkedInPoster, post_linkedin_sync
from workflowx.social.post_scheduler import PostScheduler
from workflowx.social.twitter_poster import TwitterPoster

logger = structlog.get_logger()


def handle_post_social(
    platform: str,
    text: str,
    url: str = "",
    schedule_for: str = "",
) -> dict[str, Any]:
    """Post to social media immediately or schedule for later.

    Args:
        platform: "linkedin", "twitter", or "both"
        text: Post text.
        url: Optional URL to attach.
        schedule_for: ISO 8601 datetime string (e.g., "2026-04-10T14:30:00").
                     Empty string = post immediately.

    Returns:
        Dict with keys:
        - status: "ok" if successful, "error" if failed
        - message: Human-readable status message
        - post_id: Post ID (if posted immediately)
        - scheduled_for: Scheduled time (if scheduled)
    """
    if platform not in ("linkedin", "twitter", "both"):
        return {
            "status": "error",
            "message": f"Invalid platform '{platform}'. Use: linkedin, twitter, or both",
        }

    if not text:
        return {
            "status": "error",
            "message": "Post text cannot be empty",
        }

    # Determine if scheduling or posting immediately
    scheduled_for = None
    if schedule_for:
        try:
            scheduled_for = datetime.fromisoformat(schedule_for)
        except ValueError:
            return {
                "status": "error",
                "message": f"Invalid datetime format: {schedule_for}. Use ISO 8601 (e.g., 2026-04-10T14:30:00)",
            }

    # If no schedule, post immediately
    if not scheduled_for:
        logger.info("social_post_immediate", platform=platform, text_len=len(text))

        results = {}

        # Post to Twitter if requested
        if platform in ("twitter", "both"):
            try:
                twitter = TwitterPoster()
                result = twitter.post_tweet(text=text)
                results["twitter"] = result
            except Exception as e:
                logger.exception("social_post_twitter_failed", error=str(e))
                results["twitter"] = {
                    "status": "error",
                    "error": str(e),
                }

        # Post to LinkedIn if requested
        if platform in ("linkedin", "both"):
            try:
                result = post_linkedin_sync(text=text, url=url)
                results["linkedin"] = result
            except Exception as e:
                logger.exception("social_post_linkedin_failed", error=str(e))
                results["linkedin"] = {
                    "status": "error",
                    "error": str(e),
                }

        # Check overall status
        all_ok = all(r.get("status") == "ok" for r in results.values())
        any_ok = any(r.get("status") == "ok" for r in results.values())

        if all_ok:
            status = "ok"
            message = f"Posted to {platform}"
        elif any_ok:
            status = "partial"
            message = f"Posted to some platforms, some failed"
        else:
            status = "error"
            message = "Failed to post to all requested platforms"

        return {
            "status": status,
            "message": message,
            "results": results,
        }

    # Schedule for later
    scheduler = PostScheduler()
    post = scheduler.queue(
        platform=platform,
        text=text,
        url=url,
        scheduled_for=scheduled_for,
    )

    logger.info(
        "social_post_scheduled",
        platform=platform,
        scheduled_for=scheduled_for,
        post_id=post.id,
    )

    return {
        "status": "ok",
        "message": f"Post scheduled for {scheduled_for}",
        "post_id": post.id,
        "scheduled_for": scheduled_for.isoformat(),
    }


def handle_list_post_queue() -> dict[str, Any]:
    """List all pending posts in the queue.

    Returns:
        Dict with keys:
        - status: "ok"
        - pending_count: Number of pending posts
        - posts: List of pending post dicts with:
          - id: Post ID
          - platform: Platform(s)
          - text: Post text (truncated to 100 chars)
          - scheduled_for: When to post
    """
    scheduler = PostScheduler()
    pending = scheduler.list_pending()

    posts = [
        {
            "id": p.id,
            "platform": p.platform,
            "text": p.text[:100] + ("..." if len(p.text) > 100 else ""),
            "scheduled_for": p.scheduled_for.isoformat() if p.scheduled_for else "immediately",
            "created_at": p.created_at.isoformat(),
        }
        for p in pending
    ]

    logger.info("social_list_queue", pending_count=len(pending))

    return {
        "status": "ok",
        "pending_count": len(pending),
        "posts": posts,
    }


def handle_process_post_queue() -> dict[str, Any]:
    """Process all due posts in the queue.

    Posts all posts whose scheduled_for time has passed.

    Returns:
        Dict with keys:
        - status: "ok"
        - processed: Number of posts processed
        - results: List of result dicts for each processed post
    """
    scheduler = PostScheduler()
    results = scheduler.process_due()

    logger.info("social_process_queue", processed=len(results))

    return {
        "status": "ok",
        "processed": len(results),
        "results": results,
    }
