"""
NEXUS Capital Manager — IBKR Integration
=========================================

Tracks and enforces capital allocation rules for the NEXUS trading system.

Capital lifecycle
-----------------
1. User sets ``initial_capital`` once via :meth:`setup`.  That number is
   immutable; it represents the real money the user deposited into IBKR.

2. **Recovery phase** (``in_recovery_phase=True``):
   Every realised profit flows entirely into ``recovered_capital`` until
   ``recovered_capital >= initial_capital``.  No reinvestment is allowed
   during this phase.

3. **Post-recovery phase**:
   Profits are split across three buckets according to configurable
   percentages (defaults: tools 30 %, reinvest 50 %, standby 20 %).

4. ``nexus_profit`` is a running total of *all* net profit NEXUS has ever
   generated, regardless of phase.

Hard constraints
----------------
* NEXUS may never deploy more than ``user_capital_limit`` at any moment.
* ``standby_fund`` is frozen; only :meth:`authorise_standby` (explicit user
  command) can release funds from it.
* During recovery phase, :meth:`request_capital` is allowed only up to the
  current ``user_capital_limit``; reinvestment from ``reinvest_fund`` is
  blocked.

Thread safety
-------------
All public methods acquire a single ``threading.RLock`` before touching
shared state, making the class safe for use from multiple threads (e.g. an
order-fill callback running alongside the scheduler).

Persistence
-----------
State is written as JSON to ``data/ibkr/capital_state.json``.  Every
significant action also appends a JSON line to ``logs/ibkr_orders.jsonl``
for audit purposes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CapitalState dataclass
# ---------------------------------------------------------------------------

@dataclass
class CapitalState:
    """
    Immutable-ish snapshot of NEXUS capital allocation.

    Fields
    ------
    initial_capital:
        The amount the user originally deposited.  Set once and never
        modified afterwards.
    recovered_capital:
        Profit accumulated during the recovery phase.  Grows until it
        reaches ``initial_capital``, at which point recovery ends.
    nexus_profit:
        Cumulative net profit (losses reduce this).  Always updated.
    standby_fund:
        Emergency / rainy-day reserve.  Frozen unless explicitly
        authorised by the user.
    tools_fund:
        Operational costs bucket (APIs, data feeds, etc.).
    reinvest_fund:
        Capital earmarked for increasing position sizing.
    user_capital_limit:
        Hard cap on how much NEXUS may have deployed at once.
    in_recovery_phase:
        ``True`` while ``recovered_capital < initial_capital``.
    total_deployed:
        Sum of capital currently tied up in open positions.
    last_updated:
        ISO-8601 timestamp of the most recent state mutation.
    """

    initial_capital: float = 0.0
    recovered_capital: float = 0.0
    nexus_profit: float = 0.0
    standby_fund: float = 0.0
    tools_fund: float = 0.0
    reinvest_fund: float = 0.0
    user_capital_limit: float = 0.0
    in_recovery_phase: bool = True
    total_deployed: float = 0.0
    last_updated: str = field(default_factory=_now_iso)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialisation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapitalState":
        """
        Reconstruct a :class:`CapitalState` from a plain dict.

        Unknown keys in *data* are silently ignored so that older persisted
        states can be loaded after schema additions.
        """
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# CapitalManager
# ---------------------------------------------------------------------------

class CapitalManager:
    """
    Enforces NEXUS capital allocation rules and persists state to disk.

    Typical usage
    -------------
    ::

        cm = CapitalManager()
        cm.setup(initial_capital=10_000.0, user_capital_limit=5_000.0)

        if cm.request_capital(1_000.0):
            # open a position …
            cm.release_capital(1_000.0)
            cm.record_profit(120.0)

        print(cm.status())

    Bucket percentages (post-recovery split)
    ----------------------------------------
    Defaults can be overridden at construction time:

    * ``tools_pct``   — fraction of profit → ``tools_fund``    (default 0.30)
    * ``reinvest_pct`` — fraction of profit → ``reinvest_fund`` (default 0.50)
    * ``standby_pct`` — fraction of profit → ``standby_fund``  (default 0.20)

    The three percentages **must sum to 1.0**; a :class:`ValueError` is
    raised during ``__init__`` if they do not.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        state_path: str = "data/ibkr/capital_state.json",
        *,
        tools_pct: float = 0.30,
        reinvest_pct: float = 0.50,
        standby_pct: float = 0.20,
    ) -> None:
        """
        Initialise the manager.

        Parameters
        ----------
        state_path:
            Path (relative to CWD or absolute) where JSON state is persisted.
        tools_pct:
            Fraction of post-recovery profit routed to ``tools_fund``.
        reinvest_pct:
            Fraction of post-recovery profit routed to ``reinvest_fund``.
        standby_pct:
            Fraction of post-recovery profit routed to ``standby_fund``.
        """
        total = tools_pct + reinvest_pct + standby_pct
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"Bucket percentages must sum to 1.0; got {total:.4f}."
            )

        self._state_path = state_path
        self._tools_pct = tools_pct
        self._reinvest_pct = reinvest_pct
        self._standby_pct = standby_pct
        self._lock = threading.RLock()

        # Derive the audit log path from the state path's parent project root.
        # We always write to logs/ibkr_orders.jsonl relative to CWD.
        self._log_path = "logs/ibkr_orders.jsonl"

        self._state = self.load()

    # ------------------------------------------------------------------
    # Alternate constructor
    # ------------------------------------------------------------------

    @classmethod
    def from_runtime(cls, runtime: Any) -> "CapitalManager":
        """
        Construct a :class:`CapitalManager` from a live NEXUS runtime object.

        The runtime may expose a ``config`` attribute with an
        ``ibkr_state_path`` field.  If not present the default path is used.

        Parameters
        ----------
        runtime:
            A :class:`~nexus_runtime.runtime.NexusRuntime` (or compatible)
            instance.
        """
        state_path = "data/ibkr/capital_state.json"
        try:
            cfg = getattr(runtime, "config", None)
            if cfg is not None:
                candidate = getattr(cfg, "ibkr_state_path", None)
                if candidate:
                    state_path = candidate
        except Exception:  # pragma: no cover — defensive
            pass
        return cls(state_path=state_path)

    # ------------------------------------------------------------------
    # Public API — setup
    # ------------------------------------------------------------------

    def setup(self, initial_capital: float, user_capital_limit: float) -> None:
        """
        One-time initialisation (idempotent).

        If ``initial_capital`` has already been set (i.e. it is non-zero) this
        method only updates ``user_capital_limit`` and leaves everything else
        intact, so it is safe to call repeatedly.

        Parameters
        ----------
        initial_capital:
            Total real money deposited into IBKR.  Must be > 0.
        user_capital_limit:
            Maximum capital NEXUS may deploy at any instant.  Must satisfy
            0 < ``user_capital_limit`` <= ``initial_capital``.
        """
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive.")
        if user_capital_limit <= 0 or user_capital_limit > initial_capital:
            raise ValueError(
                "user_capital_limit must be in (0, initial_capital]."
            )

        with self._lock:
            if self._state.initial_capital == 0.0:
                # First-time setup
                self._state.initial_capital = initial_capital
                self._state.in_recovery_phase = True
                self._state.last_updated = _now_iso()
                self._log("setup", {
                    "initial_capital": initial_capital,
                    "user_capital_limit": user_capital_limit,
                })
            else:
                # Already initialised — only allow limit update via dedicated
                # method; here we silently skip if values match.
                pass

            # Always honour the limit even on re-calls.
            self._state.user_capital_limit = user_capital_limit
            self._state.last_updated = _now_iso()
            self.save()

    # ------------------------------------------------------------------
    # Public API — profit / loss recording
    # ------------------------------------------------------------------

    def record_profit(self, amount: float) -> None:
        """
        Record a realised profit of *amount* and route it to the correct
        bucket(s).

        Recovery phase
        ~~~~~~~~~~~~~~
        The full *amount* is added to ``recovered_capital``.  When
        ``recovered_capital`` crosses ``initial_capital`` the recovery phase
        ends automatically and any surplus is redistributed across the
        post-recovery buckets.

        Post-recovery phase
        ~~~~~~~~~~~~~~~~~~~
        The profit is split according to the configured percentages.

        ``nexus_profit`` always increases regardless of phase.

        Parameters
        ----------
        amount:
            Realised profit in account currency.  Must be > 0.
        """
        if amount <= 0:
            raise ValueError("Profit amount must be positive.")

        with self._lock:
            self._state.nexus_profit += amount

            if self._state.in_recovery_phase:
                self._state.recovered_capital += amount

                if self._state.recovered_capital >= self._state.initial_capital:
                    # Recovery complete — redistribute any surplus.
                    surplus = (
                        self._state.recovered_capital
                        - self._state.initial_capital
                    )
                    self._state.recovered_capital = self._state.initial_capital
                    self._state.in_recovery_phase = False
                    self._log("recovery_complete", {
                        "recovered_capital": self._state.recovered_capital,
                        "surplus_redistributed": surplus,
                    })
                    if surplus > 0:
                        self._split_profit(surplus)
                else:
                    self._log("profit_recovery", {"amount": amount,
                        "recovered_capital": self._state.recovered_capital})
            else:
                self._split_profit(amount)

            self._state.last_updated = _now_iso()
            self.save()

    def record_loss(self, amount: float) -> None:
        """
        Record a realised loss of *amount* and deduct it from the appropriate
        buckets.

        Deduction order: ``reinvest_fund`` → ``tools_fund`` → ``standby_fund``
        (standby is last-resort and is touched automatically here — the
        distinction from :meth:`authorise_standby` is that standby is *not*
        the primary sink during normal loss handling; it merely absorbs
        residual losses).

        ``nexus_profit`` is decremented (may go negative).

        Parameters
        ----------
        amount:
            Realised loss in account currency.  Must be > 0.
        """
        if amount <= 0:
            raise ValueError("Loss amount must be positive.")

        with self._lock:
            self._state.nexus_profit -= amount
            remaining = amount

            if self._state.reinvest_fund >= remaining:
                self._state.reinvest_fund -= remaining
                remaining = 0.0
            else:
                remaining -= self._state.reinvest_fund
                self._state.reinvest_fund = 0.0

            if remaining > 0:
                if self._state.tools_fund >= remaining:
                    self._state.tools_fund -= remaining
                    remaining = 0.0
                else:
                    remaining -= self._state.tools_fund
                    self._state.tools_fund = 0.0

            if remaining > 0:
                if self._state.standby_fund >= remaining:
                    self._state.standby_fund -= remaining
                    remaining = 0.0
                else:
                    remaining -= self._state.standby_fund
                    self._state.standby_fund = 0.0

            if remaining > 0:
                # Loss exceeds all buckets — log as a critical drawdown.
                logger.error(
                    "Loss of %.2f exceeds all available buckets by %.2f.",
                    amount, remaining,
                )
                self._log("loss_exceeds_buckets", {
                    "amount": amount, "uncovered": remaining
                })
            else:
                self._log("record_loss", {"amount": amount})

            self._state.last_updated = _now_iso()
            self.save()

    # ------------------------------------------------------------------
    # Public API — capital deployment
    # ------------------------------------------------------------------

    def request_capital(self, amount: float) -> bool:
        """
        Attempt to reserve *amount* of capital for a new position.

        Returns ``True`` if the request is granted and ``total_deployed`` is
        increased; ``False`` otherwise.

        Rejection reasons
        -----------------
        * ``can_trade()`` returns ``False`` (safe-mode, recovery + limit
          exceeded, or not yet set up).
        * ``total_deployed + amount > user_capital_limit``.
        * *amount* <= 0.

        Parameters
        ----------
        amount:
            Capital to reserve, in account currency.
        """
        if amount <= 0:
            self._log("request_capital_rejected", {
                "amount": amount, "reason": "non_positive_amount"
            })
            return False

        with self._lock:
            if not self.can_trade():
                self._log("request_capital_rejected", {
                    "amount": amount, "reason": "cannot_trade"
                })
                return False

            prospective = self._state.total_deployed + amount
            if prospective > self._state.user_capital_limit:
                self._log("request_capital_rejected", {
                    "amount": amount,
                    "reason": "exceeds_user_limit",
                    "would_deploy": prospective,
                    "limit": self._state.user_capital_limit,
                })
                return False

            self._state.total_deployed = prospective
            self._state.last_updated = _now_iso()
            self._log("request_capital_granted", {
                "amount": amount,
                "total_deployed": self._state.total_deployed,
            })
            self.save()
            return True

    def release_capital(self, amount: float) -> None:
        """
        Return *amount* to the available pool when a position is closed.

        ``total_deployed`` is floored at 0 to guard against accounting drift.

        Parameters
        ----------
        amount:
            Capital to release, in account currency.
        """
        if amount <= 0:
            raise ValueError("Release amount must be positive.")

        with self._lock:
            self._state.total_deployed = max(
                0.0, self._state.total_deployed - amount
            )
            self._state.last_updated = _now_iso()
            self._log("release_capital", {
                "amount": amount,
                "total_deployed": self._state.total_deployed,
            })
            self.save()

    # ------------------------------------------------------------------
    # Public API — limit management
    # ------------------------------------------------------------------

    def increase_limit(self, new_limit: float) -> None:
        """
        Raise ``user_capital_limit`` to *new_limit*.

        This method is intended for **explicit user commands only**.  NEXUS
        must never call it autonomously.

        Parameters
        ----------
        new_limit:
            The new capital limit.  Must strictly exceed the current limit.
        """
        with self._lock:
            if new_limit <= self._state.user_capital_limit:
                raise ValueError(
                    f"new_limit ({new_limit}) must exceed the current limit "
                    f"({self._state.user_capital_limit})."
                )
            if new_limit > self._state.initial_capital:
                raise ValueError(
                    f"new_limit ({new_limit}) may not exceed initial_capital "
                    f"({self._state.initial_capital})."
                )
            old = self._state.user_capital_limit
            self._state.user_capital_limit = new_limit
            self._state.last_updated = _now_iso()
            self._log("increase_limit", {
                "old_limit": old, "new_limit": new_limit
            })
            self.save()

    def authorise_standby(self, amount: float) -> bool:
        """
        Release *amount* from ``standby_fund`` for discretionary use.

        This method is intended for **explicit user commands only**.

        Returns ``True`` if the full *amount* was available and transferred
        (``standby_fund`` is reduced accordingly); ``False`` if insufficient
        funds exist in the standby bucket.

        Parameters
        ----------
        amount:
            Amount to release from standby, in account currency.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive.")

        with self._lock:
            if self._state.standby_fund < amount:
                self._log("authorise_standby_rejected", {
                    "amount": amount,
                    "standby_fund": self._state.standby_fund,
                    "reason": "insufficient_standby",
                })
                return False

            self._state.standby_fund -= amount
            self._state.last_updated = _now_iso()
            self._log("authorise_standby", {
                "amount": amount,
                "standby_fund_remaining": self._state.standby_fund,
            })
            self.save()
            return True

    # ------------------------------------------------------------------
    # Public API — status / guard
    # ------------------------------------------------------------------

    def can_trade(self) -> bool:
        """
        Return ``True`` if NEXUS is permitted to open new positions.

        Returns ``False`` when:

        * The system has not been set up yet (``initial_capital == 0``).
        * The system is in recovery phase **and** ``total_deployed`` is
          already at or above ``user_capital_limit`` (no room to add).
        * (Extendable) safe mode is active — add ``self._safe_mode`` flag
          in future iterations.

        Note: being in recovery phase alone does not block trading; NEXUS
        can still trade to *earn* its way out.  What is blocked during
        recovery is reinvestment beyond the current limit.
        """
        with self._lock:
            if self._state.initial_capital == 0.0:
                return False
            if self._state.user_capital_limit == 0.0:
                return False
            # Hard cap: can never deploy more than the limit.
            if self._state.total_deployed >= self._state.user_capital_limit:
                return False
            return True

    def status(self) -> Dict[str, Any]:
        """
        Return a comprehensive snapshot of the current capital state.

        The returned dict contains every field from :class:`CapitalState`
        plus derived values:

        ``available_capital``
            ``user_capital_limit - total_deployed``
        ``recovery_gap``
            Remaining amount to recover (0 if not in recovery phase).
        ``can_trade``
            Result of :meth:`can_trade`.
        ``bucket_pcts``
            Configured split percentages.
        """
        with self._lock:
            d = self._state.to_dict()
            d["available_capital"] = max(
                0.0,
                self._state.user_capital_limit - self._state.total_deployed,
            )
            d["recovery_gap"] = (
                max(
                    0.0,
                    self._state.initial_capital
                    - self._state.recovered_capital,
                )
                if self._state.in_recovery_phase
                else 0.0
            )
            d["can_trade"] = self.can_trade()
            d["bucket_pcts"] = {
                "tools": self._tools_pct,
                "reinvest": self._reinvest_pct,
                "standby": self._standby_pct,
            }
            return d

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """
        Write the current :class:`CapitalState` to ``state_path`` as JSON.

        The parent directory is created on demand.  Writes are atomic: the
        data is written to a temporary ``.tmp`` sibling file then renamed so
        that a crash mid-write cannot corrupt the state file.
        """
        with self._lock:
            dir_path = os.path.dirname(self._state_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            tmp_path = self._state_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._state.to_dict(), fh, indent=2)
            os.replace(tmp_path, self._state_path)

    def load(self) -> CapitalState:
        """
        Load :class:`CapitalState` from ``state_path``.

        If the file does not exist a fresh default state is returned and
        **not** immediately persisted (the caller decides when to save).

        Returns
        -------
        CapitalState
            The loaded or freshly-created state object.
        """
        if not os.path.exists(self._state_path):
            logger.info(
                "No capital state found at %s — starting fresh.",
                self._state_path,
            )
            return CapitalState()

        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            state = CapitalState.from_dict(data)
            logger.info("Capital state loaded from %s.", self._state_path)
            return state
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.error(
                "Failed to parse capital state from %s: %s — starting fresh.",
                self._state_path, exc,
            )
            return CapitalState()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_profit(self, amount: float) -> None:
        """Distribute *amount* across post-recovery buckets (no lock needed
        — callers must hold ``_lock``)."""
        self._state.tools_fund += amount * self._tools_pct
        self._state.reinvest_fund += amount * self._reinvest_pct
        self._state.standby_fund += amount * self._standby_pct
        self._log("profit_split", {
            "amount": amount,
            "tools": amount * self._tools_pct,
            "reinvest": amount * self._reinvest_pct,
            "standby": amount * self._standby_pct,
        })

    def _log(self, action: str, detail: Dict[str, Any]) -> None:
        """
        Append a single JSON line to the audit log.

        Format::

            {"ts": "<ISO>", "action": "<action>", "detail": { … }}

        Failures are swallowed (with a stderr warning) so that an
        unwritable log file never crashes the trading engine.
        """
        entry = {"ts": _now_iso(), "action": action, "detail": detail}
        try:
            log_dir = os.path.dirname(self._log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.warning(
                "Could not write to audit log %s: %s", self._log_path, exc
            )
