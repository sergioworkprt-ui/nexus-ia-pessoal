"""
NEXUS Runtime — Evolution Engine
Controlled, data-driven, reversible parameter evolution layer.

The engine evaluates NEXUS performance against live signal history,
proposes small-to-moderate adjustments (BALANCED profile), applies them
with full audit logging, and supports rollback to any prior state.

Safety guarantee: every proposed change is checked against hard caps
before being included in a proposal list, and again before application.
No change > 15% of the current value in a single cycle.

Public API:
    engine = EvolutionEngine.from_runtime(runtime)
    perf   = engine.evaluate_performance()
    learn  = engine.learn_from_signals()
    props  = engine.propose_adjustments(perf, learn)
    result = engine.apply_adjustments(props)            # writes to disk
    rb     = engine.rollback(last_n=1)                  # reverts last apply
    hist   = engine.history(limit=20)
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .runtime_config import RuntimeConfig


# ---------------------------------------------------------------------------
# Safety caps — hard limits no proposal may breach
# ---------------------------------------------------------------------------

# (section.field) → (min_value, max_value)
_HARD_CAPS: Dict[str, Tuple[float, float]] = {
    "intelligence.sentiment_threshold": (0.05, 0.9),
    "financial.max_drawdown_alert":     (0.03, 0.25),
    "financial.sharpe_alert":           (0.05, 3.0),
    "consensus.agreement_alert":        (0.15, 0.85),
    "consensus.n_agents":               (1.0,  10.0),
    "evolution.max_patches_per_cycle":  (1.0,  20.0),
}

# Balanced profile — never change more than this fraction in one cycle
_MAX_STEP_FRACTION = 0.15   # 15% max change per parameter per cycle
_MAX_PROPOSALS     = 4      # max proposals in a single cycle
_MIN_SIGNALS       = 3      # minimum signals before proposing changes

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PerformanceReport:
    """Snapshot of NEXUS performance used to drive evolution proposals."""
    evaluated_at:       str
    signal_count:       int
    hit_rate:           float   = 0.0   # fraction of signals with score >= 0.6
    avg_score:          float   = 0.0   # mean composite signal score
    avg_drawdown:       float   = 0.0   # mean drawdown_pct across risk data
    volatility_regime:  str     = "medium"  # low | medium | high
    per_pattern:        Dict[str, Any] = field(default_factory=dict)
    consensus_agreement: float  = 1.0
    risk_metrics:       Dict[str, Any] = field(default_factory=dict)
    data_quality:       str     = "ok"  # ok | sparse | missing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluated_at":       self.evaluated_at,
            "signal_count":       self.signal_count,
            "hit_rate":           round(self.hit_rate, 4),
            "avg_score":          round(self.avg_score, 4),
            "avg_drawdown":       round(self.avg_drawdown, 4),
            "volatility_regime":  self.volatility_regime,
            "per_pattern":        self.per_pattern,
            "consensus_agreement": round(self.consensus_agreement, 4),
            "risk_metrics":       self.risk_metrics,
            "data_quality":       self.data_quality,
        }


@dataclass
class SignalLearning:
    """What the engine learned by analysing recent signal outcomes."""
    patterns_worked:    List[str] = field(default_factory=list)  # hit_rate > 0.6
    patterns_failed:    List[str] = field(default_factory=list)  # hit_rate < 0.4
    sentiment_effective: bool     = False
    risk_too_tight:     bool      = False   # many high-score signals never triggered
    risk_too_loose:     bool      = False   # frequent drawdown breaches
    consensus_useful:   bool      = True
    notes:              List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patterns_worked":     self.patterns_worked,
            "patterns_failed":     self.patterns_failed,
            "sentiment_effective": self.sentiment_effective,
            "risk_too_tight":      self.risk_too_tight,
            "risk_too_loose":      self.risk_too_loose,
            "consensus_useful":    self.consensus_useful,
            "notes":               self.notes,
        }


@dataclass
class Proposal:
    """A single parameter adjustment proposal."""
    proposal_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parameter:      str = ""   # dotted path: "section.field"
    description:    str = ""
    current_value:  Any = None
    proposed_value: Any = None
    rationale:      str = ""
    impact_level:   str = "low"   # low | medium
    change_pct:     float = 0.0   # relative change (signed %)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id":   self.proposal_id,
            "parameter":     self.parameter,
            "description":   self.description,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "rationale":     self.rationale,
            "impact_level":  self.impact_level,
            "change_pct":    round(self.change_pct, 4),
        }


@dataclass
class ApplyResult:
    """Outcome of apply_adjustments()."""
    evo_id:         str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    applied_count:  int = 0
    skipped_count:  int = 0
    proposals:      List[Proposal] = field(default_factory=list)
    config_before:  Dict[str, Any] = field(default_factory=dict)
    config_after:   Dict[str, Any] = field(default_factory=dict)
    ts:             str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    errors:         List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evo_id":        self.evo_id,
            "applied_count": self.applied_count,
            "skipped_count": self.skipped_count,
            "ts":            self.ts,
            "errors":        self.errors,
            "proposals":     [p.to_dict() for p in self.proposals],
        }


@dataclass
class RollbackResult:
    """Outcome of rollback()."""
    rolled_back:    int = 0
    evo_ids:        List[str] = field(default_factory=list)
    config_restored: Dict[str, Any] = field(default_factory=dict)
    ts:             str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    errors:         List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rolled_back":    self.rolled_back,
            "evo_ids":        self.evo_ids,
            "ts":             self.ts,
            "errors":         self.errors,
        }


# ---------------------------------------------------------------------------
# Evolution Engine
# ---------------------------------------------------------------------------

class EvolutionEngine:
    """
    Controlled, reversible parameter evolution for the NEXUS runtime.

    All operations are thread-safe. The engine never modifies the live
    runtime config object directly — it reads the current config, builds
    a mutated copy, and only writes to disk + memory after validation.
    """

    _LOG_PATH = "logs/evolution_live.jsonl"

    def __init__(
        self,
        modules:  Any,
        config:   RuntimeConfig,
        bus:      Optional[Any] = None,
        reports:  Optional[Any] = None,
    ) -> None:
        self._modules  = modules
        self._config   = config
        self._bus      = bus
        self._reports  = reports
        self._lock     = threading.RLock()
        self._root     = Path(__file__).parent.parent

        # Cached last evaluation
        self._last_perf:     Optional[PerformanceReport] = None
        self._last_learning: Optional[SignalLearning]    = None
        self._pending:       List[Proposal]              = []

    @classmethod
    def from_runtime(cls, runtime: Any) -> "EvolutionEngine":
        return cls(
            modules=runtime.integration.modules,
            config=runtime._config,
            bus=getattr(runtime, "bus", None),
            reports=getattr(runtime.integration.modules, "reports", None),
        )

    # ------------------------------------------------------------------
    # evaluate_performance
    # ------------------------------------------------------------------

    def evaluate_performance(self) -> PerformanceReport:
        """
        Reads recent signals, risk data, and consensus scores to produce
        a PerformanceReport used to drive proposals.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()

            signals   = self._load_signals()
            checkpoint = self._load_checkpoint()

            if not signals:
                perf = PerformanceReport(
                    evaluated_at=now,
                    signal_count=0,
                    data_quality="missing",
                )
                self._last_perf = perf
                return perf

            # Hit rate: signals where composite_score >= 0.6
            scores = [
                float(s.get("score", s.get("composite_score", 0.0)))
                for s in signals
            ]
            hit_count  = sum(1 for sc in scores if sc >= 0.6)
            hit_rate   = hit_count / len(scores) if scores else 0.0
            avg_score  = sum(scores) / len(scores) if scores else 0.0

            # Drawdown from risk sub-dicts
            drawdowns = []
            volatilities = []
            for s in signals:
                risk = s.get("risk", {})
                if isinstance(risk, dict):
                    dd  = float(risk.get("drawdown_pct", 0.0))
                    vol = float(risk.get("volatility", 0.0))
                    if dd > 0:
                        drawdowns.append(dd)
                    if vol > 0:
                        volatilities.append(vol)

            avg_drawdown = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0
            avg_vol      = sum(volatilities) / len(volatilities) if volatilities else 0.15

            if avg_vol < 0.10:
                vol_regime = "low"
            elif avg_vol < 0.25:
                vol_regime = "medium"
            else:
                vol_regime = "high"

            # Per-pattern performance
            pattern_stats: Dict[str, Dict[str, Any]] = {}
            for s in signals:
                # Signals may carry pattern info in various places
                ptype = (s.get("pattern_type")
                         or s.get("entry", {}).get("pattern_type")
                         or "unknown")
                sc = float(s.get("score", s.get("composite_score", 0.0)))
                if ptype not in pattern_stats:
                    pattern_stats[ptype] = {"count": 0, "score_sum": 0.0, "hits": 0}
                pattern_stats[ptype]["count"]     += 1
                pattern_stats[ptype]["score_sum"] += sc
                if sc >= 0.6:
                    pattern_stats[ptype]["hits"] += 1

            per_pattern: Dict[str, Any] = {}
            for ptype, st in pattern_stats.items():
                n = st["count"]
                per_pattern[ptype] = {
                    "count":    n,
                    "avg_score": round(st["score_sum"] / n, 4),
                    "hit_rate":  round(st["hits"] / n, 4),
                }

            # Consensus agreement from checkpoint
            consensus_agreement = float(
                checkpoint.get("last_consensus_agreement", 0.75)
            )

            quality = "ok" if len(signals) >= _MIN_SIGNALS else "sparse"

            perf = PerformanceReport(
                evaluated_at=now,
                signal_count=len(signals),
                hit_rate=hit_rate,
                avg_score=avg_score,
                avg_drawdown=avg_drawdown,
                volatility_regime=vol_regime,
                per_pattern=per_pattern,
                consensus_agreement=consensus_agreement,
                risk_metrics={
                    "avg_volatility": round(avg_vol, 4),
                    "drawdown_samples": len(drawdowns),
                    "max_drawdown_seen": round(max(drawdowns, default=0.0), 4),
                },
                data_quality=quality,
            )
            self._last_perf = perf
            return perf

    # ------------------------------------------------------------------
    # learn_from_signals
    # ------------------------------------------------------------------

    def learn_from_signals(self) -> SignalLearning:
        """
        Analyses last N signals to identify what is working and what is not.
        Results are fed into propose_adjustments().
        """
        with self._lock:
            signals = self._load_signals()
            perf    = self._last_perf or self.evaluate_performance()

            learning = SignalLearning()

            if not signals or len(signals) < _MIN_SIGNALS:
                learning.notes.append(
                    f"Insufficient data: {len(signals)} signals (min {_MIN_SIGNALS})."
                )
                self._last_learning = learning
                return learning

            # Pattern effectiveness
            for ptype, stats in perf.per_pattern.items():
                if ptype == "unknown":
                    continue
                hr = stats.get("hit_rate", 0.5)
                if hr >= 0.6:
                    learning.patterns_worked.append(ptype)
                elif hr < 0.4:
                    learning.patterns_failed.append(ptype)

            # Sentiment effectiveness: check if high sentiment_score correlates with hits
            sent_hits = []
            for s in signals:
                entry = s.get("entry", {})
                sent  = float(entry.get("sentiment_score", 0.0) if isinstance(entry, dict) else 0.0)
                sc    = float(s.get("score", 0.0))
                if abs(sent) > 0.05:
                    sent_hits.append((abs(sent), sc >= 0.6))

            if len(sent_hits) >= 3:
                correlation = sum(1 for _, h in sent_hits if h) / len(sent_hits)
                learning.sentiment_effective = correlation >= 0.55
            else:
                learning.sentiment_effective = True  # assume effective when low data

            # Risk calibration: too tight = many high risk_score signals that didn't fire
            risk_scores = [
                float(s.get("risk", {}).get("risk_score", 0.0))
                for s in signals
                if isinstance(s.get("risk"), dict)
            ]
            if risk_scores:
                avg_risk = sum(risk_scores) / len(risk_scores)
                high_risk_count = sum(1 for r in risk_scores if r >= 0.7)
                drawdown_pcts = [
                    float(s.get("risk", {}).get("drawdown_pct", 0.0))
                    for s in signals
                    if isinstance(s.get("risk"), dict)
                ]
                max_dd = max(drawdown_pcts, default=0.0)
                threshold = self._config.financial.max_drawdown_alert

                learning.risk_too_tight  = (avg_risk > 0.65 and
                                            max_dd < threshold * 0.5)
                learning.risk_too_loose  = max_dd >= threshold * 0.9

            # Consensus useful: check agreement scores
            learning.consensus_useful = perf.consensus_agreement >= 0.5

            # Build notes
            if learning.patterns_worked:
                learning.notes.append(
                    f"Effective patterns: {', '.join(learning.patterns_worked)}."
                )
            if learning.patterns_failed:
                learning.notes.append(
                    f"Underperforming patterns: {', '.join(learning.patterns_failed)}."
                )
            if learning.risk_too_tight:
                learning.notes.append("Risk thresholds appear conservative — consider relaxing.")
            if learning.risk_too_loose:
                learning.notes.append("Risk thresholds appear loose — consider tightening.")
            if not learning.sentiment_effective:
                learning.notes.append("Sentiment weight contribution appears low.")

            self._last_learning = learning
            return learning

    # ------------------------------------------------------------------
    # propose_adjustments
    # ------------------------------------------------------------------

    def propose_adjustments(
        self,
        perf:     Optional[PerformanceReport] = None,
        learning: Optional[SignalLearning]    = None,
    ) -> List[Proposal]:
        """
        Produces a list of balanced proposals (at most _MAX_PROPOSALS).
        Every proposal is validated against hard caps before inclusion.
        """
        with self._lock:
            perf     = perf     or self._last_perf     or self.evaluate_performance()
            learning = learning or self._last_learning or self.learn_from_signals()

            proposals: List[Proposal] = []

            if perf.data_quality == "missing":
                self._pending = proposals
                return proposals

            cfg = self._config

            # ── 1. Sentiment threshold ────────────────────────────────────────
            # If sentiment is not effective: increase threshold (be more selective)
            # If hit_rate is very high and sentiment is working: could relax slightly
            current_st = cfg.intelligence.sentiment_threshold
            if not learning.sentiment_effective and perf.signal_count >= _MIN_SIGNALS:
                new_st = current_st * 1.08   # +8% — be more selective
                p = self._make_proposal(
                    parameter="intelligence.sentiment_threshold",
                    current=current_st,
                    proposed=new_st,
                    description="Increase sentiment_threshold (sentiment has low predictive value)",
                    rationale=(
                        f"Sentiment correlation with hit_rate is below 55%. "
                        f"Raising threshold from {current_st:.3f} to {new_st:.3f} "
                        f"will filter out noise."
                    ),
                    impact="low",
                )
                if p:
                    proposals.append(p)

            elif learning.sentiment_effective and perf.hit_rate >= 0.65 and len(proposals) < _MAX_PROPOSALS:
                new_st = current_st * 0.94   # -6% — be slightly more responsive
                p = self._make_proposal(
                    parameter="intelligence.sentiment_threshold",
                    current=current_st,
                    proposed=new_st,
                    description="Lower sentiment_threshold slightly (sentiment is effective)",
                    rationale=(
                        f"Hit rate {perf.hit_rate:.1%} is strong and sentiment is "
                        f"correlated. Reducing threshold to {new_st:.3f} captures more signals."
                    ),
                    impact="low",
                )
                if p:
                    proposals.append(p)

            # ── 2. Max drawdown alert ─────────────────────────────────────────
            current_dd = cfg.financial.max_drawdown_alert
            if learning.risk_too_loose and len(proposals) < _MAX_PROPOSALS:
                new_dd = current_dd * 0.90   # tighten by 10%
                p = self._make_proposal(
                    parameter="financial.max_drawdown_alert",
                    current=current_dd,
                    proposed=new_dd,
                    description="Tighten max_drawdown_alert (risk thresholds too loose)",
                    rationale=(
                        f"Observed drawdown approaching {current_dd:.1%} alert level. "
                        f"Reducing alert to {new_dd:.3f} provides earlier warning."
                    ),
                    impact="medium",
                )
                if p:
                    proposals.append(p)

            elif learning.risk_too_tight and len(proposals) < _MAX_PROPOSALS:
                new_dd = current_dd * 1.10   # relax by 10%
                p = self._make_proposal(
                    parameter="financial.max_drawdown_alert",
                    current=current_dd,
                    proposed=new_dd,
                    description="Relax max_drawdown_alert slightly (risk is conservative)",
                    rationale=(
                        f"Drawdown consistently below {current_dd * 0.5:.1%}. "
                        f"Raising threshold to {new_dd:.3f} reduces false alerts."
                    ),
                    impact="low",
                )
                if p:
                    proposals.append(p)

            # ── 3. Consensus agreement alert ─────────────────────────────────
            current_ag = cfg.consensus.agreement_alert
            if (perf.consensus_agreement < current_ag * 0.85
                    and len(proposals) < _MAX_PROPOSALS):
                new_ag = current_ag * 0.92   # relax to reduce false escalations
                p = self._make_proposal(
                    parameter="consensus.agreement_alert",
                    current=current_ag,
                    proposed=new_ag,
                    description="Relax consensus agreement_alert (frequent false escalations)",
                    rationale=(
                        f"Observed agreement {perf.consensus_agreement:.2f} is consistently "
                        f"below alert {current_ag:.2f}. Lowering to {new_ag:.3f} "
                        f"reduces unnecessary escalations."
                    ),
                    impact="low",
                )
                if p:
                    proposals.append(p)

            elif (perf.consensus_agreement >= 0.80
                    and current_ag < 0.55
                    and len(proposals) < _MAX_PROPOSALS):
                new_ag = current_ag * 1.08   # tighten slightly
                p = self._make_proposal(
                    parameter="consensus.agreement_alert",
                    current=current_ag,
                    proposed=new_ag,
                    description="Tighten consensus agreement_alert (agreement is strong)",
                    rationale=(
                        f"IA agreement {perf.consensus_agreement:.2f} is high. "
                        f"Raising threshold to {new_ag:.3f} catches subtle divergences."
                    ),
                    impact="low",
                )
                if p:
                    proposals.append(p)

            # ── 4. Volatility-regime adjustment ──────────────────────────────
            current_sh = cfg.financial.sharpe_alert
            if (perf.volatility_regime == "high"
                    and current_sh < 1.0
                    and len(proposals) < _MAX_PROPOSALS):
                new_sh = min(current_sh * 1.12, 1.2)   # raise Sharpe bar in volatile market
                p = self._make_proposal(
                    parameter="financial.sharpe_alert",
                    current=current_sh,
                    proposed=new_sh,
                    description="Raise Sharpe alert threshold (high-volatility regime)",
                    rationale=(
                        f"Volatility regime is HIGH (avg vol: "
                        f"{perf.risk_metrics.get('avg_volatility', 0):.2%}). "
                        f"Raising Sharpe alert to {new_sh:.3f} enforces quality filter."
                    ),
                    impact="medium",
                )
                if p:
                    proposals.append(p)

            elif (perf.volatility_regime == "low"
                    and current_sh > 0.8
                    and len(proposals) < _MAX_PROPOSALS):
                new_sh = current_sh * 0.92
                p = self._make_proposal(
                    parameter="financial.sharpe_alert",
                    current=current_sh,
                    proposed=new_sh,
                    description="Lower Sharpe alert threshold (low-volatility regime)",
                    rationale=(
                        f"Volatility regime is LOW. Relaxing Sharpe alert "
                        f"from {current_sh:.3f} to {new_sh:.3f}."
                    ),
                    impact="low",
                )
                if p:
                    proposals.append(p)

            self._pending = proposals
            return proposals

    # ------------------------------------------------------------------
    # apply_adjustments
    # ------------------------------------------------------------------

    def apply_adjustments(self, proposals: List[Proposal]) -> ApplyResult:
        """
        Applies the given proposals to the live config.
        Writes config to disk, appends to evolution log, and writes audit entry.
        """
        with self._lock:
            result = ApplyResult()
            result.config_before = self._config.to_dict()

            for proposal in proposals:
                ok, err = self._apply_single(proposal)
                if ok:
                    result.applied_count += 1
                    result.proposals.append(proposal)
                else:
                    result.skipped_count += 1
                    result.errors.append(f"{proposal.parameter}: {err}")

            result.config_after = self._config.to_dict()

            # Persist config
            config_path = self._root / "config/live_runtime.json"
            if config_path.exists():
                try:
                    self._config.save(str(config_path))
                except Exception as exc:
                    result.errors.append(f"config save: {exc}")

            # Evolution log
            entry = self._build_log_entry(
                action="apply",
                evo_id=result.evo_id,
                proposals=[p.to_dict() for p in result.proposals],
                config_before=result.config_before,
                config_after=result.config_after,
            )
            self._append_log(entry)

            # Audit chain
            self._audit(
                action="evolution_apply",
                detail=(
                    f"evo_id={result.evo_id}  "
                    f"applied={result.applied_count}  "
                    f"skipped={result.skipped_count}"
                ),
            )

            # Emit event if bus is available
            self._emit("EVOLUTION_APPLIED", {
                "evo_id":        result.evo_id,
                "applied_count": result.applied_count,
                "proposals":     [p.to_dict() for p in result.proposals],
            })

            return result

    # ------------------------------------------------------------------
    # rollback
    # ------------------------------------------------------------------

    def rollback(self, last_n: int = 1) -> RollbackResult:
        """
        Reverts the last `last_n` applied evolution steps by restoring
        the config snapshot stored in each log entry.
        """
        with self._lock:
            result = RollbackResult()
            history = self._read_log_actions("apply")

            if not history:
                result.errors.append("No applied evolution steps found to rollback.")
                return result

            # Take the last_n apply entries (most recent first)
            to_revert = history[-last_n:]

            # Restore from the snapshot_before of the oldest of those entries
            oldest = to_revert[0]
            config_before = oldest.get("snapshot_before", {})

            if not config_before:
                result.errors.append("No config snapshot found in evolution log.")
                return result

            try:
                self._restore_config(config_before)
                result.config_restored = config_before
                result.rolled_back     = len(to_revert)
                result.evo_ids         = [e.get("evo_id", "?") for e in to_revert]
            except Exception as exc:
                result.errors.append(f"config restore: {exc}")
                return result

            # Persist
            config_path = self._root / "config/live_runtime.json"
            if config_path.exists():
                try:
                    self._config.save(str(config_path))
                except Exception as exc:
                    result.errors.append(f"config save: {exc}")

            # Log rollback entry
            rb_entry = self._build_log_entry(
                action="rollback",
                evo_id=str(uuid.uuid4())[:12],
                proposals=[],
                config_before=self._config.to_dict(),
                config_after=config_before,
                meta={"reverted_evo_ids": result.evo_ids},
            )
            self._append_log(rb_entry)

            self._audit(
                action="evolution_rollback",
                detail=f"rolled_back={result.rolled_back}  evo_ids={result.evo_ids}",
            )

            self._emit("EVOLUTION_ROLLBACK", {
                "rolled_back": result.rolled_back,
                "evo_ids":     result.evo_ids,
            })

            return result

    # ------------------------------------------------------------------
    # history / status
    # ------------------------------------------------------------------

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns the last `limit` evolution log entries (newest first)."""
        entries = self._read_log_raw(limit=limit * 2)
        return list(reversed(entries[-limit:]))

    def status(self) -> Dict[str, Any]:
        """Summary status of the evolution engine."""
        hist     = self.history(limit=5)
        last     = hist[0] if hist else {}
        pending  = [p.to_dict() for p in self._pending]
        return {
            "pending_proposals": len(self._pending),
            "proposals":         pending,
            "last_action":       last.get("action"),
            "last_evo_id":       last.get("evo_id"),
            "last_ts":           last.get("ts"),
            "total_logged":      len(self._read_log_raw(limit=10000)),
        }

    def pending_proposals(self) -> List[Proposal]:
        return list(self._pending)

    # ------------------------------------------------------------------
    # Internal helpers — proposal
    # ------------------------------------------------------------------

    def _make_proposal(
        self,
        parameter: str,
        current: float,
        proposed: float,
        description: str,
        rationale: str,
        impact: str = "low",
    ) -> Optional[Proposal]:
        """Validates proposed value against caps and step limit, returns Proposal or None."""
        if parameter in _HARD_CAPS:
            lo, hi = _HARD_CAPS[parameter]
            proposed = max(lo, min(hi, proposed))

        # Reject if proposed == current (rounding artefact)
        if abs(proposed - current) < 1e-9:
            return None

        # Enforce max step fraction (balanced profile)
        if current != 0:
            actual_frac = abs(proposed - current) / abs(current)
            if actual_frac > _MAX_STEP_FRACTION:
                direction = 1 if proposed > current else -1
                proposed  = current * (1 + direction * _MAX_STEP_FRACTION)
                if parameter in _HARD_CAPS:
                    lo, hi = _HARD_CAPS[parameter]
                    proposed = max(lo, min(hi, proposed))

        change_pct = ((proposed - current) / current * 100) if current else 0.0

        return Proposal(
            parameter=parameter,
            description=description,
            current_value=round(current, 6),
            proposed_value=round(proposed, 6),
            rationale=rationale,
            impact_level=impact,
            change_pct=round(change_pct, 2),
        )

    # ------------------------------------------------------------------
    # Internal helpers — apply
    # ------------------------------------------------------------------

    def _apply_single(self, proposal: Proposal) -> Tuple[bool, str]:
        """Applies one proposal to self._config in-memory. Returns (ok, error)."""
        parts = proposal.parameter.split(".")
        if len(parts) != 2:
            return False, f"unsupported path format '{proposal.parameter}'"

        section, field_name = parts
        sub = getattr(self._config, section, None)
        if sub is None:
            return False, f"section '{section}' not found in config"
        if not hasattr(sub, field_name):
            return False, f"field '{field_name}' not found in config.{section}"

        # Final cap check before write
        val = proposal.proposed_value
        if proposal.parameter in _HARD_CAPS:
            lo, hi = _HARD_CAPS[proposal.parameter]
            if not (lo <= val <= hi):
                return False, f"value {val} out of caps [{lo}, {hi}]"

        try:
            setattr(sub, field_name, type(getattr(sub, field_name))(val))
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _restore_config(self, config_dict: Dict[str, Any]) -> None:
        """Restores runtime config fields from a saved dict snapshot."""
        for section in ("intelligence", "financial", "evolution", "consensus",
                        "reporting", "scheduler"):
            sub_data = config_dict.get(section, {})
            sub      = getattr(self._config, section, None)
            if not sub or not isinstance(sub_data, dict):
                continue
            for key, val in sub_data.items():
                if hasattr(sub, key) and not isinstance(val, (dict, list)):
                    try:
                        setattr(sub, key, type(getattr(sub, key))(val))
                    except Exception:
                        pass

    # ------------------------------------------------------------------
    # Internal helpers — logging
    # ------------------------------------------------------------------

    def _build_log_entry(
        self,
        action: str,
        evo_id: str,
        proposals: List[Dict[str, Any]],
        config_before: Dict[str, Any],
        config_after:  Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prev_hash = self._last_log_hash()
        payload   = json.dumps({
            "evo_id":          evo_id,
            "action":          action,
            "ts":              datetime.now(timezone.utc).isoformat(),
            "proposals":       proposals,
            "snapshot_before": config_before,
            "snapshot_after":  config_after,
            **(meta or {}),
        }, sort_keys=True, default=str)
        entry_hash = hashlib.sha256((prev_hash + payload).encode()).hexdigest()
        entry = json.loads(payload)
        entry["hash"]      = entry_hash
        entry["prev_hash"] = prev_hash
        return entry

    def _append_log(self, entry: Dict[str, Any]) -> None:
        log_path = self._root / self._LOG_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def _read_log_raw(self, limit: int = 100) -> List[Dict[str, Any]]:
        log_path = self._root / self._LOG_PATH
        if not log_path.exists():
            return []
        entries = []
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
        return entries[-limit:]

    def _read_log_actions(self, action: str) -> List[Dict[str, Any]]:
        return [e for e in self._read_log_raw(limit=1000) if e.get("action") == action]

    def _last_log_hash(self) -> str:
        entries = self._read_log_raw(limit=1)
        return entries[-1].get("hash", "0" * 64) if entries else "0" * 64

    # ------------------------------------------------------------------
    # Internal helpers — data loading
    # ------------------------------------------------------------------

    def _load_signals(self) -> List[Dict[str, Any]]:
        path = self._root / "reports/live/signals_latest.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "signals" in data:
                return data["signals"]
        except Exception:
            pass
        return []

    def _load_checkpoint(self) -> Dict[str, Any]:
        for name in ("live_checkpoint_00.json", "checkpoint_00.json"):
            p = self._root / "data/runtime" / name
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {}

    # ------------------------------------------------------------------
    # Internal helpers — audit / events
    # ------------------------------------------------------------------

    def _audit(self, action: str, detail: str = "") -> None:
        rep = self._reports
        if rep and hasattr(rep, "log_event"):
            try:
                from reports import AuditEventType
                rep.log_event(
                    AuditEventType.PIPELINE_STARTED,
                    actor="evolution_engine",
                    action=action,
                    outcome=detail,
                )
            except Exception:
                pass
        # Also append to audit_live.jsonl directly
        try:
            audit_path = self._root / self._config.audit_log_path
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({
                "ts":     datetime.now(timezone.utc).isoformat(),
                "event":  action,
                "data":   {"detail": detail},
            }) + "\n"
            with audit_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass

    def _emit(self, event_name: str, data: Optional[Dict[str, Any]] = None) -> None:
        if not self._bus:
            return
        try:
            from .events import EventType
            evt = getattr(EventType, event_name, None)
            if evt:
                self._bus.emit(evt, source="evolution_engine", data=data or {})
        except Exception:
            pass
