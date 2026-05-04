"""
NEXUS IBKR — Risk Manager
=========================
Enforces hard risk limits before any trade is placed against the
Interactive Brokers integration.

All public methods are thread-safe (backed by a reentrant lock).
State is persisted to JSON after every mutation so that a process
restart never loses the daily/weekly accumulators.

Hard caps (class-level constants)
----------------------------------
MAX_RISK_PER_TRADE = 0.005   # 0.5 % of capital per trade
MAX_DAILY_RISK     = 0.010   # 1.0 % of capital per day
MAX_WEEKLY_RISK    = 0.020   # 2.0 % of capital per week
MAX_DRAWDOWN       = 0.050   # 5.0 % drawdown → triggers safe mode

Typical usage
-------------
    risk = RiskManager.from_runtime(runtime)

    ok, reason = risk.validate_trade(capital=100_000, risk_amount=450)
    if not ok:
        logger.warning("Trade rejected: %s", reason)
        return

    qty = risk.compute_position_size(capital=100_000,
                                     price=185.50,
                                     sl_distance=1.25)
    # place order …
    risk.record_trade_risk(risk_amount=450)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, ClassVar, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

_ORDER_LOG_PATH = "logs/ibkr_orders.jsonl"


def _append_order_log(entry: Dict[str, Any]) -> None:
    """Append a JSON line to the IBKR order / risk log."""
    os.makedirs(os.path.dirname(_ORDER_LOG_PATH), exist_ok=True)
    entry.setdefault("ts", _now_iso())
    try:
        with open(_ORDER_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("risk_manager: failed to write order log: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def _week_start_iso() -> str:
    """ISO date of the Monday that starts the current ISO week."""
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


# ---------------------------------------------------------------------------
# RiskState dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskState:
    """Persistent state for the risk manager (daily + weekly accumulators)."""

    daily_risk_used:   float = 0.0
    weekly_risk_used:  float = 0.0
    current_drawdown:  float = 0.0
    peak_balance:      float = 0.0
    in_safe_mode:      bool  = False
    safe_mode_reason:  str   = ""
    day_start:         str   = field(default_factory=_today_iso)
    week_start:        str   = field(default_factory=_week_start_iso)
    last_updated:      str   = field(default_factory=_now_iso)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict suitable for JSON serialisation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskState":
        """Reconstruct a :class:`RiskState` from a plain dict."""
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------

class RiskManager:
    """
    Hard-limit risk gate for the NEXUS IBKR integration.

    All monetary values are expressed in the same currency as *capital*
    (typically USD).  Percentages are decimal fractions (0.005 = 0.5 %).

    Thread-safety
    -------------
    Every public method acquires ``self._lock`` (a :class:`threading.RLock`)
    before touching shared state, making the class safe to use from the
    scheduler and live-feed callbacks concurrently.

    Persistence
    -----------
    State is loaded from *state_path* on construction and saved after every
    mutation.  The default path is ``data/ibkr/risk_state.json``.

    Audit trail
    -----------
    Every risk event (safe-mode entry/exit, limit breach, drawdown update) is
    appended to ``logs/ibkr_orders.jsonl`` as a single JSON line so that a
    full history is available without a database.
    """

    # ------------------------------------------------------------------
    # Hard caps — class-level constants
    # ------------------------------------------------------------------

    MAX_RISK_PER_TRADE: ClassVar[float] = 0.005   # 0.5 % of capital
    MAX_DAILY_RISK:     ClassVar[float] = 0.010   # 1.0 % of capital
    MAX_WEEKLY_RISK:    ClassVar[float] = 0.020   # 2.0 % of capital
    MAX_DRAWDOWN:       ClassVar[float] = 0.050   # 5.0 % → triggers safe mode

    # ------------------------------------------------------------------
    # Construction / factory
    # ------------------------------------------------------------------

    def __init__(self, state_path: str = "data/ibkr/risk_state.json") -> None:
        self._state_path = state_path
        self._lock = threading.RLock()
        self._state: RiskState = self._load_or_create()

    @classmethod
    def from_runtime(cls, runtime: Any) -> "RiskManager":
        """
        Construct a :class:`RiskManager` from a live
        :class:`~nexus_runtime.runtime.NexusRuntime` instance.

        Falls back to the default *state_path* when the runtime does not
        expose a custom path.
        """
        state_path = getattr(runtime, "risk_state_path", "data/ibkr/risk_state.json")
        return cls(state_path=state_path)

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def compute_position_size(
        self,
        capital: float,
        price: float,
        sl_distance: float,
        max_risk_pct: Optional[float] = None,
    ) -> float:
        """
        Calculate the maximum position size using a fixed-fraction approach.

        Parameters
        ----------
        capital:
            Total trading capital in account currency.
        price:
            Current market price per share / contract.
        sl_distance:
            Absolute distance from entry to stop-loss in the same currency
            as *price* (e.g. ``1.50`` for a $1.50 stop).
        max_risk_pct:
            Override for the per-trade risk fraction.  Defaults to
            :attr:`MAX_RISK_PER_TRADE` (0.5 %).

        Returns
        -------
        float
            Number of units (shares / contracts) to trade, already clamped
            to ``[0, 10 % of capital / price]``.  Returns ``0.0`` on any
            invalid input.
        """
        if max_risk_pct is None:
            max_risk_pct = self.MAX_RISK_PER_TRADE

        # Guard against degenerate inputs
        if capital <= 0 or price <= 0 or sl_distance <= 0 or max_risk_pct <= 0:
            logger.debug(
                "compute_position_size: invalid input (capital=%s price=%s "
                "sl_distance=%s max_risk_pct=%s) → 0.0",
                capital, price, sl_distance, max_risk_pct,
            )
            return 0.0

        risk_amount = capital * max_risk_pct
        position_size = risk_amount / sl_distance

        # Upper bound: never hold more than 10 % of capital in a single position
        max_position = 0.1 * capital / price
        position_size = min(position_size, max_position)

        # Lower bound: never negative (sanity)
        position_size = max(0.0, position_size)

        return position_size

    # ------------------------------------------------------------------
    # Trade validation
    # ------------------------------------------------------------------

    def validate_trade(
        self,
        capital: float,
        risk_amount: float,
    ) -> Tuple[bool, str]:
        """
        Gate-check a proposed trade against all hard limits.

        Parameters
        ----------
        capital:
            Total trading capital used to compute percentage limits.
        risk_amount:
            Absolute currency amount at risk for the trade being validated.

        Returns
        -------
        ``(True, "")`` if the trade passes all checks, or
        ``(False, reason)`` describing the first limit that would be breached.
        """
        with self._lock:
            self._reset_daily_if_needed()
            self._reset_weekly_if_needed()

            # 1. Safe-mode check
            if self._state.in_safe_mode:
                reason = (
                    f"System is in safe mode: {self._state.safe_mode_reason}"
                )
                logger.warning("validate_trade rejected — safe mode: %s", reason)
                return False, reason

            if capital <= 0:
                return False, "Invalid capital value."

            # 2. Per-trade limit
            per_trade_limit = capital * self.MAX_RISK_PER_TRADE
            if risk_amount > per_trade_limit:
                reason = (
                    f"Per-trade risk {risk_amount:.2f} exceeds limit "
                    f"{per_trade_limit:.2f} ({self.MAX_RISK_PER_TRADE*100:.1f}% "
                    f"of capital)."
                )
                logger.warning("validate_trade rejected — per-trade limit: %s", reason)
                return False, reason

            # 3. Daily limit
            daily_ok, daily_reason = self.check_daily_limits(capital)
            if not daily_ok:
                return False, daily_reason

            projected_daily = self._state.daily_risk_used + risk_amount
            daily_cap = capital * self.MAX_DAILY_RISK
            if projected_daily > daily_cap:
                reason = (
                    f"Adding {risk_amount:.2f} would bring daily risk to "
                    f"{projected_daily:.2f}, exceeding daily cap "
                    f"{daily_cap:.2f} ({self.MAX_DAILY_RISK*100:.1f}% of capital)."
                )
                logger.warning("validate_trade rejected — daily projection: %s", reason)
                return False, reason

            # 4. Weekly limit
            weekly_ok, weekly_reason = self.check_weekly_limits(capital)
            if not weekly_ok:
                return False, weekly_reason

            projected_weekly = self._state.weekly_risk_used + risk_amount
            weekly_cap = capital * self.MAX_WEEKLY_RISK
            if projected_weekly > weekly_cap:
                reason = (
                    f"Adding {risk_amount:.2f} would bring weekly risk to "
                    f"{projected_weekly:.2f}, exceeding weekly cap "
                    f"{weekly_cap:.2f} ({self.MAX_WEEKLY_RISK*100:.1f}% of capital)."
                )
                logger.warning("validate_trade rejected — weekly projection: %s", reason)
                return False, reason

            return True, ""

    # ------------------------------------------------------------------
    # Post-trade accounting
    # ------------------------------------------------------------------

    def record_trade_risk(self, risk_amount: float) -> None:
        """
        Update daily and weekly risk accumulators after a trade is placed.

        This method must be called **after** the order is confirmed, not
        before validation.
        """
        with self._lock:
            self._reset_daily_if_needed()
            self._reset_weekly_if_needed()
            self._state.daily_risk_used += risk_amount
            self._state.weekly_risk_used += risk_amount
            self._state.last_updated = _now_iso()
            self.save()
            _append_order_log({
                "event": "trade_risk_recorded",
                "risk_amount": risk_amount,
                "daily_risk_used": self._state.daily_risk_used,
                "weekly_risk_used": self._state.weekly_risk_used,
            })

    # ------------------------------------------------------------------
    # Limit queries
    # ------------------------------------------------------------------

    def check_daily_limits(self, capital: float) -> Tuple[bool, str]:
        """
        Return ``(True, "")`` if daily risk capacity remains, or
        ``(False, reason)`` when the daily cap has been reached.
        """
        with self._lock:
            self._reset_daily_if_needed()
            daily_cap = capital * self.MAX_DAILY_RISK
            if self._state.daily_risk_used >= daily_cap:
                reason = (
                    f"Daily risk cap reached: used {self._state.daily_risk_used:.2f} "
                    f"/ limit {daily_cap:.2f} ({self.MAX_DAILY_RISK*100:.1f}% of capital)."
                )
                return False, reason
            return True, ""

    def check_weekly_limits(self, capital: float) -> Tuple[bool, str]:
        """
        Return ``(True, "")`` if weekly risk capacity remains, or
        ``(False, reason)`` when the weekly cap has been reached.
        """
        with self._lock:
            self._reset_weekly_if_needed()
            weekly_cap = capital * self.MAX_WEEKLY_RISK
            if self._state.weekly_risk_used >= weekly_cap:
                reason = (
                    f"Weekly risk cap reached: used {self._state.weekly_risk_used:.2f} "
                    f"/ limit {weekly_cap:.2f} ({self.MAX_WEEKLY_RISK*100:.1f}% of capital)."
                )
                return False, reason
            return True, ""

    def check_drawdown(
        self,
        current_balance: float,
        capital: float,
    ) -> Tuple[bool, str]:
        """
        Evaluate current drawdown against :attr:`MAX_DRAWDOWN`.

        Automatically triggers safe mode when the threshold is breached.

        Parameters
        ----------
        current_balance:
            Current account value.
        capital:
            Reference capital (used as denominator for drawdown %).

        Returns
        -------
        ``(True, "")`` if drawdown is within limits, otherwise
        ``(False, reason)`` and safe mode is activated.
        """
        with self._lock:
            if capital <= 0:
                return False, "Invalid capital value for drawdown check."
            drawdown = max(0.0, (capital - current_balance) / capital)
            self._state.current_drawdown = drawdown
            self._state.last_updated = _now_iso()
            if drawdown >= self.MAX_DRAWDOWN:
                reason = (
                    f"Drawdown {drawdown*100:.2f}% exceeds maximum "
                    f"{self.MAX_DRAWDOWN*100:.1f}%."
                )
                self.enter_safe_mode(reason)
                return False, reason
            return True, ""

    # ------------------------------------------------------------------
    # Balance / peak tracking
    # ------------------------------------------------------------------

    def update_balance(self, current_balance: float) -> None:
        """
        Update :attr:`~RiskState.peak_balance` and recalculate drawdown.

        If the new balance sets a new peak it is recorded; if drawdown
        breaches :attr:`MAX_DRAWDOWN` safe mode is activated automatically.
        """
        with self._lock:
            if current_balance > self._state.peak_balance:
                self._state.peak_balance = current_balance

            if self._state.peak_balance > 0:
                drawdown = max(
                    0.0,
                    (self._state.peak_balance - current_balance)
                    / self._state.peak_balance,
                )
                self._state.current_drawdown = drawdown
                if drawdown >= self.MAX_DRAWDOWN and not self._state.in_safe_mode:
                    reason = (
                        f"Balance drawdown {drawdown*100:.2f}% from peak "
                        f"{self._state.peak_balance:.2f} exceeds maximum "
                        f"{self.MAX_DRAWDOWN*100:.1f}%."
                    )
                    self.enter_safe_mode(reason)
            else:
                self._state.current_drawdown = 0.0

            self._state.last_updated = _now_iso()
            self.save()
            _append_order_log({
                "event": "balance_updated",
                "current_balance": current_balance,
                "peak_balance": self._state.peak_balance,
                "current_drawdown": self._state.current_drawdown,
            })

    # ------------------------------------------------------------------
    # Safe mode
    # ------------------------------------------------------------------

    def enter_safe_mode(self, reason: str) -> None:
        """Activate safe mode, preventing any new trades."""
        with self._lock:
            self._state.in_safe_mode = True
            self._state.safe_mode_reason = reason
            self._state.last_updated = _now_iso()
            self.save()
            logger.warning("RISK MANAGER — entering safe mode: %s", reason)
            _append_order_log({
                "event": "safe_mode_entered",
                "reason": reason,
            })

    def exit_safe_mode(self) -> None:
        """Deactivate safe mode, allowing trades to resume."""
        with self._lock:
            previous_reason = self._state.safe_mode_reason
            self._state.in_safe_mode = False
            self._state.safe_mode_reason = ""
            self._state.last_updated = _now_iso()
            self.save()
            logger.info(
                "RISK MANAGER — exiting safe mode (was: %s)", previous_reason
            )
            _append_order_log({
                "event": "safe_mode_exited",
                "previous_reason": previous_reason,
            })

    def is_safe_mode(self) -> bool:
        """Return ``True`` when the system is currently in safe mode."""
        with self._lock:
            return self._state.in_safe_mode

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """
        Return a comprehensive status dict containing live state and
        configured limits.  Suitable for health-check endpoints and
        dashboard rendering.
        """
        with self._lock:
            return {
                "state": self._state.to_dict(),
                "limits": {
                    "max_risk_per_trade_pct": self.MAX_RISK_PER_TRADE,
                    "max_daily_risk_pct":     self.MAX_DAILY_RISK,
                    "max_weekly_risk_pct":    self.MAX_WEEKLY_RISK,
                    "max_drawdown_pct":       self.MAX_DRAWDOWN,
                },
                "state_path": self._state_path,
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist current state to *state_path* (JSON)."""
        # Called from within a locked context in all mutating methods.
        # Acquire the lock again (RLock is reentrant) when called directly.
        with self._lock:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            tmp_path = self._state_path + ".tmp"
            try:
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump(self._state.to_dict(), fh, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self._state_path)
            except OSError as exc:
                logger.error("risk_manager: failed to save state: %s", exc)
                # Clean up stale tmp file if present
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    def load(self) -> None:
        """Reload state from *state_path*, replacing in-memory state."""
        with self._lock:
            self._state = self._load_or_create()

    # ------------------------------------------------------------------
    # Daily / weekly reset helpers
    # ------------------------------------------------------------------

    def _reset_daily_if_needed(self) -> None:
        """Reset daily accumulator if the calendar day has changed."""
        today = _today_iso()
        if self._state.day_start != today:
            old = self._state.daily_risk_used
            self._state.daily_risk_used = 0.0
            self._state.day_start = today
            self._state.last_updated = _now_iso()
            logger.info(
                "risk_manager: daily reset (was %.4f, new day %s)", old, today
            )
            _append_order_log({
                "event": "daily_reset",
                "previous_daily_risk_used": old,
                "new_day": today,
            })
            self.save()

    def _reset_weekly_if_needed(self) -> None:
        """Reset weekly accumulator if the ISO week has changed."""
        current_week_start = _week_start_iso()
        if self._state.week_start != current_week_start:
            old = self._state.weekly_risk_used
            self._state.weekly_risk_used = 0.0
            self._state.week_start = current_week_start
            self._state.last_updated = _now_iso()
            logger.info(
                "risk_manager: weekly reset (was %.4f, new week starting %s)",
                old,
                current_week_start,
            )
            _append_order_log({
                "event": "weekly_reset",
                "previous_weekly_risk_used": old,
                "new_week_start": current_week_start,
            })
            self.save()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_create(self) -> RiskState:
        """Load state from disk or return a fresh :class:`RiskState`."""
        if os.path.exists(self._state_path):
            try:
                with open(self._state_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                state = RiskState.from_dict(data)
                logger.info(
                    "risk_manager: loaded state from %s", self._state_path
                )
                return state
            except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.error(
                    "risk_manager: could not load state (%s), starting fresh", exc
                )
        return RiskState()
