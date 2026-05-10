import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import WebSocket
from pydantic import BaseModel
from nexus.api.websocket.ws import ws_endpoint, manager

app = FastAPI(title="NEXUS", version="1.0.0", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_security = HTTPBearer(auto_error=False)
_API_KEY = os.getenv("NEXUS_API_KEY", "nexus-change-me")
_nexus = None


def set_nexus(n):
    global _nexus
    _nexus = n


def _auth(creds: HTTPAuthorizationCredentials = Depends(_security)):
    if not creds or creds.credentials != _API_KEY:
        raise HTTPException(401, "Unauthorized")


class ChatReq(BaseModel):
    message: str


class OrderReq(BaseModel):
    symbol: str
    action: str
    amount: float
    sl: Optional[float] = None
    tp: Optional[float] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", dependencies=[Depends(_auth)])
async def chat(req: ChatReq):
    if not _nexus:
        raise HTTPException(503, "NEXUS not ready")
    return {"response": await _nexus.process(req.message)}


@app.get("/status", dependencies=[Depends(_auth)])
def status():
    if not _nexus:
        raise HTTPException(503, "NEXUS not ready")
    result = {}
    for name in ["trading", "ml", "watchdog", "security"]:
        m = _nexus.get(name)
        if m and hasattr(m, "status"):
            result[name] = m.status()
    return {"modules": result, "context": _nexus.get_context()}


@app.post("/trade", dependencies=[Depends(_auth)])
def trade(req: OrderReq):
    if not _nexus:
        raise HTTPException(503, "Not ready")
    t = _nexus.get("trading")
    if not t:
        raise HTTPException(503, "Trading unavailable")
    return t.place_order(req.symbol, req.action, req.amount, req.sl, req.tp)


@app.get("/positions", dependencies=[Depends(_auth)])
def positions():
    t = _nexus.get("trading") if _nexus else None
    if not t:
        raise HTTPException(503, "Trading unavailable")
    return {"orders": t.get_orders(), "exposure": t.status()["exposure_eur"]}


@app.post("/trade/real/enable", dependencies=[Depends(_auth)])
def enable_real(body: dict):
    t = _nexus.get("trading") if _nexus else None
    if not t:
        raise HTTPException(503, "Trading unavailable")
    return {"enabled": t.enable_real(body.get("code", ""))}


@app.get("/memory", dependencies=[Depends(_auth)])
def memory(n: int = 20):
    m = _nexus.get("memory") if _nexus else None
    if not m:
        raise HTTPException(503, "Memory unavailable")
    return {"entries": m.get_recent(n)}


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws_endpoint(ws, _nexus)
