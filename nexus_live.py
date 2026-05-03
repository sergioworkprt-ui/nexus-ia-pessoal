"""
NEXUS Live Mode Entry Point
Boots the full NexusRuntime in LIVE mode with audit logging,
structured startup output, and graceful shutdown handling.

Usage:
    python nexus_live.py
    python nexus_live.py --config config/live_runtime.json
    python nexus_live.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nexus_runtime import (
    NexusRuntime,
    RuntimeConfig,
    RuntimeMode,
    EventType,
    PipelineMode,
)
from nexus_runtime.events import Event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BANNER = r"""
███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║
╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
                   LIVE MODE  v1.0.0
"""

_AUDIT_PATH = Path("logs/live/audit_live.jsonl")
_STATUS_PATH = Path("logs/live/startup_status.json")

_PIPELINE_COLORS = {
    "intelligence": "\033[36m",   # cyan
    "financial":    "\033[32m",   # green
    "evolution":    "\033[33m",   # yellow
    "consensus":    "\033[35m",   # magenta
    "reporting":    "\033[34m",   # blue
}
_RESET = "\033[0m"
_BOLD  = "\033[1m"
_RED   = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_banner() -> None:
    print(_BOLD + _BANNER + _RESET)


def _print_section(title: str) -> None:
    print(f"\n{_BOLD}{'─' * 60}{_RESET}")
    print(f"{_BOLD}  {title}{_RESET}")
    print(f"{_BOLD}{'─' * 60}{_RESET}")


def _print_ok(label: str, value: str = "") -> None:
    print(f"  {_GREEN}✓{_RESET}  {label:<35} {value}")


def _print_warn(label: str, value: str = "") -> None:
    print(f"  {_YELLOW}⚠{_RESET}  {label:<35} {value}")


def _print_err(label: str, value: str = "") -> None:
    print(f"  {_RED}✗{_RESET}  {label:<35} {value}")


def _write_audit(entry: dict) -> None:
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _make_event_handlers(runtime: NexusRuntime) -> None:
    """Subscribe live-mode event handlers to the bus."""

    def on_pipeline_completed(event: Event) -> None:
        pipe = event.data.get("pipeline", "?")
        status = event.data.get("status", "?")
        dur = event.data.get("duration_ms", 0)
        col = _PIPELINE_COLORS.get(pipe, "")
        indicator = f"{_GREEN}✓{_RESET}" if status in ("success", "partial") else f"{_RED}✗{_RESET}"
        print(f"  {indicator}  {col}{pipe:<15}{_RESET}  {status:<10}  {dur:.0f} ms")
        _write_audit({
            "ts": _now(), "event": "pipeline_completed",
            "pipeline": pipe, "status": status, "duration_ms": dur,
        })

    def on_pipeline_failed(event: Event) -> None:
        pipe = event.data.get("pipeline", "?")
        errors = event.data.get("errors", [])
        _print_err(f"Pipeline FAILED: {pipe}", str(errors))
        _write_audit({"ts": _now(), "event": "pipeline_failed", "pipeline": pipe, "errors": errors})

    def on_risk_breach(event: Event) -> None:
        detail = event.data.get("detail", "")
        print(f"\n  {_RED}{_BOLD}⚠  RISK BREACH: {detail}{_RESET}\n")
        _write_audit({"ts": _now(), "event": "risk_breach", "detail": detail})

    def on_kill_switch(event: Event) -> None:
        reason = event.data.get("reason", "")
        print(f"\n  {_RED}{_BOLD}🛑  KILL SWITCH TRIGGERED: {reason}{_RESET}\n")
        _write_audit({"ts": _now(), "event": "kill_switch", "reason": reason})

    def on_pattern_detected(event: Event) -> None:
        data = event.data
        _write_audit({"ts": _now(), "event": "pattern_detected", **data})

    def on_consensus_escalated(event: Event) -> None:
        _print_warn("Consensus escalated", str(event.data.get("reason", "")))
        _write_audit({"ts": _now(), "event": "consensus_escalated", **event.data})

    def on_security_violation(event: Event) -> None:
        _print_err("Security violation", str(event.data))
        _write_audit({"ts": _now(), "event": "security_violation", **event.data})

    def on_checkpoint_saved(event: Event) -> None:
        _write_audit({"ts": _now(), "event": "checkpoint_saved", **event.data})

    bus = runtime.bus
    bus.subscribe(on_pipeline_completed,  EventType.PIPELINE_COMPLETED,  "live:pipeline_completed")
    bus.subscribe(on_pipeline_failed,     EventType.PIPELINE_FAILED,     "live:pipeline_failed")
    bus.subscribe(on_risk_breach,         EventType.RISK_BREACH,         "live:risk_breach")
    bus.subscribe(on_kill_switch,         EventType.KILL_SWITCH_TRIGGERED, "live:kill_switch")
    bus.subscribe(on_pattern_detected,    EventType.PATTERN_DETECTED,    "live:pattern_detected")
    bus.subscribe(on_consensus_escalated, EventType.CONSENSUS_ESCALATED, "live:consensus_escalated")
    bus.subscribe(on_security_violation,  EventType.SECURITY_VIOLATION,  "live:security_violation")
    bus.subscribe(on_checkpoint_saved,    EventType.CHECKPOINT_SAVED,    "live:checkpoint_saved")


# ---------------------------------------------------------------------------
# Startup display
# ---------------------------------------------------------------------------

def _print_startup_status(runtime: NexusRuntime, config: RuntimeConfig) -> None:
    status = runtime.status()

    _print_section("RUNTIME CONFIGURATION")
    _print_ok("Mode",        status.get("mode", "?").upper())
    _print_ok("Version",     status.get("version", "?"))
    _print_ok("Audit log",   config.audit_log_path)
    _print_ok("Checkpoint",  config.state.checkpoint_path)
    _print_ok("Max workers", str(config.scheduler.max_concurrent))

    _print_section("MODULE STATUS")
    integration = status.get("integration", {})
    for module, ready in integration.items():
        if ready:
            _print_ok(module)
        else:
            _print_warn(module, "(degraded — simulation stub active)")

    _print_section("PIPELINE SCHEDULE")
    pipeline_cfgs = {
        "intelligence": config.intelligence,
        "financial":    config.financial,
        "evolution":    config.evolution,
        "consensus":    config.consensus,
        "reporting":    config.reporting,
    }
    for name, cfg in pipeline_cfgs.items():
        mode = cfg.mode.value if hasattr(cfg.mode, "value") else str(cfg.mode)
        interval = getattr(cfg, "interval_seconds", 0)
        col = _PIPELINE_COLORS.get(name, "")
        if mode == "disabled":
            _print_warn(f"{col}{name}{_RESET}", f"{mode}  (skipped)")
        else:
            h, rem = divmod(interval, 3600)
            m = rem // 60
            interval_str = f"{h}h {m}m" if h else f"{m}m"
            _print_ok(f"{col}{name}{_RESET}", f"{mode:<10}  every {interval_str}")

    _print_section("LIVE MODE ACTIVE")
    print(f"  {_GREEN}{_BOLD}NexusRuntime started successfully.{_RESET}")
    print(f"  Started at : {_now()}")
    print(f"  Press Ctrl+C to initiate graceful shutdown.\n")

    # Persist startup status to disk
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_PATH.write_text(json.dumps({
        "started_at": _now(),
        "mode": status.get("mode"),
        "version": status.get("version"),
        "integration": integration,
        "pipelines": {
            name: {
                "mode": (cfg.mode.value if hasattr(cfg.mode, "value") else str(cfg.mode)),
                "interval_seconds": getattr(cfg, "interval_seconds", 0),
            }
            for name, cfg in pipeline_cfgs.items()
        },
    }, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Shutdown handler
# ---------------------------------------------------------------------------

def _register_shutdown(runtime: NexusRuntime, stop_event: threading.Event) -> None:
    """Register SIGINT / SIGTERM handlers for graceful shutdown."""

    def _shutdown(signum, frame):  # noqa: ANN001
        sig_name = signal.Signals(signum).name
        print(f"\n\n  {_YELLOW}{_BOLD}[{sig_name}] Graceful shutdown initiated…{_RESET}")
        _write_audit({"ts": _now(), "event": "shutdown_requested", "signal": sig_name})
        stop_event.set()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nexus_live",
        description="NEXUS Live Mode — full runtime in production.",
    )
    parser.add_argument(
        "--config", metavar="PATH",
        help="Path to live_runtime.json config file.",
        default=None,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Start in DRY_RUN mode (all pipelines read-only; no side-effects).",
    )
    parser.add_argument(
        "--no-scheduler", action="store_true",
        help="Disable automatic pipeline scheduling (manual runs only).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    _print_banner()

    # ── Load config ──────────────────────────────────────────────────────────
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"  {_RED}Config file not found: {args.config}{_RESET}")
            return 1
        config = RuntimeConfig.load(str(config_path))
        print(f"  Loaded config from: {args.config}")
    else:
        config = RuntimeConfig.live()
        print(f"  Using default live RuntimeConfig.")

    # ── Apply overrides ──────────────────────────────────────────────────────
    if args.dry_run:
        for pipeline_cfg in (
            config.intelligence, config.financial,
            config.evolution, config.consensus, config.reporting,
        ):
            if pipeline_cfg.mode != PipelineMode.DISABLED:
                pipeline_cfg.mode = PipelineMode.DRY_RUN
        print(f"  {_YELLOW}DRY-RUN mode: all pipelines set to dry_run.{_RESET}")

    if args.no_scheduler:
        config.scheduler.enabled = False
        print(f"  {_YELLOW}Scheduler disabled: pipelines will not run automatically.{_RESET}")

    # ── Redirect audit log to live subfolder ─────────────────────────────────
    config.audit_log_path  = str(_AUDIT_PATH)
    config.state.checkpoint_path = "data/runtime/live_checkpoint.json"
    config.reporting.export_dir  = "reports/live"

    # ── Boot runtime ─────────────────────────────────────────────────────────
    runtime    = NexusRuntime(config)
    stop_event = threading.Event()

    _make_event_handlers(runtime)
    _register_shutdown(runtime, stop_event)

    _write_audit({"ts": _now(), "event": "startup", "mode": config.mode.value,
                  "dry_run": args.dry_run})

    ok = runtime.start()
    if not ok:
        print(f"\n  {_RED}Runtime failed to start — check logs.{_RESET}")
        _write_audit({"ts": _now(), "event": "startup_failed"})
        return 1

    _print_startup_status(runtime, config)

    # ── Keep-alive loop ──────────────────────────────────────────────────────
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=5.0)
    finally:
        print(f"  Stopping runtime…")
        runtime.stop()
        _write_audit({"ts": _now(), "event": "shutdown_complete"})

        audit_ok = runtime.audit_chain_ok()
        if audit_ok:
            _print_ok("Audit chain integrity", "VALID ✓")
        else:
            _print_warn("Audit chain integrity", "INVALID ✗")

        state = runtime.state.current_state_dict()
        print(f"\n  Cycles completed : {state.get('cycle_count', 0)}")
        print(f"  Uptime           : {state.get('uptime_seconds', 0):.1f}s")
        print(f"\n  {_BOLD}NEXUS shutdown complete.{_RESET}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
