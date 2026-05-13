"""NEXUS Prometheus metrics — Prometheus exposition format endpoint + in-process counters."""
from __future__ import annotations

import os
import subprocess
import time
from collections import defaultdict

import psutil
from fastapi import APIRouter, Response

_START_TIME = time.monotonic()

# In-process counters (safe for single-worker uvicorn)
_request_count: dict[str, int] = defaultdict(int)
_error_count: int = 0
_request_latency: dict[str, list[float]] = defaultdict(list)
_ws_connections: int = 0

router = APIRouter(tags=["prometheus"])


def record_request(method: str, path: str, status: int, duration: float) -> None:
    """Call from HTTP middleware on every request to update Prometheus counters."""
    key = f"{method}|{path}|{status}"
    _request_count[key] += 1
    if status >= 500:
        global _error_count
        _error_count += 1
    samples = _request_latency[path]
    samples.append(duration)
    if len(samples) > 500:
        _request_latency[path] = samples[-500:]


def set_ws_connections(n: int) -> None:
    global _ws_connections
    _ws_connections = n


def _svc_up(name: str) -> int:
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", name], capture_output=True, timeout=2)
        return 1 if r.returncode == 0 else 0
    except Exception:
        return 0


def _g(name: str, help_text: str, value: float, labels: dict | None = None) -> str:
    lbl = ""
    if labels:
        lbl = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    return f"# HELP {name} {help_text}\n# TYPE {name} gauge\n{name}{lbl} {value:.6g}\n"


def _c(name: str, help_text: str, value: float, labels: dict | None = None) -> str:
    lbl = ""
    if labels:
        lbl = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    return f"# HELP {name} {help_text}\n# TYPE {name} counter\n{name}{lbl} {value:.0f}\n"


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Prometheus exposition format — configure Prometheus to scrape this endpoint."""
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg()
    uptime = time.monotonic() - _START_TIME

    out: list[str] = []

    # ── System resources ────────────────────────────────────────────────────────────
    out.append(_g("nexus_cpu_percent", "CPU utilization percent", cpu))
    out.append(_g("nexus_memory_percent", "RAM utilization percent", mem.percent))
    out.append(_g("nexus_memory_used_bytes", "RAM used in bytes", float(mem.used)))
    out.append(_g("nexus_memory_total_bytes", "RAM total in bytes", float(mem.total)))
    out.append(_g("nexus_disk_percent", "Disk utilization percent", disk.percent))
    out.append(_g("nexus_disk_free_bytes", "Disk free space in bytes", float(disk.free)))
    out.append(_g("nexus_load_avg_1m", "System load average 1 minute", load[0]))
    out.append(_g("nexus_load_avg_5m", "System load average 5 minutes", load[1]))
    out.append(_g("nexus_load_avg_15m", "System load average 15 minutes", load[2]))
    out.append(_g("nexus_uptime_seconds", "API process uptime in seconds", uptime))
    out.append(_g("nexus_websocket_connections", "Active WebSocket connections", float(_ws_connections)))

    # ── Service status ──────────────────────────────────────────────────────────────────
    out.append("# HELP nexus_service_up Service is active (1) or inactive (0)\n# TYPE nexus_service_up gauge\n")
    for svc in ("nexus-core", "nexus-api", "nexus-dashboard", "nexus-ws"):
        out.append(f'nexus_service_up{{service="{svc}"}} {_svc_up(svc)}\n')

    # ── HTTP request counters ────────────────────────────────────────────────────────────
    out.append("# HELP nexus_http_requests_total HTTP requests by method/path/status\n# TYPE nexus_http_requests_total counter\n")
    for key, count in sorted(_request_count.items()):
        parts = key.split("|", 2)
        if len(parts) == 3:
            m, p, s = parts
            out.append(f'nexus_http_requests_total{{method="{m}",path="{p}",status="{s}"}} {count}\n')

    out.append(_c("nexus_http_errors_total", "Total HTTP 5xx error responses", float(_error_count)))

    # ── Latency p99 ─────────────────────────────────────────────────────────────────────────────
    out.append("# HELP nexus_request_duration_p99_seconds Request duration 99th percentile\n# TYPE nexus_request_duration_p99_seconds gauge\n")
    for path, samples in sorted(_request_latency.items()):
        if samples:
            ss = sorted(samples)
            idx = max(0, int(len(ss) * 0.99) - 1)
            out.append(f'nexus_request_duration_p99_seconds{{path="{path}"}} {ss[idx]:.6f}\n')

    return Response(content="".join(out), media_type="text/plain; version=0.0.4; charset=utf-8")
