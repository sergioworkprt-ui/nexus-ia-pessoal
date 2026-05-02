"""
NEXUS Profit Engine — Portfolio Manager
Position tracking, P&L calculation, allocation reporting, and rebalancing.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ._types import Fill, Position, Side, Trade


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------

@dataclass
class RebalanceAction:
    symbol:    str
    side:      Side
    amount:    float       # monetary amount to trade (not quantity)
    reason:    str

    def to_dict(self) -> Dict[str, Any]:
        return {"symbol": self.symbol, "side": self.side.value,
                "amount": round(self.amount, 4), "reason": self.reason}


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------

class PortfolioManager:
    """
    Tracks the complete portfolio state: cash, open positions, and trade history.

    Thread-safe. All monetary values are in the same base currency.

    Usage:
        pm = PortfolioManager(initial_capital=10_000)
        pm.open_position(fill)
        pm.update_prices({"AAPL": 155.0})
        print(pm.total_value)
        pm.close_position("AAPL", close_fill)
    """

    def __init__(self, initial_capital: float = 10_000.0) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive.")
        self._initial_capital = initial_capital
        self._cash            = initial_capital
        self._positions: Dict[str, Position] = {}      # symbol → Position
        self._trades:    List[Trade]          = []
        self._lock       = threading.RLock()

        # Peak value for drawdown calculation
        self._peak_value  = initial_capital
        self._realised_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def open_position(self, fill: Fill) -> Position:
        """
        Record a new position from a fill.
        If a position in the same symbol already exists, averages the entry price
        (scale-in). Raises ValueError for conflicting sides.
        """
        with self._lock:
            existing = self._positions.get(fill.symbol)
            if existing and existing.side != fill.side:
                raise ValueError(
                    f"Cannot open {fill.side.value} position in '{fill.symbol}': "
                    f"existing {existing.side.value} position must be closed first."
                )

            cost = fill.quantity * fill.price + fill.commission
            if fill.side is Side.BUY:
                if cost > self._cash:
                    raise ValueError(
                        f"Insufficient cash: need {cost:.2f}, have {self._cash:.2f}."
                    )
                self._cash -= cost
            else:
                # Short-sale: receive proceeds (simplified — no margin accounting)
                self._cash += fill.quantity * fill.price - fill.commission

            if existing:
                # Weighted average entry
                total_qty   = existing.quantity + fill.quantity
                avg_price   = (existing.entry_price * existing.quantity +
                                fill.price * fill.quantity) / total_qty
                existing.quantity    = total_qty
                existing.entry_price = avg_price
                existing.current_price = fill.price
                return existing

            position = Position(
                symbol        = fill.symbol,
                side          = fill.side,
                quantity      = fill.quantity,
                entry_price   = fill.price,
                current_price = fill.price,
                opened_at     = fill.timestamp,
            )
            self._positions[fill.symbol] = position
            return position

    def close_position(
        self,
        symbol: str,
        fill: Fill,
        partial: bool = False,
    ) -> Trade:
        """
        Close (or partially close) an open position using the provided fill.
        Returns the completed Trade.
        """
        with self._lock:
            pos = self._positions.get(symbol)
            if pos is None:
                raise KeyError(f"No open position for '{symbol}'.")

            close_qty = fill.quantity
            if close_qty > pos.quantity + 1e-9:
                raise ValueError(
                    f"Close quantity {close_qty} exceeds open quantity {pos.quantity} for '{symbol}'."
                )

            trade = Trade(
                symbol      = symbol,
                side        = pos.side,
                quantity    = close_qty,
                entry_price = pos.entry_price,
                exit_price  = fill.price,
                entry_time  = pos.opened_at,
                exit_time   = fill.timestamp,
                commission  = fill.commission,
            )
            self._realised_pnl += trade.pnl

            # Return cash from closing
            if pos.side is Side.BUY:
                self._cash += fill.quantity * fill.price - fill.commission
            else:
                # Buying back a short: pay at fill price
                self._cash -= fill.quantity * fill.price + fill.commission

            if partial and close_qty < pos.quantity - 1e-9:
                pos.quantity -= close_qty
            else:
                del self._positions[symbol]

            self._trades.append(trade)
            self._update_peak()
            return trade

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update current_price for all positions in the given price map."""
        with self._lock:
            for symbol, price in prices.items():
                if symbol in self._positions:
                    self._positions[symbol].current_price = price
            self._update_peak()

    # ------------------------------------------------------------------
    # Portfolio metrics
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        with self._lock:
            return self._cash

    @property
    def total_value(self) -> float:
        with self._lock:
            return self._cash + sum(p.market_value for p in self._positions.values())

    @property
    def unrealised_pnl(self) -> float:
        with self._lock:
            return sum(p.unrealised_pnl for p in self._positions.values())

    @property
    def realised_pnl(self) -> float:
        with self._lock:
            return self._realised_pnl

    @property
    def total_pnl(self) -> float:
        return self.realised_pnl + self.unrealised_pnl

    @property
    def total_return_pct(self) -> float:
        return (self.total_value / self._initial_capital - 1) * 100

    @property
    def drawdown_pct(self) -> float:
        with self._lock:
            tv = self.total_value
            if self._peak_value <= 0:
                return 0.0
            return max(0.0, (self._peak_value - tv) / self._peak_value * 100)

    # ------------------------------------------------------------------
    # Allocation & rebalancing
    # ------------------------------------------------------------------

    def allocation(self) -> Dict[str, float]:
        """Return each symbol's market value as a % of total portfolio value."""
        with self._lock:
            tv = self.total_value
            if tv <= 0:
                return {}
            return {
                sym: round(pos.market_value / tv * 100, 4)
                for sym, pos in self._positions.items()
            }

    def rebalance_suggestions(
        self,
        target_weights: Dict[str, float],   # symbol → target % of portfolio
    ) -> List[RebalanceAction]:
        """
        Compare current allocation to target weights and return
        a list of buy/sell actions needed to reach the target.
        target_weights values should sum to ≤ 100.
        """
        with self._lock:
            tv = self.total_value
            actions: List[RebalanceAction] = []
            current = self.allocation()

            for symbol, target_pct in target_weights.items():
                current_pct = current.get(symbol, 0.0)
                diff_pct    = target_pct - current_pct
                if abs(diff_pct) < 0.5:   # ignore tiny deviations
                    continue
                amount = abs(diff_pct / 100 * tv)
                side   = Side.BUY if diff_pct > 0 else Side.SELL
                actions.append(RebalanceAction(
                    symbol=symbol, side=side, amount=round(amount, 4),
                    reason=f"Rebalance: current {current_pct:.1f}% → target {target_pct:.1f}%",
                ))
            return actions

    def exposure_by_symbol(self) -> Dict[str, float]:
        """Return the monetary market value per symbol."""
        with self._lock:
            return {sym: round(pos.market_value, 4) for sym, pos in self._positions.items()}

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._positions.values()]

    def open_position_count(self) -> int:
        with self._lock:
            return len(self._positions)

    def trade_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in self._trades[-limit:]]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            wins  = sum(1 for t in self._trades if t.is_winner)
            total = len(self._trades)
            return {
                "initial_capital":   self._initial_capital,
                "total_value":       round(self.total_value, 4),
                "cash":              round(self._cash, 4),
                "unrealised_pnl":    round(self.unrealised_pnl, 4),
                "realised_pnl":      round(self._realised_pnl, 4),
                "total_return_pct":  round(self.total_return_pct, 4),
                "drawdown_pct":      round(self.drawdown_pct, 4),
                "open_positions":    len(self._positions),
                "total_trades":      total,
                "win_rate_pct":      round(wins / total * 100, 2) if total else 0.0,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_peak(self) -> None:
        tv = self._cash + sum(p.market_value for p in self._positions.values())
        if tv > self._peak_value:
            self._peak_value = tv
