"""Live dashboard server — serves a real-time WorkflowX dashboard on localhost.

Routes:
  GET /          → live dashboard HTML (data fetched client-side via /api/data)
  GET /api/data  → fresh JSON snapshot for charts + KPIs
  GET /events    → SSE stream — pushes "reload" when watched data changes

Two server modes:
  run_server()       — WorkflowX live dashboard (with --watch: auto-refresh on
                       new sessions/patterns from daemon or manual capture)
  run_file_server()  — Serve any HTML file with hot-reload (e.g., an edited
                       workflowx-demo-dashboard.html) — eliminates manual
                       browser refreshes during dashboard iteration
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# ── SSE broadcast ──────────────────────────────────────────────────────────────
# One queue per connected /events client. Watchers push "reload" to all queues.
_reload_queues: list[queue.Queue] = []
_reload_lock = threading.Lock()

# Script injected into arbitrary HTML files served via run_file_server --watch.
# Uses a full-page reload (location.reload) rather than a data refresh since
# the file's HTML structure itself may have changed.
_LIVE_RELOAD_SCRIPT = (
    "<script>"
    "(function(){"
    "var es=new EventSource('/events');"
    "es.onmessage=function(e){if(e.data==='reload')location.reload();};"
    "es.onerror=function(){setTimeout(function(){es=new EventSource('/events');},3000);};"
    "})();"
    "</script>"
)


def _broadcast_reload() -> None:
    """Push a reload signal to every connected SSE client."""
    with _reload_lock:
        for q in list(_reload_queues):
            try:
                q.put_nowait("reload")
            except queue.Full:
                pass


def _inject_live_reload(html: str) -> str:
    """Inject SSE live-reload script before </body> (or at end if absent)."""
    if "</body>" in html:
        return html.replace("</body>", _LIVE_RELOAD_SCRIPT + "\n</body>", 1)
    return html + "\n" + _LIVE_RELOAD_SCRIPT


def _start_data_watcher(data_dir: Path) -> None:
    """Watch data_dir for JSON writes → broadcast reload on change.

    Used by run_server(watch=True): when the daemon or manual capture writes
    new session/pattern files, all connected dashboard browsers auto-refresh.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.warning("watchdog_not_installed", msg="pip install watchdog")
        return

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory and str(event.src_path).endswith(".json"):
                _broadcast_reload()

        on_created = on_modified

    observer = Observer()
    observer.schedule(_Handler(), str(data_dir), recursive=False)
    observer.daemon = True
    observer.start()
    logger.info("data_watcher_started", watching=str(data_dir))


def _start_file_watcher(file_path: Path) -> None:
    """Watch a specific file → broadcast reload when it changes.

    Used by run_file_server(watch=True): when you save the HTML file in
    your editor, all browser tabs auto-reload without a manual refresh.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.warning("watchdog_not_installed", msg="pip install watchdog")
        return

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if Path(event.src_path).resolve() == file_path.resolve():
                _broadcast_reload()

        on_created = on_modified

    observer = Observer()
    observer.schedule(_Handler(), str(file_path.parent), recursive=False)
    observer.daemon = True
    observer.start()
    logger.info("file_watcher_started", watching=str(file_path))


# ── HTTP Handler ───────────────────────────────────────────────────────────────


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


def _make_handler(
    config: Any | None,
    store: Any | None,
    dashboard_html: str,
    file_path: Path | None = None,
) -> type:
    """Return a request handler class.

    - file_path=None : serve dashboard_html + /api/data
    - file_path set  : re-read and serve that file on every GET / (with
                       live-reload script injected if --watch is active)

    Both modes expose GET /events for SSE live-reload.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                if file_path is not None:
                    try:
                        html = _inject_live_reload(file_path.read_text())
                    except OSError as e:
                        self.send_error(500, str(e))
                        return
                else:
                    html = dashboard_html
                self._send(200, "text/html; charset=utf-8", html.encode())

            elif self.path == "/api/data" and store is not None:
                try:
                    body = json.dumps(_build_data(config, store)).encode()
                    self._send(200, "application/json", body)
                except Exception as e:
                    logger.error("dashboard_data_error", error=str(e))
                    self.send_error(500, str(e))

            elif self.path == "/events":
                self._stream_sse()

            else:
                self.send_error(404)

        def _send(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream_sse(self) -> None:
            """Hold the connection open, forwarding reload signals as SSE events.

            Heartbeat comments every 25 s keep proxies and browsers from timing out.
            Each connected tab gets its own queue; the handler removes it on disconnect.
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            q: queue.Queue = queue.Queue(maxsize=10)
            with _reload_lock:
                _reload_queues.append(q)

            try:
                while True:
                    try:
                        msg = q.get(timeout=25)
                        self.wfile.write(f"data: {msg}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # client disconnected
            finally:
                with _reload_lock:
                    if q in _reload_queues:
                        _reload_queues.remove(q)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # suppress per-request logs

    return _Handler


# ── Public API ─────────────────────────────────────────────────────────────────

try:
    from http.server import ThreadingHTTPServer as _ServerBase  # Python 3.7+
except ImportError:
    _ServerBase = HTTPServer  # type: ignore[assignment,misc]


def run_server(config: Any, store: Any, port: int = 7788, watch: bool = False) -> None:
    """Start the live WorkflowX dashboard server. Blocks until Ctrl+C.

    With watch=True: a watchdog observer monitors config.data_dir for JSON
    writes (new sessions, patterns) and auto-refreshes all connected browsers
    via SSE — no Update button click required.
    """
    from workflowx.dashboard import generate_live_dashboard_html

    html = generate_live_dashboard_html()
    handler_cls = _make_handler(config, store, html)
    server = _ServerBase(("127.0.0.1", port), handler_cls)
    if watch:
        _start_data_watcher(Path(config.data_dir))
    logger.info("live_dashboard_started", url=f"http://localhost:{port}", watch=watch)
    server.serve_forever()


def run_file_server(file_path: Path, port: int = 7788, watch: bool = False) -> None:
    """Serve an HTML file at localhost:PORT with optional live-reload.

    When watch=True, the browser auto-reloads whenever the file changes on disk.
    Eliminates the VS Code → Chrome manual-refresh cycle during dashboard editing.

    Usage:
        workflowx serve --file workflowx-demo-dashboard.html --watch
    """
    handler_cls = _make_handler(
        config=None, store=None, dashboard_html="", file_path=file_path
    )
    server = _ServerBase(("127.0.0.1", port), handler_cls)
    if watch:
        _start_file_watcher(file_path)
    logger.info(
        "file_server_started",
        file=str(file_path),
        url=f"http://localhost:{port}",
        watch=watch,
    )
    server.serve_forever()
