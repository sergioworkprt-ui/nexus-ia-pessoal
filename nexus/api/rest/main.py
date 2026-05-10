"""NEXUS REST API — all endpoints."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional, Any
import psutil
from fastapi import FastAPI, HTTPException, Depends, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from nexus.api.websocket.ws import ws_endpoint, manager
from nexus.services.logger.logger import get_logger

log = get_logger("api")
app = FastAPI(title="NEXUS API", version="2.0.0", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_bearer = HTTPBearer(auto_error=False)
_nexus = None
_LOG_DIR = Path(os.getenv("LOG_DIR", "/var/log/nexus"))
_SETTINGS_PATH = Path("/data/nexus/settings.json")


def set_nexus(n: Any):
    global _nexus
    _nexus = n


def _auth(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    sec = _nexus.get("security") if _nexus else None
    api_key = os.getenv("NEXUS_API_KEY", "nexus-change-me")
    token = creds.credentials if creds else ""
    if token == api_key:
        return
    if sec and sec.verify_token(token):
        return
    raise HTTPException(401, "Unauthorized")


def _mod(name: str):
    if not _nexus:
        raise HTTPException(503, "NEXUS not ready")
    m = _nexus.get(name)
    if not m:
        raise HTTPException(503, f"Module '{name}' unavailable")
    return m


# ── Models ────────────────────────────────────────────────────────────────
class ChatReq(BaseModel):
    message: str
    mode: str = "normal"

class TaskReq(BaseModel):
    title: str
    type_: str = "manual"
    payload: dict = {}
    needs_approval: bool = False

class OrderReqXTB(BaseModel):
    symbol: str
    cmd: int = 0
    volume: float = 0.01
    sl: float = 0.0
    tp: float = 0.0
    price: float = 0.0

class OrderReqIBKR(BaseModel):
    symbol: str
    action: str = "BUY"
    quantity: float = 1.0

class VideoReq(BaseModel):
    url: str
    mode: str = "full"

class LearningReq(BaseModel):
    question: str

class EvolveReq(BaseModel):
    description: str
    target_file: Optional[str] = None

class TruthReq(BaseModel):
    claim: str

class PinReq(BaseModel):
    pin: str

class RealEnableReq(BaseModel):
    code: str


# ── Health / Status ────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/status", dependencies=[Depends(_auth)])
def status():
    if not _nexus:
        raise HTTPException(503, "NEXUS not ready")
    mods = {}
    for name in ["trading", "ml", "watchdog", "security", "tasks",
                 "xtb", "ibkr", "learning", "evolution", "truth_checker"]:
        m = _nexus.get(name)
        if m and hasattr(m, "status"):
            mods[name] = m.status()
        elif m:
            mods[name] = "running"
    return {
        "name": "NEXUS", "version": "2.0.0",
        "modules": mods, "context": _nexus.get_context(),
        "trading_mode": _nexus.get_context().get("trading_mode", "simulation"),
    }


# ── Chat ───────────────────────────────────────────────────────────────────
@app.post("/chat", dependencies=[Depends(_auth)])
async def chat(req: ChatReq):
    if not _nexus:
        raise HTTPException(503, "NEXUS not ready")
    _nexus.update_context("chat_mode", req.mode)
    return {"response": await _nexus.process(req.message), "mode": req.mode}


# ── Memory ────────────────────────────────────────────────────────────────
@app.get("/memory", dependencies=[Depends(_auth)])
def get_memory(n: int = 50):
    m = _mod("memory")
    return {"entries": m.get_recent(n)}


@app.delete("/memory", dependencies=[Depends(_auth)])
def clear_memory():
    m = _mod("memory")
    if hasattr(m, "clear"):
        m.clear()
    return {"status": "cleared"}


# ── Tasks ──────────────────────────────────────────────────────────────────
@app.get("/tasks", dependencies=[Depends(_auth)])
def list_tasks(status: Optional[str] = None, type_: Optional[str] = None):
    tm = _mod("tasks")
    return {"tasks": tm.list_tasks(status=status, type_=type_)}


@app.post("/tasks", dependencies=[Depends(_auth)])
def create_task(req: TaskReq):
    tm = _mod("tasks")
    return tm.create(req.title, req.type_, req.payload, req.needs_approval)


@app.post("/tasks/{tid}/approve", dependencies=[Depends(_auth)])
def approve_task(tid: str):
    tm = _mod("tasks")
    if not tm.approve(tid):
        raise HTTPException(404, "Task not found")
    return {"status": "approved"}


@app.delete("/tasks/{tid}", dependencies=[Depends(_auth)])
def delete_task(tid: str):
    tm = _mod("tasks")
    if not tm.delete(tid):
        raise HTTPException(404, "Task not found")
    return {"status": "deleted"}


# ── Learning ───────────────────────────────────────────────────────────────
@app.post("/learning/multi", dependencies=[Depends(_auth)])
async def learning_multi(req: LearningReq):
    lm = _mod("learning")
    return {"answers": await lm.multi_query(req.question)}


@app.post("/learning/synthesize", dependencies=[Depends(_auth)])
async def learning_synthesize(req: LearningReq):
    lm = _mod("learning")
    return await lm.synthesize(req.question)


@app.get("/learning/providers", dependencies=[Depends(_auth)])
def learning_providers():
    lm = _mod("learning")
    return {"providers": lm.available_providers()}


# ── Video Analysis ─────────────────────────────────────────────────────────
@app.post("/video/analyze", dependencies=[Depends(_auth)])
async def video_analyze(req: VideoReq):
    va = _mod("video_analysis")
    return await va.analyze(req.url, req.mode)


# ── Evolution ──────────────────────────────────────────────────────────────
@app.post("/evolution/propose", dependencies=[Depends(_auth)])
async def evolution_propose(req: EvolveReq):
    ev = _mod("evolution")
    return await ev.propose(req.description, req.target_file)


@app.get("/evolution", dependencies=[Depends(_auth)])
def evolution_list(status: Optional[str] = None):
    ev = _mod("evolution")
    return {"proposals": ev.list_proposals(status)}


@app.post("/evolution/{pid}/approve", dependencies=[Depends(_auth)])
def evolution_approve(pid: str):
    ev = _mod("evolution")
    if not ev.approve(pid):
        raise HTTPException(404, "Proposal not found")
    return {"status": "approved"}


@app.post("/evolution/{pid}/reject", dependencies=[Depends(_auth)])
def evolution_reject(pid: str):
    ev = _mod("evolution")
    if not ev.reject(pid):
        raise HTTPException(404, "Proposal not found")
    return {"status": "rejected"}


@app.post("/evolution/{pid}/apply", dependencies=[Depends(_auth)])
async def evolution_apply(pid: str):
    ev = _mod("evolution")
    return await ev.apply(pid)


# ── Truth Checker ──────────────────────────────────────────────────────────
@app.post("/truth/check", dependencies=[Depends(_auth)])
async def truth_check(req: TruthReq):
    tc = _mod("truth_checker")
    return await tc.check(req.claim)


# ── Trading — XTB ─────────────────────────────────────────────────────────
@app.get("/trading/xtb/status", dependencies=[Depends(_auth)])
def xtb_status():
    return _mod("xtb").status()


@app.get("/trading/xtb/positions", dependencies=[Depends(_auth)])
async def xtb_positions():
    xtb = _mod("xtb")
    return {"positions": await xtb.get_positions()}


@app.get("/trading/xtb/balance", dependencies=[Depends(_auth)])
async def xtb_balance():
    xtb = _mod("xtb")
    return await xtb.get_balance()


@app.post("/trading/xtb/order", dependencies=[Depends(_auth)])
async def xtb_order(req: OrderReqXTB):
    sec = _mod("security")
    if not sec.validate_financial(req.volume * 100):
        raise HTTPException(403, "Financial action not authorized")
    xtb = _mod("xtb")
    return await xtb.place_order(req.symbol, req.cmd, req.volume, req.sl, req.tp, req.price)


# ── Trading — IBKR ────────────────────────────────────────────────────────
@app.get("/trading/ibkr/status", dependencies=[Depends(_auth)])
def ibkr_status():
    return _mod("ibkr").status()


@app.get("/trading/ibkr/positions", dependencies=[Depends(_auth)])
async def ibkr_positions():
    ibkr = _mod("ibkr")
    return {"positions": await ibkr.get_positions()}


@app.get("/trading/ibkr/account", dependencies=[Depends(_auth)])
async def ibkr_account():
    ibkr = _mod("ibkr")
    return await ibkr.get_account_summary()


@app.post("/trading/ibkr/order", dependencies=[Depends(_auth)])
async def ibkr_order(req: OrderReqIBKR):
    sec = _mod("security")
    if not sec.validate_financial(req.quantity * 10):
        raise HTTPException(403, "Financial action not authorized")
    ibkr = _mod("ibkr")
    return await ibkr.place_order(req.symbol, req.action, req.quantity)


@app.post("/trade/real/enable", dependencies=[Depends(_auth)])
def enable_real(req: RealEnableReq):
    sec = _mod("security")
    ok = sec.authorize_financial(req.code)
    xtb = _nexus.get("xtb") if _nexus else None
    ibkr = _nexus.get("ibkr") if _nexus else None
    if xtb: xtb.enable_real(req.code)
    if ibkr: ibkr.enable_real(req.code)
    return {"authorized": ok, "warning": "Real money at risk" if ok else "Invalid code"}


# ── Security ───────────────────────────────────────────────────────────────
@app.post("/security/pin/verify")
def pin_verify(req: PinReq):
    sec = _mod("security")
    if not sec.check_rate("pin", limit=5, window=60):
        raise HTTPException(429, "Too many PIN attempts")
    if sec.verify_pin(req.pin):
        token = sec.generate_token()
        return {"ok": True, "token": token}
    return {"ok": False}


@app.get("/security/audit", dependencies=[Depends(_auth)])
def security_audit(lines: int = 50):
    sec = _mod("security")
    return {"lines": sec.get_audit_log(lines)}


@app.get("/security/status", dependencies=[Depends(_auth)])
def security_status():
    return _mod("security").status()


# ── Monitor ────────────────────────────────────────────────────────────────
@app.get("/monitor/metrics", dependencies=[Depends(_auth)])
def monitor_metrics():
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_mb": mem.used // 1024 // 1024,
            "memory_total_mb": mem.total // 1024 // 1024,
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free // 1024 // 1024 // 1024,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Logs ───────────────────────────────────────────────────────────────────
@app.get("/logs/{service}", dependencies=[Depends(_auth)])
def get_logs(service: str, lines: int = 100):
    allowed = {"api", "core", "dashboard", "audit"}
    if service not in allowed:
        raise HTTPException(400, "Unknown service")
    log_file = _LOG_DIR / ("audit.log" if service == "audit" else f"{service}.log")
    if not log_file.exists():
        return {"lines": []}
    all_lines = log_file.read_text(errors="replace").splitlines()
    return {"lines": all_lines[-lines:], "total": len(all_lines)}


# ── Settings ───────────────────────────────────────────────────────────────
@app.get("/settings", dependencies=[Depends(_auth)])
def get_settings():
    import json
    try:
        return json.loads(_SETTINGS_PATH.read_text()) if _SETTINGS_PATH.exists() else {}
    except Exception:
        return {}


@app.put("/settings", dependencies=[Depends(_auth)])
def update_settings(body: dict):
    import json
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        if _SETTINGS_PATH.exists():
            existing = json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        pass
    existing.update(body)
    _SETTINGS_PATH.write_text(json.dumps(existing, indent=2))
    return {"status": "saved", "settings": existing}


# ── Legacy trading (backwards compat) ─────────────────────────────────────
@app.get("/positions", dependencies=[Depends(_auth)])
async def legacy_positions():
    t = _nexus.get("trading") if _nexus else None
    if not t:
        raise HTTPException(503, "Trading unavailable")
    return {"orders": t.get_orders() if hasattr(t, 'get_orders') else []}


# ── WebSocket ─────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws_endpoint(ws, _nexus)
