"""
NEXUS Runtime — Signal Engine
Generates, evaluates, and scores trade signals for any symbol by fusing:
  - price pattern detection (WebIntelligence / PatternDetector)
  - sentiment analysis (NewsAnalyzer)
  - financial risk checks (ProfitEngine / RiskManager)
  - multi-IA consensus (MultiIA voting)

Public API:
    engine = SignalEngine(modules, config, bus, reports)
    result = engine.generate_signal("BTC")
    result = engine.evaluate_entry("ETH")
    result = engine.evaluate_exit("BTC")
    result = engine.compute_risk("ETH")
"""

from __future__ import annotations

import math
import statistics
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

_SIDE_BUY  = "buy"
_SIDE_SELL = "sell"
_SIDE_HOLD = "hold"


@dataclass
class RiskMetrics:
    """Computed risk metrics for a symbol at evaluation time."""
    symbol:           str
    volatility:       float   = 0.0   # normalised 0-1 (ATR / price)
    drawdown_pct:     float   = 0.0   # current drawdown from peak
    position_size:    float   = 0.0   # suggested size (fraction of capital)
    stop_loss_pct:    float   = 0.02  # suggested stop-loss distance
    take_profit_pct:  float   = 0.04  # suggested take-profit distance
    risk_score:       float   = 0.0   # 0 (safe) – 1 (high risk)
    alerts:           List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol":          self.symbol,
            "volatility":      round(self.volatility, 4),
            "drawdown_pct":    round(self.drawdown_pct, 4),
            "position_size":   round(self.position_size, 4),
            "stop_loss_pct":   round(self.stop_loss_pct, 4),
            "take_profit_pct": round(self.take_profit_pct, 4),
            "risk_score":      round(self.risk_score, 4),
            "alerts":          self.alerts,
        }


@dataclass
class EntryEvaluation:
    """Entry readiness assessment for a symbol."""
    symbol:          str
    should_enter:    bool
    side:            str             # "buy" | "sell" | "hold"
    confidence:      float           # 0-1
    signal_strength: float           # 0-1 (weighted from all sources)
    pattern_score:   float   = 0.0
    sentiment_score: float   = 0.0
    consensus_score: float   = 0.0
    risk:            Optional[RiskMetrics] = None
    reasons:         List[str] = field(default_factory=list)
    timestamp:       str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "symbol":          self.symbol,
            "should_enter":    self.should_enter,
            "side":            self.side,
            "confidence":      round(self.confidence, 4),
            "signal_strength": round(self.signal_strength, 4),
            "pattern_score":   round(self.pattern_score, 4),
            "sentiment_score": round(self.sentiment_score, 4),
            "consensus_score": round(self.consensus_score, 4),
            "reasons":         self.reasons,
            "timestamp":       self.timestamp,
        }
        if self.risk:
            d["risk"] = self.risk.to_dict()
        return d


@dataclass
class ExitEvaluation:
    """Exit readiness assessment for an open position."""
    symbol:       str
    should_exit:  bool
    urgency:      str            # "low" | "medium" | "high" | "immediate"
    reasons:      List[str]      = field(default_factory=list)
    pnl_estimate: float          = 0.0
    timestamp:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol":       self.symbol,
            "should_exit":  self.should_exit,
            "urgency":      self.urgency,
            "reasons":      self.reasons,
            "pnl_estimate": round(self.pnl_estimate, 4),
            "timestamp":    self.timestamp,
        }


@dataclass
class SignalResult:
    """
    Full signal output for a symbol: entry, exit, risk, and IA consensus.
    This is the main output of generate_signal().
    """
    symbol:       str
    signal_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    entry:        Optional[EntryEvaluation] = None
    exit:         Optional[ExitEvaluation]  = None
    risk:         Optional[RiskMetrics]     = None
    consensus:    Optional[Dict[str, Any]]  = None
    patterns:     List[Dict[str, Any]]      = field(default_factory=list)
    sentiment:    Dict[str, Any]            = field(default_factory=dict)
    errors:       List[str]                 = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def side(self) -> str:
        return self.entry.side if self.entry else _SIDE_HOLD

    @property
    def strength(self) -> float:
        return self.entry.signal_strength if self.entry else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id":    self.signal_id,
            "symbol":       self.symbol,
            "side":         self.side,
            "strength":     round(self.strength, 4),
            "entry":        self.entry.to_dict() if self.entry else None,
            "exit":         self.exit.to_dict()  if self.exit  else None,
            "risk":         self.risk.to_dict()  if self.risk  else None,
            "consensus":    self.consensus,
            "patterns":     self.patterns,
            "sentiment":    self.sentiment,
            "errors":       self.errors,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Signal Engine
# ---------------------------------------------------------------------------

class SignalEngine:
    """
    Fuses pattern detection, sentiment, financial risk, and multi-IA consensus
    into actionable trade signals for any given symbol.

    Instantiated by the pipelines via SignalEngine.from_modules(modules, config).
    Can also be used standalone.

    Weights for the composite signal score:
        pattern   : 0.40
        sentiment : 0.20
        consensus : 0.40
    """

    PATTERN_WEIGHT   = 0.40
    SENTIMENT_WEIGHT = 0.20
    CONSENSUS_WEIGHT = 0.40

    # Minimum composite strength to recommend entry
    ENTRY_THRESHOLD = 0.35

    def __init__(
        self,
        modules:  Any,                      # ModuleHandles from NexusIntegration
        config:   Any,                      # RuntimeConfig
        bus:      Optional[Any] = None,     # EventBus
        reports:  Optional[Any] = None,     # Reports
    ) -> None:
        self._modules = modules
        self._config  = config
        self._bus     = bus
        self._reports = reports
        self._lock    = threading.RLock()
        self._history: List[SignalResult] = []

    @classmethod
    def from_runtime(cls, runtime: Any) -> "SignalEngine":
        """Construct from a live NexusRuntime instance."""
        return cls(
            modules=runtime.integration.modules,
            config=runtime._config,
            bus=runtime.bus,
            reports=getattr(runtime.integration.modules, "reports", None),
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def generate_signal(self, symbol: str) -> SignalResult:
        """
        Full signal generation pipeline for a symbol:
        1. Collect patterns from web_intelligence
        2. Score sentiment
        3. Check financial risk
        4. Run multi-IA consensus vote
        5. Compute composite entry/exit signal
        6. Emit TRADE_SIGNAL event + audit log
        """
        result = SignalResult(symbol=symbol)

        with self._lock:
            # ── 1. Patterns ─────────────────────────────────────────────
            patterns, pattern_score = self._collect_patterns(symbol, result)
            result.patterns = patterns

            # ── 2. Sentiment ─────────────────────────────────────────────
            sentiment_score, sentiment_data = self._score_sentiment(symbol, result)
            result.sentiment = sentiment_data

            # ── 3. Risk ──────────────────────────────────────────────────
            risk = self.compute_risk(symbol)
            result.risk = risk

            # ── 4. Multi-IA consensus ────────────────────────────────────
            consensus_score, consensus_data = self._ia_consensus(symbol, result)
            result.consensus = consensus_data

            # ── 5. Composite signal ──────────────────────────────────────
            result.entry = self._build_entry(
                symbol, pattern_score, sentiment_score, consensus_score, risk
            )
            result.exit = self._build_exit(symbol, risk, patterns, result)

            # ── 6. Events + audit ─────────────────────────────────────────
            self._emit_and_audit(result)
            self._history.append(result)
            if len(self._history) > 500:
                self._history = self._history[-500:]

        return result

    def evaluate_entry(self, symbol: str) -> EntryEvaluation:
        """Evaluate entry readiness for a symbol (lighter — no IA consensus)."""
        patterns, pattern_score = self._collect_patterns(symbol, SignalResult(symbol=symbol))
        sentiment_score, _ = self._score_sentiment(symbol, SignalResult(symbol=symbol))
        risk = self.compute_risk(symbol)
        return self._build_entry(symbol, pattern_score, sentiment_score, 0.5, risk)

    def evaluate_exit(self, symbol: str) -> ExitEvaluation:
        """Evaluate exit readiness for an open position."""
        patterns, _ = self._collect_patterns(symbol, SignalResult(symbol=symbol))
        risk = self.compute_risk(symbol)
        dummy = SignalResult(symbol=symbol, patterns=patterns)
        return self._build_exit(symbol, risk, patterns, dummy)

    def compute_risk(self, symbol: str) -> RiskMetrics:
        """Compute risk metrics for a symbol from current market data and PE state."""
        risk = RiskMetrics(symbol=symbol)

        try:
            pe = self._modules.profit_engine
            pe_status = pe.status() if hasattr(pe, "status") else {}

            risk_data = pe_status.get("risk", {})
            risk.drawdown_pct = float(risk_data.get("current_drawdown", 0.0))

            # Volatility from market data (if available)
            wi = self._modules.web_intelligence
            vol = self._estimate_volatility(symbol, wi)
            risk.volatility = vol

            # Position sizing: Kelly-fraction approximation
            # f* = (win_rate - (1 - win_rate) / rr)  capped at 0.05
            win_rate  = float(pe_status.get("win_rate", 0.5))
            rr        = 2.0   # assume 2:1 reward/risk
            kelly     = max(0.0, win_rate - (1.0 - win_rate) / rr)
            risk.position_size = round(min(kelly * 0.25, 0.05), 4)  # quarter-Kelly, max 5%

            # Stop / TP based on volatility
            atr_fraction       = max(vol * 2.0, 0.01)
            risk.stop_loss_pct  = round(min(atr_fraction, 0.05), 4)
            risk.take_profit_pct = round(risk.stop_loss_pct * 2.0, 4)

            # Risk score: weighted combo of drawdown and volatility
            risk.risk_score = round(
                min(1.0, risk.drawdown_pct * 5.0 + risk.volatility * 2.0), 4
            )

            # Alerts
            fin_cfg = self._config.financial
            if risk.drawdown_pct >= fin_cfg.max_drawdown_alert:
                risk.alerts.append(
                    f"Drawdown {risk.drawdown_pct:.1%} ≥ alert threshold "
                    f"{fin_cfg.max_drawdown_alert:.1%}"
                )
            if risk.volatility > 0.04:
                risk.alerts.append(f"High volatility: {risk.volatility:.1%}")

        except Exception as exc:
            risk.alerts.append(f"risk_compute_error: {exc}")

        return risk

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history[-limit:]]

    # ------------------------------------------------------------------
    # Pattern collection
    # ------------------------------------------------------------------

    def _collect_patterns(
        self, symbol: str, result: SignalResult
    ) -> tuple[List[Dict[str, Any]], float]:
        patterns: List[Dict[str, Any]] = []
        score = 0.5   # neutral default

        try:
            wi = self._modules.web_intelligence
            wi_status = wi.status() if hasattr(wi, "status") else {}

            # Pull patterns from last scan if available
            raw_patterns = (
                wi_status.get("pattern_detector", {}).get("detected_patterns", [])
            )

            bullish_score = 0.0
            bearish_score = 0.0
            total         = 0

            for p in raw_patterns:
                sym = p.get("symbol", "")
                if sym and sym.upper() != symbol.upper():
                    continue
                patterns.append(p)
                direction  = p.get("direction", "neutral").lower()
                confidence = float(p.get("confidence", 0.5))
                if direction == "bullish":
                    bullish_score += confidence
                elif direction == "bearish":
                    bearish_score += confidence
                total += 1

            if total > 0:
                # Net directional score: positive = bullish, negative = bearish
                # Normalise to 0-1 where 0.5 = neutral
                net   = (bullish_score - bearish_score) / max(total, 1)
                score = round(0.5 + net * 0.5, 4)

        except Exception as exc:
            result.errors.append(f"pattern_collect: {exc}")

        return patterns, score

    # ------------------------------------------------------------------
    # Sentiment scoring
    # ------------------------------------------------------------------

    def _score_sentiment(
        self, symbol: str, result: SignalResult
    ) -> tuple[float, Dict[str, Any]]:
        score = 0.5   # neutral
        data: Dict[str, Any] = {}

        try:
            wi = self._modules.web_intelligence
            wi_status = wi.status() if hasattr(wi, "status") else {}
            news_data = wi_status.get("news_analyzer", {})
            data = dict(news_data)

            avg_score = float(news_data.get("average_score", 0.0))
            # Map [-1, 1] → [0, 1]
            score = round(0.5 + avg_score * 0.5, 4)

        except Exception as exc:
            result.errors.append(f"sentiment_score: {exc}")

        return score, data

    # ------------------------------------------------------------------
    # Multi-IA consensus
    # ------------------------------------------------------------------

    def _ia_consensus(
        self, symbol: str, result: SignalResult
    ) -> tuple[float, Dict[str, Any]]:
        score = 0.5
        data: Dict[str, Any] = {}

        try:
            mia  = self._modules.multi_ia
            cfg  = self._config.consensus
            question = (
                f"Based on current market conditions, should we BUY, SELL, or HOLD "
                f"{symbol}? Rate your conviction 0-10 and explain briefly."
            )
            cr = mia.vote(question, n_agents=cfg.n_agents) if hasattr(mia, "vote") else None
            if cr:
                data = cr.to_dict() if hasattr(cr, "to_dict") else {}
                agreement = float(data.get("agreement_score", 0.5))

                # Determine directional bias from summary text
                summary   = str(data.get("summary", "")).lower()
                if "buy" in summary or "long" in summary or "bullish" in summary:
                    directional = 0.7
                elif "sell" in summary or "short" in summary or "bearish" in summary:
                    directional = 0.3
                else:
                    directional = 0.5

                # Weight by agreement: high agreement → trust direction; low → neutral
                score = round(0.5 + (directional - 0.5) * agreement, 4)
                data["signal_score"] = score

        except Exception as exc:
            result.errors.append(f"ia_consensus: {exc}")

        return score, data

    # ------------------------------------------------------------------
    # Entry / Exit builders
    # ------------------------------------------------------------------

    def _build_entry(
        self,
        symbol:          str,
        pattern_score:   float,
        sentiment_score: float,
        consensus_score: float,
        risk:            RiskMetrics,
    ) -> EntryEvaluation:
        composite = (
            pattern_score   * self.PATTERN_WEIGHT
            + sentiment_score * self.SENTIMENT_WEIGHT
            + consensus_score * self.CONSENSUS_WEIGHT
        )
        composite = round(composite, 4)

        # Directional bias: scores > 0.5 are bullish, < 0.5 bearish
        bias      = composite - 0.5
        side      = _SIDE_BUY if bias > 0.05 else (_SIDE_SELL if bias < -0.05 else _SIDE_HOLD)
        strength  = round(abs(bias) * 2.0, 4)   # normalise bias to [0, 1]

        reasons: List[str] = []
        reasons.append(f"Pattern score: {pattern_score:.2f}  (weight {self.PATTERN_WEIGHT})")
        reasons.append(f"Sentiment score: {sentiment_score:.2f}  (weight {self.SENTIMENT_WEIGHT})")
        reasons.append(f"IA consensus score: {consensus_score:.2f}  (weight {self.CONSENSUS_WEIGHT})")
        reasons.append(f"Composite: {composite:.4f}  →  {side.upper()}")

        if risk.alerts:
            for alert in risk.alerts:
                reasons.append(f"⚠  {alert}")

        # Block entry if risk is too high
        should_enter = (
            strength >= self.ENTRY_THRESHOLD
            and side != _SIDE_HOLD
            and risk.risk_score < 0.75
        )

        if not should_enter:
            if strength < self.ENTRY_THRESHOLD:
                reasons.append(f"Entry blocked: strength {strength:.2f} < threshold {self.ENTRY_THRESHOLD}")
            if risk.risk_score >= 0.75:
                reasons.append(f"Entry blocked: risk score {risk.risk_score:.2f} ≥ 0.75")

        return EntryEvaluation(
            symbol=symbol,
            should_enter=should_enter,
            side=side,
            confidence=round(composite, 4),
            signal_strength=strength,
            pattern_score=pattern_score,
            sentiment_score=sentiment_score,
            consensus_score=consensus_score,
            risk=risk,
            reasons=reasons,
        )

    def _build_exit(
        self,
        symbol:   str,
        risk:     RiskMetrics,
        patterns: List[Dict[str, Any]],
        result:   SignalResult,
    ) -> ExitEvaluation:
        reasons: List[str] = []
        should_exit = False
        urgency = "low"
        pnl_estimate = 0.0

        # Risk-based exit triggers
        if risk.drawdown_pct >= self._config.financial.max_drawdown_alert:
            reasons.append(f"Drawdown {risk.drawdown_pct:.1%} hit alert threshold")
            should_exit = True
            urgency = "high"

        if risk.risk_score >= 0.80:
            reasons.append(f"Risk score {risk.risk_score:.2f} ≥ 0.80")
            should_exit = True
            urgency = "immediate" if risk.risk_score >= 0.90 else "high"

        if risk.volatility > 0.06:
            reasons.append(f"Extreme volatility {risk.volatility:.1%}")
            should_exit = True
            urgency = max(urgency, "medium",
                          key=lambda x: {"low":0,"medium":1,"high":2,"immediate":3}[x])

        # Pattern-based exit triggers (bearish reversal signals)
        for p in patterns:
            if p.get("direction") == "bearish" and float(p.get("confidence", 0)) > 0.7:
                reasons.append(
                    f"Bearish pattern: {p.get('pattern', '?')} "
                    f"(conf {p.get('confidence', 0):.2f})"
                )
                should_exit = True
                urgency = max(urgency, "medium",
                              key=lambda x: {"low":0,"medium":1,"high":2,"immediate":3}[x])

        try:
            pe = self._modules.profit_engine
            pe_status = pe.status() if hasattr(pe, "status") else {}
            positions = pe_status.get("positions", [])
            for pos in positions:
                if str(pos.get("symbol", "")).upper() == symbol.upper():
                    pnl_estimate = float(pos.get("unrealised_pnl", 0.0))
                    break
        except Exception:
            pass

        if not reasons:
            reasons.append("No exit trigger active — hold position.")

        return ExitEvaluation(
            symbol=symbol,
            should_exit=should_exit,
            urgency=urgency,
            reasons=reasons,
            pnl_estimate=pnl_estimate,
        )

    # ------------------------------------------------------------------
    # Volatility estimation
    # ------------------------------------------------------------------

    def _estimate_volatility(self, symbol: str, wi: Any) -> float:
        """Estimate volatility as normalised ATR / price from stored bars."""
        try:
            from web_intelligence.market_data import TimeFrame
            bars = []
            if hasattr(wi, "get_bars"):
                bars = wi.get_bars(symbol, TimeFrame.D1, limit=20) or []
            if len(bars) < 2:
                return 0.01

            true_ranges = []
            for i in range(1, len(bars)):
                b = bars[i]
                prev_close = bars[i - 1].close
                tr = max(
                    b.high - b.low,
                    abs(b.high - prev_close),
                    abs(b.low  - prev_close),
                )
                true_ranges.append(tr)

            atr   = statistics.mean(true_ranges[-14:])
            price = bars[-1].close or 1.0
            return round(atr / price, 6)

        except Exception:
            return 0.01

    # ------------------------------------------------------------------
    # Events + audit
    # ------------------------------------------------------------------

    def _emit_and_audit(self, result: SignalResult) -> None:
        try:
            from nexus_runtime.events import EventType, Event
            if self._bus and result.entry:
                if result.entry.should_enter:
                    self._bus.emit(
                        EventType.TRADE_SIGNAL,
                        {
                            "symbol":   result.symbol,
                            "side":     result.side,
                            "strength": result.strength,
                            "signal_id": result.signal_id,
                        },
                        source="signal_engine",
                    )
                for alert in result.risk.alerts if result.risk else []:
                    self._bus.emit(
                        EventType.RISK_BREACH,
                        {"symbol": result.symbol, "detail": alert},
                        source="signal_engine",
                    )
        except Exception:
            pass

        try:
            if self._reports and hasattr(self._reports, "audit"):
                self._reports.audit.log(
                    actor="signal_engine",
                    action="generate_signal",
                    target=result.symbol,
                    outcome=(
                        f"side={result.side} strength={result.strength:.3f} "
                        f"risk={result.risk.risk_score:.3f}" if result.risk else ""
                    ),
                    detail={"signal_id": result.signal_id},
                )
        except Exception:
            pass
