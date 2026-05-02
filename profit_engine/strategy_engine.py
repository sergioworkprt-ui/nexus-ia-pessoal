"""
NEXUS Profit Engine — Strategy Engine
Strategy registration, signal generation, scoring, aggregation, and dispatch.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ._types import Bar, Order, OrderType, Side


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """
    A trading signal produced by a strategy.
    strength ∈ [0.0, 1.0] — 1.0 = maximum conviction.
    """
    symbol:        str
    side:          Side
    strength:      float           # 0.0 – 1.0
    strategy_name: str
    signal_id:     str  = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp:     str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stop_loss:     Optional[float] = None
    take_profit:   Optional[float] = None
    metadata:      Dict[str, Any]  = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"Signal strength must be in [0, 1], got {self.strength}.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id":     self.signal_id,
            "symbol":        self.symbol,
            "side":          self.side.value,
            "strength":      round(self.strength, 4),
            "strategy":      self.strategy_name,
            "stop_loss":     self.stop_loss,
            "take_profit":   self.take_profit,
            "timestamp":     self.timestamp,
        }


# ---------------------------------------------------------------------------
# Market data snapshot
# ---------------------------------------------------------------------------

@dataclass
class MarketSnapshot:
    """
    A point-in-time view of market data passed to strategy.generate().
    bars: most-recent bar per symbol.
    history: ordered list of recent bars per symbol (oldest first).
    indicators: pre-computed values (e.g. {"AAPL": {"sma_20": 150.3, "rsi": 58.2}}).
    """
    bars:       Dict[str, Bar]              = field(default_factory=dict)
    history:    Dict[str, List[Bar]]        = field(default_factory=dict)
    indicators: Dict[str, Dict[str, float]] = field(default_factory=dict)
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def latest_price(self, symbol: str) -> Optional[float]:
        bar = self.bars.get(symbol)
        return bar.close if bar else None


# ---------------------------------------------------------------------------
# Strategy base class
# ---------------------------------------------------------------------------

class Strategy(ABC):
    """
    Abstract base for all NEXUS trading strategies.
    Subclass and implement generate() to produce signals from market data.
    """

    def __init__(self, name: str, symbols: List[str]) -> None:
        self.name    = name
        self.symbols = symbols
        self.enabled = True
        self._call_count = 0

    @abstractmethod
    def generate(self, snapshot: MarketSnapshot) -> List[Signal]:
        """Analyse the market snapshot and return zero or more Signals."""
        ...

    def on_fill(self, signal: Signal, fill: Any) -> None:
        """Optional hook called when a signal's order is filled."""

    def stats(self) -> Dict[str, Any]:
        return {"name": self.name, "symbols": self.symbols,
                "enabled": self.enabled, "calls": self._call_count}

    def _emit(self, symbol: str, side: Side, strength: float, **kwargs: Any) -> Signal:
        """Helper for subclasses to build a Signal."""
        return Signal(symbol=symbol, side=side, strength=strength,
                      strategy_name=self.name, **kwargs)


# ---------------------------------------------------------------------------
# Built-in example strategy: Moving Average Crossover
# ---------------------------------------------------------------------------

class MovingAverageCrossover(Strategy):
    """
    Simple MA crossover: generates BUY when fast > slow, SELL otherwise.
    Uses indicator values from the snapshot if available.
    """

    def __init__(
        self,
        symbols: List[str],
        fast_key: str = "sma_10",
        slow_key: str = "sma_30",
        min_gap_pct: float = 0.1,
    ) -> None:
        super().__init__("ma_crossover", symbols)
        self._fast    = fast_key
        self._slow    = slow_key
        self._min_gap = min_gap_pct / 100

    def generate(self, snapshot: MarketSnapshot) -> List[Signal]:
        self._call_count += 1
        signals: List[Signal] = []
        for symbol in self.symbols:
            if not self.enabled:
                continue
            ind = snapshot.indicators.get(symbol, {})
            fast = ind.get(self._fast)
            slow = ind.get(self._slow)
            if fast is None or slow is None or slow == 0:
                continue
            gap = (fast - slow) / slow
            if abs(gap) < self._min_gap:
                continue   # no clear crossover
            side     = Side.BUY if gap > 0 else Side.SELL
            strength = min(abs(gap) * 10, 1.0)   # scale gap to [0,1]
            signals.append(self._emit(symbol, side, strength))
        return signals


# ---------------------------------------------------------------------------
# Signal aggregator
# ---------------------------------------------------------------------------

class SignalAggregator:
    """
    Combines signals from multiple strategies for the same symbol.
    Default: weighted average of strengths, tie-break by count.
    """

    def aggregate(self, signals: List[Signal]) -> List[Signal]:
        """
        Return one consensus signal per (symbol, side) pair,
        with strength = weighted mean of constituent signals.
        """
        groups: Dict[tuple, List[Signal]] = {}
        for sig in signals:
            key = (sig.symbol, sig.side)
            groups.setdefault(key, []).append(sig)

        result: List[Signal] = []
        for (symbol, side), group in groups.items():
            avg_strength = sum(s.strength for s in group) / len(group)
            best = max(group, key=lambda s: s.strength)
            consensus = Signal(
                symbol=symbol,
                side=side,
                strength=round(avg_strength, 4),
                strategy_name=",".join(sorted({s.strategy_name for s in group})),
                stop_loss=best.stop_loss,
                take_profit=best.take_profit,
                metadata={"source_count": len(group)},
            )
            result.append(consensus)

        # Sort by strength descending
        result.sort(key=lambda s: s.strength, reverse=True)
        return result


# ---------------------------------------------------------------------------
# Strategy Engine
# ---------------------------------------------------------------------------

class StrategyEngine:
    """
    Registry and execution hub for all trading strategies.

    Usage:
        engine = StrategyEngine()
        engine.register(MovingAverageCrossover(symbols=["AAPL"]))
        signals = engine.run(snapshot)
        top = engine.top_signals(signals, limit=5)
    """

    def __init__(self, aggregator: Optional[SignalAggregator] = None) -> None:
        self._strategies:  Dict[str, Strategy] = {}
        self._aggregator   = aggregator or SignalAggregator()
        self._signal_log:  List[Signal] = []
        self._hooks:       List[Callable[[List[Signal]], None]] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, strategy: Strategy) -> None:
        self._strategies[strategy.name] = strategy

    def unregister(self, name: str) -> bool:
        return self._strategies.pop(name, None) is not None

    def enable(self, name: str) -> None:
        if name in self._strategies:
            self._strategies[name].enabled = True

    def disable(self, name: str) -> None:
        if name in self._strategies:
            self._strategies[name].enabled = False

    def add_signal_hook(self, fn: Callable[[List[Signal]], None]) -> None:
        """Register a callback invoked after every run() with the raw signal list."""
        self._hooks.append(fn)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, snapshot: MarketSnapshot, aggregate: bool = True) -> List[Signal]:
        """
        Run all enabled strategies and return signals.
        If aggregate=True, combines signals per symbol via the aggregator.
        """
        raw: List[Signal] = []
        for strategy in self._strategies.values():
            if strategy.enabled:
                try:
                    raw.extend(strategy.generate(snapshot))
                except Exception:
                    pass   # strategy errors must not crash the engine

        for hook in self._hooks:
            try:
                hook(raw)
            except Exception:
                pass

        result = self._aggregator.aggregate(raw) if aggregate else raw
        self._signal_log.extend(result)
        return result

    def top_signals(
        self,
        signals: List[Signal],
        limit: int = 5,
        min_strength: float = 0.3,
    ) -> List[Signal]:
        """Filter and return the highest-conviction signals."""
        return [s for s in signals if s.strength >= min_strength][:limit]

    def signals_to_orders(
        self,
        signals: List[Signal],
        quantity_fn: Callable[[Signal], float],
        order_type: OrderType = OrderType.MARKET,
    ) -> List[Order]:
        """Convert signals to Orders using a caller-supplied quantity function."""
        orders: List[Order] = []
        for sig in signals:
            qty = quantity_fn(sig)
            if qty <= 0:
                continue
            orders.append(Order(
                symbol=sig.symbol,
                side=sig.side,
                order_type=order_type,
                quantity=qty,
                metadata={"signal_id": sig.signal_id, "strength": sig.strength},
            ))
        return orders

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_strategies(self) -> List[Dict[str, Any]]:
        return [s.stats() for s in self._strategies.values()]

    def signal_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._signal_log[-limit:]]

    def stats(self) -> Dict[str, Any]:
        return {
            "registered_strategies": len(self._strategies),
            "enabled_strategies": sum(1 for s in self._strategies.values() if s.enabled),
            "total_signals_generated": len(self._signal_log),
        }
