"""FastAPI route handlers for the NEXUS server-side dashboard."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from nexus.dashboard.reader import get_log_lines, get_positions, get_status
from nexus.dashboard.html_builder import logs_card, page, positions_card, status_card

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Main dashboard page."""
    status = await get_status()
    pos_data = await get_positions()
    api_logs = get_log_lines("api", 30)
    core_logs = get_log_lines("core", 30)

    body = (
        status_card(status)
        + positions_card(pos_data)
        + logs_card(api_logs, "nexus-api")
        + logs_card(core_logs, "nexus-core")
    )
    return page("NEXUS Dashboard", body)


@router.get("/status", response_class=HTMLResponse)
async def status_page() -> str:
    """Status-only page."""
    status = await get_status()
    return page("NEXUS — Estado", status_card(status), refresh=5)


@router.get("/positions", response_class=HTMLResponse)
async def positions_page() -> str:
    """Positions-only page."""
    pos_data = await get_positions()
    return page("NEXUS — Posições", positions_card(pos_data), refresh=5)


@router.get("/logs/{service}", response_class=HTMLResponse)
async def logs_page(service: str) -> str:
    """Log viewer page."""
    lines = get_log_lines(service, 100)
    return page(f"NEXUS — Logs ({service})", logs_card(lines, service), refresh=5)
