"""
NEXUS Command Layer — Command Registry
Stores command definitions: verb/target grammar, parameter schemas,
confirmation requirements, and help text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Grammar constants
# ---------------------------------------------------------------------------

VERBS: Set[str] = {
    "run", "show", "generate", "start", "stop",
    "enable", "disable", "increase", "decrease", "set",
    "pause", "resume", "reset", "list", "check",
    "signal", "analyze", "entry", "exit",
    "evolve", "apply", "rollback", "propose",
    "ibkr", "close", "confirm",
    "gateway",
}

TARGETS: Set[str] = {
    "pipeline", "report", "risk", "module", "audit",
    "state", "evolution", "intelligence", "consensus",
    "financial", "reporting", "scheduler", "limit",
    "status", "history", "checkpoint",
    "signal", "entry", "exit",
    # IBKR targets
    "positions", "balance", "capital", "orders",
    "safe", "mode", "ibkr", "confirm", "close",
    # Gateway targets
    "gateway", "accounts", "pnl", "snapshot", "contract", "login",
}

IBKR_MODES: Set[str] = {"paper", "semi", "auto"}

PIPELINE_NAMES: Set[str] = {
    "intelligence", "financial", "evolution", "consensus", "reporting",
}

MODULE_NAMES: Set[str] = {
    "intelligence", "financial", "evolution", "consensus", "reporting",
    "profit_engine", "web_intelligence", "auto_evolution", "multi_ia", "reports",
}

# Verbs that mutate runtime state and require confirmation in safe mode
DESTRUCTIVE_VERBS: Set[str] = {"stop", "reset", "disable", "decrease", "set"}

# Verbs that read-only and never need confirmation
SAFE_VERBS: Set[str] = {"show", "list", "check", "generate"}


# ---------------------------------------------------------------------------
# Command definition
# ---------------------------------------------------------------------------

@dataclass
class ParamSchema:
    """Schema for a named parameter accepted by a command."""
    name:        str
    type:        str          # "str" | "float" | "int" | "bool" | "percent"
    required:    bool = False
    default:     Any  = None
    description: str  = ""
    choices:     Optional[List[str]] = None


@dataclass
class CommandDef:
    """Definition of a single command variant."""
    verb:          str
    target:        str
    handler_key:   str                  # key used to look up handler in engine
    description:   str
    params:        List[ParamSchema]    = field(default_factory=list)
    requires_confirm: bool             = False
    aliases:       List[str]           = field(default_factory=list)
    examples:      List[str]           = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.verb}:{self.target}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class CommandRegistry:
    """
    Stores all registered CommandDefs; exposes lookup by key and fuzzy search.

    Usage:
        registry = CommandRegistry()
        registry.register(CommandDef(...))
        defn = registry.get("run", "pipeline")
    """

    def __init__(self) -> None:
        self._commands: Dict[str, CommandDef] = {}
        self._alias_map: Dict[str, str] = {}
        self._populate_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, defn: CommandDef) -> None:
        self._commands[defn.key] = defn
        for alias in defn.aliases:
            self._alias_map[alias] = defn.key

    def get(self, verb: str, target: str) -> Optional[CommandDef]:
        key = f"{verb}:{target}"
        if key in self._commands:
            return self._commands[key]
        resolved = self._alias_map.get(key)
        return self._commands.get(resolved) if resolved else None

    def get_by_key(self, key: str) -> Optional[CommandDef]:
        return self._commands.get(key) or self._commands.get(self._alias_map.get(key, ""))

    def all(self) -> List[CommandDef]:
        return list(self._commands.values())

    def for_verb(self, verb: str) -> List[CommandDef]:
        return [d for d in self._commands.values() if d.verb == verb]

    def for_target(self, target: str) -> List[CommandDef]:
        return [d for d in self._commands.values() if d.target == target]

    def search(self, query: str) -> List[CommandDef]:
        """Return commands whose description or key contains the query."""
        q = query.lower()
        return [
            d for d in self._commands.values()
            if q in d.key or q in d.description.lower()
        ]

    def help_text(self, verb: Optional[str] = None, target: Optional[str] = None) -> str:
        """Return formatted help string for a subset or all commands."""
        if verb and target:
            defn = self.get(verb, target)
            if not defn:
                return f"No command found for '{verb} {target}'."
            return self._format_one(defn)

        pool = self.for_verb(verb) if verb else (self.for_target(target) if target else self.all())
        if not pool:
            return "No matching commands."
        return "\n".join(self._format_one(d) for d in pool)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _format_one(self, defn: CommandDef) -> str:
        lines = [f"  {defn.verb} {defn.target}  —  {defn.description}"]
        if defn.params:
            for p in defn.params:
                req = " (required)" if p.required else ""
                lines.append(f"    param: {p.name} [{p.type}]{req}  {p.description}")
        if defn.examples:
            for ex in defn.examples:
                lines.append(f"    e.g.: {ex}")
        if defn.requires_confirm:
            lines.append("    ⚠  requires confirmation in safe mode")
        return "\n".join(lines)

    def _populate_defaults(self) -> None:
        """Register the full built-in command vocabulary."""
        defs: List[CommandDef] = [

            # ── run ──────────────────────────────────────────────────────────
            CommandDef(
                verb="run", target="pipeline",
                handler_key="run_pipeline",
                description="Run one or all pipelines immediately.",
                params=[
                    ParamSchema("name", "str", required=False,
                                choices=list(PIPELINE_NAMES),
                                description="Pipeline name. Omit to run all."),
                ],
                examples=[
                    "run pipeline intelligence",
                    "run pipeline financial",
                    "run pipeline",
                ],
            ),
            CommandDef(
                verb="run", target="intelligence",
                handler_key="run_pipeline",
                description="Run the intelligence pipeline.",
                aliases=["run:intelligence"],
                examples=["run intelligence"],
            ),
            CommandDef(
                verb="run", target="financial",
                handler_key="run_pipeline",
                description="Run the financial pipeline.",
                examples=["run financial"],
            ),
            CommandDef(
                verb="run", target="evolution",
                handler_key="run_pipeline",
                description="Run the evolution pipeline (dry-run by default).",
                examples=["run evolution"],
            ),
            CommandDef(
                verb="run", target="consensus",
                handler_key="run_pipeline",
                description="Run the consensus pipeline.",
                examples=["run consensus"],
            ),
            CommandDef(
                verb="run", target="reporting",
                handler_key="run_pipeline",
                description="Run the reporting pipeline.",
                examples=["run reporting"],
            ),

            # ── show ─────────────────────────────────────────────────────────
            CommandDef(
                verb="show", target="status",
                handler_key="show_status",
                description="Show full runtime status: mode, modules, pipelines.",
                examples=["show status"],
            ),
            CommandDef(
                verb="show", target="pipeline",
                handler_key="show_pipeline",
                description="Show schedule and mode for all pipelines.",
                examples=["show pipeline"],
            ),
            CommandDef(
                verb="show", target="history",
                handler_key="show_history",
                description="Show recent pipeline run history.",
                params=[
                    ParamSchema("limit", "int", default=10,
                                description="Number of entries to show."),
                ],
                examples=["show history", "show history 20"],
            ),
            CommandDef(
                verb="show", target="state",
                handler_key="show_state",
                description="Show runtime state: cycle count, uptime, last cycle.",
                examples=["show state"],
            ),
            CommandDef(
                verb="show", target="audit",
                handler_key="show_audit",
                description="Show last N audit log entries.",
                params=[
                    ParamSchema("limit", "int", default=10,
                                description="Number of entries to show."),
                ],
                examples=["show audit", "show audit 20"],
            ),
            CommandDef(
                verb="show", target="risk",
                handler_key="show_risk",
                description="Show current financial risk limits and alerts.",
                examples=["show risk"],
            ),
            CommandDef(
                verb="show", target="module",
                handler_key="show_module",
                description="Show health and ready status of all modules.",
                params=[
                    ParamSchema("name", "str", required=False,
                                choices=list(MODULE_NAMES),
                                description="Module name. Omit for all."),
                ],
                examples=["show module", "show module profit_engine"],
            ),

            # ── generate ─────────────────────────────────────────────────────
            CommandDef(
                verb="generate", target="report",
                handler_key="generate_report",
                description="Generate and export a consolidated report.",
                params=[
                    ParamSchema("pipeline", "str", required=False,
                                choices=list(PIPELINE_NAMES),
                                description="Scope to one pipeline. Omit for all."),
                    ParamSchema("export", "str", required=False,
                                description="Output path for JSON export."),
                ],
                examples=[
                    "generate report",
                    "generate report financial",
                    "generate report intelligence export reports/live/intel.json",
                ],
            ),
            CommandDef(
                verb="generate", target="audit",
                handler_key="generate_audit",
                description="Verify and export the full audit chain.",
                examples=["generate audit"],
            ),
            CommandDef(
                verb="generate", target="checkpoint",
                handler_key="generate_checkpoint",
                description="Force a state checkpoint now.",
                examples=["generate checkpoint"],
            ),

            # ── start / stop ─────────────────────────────────────────────────
            CommandDef(
                verb="start", target="scheduler",
                handler_key="start_scheduler",
                description="Enable the pipeline scheduler.",
                examples=["start scheduler"],
            ),
            CommandDef(
                verb="stop", target="scheduler",
                handler_key="stop_scheduler",
                description="Disable the pipeline scheduler (manual runs only).",
                requires_confirm=True,
                examples=["stop scheduler"],
            ),
            CommandDef(
                verb="start", target="pipeline",
                handler_key="enable_pipeline",
                description="Enable a pipeline (set mode to enabled).",
                params=[
                    ParamSchema("name", "str", required=True,
                                choices=list(PIPELINE_NAMES),
                                description="Pipeline to enable."),
                ],
                examples=["start pipeline reporting"],
            ),
            CommandDef(
                verb="stop", target="pipeline",
                handler_key="disable_pipeline",
                description="Disable a pipeline.",
                requires_confirm=True,
                params=[
                    ParamSchema("name", "str", required=True,
                                choices=list(PIPELINE_NAMES),
                                description="Pipeline to disable."),
                ],
                examples=["stop pipeline evolution"],
            ),

            # ── enable / disable ─────────────────────────────────────────────
            CommandDef(
                verb="enable", target="module",
                handler_key="enable_module",
                description="Enable a NEXUS module.",
                params=[
                    ParamSchema("name", "str", required=True,
                                choices=list(MODULE_NAMES),
                                description="Module name."),
                ],
                examples=["enable module auto_evolution"],
            ),
            CommandDef(
                verb="disable", target="module",
                handler_key="disable_module",
                description="Disable a NEXUS module.",
                requires_confirm=True,
                params=[
                    ParamSchema("name", "str", required=True,
                                choices=list(MODULE_NAMES),
                                description="Module name."),
                ],
                examples=["disable module web_intelligence"],
            ),
            CommandDef(
                verb="enable", target="evolution",
                handler_key="enable_evolution_writes",
                description="Allow auto-evolution to apply patches (disables dry-run).",
                requires_confirm=True,
                examples=["enable evolution"],
            ),
            CommandDef(
                verb="disable", target="evolution",
                handler_key="disable_evolution_writes",
                description="Set auto-evolution back to dry-run (suggest-only).",
                examples=["disable evolution"],
            ),

            # ── set / increase / decrease ─────────────────────────────────────
            CommandDef(
                verb="set", target="limit",
                handler_key="set_limit",
                description="Set a named runtime limit to an exact value.",
                requires_confirm=True,
                params=[
                    ParamSchema("name", "str", required=True,
                                description="Limit name (e.g. max_drawdown, sharpe_alert, sentiment_threshold)."),
                    ParamSchema("value", "float", required=True,
                                description="New value."),
                ],
                examples=[
                    "set limit max_drawdown 0.15",
                    "set limit sharpe_alert 1.0",
                    "set limit sentiment_threshold 0.5",
                ],
            ),
            CommandDef(
                verb="increase", target="limit",
                handler_key="adjust_limit",
                description="Increase a limit by an amount or percentage.",
                params=[
                    ParamSchema("name", "str", required=True,
                                description="Limit name."),
                    ParamSchema("amount", "float", required=True,
                                description="Amount to add (e.g. 0.05 or '5%')."),
                ],
                examples=[
                    "increase limit max_drawdown 0.05",
                    "increase limit sentiment_threshold 10%",
                ],
            ),
            CommandDef(
                verb="decrease", target="limit",
                handler_key="adjust_limit",
                description="Decrease a limit by an amount or percentage.",
                requires_confirm=True,
                params=[
                    ParamSchema("name", "str", required=True,
                                description="Limit name."),
                    ParamSchema("amount", "float", required=True,
                                description="Amount to subtract (e.g. 0.02 or '2%')."),
                ],
                examples=[
                    "decrease limit max_drawdown 0.02",
                    "decrease limit sharpe_alert 20%",
                ],
            ),
            CommandDef(
                verb="set", target="risk",
                handler_key="set_limit",
                description="Alias for 'set limit' focused on risk parameters.",
                requires_confirm=True,
                params=[
                    ParamSchema("name", "str", required=True,
                                description="Risk param name."),
                    ParamSchema("value", "float", required=True,
                                description="New value."),
                ],
                examples=["set risk max_drawdown 0.12"],
            ),

            # ── pause / resume ───────────────────────────────────────────────
            CommandDef(
                verb="pause", target="pipeline",
                handler_key="pause_runtime",
                description="Pause the runtime scheduler (no new pipelines start).",
                examples=["pause pipeline"],
            ),
            CommandDef(
                verb="resume", target="pipeline",
                handler_key="resume_runtime",
                description="Resume a paused runtime scheduler.",
                examples=["resume pipeline"],
            ),

            # ── reset ────────────────────────────────────────────────────────
            CommandDef(
                verb="reset", target="state",
                handler_key="reset_state",
                description="Reset runtime counters and reload last checkpoint.",
                requires_confirm=True,
                examples=["reset state"],
            ),

            # ── list ─────────────────────────────────────────────────────────
            CommandDef(
                verb="list", target="pipeline",
                handler_key="list_pipelines",
                description="List all pipelines with mode and interval.",
                examples=["list pipeline"],
            ),
            CommandDef(
                verb="list", target="module",
                handler_key="list_modules",
                description="List all modules and their ready status.",
                examples=["list module"],
            ),

            # ── check ────────────────────────────────────────────────────────
            CommandDef(
                verb="check", target="audit",
                handler_key="check_audit",
                description="Verify the audit chain integrity.",
                examples=["check audit"],
            ),
            CommandDef(
                verb="check", target="risk",
                handler_key="show_risk",
                description="Check current risk parameters and alert thresholds.",
                examples=["check risk"],
            ),

            # ── Signal Engine ────────────────────────────────────────────────
            CommandDef(
                verb="signal", target="signal",
                handler_key="signal_generate",
                description="Run the full signal pipeline for a symbol: patterns + sentiment + IA consensus.",
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Trading symbol (e.g. BTC, ETH, AAPL)."),
                ],
                examples=["signal BTC", "signal ETH", "signal AAPL"],
            ),
            CommandDef(
                verb="analyze", target="signal",
                handler_key="signal_generate",
                description="Alias for 'signal <symbol>': full signal analysis.",
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Trading symbol."),
                ],
                examples=["analyze BTC", "analyze ETH"],
            ),
            CommandDef(
                verb="entry", target="entry",
                handler_key="signal_entry",
                description="Evaluate entry readiness for a symbol (pattern + sentiment).",
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Trading symbol."),
                ],
                examples=["entry BTC", "entry AAPL"],
            ),
            CommandDef(
                verb="exit", target="exit",
                handler_key="signal_exit",
                description="Evaluate exit readiness for an open position.",
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Trading symbol."),
                ],
                examples=["exit BTC", "exit ETH"],
            ),
            CommandDef(
                verb="check", target="signal",
                handler_key="signal_generate",
                description="Alias for signal: full analysis for a symbol.",
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Trading symbol."),
                ],
                examples=["check signal BTC"],
            ),
            CommandDef(
                verb="show", target="signal",
                handler_key="signal_history",
                description="Show recent signal history (last N signals).",
                params=[
                    ParamSchema("limit", "int", default=10,
                                description="Number of signals to show."),
                ],
                examples=["show signal", "show signal 20"],
            ),
            CommandDef(
                verb="analyze", target="risk",
                handler_key="signal_risk",
                description="Compute risk metrics for a symbol.",
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Trading symbol."),
                ],
                examples=["analyze risk BTC", "risk BTC"],
            ),

            # ── Evolution Engine ───────────────────────────���─────────────────
            CommandDef(
                verb="evolve", target="evolution",
                handler_key="evolve_run",
                description="Run evaluate_performance + learn_from_signals + propose_adjustments. Returns summary.",
                examples=["evolve", "run evolution", "NEXUS, evolui."],
            ),
            CommandDef(
                verb="show", target="evolution",
                handler_key="evolve_show",
                description="Show pending evolution proposals and last evolution step.",
                aliases=["propose evolution", "show proposals"],
                examples=["show evolution", "mostra propostas de evolução"],
            ),
            CommandDef(
                verb="propose", target="evolution",
                handler_key="evolve_show",
                description="Show pending evolution proposals (alias for 'show evolution').",
                examples=["propose evolution", "show evolution proposals"],
            ),
            CommandDef(
                verb="apply", target="evolution",
                handler_key="evolve_apply",
                description="Apply all pending evolution proposals to the live config.",
                requires_confirm=True,
                examples=["apply evolution", "NEXUS, aplica evolução."],
            ),
            CommandDef(
                verb="rollback", target="evolution",
                handler_key="evolve_rollback",
                description="Rollback the last applied evolution step.",
                requires_confirm=True,
                params=[
                    ParamSchema("n", "int", default=1,
                                description="Number of evolution steps to revert."),
                ],
                examples=["rollback evolution", "rollback evolution 2",
                          "NEXUS, reverte a última evolução."],
            ),
            CommandDef(
                verb="show", target="evolution",
                handler_key="evolve_history",
                description="Show evolution history (last N steps).",
                aliases=["show evolution history"],
                params=[
                    ParamSchema("limit", "int", default=10,
                                description="Number of history entries to show."),
                ],
                examples=["show evolution history", "show evolution history 5"],
            ),

            # ── IBKR Integration ─────────────────────────────────────────────
            CommandDef(
                verb="ibkr", target="status",
                handler_key="ibkr_status",
                description="Show IBKR connection status, mode, balance, positions and risk.",
                aliases=["show:ibkr"],
                examples=["ibkr status", "show ibkr", "NEXUS, estado IBKR."],
            ),
            CommandDef(
                verb="ibkr", target="positions",
                handler_key="ibkr_positions",
                description="List all open IBKR positions with PnL.",
                examples=["ibkr positions", "mostra posições"],
            ),
            CommandDef(
                verb="ibkr", target="balance",
                handler_key="ibkr_balance",
                description="Show IBKR account balance and capital bucket breakdown.",
                examples=["ibkr balance", "ibkr saldo"],
            ),
            CommandDef(
                verb="ibkr", target="orders",
                handler_key="ibkr_orders",
                description="List open and recent IBKR orders.",
                examples=["ibkr orders", "ibkr ordens"],
            ),
            CommandDef(
                verb="ibkr", target="mode",
                handler_key="ibkr_enable_mode",
                description="Set IBKR trading mode: paper | semi | auto.",
                requires_confirm=True,
                params=[
                    ParamSchema("mode", "str", required=True,
                                choices=["paper", "semi", "auto"],
                                description="Trading mode."),
                ],
                examples=[
                    "ibkr mode auto", "ibkr mode semi", "ibkr mode paper",
                    "ibkr enable auto", "NEXUS, ativa modo automático.",
                ],
            ),
            CommandDef(
                verb="enable", target="ibkr",
                handler_key="ibkr_enable_mode",
                description="Enable IBKR trading mode (paper/semi/auto).",
                requires_confirm=True,
                params=[
                    ParamSchema("mode", "str", required=False,
                                choices=["paper", "semi", "auto"],
                                description="Mode to activate. Defaults to paper."),
                ],
                examples=[
                    "enable auto", "enable semi", "enable paper",
                    "enable ibkr auto", "NEXUS, ativa modo automático.",
                ],
            ),
            CommandDef(
                verb="ibkr", target="capital",
                handler_key="ibkr_set_capital",
                description="Set the hard capital limit NEXUS may deploy (euros/USD).",
                requires_confirm=True,
                params=[
                    ParamSchema("limit", "float", required=True,
                                description="Maximum capital in account currency."),
                ],
                examples=[
                    "ibkr set capital 1000", "ibkr capital 800",
                    "NEXUS, usa no máximo 800 euros.",
                ],
            ),
            CommandDef(
                verb="set", target="capital",
                handler_key="ibkr_set_capital",
                description="Alias for 'ibkr capital LIMIT' — set the IBKR capital limit.",
                requires_confirm=True,
                params=[
                    ParamSchema("limit", "float", required=True,
                                description="Maximum capital in account currency."),
                ],
                examples=["set capital 1000", "set capital 500"],
            ),
            CommandDef(
                verb="ibkr", target="close",
                handler_key="ibkr_close",
                description="Close an open IBKR position for a symbol.",
                requires_confirm=True,
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Symbol to close (e.g. BTC, ETH, AAPL)."),
                ],
                examples=[
                    "ibkr close BTC", "ibkr close ETH",
                    "NEXUS, fecha BTC.", "fecha posição BTC",
                ],
            ),
            CommandDef(
                verb="close", target="ibkr",
                handler_key="ibkr_close",
                description="Alias for 'ibkr close SYMBOL'.",
                requires_confirm=True,
                params=[
                    ParamSchema("symbol", "str", required=True,
                                description="Symbol to close."),
                ],
                examples=["close BTC", "close ETH"],
            ),
            CommandDef(
                verb="ibkr", target="safe",
                handler_key="ibkr_safe_mode",
                description="Enter IBKR safe mode — block all new trades immediately.",
                requires_confirm=False,
                examples=[
                    "ibkr safe mode", "ibkr safe",
                    "NEXUS, entra em safe mode.", "safe mode",
                ],
            ),
            CommandDef(
                verb="ibkr", target="resume",
                handler_key="ibkr_resume",
                description="Exit IBKR safe mode and resume normal trading operations.",
                requires_confirm=True,
                examples=[
                    "ibkr resume", "resume ibkr",
                    "NEXUS, retoma operações.", "sair de safe mode",
                ],
            ),
            CommandDef(
                verb="ibkr", target="confirm",
                handler_key="ibkr_confirm",
                description="Confirm a pending semi-mode order by order ID.",
                params=[
                    ParamSchema("order_id", "str", required=True,
                                description="Order ID to confirm."),
                ],
                examples=["ibkr confirm ORD-001", "confirmar ordem ORD-001"],
            ),

            # ── Gateway (Render CPG) ─────────────────────────────────────────
            CommandDef(
                verb="gateway", target="status",
                handler_key="gateway_status",
                description="Show IBKR gateway connection status and authentication state.",
                aliases=["show:gateway"],
                examples=["gateway status", "gateway", "show gateway"],
            ),
            CommandDef(
                verb="gateway", target="login",
                handler_key="gateway_login",
                description="Attempt gateway authentication; returns browser URL if manual login required.",
                examples=["gateway login", "gateway auth", "login gateway"],
            ),
            CommandDef(
                verb="gateway", target="accounts",
                handler_key="gateway_accounts",
                description="List all IBKR accounts available via the gateway.",
                examples=["gateway accounts", "gateway contas"],
            ),
            CommandDef(
                verb="gateway", target="positions",
                handler_key="gateway_positions",
                description="Fetch live open positions directly from the Render gateway.",
                examples=["gateway positions", "gateway posições"],
            ),
            CommandDef(
                verb="gateway", target="pnl",
                handler_key="gateway_pnl",
                description="Fetch partitioned P&L (realized, unrealized, daily) from the gateway.",
                examples=["gateway pnl", "gateway lucro", "gateway resultado"],
            ),
            CommandDef(
                verb="gateway", target="snapshot",
                handler_key="gateway_snapshot",
                description="Get market data snapshot for an IBKR contract ID (conid).",
                params=[
                    ParamSchema("conid", "int", required=True,
                                description="IBKR contract ID (e.g. 265598 for AAPL)."),
                ],
                examples=["gateway snapshot 265598", "gateway snapshot 8314"],
            ),
            CommandDef(
                verb="gateway", target="contract",
                handler_key="gateway_contract",
                description="Get full contract details for an IBKR contract ID (conid).",
                params=[
                    ParamSchema("conid", "int", required=True,
                                description="IBKR contract ID."),
                ],
                examples=["gateway contract 265598", "gateway contract 8314"],
            ),
        ]

        for d in defs:
            self.register(d)
