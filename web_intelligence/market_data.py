"""
NEXUS Web Intelligence — Market Data
OHLC aggregation from tick data, normalisation, validation, and pluggable feeds.
Defines OHLCBar independently of profit_engine to avoid circular imports;
provides a to_profit_bar() converter for seamless integration.
"""

from __future__ import annotations

import math
import statistics
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Tuple


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

class TimeFrame(str, Enum):
    TICK   = "tick"
    M1     = "1m"
    M5     = "5m"
    M15    = "15m"
    M30    = "30m"
    H1     = "1h"
    H4     = "4h"
    D1     = "1d"
    W1     = "1w"


@dataclass
class Tick:
    """A single price update (last trade or bid/ask mid)."""
    symbol:    str
    price:     float
    volume:    float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"Tick price must be positive, got {self.price}.")
        if self.volume < 0:
            raise ValueError(f"Tick volume must be non-negative, got {self.volume}.")


@dataclass
class OHLCBar:
    """OHLCV bar — independent primitive for the web intelligence layer."""
    symbol:    str
    timeframe: TimeFrame
    timestamp: str
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float
    trades:    int   = 0           # number of ticks aggregated
    vwap:      Optional[float] = None

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"OHLCBar high ({self.high}) < low ({self.low}) for {self.symbol}.")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"OHLCBar open ({self.open}) outside [low, high] for {self.symbol}.")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"OHLCBar close ({self.close}) outside [low, high] for {self.symbol}.")

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    def to_profit_bar(self) -> Any:
        """Convert to profit_engine._types.Bar for strategy use."""
        try:
            from profit_engine._types import Bar  # type: ignore[import]
            return Bar(symbol=self.symbol, timestamp=self.timestamp,
                       open=self.open, high=self.high,
                       low=self.low, close=self.close, volume=self.volume)
        except ImportError:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol, "timeframe": self.timeframe.value,
            "timestamp": self.timestamp,
            "open": self.open, "high": self.high,
            "low": self.low, "close": self.close,
            "volume": self.volume, "trades": self.trades,
            "vwap": self.vwap,
        }


# ---------------------------------------------------------------------------
# Data feed protocol (pluggable)
# ---------------------------------------------------------------------------

class MarketDataFeed(Protocol):
    """
    Pluggable market data source.
    Implement this protocol to connect any data provider (file, API, WebSocket).
    """

    def stream(self, symbol: str, timeframe: TimeFrame) -> Iterator[OHLCBar]:
        """Yield bars in chronological order."""
        ...

    def latest(self, symbol: str) -> Optional[OHLCBar]:
        """Return the most recent bar for a symbol."""
        ...


# ---------------------------------------------------------------------------
# OHLC Aggregator (tick → bar)
# ---------------------------------------------------------------------------

class OHLCAggregator:
    """
    Aggregates a stream of Tick objects into OHLC bars.
    Groups ticks by a caller-supplied key function (e.g. minute bucket).
    """

    def __init__(self, bucket_fn: Optional[Callable[[str], str]] = None) -> None:
        """
        bucket_fn: maps a tick timestamp to a bar timestamp key.
        Default: truncate to minute (first 16 chars of ISO timestamp).
        """
        self._bucket_fn = bucket_fn or (lambda ts: ts[:16])
        self._buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def feed(self, tick: Tick) -> Optional[OHLCBar]:
        """
        Feed a tick. Returns a completed OHLCBar when a bucket closes
        (i.e. when a tick arrives for a new time bucket), else None.
        """
        key = (tick.symbol, self._bucket_fn(tick.timestamp))
        closed_bar: Optional[OHLCBar] = None

        # Check if previous bucket for this symbol should be closed
        prev_key = self._current_key(tick.symbol)
        if prev_key and prev_key != key and prev_key in self._buckets:
            closed_bar = self._close_bucket(prev_key)

        # Update current bucket
        if key not in self._buckets:
            self._buckets[key] = {
                "symbol": tick.symbol, "timestamp": key[1],
                "open": tick.price, "high": tick.price,
                "low": tick.price, "close": tick.price,
                "volume": 0.0, "trades": 0,
                "vwap_sum": 0.0, "vol_sum": 0.0,
            }
        b = self._buckets[key]
        b["high"]     = max(b["high"], tick.price)
        b["low"]      = min(b["low"],  tick.price)
        b["close"]    = tick.price
        b["volume"]  += tick.volume
        b["trades"]  += 1
        b["vwap_sum"] += tick.price * tick.volume
        b["vol_sum"]  += tick.volume

        return closed_bar

    def flush(self, symbol: str) -> Optional[OHLCBar]:
        """Force-close the current open bucket for a symbol."""
        key = self._current_key(symbol)
        if key:
            return self._close_bucket(key)
        return None

    def _current_key(self, symbol: str) -> Optional[Tuple[str, str]]:
        for k in self._buckets:
            if k[0] == symbol:
                return k
        return None

    def _close_bucket(self, key: Tuple[str, str]) -> OHLCBar:
        b = self._buckets.pop(key)
        vwap = (b["vwap_sum"] / b["vol_sum"]) if b["vol_sum"] > 0 else b["close"]
        return OHLCBar(
            symbol=b["symbol"], timeframe=TimeFrame.M1,
            timestamp=b["timestamp"],
            open=b["open"], high=b["high"],
            low=b["low"], close=b["close"],
            volume=b["volume"], trades=b["trades"],
            vwap=round(vwap, 8),
        )


# ---------------------------------------------------------------------------
# Data Validator
# ---------------------------------------------------------------------------

class DataValidator:
    """
    Validates a sequence of OHLCBars for common data quality issues.
    Returns a list of (index, issue_description) tuples.
    """

    def __init__(
        self,
        max_gap_multiplier: float = 3.0,    # flag bars where range > N × avg_range
        min_volume: float = 0.0,
    ) -> None:
        self._max_gap = max_gap_multiplier
        self._min_vol = min_volume

    def validate(self, bars: List[OHLCBar]) -> List[Tuple[int, str]]:
        """Return list of (bar_index, issue) for all detected anomalies."""
        issues: List[Tuple[int, str]] = []
        if not bars:
            return issues

        ranges = [b.range for b in bars if b.range > 0]
        avg_range = statistics.mean(ranges) if ranges else 0

        for i, bar in enumerate(bars):
            # OHLC consistency (already checked in __post_init__, but catch re-assigned)
            if bar.high < bar.low:
                issues.append((i, f"high < low ({bar.high} < {bar.low})"))
            if bar.volume < self._min_vol:
                issues.append((i, f"volume below minimum ({bar.volume} < {self._min_vol})"))
            if avg_range > 0 and bar.range > avg_range * self._max_gap:
                issues.append((i, f"abnormal range ({bar.range:.4f} > {self._max_gap}× avg {avg_range:.4f})"))
            # Consecutive price gap
            if i > 0 and avg_range > 0:
                gap = abs(bar.open - bars[i - 1].close)
                if gap > avg_range * self._max_gap:
                    issues.append((i, f"price gap between bars ({gap:.4f} > {self._max_gap}× avg range)"))

        return issues


# ---------------------------------------------------------------------------
# Normaliser
# ---------------------------------------------------------------------------

class Normalizer:
    """
    Normalises a list of float values or bar close prices.
    """

    @staticmethod
    def z_score(values: List[float]) -> List[float]:
        """Standardise to zero mean and unit variance."""
        if len(values) < 2:
            return [0.0] * len(values)
        mu  = statistics.mean(values)
        std = statistics.pstdev(values) or 1.0
        return [(v - mu) / std for v in values]

    @staticmethod
    def min_max(values: List[float], low: float = 0.0, high: float = 1.0) -> List[float]:
        """Scale to [low, high]."""
        if not values:
            return []
        vmin, vmax = min(values), max(values)
        span = vmax - vmin or 1.0
        return [low + (v - vmin) / span * (high - low) for v in values]

    @staticmethod
    def pct_change(values: List[float]) -> List[float]:
        """Percentage change from previous value."""
        if len(values) < 2:
            return [0.0] * len(values)
        result = [0.0]
        for i in range(1, len(values)):
            prev = values[i - 1]
            result.append(((values[i] - prev) / prev * 100) if prev != 0 else 0.0)
        return result

    @staticmethod
    def log_returns(values: List[float]) -> List[float]:
        """Natural log returns: ln(p_t / p_{t-1})."""
        if len(values) < 2:
            return [0.0] * len(values)
        result = [0.0]
        for i in range(1, len(values)):
            if values[i] > 0 and values[i - 1] > 0:
                result.append(math.log(values[i] / values[i - 1]))
            else:
                result.append(0.0)
        return result


# ---------------------------------------------------------------------------
# Market Data Store
# ---------------------------------------------------------------------------

class MarketDataStore:
    """
    Thread-safe in-memory store for OHLCBars, keyed by (symbol, timeframe).
    Provides sliding-window access and optional persistence hooks.
    """

    def __init__(self, max_bars_per_series: int = 5_000) -> None:
        self._max    = max_bars_per_series
        self._store: Dict[Tuple[str, str], List[OHLCBar]] = {}
        self._lock   = threading.RLock()

    def add(self, bar: OHLCBar) -> None:
        key = (bar.symbol, bar.timeframe.value)
        with self._lock:
            series = self._store.setdefault(key, [])
            series.append(bar)
            if len(series) > self._max:
                del series[0]

    def get(
        self,
        symbol: str,
        timeframe: TimeFrame = TimeFrame.D1,
        limit: int = 100,
    ) -> List[OHLCBar]:
        key = (symbol, timeframe.value)
        with self._lock:
            return list(self._store.get(key, [])[-limit:])

    def latest(self, symbol: str, timeframe: TimeFrame = TimeFrame.D1) -> Optional[OHLCBar]:
        bars = self.get(symbol, timeframe, limit=1)
        return bars[-1] if bars else None

    def symbols(self) -> List[str]:
        with self._lock:
            return sorted({k[0] for k in self._store})

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "series": len(self._store),
                "total_bars": sum(len(v) for v in self._store.values()),
                "symbols": self.symbols(),
            }
