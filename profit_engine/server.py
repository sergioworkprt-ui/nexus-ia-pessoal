"""
NEXUS Profit Engine — HTTP service entrypoint.

Exposes ProfitEngine as a FastAPI microservice.
Run with: uvicorn profit_engine.server:app --host 0.0.0.0 --port 8002
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .profit_engine import ProfitEngine, ProfitEngineConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nexus-profit-engine")

_engine: Optional[ProfitEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    cfg = ProfitEngineConfig(
        initial_capital=float(os.environ.get("INITIAL_CAPITAL", "10000")),
    )
    _engine = ProfitEngine(cfg)
    _engine.start()
    log.info("ProfitEngine iniciado")
    yield
    _engine.stop()
    log.info("ProfitEngine parado")


app = FastAPI(
    title="NEXUS Profit Engine",
    description="Motor de estratégia, risco e portfolio do NEXUS",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────

class SignalRequest(BaseModel):
    symbol: str
    prices: List[float]
    volumes: Optional[List[float]] = None


class OrderRequest(BaseModel):
    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: float
    price: Optional[float] = None


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_engine() -> ProfitEngine:
    if _engine is None:
        raise HTTPException(status_code=503, detail="ProfitEngine não está pronto")
    return _engine


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    if _engine is None:
        return JSONResponse({"status": "a iniciar"}, status_code=503)
    return {"status": "ok", "service": "nexus-profit-engine"}


@app.get("/api/status")
def status() -> Dict[str, Any]:
    engine = _require_engine()
    return engine.status()


@app.get("/api/portfolio")
def portfolio() -> Dict[str, Any]:
    engine = _require_engine()
    pm = engine.portfolio
    return {
        "positions": {k: vars(v) if hasattr(v, '__dict__') else str(v)
                      for k, v in pm.positions.items()},
        "cash": getattr(pm, 'cash', None),
        "equity": getattr(pm, 'equity', None),
    }


@app.get("/api/risk")
def risk_summary() -> Dict[str, Any]:
    engine = _require_engine()
    rm = engine.risk
    return {
        "limits": vars(rm.limits) if hasattr(rm, 'limits') and hasattr(rm.limits, '__dict__') else {},
        "violations_count": len(getattr(rm, '_violations', [])),
    }


@app.get("/api/rules")
def trading_rules() -> Dict[str, Any]:
    engine = _require_engine()
    rules = engine.rules
    return {
        "kill_switch": getattr(rules, '_kill_switch_active', False),
        "circuit_breakers": len(getattr(rules, '_circuit_breakers', [])),
    }


@app.post("/api/backtest")
async def backtest(body: Dict[str, Any]) -> Dict[str, Any]:
    engine = _require_engine()
    from .backtester import BacktestConfig, SyntheticDataFeed
    from .strategy_engine import MovingAverageCrossover
    symbols = body.get("symbols", ["SYM"])
    n_bars = int(body.get("n_bars", 252))
    strat = MovingAverageCrossover(symbols=symbols)
    feed = SyntheticDataFeed(symbols=symbols, n_bars=n_bars)
    try:
        result = engine.backtest(strat, feed)
        return result.summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "profit_engine.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8002")),
        log_level="info",
    )
