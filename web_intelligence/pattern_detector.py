"""
NEXUS Web Intelligence — Pattern Detector
Detects breakouts, breakdowns, anomalies, volume divergences, support/resistance
levels, and scores each signal by confidence. Pure statistics; no ML libraries.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .market_data import OHLCBar


# ---------------------------------------------------------------------------
# Pattern types & signal
# ---------------------------------------------------------------------------

class PatternType(str, Enum):
    BREAKOUT          = "breakout"           # price breaks above N-bar high
    BREAKDOWN         = "breakdown"          # price breaks below N-bar low
    ANOMALY_PRICE     = "anomaly_price"      # statistical outlier in price move
    ANOMALY_VOLUME    = "anomaly_volume"     # statistical outlier in volume
    BULLISH_DIVERGENCE = "bullish_divergence" # price falls, volume rises (accumulation)
    BEARISH_DIVERGENCE = "bearish_divergence" # price rises, volume falls (distribution)
    DOUBLE_TOP        = "double_top"         # two peaks at similar level
    DOUBLE_BOTTOM     = "double_bottom"      # two troughs at similar level
    SUPPORT_TEST      = "support_test"       # price approaches support level
    RESISTANCE_TEST   = "resistance_test"    # price approaches resistance level
    HIGH_VOLATILITY   = "high_volatility"    # ATR spike relative to average


@dataclass
class PatternSignal:
    """A detected chart pattern with confidence and price context."""
    symbol:       str
    pattern_type: PatternType
    confidence:   float         # 0.0 – 1.0
    price_level:  float         # relevant price (breakout level, support, etc.)
    direction:    str           # "bullish", "bearish", or "neutral"
    detected_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signal_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    bar_index:    int = -1      # index in the input bar list
    metadata:     Dict[str, Any] = field(default_factory=dict)

    def is_actionable(self, min_confidence: float = 0.5) -> bool:
        return self.confidence >= min_confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id":    self.signal_id,
            "symbol":       self.symbol,
            "pattern":      self.pattern_type.value,
            "confidence":   round(self.confidence, 4),
            "price_level":  self.price_level,
            "direction":    self.direction,
            "detected_at":  self.detected_at,
            "bar_index":    self.bar_index,
            "metadata":     self.metadata,
        }


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _rolling_mean(values: List[float], window: int) -> List[Optional[float]]:
    result: List[Optional[float]] = [None] * len(values)
    for i in range(window - 1, len(values)):
        result[i] = statistics.mean(values[i - window + 1: i + 1])
    return result


def _rolling_std(values: List[float], window: int) -> List[Optional[float]]:
    result: List[Optional[float]] = [None] * len(values)
    for i in range(window - 1, len(values)):
        chunk = values[i - window + 1: i + 1]
        result[i] = statistics.pstdev(chunk) if len(chunk) >= 2 else 0.0
    return result


def _atr(bars: List[OHLCBar], period: int) -> List[Optional[float]]:
    """Average True Range over a rolling window."""
    trs: List[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            trs.append(bar.high - bar.low)
        else:
            prev = bars[i - 1]
            trs.append(max(
                bar.high - bar.low,
                abs(bar.high - prev.close),
                abs(bar.low  - prev.close),
            ))
    return _rolling_mean(trs, period)


# ---------------------------------------------------------------------------
# Pattern Detector
# ---------------------------------------------------------------------------

class PatternDetector:
    """
    Runs a suite of technical pattern detectors over a list of OHLCBars.

    All detectors return PatternSignal objects with confidence ∈ [0, 1].
    The scan() method runs all detectors and returns a sorted, deduplicated list.
    """

    def __init__(
        self,
        breakout_window: int   = 20,
        anomaly_z_threshold: float = 2.5,
        divergence_window: int = 10,
        double_pattern_window: int = 30,
        tolerance_pct: float   = 0.02,   # 2% tolerance for support/resistance matching
        atr_period: int        = 14,
        min_bars: int          = 30,
    ) -> None:
        self._bk_window  = breakout_window
        self._z_thresh   = anomaly_z_threshold
        self._div_window = divergence_window
        self._dp_window  = double_pattern_window
        self._tol        = tolerance_pct
        self._atr_period = atr_period
        self._min_bars   = min_bars

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scan(self, bars: List[OHLCBar], symbol: Optional[str] = None) -> List[PatternSignal]:
        """Run all detectors and return signals sorted by confidence (descending)."""
        if len(bars) < self._min_bars:
            return []
        sym = symbol or (bars[0].symbol if bars else "UNKNOWN")
        signals: List[PatternSignal] = []
        signals.extend(self.detect_breakout(bars, sym))
        signals.extend(self.detect_anomaly(bars, sym))
        signals.extend(self.detect_divergence(bars, sym))
        signals.extend(self.detect_double_patterns(bars, sym))
        signals.extend(self.detect_support_resistance(bars, sym))
        signals.extend(self.detect_high_volatility(bars, sym))
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    # ------------------------------------------------------------------
    # Breakout / Breakdown
    # ------------------------------------------------------------------

    def detect_breakout(
        self, bars: List[OHLCBar], symbol: str
    ) -> List[PatternSignal]:
        if len(bars) < self._bk_window + 1:
            return []
        signals: List[PatternSignal] = []
        for i in range(self._bk_window, len(bars)):
            window = bars[i - self._bk_window: i]
            current = bars[i]
            n_high = max(b.high for b in window)
            n_low  = min(b.low  for b in window)
            atr_val = _atr(bars[:i + 1], self._atr_period)[-1] or 1

            if current.close > n_high:
                excess     = (current.close - n_high) / atr_val
                confidence = min(1.0, 0.5 + excess * 0.2)
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=PatternType.BREAKOUT,
                    confidence=confidence, price_level=n_high,
                    direction="bullish", bar_index=i,
                    metadata={"window": self._bk_window, "excess_atr": round(excess, 3)},
                ))
            elif current.close < n_low:
                excess     = (n_low - current.close) / atr_val
                confidence = min(1.0, 0.5 + excess * 0.2)
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=PatternType.BREAKDOWN,
                    confidence=confidence, price_level=n_low,
                    direction="bearish", bar_index=i,
                    metadata={"window": self._bk_window, "excess_atr": round(excess, 3)},
                ))
        return self._last_only(signals)

    # ------------------------------------------------------------------
    # Anomaly detection (price & volume)
    # ------------------------------------------------------------------

    def detect_anomaly(
        self, bars: List[OHLCBar], symbol: str
    ) -> List[PatternSignal]:
        if len(bars) < 20:
            return []
        signals: List[PatternSignal] = []
        closes  = [b.close  for b in bars]
        volumes = [b.volume for b in bars]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]

        if len(returns) >= 10:
            mu  = statistics.mean(returns)
            std = statistics.pstdev(returns) or 1e-9
            for i, ret in enumerate(returns, start=1):
                z = abs((ret - mu) / std)
                if z >= self._z_thresh:
                    direction = "bullish" if ret > 0 else "bearish"
                    signals.append(PatternSignal(
                        symbol=symbol, pattern_type=PatternType.ANOMALY_PRICE,
                        confidence=min(1.0, (z - self._z_thresh + 1) / 3),
                        price_level=closes[i], direction=direction, bar_index=i,
                        metadata={"z_score": round(z, 3), "return_pct": round(ret * 100, 3)},
                    ))

        if len(volumes) >= 10:
            mu_v  = statistics.mean(volumes)
            std_v = statistics.pstdev(volumes) or 1e-9
            for i, vol in enumerate(volumes):
                z = (vol - mu_v) / std_v
                if z >= self._z_thresh:
                    signals.append(PatternSignal(
                        symbol=symbol, pattern_type=PatternType.ANOMALY_VOLUME,
                        confidence=min(1.0, (z - self._z_thresh + 1) / 3),
                        price_level=bars[i].close, direction="neutral", bar_index=i,
                        metadata={"z_score": round(z, 3), "volume": round(vol, 2)},
                    ))

        return self._last_only(signals)

    # ------------------------------------------------------------------
    # Volume divergence
    # ------------------------------------------------------------------

    def detect_divergence(
        self, bars: List[OHLCBar], symbol: str
    ) -> List[PatternSignal]:
        w = self._div_window
        if len(bars) < w * 2:
            return []
        signals: List[PatternSignal] = []
        for i in range(w, len(bars)):
            window  = bars[i - w: i + 1]
            prices  = [b.close  for b in window]
            volumes = [b.volume for b in window]
            price_trend  = prices[-1]  - prices[0]
            volume_trend = volumes[-1] - volumes[0]

            if price_trend < 0 and volume_trend > 0:
                # Price falling, volume rising → bullish accumulation divergence
                mag = min(1.0, abs(price_trend / (prices[0] or 1)) * 10)
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=PatternType.BULLISH_DIVERGENCE,
                    confidence=round(0.4 + mag * 0.4, 4),
                    price_level=prices[-1], direction="bullish", bar_index=i,
                    metadata={"price_chg_pct": round(price_trend / (prices[0] or 1) * 100, 2)},
                ))
            elif price_trend > 0 and volume_trend < 0:
                # Price rising, volume falling → bearish distribution divergence
                mag = min(1.0, abs(price_trend / (prices[0] or 1)) * 10)
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=PatternType.BEARISH_DIVERGENCE,
                    confidence=round(0.4 + mag * 0.4, 4),
                    price_level=prices[-1], direction="bearish", bar_index=i,
                    metadata={"price_chg_pct": round(price_trend / (prices[0] or 1) * 100, 2)},
                ))

        return self._last_only(signals)

    # ------------------------------------------------------------------
    # Double top / Double bottom
    # ------------------------------------  --------------------------------

    def detect_double_patterns(
        self, bars: List[OHLCBar], symbol: str
    ) -> List[PatternSignal]:
        w = self._dp_window
        if len(bars) < w:
            return []
        signals: List[PatternSignal] = []
        highs  = [b.high  for b in bars]
        lows   = [b.low   for b in bars]
        closes = [b.close for b in bars]
        tol    = self._tol

        for i in range(w, len(bars)):
            window_h = highs[i - w: i + 1]
            window_l = lows [i - w: i + 1]
            peak_1   = max(window_h[:w // 2])
            peak_2   = max(window_h[w // 2:])
            trough_1 = min(window_l[:w // 2])
            trough_2 = min(window_l[w // 2:])

            if peak_1 > 0 and abs(peak_1 - peak_2) / peak_1 < tol:
                conf = 1.0 - abs(peak_1 - peak_2) / (peak_1 * tol + 1e-9)
                conf = max(0.0, min(1.0, conf * 0.7))
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=PatternType.DOUBLE_TOP,
                    confidence=conf, price_level=round((peak_1 + peak_2) / 2, 6),
                    direction="bearish", bar_index=i,
                    metadata={"peak_1": peak_1, "peak_2": peak_2},
                ))

            if trough_1 > 0 and abs(trough_1 - trough_2) / trough_1 < tol:
                conf = 1.0 - abs(trough_1 - trough_2) / (trough_1 * tol + 1e-9)
                conf = max(0.0, min(1.0, conf * 0.7))
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=PatternType.DOUBLE_BOTTOM,
                    confidence=conf, price_level=round((trough_1 + trough_2) / 2, 6),
                    direction="bullish", bar_index=i,
                    metadata={"trough_1": trough_1, "trough_2": trough_2},
                ))

        return self._last_only(signals)

    # ------------------------------------------------------------------
    # Support & Resistance
    # ------------------------------------------------------------------

    def detect_support_resistance(
        self, bars: List[OHLCBar], symbol: str
    ) -> List[PatternSignal]:
        if len(bars) < 20:
            return []
        signals: List[PatternSignal] = []
        current = bars[-1]
        levels  = self._find_levels(bars[:-1])
        tol     = current.close * self._tol

        for level in levels:
            distance = abs(current.close - level)
            if distance <= tol:
                is_support = current.close >= level
                pt = PatternType.SUPPORT_TEST if is_support else PatternType.RESISTANCE_TEST
                direction = "bullish" if is_support else "bearish"
                confidence = max(0.3, 1.0 - distance / tol)
                signals.append(PatternSignal(
                    symbol=symbol, pattern_type=pt,
                    confidence=round(confidence, 4),
                    price_level=round(level, 6),
                    direction=direction, bar_index=len(bars) - 1,
                    metadata={"distance_pct": round(distance / current.close * 100, 3)},
                ))
        return signals

    # ------------------------------------------------------------------
    # High volatility (ATR spike)
    # ------------------------------------------------------------------

    def detect_high_volatility(
        self, bars: List[OHLCBar], symbol: str
    ) -> List[PatternSignal]:
        if len(bars) < self._atr_period * 2:
            return []
        signals: List[PatternSignal] = []
        atr_vals = [v for v in _atr(bars, self._atr_period) if v is not None]
        if len(atr_vals) < 5:
            return []
        mu  = statistics.mean(atr_vals[:-1])
        std = statistics.pstdev(atr_vals[:-1]) or 1e-9
        latest_atr = atr_vals[-1]
        z = (latest_atr - mu) / std
        if z >= 2.0:
            signals.append(PatternSignal(
                symbol=symbol, pattern_type=PatternType.HIGH_VOLATILITY,
                confidence=min(1.0, (z - 2.0 + 1) / 3),
                price_level=bars[-1].close,
                direction="neutral", bar_index=len(bars) - 1,
                metadata={"atr": round(latest_atr, 6), "z_score": round(z, 3)},
            ))
        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_levels(self, bars: List[OHLCBar]) -> List[float]:
        """Identify support/resistance levels as frequently-tested price clusters."""
        if len(bars) < 10:
            return []
        pivot_prices: List[float] = []
        for i in range(1, len(bars) - 1):
            if bars[i].high >= bars[i-1].high and bars[i].high >= bars[i+1].high:
                pivot_prices.append(bars[i].high)
            if bars[i].low <= bars[i-1].low and bars[i].low <= bars[i+1].low:
                pivot_prices.append(bars[i].low)

        if not pivot_prices:
            return []

        # Cluster nearby pivots (within 1% of each other)
        pivot_prices.sort()
        clusters: List[List[float]] = [[pivot_prices[0]]]
        for price in pivot_prices[1:]:
            if price <= clusters[-1][-1] * 1.01:
                clusters[-1].append(price)
            else:
                clusters.append([price])

        # Only return levels touched by at least 2 pivots
        return [statistics.mean(c) for c in clusters if len(c) >= 2]

    @staticmethod
    def _last_only(signals: List[PatternSignal]) -> List[PatternSignal]:
        """Keep only the most recent signal per PatternType."""
        seen: Dict[PatternType, PatternSignal] = {}
        for s in signals:
            if s.pattern_type not in seen or s.bar_index > seen[s.pattern_type].bar_index:
                seen[s.pattern_type] = s
        return list(seen.values())
