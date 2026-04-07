"""MS Graph authentication via MSAL device code flow.

Design:
  - start_device_flow() returns the code + URL directly (no stderr, no log hunting)
  - complete_device_flow() polls until the user enters the code or timeout
  - Tokens cached at ~/.workflowx/ms_token_cache.bin (encrypted by MSAL)
  - Auto-refresh: get_token() silently refreshes if expired
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Standard Microsoft public client — same App ID used by Azure CLI, Graph Explorer
_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
_AUTHORITY = "https://login.microsoftonline.com/common"
_SCOPES = [
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/Team.ReadBasic.All",
    "https://graph.microsoft.com/Channel.ReadBasic.All",
    "https://graph.microsoft.com/ChannelMessage.Read.All",
    "https://graph.microsoft.com/Chat.Read",
    "https://graph.microsoft.com/User.Read",
    "offline_access",
]
_CACHE_PATH = Path.home() / ".workflowx" / "ms_token_cache.bin"
_FLOW_PATH = Path.home() / ".workflowx" / "ms_pending_flow.json"


class MSGraphAuth:
    """Handles MSAL device code flow with token caching.

    Usage (autonomous, code appears in MCP response):
        auth = MSGraphAuth()
        flow_info = auth.start_device_flow()
        # → {"user_code": "ABCD1234", "verification_uri": "https://microsoft.com/devicelogin", ...}
        # Show user_code + verification_uri to Wu in chat
        # Wu goes to the URL, enters the code

        token = auth.complete_device_flow(timeout=300)
        # → {"access_token": "...", "status": "ok"}
    """

    def __init__(self, cache_path: Path = _CACHE_PATH) -> None:
        self._cache_path = Path(cache_path)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._app = self._build_app()

    def _build_app(self):
        try:
            import msal
        except ImportError:
            raise ImportError("msal not installed. Run: pip install msal")

        cache = msal.SerializableTokenCache()
        if self._cache_path.exists():
            cache.deserialize(self._cache_path.read_text())

        app = msal.PublicClientApplication(
            _CLIENT_ID,
            authority=_AUTHORITY,
            token_cache=cache,
        )
        self._msal_cache = cache
        return app

    def _persist_cache(self) -> None:
        if self._msal_cache.has_state_changed:
            self._cache_path.write_text(self._msal_cache.serialize())

    def is_authenticated(self) -> bool:
        """Return True if a valid (or silently refreshable) token exists."""
        accounts = self._app.get_accounts()
        if not accounts:
            return False
        result = self._app.acquire_token_silent(_SCOPES, account=accounts[0])
        return result is not None and "access_token" in result

    def get_token(self) -> dict[str, Any]:
        """Get a valid access token, refreshing silently if needed.

        Returns:
            {"status": "ok", "access_token": "...", "account": "user@domain.com"}
            {"status": "error", "message": "Not authenticated. Call start_device_flow."}
        """
        accounts = self._app.get_accounts()
        if not accounts:
            return {"status": "error", "message": "Not authenticated. Call start_device_flow."}

        result = self._app.acquire_token_silent(_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            self._persist_cache()
            return {
                "status": "ok",
                "access_token": result["access_token"],
                "account": accounts[0].get("username", "unknown"),
            }

        return {"status": "error", "message": "Token expired and could not be refreshed silently."}

    def start_device_flow(self) -> dict[str, Any]:
        """Initiate device code flow. Returns the code + URL to show the user.

        The user_code and verification_uri are returned directly so they can be
        displayed in the chat — no log file hunting required.

        Returns:
            {
              "status": "ok",
              "user_code": "ABCD1234",
              "verification_uri": "https://microsoft.com/devicelogin",
              "expires_in": 900,
              "message": "Go to https://microsoft.com/devicelogin and enter ABCD1234"
            }
        """
        try:
            flow = self._app.initiate_device_flow(scopes=_SCOPES)
            if "user_code" not in flow:
                return {"status": "error", "message": flow.get("error_description", "Unknown error")}

            # Persist the flow so complete_device_flow can pick it up
            _FLOW_PATH.write_text(json.dumps(flow, default=str))

            logger.info("ms_graph_device_flow_started", user_code=flow["user_code"])
            return {
                "status": "ok",
                "user_code": flow["user_code"],
                "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
                "expires_in": flow.get("expires_in", 900),
                "message": (
                    f"Go to {flow.get('verification_uri', 'https://microsoft.com/devicelogin')} "
                    f"and enter code: {flow['user_code']}"
                ),
            }
        except Exception as e:
            logger.exception("ms_graph_device_flow_error", error=str(e))
            return {"status": "error", "message": str(e)}

    def complete_device_flow(self, timeout: int = 300) -> dict[str, Any]:
        """Poll for device code completion (call after user enters the code).

        Args:
            timeout: Seconds to wait for completion. Default 300 (5 min).

        Returns:
            {"status": "ok", "account": "user@domain.com", "message": "Authenticated!"}
            {"status": "error", "message": "..."}
        """
        if not _FLOW_PATH.exists():
            return {"status": "error", "message": "No pending flow. Call start_device_flow first."}

        try:
            flow = json.loads(_FLOW_PATH.read_text())
        except Exception as e:
            return {"status": "error", "message": f"Could not read pending flow: {e}"}

        logger.info("ms_graph_polling_for_completion", timeout=timeout)
        deadline = time.time() + timeout
        interval = flow.get("interval", 5)

        while time.time() < deadline:
            result = self._app.acquire_token_by_device_flow(flow)

            if "access_token" in result:
                self._persist_cache()
                _FLOW_PATH.unlink(missing_ok=True)
                accounts = self._app.get_accounts()
                account_name = accounts[0].get("username", "unknown") if accounts else "unknown"
                logger.info("ms_graph_authenticated", account=account_name)
                return {
                    "status": "ok",
                    "account": account_name,
                    "message": f"Authenticated as {account_name}",
                }

            error = result.get("error", "")
            if error == "authorization_pending":
                time.sleep(interval)
                continue
            elif error == "slow_down":
                interval = min(interval + 5, 30)
                time.sleep(interval)
                continue
            else:
                _FLOW_PATH.unlink(missing_ok=True)
                return {
                    "status": "error",
                    "message": result.get("error_description", f"Auth error: {error}"),
                }

        return {"status": "error", "message": "Timed out waiting for device code entry."}

    def revoke(self) -> dict[str, Any]:
        """Clear cached tokens (logout)."""
        if self._cache_path.exists():
            self._cache_path.unlink()
        _FLOW_PATH.unlink(missing_ok=True)
        return {"status": "ok", "message": "Tokens cleared."}
