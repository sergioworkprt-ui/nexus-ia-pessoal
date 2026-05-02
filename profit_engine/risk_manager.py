"""
NEXUS Profit Engine — Risk Manager
Per-trade limits, daily loss limits, exposure caps, and hard-stop logic.
All violations raise RiskViolation before any order reaches execution.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional

from ._types import Order, Side


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RiskViolation(Exception):
    """Raised when a proposed trade breaches a risk limit."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule   = rule
        self.detail = detail


# ---------------------------------------------------------------------------
# Risk limits configuration
# ---------------------------------------------------------------------------

@dataclass
class RiskLimits:
    """
    All limits are expressed in absolute currency units unless noted with '_pct'.
    Set a limit to None to disable it.
    """
    # Per-trade limits
    max_loss_per_trade:      Optional[float] = 500.0     # max monetary loss on a single trade
    max_order_value:         Optional[float] = 10_000.0  # max notional value of a single order
    max_position_size_pct:   Optional[float] = 10.0      # max % of portfolio in one symbol

    # Daily limits
    max_daily_loss:          Optional[float] = 1_000.0   # cumulative loss cap per trading day
    max_daily_trades:        Optional[int]   = 20        # max number of trades per day

    # Portfolio-level limits
    max_open_positions:      Optional[int]   = 10        # max concurrent open positions
    max_total_exposure_pct:  Optional[float] = 80.0      # max % of capital deployed

    # Drawdown
    max_drawdown_pct:        Optional[float] = 20.0      # halt if portfolio drops > N% from peak

    # Concentration (per symbol across all positions)
    max_symbol_exposure_pct: Optional[float] = 20.0      # max % of portfolio in one symbol (all sides)


# ---------------------------------------------------------------------------
# Risk Manager
# ---------------------------------------------------------------------------

class RiskManager:
    """
    Enforces all configured risk limits before and after trade execution.

    Usage:
        rm = RiskManager(limits=RiskLimits(max_daily_loss=500))
        rm.check_order(order, portfolio_value=10000, open_positions=3)
        # ... execute order ...
        rm.record_fill(pnl=-120)  # record realised P&L
    """

    def __init__(self, limits: Optional[RiskLimits] = None) -> None:
        self._limits    = limits or RiskLimits()
        self._lock      = threading.Lock()

        # Daily tracking (reset at midnight UTC)
        self._daily_date:     Optional[date] = None
        self._daily_loss:     float = 0.0
        self._daily_trades:   int   = 0

        # Peak value tracking for drawdown
        self._peak_value:     float = 0.0

        # Audit log
        self._violations: List[Dict[str, Any]] = []
        self._fill_log:   List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-trade checks
    # ------------------------------------------------------------------

    def check_order(
        self,
        order: Order,
        portfolio_value: float,
        current_price: float,
        open_positions: int = 0,
        symbol_exposure: float = 0.0,   # current monetary exposure in this symbol
        total_exposure: float = 0.0,    # current total deployed capital
    ) -> None:
        """
        Validate a proposed order against all applicable risk limits.
        Raises RiskViolation on the first breach found.
        """
        self._refresh_daily()
        lim = self._limits

        notional = order.quantity * current_price

        # Kill switch: max_daily_loss already hit
        self._check_daily_loss_not_exceeded()

        # Max order value
        if lim.max_order_value is not None and notional > lim.max_order_value:
            self._raise(
                "MAX_ORDER_VALUE",
                f"Order notional {notional:.2f} exceeds limit {lim.max_order_value:.2f}.",
            )

        # Max position size % of portfolio
        if lim.max_position_size_pct is not None and portfolio_value > 0:
            pct = (notional / portfolio_value) * 100
            if pct > lim.max_position_size_pct:
                self._raise(
                    "MAX_POSITION_SIZE_PCT",
                    f"Order is {pct:.1f}% of portfolio; limit is {lim.max_position_size_pct:.1f}%.",
                )

        # Max open positions
        if lim.max_open_positions is not None and open_positions >= lim.max_open_positions:
            self._raise(
                "MAX_OPEN_POSITIONS",
                f"Already at maximum open positions ({lim.max_open_positions}).",
            )

        # Max total exposure
        if lim.max_total_exposure_pct is not None and portfolio_value > 0:
            new_exposure = total_exposure + notional
            exp_pct = (new_exposure / portfolio_value) * 100
            if exp_pct > lim.max_total_exposure_pct:
                self._raise(
                    "MAX_TOTAL_EXPOSURE",
                    f"Total exposure would reach {exp_pct:.1f}% of portfolio; "
                    f"limit is {lim.max_total_exposure_pct:.1f}%.",
                )

        # Max symbol concentration
        if lim.max_symbol_exposure_pct is not None and portfolio_value > 0:
            new_sym_exp = symbol_exposure + notional
            sym_pct = (new_sym_exp / portfolio_value) * 100
            if sym_pct > lim.max_symbol_exposure_pct:
                self._raise(
                    "MAX_SYMBOL_EXPOSURE",
                    f"Symbol '{order.symbol}' exposure would be {sym_pct:.1f}%; "
                    f"limit is {lim.max_symbol_exposure_pct:.1f}%.",
                )

        # Max daily trades
        with self._lock:
            if lim.max_daily_trades is not None and self._daily_trades >= lim.max_daily_trades:
                self._raise(
                    "MAX_DAILY_TRADES",
                    f"Already executed {self._daily_trades} trades today; "
                    f"limit is {lim.max_daily_trades}.",
                )

    def check_max_loss_per_trade(self, potential_loss: float) -> None:
        """Check a potential loss value against the per-trade limit (call before sizing)."""
        lim = self._limits
        if lim.max_loss_per_trade is not None and potential_loss > lim.max_loss_per_trade:
            self._raise(
                "MAX_LOSS_PER_TRADE",
                f"Potential loss {potential_loss:.2f} exceeds per-trade limit "
                f"{lim.max_loss_per_trade:.2f}.",
            )

    def check_drawdown(self, current_value: float) -> None:
        """Update peak and raise if max drawdown is breached."""
        with self._lock:
            if current_value > self._peak_value:
                self._peak_value = current_value
            if self._limits.max_drawdown_pct is not None and self._peak_value > 0:
                dd_pct = ((self._peak_value - current_value) / self._peak_value) * 100
                if dd_pct > self._limits.max_drawdown_pct:
                    self._raise(
                        "MAX_DRAWDOWN",
                        f"Portfolio drawdown is {dd_pct:.1f}%; limit is "
                        f"{self._limits.max_drawdown_pct:.1f}%. Hard stop triggered.",
                    )

    # ------------------------------------------------------------------
    # Post-trade recording
    # ------------------------------------------------------------------

    def record_fill(self, pnl: float, symbol: str = "") -> None:
        """Record a realised P&L from a completed trade."""
        self._refresh_daily()
        with self._lock:
            self._daily_trades += 1
            if pnl < 0:
                self._daily_loss += abs(pnl)
            self._fill_log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "pnl": pnl,
                "daily_loss_so_far": self._daily_loss,
            })

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def daily_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "date": str(self._daily_date),
                "daily_loss": round(self._daily_loss, 4),
                "daily_trades": self._daily_trades,
                "daily_loss_limit": self._limits.max_daily_loss,
                "daily_trades_limit": self._limits.max_daily_trades,
            }

    def violations(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._violations[-limit:])

    def update_limits(self, limits: RiskLimits) -> None:
        with self._lock:
            self._limits = limits

    def snapshot_limits(self) -> Dict[str, Any]:
        lim = self._limits
        return {k: v for k, v in lim.__dict__.items()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_daily_loss_not_exceeded(self) -> None:
        with self._lock:
            lim = self._limits.max_daily_loss
            if lim is not None and self._daily_loss >= lim:
                self._raise(
                    "MAX_DAILY_LOSS",
                    f"Daily loss of {self._daily_loss:.2f} has reached the limit of {lim:.2f}. "
                    "No further trades allowed today.",
                )

    def _refresh_daily(self) -> None:
        today = datetime.now(timezone.utc).date()
        with self._lock:
            if self._daily_date != today:
                self._daily_date  = today
                self._daily_loss  = 0.0
                self._daily_trades = 0

    def _raise(self, rule: str, detail: str) -> None:
        self._violations.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "rule": rule,
            "detail": detail,
        })
        raise RiskViolation(rule, detail)
