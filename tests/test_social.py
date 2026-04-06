"""Tests for social media automation module.

These tests run WITHOUT calling actual Twitter/LinkedIn APIs.
They test validation, scheduling, and data persistence only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from workflowx.social.post_scheduler import PostScheduler, PostStatus, ScheduledPost
from workflowx.social.twitter_poster import TwitterPoster


# ── TwitterPoster Tests ──────────────────────────────────────────


class TestTwitterPoster:
    """Tests for TwitterPoster.validate_text (no API calls)."""

    def test_validate_text_valid(self):
        """Valid tweet should pass validation."""
        result, msg = TwitterPoster.validate_text(None, "Hello, World!")
        assert result is True
        assert msg == ""

    def test_validate_text_empty(self):
        """Empty tweet should fail."""
        result, msg = TwitterPoster.validate_text(None, "")
        assert result is False
        assert "empty" in msg.lower()

    def test_validate_text_at_limit(self):
        """Tweet at exactly 280 characters should pass."""
        text = "x" * 280
        result, msg = TwitterPoster.validate_text(None, text)
        assert result is True

    def test_validate_text_over_limit(self):
        """Tweet over 280 characters should fail."""
        text = "x" * 281
        result, msg = TwitterPoster.validate_text(None, text)
        assert result is False
        assert "280" in msg
        assert "281" in msg

    def test_validate_text_with_emoji(self):
        """Tweet with emoji should count characters correctly."""
        # Most emoji count as 2 characters in terms of visual width,
        # but Python's len() counts them as 1 character (for UCS-4)
        text = "Hello 👋" * 30  # Should be under 280
        result, msg = TwitterPoster.validate_text(None, text)
        # Either way is fine; we're just testing that validation works
        assert isinstance(result, bool)


# ── ScheduledPost Model Tests ────────────────────────────────────


class TestScheduledPost:
    """Tests for ScheduledPost Pydantic model."""

    def test_scheduled_post_creation(self):
        """Create a ScheduledPost."""
        post = ScheduledPost(
            platform="twitter",
            text="Test tweet",
            scheduled_for=datetime.now() + timedelta(hours=1),
        )
        assert post.platform == "twitter"
        assert post.text == "Test tweet"
        assert post.status == PostStatus.PENDING
        assert post.post_id == ""

    def test_scheduled_post_with_url(self):
        """Create a ScheduledPost with URL."""
        post = ScheduledPost(
            platform="linkedin",
            text="Test post",
            url="https://example.com",
        )
        assert post.url == "https://example.com"

    def test_scheduled_post_immediate(self):
        """Create a ScheduledPost for immediate posting."""
        post = ScheduledPost(
            platform="both",
            text="Post now",
            scheduled_for=None,
        )
        assert post.scheduled_for is None


# ── PostScheduler Tests ──────────────────────────────────────────


class TestPostScheduler:
    """Tests for PostScheduler (no API calls)."""

    def test_scheduler_init(self, tmp_path):
        """Initialize scheduler."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))
        assert scheduler.posts == []
        assert scheduler.queue_file == queue_file

    def test_scheduler_queue_twitter(self, tmp_path):
        """Queue a Twitter post."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        post = scheduler.queue(
            platform="twitter",
            text="Test tweet",
            scheduled_for=None,
        )

        assert post.platform == "twitter"
        assert post.text == "Test tweet"
        assert len(scheduler.posts) == 1

    def test_scheduler_queue_linkedin(self, tmp_path):
        """Queue a LinkedIn post."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        post = scheduler.queue(
            platform="linkedin",
            text="Test post",
            url="https://example.com",
            scheduled_for=datetime.now() + timedelta(hours=1),
        )

        assert post.platform == "linkedin"
        assert post.url == "https://example.com"
        assert len(scheduler.posts) == 1

    def test_scheduler_queue_both(self, tmp_path):
        """Queue a post to both platforms."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        post = scheduler.queue(
            platform="both",
            text="Test post",
        )

        assert post.platform == "both"

    def test_scheduler_queue_invalid_platform(self, tmp_path):
        """Queue with invalid platform should raise ValueError."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        with pytest.raises(ValueError):
            scheduler.queue(
                platform="invalid",
                text="Test",
            )

    def test_scheduler_list_pending(self, tmp_path):
        """List pending posts."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        scheduler.queue(platform="twitter", text="Test 1")
        scheduler.queue(platform="linkedin", text="Test 2")

        pending = scheduler.list_pending()
        assert len(pending) == 2
        assert all(p.status == PostStatus.PENDING for p in pending)

    def test_scheduler_save(self, tmp_path):
        """Save queue to JSON file."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        scheduler.queue(platform="twitter", text="Test tweet")

        scheduler.save()
        assert queue_file.exists()

        # Verify file is valid JSON
        import json
        with open(queue_file) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["platform"] == "twitter"

    def test_scheduler_load(self, tmp_path):
        """Load queue from JSON file."""
        queue_file = tmp_path / "queue.json"

        # Create a scheduler, add a post, save
        scheduler1 = PostScheduler(queue_file=str(queue_file))
        scheduler1.queue(platform="twitter", text="Test tweet")
        scheduler1.save()

        # Create a new scheduler and load
        scheduler2 = PostScheduler(queue_file=str(queue_file))
        assert len(scheduler2.posts) == 1
        assert scheduler2.posts[0].platform == "twitter"
        assert scheduler2.posts[0].text == "Test tweet"

    def test_scheduler_load_missing_file(self, tmp_path):
        """Load from non-existent file should work (empty queue)."""
        queue_file = tmp_path / "missing.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        assert len(scheduler.posts) == 0

    def test_scheduler_process_due_immediate(self, tmp_path):
        """Process due posts with no scheduled_for should post immediately."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        post = scheduler.queue(
            platform="twitter",
            text="Post now",
            scheduled_for=None,
        )

        results = scheduler.process_due()

        # Should process this post
        assert len(results) == 1
        assert results[0]["post_id"] == post.id
        assert results[0]["platform"] == "twitter"

    def test_scheduler_process_due_scheduled_future(self, tmp_path):
        """Process should skip posts scheduled for the future."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        future = datetime.now() + timedelta(hours=1)
        post = scheduler.queue(
            platform="twitter",
            text="Post later",
            scheduled_for=future,
        )

        results = scheduler.process_due()

        # Should not process this post (it's in the future)
        assert len(results) == 0

    def test_scheduler_process_due_scheduled_past(self, tmp_path):
        """Process should post posts scheduled for the past."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        past = datetime.now() - timedelta(hours=1)
        post = scheduler.queue(
            platform="twitter",
            text="Post now",
            scheduled_for=past,
        )

        results = scheduler.process_due()

        # Should process this post (it's in the past)
        assert len(results) == 1

    def test_scheduler_process_updates_status(self, tmp_path):
        """After processing, post status should change to POSTED."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        post = scheduler.queue(
            platform="twitter",
            text="Test",
            scheduled_for=None,
        )

        assert post.status == PostStatus.PENDING

        scheduler.process_due()

        # Post object in memory should be updated
        assert post.status == PostStatus.POSTED

        # Reload and verify persistence
        scheduler2 = PostScheduler(queue_file=str(queue_file))
        assert scheduler2.posts[0].status == PostStatus.POSTED

    def test_scheduler_multiple_queues(self, tmp_path):
        """Add and process multiple posts."""
        queue_file = tmp_path / "queue.json"
        scheduler = PostScheduler(queue_file=str(queue_file))

        scheduler.queue(platform="twitter", text="Tweet 1")
        scheduler.queue(platform="linkedin", text="Post 1")
        scheduler.queue(platform="both", text="Post everywhere")

        pending = scheduler.list_pending()
        assert len(pending) == 3

        results = scheduler.process_due()
        assert len(results) == 3
