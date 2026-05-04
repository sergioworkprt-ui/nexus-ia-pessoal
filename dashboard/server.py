"""
NEXUS Dashboard Server
Lightweight read-only web dashboard using Python stdlib only.
Serves live runtime data from JSON/JSONL files.

Usage:
    from dashboard.server import DashboardServer, start_dashboard

    # Blocking
    start_dashboard(host="127.0.0.1", port=7000)

    # Non-blocking (background thread)
    srv = DashboardServer(host="127.0.0.1", port=7000)
    srv.start_background()
    ...
    srv.stop()
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlparse

from . import pages


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        # Route dispatch
        if path == "/":
            html = pages.render_overview()
        elif path == "/pipelines":
            html = pages.render_pipelines()
        elif path == "/signals":
            html = pages.render_signals()
        elif path == "/risk":
            html = pages.render_risk()
        elif path == "/audit":
            html = pages.render_audit()
        elif path == "/reports":
            html = pages.render_reports()
        elif path.startswith("/reports/"):
            name = path[len("/reports/"):]
            html = pages.render_report_detail(name)
        elif path == "/evolution":
            html = pages.render_evolution()
        elif path == "/limits":
            html = pages.render_limits()
        elif path == "/ibkr":
            html = pages.render_ibkr()
        elif path == "/ibkr/positions":
            html = pages.render_ibkr_positions()
        elif path == "/ibkr/orders":
            html = pages.render_ibkr_orders()
        elif path == "/ibkr/capital":
            html = pages.render_ibkr_capital()
        else:
            self._send(404, pages.render_404(path))
            return

        self._send(200, html)

    def _send(self, code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        pass  # silence default access log spam


# ---------------------------------------------------------------------------
# Server wrapper
# ---------------------------------------------------------------------------

class DashboardServer:
    """Manages the HTTP server lifecycle."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7000) -> None:
        self.host = host
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start_background(self) -> None:
        """Start the server in a daemon thread."""
        self._server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="nexus-dashboard",
            daemon=True,
        )
        self._thread.start()

    def serve_forever(self) -> None:
        """Start the server, blocking the current thread."""
        self._server = HTTPServer((self.host, self.port), _Handler)
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def start_dashboard(
    host: str = "127.0.0.1",
    port: int = 7000,
    background: bool = False,
) -> DashboardServer:
    """
    Start the NEXUS dashboard server.
    Returns the DashboardServer instance (useful for stopping it later).
    """
    srv = DashboardServer(host=host, port=port)
    if background:
        srv.start_background()
    else:
        srv.serve_forever()
    return srv
