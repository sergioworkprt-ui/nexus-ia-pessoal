"""NEXUS Dashboard backend — thin FastAPI layer for metrics and logs."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="NEXUS Dashboard API")

NEXUS_API = os.getenv("NEXUS_API_URL", "http://localhost:8000")
LOG_DIR = Path(os.getenv("NEXUS_LOG_DIR", "/var/log/nexus"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
async def status() -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{NEXUS_API}/status")
            return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        return JSONResponse({"error": "nexus_unavailable"}, status_code=503)


@app.get("/api/positions")
async def positions() -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{NEXUS_API}/positions")
            return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        return JSONResponse({"error": "nexus_unavailable"}, status_code=503)


@app.get("/api/logs/{service}")
async def logs(service: str, lines: int = 100) -> JSONResponse:
    allowed = {"api", "core"}
    if service not in allowed:
        return JSONResponse({"error": "unknown_service"}, status_code=400)
    log_file = LOG_DIR / f"{service}.log"
    if not log_file.exists():
        return JSONResponse({"lines": []})
    all_lines = log_file.read_text(errors="replace").splitlines()
    return JSONResponse({"lines": all_lines[-lines:]})


@app.websocket("/ws/logs/{service}")
async def ws_logs(websocket: WebSocket, service: str) -> None:
    allowed = {"api", "core"}
    if service not in allowed:
        await websocket.close(code=4004)
        return
    await websocket.accept()
    log_file = LOG_DIR / f"{service}.log"
    try:
        while True:
            if log_file.exists():
                lines = log_file.read_text(errors="replace").splitlines()
                await websocket.send_json({"lines": lines[-50:]})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
