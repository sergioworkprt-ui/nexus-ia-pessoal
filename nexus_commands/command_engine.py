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
