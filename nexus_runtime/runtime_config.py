"""
NEXUS Runtime — Configuration Model
All configuration for pipelines, scheduler intervals, runtime mode,
and module toggles. Supports loading from and saving to a JSON file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RuntimeMode(str, Enum):
    SIMULATION = "simulation"   # dry-run; no real orders, no live fetches
    LIVE       = "live"         # full operation; real execution enabled


class PipelineMode(str, Enum):
    ENABLED   = "enabled"
    DISABLED  = "disabled"
    DRY_RUN   = "dry_run"       # run logic but produce no side-effects


# ---------------------------------------------------------------------------
# Per-pipeline config
# ---------------------------------------------------------------------------

@dataclass
class IntelligenceConfig:
    mode:             PipelineMode = PipelineMode.DRY_RUN
    interval_seconds: int          = 3600        # run every hour
    max_urls:         int          = 10
    sentiment_threshold: float     = 0.3         # alert if |score| > threshold
    enabled_patterns: List[str]    = field(default_factory=lambda: [
        "breakout", "breakdown", "anomaly_price", "anomaly_volume",
        "bullish_divergence", "bearish_divergence",
    ])


@dataclass
class FinancialConfig:
    mode:             PipelineMode = PipelineMode.DRY_RUN
    interval_seconds: int          = 1800        # run every 30 minutes
    max_drawdown_alert: float      = 0.10        # alert at 10% drawdown
    sharpe_alert:       float      = 0.5         # alert if Sharpe < this
    backtest_on_start:  bool       = False


@dataclass
class EvolutionConfig:
    mode:             PipelineMode = PipelineMode.DRY_RUN
    interval_seconds: int          = 86400       # run once per day
    max_patches_per_cycle: int     = 5
    auto_apply_patches:    bool    = False       # False = suggest only
    scan_paths: List[str]          = field(default_factory=lambda: [
        "core", "auto_evolution", "profit_engine",
        "web_intelligence", "multi_ia", "reports", "nexus_runtime",
    ])


@dataclass
class ConsensusConfig:
    mode:             PipelineMode = PipelineMode.ENABLED
    interval_seconds: int          = 7200        # run every 2 hours
    n_agents:         int          = 3
    agreement_alert:  float        = 0.40        # alert if agreement < this
    escalate_on_contradiction: bool = True


@dataclass
class ReportingConfig:
    mode:              PipelineMode = PipelineMode.ENABLED
    interval_seconds:  int          = 3600        # hourly reports
    auto_export_json:  bool         = False
    export_dir:        str          = "reports/exports"
    report_types: List[str]         = field(default_factory=lambda: [
        "financial", "intelligence", "evolution", "multi_ia",
    ])


# ---------------------------------------------------------------------------
# Scheduler config
# ---------------------------------------------------------------------------

@dataclass
class SchedulerConfig:
    enabled:           bool  = True
    tick_interval_s:   float = 1.0    # how often the scheduler thread wakes
    max_concurrent:    int   = 4      # max simultaneous pipeline tasks


# ---------------------------------------------------------------------------
# State manager config
# ---------------------------------------------------------------------------

@dataclass
class StateConfig:
    checkpoint_path:   str  = "data/runtime/checkpoint.json"
    checkpoint_interval_s: int = 300  # save state every 5 minutes
    max_checkpoints:   int  = 5       # rolling window of saved checkpoints


# ---------------------------------------------------------------------------
# Top-level runtime config
# ---------------------------------------------------------------------------

@dataclass
class RuntimeConfig:
    """Master configuration for the NEXUS runtime."""
    mode:         RuntimeMode      = RuntimeMode.SIMULATION
    log_level:    str              = "info"
    audit_log_path: str            = "logs/audit_chain.jsonl"

    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    financial:    FinancialConfig    = field(default_factory=FinancialConfig)
    evolution:    EvolutionConfig    = field(default_factory=EvolutionConfig)
    consensus:    ConsensusConfig    = field(default_factory=ConsensusConfig)
    reporting:    ReportingConfig    = field(default_factory=ReportingConfig)
    scheduler:    SchedulerConfig    = field(default_factory=SchedulerConfig)
    state:        StateConfig        = field(default_factory=StateConfig)

    @property
    def is_live(self) -> bool:
        return self.mode == RuntimeMode.LIVE

    @property
    def is_simulation(self) -> bool:
        return self.mode == RuntimeMode.SIMULATION

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        def _convert(obj: Any) -> Any:
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_convert(i) for i in obj]
            return obj
        return _convert(asdict(self))

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "RuntimeConfig":
        """Load config from a JSON file. Missing keys use defaults."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        cfg = cls()
        mode_val = data.get("mode", cfg.mode.value)
        cfg.mode = RuntimeMode(mode_val)
        cfg.log_level = data.get("log_level", cfg.log_level)
        cfg.audit_log_path = data.get("audit_log_path", cfg.audit_log_path)

        def _apply(target: Any, source: Dict[str, Any]) -> None:
            for key, val in source.items():
                if hasattr(target, key):
                    attr = getattr(target, key)
                    if isinstance(attr, Enum):
                        setattr(target, key, type(attr)(val))
                    elif not isinstance(attr, (dict, list)):
                        setattr(target, key, val)

        for sub, klass in [
            ("intelligence", cfg.intelligence),
            ("financial",    cfg.financial),
            ("evolution",    cfg.evolution),
            ("consensus",    cfg.consensus),
            ("reporting",    cfg.reporting),
            ("scheduler",    cfg.scheduler),
            ("state",        cfg.state),
        ]:
            if sub in data and isinstance(data[sub], dict):
                _apply(klass, data[sub])

        return cfg

    @classmethod
    def simulation(cls) -> "RuntimeConfig":
        """Return a safe simulation-mode config."""
        return cls(mode=RuntimeMode.SIMULATION)

    @classmethod
    def live(cls) -> "RuntimeConfig":
        """Return a live-mode config (operator must explicitly request this)."""
        cfg = cls(mode=RuntimeMode.LIVE)
        cfg.intelligence.mode = PipelineMode.ENABLED
        cfg.financial.mode    = PipelineMode.ENABLED
        cfg.evolution.mode    = PipelineMode.DRY_RUN   # evolution stays cautious
        cfg.consensus.mode    = PipelineMode.ENABLED
        cfg.reporting.mode    = PipelineMode.ENABLED
        return cfg
