"""
NEXUS Runtime — Pipeline Definitions
Daily, hourly, and on-demand pipelines for each subsystem.
Each pipeline:
  - receives module handles + config
  - produces a PipelineRunResult with structured data
  - emits events on the EventBus
  - writes to the Reports audit log
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .events import Event, EventBus, EventType
from .runtime_config import (
    RuntimeConfig, PipelineMode,
    ConsensusConfig, EvolutionConfig,
    FinancialConfig, IntelligenceConfig, ReportingConfig,
)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineStatus(str, Enum):
    SUCCESS  = "success"
    PARTIAL  = "partial"      # ran but with non-critical errors
    FAILED   = "failed"
    SKIPPED  = "skipped"      # mode = DISABLED


@dataclass
class PipelineRunResult:
    """Outcome of a single pipeline execution."""
    run_id:       str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    pipeline:     str = ""
    status:       PipelineStatus = PipelineStatus.SUCCESS
    started_at:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at:  Optional[str] = None
    duration_ms:  float = 0.0
    data:         Dict[str, Any] = field(default_factory=dict)
    errors:       List[str] = field(default_factory=list)
    report_id:    Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in (PipelineStatus.SUCCESS, PipelineStatus.PARTIAL)

    def finish(self, t0: float) -> "PipelineRunResult":
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.duration_ms = (time.perf_counter() - t0) * 1000
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id":      self.run_id,
            "pipeline":    self.pipeline,
            "status":      self.status.value,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 2),
            "errors":      self.errors,
            "report_id":   self.report_id,
            "data_keys":   list(self.data.keys()),
        }


# ---------------------------------------------------------------------------
# Base pipeline
# ---------------------------------------------------------------------------

class BasePipeline:
    """
    Abstract base for all NEXUS pipelines.
    Subclasses implement _execute() and call super().run() which handles
    timing, error capture, event emission, and audit logging.
    """

    name: str = "base"

    def __init__(
        self,
        modules: Any,
        config:  RuntimeConfig,
        bus:     Optional[EventBus] = None,
    ) -> None:
        self._modules = modules
        self._config  = config
        self._bus     = bus

    def run(self) -> PipelineRunResult:
        t0     = time.perf_counter()
        result = PipelineRunResult(pipeline=self.name)

        self._emit(EventType.PIPELINE_STARTED, {"pipeline": self.name})

        try:
            self._execute(result)
            if result.status == PipelineStatus.SUCCESS and result.errors:
                result.status = PipelineStatus.PARTIAL
        except Exception as exc:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Unhandled exception: {exc}")

        result.finish(t0)
        event_type = (EventType.PIPELINE_COMPLETED if result.ok
                      else EventType.PIPELINE_FAILED)
        self._emit(event_type, result.to_dict())
        return result

    def _execute(self, result: PipelineRunResult) -> None:
        raise NotImplementedError

    def _emit(self, event_type: EventType, data: Optional[Dict[str, Any]] = None) -> None:
        if self._bus:
            self._bus.emit(event_type, source=f"pipeline.{self.name}", data=data or {})

    def _reports(self) -> Any:
        return self._modules.reports

    def _audit(self, action: str, detail: str = "") -> None:
        rep = self._reports()
        if rep and hasattr(rep, "log_event"):
            try:
                from reports import AuditEventType, AuditSeverity
                rep.log_event(
                    AuditEventType.PIPELINE_STARTED,
                    actor=f"pipeline.{self.name}",
                    action=action,
                    outcome=detail,
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Intelligence pipeline
# ---------------------------------------------------------------------------

class IntelligencePipeline(BasePipeline):
    """
    Fetches market intelligence, detects patterns, scores sentiment.
    In simulation mode: uses status() from stub / last known state.
    """

    name = "intelligence"

    def _execute(self, result: PipelineRunResult) -> None:
        cfg: IntelligenceConfig = self._config.intelligence
        if cfg.mode == PipelineMode.DISABLED:
            result.status = PipelineStatus.SKIPPED
            return

        wi = self._modules.web_intelligence
        rep = self._reports()

        # Collect status / run scan if possible
        try:
            if hasattr(wi, "scan") and cfg.mode == PipelineMode.ENABLED:
                wi.scan()
            wi_status = wi.status() if hasattr(wi, "status") else {}
        except Exception as exc:
            result.errors.append(f"web_intelligence.status: {exc}")
            wi_status = {}

        result.data["web_intelligence_status"] = wi_status

        # Emit pattern events
        patterns = wi_status.get("pattern_detector", {}).get("detected_patterns", [])
        for p in patterns:
            pt = p.get("type", "")
            if pt in ("anomaly_price", "anomaly_volume", "breakdown"):
                self._emit(EventType.ANOMALY_DETECTED, p)
            else:
                self._emit(EventType.PATTERN_DETECTED, p)

        # Sentiment alert
        sentiment = wi_status.get("news_analyzer", {})
        score = float(sentiment.get("average_score", 0.0))
        if abs(score) >= cfg.sentiment_threshold:
            self._emit(EventType.SENTIMENT_ALERT, {
                "score": score, "threshold": cfg.sentiment_threshold
            })

        # Signal Engine — generate signals for symbols with detected patterns
        try:
            from .signal_engine import SignalEngine
            sig_engine = SignalEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            symbols = list({
                p.get("symbol", "") for p in patterns if p.get("symbol")
            })
            signals = []
            for sym in symbols[:5]:   # cap at 5 per cycle to limit latency
                sig = sig_engine.generate_signal(sym)
                signals.append(sig.to_dict())
            if symbols and not signals:
                # No symbol-tagged patterns — run on a default watchlist symbol
                sig = sig_engine.generate_signal(symbols[0] if symbols else "NEXUS")
                signals.append(sig.to_dict())
            result.data["signals"] = signals
        except Exception as exc:
            result.errors.append(f"signal_engine: {exc}")

        # Generate report
        if rep:
            try:
                report = rep.intelligence_from_dict(wi_status)
                result.report_id = report.report_id
            except Exception as exc:
                result.errors.append(f"report generation: {exc}")

        self._audit("intelligence_pipeline", f"patterns={len(patterns)}, score={score:.3f}")


# ---------------------------------------------------------------------------
# Financial pipeline
# ---------------------------------------------------------------------------

class FinancialPipeline(BasePipeline):
    """
    Evaluates portfolio, risk, and PnL from the profit engine.
    In DRY_RUN / SIMULATION: reads status only; no orders placed.
    """

    name = "financial"

    def _execute(self, result: PipelineRunResult) -> None:
        cfg: FinancialConfig = self._config.financial
        if cfg.mode == PipelineMode.DISABLED:
            result.status = PipelineStatus.SKIPPED
            return

        pe  = self._modules.profit_engine
        rep = self._reports()

        try:
            pe_status = pe.status() if hasattr(pe, "status") else {}
        except Exception as exc:
            result.errors.append(f"profit_engine.status: {exc}")
            pe_status = {}

        result.data["profit_engine_status"] = pe_status

        # Risk breach check
        risk = pe_status.get("risk", {})
        drawdown = float(risk.get("current_drawdown", 0.0))
        if drawdown >= cfg.max_drawdown_alert:
            self._emit(EventType.DRAWDOWN_ALERT, {
                "drawdown": drawdown, "threshold": cfg.max_drawdown_alert
            })

        # Backtest on demand (simulation safe)
        if cfg.backtest_on_start and hasattr(pe, "backtest"):
            try:
                bt_result = pe.backtest()
                result.data["backtest"] = (bt_result.summary()
                                           if hasattr(bt_result, "summary")
                                           else str(bt_result))
            except Exception as exc:
                result.errors.append(f"backtest: {exc}")

        # Signal Engine — compute risk metrics for open positions
        try:
            from .signal_engine import SignalEngine
            sig_engine = SignalEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            positions = pe_status.get("positions", [])
            risk_summaries = []
            for pos in positions[:5]:
                sym = pos.get("symbol", "")
                if sym:
                    rm = sig_engine.compute_risk(sym)
                    risk_summaries.append(rm.to_dict())
            result.data["signal_risk"] = risk_summaries
        except Exception as exc:
            result.errors.append(f"signal_engine risk: {exc}")

        # Evolution Engine — feed risk performance into evaluation
        try:
            from .evolution_engine import EvolutionEngine
            evo_engine = EvolutionEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            perf = evo_engine.evaluate_performance()
            result.data["evolution_perf_snapshot"] = {
                "avg_drawdown":      perf.avg_drawdown,
                "volatility_regime": perf.volatility_regime,
                "hit_rate":          perf.hit_rate,
                "signal_count":      perf.signal_count,
            }
        except Exception as exc:
            result.errors.append(f"evolution_engine.evaluate_performance: {exc}")

        # Generate report
        if rep:
            try:
                report = rep.financial_from_dict(pe_status)
                result.report_id = report.report_id
            except Exception as exc:
                result.errors.append(f"report generation: {exc}")

        self._audit("financial_pipeline", f"drawdown={drawdown:.3f}")


# ---------------------------------------------------------------------------
# Evolution pipeline
# ---------------------------------------------------------------------------

class EvolutionPipeline(BasePipeline):
    """
    Runs an auto-evolution analysis cycle, generating (and optionally
    applying) code improvement patches.
    Always starts in DRY_RUN unless explicitly enabled.
    """

    name = "evolution"

    def _execute(self, result: PipelineRunResult) -> None:
        cfg: EvolutionConfig = self._config.evolution
        if cfg.mode == PipelineMode.DISABLED:
            result.status = PipelineStatus.SKIPPED
            return

        ae  = self._modules.auto_evolution
        rep = self._reports()

        # Run analysis cycle
        try:
            if hasattr(ae, "run_cycle"):
                cycle = ae.run_cycle(
                    paths=cfg.scan_paths,
                    max_patches=cfg.max_patches_per_cycle,
                )
                result.data["cycle"] = (cycle.to_dict()
                                        if hasattr(cycle, "to_dict") else str(cycle))
                patches_generated = cycle.patches_generated if hasattr(cycle, "patches_generated") else 0
                self._emit(EventType.EVOLUTION_CYCLE_DONE, {
                    "patches_generated": patches_generated,
                    "mode": cfg.mode.value,
                })
            ae_status = ae.status() if hasattr(ae, "status") else {}
        except Exception as exc:
            result.errors.append(f"evolution cycle: {exc}")
            ae_status = {}

        result.data["auto_evolution_status"] = ae_status

        # Apply patches if allowed and in live mode
        if (cfg.auto_apply_patches
                and cfg.mode == PipelineMode.ENABLED
                and self._config.is_live
                and "cycle" in result.data):
            try:
                if hasattr(ae, "apply_pending_patches"):
                    applied = ae.apply_pending_patches(
                        max_patches=cfg.max_patches_per_cycle
                    )
                    result.data["patches_applied"] = applied
                    if applied:
                        self._emit(EventType.PATCH_APPLIED, {"count": applied})
            except Exception as exc:
                result.errors.append(f"apply patches: {exc}")

        # Generate report
        if rep:
            try:
                report = rep.evolution_from_dict(ae_status)
                result.report_id = report.report_id
            except Exception as exc:
                result.errors.append(f"report generation: {exc}")

        self._audit("evolution_pipeline", f"mode={cfg.mode.value}")


# ---------------------------------------------------------------------------
# Consensus pipeline
# ---------------------------------------------------------------------------

class ConsensusPipeline(BasePipeline):
    """
    Queries multiple AI agents for a NEXUS system-state assessment,
    reaches consensus, and escalates contradictions.
    """

    name = "consensus"

    SYSTEM_QUESTIONS = [
        "Analyse the current NEXUS system health and identify any anomalies.",
        "Evaluate the risk profile of the current portfolio and recommend actions.",
        "Summarise the most significant market intelligence findings.",
    ]

    def _execute(self, result: PipelineRunResult) -> None:
        cfg: ConsensusConfig = self._config.consensus
        if cfg.mode == PipelineMode.DISABLED:
            result.status = PipelineStatus.SKIPPED
            return

        mia = self._modules.multi_ia
        rep = self._reports()

        consensus_results = []
        for question in self.SYSTEM_QUESTIONS:
            try:
                cr = mia.vote(question, n_agents=cfg.n_agents) if hasattr(mia, "vote") else None
                if cr:
                    cr_dict = cr.to_dict() if hasattr(cr, "to_dict") else {}
                    consensus_results.append(cr_dict)
                    agreement = float(cr_dict.get("agreement_score", 1.0))
                    if agreement < cfg.agreement_alert:
                        self._emit(EventType.CONSENSUS_ESCALATED, {
                            "question": question[:80],
                            "agreement_score": agreement,
                        })
                    if cr_dict.get("escalated"):
                        self._emit(EventType.CONSENSUS_ESCALATED, cr_dict)
            except Exception as exc:
                result.errors.append(f"consensus on '{question[:40]}': {exc}")

        result.data["consensus_results"] = consensus_results

        # Collect multi_ia status
        try:
            mia_status = mia.status() if hasattr(mia, "status") else {}
            result.data["multi_ia_status"] = mia_status
        except Exception as exc:
            result.errors.append(f"multi_ia.status: {exc}")
            mia_status = {}

        # Signal Engine — IA consensus on notable symbols from intelligence data
        try:
            from .signal_engine import SignalEngine
            sig_engine = SignalEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            # Derive symbols from previous intelligence signals if present
            signal_results = []
            wi = self._modules.web_intelligence
            wi_status = wi.status() if hasattr(wi, "status") else {}
            symbols = list({
                p.get("symbol", "")
                for p in wi_status.get("pattern_detector", {}).get("detected_patterns", [])
                if p.get("symbol")
            })
            for sym in symbols[:3]:
                _, consensus_data = sig_engine._ia_consensus(
                    sym, type("_R", (), {"errors": []})()
                )
                if consensus_data:
                    signal_results.append({"symbol": sym, "consensus": consensus_data})
            result.data["signal_consensus"] = signal_results
        except Exception as exc:
            result.errors.append(f"signal_engine consensus: {exc}")

        # Evolution Engine — feed consensus performance into evaluation
        try:
            from .evolution_engine import EvolutionEngine
            evo_engine = EvolutionEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            # Store last consensus agreement in checkpoint-accessible dict
            agreements = [
                float(cr.get("agreement_score", 1.0))
                for cr in consensus_results
                if isinstance(cr, dict)
            ]
            avg_agreement = sum(agreements) / len(agreements) if agreements else 1.0
            result.data["evolution_consensus_agreement"] = round(avg_agreement, 4)
            # Run a lightweight performance snapshot
            perf = evo_engine.evaluate_performance()
            result.data["evolution_perf_consensus"] = {
                "avg_agreement":   round(avg_agreement, 4),
                "hit_rate":        perf.hit_rate,
                "data_quality":    perf.data_quality,
            }
        except Exception as exc:
            result.errors.append(f"evolution_engine.consensus_eval: {exc}")

        # Generate report
        if rep:
            try:
                report = rep.multi_ia_from_dict({
                    **mia_status,
                    "history": [cr.to_dict() if hasattr(cr, "to_dict") else cr
                                for cr in consensus_results],
                })
                result.report_id = report.report_id
            except Exception as exc:
                result.errors.append(f"report generation: {exc}")

        self._audit("consensus_pipeline",
                    f"questions={len(self.SYSTEM_QUESTIONS)}, results={len(consensus_results)}")


# ---------------------------------------------------------------------------
# Reporting pipeline
# ---------------------------------------------------------------------------

class ReportingPipeline(BasePipeline):
    """
    Aggregates all module statuses, generates a unified report bundle,
    and optionally exports to JSON files.
    """

    name = "reporting"

    def _execute(self, result: PipelineRunResult) -> None:
        cfg: ReportingConfig = self._config.reporting
        if cfg.mode == PipelineMode.DISABLED:
            result.status = PipelineStatus.SKIPPED
            return

        rep = self._reports()
        if rep is None:
            result.errors.append("Reports module not available.")
            result.status = PipelineStatus.FAILED
            return

        generated: List[str] = []

        # Financial
        if "financial" in cfg.report_types:
            try:
                pe_status = (self._modules.profit_engine.status()
                             if hasattr(self._modules.profit_engine, "status") else {})
                r = rep.financial_from_dict(pe_status, period_label="reporting_cycle")
                generated.append(r.report_id)
                if cfg.auto_export_json:
                    rep.export_json(r, cfg.export_dir)
            except Exception as exc:
                result.errors.append(f"financial report: {exc}")

        # Intelligence
        if "intelligence" in cfg.report_types:
            try:
                wi_status = (self._modules.web_intelligence.status()
                             if hasattr(self._modules.web_intelligence, "status") else {})
                r = rep.intelligence_from_dict(wi_status, period_label="reporting_cycle")
                generated.append(r.report_id)
                if cfg.auto_export_json:
                    rep.export_json(r, cfg.export_dir)
            except Exception as exc:
                result.errors.append(f"intelligence report: {exc}")

        # Evolution
        if "evolution" in cfg.report_types:
            try:
                ae_status = (self._modules.auto_evolution.status()
                             if hasattr(self._modules.auto_evolution, "status") else {})
                r = rep.evolution_from_dict(ae_status, period_label="reporting_cycle")
                generated.append(r.report_id)
                if cfg.auto_export_json:
                    rep.export_json(r, cfg.export_dir)
            except Exception as exc:
                result.errors.append(f"evolution report: {exc}")

        # Multi-IA
        if "multi_ia" in cfg.report_types:
            try:
                mia_status = (self._modules.multi_ia.status()
                              if hasattr(self._modules.multi_ia, "status") else {})
                r = rep.multi_ia_from_dict(mia_status, period_label="reporting_cycle")
                generated.append(r.report_id)
                if cfg.auto_export_json:
                    rep.export_json(r, cfg.export_dir)
            except Exception as exc:
                result.errors.append(f"multi_ia report: {exc}")

        result.data["reports_generated"] = generated
        result.report_id = generated[0] if generated else None

        # Signal Engine — generate a summary signal report for recent signals
        try:
            from .signal_engine import SignalEngine
            sig_engine = SignalEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            recent_signals = sig_engine.history(limit=10)
            result.data["recent_signals"] = recent_signals
            if cfg.auto_export_json and recent_signals:
                import json
                from pathlib import Path
                sig_path = Path(cfg.export_dir) / "signals_latest.json"
                sig_path.parent.mkdir(parents=True, exist_ok=True)
                sig_path.write_text(
                    json.dumps({"signals": recent_signals}, indent=2, default=str),
                    encoding="utf-8",
                )
        except Exception as exc:
            result.errors.append(f"signal_engine reporting: {exc}")

        # Evolution Engine — include evolution summary in reports
        try:
            from .evolution_engine import EvolutionEngine
            import json as _json
            from pathlib import Path as _Path
            evo_engine = EvolutionEngine(
                modules=self._modules, config=self._config,
                bus=self._bus, reports=rep,
            )
            perf     = evo_engine.evaluate_performance()
            learning = evo_engine.learn_from_signals()
            proposals = evo_engine.propose_adjustments(perf, learning)
            evo_summary = {
                "evaluated_at":      perf.evaluated_at,
                "signal_count":      perf.signal_count,
                "hit_rate":          perf.hit_rate,
                "avg_score":         perf.avg_score,
                "volatility_regime": perf.volatility_regime,
                "data_quality":      perf.data_quality,
                "learning":          learning.to_dict(),
                "pending_proposals": [p.to_dict() for p in proposals],
            }
            result.data["evolution_summary"] = evo_summary
            if cfg.auto_export_json:
                evo_path = _Path(cfg.export_dir) / "evolution_summary.json"
                evo_path.parent.mkdir(parents=True, exist_ok=True)
                evo_path.write_text(
                    _json.dumps(evo_summary, indent=2, default=str),
                    encoding="utf-8",
                )
        except Exception as exc:
            result.errors.append(f"evolution_engine reporting: {exc}")

        self._emit(EventType.REPORT_GENERATED, {
            "count":      len(generated),
            "report_ids": generated,
        })
        self._audit("reporting_pipeline", f"generated={len(generated)}")
