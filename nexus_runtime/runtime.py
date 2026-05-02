"""
NEXUS Runtime — Main Orchestrator
Lifecycle manager and event loop for the entire NEXUS system.
Wires event bus, scheduler, state manager, integration, and all pipelines.
Supports simulation mode (safe, no live IO) and live mode (full operation).
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .events import Event, EventBus, EventType
from .integration import NexusIntegration
from .pipelines import (
    BasePipeline,
    ConsensusPipeline,
    EvolutionPipeline,
    FinancialPipeline,
    IntelligencePipeline,
    PipelineRunResult,
    PipelineStatus,
    ReportingPipeline,
)
from .runtime_config import PipelineMode, RuntimeConfig, RuntimeMode
from .scheduler import Scheduler, TaskResult
from .state_manager import StateManager


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

class NexusRuntime:
    """
    Top-level orchestrator for the NEXUS system.

    Responsibilities:
    - Boot all modules via NexusIntegration
    - Register all pipelines with the Scheduler
    - Start EventBus and begin dispatching events
    - Maintain persistent state via StateManager (checkpoints / rollback)
    - Provide a unified status/health endpoint
    - Support graceful start, stop, pause, and resume

    Simulation mode:
        Stubs out live modules; multi_ia and reports run normally.
        No real network requests, no real orders.

    Live mode:
        Attempts to import and start all real NEXUS modules.
        Profit engine and web_intelligence run with real data.

    Usage (standalone):
        runtime = NexusRuntime()
        runtime.start()
        # ... runs pipelines on schedule ...
        runtime.stop()

    Usage (with NexusCore):
        from core import get_core
        runtime = NexusRuntime.from_core(get_core())
        runtime.start()
    """

    VERSION = "1.0.0"

    def __init__(self, config: Optional[RuntimeConfig] = None) -> None:
        self._config        = config or RuntimeConfig.simulation()
        self._running       = False
        self._paused        = False
        self._lock          = threading.RLock()
        self._pipeline_lock = threading.Lock()

        # Sub-systems
        self.bus            = EventBus()
        self.scheduler      = Scheduler(
            tick_interval=self._config.scheduler.tick_interval_s,
            max_concurrent=self._config.scheduler.max_concurrent,
            on_task_done=self._on_task_done,
            on_task_missed=self._on_task_missed,
        )
        self.state          = StateManager(
            checkpoint_path=self._config.state.checkpoint_path,
            max_checkpoints=self._config.state.max_checkpoints,
        )
        self.integration    = NexusIntegration(self._config)

        # Pipeline instances (built after integration.setup())
        self._pipelines:    Dict[str, BasePipeline] = {}

        # Pipeline run history
        self._run_history:  List[PipelineRunResult] = []
        self._max_history   = 100

        # Core handles (set via from_core)
        self._logger   = None
        self._memory   = None
        self._security = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_core(
        cls,
        core:   Any,
        config: Optional[RuntimeConfig] = None,
    ) -> "NexusRuntime":
        """Wire to a running NexusCore instance."""
        runtime = cls(config)
        runtime._logger   = core.logger
        runtime._memory   = core.memory
        runtime._security = core.security
        return runtime

    @classmethod
    def simulation(cls) -> "NexusRuntime":
        return cls(RuntimeConfig.simulation())

    @classmethod
    def live(cls) -> "NexusRuntime":
        return cls(RuntimeConfig.live())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, core: Optional[Any] = None) -> bool:
        """
        Boot all subsystems and begin scheduled pipeline execution.
        Returns True if all modules initialised successfully.
        """
        with self._lock:
            if self._running:
                return True

        self._log("runtime", f"NEXUS Runtime v{self.VERSION} starting "
                  f"[mode={self._config.mode.value}]")

        # 1. Restore or init state
        restored = self.state.restore_or_init(self._config.mode.value)
        if restored:
            self._log("runtime", "State restored from checkpoint.")
        else:
            self._log("runtime", "Starting with fresh state.")

        # 2. Start event bus
        self.bus.start()
        self._register_core_handlers()

        # 3. Set up module integration
        ok = self.integration.setup(core or getattr(self, "_core_ref", None))
        for name, ready in self.integration.modules.ready_map().items():
            self.state.mark_module_ready(name) if ready else None
            self.bus.emit(
                EventType.MODULE_READY if ready else EventType.MODULE_FAILED,
                source="runtime.integration",
                data={"module": name},
            )

        # 4. Build pipelines
        self._build_pipelines()

        # 5. Register pipelines with scheduler
        if self._config.scheduler.enabled:
            self._register_pipeline_tasks()

        # 6. Register checkpoint task
        self.scheduler.schedule(
            name="checkpoint",
            callback=self._do_checkpoint,
            interval_seconds=self._config.state.checkpoint_interval_s,
            description="Periodic state checkpoint",
            tags=["system"],
        )

        # 7. Start scheduler
        self.scheduler.start()

        self._running = True
        self.bus.emit(EventType.RUNTIME_STARTED, source="runtime",
                      data={"mode": self._config.mode.value, "version": self.VERSION})
        self._log("runtime", "NEXUS Runtime started.", mode=self._config.mode.value)
        return ok

    def stop(self) -> None:
        """Graceful shutdown: stop scheduler, drain events, save state."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        self._log("runtime", "NEXUS Runtime stopping…")
        self.bus.emit(EventType.RUNTIME_STOPPED, source="runtime")

        self.scheduler.stop(wait=5.0)
        self._do_checkpoint()
        self.integration.teardown()
        self.bus.stop(drain_timeout=3.0)
        self._log("runtime", "NEXUS Runtime stopped.")

    def pause(self) -> None:
        """Pause pipeline scheduling (event bus keeps running)."""
        with self._lock:
            self._paused = True
        self.bus.emit(EventType.RUNTIME_PAUSED, source="runtime")
        self._log("runtime", "Runtime paused.")

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self.bus.emit(EventType.RUNTIME_RESUMED, source="runtime")
        self._log("runtime", "Runtime resumed.")

    # ------------------------------------------------------------------
    # Manual pipeline execution
    # ------------------------------------------------------------------

    def run_pipeline(self, name: str) -> Optional[PipelineRunResult]:
        """Run a pipeline by name immediately, outside the scheduler."""
        pipeline = self._pipelines.get(name)
        if pipeline is None:
            self._log("runtime", f"Unknown pipeline: {name}", level="warning")
            return None
        return self._execute_pipeline(pipeline)

    def run_all_pipelines(self) -> List[PipelineRunResult]:
        """Run all enabled pipelines immediately (useful for on-demand cycles)."""
        results = []
        for name, pipeline in self._pipelines.items():
            result = self._execute_pipeline(pipeline)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Status & introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        state = self.state.current_state_dict()
        return {
            "version":     self.VERSION,
            "running":     self._running,
            "paused":      self._paused,
            "mode":        self._config.mode.value,
            "integration": self.integration.health(),
            "scheduler":   self.scheduler.stats(),
            "event_bus":   self.bus.stats(),
            "state":       state,
            "pipelines":   list(self._pipelines.keys()),
        }

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._run_history[-limit:]]

    def pipeline_tasks(self) -> List[Dict[str, Any]]:
        return self.scheduler.list_tasks()

    def audit_chain_ok(self) -> bool:
        rep = self.integration.modules.reports
        if rep and hasattr(rep, "verify_audit_chain"):
            ok, _ = rep.verify_audit_chain()
            return ok
        return True

    # ------------------------------------------------------------------
    # Internal: pipeline build & registration
    # ------------------------------------------------------------------

    def _build_pipelines(self) -> None:
        mods = self.integration.modules
        cfg  = self._config
        bus  = self.bus
        self._pipelines = {
            "intelligence": IntelligencePipeline(mods, cfg, bus),
            "financial":    FinancialPipeline(mods, cfg, bus),
            "evolution":    EvolutionPipeline(mods, cfg, bus),
            "consensus":    ConsensusPipeline(mods, cfg, bus),
            "reporting":    ReportingPipeline(mods, cfg, bus),
        }

    def _register_pipeline_tasks(self) -> None:
        intervals = {
            "intelligence": self._config.intelligence.interval_seconds,
            "financial":    self._config.financial.interval_seconds,
            "evolution":    self._config.evolution.interval_seconds,
            "consensus":    self._config.consensus.interval_seconds,
            "reporting":    self._config.reporting.interval_seconds,
        }
        pipeline_modes = {
            "intelligence": self._config.intelligence.mode,
            "financial":    self._config.financial.mode,
            "evolution":    self._config.evolution.mode,
            "consensus":    self._config.consensus.mode,
            "reporting":    self._config.reporting.mode,
        }
        for name, pipeline in self._pipelines.items():
            if pipeline_modes[name] == PipelineMode.DISABLED:
                continue
            self.scheduler.schedule(
                name=f"pipeline_{name}",
                callback=lambda p=pipeline: self._execute_pipeline(p),
                interval_seconds=intervals[name],
                run_immediately=False,
                description=f"{name.title()} pipeline",
                tags=["pipeline"],
            )

    # ------------------------------------------------------------------
    # Internal: execution
    # ------------------------------------------------------------------

    def _execute_pipeline(self, pipeline: BasePipeline) -> PipelineRunResult:
        if self._paused:
            result = PipelineRunResult(pipeline=pipeline.name,
                                       status=PipelineStatus.SKIPPED)
            result.errors.append("Runtime is paused.")
            return result

        with self._pipeline_lock:
            pass  # serialise concurrent manual calls if needed

        result = pipeline.run()

        with self._lock:
            self.state.record_pipeline_run(pipeline.name, result.ok)
            self.state.increment_cycle()
            self._run_history.append(result)
            if len(self._run_history) > self._max_history:
                self._run_history.pop(0)

        self._log(
            "runtime",
            f"Pipeline '{pipeline.name}' finished: "
            f"status={result.status.value}, ms={result.duration_ms:.0f}",
            level="info" if result.ok else "warning",
        )
        return result

    # ------------------------------------------------------------------
    # Internal: event handlers
    # ------------------------------------------------------------------

    def _register_core_handlers(self) -> None:
        self.bus.subscribe(self._on_risk_breach,    EventType.RISK_BREACH,          description="risk_breach_handler")
        self.bus.subscribe(self._on_kill_switch,    EventType.KILL_SWITCH_TRIGGERED, description="kill_switch_handler")
        self.bus.subscribe(self._on_escalation,     EventType.CONSENSUS_ESCALATED,  description="consensus_escalation_handler")
        self.bus.subscribe(self._on_security_event, EventType.SECURITY_VIOLATION,   description="security_violation_handler")

    def _on_risk_breach(self, event: Event) -> None:
        self._log("runtime", f"RISK BREACH event: {event.data}", level="warning")
        rep = self.integration.modules.reports
        if rep and hasattr(rep, "log_violation"):
            rep.log_violation(
                actor="profit_engine",
                code="RISK_BREACH",
                detail=str(event.data),
            )

    def _on_kill_switch(self, event: Event) -> None:
        self._log("runtime", "KILL SWITCH triggered — pausing runtime.", level="warning")
        self.pause()

    def _on_escalation(self, event: Event) -> None:
        self._log("runtime", f"Consensus escalation: {event.data}", level="warning")
        if self._security and hasattr(self._security, "audit"):
            try:
                self._security.audit(
                    actor="runtime.consensus",
                    action="escalate",
                    target="consensus_result",
                    outcome=str(event.data.get("escalation_reason", "")),
                )
            except Exception:
                pass

    def _on_security_event(self, event: Event) -> None:
        self._log("runtime", f"Security violation: {event.data}", level="warning")

    # ------------------------------------------------------------------
    # Internal: scheduler callbacks
    # ------------------------------------------------------------------

    def _on_task_done(self, result: TaskResult) -> None:
        if not result.ok:
            self._log("runtime",
                      f"Task '{result.task_name}' failed: {result.error}", level="warning")

    def _on_task_missed(self, task: Any) -> None:
        self.bus.emit(EventType.TASK_MISSED, source="scheduler",
                      data={"task_name": task.name})

    def _do_checkpoint(self) -> None:
        try:
            cp = self.state.save_checkpoint()
            self.bus.emit(EventType.CHECKPOINT_SAVED, source="runtime",
                          data={"checkpoint_id": cp.checkpoint_id,
                                "cycle": cp.cycle_count})
        except Exception as exc:
            self._log("runtime", f"Checkpoint failed: {exc}", level="warning")

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log(self, module: str, message: str, level: str = "info", **kw: Any) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(module, message, **kw)
