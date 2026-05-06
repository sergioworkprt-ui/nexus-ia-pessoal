"""
NEXUS — FastAPI Server

Exposes the NEXUS command engine over HTTP so any external process,
chat interface, or webhook can send commands and receive responses.

Endpoints:
    POST /nexus   {"command": "gateway login"}  → {"ok": bool, "message": str, "data": {...}}
    GET  /health  → {"status": "ok", "runtime": "simulation"|"live", "uptime_s": float}

Usage:
    python server.py              # simulation mode, port 8000
    python server.py --live       # live mode
    python server.py --port 9000  # custom port
"""

from __future__ import annotations

import argparse
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Runtime bootstrap (reuses main.py globals)
# ---------------------------------------------------------------------------

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import main as _nexus   # boots and owns the runtime + engine singletons

_START_TIME = time.time()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NEXUS Command API",
    description="Natural-language command interface for the NEXUS trading runtime.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CommandRequest(BaseModel):
    command: str

class CommandResponse(BaseModel):
    ok:      bool
    command: str
    message: str
    data:    Dict[str, Any] = {}
    warnings: list[str]    = []


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup():
    """Boot the NEXUS runtime before the first request arrives."""
    live = getattr(app.state, "live_mode", False)
    _nexus._boot(live=live)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health():
    """Liveness check — always returns 200 while the process is running."""
    uptime = round(time.time() - _START_TIME, 1)
    runtime_mode = "unknown"
    if _nexus._runtime is not None:
        runtime_mode = _nexus._runtime._config.mode.value
    return {
        "status":       "ok",
        "runtime":      runtime_mode,
        "uptime_s":     uptime,
        "engine_ready": _nexus._engine is not None,
    }


@app.post("/nexus", response_model=CommandResponse, tags=["commands"])
def nexus_command(req: CommandRequest):
    """
    Execute a NEXUS command and return a structured response.

    Examples:
        {"command": "gateway status"}
        {"command": "gateway login"}
        {"command": "gateway accounts"}
        {"command": "gateway positions"}
        {"command": "gateway pnl"}
        {"command": "gateway snapshot 265598"}
        {"command": "ibkr status"}
        {"command": "ibkr positions"}
        {"command": "ibkr balance"}
        {"command": "show status"}
        {"command": "signal BTC"}
    """
    text = req.command.strip()
    if not text:
        raise HTTPException(status_code=400, detail="command must not be empty")

    if _nexus._engine is None:
        raise HTTPException(status_code=503, detail="NEXUS engine not ready")

    resp = _nexus._engine.execute(text)
    return CommandResponse(
        ok      = resp.ok,
        command = resp.command,
        message = resp.message,
        data    = resp.data,
        warnings= resp.warnings,
    )


@app.get("/nexus/help", tags=["commands"])
def nexus_help(query: Optional[str] = None):
    """Return available commands and their descriptions."""
    if _nexus._engine is None:
        raise HTTPException(status_code=503, detail="NEXUS engine not ready")
    return {"help": _nexus._engine.help(query or "")}


@app.get("/nexus/history", tags=["commands"])
def nexus_history(limit: int = 20):
    """Return the last N commands executed in this session."""
    if _nexus._engine is None:
        raise HTTPException(status_code=503, detail="NEXUS engine not ready")
    return {"history": _nexus._engine.history(limit=limit)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="NEXUS FastAPI Server")
    parser.add_argument("--live",  action="store_true", help="Live mode (default: simulation)")
    parser.add_argument("--port",  type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--host",  default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    args = parser.parse_args()

    app.state.live_mode = args.live

    print(f"[NEXUS] Starting FastAPI server on {args.host}:{args.port} "
          f"({'LIVE' if args.live else 'SIMULATION'} mode)")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
