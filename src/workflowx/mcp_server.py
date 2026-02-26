"""MCP Server — lets Claude, Cursor, and other AI tools query your workflow data.

This is the bridge between WorkflowX (your local workflow intelligence)
and whatever AI assistant you use. Claude can ask "what were my high-friction
workflows this week?" and get structured answers.

Runs as a FastMCP server on stdio (for Claude Code/Cursor integration)
or HTTP (for remote access).

Usage:
    workflowx mcp          # Start MCP server on stdio
    workflowx mcp --http   # Start on HTTP (localhost:8765)
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()


def _get_store():
    """Lazy-load store to avoid import-time side effects."""
    from workflowx.config import load_config
    from workflowx.storage import LocalStore

    config = load_config()
    return LocalStore(config.data_dir), config


def _sessions_for_period(period: str = "today") -> list:
    """Load sessions for a named period."""
    store, config = _get_store()

    if period == "today":
        return store.load_sessions(date.today())
    elif period == "yesterday":
        return store.load_sessions(date.today() - timedelta(days=1))
    elif period == "week":
        sessions = []
        for i in range(7):
            d = date.today() - timedelta(days=i)
            sessions.extend(store.load_sessions(d))
        return sessions
    elif period == "month":
        sessions = []
        for i in range(30):
            d = date.today() - timedelta(days=i)
            sessions.extend(store.load_sessions(d))
        return sessions
    else:
        return store.load_sessions(date.today())


# ── MCP Tool Handlers ────────────────────────────────────────
# These functions are the actual tool implementations.
# Each returns a dict that gets JSON-serialized as the MCP response.


def handle_get_sessions(period: str = "today") -> dict[str, Any]:
    """Get workflow sessions for a time period.

    Args:
        period: "today", "yesterday", "week", or "month"

    Returns a summary of sessions with intents, friction, and time.
    """
    sessions = _sessions_for_period(period)

    return {
        "period": period,
        "total_sessions": len(sessions),
        "total_minutes": round(sum(s.total_duration_minutes for s in sessions), 1),
        "sessions": [
            {
                "time": f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}",
                "duration_min": round(s.total_duration_minutes, 1),
                "intent": s.inferred_intent or "(unknown)",
                "friction": s.friction_level.value,
                "apps": s.apps_used[:5],
                "switches": s.context_switches,
            }
            for s in sessions
        ],
    }


def handle_get_friction(period: str = "week") -> dict[str, Any]:
    """Get high-friction workflows for a period.

    Returns only sessions with HIGH or CRITICAL friction, sorted by cost.
    """
    sessions = _sessions_for_period(period)
    from workflowx.models import FrictionLevel

    high_friction = [
        s for s in sessions
        if s.friction_level in (FrictionLevel.HIGH, FrictionLevel.CRITICAL)
    ]
    high_friction.sort(key=lambda s: s.total_duration_minutes, reverse=True)

    _, config = _get_store()
    rate = config.hourly_rate_usd

    return {
        "period": period,
        "high_friction_sessions": len(high_friction),
        "total_friction_minutes": round(sum(s.total_duration_minutes for s in high_friction), 1),
        "estimated_weekly_cost_usd": round(
            sum(s.total_duration_minutes for s in high_friction) / 60.0 * rate, 2
        ),
        "sessions": [
            {
                "intent": s.inferred_intent or "(unknown)",
                "duration_min": round(s.total_duration_minutes, 1),
                "friction": s.friction_level.value,
                "apps": s.apps_used[:5],
                "cost_usd": round(s.total_duration_minutes / 60.0 * rate, 2),
            }
            for s in high_friction[:10]
        ],
    }


def handle_get_patterns() -> dict[str, Any]:
    """Detect recurring workflow patterns across the last 30 days."""
    sessions = _sessions_for_period("month")
    from workflowx.inference.patterns import detect_patterns

    patterns = detect_patterns(sessions)

    return {
        "patterns_found": len(patterns),
        "patterns": [
            {
                "intent": p.intent,
                "occurrences": p.occurrences,
                "avg_duration_min": p.avg_duration_minutes,
                "total_time_min": p.total_time_invested_minutes,
                "friction": p.most_common_friction.value,
                "trend": p.trend,
                "apps": p.apps_involved[:5],
            }
            for p in patterns
        ],
    }


def handle_get_trends() -> dict[str, Any]:
    """Get weekly friction trends for the last 4 weeks."""
    sessions = _sessions_for_period("month")
    from workflowx.inference.patterns import compute_friction_trends

    trends = compute_friction_trends(sessions, num_weeks=4)

    trajectory = "stable"
    if len(trends) >= 2:
        diff = trends[-1].high_friction_ratio - trends[0].high_friction_ratio
        if diff > 0.1:
            trajectory = "worsening"
        elif diff < -0.1:
            trajectory = "improving"

    return {
        "weeks": len(trends),
        "trajectory": trajectory,
        "trends": [
            {
                "week": t.week_label,
                "sessions": t.total_sessions,
                "total_min": t.total_minutes,
                "friction_ratio": round(t.high_friction_ratio, 3),
                "avg_switches": t.avg_switches_per_session,
                "top_friction": t.top_friction_intents,
            }
            for t in trends
        ],
    }


def handle_get_roi() -> dict[str, Any]:
    """Get ROI summary from replacement outcomes."""
    store, config = _get_store()
    from workflowx.measurement import compute_roi_summary

    outcomes = store.load_outcomes()
    return compute_roi_summary(outcomes)


# ── MCP Server Setup ─────────────────────────────────────────


TOOL_REGISTRY = {
    "workflowx_sessions": {
        "handler": handle_get_sessions,
        "description": "Get workflow sessions for a time period (today/yesterday/week/month)",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month"],
                    "default": "today",
                    "description": "Time period to query",
                },
            },
        },
    },
    "workflowx_friction": {
        "handler": handle_get_friction,
        "description": "Get high-friction workflows with cost estimates",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month"],
                    "default": "week",
                },
            },
        },
    },
    "workflowx_patterns": {
        "handler": handle_get_patterns,
        "description": "Detect recurring workflow patterns across the last 30 days",
        "parameters": {"type": "object", "properties": {}},
    },
    "workflowx_trends": {
        "handler": handle_get_trends,
        "description": "Get weekly friction trends (is friction improving or worsening?)",
        "parameters": {"type": "object", "properties": {}},
    },
    "workflowx_roi": {
        "handler": handle_get_roi,
        "description": "Get ROI summary from adopted workflow replacements",
        "parameters": {"type": "object", "properties": {}},
    },
}


def create_mcp_server():
    """Create and configure the MCP server.

    Uses FastMCP if available, otherwise falls back to a basic JSON-RPC handler.
    """
    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("workflowx")

        @mcp.tool()
        def workflowx_sessions(period: str = "today") -> str:
            """Get workflow sessions for a time period."""
            return json.dumps(handle_get_sessions(period), default=str)

        @mcp.tool()
        def workflowx_friction(period: str = "week") -> str:
            """Get high-friction workflows with cost estimates."""
            return json.dumps(handle_get_friction(period), default=str)

        @mcp.tool()
        def workflowx_patterns() -> str:
            """Detect recurring workflow patterns."""
            return json.dumps(handle_get_patterns(), default=str)

        @mcp.tool()
        def workflowx_trends() -> str:
            """Get weekly friction trends."""
            return json.dumps(handle_get_trends(), default=str)

        @mcp.tool()
        def workflowx_roi() -> str:
            """Get ROI from adopted replacements."""
            return json.dumps(handle_get_roi(), default=str)

        return mcp

    except ImportError:
        logger.warning("fastmcp_not_installed", msg="Install mcp package for MCP server support")
        return None


def run_mcp_stdio():
    """Run MCP server on stdio (for Claude Code / Cursor integration)."""
    server = create_mcp_server()
    if server is None:
        raise RuntimeError(
            "MCP server requires the 'mcp' package. "
            "Install with: pip install 'workflowx[mcp]'"
        )
    server.run()


def run_mcp_http(host: str = "localhost", port: int = 8765):
    """Run MCP server on HTTP."""
    server = create_mcp_server()
    if server is None:
        raise RuntimeError("MCP server requires the 'mcp' package.")
    server.run(transport="sse", host=host, port=port)
