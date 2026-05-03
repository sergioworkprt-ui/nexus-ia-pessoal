"""
NEXUS CLI Controller
Command-line interface for managing a running NexusRuntime instance.

Usage:
    python nexus_cli.py start   [--config PATH] [--dry-run] [--detach]
    python nexus_cli.py stop
    python nexus_cli.py status  [--json]
    python nexus_cli.py run <pipeline>
    python nexus_cli.py report  [--pipeline <name>] [--export PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nexus_runtime import (
    NexusRuntime,
    RuntimeConfig,
    PipelineStatus,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_PID_FILE    = Path("logs/live/nexus.pid")
_STATUS_FILE = Path("logs/live/startup_status.json")
_AUDIT_FILE  = Path("logs/live/audit_live.jsonl")

_BOLD   = "\033[1m"
_RESET  = "\033[0m"
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"

_PIPELINES = ("intelligence", "financial", "evolution", "consensus", "reporting")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET}  {msg}")


def _err(msg: str) -> None:
    print(f"  {_RED}✗{_RESET}  {msg}")
    sys.exit(1)


def _header(title: str) -> None:
    print(f"\n{_BOLD}{'─' * 55}{_RESET}")
    print(f"{_BOLD}  {title}{_RESET}")
    print(f"{_BOLD}{'─' * 55}{_RESET}")


# ---------------------------------------------------------------------------
# PID helpers (for detached/background mode)
# ---------------------------------------------------------------------------

def _write_pid(pid: int) -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _read_pid() -> Optional[int]:
    if not _PID_FILE.exists():
        return None
    try:
        return int(_PID_FILE.read_text().strip())
    except ValueError:
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _clear_pid() -> None:
    if _PID_FILE.exists():
        _PID_FILE.unlink()


# ---------------------------------------------------------------------------
# Build a temporary RuntimeConfig + NexusRuntime for one-shot commands
# ---------------------------------------------------------------------------

def _build_runtime(config_path: Optional[str] = None) -> NexusRuntime:
    if config_path:
        p = Path(config_path)
        if not p.exists():
            _err(f"Config file not found: {config_path}")
        config = RuntimeConfig.load(str(p))
    else:
        config = RuntimeConfig.live()

    config.audit_log_path        = str(_AUDIT_FILE)
    config.state.checkpoint_path = "data/runtime/live_checkpoint.json"
    config.reporting.export_dir  = "reports/live"
    return NexusRuntime(config)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    """Start NexusRuntime (foreground or detached)."""
    pid = _read_pid()
    if pid and _pid_running(pid):
        _warn(f"NEXUS is already running (PID {pid}).")
        return

    if args.detach:
        # Launch nexus_live.py as a background process
        cmd = [sys.executable, str(_ROOT / "nexus_live.py")]
        if args.config:
            cmd += ["--config", args.config]
        if args.dry_run:
            cmd.append("--dry-run")

        log_out = _AUDIT_FILE.parent / "stdout.log"
        log_out.parent.mkdir(parents=True, exist_ok=True)
        with log_out.open("w") as fh:
            proc = subprocess.Popen(
                cmd,
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _write_pid(proc.pid)
        _ok(f"NEXUS started in background  (PID {proc.pid})")
        _ok(f"Logs: {log_out}")
        _ok(f"Stop with: python nexus_cli.py stop")
        return

    # Foreground: delegate to nexus_live.py
    cmd = [sys.executable, str(_ROOT / "nexus_live.py")]
    if args.config:
        cmd += ["--config", args.config]
    if args.dry_run:
        cmd.append("--dry-run")

    _write_pid(os.getpid())
    try:
        os.execv(sys.executable, cmd)
    finally:
        _clear_pid()


def cmd_stop(args: argparse.Namespace) -> None:
    """Send SIGTERM to a detached NEXUS process."""
    import signal as _sig

    pid = _read_pid()
    if not pid:
        _warn("No PID file found. Is NEXUS running in detached mode?")
        return

    if not _pid_running(pid):
        _warn(f"PID {pid} is not running. Cleaning up.")
        _clear_pid()
        return

    os.kill(pid, _sig.SIGTERM)
    _ok(f"SIGTERM sent to PID {pid}.")

    # Wait up to 10s for process to exit
    for _ in range(20):
        time.sleep(0.5)
        if not _pid_running(pid):
            _clear_pid()
            _ok("NEXUS stopped cleanly.")
            return

    _warn(f"Process {pid} did not exit within 10s. Use SIGKILL manually.")


def cmd_status(args: argparse.Namespace) -> None:
    """Show runtime status by reading saved status file + live checkpoint."""
    _header("NEXUS STATUS")

    # Check if a detached process is running
    pid = _read_pid()
    if pid:
        if _pid_running(pid):
            _ok(f"Process        PID {pid}  (running)")
        else:
            _warn(f"Process        PID {pid}  (not found — stale PID file)")
            _clear_pid()
    else:
        _warn("Process        not running (no PID file)")

    # Load last startup status from disk
    if _STATUS_FILE.exists():
        try:
            info = json.loads(_STATUS_FILE.read_text())
            print(f"\n  Started at   : {info.get('started_at', 'N/A')}")
            print(f"  Mode         : {_BOLD}{info.get('mode', 'N/A').upper()}{_RESET}")
            print(f"  Version      : {info.get('version', 'N/A')}")

            print(f"\n  {'MODULE':<25} {'STATUS'}")
            print(f"  {'─' * 40}")
            for mod, ready in info.get("integration", {}).items():
                indicator = f"{_GREEN}ready{_RESET}" if ready else f"{_YELLOW}degraded{_RESET}"
                print(f"  {mod:<25} {indicator}")

            print(f"\n  {'PIPELINE':<20} {'MODE':<12} {'INTERVAL'}")
            print(f"  {'─' * 48}")
            for name, cfg in info.get("pipelines", {}).items():
                mode     = cfg.get("mode", "?")
                interval = cfg.get("interval_seconds", 0)
                h, rem   = divmod(interval, 3600)
                m        = rem // 60
                ivstr    = f"{h}h {m}m" if h else (f"{m}m" if m else "—")
                col      = _GREEN if mode == "enabled" else (_YELLOW if mode == "dry_run" else _RED)
                print(f"  {name:<20} {col}{mode:<12}{_RESET} {ivstr}")
        except Exception as exc:
            _warn(f"Could not parse status file: {exc}")
    else:
        _warn("No startup status file found. Has NEXUS been started yet?")

    # Load live checkpoint state
    checkpoint_path = Path("data/runtime/live_checkpoint_00.json")
    if checkpoint_path.exists():
        try:
            state = json.loads(checkpoint_path.read_text())
            print(f"\n  Cycle count  : {state.get('cycle_count', 0)}")
            print(f"  Uptime       : {state.get('uptime_seconds', 0):.1f}s")
            print(f"  Last cycle   : {state.get('last_cycle_at', 'N/A')}")
        except Exception:
            pass

    # Audit log tail
    if _AUDIT_FILE.exists():
        lines = _AUDIT_FILE.read_text().splitlines()
        recent = lines[-5:] if len(lines) >= 5 else lines
        print(f"\n  {'─' * 55}")
        print(f"  Last {len(recent)} audit entries:")
        for line in recent:
            try:
                entry = json.loads(line)
                ts  = entry.get("ts", "")[:19].replace("T", " ")
                evt = entry.get("event", "?")
                print(f"    {_CYAN}{ts}{_RESET}  {evt}")
            except Exception:
                print(f"    {line[:80]}")

    if args.json:
        out = {
            "pid": pid,
            "pid_running": bool(pid and _pid_running(pid)),
            "status_file": str(_STATUS_FILE) if _STATUS_FILE.exists() else None,
            "audit_entries": len(
                _AUDIT_FILE.read_text().splitlines()
            ) if _AUDIT_FILE.exists() else 0,
        }
        print(f"\n{json.dumps(out, indent=2)}")

    print()


def cmd_run(args: argparse.Namespace) -> None:
    """Run a single pipeline immediately."""
    pipeline = args.pipeline
    if pipeline not in _PIPELINES:
        _err(f"Unknown pipeline '{pipeline}'. Valid: {', '.join(_PIPELINES)}")

    _header(f"RUNNING PIPELINE: {pipeline.upper()}")
    print(f"  Config : {args.config or 'default live config'}")
    print(f"  Start  : {_now()}\n")

    runtime = _build_runtime(args.config)
    ok = runtime.start()
    if not ok:
        _err("Runtime failed to start.")

    try:
        result = runtime.run_pipeline(pipeline)
    finally:
        runtime.stop()

    if result is None:
        _err(f"Pipeline '{pipeline}' not found or returned None.")

    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    dur    = getattr(result, "duration_ms", 0)
    errors = getattr(result, "errors", [])

    if status in ("success", "partial"):
        _ok(f"Status : {status}  ({dur:.0f} ms)")
    else:
        _warn(f"Status : {status}  ({dur:.0f} ms)")

    if errors:
        print(f"  Errors :")
        for e in errors:
            print(f"    {_RED}•{_RESET} {e}")

    data = getattr(result, "data", {})
    if data:
        print(f"\n  Output:")
        for k, v in list(data.items())[:10]:
            vstr = json.dumps(v)[:80] if not isinstance(v, str) else v[:80]
            print(f"    {_CYAN}{k}{_RESET}: {vstr}")

    if args.export:
        out_path = Path(args.export)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result.to_dict() if hasattr(result, "to_dict") else vars(result),
                       indent=2, default=str),
            encoding="utf-8",
        )
        _ok(f"Result exported to: {out_path}")

    print()


def cmd_report(args: argparse.Namespace) -> None:
    """Run all pipelines and generate a consolidated status report."""
    _header("NEXUS REPORT")
    print(f"  Config    : {args.config or 'default live config'}")
    print(f"  Generated : {_now()}\n")

    runtime = _build_runtime(args.config)
    ok = runtime.start()
    if not ok:
        _err("Runtime failed to start.")

    try:
        if args.pipeline:
            if args.pipeline not in _PIPELINES:
                runtime.stop()
                _err(f"Unknown pipeline '{args.pipeline}'. Valid: {', '.join(_PIPELINES)}")
            results = [runtime.run_pipeline(args.pipeline)]
        else:
            results = runtime.run_all_pipelines()

        audit_ok = runtime.audit_chain_ok()
        state    = runtime.state.current_state_dict()
    finally:
        runtime.stop()

    # ── Summary table ────────────────────────────────────────────────────────
    print(f"  {'PIPELINE':<20} {'STATUS':<12} {'DURATION':>10}  {'ERRORS'}")
    print(f"  {'─' * 58}")
    total_ok = 0
    for r in results:
        status  = r.status.value if hasattr(r.status, "value") else str(r.status)
        dur     = getattr(r, "duration_ms", 0)
        errors  = getattr(r, "errors", [])
        name    = getattr(r, "pipeline", "?")
        is_ok   = status in ("success", "partial")
        col     = _GREEN if is_ok else (_YELLOW if status == "skipped" else _RED)
        err_str = f"{len(errors)} error(s)" if errors else "—"
        print(f"  {name:<20} {col}{status:<12}{_RESET} {dur:>9.0f}ms  {err_str}")
        if is_ok:
            total_ok += 1

    print(f"\n  Pipelines OK  : {total_ok}/{len(results)}")
    print(f"  Cycle count   : {state.get('cycle_count', 0)}")
    print(f"  Audit chain   : {f'{_GREEN}VALID ✓{_RESET}' if audit_ok else f'{_RED}INVALID ✗{_RESET}'}")

    # ── Export ────────────────────────────────────────────────────────────────
    export_path = args.export or f"reports/live/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out = Path(export_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "generated_at": _now(),
        "audit_chain_ok": audit_ok,
        "cycle_count": state.get("cycle_count", 0),
        "results": [
            (r.to_dict() if hasattr(r, "to_dict") else vars(r))
            for r in results
        ],
    }
    out.write_text(json.dumps(report_data, indent=2, default=str), encoding="utf-8")
    _ok(f"Report saved to: {out}")
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus_cli",
        description="NEXUS CLI — control the live runtime from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nexus_cli.py start
  python nexus_cli.py start --detach --config config/live_runtime.json
  python nexus_cli.py stop
  python nexus_cli.py status
  python nexus_cli.py status --json
  python nexus_cli.py run intelligence
  python nexus_cli.py run financial --export reports/live/financial.json
  python nexus_cli.py report
  python nexus_cli.py report --pipeline consensus --export reports/live/consensus.json
""",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # start
    p_start = sub.add_parser("start", help="Start the NexusRuntime in LIVE mode.")
    p_start.add_argument("--config",   metavar="PATH", help="Path to live_runtime.json.")
    p_start.add_argument("--dry-run",  action="store_true", help="All pipelines in dry_run mode.")
    p_start.add_argument("--detach",   action="store_true", help="Run in background (writes PID file).")

    # stop
    sub.add_parser("stop", help="Send SIGTERM to a detached NEXUS process.")

    # status
    p_status = sub.add_parser("status", help="Show runtime status.")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON.")

    # run
    p_run = sub.add_parser("run", help="Run a single pipeline immediately.")
    p_run.add_argument("pipeline", choices=_PIPELINES, help="Pipeline to run.")
    p_run.add_argument("--config", metavar="PATH", help="Path to live_runtime.json.")
    p_run.add_argument("--export", metavar="PATH", help="Save result to JSON file.")

    # report
    p_rep = sub.add_parser("report", help="Run all pipelines and export a consolidated report.")
    p_rep.add_argument("--pipeline", choices=_PIPELINES, help="Run only one pipeline.")
    p_rep.add_argument("--config",   metavar="PATH", help="Path to live_runtime.json.")
    p_rep.add_argument("--export",   metavar="PATH", help="Output JSON path (default: reports/live/).")

    return parser


def main() -> int:
    parser  = _build_parser()
    args    = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    dispatch = {
        "start":  cmd_start,
        "stop":   cmd_stop,
        "status": cmd_status,
        "run":    cmd_run,
        "report": cmd_report,
    }
    dispatch[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
