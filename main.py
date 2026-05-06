"""
NEXUS — Main Entry Point

Boots the NexusRuntime in simulation mode, initialises the CommandEngine,
and opens an interactive command loop.

Usage:
    python main.py                  # interactive REPL
    python main.py --live           # live mode (real modules)
    python main.py --cmd "gateway status"  # single command, then exit

Public API (importable):
    from main import process_command
    response = process_command("gateway status")
    print(response)
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Globals — set by _boot()
# ---------------------------------------------------------------------------

_runtime = None
_engine  = None
_lock    = threading.Lock()


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

def _boot(live: bool = False) -> None:
    """Initialise runtime + command engine. Idempotent."""
    global _runtime, _engine

    with _lock:
        if _runtime is not None:
            return

        from nexus_runtime import NexusRuntime, RuntimeConfig
        from nexus_commands.command_engine import CommandEngine
        from nexus_commands.command_registry import CommandRegistry

        print(f"[NEXUS] Booting in {'LIVE' if live else 'SIMULATION'} mode…")

        config  = RuntimeConfig.live() if live else RuntimeConfig.simulation()
        runtime = NexusRuntime(config)
        ok      = runtime.start()

        registry = CommandRegistry()
        engine   = CommandEngine(runtime, safe_mode=True, registry=registry)

        _runtime = runtime
        _engine  = engine

        mode_str = config.mode.value.upper()
        status   = "OK" if ok else "DEGRADED (some modules unavailable)"
        print(f"[NEXUS] Runtime started — mode={mode_str}  status={status}")
        print(f"[NEXUS] Type a command or 'help'. Ctrl-C to exit.\n")


def _shutdown() -> None:
    global _runtime
    if _runtime is not None:
        print("\n[NEXUS] Shutting down…")
        _runtime.stop()
        print("[NEXUS] Stopped.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_command(text: str) -> str:
    """
    Process a natural-language NEXUS command and return the response string.

    Can be called from any external process, API layer, or test without
    touching the interactive loop.

    Example:
        from main import process_command
        print(process_command("gateway status"))
        print(process_command("ibkr positions"))
    """
    if _engine is None:
        _boot()

    response = _engine.execute(text)
    return str(response)


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

_BANNER = """
╔══════════════════════════════════════════════════╗
║          NEXUS Command Interface                 ║
║  Type a command or 'help'. Ctrl-C to exit.       ║
╚══════════════════════════════════════════════════╝
"""

_HELP_HINT = (
    "  Commands: gateway status | gateway login | gateway positions | gateway pnl\n"
    "            ibkr status | ibkr positions | ibkr balance | signal BTC\n"
    "            run pipeline | show status | help\n"
)


def _repl() -> None:
    print(_BANNER)
    print(_HELP_HINT)

    while True:
        try:
            text = input("NEXUS> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not text:
            continue

        if text.lower() in ("exit", "quit", "sair"):
            break

        if text.lower() == "help":
            print(_engine.help())
            continue

        response = _engine.execute(text)
        print(response)

        # If a destructive command needs confirmation, prompt immediately
        if response.requires_confirm:
            try:
                confirm = input("  Confirm? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                confirm = "n"
            if confirm == "y":
                confirmed = response.confirm()
                print(confirmed)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _handle_sigterm(signum, frame):
    _shutdown()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS Runtime")
    parser.add_argument("--live", action="store_true",
                        help="Start in live mode (default: simulation)")
    parser.add_argument("--cmd", metavar="COMMAND",
                        help="Run a single command and exit")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    _boot(live=args.live)

    if args.cmd:
        print(process_command(args.cmd))
        _shutdown()
        return

    try:
        _repl()
    finally:
        _shutdown()


if __name__ == "__main__":
    main()
