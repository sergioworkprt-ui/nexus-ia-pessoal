"""NEXUS Automation API — secure external endpoints for CI/CD and DevOps."""
from __future__ import annotations

import os
import subprocess
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from nexus.services.logger.logger import get_logger

log = get_logger("automation-api")

router = APIRouter(prefix="/api", tags=["automation"])

_NEXUS_HOME = Path(os.getenv("NEXUS_HOME", "/opt/nexus"))
_AUDIT_LOG = _NEXUS_HOME / "logs" / "automation_audit.log"
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_RATE_LIMIT = int(os.getenv("AUTOMATION_RATE_LIMIT", "60"))
_RATE_WINDOW = int(os.getenv("AUTOMATION_RATE_WINDOW", "60"))
_request_times: dict[str, deque] = defaultdict(deque)


def _audit(action: str, ip: str, details: str = "") -> None:
    _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with open(_AUDIT_LOG, "a") as f:
        f.write(f"[{ts}] [AUDIT] action={action} ip={ip} {details}\n")
    log.info("AUDIT %s ip=%s %s", action, ip, details)


def _require_api_key(key: str | None = Depends(_API_KEY_HEADER)) -> None:
    expected = os.getenv("AUTOMATION_API_KEY", "")
    if not expected:
        raise HTTPException(503, detail={"error": "AUTOMATION_API_KEY not configured on server"})
    if not key or key != expected:
        raise HTTPException(401, detail={"error": "Invalid or missing X-API-Key header"})


def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    q = _request_times[ip]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        raise HTTPException(
            429,
            detail={"error": f"Rate limit: {_RATE_LIMIT} requests per {_RATE_WINDOW}s"},
            headers={"Retry-After": str(_RATE_WINDOW)},
        )
    q.append(now)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ok(data: Any = None, message: str = "ok") -> dict:
    return {"status": "ok", "message": message, "data": data}


# ── Models ──────────────────────────────────────────────────────────────────────────
class DeployReq(BaseModel):
    commit: str = "HEAD"
    reason: str = "api-trigger"


class RollbackReq(BaseModel):
    commits_back: int = 1
    reason: str = "api-trigger"


class PluginReq(BaseModel):
    name: str


# ── GET /api/health ───────────────────────────────────────────────────────────────────────
@router.get("/health")
def api_health(request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("GET /api/health", _ip(request))
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return _ok({"api": "ok", "cpu_percent": cpu, "memory_percent": mem.percent, "disk_percent": disk.percent})


# ── POST /api/deploy ──────────────────────────────────────────────────────────────────────
@router.post("/deploy")
def api_deploy(body: DeployReq, request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("POST /api/deploy", _ip(request), f"commit={body.commit} reason={body.reason}")
    script = _NEXUS_HOME / "nexus" / "scripts" / "deploy_vps.sh"
    if not script.exists():
        raise HTTPException(404, detail={"error": "deploy_vps.sh not found on server"})
    try:
        result = subprocess.run(
            ["bash", str(script), body.commit],
            capture_output=True, text=True, timeout=120,
        )
        return _ok(
            {"exit_code": result.returncode, "stdout": result.stdout[-2000:], "stderr": result.stderr[-1000:]},
            message="deploy completed" if result.returncode == 0 else "deploy failed",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, detail={"error": "Script timed out (120s)"})
    except Exception as e:
        raise HTTPException(500, detail={"error": str(e)})


# ── POST /api/rollback ────────────────────────────────────────────────────────────────────
@router.post("/rollback")
def api_rollback(body: RollbackReq, request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("POST /api/rollback", _ip(request), f"commits_back={body.commits_back} reason={body.reason}")
    script = _NEXUS_HOME / "nexus" / "scripts" / "rollback.sh"
    if not script.exists():
        raise HTTPException(404, detail={"error": "rollback.sh not found on server"})
    try:
        result = subprocess.run(
            ["bash", str(script), "manual", str(body.commits_back), body.reason],
            capture_output=True, text=True, timeout=120,
        )
        return _ok(
            {"exit_code": result.returncode, "stdout": result.stdout[-2000:]},
            message="rollback completed" if result.returncode == 0 else "rollback failed",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, detail={"error": "Script timed out (120s)"})
    except Exception as e:
        raise HTTPException(500, detail={"error": str(e)})


# ── GET /api/logs ──────────────────────────────────────────────────────────────────────────
@router.get("/logs")
def api_logs(
    request: Request,
    service: str = "core",
    lines: int = 100,
    _: None = Depends(_require_api_key),
):
    _rate_limit(request)
    _audit("GET /api/logs", _ip(request), f"service={service}")
    allowed = {"core", "api", "dashboard", "backup", "autoheal", "alerts", "automation_audit"}
    if service not in allowed:
        raise HTTPException(400, detail={"error": f"Unknown service. Allowed: {sorted(allowed)}"})
    log_file = _NEXUS_HOME / "logs" / (
        "automation_audit.log" if service == "automation_audit" else f"{service}.log"
    )
    if not log_file.exists():
        return _ok({"lines": [], "total": 0})
    all_lines = log_file.read_text(errors="replace").splitlines()
    cap = min(lines, 500)
    return _ok({"lines": all_lines[-cap:], "total": len(all_lines)})


# ── GET /api/metrics ─────────────────────────────────────────────────────────────────────
@router.get("/metrics")
def api_metrics_json(request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("GET /api/metrics", _ip(request))
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = list(os.getloadavg())
    return _ok({
        "cpu_percent": cpu,
        "memory_percent": mem.percent,
        "memory_used_mb": mem.used // 1024 // 1024,
        "memory_total_mb": mem.total // 1024 // 1024,
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 1024 ** 3, 2),
        "load_avg": {"1m": load[0], "5m": load[1], "15m": load[2]},
    })


# ── GET /api/plugins ─────────────────────────────────────────────────────────────────────
@router.get("/plugins")
def api_plugins(request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("GET /api/plugins", _ip(request))
    try:
        from nexus.plugins.loader import discover
        raw = discover()
        plugins = [{k: v for k, v in p.items() if not k.startswith("_")} | {"enabled": p["_enabled"]} for p in raw]
        return _ok({"plugins": plugins, "count": len(plugins)})
    except Exception as e:
        return _ok({"plugins": [], "error": str(e)})


# ── POST /api/plugins/enable ───────────────────────────────────────────────────────────────
@router.post("/plugins/enable")
def api_plugins_enable(body: PluginReq, request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("POST /api/plugins/enable", _ip(request), f"name={body.name}")
    try:
        from nexus.plugins.loader import enable
        if enable(body.name):
            return _ok(message=f"Plugin '{body.name}' enabled")
        raise HTTPException(404, detail={"error": f"Plugin '{body.name}' not found"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail={"error": str(e)})


# ── POST /api/plugins/disable ──────────────────────────────────────────────────────────────
@router.post("/plugins/disable")
def api_plugins_disable(body: PluginReq, request: Request, _: None = Depends(_require_api_key)):
    _rate_limit(request)
    _audit("POST /api/plugins/disable", _ip(request), f"name={body.name}")
    try:
        from nexus.plugins.loader import disable
        disable(body.name)
        return _ok(message=f"Plugin '{body.name}' disabled")
    except Exception as e:
        raise HTTPException(500, detail={"error": str(e)})
