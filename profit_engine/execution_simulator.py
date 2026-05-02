"""
NEXUS Profit Engine — Execution Simulator
Simulated order execution with configurable latency, slippage, commissions,
and partial fill probability. No broker dependency.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ._types import Bar, Fill, Order, OrderStatus, OrderType, Side


# ---------------------------------------------------------------------------
# Slippage models
# ---------------------------------------------------------------------------

class SlippageModel:
    """Base class for slippage models — override apply()."""

    def apply(self, price: float, side: Side, bar: Bar) -> float:
        """Return the execution price after slippage."""
        return price


class FixedBpsSlippage(SlippageModel):
    """Slippage expressed as fixed basis points of the mid price."""

    def __init__(self, bps: float = 2.0) -> None:
        self._bps = bps / 10_000

    def apply(self, price: float, side: Side, bar: Bar) -> float:
        adj = price * self._bps
        return price + adj if side is Side.BUY else price - adj


class SpreadSlippage(SlippageModel):
    """
    Models half-spread slippage: BUY fills at ask, SELL fills at bid.
    Spread is estimated as a fraction of the bar range.
    """

    def __init__(self, spread_fraction: float = 0.10) -> None:
        self._frac = spread_fraction   # fraction of (high - low) used as full spread

    def apply(self, price: float, side: Side, bar: Bar) -> float:
        half_spread = (bar.high - bar.low) * self._frac / 2
        return price + half_spread if side is Side.BUY else price - half_spread


# ---------------------------------------------------------------------------
# Execution configuration
# ---------------------------------------------------------------------------

@dataclass
class ExecutionConfig:
    commission_rate:          float = 0.001      # 0.1% of notional
    min_commission:           float = 1.0        # minimum flat commission per fill
    slippage_model:           SlippageModel = field(default_factory=FixedBpsSlippage)
    latency_ms:               float = 50.0       # simulated round-trip latency
    partial_fill_probability: float = 0.0        # 0.0 = always full fill
    partial_fill_min_pct:     float = 0.50       # if partial, fill at least this fraction
    random_seed:              Optional[int] = None


# ---------------------------------------------------------------------------
# Execution Simulator
# ---------------------------------------------------------------------------

class ExecutionSimulator:
    """
    Simulates order execution against OHLCV bars.

    Supports:
    - MARKET orders (filled at open or close + slippage)
    - LIMIT orders (filled only if bar trades through the limit)
    - STOP orders (triggered when bar trades through stop, then filled as market)
    - Partial fills and latency simulation
    - Commission calculation

    Pending limit/stop orders are held in an internal queue and processed
    bar-by-bar via process_pending().
    """

    def __init__(self, config: Optional[ExecutionConfig] = None) -> None:
        self._cfg     = config or ExecutionConfig()
        self._pending: List[Order] = []
        self._fills:   List[Fill]  = []
        self._rng     = random.Random(self._cfg.random_seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, order: Order, bar: Optional[Bar] = None) -> Optional[Fill]:
        """
        Submit an order for execution.
        - MARKET orders are filled immediately against the provided bar.
        - LIMIT / STOP orders are queued and processed on subsequent bars.
        Returns a Fill if executed immediately, else None.
        """
        if order.order_type is OrderType.MARKET:
            if bar is None:
                raise ValueError("MARKET orders require a bar for immediate execution.")
            return self._fill_market(order, bar)

        # Queue LIMIT / STOP / STOP_LIMIT
        self._pending.append(order)
        return None

    def process_pending(self, bar: Bar) -> List[Fill]:
        """
        Attempt to fill all pending orders against the current bar.
        Returns a list of Fills for orders that executed.
        """
        fills: List[Fill] = []
        still_pending: List[Order] = []

        for order in self._pending:
            if order.symbol != bar.symbol:
                still_pending.append(order)
                continue

            fill = self._try_fill_pending(order, bar)
            if fill:
                fills.append(fill)
            else:
                still_pending.append(order)

        self._pending = still_pending
        return fills

    def cancel_order(self, order_id: str) -> bool:
        before = len(self._pending)
        self._pending = [o for o in self._pending if o.order_id != order_id]
        return len(self._pending) < before

    def pending_orders(self) -> List[Dict[str, Any]]:
        return [o.to_dict() for o in self._pending]

    def fill_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [f.to_dict() for f in self._fills[-limit:]]

    def stats(self) -> Dict[str, Any]:
        total_commission = sum(f.commission for f in self._fills)
        total_slippage   = sum(abs(f.slippage) for f in self._fills)
        return {
            "total_fills": len(self._fills),
            "pending_orders": len(self._pending),
            "total_commission": round(total_commission, 4),
            "total_slippage": round(total_slippage, 4),
        }

    # ------------------------------------------------------------------
    # Internal fill logic
    # ------------------------------------------------------------------

    def _fill_market(self, order: Order, bar: Bar) -> Fill:
        """Fill a market order at bar.open (or close if open not available) + slippage."""
        raw_price  = bar.open if bar.open > 0 else bar.close
        exec_price = self._cfg.slippage_model.apply(raw_price, order.side, bar)
        exec_price = max(exec_price, 1e-9)   # never negative

        quantity    = self._partial_quantity(order.quantity)
        commission  = self._commission(quantity, exec_price)
        slippage_v  = (exec_price - raw_price) * quantity

        if self._cfg.latency_ms > 0:
            time.sleep(self._cfg.latency_ms / 1_000)   # simulate round-trip

        fill = Fill(
            order_id   = order.order_id,
            symbol     = order.symbol,
            side       = order.side,
            quantity   = quantity,
            price      = round(exec_price, 8),
            commission = round(commission, 6),
            timestamp  = datetime.now(timezone.utc).isoformat(),
            slippage   = round(slippage_v, 6),
        )
        order.status = OrderStatus.FILLED if quantity == order.quantity else OrderStatus.PARTIAL
        self._fills.append(fill)
        return fill

    def _try_fill_pending(self, order: Order, bar: Bar) -> Optional[Fill]:
        """Check if a LIMIT or STOP order can be filled by the current bar."""
        if order.order_type is OrderType.LIMIT:
            return self._try_fill_limit(order, bar)
        if order.order_type is OrderType.STOP:
            return self._try_fill_stop(order, bar)
        if order.order_type is OrderType.STOP_LIMIT:
            return self._try_fill_stop_limit(order, bar)
        return None

    def _try_fill_limit(self, order: Order, bar: Bar) -> Optional[Fill]:
        assert order.limit_price is not None
        lp = order.limit_price
        # BUY limit: fill if bar.low <= limit (price came down to limit)
        # SELL limit: fill if bar.high >= limit (price came up to limit)
        if order.side is Side.BUY and bar.low <= lp:
            exec_price = min(lp, bar.open)   # could open below limit
        elif order.side is Side.SELL and bar.high >= lp:
            exec_price = max(lp, bar.open)
        else:
            return None
        return self._build_fill(order, exec_price, bar)

    def _try_fill_stop(self, order: Order, bar: Bar) -> Optional[Fill]:
        assert order.stop_price is not None
        sp = order.stop_price
        # BUY stop: triggered when bar.high >= stop (breakout above)
        # SELL stop: triggered when bar.low <= stop (breakdown below)
        if order.side is Side.BUY and bar.high >= sp:
            raw_price = max(sp, bar.open)
        elif order.side is Side.SELL and bar.low <= sp:
            raw_price = min(sp, bar.open)
        else:
            return None
        exec_price = self._cfg.slippage_model.apply(raw_price, order.side, bar)
        return self._build_fill(order, exec_price, bar)

    def _try_fill_stop_limit(self, order: Order, bar: Bar) -> Optional[Fill]:
        assert order.stop_price is not None and order.limit_price is not None
        sp, lp = order.stop_price, order.limit_price
        # Trigger by stop first, then apply limit constraint
        if order.side is Side.BUY:
            if bar.high < sp:
                return None
            exec_price = min(max(sp, bar.open), lp)
            if exec_price > lp:
                return None
        else:
            if bar.low > sp:
                return None
            exec_price = max(min(sp, bar.open), lp)
            if exec_price < lp:
                return None
        return self._build_fill(order, exec_price, bar)

    def _build_fill(self, order: Order, exec_price: float, bar: Bar) -> Fill:
        slipped   = self._cfg.slippage_model.apply(exec_price, order.side, bar)
        quantity  = self._partial_quantity(order.quantity)
        commission = self._commission(quantity, slipped)
        order.status = OrderStatus.FILLED if quantity == order.quantity else OrderStatus.PARTIAL
        fill = Fill(
            order_id   = order.order_id,
            symbol     = order.symbol,
            side       = order.side,
            quantity   = quantity,
            price      = round(slipped, 8),
            commission = round(commission, 6),
            timestamp  = datetime.now(timezone.utc).isoformat(),
            slippage   = round((slipped - exec_price) * quantity, 6),
        )
        self._fills.append(fill)
        return fill

    def _partial_quantity(self, requested: float) -> float:
        if self._rng.random() < self._cfg.partial_fill_probability:
            frac = self._rng.uniform(self._cfg.partial_fill_min_pct, 1.0)
            return round(requested * frac, 8)
        return requested

    def _commission(self, quantity: float, price: float) -> float:
        notional = quantity * price
        return max(self._cfg.min_commission, notional * self._cfg.commission_rate)
