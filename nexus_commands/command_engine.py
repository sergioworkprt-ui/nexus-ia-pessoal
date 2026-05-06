"""
NEXUS Command Layer — Command Engine
Bridges ParsedIntent → NexusRuntime actions.

Responsibilities:
- Accept natural-language text or a pre-parsed ParsedIntent
- Dispatch to the appropriate runtime handler
- Handle safe-mode confirmation gates
- Return a structured CommandResponse
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .command_registry import CommandRegistry, DESTRUCTIVE_VERBS
from .command_parser import CommandParser, ParsedIntent, ParseError


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

@dataclass
class CommandResponse:
    """Result returned from CommandEngine.execute()."""
    ok:       bool
    command:  str                    # canonical "verb target"
    message:  str                    # human-readable summary
    data:     Dict[str, Any]         = field(default_factory=dict)
    warnings: List[str]              = field(default_factory=list)
    requires_confirm: bool           = False   # True = needs .confirm() call
    _confirm_fn: Optional[Callable[[], "CommandResponse"]] = field(
        default=None, repr=False, compare=False
    )

    def confirm(self) -> "CommandResponse":
        """Execute a previously-blocked destructive command after user confirmation."""
        if self._confirm_fn:
            return self._confirm_fn()
        return CommandResponse(ok=False, command=self.command,
                               message="Nothing to confirm.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok":      self.ok,
            "command": self.command,
            "message": self.message,
            "data":    self.data,
            "warnings": self.warnings,
            "requires_confirm": self.requires_confirm,
        }

    def __str__(self) -> str:
        status = "OK" if self.ok else "FAIL"
        lines  = [f"[{status}] {self.command}  —  {self.message}"]
        if self.data:
            for k, v in list(self.data.items())[:8]:
                vstr = json.dumps(v, default=str)[:120] if not isinstance(v, str) else v[:120]
                lines.append(f"  {k}: {vstr}")
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  ⚠  {w}")
        if self.requires_confirm:
            lines.append("  ➜  Call .confirm() to proceed with this destructive operation.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Limit map — maps canonical limit names → (config_object_path, attribute)
# ---------------------------------------------------------------------------

_LIMIT_MAP: Dict[str, tuple] = {
    # (pipeline_config_attr_on_RuntimeConfig, field_name)
    "max_drawdown_alert":    ("financial",     "max_drawdown_alert"),
    "sharpe_alert":          ("financial",     "sharpe_alert"),
    "sentiment_threshold":   ("intelligence",  "sentiment_threshold"),
    "max_urls":              ("intelligence",  "max_urls"),
    "max_patches_per_cycle": ("evolution",     "max_patches_per_cycle"),
    "n_agents":              ("consensus",     "n_agents"),
    "agreement_alert":       ("consensus",     "agreement_alert"),
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CommandEngine:
    """
    Natural-language command processor wired to a NexusRuntime instance.

    Usage:
        engine = CommandEngine(runtime)
        resp = engine.execute("run pipeline intelligence")
        print(resp)

        # Destructive command in safe mode:
        resp = engine.execute("stop scheduler")
        if resp.requires_confirm:
            resp = resp.confirm()

    safe_mode (default True):
        When True, destructive commands (stop, disable, decrease, set, reset)
        return a CommandResponse with requires_confirm=True and do NOT execute
        immediately. Call .confirm() to proceed.
    """

    def __init__(
        self,
        runtime: Any,                    # NexusRuntime
        safe_mode: bool = True,
        registry: Optional[CommandRegistry] = None,
    ) -> None:
        self._runtime   = runtime
        self._safe_mode = safe_mode
        self._registry  = registry or CommandRegistry()
        self._parser    = CommandParser(self._registry)
        self._history:  List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def safe_mode(self) -> bool:
        return self._safe_mode

    @safe_mode.setter
    def safe_mode(self, value: bool) -> None:
        self._safe_mode = value

    def execute(self, text: str) -> CommandResponse:
        """Parse and execute a natural-language command string."""
        intent, err = self._parser.parse(text)
        if err:
            resp = CommandResponse(
                ok=False,
                command=text,
                message=err.reason,
                warnings=[f"Did you mean: {s}" for s in err.suggestions[:3]],
            )
            self._record(text, resp)
            return resp
        return self._dispatch(intent)

    def execute_intent(self, intent: ParsedIntent) -> CommandResponse:
        """Execute a pre-parsed ParsedIntent directly."""
        return self._dispatch(intent)

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    def help(self, query: str = "") -> str:
        """Return help text for all commands or a specific verb/target."""
        if not query:
            return self._registry.help_text()
        parts = query.strip().lower().split()
        verb   = parts[0] if parts else None
        target = parts[1] if len(parts) > 1 else None
        return self._registry.help_text(verb=verb, target=target)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, intent: ParsedIntent) -> CommandResponse:
        if not intent.matched:
            return CommandResponse(
                ok=False,
                command=f"{intent.verb} {intent.target}",
                message=(
                    f"No handler registered for '{intent.verb} {intent.target}'. "
                    "Try 'help' for available commands."
                ),
                warnings=intent.warnings,
            )

        handler_key = intent.matched.handler_key

        # Safe-mode gate for destructive commands
        if self._safe_mode and intent.matched.requires_confirm:
            return self._gate(intent)

        handler = self._handler_map().get(handler_key)
        if not handler:
            return CommandResponse(
                ok=False,
                command=str(intent),
                message=f"Internal: no handler for key '{handler_key}'.",
            )

        try:
            resp = handler(intent)
        except Exception as exc:
            resp = CommandResponse(
                ok=False,
                command=str(intent),
                message=f"Execution error: {exc}",
            )

        resp.warnings.extend(intent.warnings)
        self._record(intent.raw, resp)
        return resp

    def _gate(self, intent: ParsedIntent) -> CommandResponse:
        """Return a pending response that requires explicit .confirm()."""
        def _do() -> CommandResponse:
            handler = self._handler_map().get(intent.matched.handler_key)
            if not handler:
                return CommandResponse(ok=False, command=str(intent),
                                       message="No handler found after confirm.")
            resp = handler(intent)
            self._record(intent.raw, resp)
            return resp

        return CommandResponse(
            ok=True,
            command=str(intent),
            message=(
                f"'{intent.verb} {intent.target}' is a destructive operation. "
                "Call .confirm() to proceed or discard this response to cancel."
            ),
            requires_confirm=True,
            _confirm_fn=_do,
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handler_map(self) -> Dict[str, Callable[[ParsedIntent], CommandResponse]]:
        return {
            "run_pipeline":          self._h_run_pipeline,
            "show_status":           self._h_show_status,
            "show_pipeline":         self._h_show_pipeline,
            "show_history":          self._h_show_history,
            "show_state":            self._h_show_state,
            "show_audit":            self._h_show_audit,
            "show_risk":             self._h_show_risk,
            "show_module":           self._h_show_module,
            "generate_report":       self._h_generate_report,
            "generate_audit":        self._h_generate_audit,
            "generate_checkpoint":   self._h_generate_checkpoint,
            "start_scheduler":       self._h_start_scheduler,
            "stop_scheduler":        self._h_stop_scheduler,
            "enable_pipeline":       self._h_enable_pipeline,
            "disable_pipeline":      self._h_disable_pipeline,
            "enable_module":         self._h_enable_module,
            "disable_module":        self._h_disable_module,
            "enable_evolution_writes":  self._h_enable_evolution_writes,
            "disable_evolution_writes": self._h_disable_evolution_writes,
            "set_limit":             self._h_set_limit,
            "adjust_limit":          self._h_adjust_limit,
            "pause_runtime":         self._h_pause_runtime,
            "resume_runtime":        self._h_resume_runtime,
            "reset_state":           self._h_reset_state,
            "list_pipelines":        self._h_show_pipeline,
            "list_modules":          self._h_show_module,
            "check_audit":           self._h_generate_audit,
            # Signal Engine
            "signal_generate":       self._h_signal_generate,
            "signal_entry":          self._h_signal_entry,
            "signal_exit":           self._h_signal_exit,
            "signal_risk":           self._h_signal_risk,
            "signal_history":        self._h_signal_history,
            # Evolution Engine
            "evolve_run":            self._h_evolve_run,
            "evolve_show":           self._h_evolve_show,
            "evolve_apply":          self._h_evolve_apply,
            "evolve_rollback":       self._h_evolve_rollback,
            "evolve_history":        self._h_evolve_history,
            # IBKR Integration
            "ibkr_status":           self._h_ibkr_status,
            "ibkr_positions":        self._h_ibkr_positions,
            "ibkr_balance":          self._h_ibkr_balance,
            "ibkr_orders":           self._h_ibkr_orders,
            "ibkr_enable_mode":      self._h_ibkr_enable_mode,
            "ibkr_set_capital":      self._h_ibkr_set_capital,
            "ibkr_close":            self._h_ibkr_close,
            "ibkr_safe_mode":        self._h_ibkr_safe_mode,
            "ibkr_resume":           self._h_ibkr_resume,
            "ibkr_confirm":          self._h_ibkr_confirm,
            # Gateway (Render CPG)
            "gateway_status":        self._h_gateway_status,
            "gateway_login":         self._h_gateway_login,
            "gateway_accounts":      self._h_gateway_accounts,
            "gateway_positions":     self._h_gateway_positions,
            "gateway_pnl":           self._h_gateway_pnl,
            "gateway_snapshot":      self._h_gateway_snapshot,
            "gateway_contract":      self._h_gateway_contract,
        }

    # ── run ──────────────────────────────────────────────────────────────

    def _h_run_pipeline(self, intent: ParsedIntent) -> CommandResponse:
        name = intent.params.get("name")
        rt   = self._runtime

        if name:
            result = rt.run_pipeline(name)
            if result is None:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Pipeline '{name}' not found.")
            status = result.status.value if hasattr(result.status, "value") else str(result.status)
            dur    = getattr(result, "duration_ms", 0)
            return CommandResponse(
                ok=result.ok,
                command=str(intent),
                message=f"Pipeline '{name}' finished: {status} ({dur:.0f} ms)",
                data=result.to_dict() if hasattr(result, "to_dict") else vars(result),
            )
        else:
            results = rt.run_all_pipelines()
            n_ok    = sum(1 for r in results if r.ok)
            summary = {r.pipeline: r.status.value for r in results}
            return CommandResponse(
                ok=n_ok == len(results),
                command=str(intent),
                message=f"All pipelines ran: {n_ok}/{len(results)} succeeded.",
                data={"results": summary},
            )

    # ── show ─────────────────────────────────────────────────────────────

    def _h_show_status(self, intent: ParsedIntent) -> CommandResponse:
        status = self._runtime.status()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Runtime status retrieved.",
            data=status,
        )

    def _h_show_pipeline(self, intent: ParsedIntent) -> CommandResponse:
        tasks = self._runtime.pipeline_tasks()
        cfg   = self._runtime._config
        info: Dict[str, Any] = {}
        for name in ("intelligence", "financial", "evolution", "consensus", "reporting"):
            pcfg = getattr(cfg, name, None)
            info[name] = {
                "mode":     pcfg.mode.value if pcfg else "?",
                "interval": getattr(pcfg, "interval_seconds", 0),
            }
        return CommandResponse(
            ok=True, command=str(intent),
            message="Pipeline configuration retrieved.",
            data={"pipelines": info, "scheduled_tasks": tasks},
        )

    def _h_show_history(self, intent: ParsedIntent) -> CommandResponse:
        limit   = int(intent.params.get("limit", 10))
        entries = self._runtime.history(limit=limit)
        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Last {len(entries)} pipeline runs.",
            data={"history": entries},
        )

    def _h_show_state(self, intent: ParsedIntent) -> CommandResponse:
        state = self._runtime.state.current_state_dict()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Runtime state retrieved.",
            data=state,
        )

    def _h_show_audit(self, intent: ParsedIntent) -> CommandResponse:
        limit   = int(intent.params.get("limit", 10))
        entries = self._runtime.history(limit=limit)
        chain_ok = self._runtime.audit_chain_ok()
        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Audit chain {'VALID' if chain_ok else 'INVALID'}. Last {len(entries)} entries shown.",
            data={"chain_ok": chain_ok, "entries": entries},
        )

    def _h_show_risk(self, intent: ParsedIntent) -> CommandResponse:
        cfg = self._runtime._config.financial
        data = {
            "max_drawdown_alert": cfg.max_drawdown_alert,
            "sharpe_alert":       cfg.sharpe_alert,
        }
        icfg = self._runtime._config.intelligence
        data["sentiment_threshold"] = icfg.sentiment_threshold
        return CommandResponse(
            ok=True, command=str(intent),
            message="Current risk / alert thresholds.",
            data=data,
        )

    def _h_show_module(self, intent: ParsedIntent) -> CommandResponse:
        name   = intent.params.get("name")
        health = self._runtime._integration.health()
        modules = health.get("modules", {})
        errors  = health.get("errors", {})
        if name:
            ready = modules.get(name)
            if ready is None:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Module '{name}' not found.")
            return CommandResponse(
                ok=True, command=str(intent),
                message=f"Module '{name}': {'ready' if ready else 'degraded'}.",
                data={"name": name, "ready": ready, "error": errors.get(name)},
            )
        return CommandResponse(
            ok=True, command=str(intent),
            message="Module health overview.",
            data={"modules": modules, "errors": errors},
        )

    # ── generate ─────────────────────────────────────────────────────────

    def _h_generate_report(self, intent: ParsedIntent) -> CommandResponse:
        pipeline = intent.params.get("pipeline") or intent.params.get("name")
        export   = intent.params.get("export")
        rt       = self._runtime

        if pipeline:
            results = [rt.run_pipeline(pipeline)]
        else:
            results = rt.run_all_pipelines()

        summary = {
            r.pipeline: {
                "status":      r.status.value if hasattr(r.status, "value") else str(r.status),
                "duration_ms": getattr(r, "duration_ms", 0),
                "errors":      getattr(r, "errors", []),
            }
            for r in results if r
        }

        if export:
            from pathlib import Path
            out = Path(export)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(
                {"generated_at": _now(), "results": summary}, indent=2, default=str
            ))

        n_ok = sum(1 for r in results if r and r.ok)
        return CommandResponse(
            ok=n_ok == len(results),
            command=str(intent),
            message=f"Report generated: {n_ok}/{len(results)} pipelines OK."
                    + (f" Exported to {export}." if export else ""),
            data={"results": summary},
        )

    def _h_generate_audit(self, intent: ParsedIntent) -> CommandResponse:
        ok = self._runtime.audit_chain_ok()
        return CommandResponse(
            ok=ok,
            command=str(intent),
            message=f"Audit chain integrity: {'VALID ✓' if ok else 'INVALID ✗'}",
            data={"chain_ok": ok},
        )

    def _h_generate_checkpoint(self, intent: ParsedIntent) -> CommandResponse:
        self._runtime._do_checkpoint()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Checkpoint saved.",
        )

    # ── scheduler ─────────────────────────────────────────────────────────

    def _h_start_scheduler(self, intent: ParsedIntent) -> CommandResponse:
        self._runtime.resume()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Scheduler enabled — pipelines will run on schedule.",
        )

    def _h_stop_scheduler(self, intent: ParsedIntent) -> CommandResponse:
        self._runtime.pause()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Scheduler paused — no new pipeline runs will be triggered automatically.",
        )

    # ── pipeline enable / disable ──────────────────────────────────────────

    def _h_enable_pipeline(self, intent: ParsedIntent) -> CommandResponse:
        from nexus_runtime import PipelineMode
        name = intent.params.get("name")
        if not name:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Pipeline name required.")
        cfg = getattr(self._runtime._config, name, None)
        if cfg is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"No config found for pipeline '{name}'.")
        cfg.mode = PipelineMode.ENABLED
        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Pipeline '{name}' set to ENABLED.",
            data={"pipeline": name, "mode": "enabled"},
        )

    def _h_disable_pipeline(self, intent: ParsedIntent) -> CommandResponse:
        from nexus_runtime import PipelineMode
        name = intent.params.get("name")
        if not name:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Pipeline name required.")
        cfg = getattr(self._runtime._config, name, None)
        if cfg is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"No config found for pipeline '{name}'.")
        cfg.mode = PipelineMode.DISABLED
        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Pipeline '{name}' DISABLED.",
            data={"pipeline": name, "mode": "disabled"},
        )

    # ── module enable / disable ────────────────────────────────────────────

    def _h_enable_module(self, intent: ParsedIntent) -> CommandResponse:
        name = intent.params.get("name")
        if not name:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Module name required.")
        mod = getattr(self._runtime._integration.modules, name, None)
        if mod is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Module '{name}' not found or not loaded.")
        if hasattr(mod, "start"):
            try:
                mod.start()
            except Exception as e:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Failed to start module '{name}': {e}")
        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Module '{name}' enabled.",
            data={"module": name},
        )

    def _h_disable_module(self, intent: ParsedIntent) -> CommandResponse:
        name = intent.params.get("name")
        if not name:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Module name required.")
        mod = getattr(self._runtime._integration.modules, name, None)
        if mod is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Module '{name}' not found or not loaded.")
        if hasattr(mod, "stop"):
            try:
                mod.stop()
            except Exception as e:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Failed to stop module '{name}': {e}")
        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Module '{name}' disabled.",
            data={"module": name},
        )

    # ── evolution writes ──────────────────────────────────────────────────

    def _h_enable_evolution_writes(self, intent: ParsedIntent) -> CommandResponse:
        from nexus_runtime import PipelineMode
        self._runtime._config.evolution.auto_apply_patches = True
        self._runtime._config.evolution.mode = PipelineMode.ENABLED
        ae = self._runtime._integration.modules.auto_evolution
        if ae and hasattr(ae, "enable_writes"):
            ae.enable_writes()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Auto-evolution write mode ENABLED — patches will be applied.",
            warnings=["Evolution may modify source files. Monitor carefully."],
            data={"auto_apply_patches": True},
        )

    def _h_disable_evolution_writes(self, intent: ParsedIntent) -> CommandResponse:
        from nexus_runtime import PipelineMode
        self._runtime._config.evolution.auto_apply_patches = False
        self._runtime._config.evolution.mode = PipelineMode.DRY_RUN
        return CommandResponse(
            ok=True, command=str(intent),
            message="Auto-evolution set to DRY-RUN — suggestions only, no file writes.",
            data={"auto_apply_patches": False},
        )

    # ── limits ────────────────────────────────────────────────────────────

    def _h_set_limit(self, intent: ParsedIntent) -> CommandResponse:
        name  = intent.params.get("name")
        value = intent.params.get("value")
        if name is None or value is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Both 'name' and 'value' are required for set limit.")
        return self._apply_limit(intent, name, value)

    def _h_adjust_limit(self, intent: ParsedIntent) -> CommandResponse:
        name   = intent.params.get("name")
        amount = intent.params.get("amount")
        if name is None or amount is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Both 'name' and 'amount' are required.")

        mapping = _LIMIT_MAP.get(name)
        if not mapping:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Unknown limit '{name}'.")

        cfg_name, attr = mapping
        cfg = getattr(self._runtime._config, cfg_name, None)
        if cfg is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Config section '{cfg_name}' not found.")

        current = getattr(cfg, attr, None)
        if current is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Attribute '{attr}' not found in {cfg_name} config.")

        delta   = float(amount)
        new_val = current + delta if intent.verb == "increase" else current - delta
        new_val = round(new_val, 6)

        return self._apply_limit(intent, name, new_val)

    def _apply_limit(
        self, intent: ParsedIntent, name: str, value: float
    ) -> CommandResponse:
        mapping = _LIMIT_MAP.get(name)
        if not mapping:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Unknown limit '{name}'. "
                                           f"Valid: {', '.join(_LIMIT_MAP.keys())}")

        cfg_name, attr = mapping
        cfg = getattr(self._runtime._config, cfg_name, None)
        if cfg is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Config section '{cfg_name}' not found.")

        old_val = getattr(cfg, attr, None)
        setattr(cfg, attr, value)

        return CommandResponse(
            ok=True, command=str(intent),
            message=f"Limit '{name}' updated: {old_val} → {value}",
            data={"limit": name, "old": old_val, "new": value, "section": cfg_name},
        )

    # ── pause / resume ────────────────────────────────────────────────────

    def _h_pause_runtime(self, intent: ParsedIntent) -> CommandResponse:
        self._runtime.pause()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Runtime paused — scheduler suspended.",
        )

    def _h_resume_runtime(self, intent: ParsedIntent) -> CommandResponse:
        self._runtime.resume()
        return CommandResponse(
            ok=True, command=str(intent),
            message="Runtime resumed — scheduler active.",
        )

    # ── reset ──────────────────────────────────────────────────────────────

    def _h_reset_state(self, intent: ParsedIntent) -> CommandResponse:
        try:
            self._runtime.state.restore_or_init()
            return CommandResponse(
                ok=True, command=str(intent),
                message="Runtime state reset to last checkpoint.",
            )
        except Exception as exc:
            return CommandResponse(
                ok=False, command=str(intent),
                message=f"State reset failed: {exc}",
            )

    # ------------------------------------------------------------------
    # Signal Engine handlers
    # ------------------------------------------------------------------

    def _get_signal_engine(self):
        """Build a SignalEngine from the current runtime."""
        from nexus_runtime.signal_engine import SignalEngine
        return SignalEngine(
            modules=self._runtime.integration.modules,
            config=self._runtime._config,
            bus=self._runtime.bus,
            reports=getattr(self._runtime.integration.modules, "reports", None),
        )

    def _h_signal_generate(self, intent: ParsedIntent) -> CommandResponse:
        symbol = intent.params.get("symbol", "").upper()
        if not symbol:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Symbol required. Example: signal BTC")
        try:
            se     = self._get_signal_engine()
            result = se.generate_signal(symbol)
            d      = result.to_dict()
            side   = d.get("side", "hold").upper()
            strength = d.get("strength", 0.0)
            risk_score = d.get("risk", {}).get("risk_score", 0.0) if d.get("risk") else 0.0
            entry_flag = d.get("entry", {}).get("should_enter", False) if d.get("entry") else False
            msg = (
                f"{symbol}: {side}  strength={strength:.2f}  risk={risk_score:.2f}"
                + ("  → ENTER" if entry_flag else "  → HOLD")
            )
            return CommandResponse(ok=True, command=str(intent), message=msg, data=d,
                                   warnings=[w for e in result.errors for w in [f"⚠ {e}"]])
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Signal generation failed: {exc}")

    def _h_signal_entry(self, intent: ParsedIntent) -> CommandResponse:
        symbol = intent.params.get("symbol", "").upper()
        if not symbol:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Symbol required. Example: entry BTC")
        try:
            se     = self._get_signal_engine()
            entry  = se.evaluate_entry(symbol)
            d      = entry.to_dict()
            side   = d.get("side", "hold").upper()
            conf   = d.get("confidence", 0.0)
            go     = "✓ ENTER" if d.get("should_enter") else "✗ WAIT"
            msg    = f"{symbol}: {go}  side={side}  confidence={conf:.2f}"
            return CommandResponse(ok=True, command=str(intent), message=msg, data=d)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Entry evaluation failed: {exc}")

    def _h_signal_exit(self, intent: ParsedIntent) -> CommandResponse:
        symbol = intent.params.get("symbol", "").upper()
        if not symbol:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Symbol required. Example: exit BTC")
        try:
            se    = self._get_signal_engine()
            ev    = se.evaluate_exit(symbol)
            d     = ev.to_dict()
            go    = "✓ EXIT" if d.get("should_exit") else "✗ HOLD"
            urg   = d.get("urgency", "low")
            msg   = f"{symbol}: {go}  urgency={urg}  pnl_estimate={d.get('pnl_estimate', 0):.4f}"
            return CommandResponse(ok=True, command=str(intent), message=msg, data=d)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Exit evaluation failed: {exc}")

    def _h_signal_risk(self, intent: ParsedIntent) -> CommandResponse:
        symbol = intent.params.get("symbol", "").upper()
        if not symbol:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Symbol required. Example: analyze risk BTC")
        try:
            se   = self._get_signal_engine()
            risk = se.compute_risk(symbol)
            d    = risk.to_dict()
            msg  = (
                f"{symbol}: risk_score={d['risk_score']:.2f}  "
                f"vol={d['volatility']:.2%}  drawdown={d['drawdown_pct']:.2%}  "
                f"pos_size={d['position_size']:.2%}"
            )
            return CommandResponse(ok=True, command=str(intent), message=msg, data=d,
                                   warnings=risk.alerts)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Risk computation failed: {exc}")

    def _h_signal_history(self, intent: ParsedIntent) -> CommandResponse:
        limit = int(intent.params.get("limit", 10))
        try:
            se      = self._get_signal_engine()
            entries = se.history(limit=limit)
            return CommandResponse(
                ok=True, command=str(intent),
                message=f"Last {len(entries)} signals in engine history.",
                data={"signals": entries},
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Signal history failed: {exc}")

    # ------------------------------------------------------------------
    # Evolution Engine handlers
    # ------------------------------------------------------------------

    def _get_evolution_engine(self):
        from nexus_runtime.evolution_engine import EvolutionEngine
        rt = self._runtime
        return EvolutionEngine(
            modules=rt.integration.modules,
            config=rt._config,
            bus=getattr(rt, "bus", None),
            reports=getattr(rt.integration.modules, "reports", None),
        )

    def _h_evolve_run(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ee     = self._get_evolution_engine()
            perf   = ee.evaluate_performance()
            learn  = ee.learn_from_signals()
            props  = ee.propose_adjustments(perf, learn)
            msg    = (
                f"Evolution cycle done. Signals={perf.signal_count}  "
                f"hit_rate={perf.hit_rate:.1%}  vol={perf.volatility_regime}  "
                f"proposals={len(props)}"
            )
            return CommandResponse(
                ok=True, command=str(intent), message=msg,
                data={
                    "performance":  perf.to_dict(),
                    "learning":     learn.to_dict(),
                    "proposals":    [p.to_dict() for p in props],
                },
                warnings=learn.notes,
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Evolution run failed: {exc}")

    def _h_evolve_show(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ee     = self._get_evolution_engine()
            status = ee.status()
            props  = [p.to_dict() for p in ee.pending_proposals()]
            if not props:
                msg = "No pending proposals. Run 'evolve' first to generate proposals."
            else:
                lines = []
                for p in props:
                    sign  = "+" if p["change_pct"] >= 0 else ""
                    lines.append(
                        f"  [{p['impact_level'].upper()}] {p['parameter']}: "
                        f"{p['current_value']} → {p['proposed_value']} "
                        f"({sign}{p['change_pct']:.1f}%)"
                    )
                msg = f"{len(props)} pending proposal(s):\n" + "\n".join(lines)
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data={"pending_proposals": props, "status": status})
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Evolution show failed: {exc}")

    def _h_evolve_apply(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ee    = self._get_evolution_engine()
            props = ee.pending_proposals()
            if not props:
                return CommandResponse(
                    ok=False, command=str(intent),
                    message="No pending proposals to apply. Run 'evolve' first.",
                )
            result = ee.apply_adjustments(props)
            msg    = (
                f"Evolution applied: {result.applied_count} change(s)  "
                f"skipped={result.skipped_count}  evo_id={result.evo_id}"
            )
            return CommandResponse(
                ok=True, command=str(intent), message=msg,
                data=result.to_dict(),
                warnings=result.errors,
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Evolution apply failed: {exc}")

    def _h_evolve_rollback(self, intent: ParsedIntent) -> CommandResponse:
        n = int(intent.params.get("n", 1))
        try:
            ee     = self._get_evolution_engine()
            result = ee.rollback(last_n=n)
            if result.errors:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Rollback failed: {result.errors[0]}")
            msg = (
                f"Rolled back {result.rolled_back} evolution step(s).  "
                f"evo_ids={result.evo_ids}"
            )
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data=result.to_dict())
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Evolution rollback failed: {exc}")

    def _h_evolve_history(self, intent: ParsedIntent) -> CommandResponse:
        limit = int(intent.params.get("limit", 10))
        try:
            ee      = self._get_evolution_engine()
            entries = ee.history(limit=limit)
            lines   = []
            for e in entries:
                ts     = str(e.get("ts", ""))[:19].replace("T", " ")
                action = e.get("action", "?")
                evo_id = e.get("evo_id", "?")[:8]
                n_prop = len(e.get("proposals", []))
                lines.append(f"  {ts}  [{action}]  id={evo_id}  proposals={n_prop}")
            msg = f"Last {len(entries)} evolution log entries:\n" + "\n".join(lines)
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data={"history": entries})
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Evolution history failed: {exc}")

    # ------------------------------------------------------------------
    # IBKR Integration handlers
    # ------------------------------------------------------------------

    def _get_ibkr(self):
        """Return the IBKRIntegration from the runtime, or raise."""
        ibkr = getattr(self._runtime, "ibkr", None)
        if ibkr is None:
            raise RuntimeError(
                "IBKRIntegration not attached to runtime. "
                "Start the runtime with ibkr enabled or call runtime.setup_ibkr()."
            )
        return ibkr

    def _h_ibkr_status(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ibkr   = self._get_ibkr()
            status = ibkr.status()
            mode   = status.get("mode", "?")
            connected = status.get("connected", False)
            bal    = status.get("balance", 0.0)
            n_pos  = status.get("positions", 0)
            n_pend = status.get("pending_orders", 0)
            safe   = status.get("risk", {}).get("in_safe_mode", False)
            msg = (
                f"IBKR {'connected' if connected else 'disconnected'}  "
                f"mode={mode}  balance={bal:.2f}  "
                f"positions={n_pos}  pending={n_pend}"
                + ("  [SAFE MODE]" if safe else "")
            )
            return CommandResponse(ok=True, command=str(intent), message=msg, data=status)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR status failed: {exc}")

    def _h_ibkr_positions(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ibkr = self._get_ibkr()
            positions = ibkr.get_positions()
            if not positions:
                return CommandResponse(ok=True, command=str(intent),
                                       message="No open IBKR positions.", data={"positions": []})
            lines = []
            for p in positions:
                d = p.to_dict() if hasattr(p, "to_dict") else p
                pnl = d.get("pnl", 0.0)
                sign = "+" if pnl >= 0 else ""
                lines.append(
                    f"  {d['symbol']}  {d['side'].upper()}  size={d['size']}  "
                    f"entry={d['entry_price']:.4f}  pnl={sign}{pnl:.2f}"
                )
            msg = f"{len(positions)} open position(s):\n" + "\n".join(lines)
            return CommandResponse(
                ok=True, command=str(intent), message=msg,
                data={"positions": [p.to_dict() if hasattr(p, "to_dict") else p for p in positions]},
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR positions failed: {exc}")

    def _h_ibkr_balance(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ibkr    = self._get_ibkr()
            balance = ibkr.get_balance()
            cap     = ibkr._cm.status() if ibkr._cm else {}
            risk    = ibkr._rm.status() if ibkr._rm else {}
            data = {
                "balance":       balance,
                "capital":       cap,
                "risk":          risk,
            }
            avail    = cap.get("available_capital", balance)
            deployed = cap.get("total_deployed", 0.0)
            msg = (
                f"Balance={balance:.2f}  available={avail:.2f}  "
                f"deployed={deployed:.2f}  "
                f"daily_risk_used={risk.get('daily_risk_used_pct', 0.0):.2%}"
            )
            return CommandResponse(ok=True, command=str(intent), message=msg, data=data)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR balance failed: {exc}")

    def _h_ibkr_orders(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ibkr    = self._get_ibkr()
            orders  = ibkr.get_open_orders()
            if not orders:
                return CommandResponse(ok=True, command=str(intent),
                                       message="No open IBKR orders.", data={"orders": []})
            lines = []
            for o in orders:
                d = o if isinstance(o, dict) else vars(o)
                lines.append(
                    f"  {d.get('order_id', '?')}  {d.get('symbol', '?')}  "
                    f"{d.get('side', '?').upper()}  size={d.get('size', 0)}  "
                    f"status={d.get('status', '?')}"
                )
            msg = f"{len(orders)} order(s):\n" + "\n".join(lines)
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data={"orders": orders})
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR orders failed: {exc}")

    def _h_ibkr_enable_mode(self, intent: ParsedIntent) -> CommandResponse:
        mode = intent.params.get("mode", "paper")
        if mode not in ("paper", "semi", "auto"):
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Invalid mode '{mode}'. Choose: paper | semi | auto")
        try:
            ibkr = self._get_ibkr()
            ibkr.set_mode(mode)
            warnings = []
            if mode == "auto":
                warnings.append("AUTO mode: orders execute immediately within risk limits.")
            elif mode == "semi":
                warnings.append("SEMI mode: orders require 'ibkr confirm ORDER_ID' before execution.")
            return CommandResponse(
                ok=True, command=str(intent),
                message=f"IBKR mode set to {mode.upper()}.",
                data={"mode": mode},
                warnings=warnings,
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR set mode failed: {exc}")

    def _h_ibkr_set_capital(self, intent: ParsedIntent) -> CommandResponse:
        limit = intent.params.get("limit") or intent.params.get("value") or intent.params.get("amount")
        if limit is None:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Capital limit required. Example: ibkr capital 1000")
        limit = float(limit)
        if limit <= 0:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Capital limit must be positive.")
        try:
            ibkr = self._get_ibkr()
            old  = ibkr._cm._state.user_capital_limit if ibkr._cm else 0
            ibkr._cm.increase_limit(limit)
            return CommandResponse(
                ok=True, command=str(intent),
                message=f"IBKR capital limit updated: {old:.2f} → {limit:.2f}",
                data={"old_limit": old, "new_limit": limit},
                warnings=[
                    "This is a hard cap. NEXUS will never deploy more than this amount.",
                    "Use 'ibkr balance' to verify the new deployment limit.",
                ],
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR set capital failed: {exc}")

    def _h_ibkr_close(self, intent: ParsedIntent) -> CommandResponse:
        symbol = (intent.params.get("symbol") or "").upper()
        if not symbol:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Symbol required. Example: ibkr close BTC")
        try:
            ibkr   = self._get_ibkr()
            result = ibkr.close_position(symbol)
            d      = result.to_dict() if hasattr(result, "to_dict") else result
            pnl    = d.get("pnl", 0.0) if isinstance(d, dict) else 0.0
            status = d.get("status", "?") if isinstance(d, dict) else "?"
            sign   = "+" if pnl >= 0 else ""
            msg    = f"Position {symbol} closed. status={status}  pnl={sign}{pnl:.2f}"
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data=d if isinstance(d, dict) else {"result": str(d)})
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR close {symbol} failed: {exc}")

    def _h_ibkr_safe_mode(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ibkr = self._get_ibkr()
            ibkr.enter_safe_mode("Manual safe mode activated via command.")
            return CommandResponse(
                ok=True, command=str(intent),
                message="IBKR safe mode ACTIVATED — all new trades blocked.",
                warnings=[
                    "No new positions will be opened until safe mode is lifted.",
                    "Use 'ibkr resume' to exit safe mode.",
                ],
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR safe mode failed: {exc}")

    def _h_ibkr_resume(self, intent: ParsedIntent) -> CommandResponse:
        try:
            ibkr = self._get_ibkr()
            ibkr.exit_safe_mode()
            return CommandResponse(
                ok=True, command=str(intent),
                message="IBKR safe mode DEACTIVATED — trading operations resumed.",
                data={"mode": ibkr.mode()},
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR resume failed: {exc}")

    def _h_ibkr_confirm(self, intent: ParsedIntent) -> CommandResponse:
        order_id = intent.params.get("order_id", "").upper()
        if not order_id:
            return CommandResponse(ok=False, command=str(intent),
                                   message="Order ID required. Example: ibkr confirm ORD-001")
        try:
            ibkr   = self._get_ibkr()
            result = ibkr.confirm_pending(order_id)
            d      = result.to_dict() if hasattr(result, "to_dict") else {}
            status = d.get("status", "?")
            symbol = d.get("symbol", "?")
            msg    = f"Order {order_id} ({symbol}) confirmed: status={status}"
            return CommandResponse(ok=True, command=str(intent), message=msg, data=d)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"IBKR confirm failed: {exc}")

    # ------------------------------------------------------------------
    # Gateway (Render CPG) handlers
    # ------------------------------------------------------------------

    def _get_gateway(self):
        """
        Return an IBKRGateway singleton stored on the runtime, or build one
        from config on first call.  Raises RuntimeError if gateway is disabled.
        """
        from nexus_runtime.ibkr_gateway import IBKRGateway, RENDER_URL

        gw = getattr(self._runtime, "_gateway", None)
        if gw is None:
            ibkr_cfg = getattr(self._runtime._config, "ibkr", None)
            base_url = getattr(ibkr_cfg, "cpg_base_url", RENDER_URL) if ibkr_cfg else RENDER_URL
            verify_ssl = getattr(ibkr_cfg, "cpg_verify_ssl", True) if ibkr_cfg else True
            timeout_s  = getattr(ibkr_cfg, "cpg_timeout_s",  15)   if ibkr_cfg else 15
            acct_id    = getattr(ibkr_cfg, "cpg_account_id", "")    if ibkr_cfg else ""
            paper      = (getattr(ibkr_cfg, "mode", "paper") == "paper") if ibkr_cfg else True

            gw = IBKRGateway(
                base_url    = base_url,
                account_id  = acct_id,
                verify_ssl  = verify_ssl,
                timeout_s   = timeout_s,
                paper       = paper,
            )
            self._runtime._gateway = gw
        return gw

    def _h_gateway_status(self, intent: ParsedIntent) -> CommandResponse:
        try:
            gw   = self._get_gateway()
            data = gw.status()
            auth = data.get("authenticated", False)
            msg  = (
                f"Gateway {'authenticated' if auth else 'NOT authenticated'}  "
                f"connected={data.get('connected', False)}  "
                f"url={data.get('base_url', '?')}"
            )
            if not auth:
                msg += f"  → Open {data.get('browser_url', '')} in a browser to log in."
            return CommandResponse(ok=True, command=str(intent), message=msg, data=data)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway status failed: {exc}")

    def _h_gateway_login(self, intent: ParsedIntent) -> CommandResponse:
        try:
            gw   = self._get_gateway()
            data = gw.login()
            auth = data.get("authenticated", False)
            msg  = data.get("message", "")
            if not auth:
                msg += f"  Browser URL: {data.get('browser_url', '')}"
            warnings = [] if auth else [
                "You must authenticate via browser before the gateway will accept API calls.",
                f"Open this URL and log in with your IBKR credentials: {data.get('browser_url', '')}",
            ]
            return CommandResponse(
                ok=auth, command=str(intent), message=msg,
                data=data, warnings=warnings,
            )
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway login failed: {exc}")

    def _h_gateway_accounts(self, intent: ParsedIntent) -> CommandResponse:
        try:
            gw       = self._get_gateway()
            accounts = gw.get_accounts()
            if not accounts:
                return CommandResponse(ok=True, command=str(intent),
                                       message="No accounts found (not authenticated?).",
                                       data={"accounts": []})
            lines = [f"  {a.get('accountId', a.get('id', '?'))}  "
                     f"type={a.get('type', '?')}  "
                     f"currency={a.get('currency', '?')}"
                     for a in accounts]
            msg = f"{len(accounts)} account(s):\n" + "\n".join(lines)
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data={"accounts": accounts})
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway accounts failed: {exc}")

    def _h_gateway_positions(self, intent: ParsedIntent) -> CommandResponse:
        try:
            gw        = self._get_gateway()
            positions = gw.get_positions()
            if not positions:
                return CommandResponse(ok=True, command=str(intent),
                                       message="No open positions via gateway.",
                                       data={"positions": []})
            lines = []
            for p in positions:
                size = p.get("position", p.get("pos", "?"))
                pnl  = p.get("unrealizedPnl", 0.0)
                sign = "+" if (pnl or 0) >= 0 else ""
                lines.append(
                    f"  {p.get('ticker', p.get('symbol', '?'))}  "
                    f"size={size}  "
                    f"avg={p.get('avgCost', 0):.4f}  "
                    f"mktVal={p.get('mktValue', 0):.2f}  "
                    f"pnl={sign}{pnl:.2f}"
                )
            msg = f"{len(positions)} open position(s):\n" + "\n".join(lines)
            return CommandResponse(ok=True, command=str(intent), message=msg,
                                   data={"positions": positions})
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway positions failed: {exc}")

    def _h_gateway_pnl(self, intent: ParsedIntent) -> CommandResponse:
        try:
            gw  = self._get_gateway()
            pnl = gw.get_pnl()
            if "error" in pnl:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Gateway P&L error: {pnl['error']}")
            upnl = pnl.get("upnl", {})
            lines = []
            for acct, vals in upnl.items():
                if isinstance(vals, dict):
                    nl  = vals.get("nl",  vals.get("NL",  0.0))
                    dpl = vals.get("dpl", vals.get("DPL", 0.0))
                    upl = vals.get("upl", vals.get("UPL", 0.0))
                    lines.append(
                        f"  {acct}  NLV={nl:.2f}  daily_pnl={dpl:+.2f}  unrealized={upl:+.2f}"
                    )
            msg = (f"{len(upnl)} account(s) P&L:\n" + "\n".join(lines)) if lines else "P&L data received."
            return CommandResponse(ok=True, command=str(intent), message=msg, data=pnl)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway P&L failed: {exc}")

    def _h_gateway_snapshot(self, intent: ParsedIntent) -> CommandResponse:
        conid_raw = intent.params.get("conid")
        if not conid_raw:
            return CommandResponse(ok=False, command=str(intent),
                                   message="conid required. Example: gateway snapshot 265598")
        try:
            conid = int(conid_raw)
            gw    = self._get_gateway()
            snap  = gw.get_snapshot(conid)
            if "error" in snap:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Snapshot error: {snap['error']}", data=snap)
            symbol    = snap.get("symbol", str(conid))
            last      = snap.get("last_price", "?")
            bid       = snap.get("bid", "?")
            ask       = snap.get("ask", "?")
            vol       = snap.get("volume", "?")
            msg = (
                f"{symbol} (conid={conid})  "
                f"last={last}  bid={bid}  ask={ask}  volume={vol}"
            )
            return CommandResponse(ok=True, command=str(intent), message=msg, data=snap)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway snapshot failed: {exc}")

    def _h_gateway_contract(self, intent: ParsedIntent) -> CommandResponse:
        conid_raw = intent.params.get("conid")
        if not conid_raw:
            return CommandResponse(ok=False, command=str(intent),
                                   message="conid required. Example: gateway contract 265598")
        try:
            conid = int(conid_raw)
            gw    = self._get_gateway()
            info  = gw.get_contract_info(conid)
            if "error" in info:
                return CommandResponse(ok=False, command=str(intent),
                                       message=f"Contract info error: {info['error']}", data=info)
            symbol   = info.get("symbol", info.get("ticker", str(conid)))
            sec_type = info.get("secType", info.get("instrumentType", "?"))
            exchange = info.get("exchange", info.get("listingExchange", "?"))
            currency = info.get("currency", "?")
            msg = (
                f"{symbol} (conid={conid})  "
                f"type={sec_type}  exchange={exchange}  currency={currency}"
            )
            return CommandResponse(ok=True, command=str(intent), message=msg, data=info)
        except Exception as exc:
            return CommandResponse(ok=False, command=str(intent),
                                   message=f"Gateway contract info failed: {exc}")

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _record(self, raw: str, resp: CommandResponse) -> None:
        self._history.append({
            "ts":      _now(),
            "raw":     raw,
            "command": resp.command,
            "ok":      resp.ok,
            "message": resp.message,
        })
        if len(self._history) > 200:
            self._history = self._history[-200:]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
