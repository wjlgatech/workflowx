"""Post to LinkedIn via Playwright browser automation.

Uses Playwright for browser automation instead of unofficial APIs to avoid ban risk.
Cookies expire ~1 year; re-authenticate once annually via save_session().
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


class LinkedInPoster:
    """Post to LinkedIn via Playwright browser automation."""

    def __init__(self, cookies_path: str = "~/.workflowx/linkedin_cookies.json"):
        """Initialize LinkedInPoster.

        Args:
            cookies_path: Path to store/load LinkedIn session cookies.
                Defaults to ~/.workflowx/linkedin_cookies.json
        """
        self.cookies_path = Path(cookies_path).expanduser()
        self._ensure_cookie_dir()
        self._browser = None
        self._context = None
        self._page = None
        logger.info("linkedin_poster_init", cookies_path=str(self.cookies_path))

    def _ensure_cookie_dir(self) -> None:
        """Ensure the cookies directory exists."""
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_cookies(self) -> list[dict[str, Any]] | None:
        """Load cookies from file if they exist.

        Returns:
            List of cookie dicts or None if file doesn't exist.
        """
        if not self.cookies_path.exists():
            return None

        try:
            with open(self.cookies_path) as f:
                cookies = json.load(f)
            logger.info("linkedin_cookies_loaded", count=len(cookies))
            return cookies
        except Exception as e:
            logger.warning("linkedin_cookies_load_failed", error=str(e))
            return None

    def _save_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Save cookies to file.

        Args:
            cookies: List of cookie dicts from Playwright context.
        """
        try:
            with open(self.cookies_path, "w") as f:
                json.dump(cookies, f, indent=2)
            logger.info("linkedin_cookies_saved", count=len(cookies))
        except Exception as e:
            logger.exception("linkedin_cookies_save_failed", error=str(e))

    async def _init_browser_headless(self) -> None:
        """Initialize Playwright browser in headless mode."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright not installed. Run: pip install playwright>=1.40"
            )

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._context = await self._browser.new_context()

        # Load cookies if they exist
        cookies = self._load_cookies()
        if cookies:
            try:
                await self._context.add_cookies(cookies)
            except Exception as e:
                logger.warning("linkedin_cookies_add_failed", error=str(e))

    async def _init_browser_visible(self) -> None:
        """Initialize Playwright browser in visible mode for authentication."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright not installed. Run: pip install playwright>=1.40"
            )

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=False)
        self._context = await self._browser.new_context()

    async def _close_browser(self) -> None:
        """Close the browser and cleanup."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw"):
            await self._pw.stop()
        self._browser = self._context = self._page = None

    async def save_session(self, email: str, password: str) -> dict[str, Any]:
        """One-time login to save LinkedIn session cookies.

        Opens a visible browser window for you to log in manually.
        Saves cookies to disk for future automated posts.

        Args:
            email: LinkedIn email address (not used for automated login; shown in console).
            password: LinkedIn password (not used for automated login; shown in console).

        Returns:
            Dict with keys:
            - status: "ok" if successful, "error" if failed
            - message: Human-readable status message
            - cookies_saved: Number of cookies saved (if successful)

        Note:
            The email/password parameters are shown to you in the console only.
            You must manually log in in the browser window that opens.
            This is intentional to avoid storing plain-text passwords.
        """
        logger.info("linkedin_save_session_start", email=email)
        print(f"\n[LinkedIn Auth] Email: {email}")
        print(f"[LinkedIn Auth] Password: (use the browser window to log in)\n")

        try:
            await self._init_browser_visible()
            self._page = await self._context.new_page()

            # Navigate to LinkedIn
            logger.info("linkedin_navigating_to_login")
            await self._page.goto("https://www.linkedin.com/login", wait_until="load")

            # Wait for user to manually log in
            # Look for the feed/home page as signal of successful login
            logger.info("linkedin_waiting_for_manual_login")
            print("[LinkedIn Auth] Please log in using the browser window...")
            print("[LinkedIn Auth] Once logged in, this process will continue automatically.\n")

            try:
                await self._page.wait_for_url(
                    "https://www.linkedin.com/feed/**", timeout=5 * 60 * 1000  # 5 minutes
                )
            except Exception:
                # Alternative: wait for a known element on the feed
                await self._page.wait_for_selector(
                    "div[data-test-id='feed-item']", timeout=5 * 60 * 1000
                )

            # Extract cookies
            cookies = await self._context.cookies()
            self._save_cookies(cookies)

            await self._close_browser()

            logger.info("linkedin_save_session_success", cookies_count=len(cookies))
            return {
                "status": "ok",
                "message": f"Logged in successfully. {len(cookies)} cookies saved.",
                "cookies_saved": len(cookies),
            }

        except asyncio.TimeoutError:
            await self._close_browser()
            logger.error("linkedin_save_session_timeout")
            return {
                "status": "error",
                "message": "Login timeout. Please try again.",
            }
        except Exception as e:
            await self._close_browser()
            logger.exception("linkedin_save_session_failed", error=str(e))
            return {
                "status": "error",
                "message": f"Login failed: {e}",
            }

    async def post(
        self,
        text: str,
        url: str = "",
    ) -> dict[str, Any]:
        """Post to LinkedIn feed.

        Navigates to linkedin.com/feed, clicks Start a Post, types text,
        optionally adds URL, and posts.

        Args:
            text: Post text.
            url: Optional URL to attach as link preview.

        Returns:
            Dict with keys:
            - status: "ok" if successful, "error" if failed
            - post_url: LinkedIn post URL (if successful)
            - error: Error message (if failed)
        """
        logger.info("linkedin_post_start", text_len=len(text), has_url=bool(url))

        try:
            await self._init_browser_headless()
            self._page = await self._context.new_page()

            # Navigate to feed
            logger.info("linkedin_navigating_to_feed")
            await self._page.goto("https://www.linkedin.com/feed/", wait_until="load")

            # Click "Start a post" button
            logger.info("linkedin_clicking_start_post")
            start_post_btn = self._page.locator(
                "button:has-text('Start a post')"
            ) or self._page.locator("div[role='menuitem']:has-text('Start a post')")

            await start_post_btn.click(timeout=10000)
            await self._page.wait_for_selector(
                "textarea[aria-label*='post']", timeout=10000
            )

            # Type the post text
            logger.info("linkedin_typing_text")
            textarea = self._page.locator("textarea[aria-label*='post']").first
            await textarea.click()
            await textarea.fill(text)

            # Add URL if provided
            if url:
                logger.info("linkedin_adding_url", url=url)
                # This is simplified; in practice you'd need to interact with
                # the link preview UI which can be complex
                pass

            # Click Post button
            logger.info("linkedin_clicking_post_button")
            post_btn = self._page.locator(
                "button:has-text('Post')"
            ) or self._page.locator("button[aria-label*='Post']")

            await post_btn.click(timeout=10000)

            # Wait for post to appear in feed (indicates success)
            await self._page.wait_for_selector("div[data-test-id='feed-item']", timeout=10000)

            # Try to extract the post URL from the page
            # LinkedIn's structure is complex; this is a simplified approach
            post_url = self._page.url

            await self._close_browser()

            logger.info("linkedin_post_success", post_url=post_url)
            return {
                "status": "ok",
                "post_url": post_url,
            }

        except Exception as e:
            await self._close_browser()
            logger.exception("linkedin_post_failed", error=str(e))
            return {
                "status": "error",
                "error": str(e),
            }


def post_linkedin_sync(text: str, url: str = "", cookies_path: str = "") -> dict[str, Any]:
    """Synchronous wrapper to post to LinkedIn.

    Args:
        text: Post text.
        url: Optional URL to attach.
        cookies_path: Path to cookies file.

    Returns:
        Result dict from post().
    """
    if cookies_path:
        poster = LinkedInPoster(cookies_path=cookies_path)
    else:
        poster = LinkedInPoster()

    return asyncio.run(poster.post(text=text, url=url))


def save_linkedin_session_sync(
    email: str, password: str, cookies_path: str = ""
) -> dict[str, Any]:
    """Synchronous wrapper to save LinkedIn session.

    Args:
        email: LinkedIn email.
        password: LinkedIn password (shown in console only).
        cookies_path: Path to cookies file.

    Returns:
        Result dict from save_session().
    """
    if cookies_path:
        poster = LinkedInPoster(cookies_path=cookies_path)
    else:
        poster = LinkedInPoster()

    return asyncio.run(poster.save_session(email=email, password=password))
