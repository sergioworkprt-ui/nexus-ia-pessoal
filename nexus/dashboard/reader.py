"""Read logs and status data for the NEXUS dashboard."""
from __future__ import annotations

import os
from pathlib import Path

import httpx

NEXUS_API = os.getenv("NEXUS_API_URL", "http://localhost:8000")
LOG_DIR = Path(os.getenv("NEXUS_LOG_DIR", "/var/log/nexus"))
_TIMEOUT = 5.0


def get_log_lines(service: str, n: int = 100) -> list[str]:
    """Return the last n lines of a service log file."""
    allowed = {"api", "core"}
    if service not in allowed:
        return []
    log_file = LOG_DIR / f"{service}.log"
    if not log_file.exists():
        return []
    return log_file.read_text(errors="replace").splitlines()[-n:]


async def get_status() -> dict:
    """Fetch NEXUS system status from the API."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{NEXUS_API}/status")
            return r.json()
    except httpx.ConnectError:
        return {"error": "nexus_unavailable"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def get_positions() -> dict:
    """Fetch open trading positions from the API."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{NEXUS_API}/positions")
            return r.json()
    except httpx.ConnectError:
        return {"positions": [], "error": "nexus_unavailable"}
    except Exception as exc:  # noqa: BLE001
        return {"positions": [], "error": str(exc)}
