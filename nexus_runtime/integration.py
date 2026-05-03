"""
NEXUS Runtime — Integration Layer
Glue layer that initializes and wires all NEXUS modules together.
Provides typed accessors and a unified health check across modules.
Works in simulation mode (mock modules) and live mode (real instances).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .runtime_config import RuntimeConfig, RuntimeMode, PipelineMode


# ---------------------------------------------------------------------------
# Module handles
# ---------------------------------------------------------------------------

@dataclass
class ModuleHandles:
    """References to all live NEXUS module instances."""
    core:             Optional[Any] = None
    auto_evolution:   Optional[Any] = None
    profit_engine:    Optional[Any] = None
    web_intelligence: Optional[Any] = None
    multi_ia:         Optional[Any] = None
    reports:          Optional[Any] = None

    def all_ready(self) -> bool:
        return all([
            self.core is not None,
            self.auto_evolution is not None,
            self.profit_engine is not None,
            self.web_intelligence is not None,
            self.multi_ia is not None,
            self.reports is not None,
        ])

    def ready_map(self) -> Dict[str, bool]:
        return {
            "core":             self.core is not None,
            "auto_evolution":   self.auto_evolution is not None,
            "profit_engine":    self.profit_engine is not None,
            "web_intelligence": self.web_intelligence is not None,
            "multi_ia":         self.multi_ia is not None,
            "reports":          self.reports is not None,
        }


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class NexusIntegration:
    """
    Wires all NEXUS modules into a unified operational layer.

    In SIMULATION mode: uses lightweight mock/stub versions of each module
    so the runtime can operate without any real API connections.

    In LIVE mode: imports and initialises real module instances, wiring
    them to the NexusCore (logger, memory, security).

    Usage:
        integration = NexusIntegration(config)
        integration.setup()
        engine = integration.modules.profit_engine
    """

    def __init__(self, config: RuntimeConfig) -> None:
        self._config  = config
        self._lock    = threading.RLock()
        self._ready   = False
        self.modules  = ModuleHandles()
        self._errors: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self, core: Optional[Any] = None) -> bool:
        """
        Initialise all modules. Returns True if all succeeded.
        core: optional NexusCore instance for live mode wiring.
        """
        with self._lock:
            self._errors.clear()
            if self._config.is_simulation:
                self._setup_simulation(core)
            else:
                self._setup_live(core)
            self._ready = len(self._errors) == 0
        return self._ready

    def teardown(self) -> None:
        """Stop all running module instances."""
        with self._lock:
            for name, mod in [
                ("multi_ia",         self.modules.multi_ia),
                ("web_intelligence", self.modules.web_intelligence),
                ("profit_engine",    self.modules.profit_engine),
                ("auto_evolution",   self.modules.auto_evolution),
                ("reports",          self.modules.reports),
            ]:
                if mod is not None and hasattr(mod, "stop"):
                    try:
                        mod.stop()
                    except Exception:
                        pass
            self._ready = False

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        ready = self.modules.ready_map()
        return {
            "all_ready": all(ready.values()),
            "modules":   ready,
            "errors":    dict(self._errors),
            "mode":      self._config.mode.value,
        }

    # ------------------------------------------------------------------
    # Live setup
    # ------------------------------------------------------------------

    def _setup_live(self, core: Optional[Any]) -> None:
        """Import and start real module instances."""

        # core
        if core is not None:
            self.modules.core = core
        else:
            try:
                from core import get_core
                self.modules.core = get_core()
            except Exception as exc:
                self._errors["core"] = str(exc)

        core_ref = self.modules.core

        # reports (needed early for audit logging)
        try:
            from reports import Reports, ReportsConfig
            r_cfg  = ReportsConfig(
                audit_log_path=self._config.audit_log_path,
                auto_export_json=self._config.reporting.auto_export_json,
                report_export_dir=self._config.reporting.export_dir,
            )
            rep = Reports.from_core(core_ref, r_cfg) if core_ref else Reports(r_cfg)
            rep.start()
            self.modules.reports = rep
        except Exception as exc:
            self._errors["reports"] = str(exc)

        # auto_evolution
        try:
            from auto_evolution import AutoEvolution
            ae = (AutoEvolution.from_core(core_ref)
                  if core_ref else AutoEvolution())
            if self._config.evolution.auto_apply_patches:
                ae.enable_writes()
            ae.start()
            self.modules.auto_evolution = ae
        except Exception as exc:
            self._errors["auto_evolution"] = str(exc)

        # profit_engine
        try:
            from profit_engine import ProfitEngine
            pe = (ProfitEngine.from_core(core_ref)
                  if core_ref else ProfitEngine())
            pe.start()
            self.modules.profit_engine = pe
        except Exception as exc:
            self._errors["profit_engine"] = str(exc)

        # web_intelligence
        try:
            from web_intelligence import WebIntelligence
            wi = (WebIntelligence.from_core(core_ref)
                  if core_ref else WebIntelligence())
            wi.start()
            self.modules.web_intelligence = wi
        except Exception as exc:
            self._errors["web_intelligence"] = str(exc)

        # multi_ia
        try:
            from multi_ia import MultiIA
            mia = (MultiIA.from_core(core_ref)
                   if core_ref else MultiIA())
            mia.start()
            self.modules.multi_ia = mia
        except Exception as exc:
            self._errors["multi_ia"] = str(exc)

    # ------------------------------------------------------------------
    # Simulation setup — lightweight stubs
    # ------------------------------------------------------------------

    def _setup_simulation(self, core: Optional[Any]) -> None:
        """Create minimal stub objects so pipelines can run without real modules."""

        if core is not None:
            self.modules.core = core

        # reports — always use real implementation (no network, no risk)
        try:
            from reports import Reports, ReportsConfig
            r_cfg = ReportsConfig(
                audit_log_path=self._config.audit_log_path,
                auto_export_json=False,
            )
            rep = Reports.from_core(core, r_cfg) if core else Reports(r_cfg)
            rep.start()
            self.modules.reports = rep
        except Exception as exc:
            self._errors["reports"] = str(exc)
            self.modules.reports = _StubModule("reports")

        # multi_ia — use real implementation (pure logic, no network)
        try:
            from multi_ia import MultiIA
            mia = MultiIA.from_core(core) if core else MultiIA()
            mia.start()
            self.modules.multi_ia = mia
        except Exception as exc:
            self._errors["multi_ia"] = str(exc)
            self.modules.multi_ia = _StubModule("multi_ia")

        # Other modules: use stubs in simulation (avoid real IO)
        for name in ("auto_evolution", "profit_engine", "web_intelligence"):
            if name not in self._errors:
                self.modules.__dict__[name] = _StubModule(name)


# ---------------------------------------------------------------------------
# Stub module (simulation mode fallback)
# ---------------------------------------------------------------------------

class _StubModule:
    """Minimal no-op stub satisfying the module interface in simulation mode."""

    def __init__(self, name: str) -> None:
        self._name = name

    def status(self) -> Dict[str, Any]:
        return {"module": self._name, "mode": "stub", "running": False}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"<_StubModule name={self._name!r}>"
