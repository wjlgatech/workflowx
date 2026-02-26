"""Live dashboard server — serves a real-time WorkflowX dashboard on localhost.

Uses Python's built-in http.server — no extra dependencies.
Exposes two routes:
  GET /          → live dashboard HTML (JS fetches data client-side)
  GET /api/data  → fresh JSON data for all charts + KPIs
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import structlog

logger = structlog.get_logger()


def _build_data(config: Any, store: Any) -> dict[str, Any]:
    """Pull fresh data from storage and return as chart-ready dict."""
    from workflowx.inference.patterns import compute_friction_trends, detect_patterns
    from workflowx.measurement import compute_roi_summary

    today = date.today()
    all_sessions = []
    for i in range(30):
        d = today - timedelta(days=i)
        all_sessions.extend(store.load_sessions(d))

    patterns = detect_patterns(all_sessions) if all_sessions else []
    trends = compute_friction_trends(all_sessions) if all_sessions else []
    outcomes = store.load_outcomes()
    roi = compute_roi_summary(outcomes)

    return {
        "trend_labels": [t.week_label for t in trends],
        "trend_friction": [round(t.high_friction_ratio * 100, 1) for t in trends],
        "trend_minutes": [round(t.total_minutes, 0) for t in trends],
        "pattern_labels": [p.intent[:25] for p in patterns[:8]],
        "pattern_times": [round(p.total_time_invested_minutes, 0) for p in patterns[:8]],
        "outcome_labels": [o["intent"][:20] for o in roi["outcomes"][:10]],
        "outcome_before": [o["before"] for o in roi["outcomes"][:10]],
        "outcome_after": [o["after"] for o in roi["outcomes"][:10]],
        "kpis": {
            "weekly_minutes": roi["total_weekly_savings_minutes"],
            "weekly_hours": roi["total_weekly_savings_hours"],
            "weekly_usd": roi["total_weekly_savings_hours"] * config.hourly_rate_usd,
            "cumulative_hours": roi["total_cumulative_savings_hours"],
            "cumulative_usd": roi["total_cumulative_savings_hours"] * config.hourly_rate_usd,
            "total_outcomes": roi["total_outcomes"],
            "adopted": roi["adopted"],
            "rejected": roi["rejected"],
            "measuring": roi["measuring"],
            "adoption_rate": roi["adoption_rate"],
        },
        "session_count": len(all_sessions),
    }


def _make_handler(config: Any, store: Any, dashboard_html: str) -> type:
    """Return a request handler class bound to config/store/html."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                body = dashboard_html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path == "/api/data":
                try:
                    data = _build_data(config, store)
                    body = json.dumps(data).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as e:
                    logger.error("dashboard_data_error", error=str(e))
                    self.send_error(500, str(e))

            else:
                self.send_error(404)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # suppress per-request logs; server start is logged separately

    return _Handler


def run_server(config: Any, store: Any, port: int = 7788) -> None:
    """Start the live dashboard HTTP server. Blocks until Ctrl+C."""
    from workflowx.dashboard import generate_live_dashboard_html

    html = generate_live_dashboard_html()
    handler_cls = _make_handler(config, store, html)
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    logger.info("live_dashboard_started", url=f"http://localhost:{port}")
    server.serve_forever()
