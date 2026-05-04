"""
Dashboard Data Reader
Reads runtime files from disk — no live runtime connection needed.
All paths are relative to the project root (one level up from this file).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).parent.parent


def _load_json(rel: str) -> Optional[Dict[str, Any]]:
    p = _ROOT / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(rel: str, limit: int = 100) -> List[Dict[str, Any]]:
    p = _ROOT / rel
    if not p.exists():
        return []
    lines: List[Dict[str, Any]] = []
    try:
        raw = p.read_text(encoding="utf-8").splitlines()
        for line in raw[-limit:]:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except Exception:
                    lines.append({"raw": line})
    except Exception:
        pass
    return lines


def _mtime(rel: str) -> Optional[str]:
    p = _ROOT / rel
    if not p.exists():
        return None
    ts = p.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def read_startup_status() -> Dict[str, Any]:
    data = _load_json("logs/live/startup_status.json") or {}
    pid_path = _ROOT / "logs/live/nexus.pid"
    pid_running = False
    pid = None
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            pid_running = True
        except Exception:
            pass
    data["_pid"] = pid
    data["_pid_running"] = pid_running
    return data


def read_checkpoint() -> Dict[str, Any]:
    # Try live_checkpoint_00.json first, then fallback to checkpoint_00.json
    for name in ("live_checkpoint_00.json", "checkpoint_00.json"):
        data = _load_json(f"data/runtime/{name}")
        if data:
            return data
    # Try checkpoint_index to find latest
    idx = _load_json("data/runtime/checkpoint_index.json")
    if idx and isinstance(idx, list) and idx:
        latest = sorted(idx, key=lambda x: x.get("created_at", ""), reverse=True)[0]
        path = latest.get("path", "")
        if path:
            data = _load_json(path.lstrip("/"))
            if data:
                return data
    return {}


def read_checkpoint_index() -> List[Dict[str, Any]]:
    idx = _load_json("data/runtime/checkpoint_index.json")
    if isinstance(idx, list):
        return sorted(idx, key=lambda x: x.get("created_at", ""), reverse=True)
    return []


def read_audit_log(limit: int = 50) -> List[Dict[str, Any]]:
    entries = _load_jsonl("logs/live/audit_live.jsonl", limit=limit)
    # Normalise mixed formats
    out = []
    for e in entries:
        if "ts" in e and "event" in e:
            out.append({"ts": e["ts"], "event": e["event"], "data": e.get("data", {})})
        elif "entry_id" in e:
            payload = e.get("payload", {})
            out.append({
                "ts": e.get("ts", ""),
                "event": payload.get("action", payload.get("event_type", "AUDIT")),
                "data": payload,
            })
        else:
            out.append({"ts": "", "event": str(e.get("raw", e))[:120], "data": {}})
    return list(reversed(out))


def read_audit_chain_status() -> Dict[str, Any]:
    p = _ROOT / "logs/audit_chain.jsonl"
    if not p.exists():
        return {"available": False}
    lines = p.read_text(encoding="utf-8").splitlines()
    count = sum(1 for l in lines if l.strip())
    return {"available": True, "entry_count": count, "path": str(p)}


def read_signals() -> List[Dict[str, Any]]:
    data = _load_json("reports/live/signals_latest.json")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "signals" in data:
        return data["signals"]
    return []


def read_reports_list() -> List[Dict[str, Any]]:
    reports_dir = _ROOT / "reports/live"
    if not reports_dir.exists():
        return []
    files = []
    for p in sorted(reports_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.suffix == ".json":
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
                "path": str(p.relative_to(_ROOT)),
            })
    return files[:50]


def read_report_file(name: str) -> Optional[Dict[str, Any]]:
    p = _ROOT / "reports/live" / name
    if not p.exists() or p.suffix != ".json":
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_limits() -> Dict[str, Any]:
    cfg = _load_json("config/live_runtime.json") or {}
    pipeline_cfg = _load_json("config/live_pipelines.json") or {}
    return {"runtime": cfg, "pipelines": pipeline_cfg}


def read_pipeline_status() -> Dict[str, Any]:
    startup = read_startup_status()
    checkpoint = read_checkpoint()
    limits = read_limits()

    pipelines_cfg = startup.get("pipelines", {})
    pipeline_runs = checkpoint.get("pipeline_last_run", {})
    pipeline_errors = checkpoint.get("pipeline_errors", {})
    pipeline_run_counts = checkpoint.get("pipeline_runs", {})
    schedule_notes = limits.get("pipelines", {}).get("schedule_notes", {})
    pipeline_schedule = limits.get("pipelines", {}).get("pipelines", {})

    result = {}
    for name in ("intelligence", "financial", "evolution", "consensus", "reporting"):
        cfg = pipelines_cfg.get(name, {})
        sched = pipeline_schedule.get(name, {})
        result[name] = {
            "mode": cfg.get("mode", sched.get("mode", "unknown")),
            "interval_seconds": cfg.get("interval_seconds", sched.get("interval_seconds", 0)),
            "last_run": pipeline_runs.get(name, "never"),
            "run_count": pipeline_run_counts.get(name, 0),
            "error_count": pipeline_errors.get(name, 0),
            "description": sched.get("description", ""),
            "dependencies": sched.get("dependencies", []),
        }
    return result


def read_evolution_log(limit: int = 20) -> List[Dict[str, Any]]:
    """Read entries from logs/evolution_live.jsonl (newest first)."""
    entries = _load_jsonl("logs/evolution_live.jsonl", limit=limit * 2)
    return list(reversed(entries[-limit:]))


def read_evolution_summary() -> Dict[str, Any]:
    """Read the last evolution summary exported by the reporting pipeline."""
    data = _load_json("reports/live/evolution_summary.json") or {}
    return data


def read_evolution_data() -> Dict[str, Any]:
    log     = read_evolution_log(limit=20)
    summary = read_evolution_summary()

    # Extract pending proposals from the most recent non-rollback log entry
    pending: List[Dict[str, Any]] = []
    active_adjustments: List[Dict[str, Any]] = []
    for entry in log:
        if entry.get("action") == "apply":
            # Most recent apply contains current active adjustments
            if not active_adjustments:
                active_adjustments = entry.get("proposals", [])
            break

    # Pending come from evolution_summary if present
    pending = summary.get("pending_proposals", [])

    return {
        "log":                log,
        "summary":            summary,
        "pending_proposals":  pending,
        "active_adjustments": active_adjustments,
    }


def read_ibkr_status() -> Dict[str, Any]:
    """Read IBKR integration status from persisted state files."""
    capital = _load_json("data/ibkr/capital_state.json") or {}
    risk    = _load_json("data/ibkr/risk_state.json") or {}
    positions = _load_json("data/ibkr/positions.json") or {}
    pending   = _load_json("data/ibkr/pending_orders.json") or {}
    cfg       = (_load_json("config/live_runtime.json") or {}).get("ibkr", {})

    n_positions = len(positions)
    n_pending   = len(pending)

    return {
        "enabled":      cfg.get("enabled", False),
        "mode":         cfg.get("mode", "paper"),
        "connected":    False,   # file-only read; live connection not available here
        "balance":      capital.get("initial_capital", 0.0),
        "n_positions":  n_positions,
        "n_pending":    n_pending,
        "capital":      capital,
        "risk":         risk,
        "cfg":          cfg,
        "updated":      capital.get("last_updated", "—"),
    }


def read_ibkr_positions() -> List[Dict[str, Any]]:
    """Read open IBKR positions from persisted JSON."""
    positions = _load_json("data/ibkr/positions.json") or {}
    if isinstance(positions, dict):
        return list(positions.values())
    if isinstance(positions, list):
        return positions
    return []


def read_ibkr_orders() -> Dict[str, Any]:
    """Read IBKR order logs (recent fills + pending)."""
    pending  = _load_json("data/ibkr/pending_orders.json") or {}
    log      = _load_jsonl("logs/ibkr_orders.jsonl", limit=50)
    fills    = [e for e in log if e.get("status") in ("simulated", "filled", "closed")]
    return {
        "pending": list(pending.values()) if isinstance(pending, dict) else pending,
        "recent":  list(reversed(fills[-20:])),
        "total_logged": len(log),
    }


def read_ibkr_capital() -> Dict[str, Any]:
    """Read IBKR capital state including bucket breakdown."""
    state = _load_json("data/ibkr/capital_state.json") or {}
    risk  = _load_json("data/ibkr/risk_state.json") or {}

    initial    = state.get("initial_capital", 0.0)
    recovered  = state.get("recovered_capital", 0.0)
    limit      = state.get("user_capital_limit", 0.0)
    deployed   = state.get("total_deployed", 0.0)
    tools      = state.get("tools_fund", 0.0)
    reinvest   = state.get("reinvest_fund", 0.0)
    standby    = state.get("standby_fund", 0.0)
    profit     = state.get("nexus_profit", 0.0)
    in_recovery = state.get("in_recovery_phase", True)

    available  = max(0.0, min(limit, tools + reinvest) - deployed) if limit else 0.0

    return {
        "initial_capital":   initial,
        "recovered_capital": recovered,
        "recovery_gap":      max(0.0, initial - recovered),
        "in_recovery_phase": in_recovery,
        "user_capital_limit": limit,
        "total_deployed":    deployed,
        "available_capital": available,
        "nexus_profit":      profit,
        "buckets": {
            "tools_fund":    tools,
            "reinvest_fund": reinvest,
            "standby_fund":  standby,
        },
        "risk": {
            "daily_risk_used":   risk.get("daily_risk_used", 0.0),
            "weekly_risk_used":  risk.get("weekly_risk_used", 0.0),
            "current_drawdown":  risk.get("current_drawdown", 0.0),
            "in_safe_mode":      risk.get("in_safe_mode", False),
            "safe_mode_reason":  risk.get("safe_mode_reason", ""),
        },
        "updated": state.get("last_updated", "—"),
    }


def read_overview() -> Dict[str, Any]:
    startup = read_startup_status()
    checkpoint = read_checkpoint()
    audit_chain = read_audit_chain_status()
    signals = read_signals()

    modules = startup.get("integration", {})
    if isinstance(modules, dict):
        module_map = modules.get("modules", modules)
    else:
        module_map = {}

    return {
        "startup": startup,
        "checkpoint": checkpoint,
        "modules": module_map,
        "audit_chain": audit_chain,
        "signal_count": len(signals),
        "pipelines": read_pipeline_status(),
    }
