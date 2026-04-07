"""MS Graph API client for Outlook and Teams.

All methods return plain dicts — no exceptions leak out.
Auth is handled transparently via MSGraphAuth.get_token().
"""

from __future__ import annotations

from typing import Any

import structlog

from workflowx.ms_graph.auth import MSGraphAuth

logger = structlog.get_logger()

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class MSGraphClient:
    """Thin wrapper around MS Graph REST API.

    Usage:
        client = MSGraphClient()
        emails = client.list_recent_emails(count=10)
        channels = client.list_teams_channels(team_id="...")
    """

    def __init__(self, auth: MSGraphAuth | None = None) -> None:
        self._auth = auth or MSGraphAuth()

    def _headers(self) -> dict[str, str] | None:
        result = self._auth.get_token()
        if result["status"] != "ok":
            return None
        return {
            "Authorization": f"Bearer {result['access_token']}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        try:
            import requests
        except ImportError:
            return {"status": "error", "message": "requests not installed"}

        headers = self._headers()
        if headers is None:
            return {"status": "error", "message": "Not authenticated. Call workflowx_ms_auth_start."}

        r = requests.get(f"{_GRAPH_BASE}{path}", headers=headers, params=params, timeout=30)
        if not r.ok:
            logger.warning("ms_graph_get_error", path=path, status=r.status_code)
            return {"status": "error", "code": r.status_code, "message": r.text[:200]}
        return {"status": "ok", "data": r.json()}

    def _post(self, path: str, body: dict) -> dict[str, Any]:
        try:
            import requests
        except ImportError:
            return {"status": "error", "message": "requests not installed"}

        headers = self._headers()
        if headers is None:
            return {"status": "error", "message": "Not authenticated. Call workflowx_ms_auth_start."}

        r = requests.post(f"{_GRAPH_BASE}{path}", headers=headers, json=body, timeout=30)
        if not r.ok:
            logger.warning("ms_graph_post_error", path=path, status=r.status_code)
            return {"status": "error", "code": r.status_code, "message": r.text[:200]}
        return {"status": "ok", "data": r.json() if r.content else {}}

    # ── Outlook ──────────────────────────────────────────────────────────────

    def list_recent_emails(self, count: int = 20, folder: str = "inbox") -> dict[str, Any]:
        """List recent emails from a mail folder."""
        result = self._get(
            f"/me/mailFolders/{folder}/messages",
            params={
                "$top": count,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
            },
        )
        if result["status"] != "ok":
            return result
        msgs = result["data"].get("value", [])
        return {
            "status": "ok",
            "count": len(msgs),
            "messages": [
                {
                    "id": m["id"],
                    "subject": m.get("subject", "(no subject)"),
                    "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "received": m.get("receivedDateTime", ""),
                    "preview": m.get("bodyPreview", "")[:120],
                    "read": m.get("isRead", True),
                }
                for m in msgs
            ],
        }

    def search_emails(self, query: str, count: int = 10) -> dict[str, Any]:
        """Search emails by keyword."""
        result = self._get(
            "/me/messages",
            params={
                "$search": f'"{query}"',
                "$top": count,
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
            },
        )
        if result["status"] != "ok":
            return result
        msgs = result["data"].get("value", [])
        return {
            "status": "ok",
            "count": len(msgs),
            "messages": [
                {
                    "id": m["id"],
                    "subject": m.get("subject", "(no subject)"),
                    "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "received": m.get("receivedDateTime", ""),
                    "preview": m.get("bodyPreview", "")[:120],
                }
                for m in msgs
            ],
        }

    def create_draft(self, to: str, subject: str, body: str, html: bool = False) -> dict[str, Any]:
        """Create an Outlook draft."""
        payload = {
            "subject": subject,
            "body": {"contentType": "HTML" if html else "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        result = self._post("/me/messages", payload)
        if result["status"] != "ok":
            return result
        return {"status": "ok", "draft_id": result["data"].get("id"), "subject": subject, "to": to}

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        """Send a previously created draft."""
        try:
            import requests
        except ImportError:
            return {"status": "error", "message": "requests not installed"}

        headers = self._headers()
        if headers is None:
            return {"status": "error", "message": "Not authenticated."}

        r = requests.post(
            f"{_GRAPH_BASE}/me/messages/{draft_id}/send",
            headers=headers,
            timeout=30,
        )
        if r.ok:
            return {"status": "ok", "message": "Email sent."}
        return {"status": "error", "code": r.status_code, "message": r.text[:200]}

    # ── Teams ─────────────────────────────────────────────────────────────────

    def list_teams(self) -> dict[str, Any]:
        """List Teams the user is a member of."""
        result = self._get("/me/joinedTeams", params={"$select": "id,displayName,description"})
        if result["status"] != "ok":
            return result
        teams = result["data"].get("value", [])
        return {
            "status": "ok",
            "count": len(teams),
            "teams": [{"id": t["id"], "name": t.get("displayName", ""), "desc": t.get("description", "")} for t in teams],
        }

    def list_channels(self, team_id: str) -> dict[str, Any]:
        """List channels in a Team."""
        result = self._get(f"/teams/{team_id}/channels", params={"$select": "id,displayName,description"})
        if result["status"] != "ok":
            return result
        channels = result["data"].get("value", [])
        return {
            "status": "ok",
            "count": len(channels),
            "channels": [{"id": c["id"], "name": c.get("displayName", "")} for c in channels],
        }

    def read_channel_messages(self, team_id: str, channel_id: str, count: int = 20) -> dict[str, Any]:
        """Read recent messages from a Teams channel."""
        result = self._get(
            f"/teams/{team_id}/channels/{channel_id}/messages",
            params={"$top": count},
        )
        if result["status"] != "ok":
            return result
        msgs = result["data"].get("value", [])
        return {
            "status": "ok",
            "count": len(msgs),
            "messages": [
                {
                    "id": m["id"],
                    "from": m.get("from", {}).get("user", {}).get("displayName", ""),
                    "created": m.get("createdDateTime", ""),
                    "body": m.get("body", {}).get("content", "")[:300],
                }
                for m in msgs
            ],
        }

    def post_channel_message(self, team_id: str, channel_id: str, text: str) -> dict[str, Any]:
        """Post a message to a Teams channel."""
        payload = {"body": {"contentType": "text", "content": text}}
        result = self._post(f"/teams/{team_id}/channels/{channel_id}/messages", payload)
        if result["status"] != "ok":
            return result
        return {"status": "ok", "message_id": result["data"].get("id"), "text_preview": text[:80]}
