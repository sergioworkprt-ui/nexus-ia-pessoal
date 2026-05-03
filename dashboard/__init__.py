"""
NEXUS Dashboard — read-only runtime web dashboard.

Quick start:
    python nexus_cli.py dashboard              # opens http://127.0.0.1:7000
    python nexus_cli.py dashboard --port 8080  # custom port
    python nexus_cli.py dashboard --host 0.0.0.0 --port 7000  # all interfaces

Python API:
    from dashboard import DashboardServer, start_dashboard

    # Blocking (foreground)
    start_dashboard(host="127.0.0.1", port=7000)

    # Background thread
    srv = DashboardServer(port=7000)
    srv.start_background()
    print(f"Dashboard at {srv.url}")
    ...
    srv.stop()
"""

from .server import DashboardServer, start_dashboard

__all__ = ["DashboardServer", "start_dashboard"]
