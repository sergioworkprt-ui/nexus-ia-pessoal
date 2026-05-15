"""
NEXUS Auto-Evolution — HTTP service entrypoint.

Exposes AutoEvolution como serviço FastAPI.
Run with: uvicorn auto_evolution.server:app --host 0.0.0.0 --port 8004
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auto_evolution import AutoEvolution, AutoEvolutionConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nexus-auto-evolution")

_ae: Optional[AutoEvolution] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ae
    cfg = AutoEvolutionConfig(
        workspace=os.environ.get("WORKSPACE", "/opt/nexus"),
    )
    _ae = AutoEvolution(cfg)
    _ae.start()
    log.info("AutoEvolution iniciada")
    yield
    _ae.stop()
    log.info("AutoEvolution parada")


app = FastAPI(
    title="NEXUS Auto-Evolution",
    description="Análise autónoma de código, auto-reparação e testes A/B",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────

class CycleRequest(BaseModel):
    files: List[str]


class SuggestRequest(BaseModel):
    file_path: str


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_ae() -> AutoEvolution:
    if _ae is None:
        raise HTTPException(status_code=503, detail="AutoEvolution não está pronto")
    return _ae


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    if _ae is None:
        return JSONResponse({"status": "a iniciar"}, status_code=503)
    return {"status": "ok", "service": "nexus-auto-evolution"}


@app.get("/api/status")
def status() -> Dict[str, Any]:
    ae = _require_ae()
    return ae.status()


@app.post("/api/cycle")
async def run_cycle(req: CycleRequest) -> Dict[str, Any]:
    ae = _require_ae()
    try:
        report = ae.run_cycle(req.files)
        return {
            "files_analysed": getattr(report, 'files_analysed', len(req.files)),
            "issues_found": len(getattr(report, 'issues', [])),
            "patches_generated": len(getattr(report, 'patches', [])),
            "summary": getattr(report, 'summary', None),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/suggest")
async def suggest(req: SuggestRequest) -> Dict[str, Any]:
    ae = _require_ae()
    try:
        suggestions = ae.suggest(req.file_path)
        return {
            "file": req.file_path,
            "suggestions": [
                {"type": getattr(s, 'type', None),
                 "description": getattr(s, 'description', str(s)),
                 "priority": getattr(s, 'priority', None)}
                for s in (suggestions or [])
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/pending-patches")
def pending_patches() -> Dict[str, Any]:
    ae = _require_ae()
    patches = getattr(ae, 'pending_patches', lambda: [])() \
        if callable(getattr(ae, 'pending_patches', None)) \
        else getattr(ae, '_pending_patches', [])
    return {"count": len(patches), "patches": [str(p) for p in patches]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "auto_evolution.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8004")),
        log_level="info",
    )
