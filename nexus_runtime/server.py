"""
NEXUS Runtime — HTTP service entrypoint.

Exposes NexusRuntime como serviço FastAPI.
Run with: uvicorn nexus_runtime.server:app --host 0.0.0.0 --port 8006
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nexus-runtime")

_runtime: Optional[Any] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runtime
    try:
        from .runtime import NexusRuntime
        from .runtime_config import RuntimeConfig
        cfg = RuntimeConfig(
            data_dir=os.environ.get("DATA_DIR", "/opt/nexus/data"),
            log_dir=os.environ.get("LOG_DIR", "/opt/nexus/logs"),
        )
        _runtime = NexusRuntime(cfg)
        _runtime.start()
        log.info("NexusRuntime iniciado")
    except Exception as exc:
        log.error("Falha ao iniciar NexusRuntime: %s", exc)
    yield
    if _runtime is not None:
        try:
            _runtime.stop()
        except Exception as exc:
            log.warning("Erro ao parar NexusRuntime: %s", exc)
    log.info("NexusRuntime parado")


app = FastAPI(
    title="NEXUS Runtime",
    description="Motor de execução de pipelines e eventos do NEXUS",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    pipeline_id: str
    payload: Dict[str, Any] = {}


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_runtime():
    if _runtime is None:
        raise HTTPException(status_code=503, detail="NexusRuntime não está pronto")
    return _runtime


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    if _runtime is None:
        return JSONResponse({"status": "a iniciar"}, status_code=503)
    return {"status": "ok", "service": "nexus-runtime"}


@app.get("/api/status")
def status() -> Dict[str, Any]:
    rt = _require_runtime()
    if hasattr(rt, 'status'):
        return rt.status()
    return {"running": True, "service": "nexus-runtime"}


@app.post("/api/pipeline/run")
async def run_pipeline(req: PipelineRequest) -> Dict[str, Any]:
    rt = _require_runtime()
    try:
        if hasattr(rt, 'run_pipeline'):
            result = rt.run_pipeline(req.pipeline_id, **req.payload)
        else:
            result = {"pipeline_id": req.pipeline_id, "note": "método run_pipeline não disponível"}
        return {"ok": True, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    rt = _require_runtime()
    if hasattr(rt, 'state_manager'):
        sm = rt.state_manager
        return {"state": vars(sm) if hasattr(sm, '__dict__') else str(sm)}
    return {"state": {}}


@app.get("/api/scheduler")
def scheduler_status() -> Dict[str, Any]:
    rt = _require_runtime()
    if hasattr(rt, 'scheduler'):
        sched = rt.scheduler
        return {
            "running": getattr(sched, '_running', False),
            "jobs": len(getattr(sched, '_jobs', [])),
        }
    return {"running": False, "jobs": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "nexus_runtime.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8006")),
        log_level="info",
    )
