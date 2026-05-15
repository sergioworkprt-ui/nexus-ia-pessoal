"""
NEXUS Web Intelligence — HTTP service entrypoint.

Exposes WebIntelligence as a FastAPI microservice.
Run with: uvicorn web_intelligence.server:app --host 0.0.0.0 --port 8003
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .web_intelligence import WebIntelligence, WebIntelligenceConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nexus-web-intelligence")

_wi: Optional[WebIntelligence] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _wi
    cfg = WebIntelligenceConfig(
        fetch_timeout=float(os.environ.get("FETCH_TIMEOUT", "15")),
    )
    _wi = WebIntelligence(cfg)
    _wi.start()
    log.info("WebIntelligence iniciada")
    yield
    _wi.stop()
    log.info("WebIntelligence parada")


app = FastAPI(
    title="NEXUS Web Intelligence",
    description="Web scraping, análise de notícias e dados de mercado",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────

class NewsAnalysisRequest(BaseModel):
    title: str
    body: Optional[str] = None
    source: Optional[str] = None


class FetchRequest(BaseModel):
    url: str
    timeout: Optional[float] = None


class PatternRequest(BaseModel):
    symbol: str
    bars: List[Dict[str, Any]]


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_wi() -> WebIntelligence:
    if _wi is None:
        raise HTTPException(status_code=503, detail="WebIntelligence não está pronto")
    return _wi


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    if _wi is None:
        return JSONResponse({"status": "a iniciar"}, status_code=503)
    return {"status": "ok", "service": "nexus-web-intelligence"}


@app.get("/api/status")
def status() -> Dict[str, Any]:
    wi = _require_wi()
    return wi.status()


@app.post("/api/news/analyze")
async def analyze_news(req: NewsAnalysisRequest) -> Dict[str, Any]:
    wi = _require_wi()
    from .news_analyzer import NewsItem
    item = NewsItem(title=req.title, body=req.body or "", source=req.source or "")
    try:
        result = wi.analyze_news_item(item)
        return {
            "sentiment": result.sentiment.value if hasattr(result.sentiment, 'value') else str(result.sentiment),
            "score": result.score,
            "summary": getattr(result, 'summary', None),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/fetch")
async def fetch_url(req: FetchRequest) -> Dict[str, Any]:
    wi = _require_wi()
    try:
        result = wi.fetch(req.url)
        return {
            "url": req.url,
            "status_code": result.status_code,
            "content_length": len(result.content) if result.content else 0,
            "ok": result.ok,
            "error": result.error,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/patterns")
async def detect_patterns(req: PatternRequest) -> Dict[str, Any]:
    wi = _require_wi()
    from .market_data import OHLCBar
    bars = []
    for b in req.bars:
        try:
            bars.append(OHLCBar(**b))
        except Exception:
            pass
    if not bars:
        raise HTTPException(status_code=400, detail="Nenhum bar válido fornecido")
    try:
        signals = wi.detect_patterns(req.symbol, bars=bars)
        return {
            "symbol": req.symbol,
            "patterns": [
                {"type": s.pattern_type.value if hasattr(s.pattern_type, 'value') else str(s.pattern_type),
                 "confidence": s.confidence,
                 "direction": getattr(s, 'direction', None)}
                for s in signals
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web_intelligence.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8003")),
        log_level="info",
    )
