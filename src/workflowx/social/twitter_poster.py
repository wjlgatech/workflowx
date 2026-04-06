"""Post to X/Twitter via tweepy v4 (X API v2).

Cost: ~$0.01/tweet via X API v2 paid tier.
Credentials: TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger()


class TwitterPoster:
    """Post tweets and threads to X/Twitter via tweepy."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        access_token: str | None = None,
        access_token_secret: str | None = None,
    ):
        """Initialize TwitterPoster with X API v2 credentials.

        Args:
            api_key: X API key (defaults to TWITTER_API_KEY env var)
            api_secret: X API secret (defaults to TWITTER_API_SECRET env var)
            access_token: X access token (defaults to TWITTER_ACCESS_TOKEN env var)
            access_token_secret: X access token secret
                (defaults to TWITTER_ACCESS_TOKEN_SECRET env var)

        Raises:
            ValueError: If any required credential is missing.
        """
        self.api_key = api_key or os.getenv("TWITTER_API_KEY")
        self.api_secret = api_secret or os.getenv("TWITTER_API_SECRET")
        self.access_token = access_token or os.getenv("TWITTER_ACCESS_TOKEN")
        self.access_token_secret = (
            access_token_secret or os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
        )

        missing = [
            name
            for name, value in [
                ("TWITTER_API_KEY", self.api_key),
                ("TWITTER_API_SECRET", self.api_secret),
                ("TWITTER_ACCESS_TOKEN", self.access_token),
                ("TWITTER_ACCESS_TOKEN_SECRET", self.access_token_secret),
            ]
            if not value
        ]

        if missing:
            raise ValueError(f"Missing required Twitter credentials: {', '.join(missing)}")

        self._client = None
        logger.info("twitter_poster_init", credentials_loaded=len(missing) == 0)

    @property
    def client(self):
        """Lazy-load tweepy client."""
        if self._client is None:
            try:
                import tweepy
            except ImportError:
                raise ImportError("tweepy not installed. Run: pip install tweepy>=4.14")

            self._client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                api_version="2",
            )
        return self._client

    def validate_text(self, text: str) -> tuple[bool, str]:
        """Validate tweet text against X's 280 character limit.

        Args:
            text: Tweet text to validate.

        Returns:
            Tuple of (is_valid, message).
            - is_valid: True if text is valid
            - message: "" if valid, error message if invalid
        """
        if not text:
            return False, "Tweet text cannot be empty"

        # X counts characters, not UTF-16 code units for most emoji
        # For simplicity, we use character length
        if len(text) > 280:
            return False, f"Tweet exceeds 280 characters ({len(text)} chars)"

        return True, ""

    def post_tweet(self, text: str) -> dict[str, Any]:
        """Post a single tweet to X.

        Args:
            text: Tweet text (max 280 characters).

        Returns:
            Dict with keys:
            - status: "ok" if successful, "error" if failed
            - tweet_id: X tweet ID (if successful)
            - url: Full tweet URL (if successful)
            - error: Error message (if failed)

        Cost: ~$0.01 per tweet via X API v2 paid tier.
        """
        is_valid, error_msg = self.validate_text(text)
        if not is_valid:
            logger.warning("twitter_post_invalid", error=error_msg, text_len=len(text))
            return {
                "status": "error",
                "error": error_msg,
            }

        try:
            response = self.client.create_tweet(text=text)
            tweet_id = response.data["id"]
            username = self.client.get_me().data.username
            url = f"https://x.com/{username}/status/{tweet_id}"

            logger.info(
                "twitter_post_success",
                tweet_id=tweet_id,
                text_len=len(text),
                url=url,
            )

            return {
                "status": "ok",
                "tweet_id": tweet_id,
                "url": url,
            }
        except Exception as e:
            logger.exception("twitter_post_failed", error=str(e))
            return {
                "status": "error",
                "error": str(e),
            }

    def post_thread(self, tweets: list[str]) -> dict[str, Any]:
        """Post a thread of tweets to X (chained by reply).

        Args:
            tweets: List of tweet texts (each max 280 characters).

        Returns:
            Dict with keys:
            - status: "ok" if all posted, "partial" if some failed, "error" if none posted
            - tweet_ids: List of tweet IDs (in order)
            - urls: List of tweet URLs (in order)
            - failed_indices: List of indices that failed
            - error: Error message (if status is "error")

        Note: Posts sequentially. Stops on first error unless continuing is desired.
        """
        if not tweets:
            return {
                "status": "error",
                "error": "No tweets to post",
            }

        tweet_ids = []
        urls = []
        failed_indices = []

        try:
            username = self.client.get_me().data.username
        except Exception as e:
            logger.exception("twitter_thread_auth_failed", error=str(e))
            return {
                "status": "error",
                "error": f"Failed to authenticate: {e}",
            }

        reply_to_id = None

        for idx, text in enumerate(tweets):
            is_valid, error_msg = self.validate_text(text)
            if not is_valid:
                logger.warning(
                    "twitter_thread_invalid_tweet",
                    index=idx,
                    error=error_msg,
                )
                failed_indices.append(idx)
                continue

            try:
                response = self.client.create_tweet(
                    text=text,
                    reply_settings="everyone" if reply_to_id is None else None,
                    in_reply_to_tweet_id=reply_to_id,
                )
                tweet_id = response.data["id"]
                url = f"https://x.com/{username}/status/{tweet_id}"

                tweet_ids.append(tweet_id)
                urls.append(url)
                reply_to_id = tweet_id

                logger.info(
                    "twitter_thread_post_success",
                    index=idx,
                    tweet_id=tweet_id,
                    reply_to=reply_to_id,
                )
            except Exception as e:
                logger.exception(
                    "twitter_thread_post_failed",
                    index=idx,
                    error=str(e),
                )
                failed_indices.append(idx)

        if not tweet_ids:
            return {
                "status": "error",
                "error": "Failed to post any tweets in thread",
                "failed_indices": failed_indices,
            }

        status = "ok" if not failed_indices else "partial"
        return {
            "status": status,
            "tweet_ids": tweet_ids,
            "urls": urls,
            "failed_indices": failed_indices,
            "total_posted": len(tweet_ids),
            "total_requested": len(tweets),
        }
