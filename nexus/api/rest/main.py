"""NEXUS REST API — all endpoints."""
from __future__ import annotations
import json as _json
import os
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Any
import psutil
from fastapi import FastAPI, HTTPException, Depends, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from nexus.api.websocket.ws import ws_endpoint, manager
from nexus.services.logger.logger import get_logger

log = get_logger("api")

# ── Internal vars ─────────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)
_nexus = None
_LOG_DIR = Path(os.getenv("LOG_DIR", "/var/log/nexus"))
_SETTINGS_PATH = Path("/data/nexus/settings.json")
_NEXUS_HOME = Path(os.getenv("NEXUS_HOME", "/opt/nexus"))
_MONITOR_DIR = _NEXUS_HOME / "monitor"
_AUTOHEAL_STATE = _NEXUS_HOME / "autoheal_state.json"

_MODS = [
    ("memory",         "nexus.core.memory.memory",                   "Memory"),
    ("personality",    "nexus.core.personality.personality",          "Personality"),
    ("security",       "nexus.core.security.security",                "SecurityManager"),
    ("tts",            "nexus.core.voice.tts",                        "TTS"),
    ("ml",             "nexus.modules.ml.ml",                         "MLModule"),
    ("watchdog",       "nexus.modules.watchdog.watchdog",             "Watchdog"),
    ("tasks",          "nexus.modules.tasks.tasks",                   "TaskManager"),
    ("learning",       "nexus.modules.learning.learning",             "LearningModule"),
    ("video_analysis", "nexus.modules.video_analysis.video_analysis", "VideoAnalysis"),
    ("evolution",      "nexus.modules.evolution.evolution",           "Evolution"),
    ("truth_checker",  "nexus.modules.truth_checker.truth_checker",   "TruthChecker"),
    ("xtb",            "nexus.modules.trading.xtb.xtb_client",        "XTBClient"),
    ("ibkr",           "nexus.modules.trading.ibkr.ibkr_client",      "IBKRClient"),
    ("scheduler",      "nexus.services.scheduler.scheduler",          "Scheduler"),
]


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


# ── Lifespan: inicializa o Orchestrator no startup do uvicorn ─────────────────
@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Inicializa Orchestrator NEXUS quando uvicorn arranca o app."""
    global _nexus
    try:
        from nexus.core.orchestrator.orchestrator import Orchestrator  # type: ignore
        instance = Orchestrator()
        loaded: list[str] = []

        for name, mod_path, class_name in _MODS:
            try:
                cls = getattr(__import__(mod_path, fromlist=[class_name]), class_name)
                instance.register(name, cls())
                loaded.append(name)
            except Exception as exc:
                log.warning("[startup] módulo '%s' indisponível: %s", name, exc)

        # trading precisa do módulo security já carregado
        sec = instance.get("security")
        if sec:
            try:
                from nexus.modules.trading.trading import TradingModule  # type: ignore
                instance.register("trading", TradingModule(sec))
                loaded.append("trading")
            except Exception as exc:
                log.warning("[startup] módulo 'trading' indisponível: %s", exc)

        # stt precisa do nexus.process como callback de wake word
        try:
            from nexus.core.voice.stt import STT  # type: ignore
            instance.register("stt", STT(on_wake=instance.process))
            loaded.append("stt")
        except Exception as exc:
            log.warning("[startup] módulo 'stt' indisponível: %s", exc)

        await instance.start()
        set_nexus(instance)
        log.info("[startup] Orchestrator iniciado — módulos activos: %s", loaded)
    except Exception as exc:
        log.error(
            "[startup] Orchestrator falhou (%s) — a continuar sem orquestrador", exc
        )
    yield
    if _nexus:
        try:
            await _nexus.stop()
        except Exception:
            pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="NEXUS API", version="2.0.0", docs_url="/docs", lifespan=_lifespan)

# CORS: permite qualquer origem — não usar allow_credentials=True com allow_origins=["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

# ── HTTP middleware: Prometheus counters + structured log ─────────────────────
try:
    from nexus.api.rest import prometheus_metrics as _prom
    from nexus.services.logger.structured import http_logging_middleware

    @app.middleware("http")
    async def _http_mw(request: Request, call_next):
        return await http_logging_middleware(request, call_next, record_fn=_prom.record_request)
except Exception as _e:
    log.warning("Metrics/logging middleware unavailable: %s", _e)

# ── Extra routers ──────────────────────────────────────────────────────────────
try:
    from nexus.api.rest.automation import router as _automation_router
    app.include_router(_automation_router)
except Exception as _e:
    log.warning("Automation API unavailable: %s", _e)

try:
    from nexus.api.rest.prometheus_metrics import router as _prom_router
    app.include_router(_prom_router)
except Exception as _e:
    log.warning("Prometheus router unavailable: %s", _e)


# ── Models ────────────────────────────────────────────────────────────────────
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


# ── Health / Status ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0", "nexus_ready": _nexus is not None}


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


# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatReq):
    if not _nexus:
        return {
            "response": (
                f"Olá! Recebi a tua mensagem: \"{req.message}\" — "
                "mas o orquestrador NEXUS não está activo neste momento. "
                "O chat completo requer o nexus-core em execução. "
                "Verifica: systemctl status nexus-core"
            ),
            "mode": req.mode, "nexus_ready": False,
        }
    _nexus.update_context("chat_mode", req.mode)
    return {"response": await _nexus.process(req.message), "mode": req.mode, "nexus_ready": True}


# ── Memory ────────────────────────────────────────────────────────────────────
@app.get("/memory", dependencies=[Depends(_auth)])
def get_memory(n: int = 50):
    return {"entries": _mod("memory").get_recent(n)}


@app.delete("/memory", dependencies=[Depends(_auth)])
def clear_memory():
    m = _mod("memory")
    if hasattr(m, "clear"):
        m.clear()
    return {"status": "cleared"}


# ── Tasks ─────────────────────────────────────────────────────────────────────
@app.get("/tasks", dependencies=[Depends(_auth)])
def list_tasks(status: Optional[str] = None, type_: Optional[str] = None):
    return {"tasks": _mod("tasks").list_tasks(status=status, type_=type_)}

@app.post("/tasks", dependencies=[Depends(_auth)])
def create_task(req: TaskReq):
    return _mod("tasks").create(req.title, req.type_, req.payload, req.needs_approval)

@app.post("/tasks/{tid}/approve", dependencies=[Depends(_auth)])
def approve_task(tid: str):
    if not _mod("tasks").approve(tid):
        raise HTTPException(404, "Task not found")
    return {"status": "approved"}

@app.delete("/tasks/{tid}", dependencies=[Depends(_auth)])
def delete_task(tid: str):
    if not _mod("tasks").delete(tid):
        raise HTTPException(404, "Task not found")
    return {"status": "deleted"}


# ── Learning ──────────────────────────────────────────────────────────────────
@app.post("/learning/multi", dependencies=[Depends(_auth)])
async def learning_multi(req: LearningReq):
    return {"answers": await _mod("learning").multi_query(req.question)}

@app.post("/learning/synthesize", dependencies=[Depends(_auth)])
async def learning_synthesize(req: LearningReq):
    return await _mod("learning").synthesize(req.question)

@app.get("/learning/providers", dependencies=[Depends(_auth)])
def learning_providers():
    return {"providers": _mod("learning").available_providers()}


# ── Video Analysis ────────────────────────────────────────────────────────────
@app.post("/video/analyze", dependencies=[Depends(_auth)])
async def video_analyze(req: VideoReq):
    return await _mod("video_analysis").analyze(req.url, req.mode)


# ── Evolution ─────────────────────────────────────────────────────────────────
@app.post("/evolution/propose", dependencies=[Depends(_auth)])
async def evolution_propose(req: EvolveReq):
    return await _mod("evolution").propose(req.description, req.target_file)

@app.get("/evolution", dependencies=[Depends(_auth)])
def evolution_list(status: Optional[str] = None):
    return {"proposals": _mod("evolution").list_proposals(status)}

@app.post("/evolution/{pid}/approve", dependencies=[Depends(_auth)])
def evolution_approve(pid: str):
    if not _mod("evolution").approve(pid):
        raise HTTPException(404, "Proposal not found")
    return {"status": "approved"}

@app.post("/evolution/{pid}/reject", dependencies=[Depends(_auth)])
def evolution_reject(pid: str):
    if not _mod("evolution").reject(pid):
        raise HTTPException(404, "Proposal not found")
    return {"status": "rejected"}

@app.post("/evolution/{pid}/apply", dependencies=[Depends(_auth)])
async def evolution_apply(pid: str):
    return await _mod("evolution").apply(pid)


# ── Truth Checker ─────────────────────────────────────────────────────────────
@app.post("/truth/check", dependencies=[Depends(_auth)])
async def truth_check(req: TruthReq):
    return await _mod("truth_checker").check(req.claim)


# ── Trading — XTB ─────────────────────────────────────────────────────────────
@app.get("/trading/xtb/status", dependencies=[Depends(_auth)])
def xtb_status(): return _mod("xtb").status()

@app.get("/trading/xtb/positions", dependencies=[Depends(_auth)])
async def xtb_positions(): return {"positions": await _mod("xtb").get_positions()}

@app.get("/trading/xtb/balance", dependencies=[Depends(_auth)])
async def xtb_balance(): return await _mod("xtb").get_balance()

@app.post("/trading/xtb/order", dependencies=[Depends(_auth)])
async def xtb_order(req: OrderReqXTB):
    if not _mod("security").validate_financial(req.volume * 100):
        raise HTTPException(403, "Financial action not authorized")
    return await _mod("xtb").place_order(req.symbol, req.cmd, req.volume, req.sl, req.tp, req.price)


# ── Trading — IBKR ────────────────────────────────────────────────────────────
@app.get("/trading/ibkr/status", dependencies=[Depends(_auth)])
def ibkr_status(): return _mod("ibkr").status()

@app.get("/trading/ibkr/positions", dependencies=[Depends(_auth)])
async def ibkr_positions(): return {"positions": await _mod("ibkr").get_positions()}

@app.get("/trading/ibkr/account", dependencies=[Depends(_auth)])
async def ibkr_account(): return await _mod("ibkr").get_account_summary()

@app.post("/trading/ibkr/order", dependencies=[Depends(_auth)])
async def ibkr_order(req: OrderReqIBKR):
    if not _mod("security").validate_financial(req.quantity * 10):
        raise HTTPException(403, "Financial action not authorized")
    return await _mod("ibkr").place_order(req.symbol, req.action, req.quantity)

@app.post("/trade/real/enable", dependencies=[Depends(_auth)])
def enable_real(req: RealEnableReq):
    sec = _mod("security")
    ok = sec.authorize_financial(req.code)
    xtb = _nexus.get("xtb") if _nexus else None
    ibkr = _nexus.get("ibkr") if _nexus else None
    if xtb: xtb.enable_real(req.code)
    if ibkr: ibkr.enable_real(req.code)
    return {"authorized": ok, "warning": "Real money at risk" if ok else "Invalid code"}


# ── Security ──────────────────────────────────────────────────────────────────
@app.post("/security/pin/verify")
def pin_verify(req: PinReq):
    sec = _mod("security")
    if not sec.check_rate("pin", limit=5, window=60):
        raise HTTPException(429, "Too many PIN attempts")
    if sec.verify_pin(req.pin):
        return {"ok": True, "token": sec.generate_token()}
    return {"ok": False}

@app.get("/security/audit", dependencies=[Depends(_auth)])
def security_audit(lines: int = 50):
    return {"lines": _mod("security").get_audit_log(lines)}

@app.get("/security/status", dependencies=[Depends(_auth)])
def security_status():
    return _mod("security").status()


# ── Monitor ───────────────────────────────────────────────────────────────────
@app.get("/monitor/metrics", dependencies=[Depends(_auth)])
def monitor_metrics():
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {"cpu_percent": cpu, "memory_percent": mem.percent,
                "memory_used_mb": mem.used // 1024 // 1024,
                "memory_total_mb": mem.total // 1024 // 1024,
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free // 1024 // 1024 // 1024}
    except Exception as e:
        return {"error": str(e)}

@app.get("/monitor/status")
def monitor_status():
    current_file = _MONITOR_DIR / "current.json"
    if not current_file.exists():
        return {"error": "No monitor data yet", "hint": "Run scripts/monitor_collect.sh on VPS"}
    try:
        return _json.loads(current_file.read_text())
    except Exception as e:
        return {"error": str(e)}

@app.get("/monitor/history")
def monitor_history(limit: int = 50):
    history_file = _MONITOR_DIR / "history.jsonl"
    if not history_file.exists():
        return {"history": [], "count": 0}
    try:
        lines = [l for l in history_file.read_text().splitlines() if l.strip()]
        entries = [_json.loads(l) for l in lines]
        limited = entries[-limit:]
        return {"history": limited, "count": len(limited)}
    except Exception as e:
        return {"history": [], "error": str(e)}

@app.get("/monitor/autoheal")
def monitor_autoheal():
    if not _AUTOHEAL_STATE.exists():
        return {"consecutive_failures": 0, "last_action": "none", "last_check": None, "max_failures": 3}
    try:
        data = _json.loads(_AUTOHEAL_STATE.read_text())
        data.setdefault("max_failures", 3)
        return data
    except Exception as e:
        return {"error": str(e)}

@app.get("/monitor/scale")
def monitor_scale():
    load_history = _MONITOR_DIR / "load_history.jsonl"
    load_report = _MONITOR_DIR / "load_report.md"
    history: list = []
    if load_history.exists():
        try:
            lines = [l for l in load_history.read_text().splitlines() if l.strip()]
            history = [_json.loads(l) for l in lines]
        except Exception:
            pass
    report = load_report.read_text() if load_report.exists() else "No scaling report yet"
    latest = history[-1] if history else None
    return {"latest": latest, "history_count": len(history), "report": report,
            "recommendations": latest.get("recommendations", []) if latest else []}


# ── Logs ──────────────────────────────────────────────────────────────────────
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


# ── Settings ──────────────────────────────────────────────────────────────────
@app.get("/settings", dependencies=[Depends(_auth)])
def get_settings():
    try:
        return _json.loads(_SETTINGS_PATH.read_text()) if _SETTINGS_PATH.exists() else {}
    except Exception:
        return {}

@app.put("/settings", dependencies=[Depends(_auth)])
def update_settings(body: dict):
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        if _SETTINGS_PATH.exists():
            existing = _json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        pass
    existing.update(body)
    _SETTINGS_PATH.write_text(_json.dumps(existing, indent=2))
    return {"status": "saved", "settings": existing}


# ── Legacy ────────────────────────────────────────────────────────────────────
@app.get("/positions", dependencies=[Depends(_auth)])
async def legacy_positions():
    t = _nexus.get("trading") if _nexus else None
    if not t:
        raise HTTPException(503, "Trading unavailable")
    return {"orders": t.get_orders() if hasattr(t, 'get_orders') else []}


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws_endpoint(ws, _nexus)
