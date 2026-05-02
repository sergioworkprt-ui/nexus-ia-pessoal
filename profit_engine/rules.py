"""
NEXUS Profit Engine — Trading Rules
Global safety rules: kill switch, circuit breakers, cooldowns, and session guards.
All checks raise TradingRulesViolation; callers must handle before sending any order.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Violation exception
# ---------------------------------------------------------------------------

class TradingRulesViolation(Exception):
    """Raised when a pre-trade rule check fails."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule   = rule
        self.detail = detail


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

class KillSwitch:
    """
    Manual emergency halt.
    When engaged, all trade checks fail immediately.
    Thread-safe.
    """

    def __init__(self) -> None:
        self._engaged  = threading.Event()
        self._reason:  Optional[str] = None
        self._engaged_at: Optional[str] = None

    def engage(self, reason: str = "manual") -> None:
        self._reason    = reason
        self._engaged_at = datetime.now(timezone.utc).isoformat()
        self._engaged.set()

    def disengage(self) -> None:
        self._reason    = None
        self._engaged_at = None
        self._engaged.clear()

    def check(self) -> None:
        if self._engaged.is_set():
            raise TradingRulesViolation(
                "KILL_SWITCH",
                f"Kill switch is engaged (reason: {self._reason!r}, since {self._engaged_at}). "
                "Call kill_switch.disengage() to resume.",
            )

    @property
    def is_engaged(self) -> bool:
        return self._engaged.is_set()

    def status(self) -> Dict[str, Any]:
        return {
            "engaged": self.is_engaged,
            "reason": self._reason,
            "engaged_at": self._engaged_at,
        }


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreakerConfig:
    max_consecutive_losses: int   = 3      # halt after N straight losses
    loss_window_seconds: float    = 3600   # sliding window for loss count
    cooldown_seconds: float       = 900    # pause duration after trigger (15 min)
    max_loss_events_in_window: int = 5     # total loss events allowed in window


class CircuitBreaker:
    """
    Pauses trading automatically after too many losses in a sliding window.
    Resets automatically after the cooldown period.
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None) -> None:
        self._cfg     = config or CircuitBreakerConfig()
        self._losses: Deque[float] = deque()   # monotonic timestamps of loss events
        self._consecutive = 0
        self._tripped_at: Optional[float] = None
        self._lock = threading.Lock()

    def record_loss(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._losses.append(now)
            self._consecutive += 1
            self._prune(now)
            # Trip if consecutive or window thresholds exceeded
            if (self._consecutive >= self._cfg.max_consecutive_losses or
                    len(self._losses) >= self._cfg.max_loss_events_in_window):
                self._tripped_at = now

    def record_win(self) -> None:
        with self._lock:
            self._consecutive = 0

    def check(self) -> None:
        with self._lock:
            if self._tripped_at is None:
                return
            elapsed = time.monotonic() - self._tripped_at
            if elapsed < self._cfg.cooldown_seconds:
                remaining = int(self._cfg.cooldown_seconds - elapsed)
                raise TradingRulesViolation(
                    "CIRCUIT_BREAKER",
                    f"Circuit breaker is open. Cooldown: {remaining}s remaining "
                    f"(consecutive losses: {self._consecutive}, "
                    f"window losses: {len(self._losses)}).",
                )
            # Auto-reset after cooldown
            self._tripped_at  = None
            self._consecutive = 0

    def reset(self) -> None:
        with self._lock:
            self._tripped_at  = None
            self._consecutive = 0
            self._losses.clear()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            tripped = self._tripped_at is not None
            cooldown_remaining = 0
            if tripped:
                elapsed = time.monotonic() - self._tripped_at  # type: ignore[operator]
                cooldown_remaining = max(0, int(self._cfg.cooldown_seconds - elapsed))
            return {
                "tripped": tripped,
                "consecutive_losses": self._consecutive,
                "window_losses": len(self._losses),
                "cooldown_remaining_seconds": cooldown_remaining,
            }

    def _prune(self, now: float) -> None:
        cutoff = now - self._cfg.loss_window_seconds
        while self._losses and self._losses[0] < cutoff:
            self._losses.popleft()


# ---------------------------------------------------------------------------
# Cooldown (per-symbol and global)
# ---------------------------------------------------------------------------

class Cooldown:
    """
    Enforces a minimum interval between trades, per symbol and globally.
    Prevents overtrading and revenge-trading patterns.
    """

    def __init__(
        self,
        per_symbol_seconds: float = 60.0,
        global_seconds: float = 5.0,
    ) -> None:
        self._per_symbol = per_symbol_seconds
        self._global     = global_seconds
        self._last_trade_symbol: Dict[str, float] = {}
        self._last_trade_global: float = 0.0
        self._lock = threading.Lock()

    def record_trade(self, symbol: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._last_trade_symbol[symbol] = now
            self._last_trade_global = now

    def check(self, symbol: str) -> None:
        now = time.monotonic()
        with self._lock:
            global_wait = self._global - (now - self._last_trade_global)
            if global_wait > 0:
                raise TradingRulesViolation(
                    "COOLDOWN_GLOBAL",
                    f"Global cooldown active: {global_wait:.1f}s remaining.",
                )
            last_sym = self._last_trade_symbol.get(symbol, 0.0)
            sym_wait = self._per_symbol - (now - last_sym)
            if sym_wait > 0:
                raise TradingRulesViolation(
                    "COOLDOWN_SYMBOL",
                    f"Per-symbol cooldown active for '{symbol}': {sym_wait:.1f}s remaining.",
                )

    def status(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            global_remaining = max(0.0, self._global - (now - self._last_trade_global))
            result: Dict[str, Any] = {"global_remaining_seconds": round(global_remaining, 2)}
            if symbol:
                last = self._last_trade_symbol.get(symbol, 0.0)
                result["symbol_remaining_seconds"] = round(max(0.0, self._per_symbol - (now - last)), 2)
            return result


# ---------------------------------------------------------------------------
# Session guard (trading hours)
# ---------------------------------------------------------------------------

class SessionGuard:
    """
    Blocks trading outside a configured UTC hour window.
    Uses 24-h format (e.g. open_hour=8, close_hour=22 → allow 08:00–22:00 UTC).
    """

    def __init__(self, open_hour: int = 0, close_hour: int = 24, active: bool = False) -> None:
        self._open  = open_hour
        self._close = close_hour
        self._active = active    # if False, guard is disabled (always allow)

    def check(self) -> None:
        if not self._active:
            return
        hour = datetime.now(timezone.utc).hour
        if not (self._open <= hour < self._close):
            raise TradingRulesViolation(
                "SESSION_CLOSED",
                f"Trading is only allowed between {self._open:02d}:00 and {self._close:02d}:00 UTC. "
                f"Current UTC hour: {hour:02d}.",
            )


# ---------------------------------------------------------------------------
# TradingRules — composite guard
# ---------------------------------------------------------------------------

class TradingRules:
    """
    Composite rule checker.
    Call check_before_trade(symbol) before submitting any order.
    All sub-rules must pass; the first failure raises TradingRulesViolation.
    """

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        cooldown: Optional[Cooldown] = None,
        session_guard: Optional[SessionGuard] = None,
    ) -> None:
        self.kill_switch     = kill_switch     or KillSwitch()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.cooldown        = cooldown        or Cooldown()
        self.session_guard   = session_guard   or SessionGuard()
        self._violation_log: List[Dict[str, Any]] = []

    def check_before_trade(self, symbol: str) -> None:
        """
        Run all rule checks in order.
        Raises TradingRulesViolation on the first failed check.
        Records every violation for audit purposes.
        """
        checks = [
            self.kill_switch.check,
            self.session_guard.check,
            self.circuit_breaker.check,
            lambda: self.cooldown.check(symbol),
        ]
        for check in checks:
            try:
                check()
            except TradingRulesViolation as exc:
                self._violation_log.append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "rule": exc.rule,
                    "detail": exc.detail,
                    "symbol": symbol,
                })
                raise

    def on_trade_executed(self, symbol: str) -> None:
        """Call this after every successful trade execution."""
        self.cooldown.record_trade(symbol)

    def on_loss(self) -> None:
        self.circuit_breaker.record_loss()

    def on_win(self) -> None:
        self.circuit_breaker.record_win()

    def status(self) -> Dict[str, Any]:
        return {
            "kill_switch":     self.kill_switch.status(),
            "circuit_breaker": self.circuit_breaker.status(),
        }

    def violation_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._violation_log[-limit:])
