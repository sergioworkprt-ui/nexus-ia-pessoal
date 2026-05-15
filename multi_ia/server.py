"""
NEXUS Multi-IA — HTTP service entrypoint.

Exposes MultiIA como serviço FastAPI.
Run with: uvicorn multi_ia.server:app --host 0.0.0.0 --port 8005
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .multi_ia import MultiIA, MultiIAConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nexus-multi-ia")

_ia: Optional[MultiIA] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ia
    cfg = MultiIAConfig(
        max_agents=int(os.environ.get("MAX_AGENTS", "5")),
    )
    _ia = MultiIA(cfg)
    _ia.start()
    log.info("MultiIA iniciada")
    yield
    _ia.stop()
    log.info("MultiIA parada")


app = FastAPI(
    title="NEXUS Multi-IA",
    description="Orquestração de múltiplos agentes IA com consenso e routing",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    n_agents: int = 1


class VoteRequest(BaseModel):
    question: str


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_ia() -> MultiIA:
    if _ia is None:
        raise HTTPException(status_code=503, detail="MultiIA não está pronto")
    return _ia


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    if _ia is None:
        return JSONResponse({"status": "a iniciar"}, status_code=503)
    return {"status": "ok", "service": "nexus-multi-ia"}


@app.get("/api/status")
def status() -> Dict[str, Any]:
    ia = _require_ia()
    return ia.status()


@app.post("/api/ask")
async def ask(req: AskRequest) -> Dict[str, Any]:
    ia = _require_ia()
    try:
        if req.n_agents > 1:
            result = ia.ask_all(req.question, n_agents=req.n_agents)
            consensus = getattr(result, 'consensus_result', None)
            return {
                "question": req.question,
                "n_agents": req.n_agents,
                "agreement_score": getattr(consensus, 'agreement_score', None) if consensus else None,
                "final_answer": getattr(consensus, 'final_content', None) if consensus else None,
            }
        else:
            response = ia.ask(req.question)
            return {
                "question": req.question,
                "n_agents": 1,
                "answer": getattr(response, 'content', str(response)),
                "agent": getattr(response, 'agent_id', None),
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/vote")
async def vote(req: VoteRequest) -> Dict[str, Any]:
    ia = _require_ia()
    try:
        result = ia.vote(req.question)
        return {
            "question": req.question,
            "final_answer": getattr(result, 'final_content', str(result)),
            "agreement_score": getattr(result, 'agreement_score', None),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/agents")
def list_agents() -> Dict[str, Any]:
    ia = _require_ia()
    registry = getattr(ia, 'registry', None)
    agents = registry.list_agents() if registry and hasattr(registry, 'list_agents') else []
    return {"agents": [str(a) for a in agents], "count": len(agents)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "multi_ia.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8005")),
        log_level="info",
    )
