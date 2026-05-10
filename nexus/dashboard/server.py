"""NEXUS Dashboard — unified entry point.

Run via systemd:
    /opt/nexus/venv/bin/python -m nexus.dashboard.server

Or directly (with PYTHONPATH set):
    PYTHONPATH=/opt/nexus python nexus/dashboard/server.py
"""
from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# All imports are absolute — no relative imports
from nexus.dashboard.reader import get_log_lines, get_positions, get_status
from nexus.dashboard.pages import router as pages_router

app = FastAPI(title="NEXUS Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount server-side rendered pages
app.include_router(pages_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "nexus-dashboard"}


@app.get("/api/status")
async def api_status() -> JSONResponse:
    data = await get_status()
    code = 503 if "error" in data else 200
    return JSONResponse(data, status_code=code)


@app.get("/api/positions")
async def api_positions() -> JSONResponse:
    data = await get_positions()
    return JSONResponse(data)


@app.get("/api/logs/{service}")
async def api_logs(service: str, lines: int = 100) -> JSONResponse:
    allowed = {"api", "core"}
    if service not in allowed:
        return JSONResponse({"error": "unknown_service"}, status_code=400)
    return JSONResponse({"lines": get_log_lines(service, lines)})


@app.websocket("/ws/logs/{service}")
async def ws_logs(websocket: WebSocket, service: str) -> None:
    import asyncio
    allowed = {"api", "core"}
    if service not in allowed:
        await websocket.close(code=4004)
        return
    await websocket.accept()
    try:
        while True:
            lines = get_log_lines(service, 50)
            await websocket.send_json({"lines": lines})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "9000"))
    uvicorn.run(
        "nexus.dashboard.server:app",
        host=host,
        port=port,
        reload=False,
    )
