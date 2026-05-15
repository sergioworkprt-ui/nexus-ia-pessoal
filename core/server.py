"""
NEXUS Core — HTTP service entrypoint.

Exposes NexusCore as a FastAPI microservice.
Run with: uvicorn core.server:app --host 0.0.0.0 --port 8001
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .core_init import NexusCore, NexusCoreConfig
from .cognitive_engine import ReasoningStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nexus-core-service")

_core: Optional[NexusCore] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _core
    cfg = NexusCoreConfig(
        log_dir=os.environ.get("LOG_DIR", "/opt/nexus/logs"),
        data_dir=os.environ.get("DATA_DIR", "/opt/nexus/data"),
        heartbeat_interval=float(os.environ.get("HEARTBEAT_INTERVAL", "30")),
        task_workers=int(os.environ.get("TASK_WORKERS", "4")),
    )
    _core = NexusCore(cfg)
    _core.start()
    log.info("NexusCore iniciado")
    yield
    _core.stop()
    log.info("NexusCore parado")


app = FastAPI(
    title="NEXUS Core Service",
    description="Motor central do NEXUS — memória, tarefas, cognitivo, segurança",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    command: str
    actor: str = "api"


class ThinkRequest(BaseModel):
    content: str
    strategy: str = "direct"
    context: Dict[str, Any] = {}


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_core() -> NexusCore:
    if _core is None or not _core._ready:
        raise HTTPException(status_code=503, detail="NexusCore não está pronto")
    return _core


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    if _core is None:
        return JSONResponse({"status": "a iniciar"}, status_code=503)
    return {"status": "ok", "ready": _core._ready, "service": "nexus-core"}


@app.get("/api/status")
def status() -> Dict[str, Any]:
    core = _require_core()
    return core.status()


@app.post("/api/execute")
async def execute(req: ExecuteRequest) -> Dict[str, Any]:
    core = _require_core()
    result = core.execute(req.command, actor=req.actor)
    return {
        "success": result.success,
        "command": result.command,
        "output": getattr(result, "output", None),
        "error": result.error,
    }


@app.post("/api/think")
async def think(req: ThinkRequest) -> Dict[str, Any]:
    core = _require_core()
    try:
        strat = ReasoningStrategy(req.strategy)
    except ValueError:
        strat = ReasoningStrategy.DIRECT
    return core.think(req.content, strategy=strat, context=req.context)


@app.get("/api/memory/stats")
def memory_stats() -> Dict[str, Any]:
    core = _require_core()
    return core.memory.stats()


@app.get("/api/tasks/stats")
def task_stats() -> Dict[str, Any]:
    core = _require_core()
    return core.tasks.stats()


@app.get("/api/cognitive/history")
def cognitive_history(limit: int = 20) -> Any:
    core = _require_core()
    return core.cognitive.history(limit=limit)


@app.get("/api/heartbeat")
def heartbeat() -> Dict[str, Any]:
    core = _require_core()
    snap = core.heartbeat.beat()
    return {
        "status": snap.status,
        "uptime_seconds": snap.uptime_seconds,
        "checks": snap.checks,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "core.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8001")),
        log_level="info",
    )
