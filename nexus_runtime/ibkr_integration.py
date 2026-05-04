"""
NEXUS Runtime — IBKR Integration
Safe, fully-audited, rule-based trading integration with Interactive Brokers.

Three operating modes:
  paper — fully simulated; no real trades; state in data/ibkr/
  semi  — NEXUS generates orders; human confirms via command layer
  auto  — NEXUS executes autonomously within hard risk/capital limits

Real IBKR connectivity (ib_insync / TWS API) is injected at the connection
layer. In all other respects the class is mode-agnostic: every action is
logged, audited, and validated before execution.

Audit chain:
  logs/ibkr_orders.jsonl   — per-order log (SHA-256 chained)
  logs/live/audit_live.jsonl — runtime audit chain

Usage:
    ibkr = IBKRIntegration.from_runtime(runtime)
    ibkr.connect()
    result = ibkr.place_order("AAPL", "buy", 10, sl=148.0, tp=158.0)
    ibkr.disconnect()
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .capital_manager import CapitalManager
from .risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    """Outcome of a single place_order() call."""
    order_id:    str
    symbol:      str
    side:        str            # "buy" | "sell"
    size:        float
    price:       float          # fill price (paper) or 0 (pending)
    sl:          Optional[float]
    tp:          Optional[float]
    status:      str            # "filled" | "pending" | "rejected" | "simulated"
    mode:        str            # paper | semi | auto
    reason:      Optional[str]  # rejection reason
    risk_amount: float
    capital_state: Dict[str, Any] = field(default_factory=dict)
    ts:          str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id":     self.order_id,
            "symbol":       self.symbol,
            "side":         self.side,
            "size":         self.size,
            "price":        self.price,
            "sl":           self.sl,
            "tp":           self.tp,
            "status":       self.status,
            "mode":         self.mode,
            "reason":       self.reason,
            "risk_amount":  round(self.risk_amount, 6),
            "capital_state": self.capital_state,
            "ts":           self.ts,
        }


@dataclass
class Position:
    """An open position tracked by the integration."""
    symbol:    str
    side:      str
    size:      float
    entry_price: float
    sl:        Optional[float] = None
    tp:        Optional[float] = None
    order_id:  str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pnl:       float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol":      self.symbol,
            "side":        self.side,
            "size":        round(self.size, 6),
            "entry_price": round(self.entry_price, 6),
            "sl":          self.sl,
            "tp":          self.tp,
            "order_id":    self.order_id,
            "opened_at":   self.opened_at,
            "pnl":         round(self.pnl, 6),
        }


# ---------------------------------------------------------------------------
# IBKR Integration
# ---------------------------------------------------------------------------

_ORDER_LOG = "logs/ibkr_orders.jsonl"
_POSITIONS_FILE = "data/ibkr/positions.json"
_PENDING_FILE   = "data/ibkr/pending_orders.json"


class IBKRIntegration:
    """
    Safe IBKR trading interface with three operating modes.

    All orders are:
      1. Validated by RiskManager (position size, daily/weekly limits, drawdown)
      2. Authorised by CapitalManager (capital limit, recovery phase)
      3. Logged with SHA-256 audit chain before execution
      4. Persisted to disk so state survives restarts

    The class can be subclassed or monkey-patched to inject real ib_insync
    calls at the _place_real_order() hook; the paper engine is always the
    default.
    """

    VALID_MODES = ("paper", "semi", "auto")

    def __init__(
        self,
        mode:            str              = "paper",
        capital_manager: Optional[CapitalManager] = None,
        risk_manager:    Optional[RiskManager]    = None,
        config:          Optional[Any]    = None,
        bus:             Optional[Any]    = None,
        reports:         Optional[Any]   = None,
    ) -> None:
        if mode not in self.VALID_MODES:
            raise ValueError(f"mode must be one of {self.VALID_MODES}, got {mode!r}")

        self._mode   = mode
        self._config = config
        self._bus    = bus
        self._reports = reports
        self._lock   = threading.RLock()
        self._root   = Path(__file__).parent.parent

        self._cm = capital_manager or CapitalManager()
        self._rm = risk_manager    or RiskManager()

        self._connected  = False
        self._positions: Dict[str, Position] = {}   # symbol → Position
        self._pending:   Dict[str, Dict[str, Any]] = {}  # order_id → order dict
        self._balance    = 0.0
        self._market_prices: Dict[str, float] = {}  # symbol → last price (paper)

        self._load_positions()
        self._load_pending()

    @classmethod
    def from_runtime(cls, runtime: Any) -> "IBKRIntegration":
        cfg  = runtime._config
        ibkr_cfg = getattr(cfg, "ibkr", None)
        mode = getattr(ibkr_cfg, "mode", "paper") if ibkr_cfg else "paper"
        cm   = CapitalManager.from_runtime(runtime)
        rm   = RiskManager.from_runtime(runtime)
        return cls(
            mode=mode,
            capital_manager=cm,
            risk_manager=rm,
            config=cfg,
            bus=getattr(runtime, "bus", None),
            reports=getattr(runtime.integration.modules, "reports", None),
        )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish connection to IBKR (paper: always succeeds).
        In live mode: would call ib.connect(host, port, clientId).
        """
        with self._lock:
            if self._connected:
                return True
            try:
                if self._mode == "paper":
                    self._connected = True
                    # Initialise paper balance from capital manager
                    capital = self._cm._state.user_capital_limit or self._cm._state.initial_capital
                    self._balance = capital
                else:
                    # Real IBKR connection point — inject ib_insync here
                    # ib.connect(host, port, clientId)
                    self._connected = True  # paper fallback for now
                    self._balance = self._cm._state.user_capital_limit

                self._append_log({
                    "action":   "connect",
                    "mode":     self._mode,
                    "balance":  self._balance,
                    "ts":       _now(),
                })
                self._audit("ibkr_connect", f"mode={self._mode}  balance={self._balance:.2f}")
                return True
            except Exception as exc:
                self._append_log({"action": "connect_failed", "error": str(exc), "ts": _now()})
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self._connected:
                self._save_positions()
                self._save_pending()
                self._connected = False
                self._audit("ibkr_disconnect", f"mode={self._mode}")

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # ------------------------------------------------------------------
    # Read-only market data
    # ------------------------------------------------------------------

    def get_balance(self) -> float:
        with self._lock:
            return self._balance

    def get_positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._positions.values()]

    def get_open_orders(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._pending.values())

    def get_market_price(self, symbol: str) -> float:
        """Returns last known price (paper: synthetic; real: TWS ticker)."""
        with self._lock:
            if symbol in self._market_prices:
                return self._market_prices[symbol]
            # Paper: return a synthetic price based on symbol hash for stability
            price = 100.0 + (hash(symbol) % 900)
            self._market_prices[symbol] = float(price)
            return float(price)

    def set_paper_price(self, symbol: str, price: float) -> None:
        """Override paper price for testing / signal-driven updates."""
        with self._lock:
            self._market_prices[symbol] = price

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol:     str,
        side:       str,
        size:       float,
        sl:         Optional[float]  = None,
        tp:         Optional[float]  = None,
        order_type: str              = "market",
        reason:     str              = "",
    ) -> OrderResult:
        """
        Place an order through the NEXUS safety pipeline.

        Flow:
          1. Validate inputs
          2. RiskManager validates limits
          3. CapitalManager authorises capital
          4. Log audit entry (before execution — tamper-evident)
          5. Execute (paper / semi-pending / real)
          6. Update state

        Returns OrderResult — check .status for "filled"/"pending"/"rejected".
        """
        with self._lock:
            order_id = str(uuid.uuid4())[:12]
            side = side.lower()

            # ── 1. Input validation ───────────────────────────────────────
            if side not in ("buy", "sell"):
                return self._reject(order_id, symbol, side, size, sl, tp, "side must be buy or sell")
            if size <= 0:
                return self._reject(order_id, symbol, side, size, sl, tp, "size must be > 0")
            if not self._connected:
                return self._reject(order_id, symbol, side, size, sl, tp, "not connected")

            price = self.get_market_price(symbol)

            # ── 2. Risk validation ────────────────────────────────────────
            self._rm._reset_daily_if_needed()
            self._rm._reset_weekly_if_needed()

            sl_distance = abs(price - sl) if sl else price * 0.02
            if sl_distance <= 0:
                sl_distance = price * 0.02

            risk_amount = sl_distance * size
            capital = self._cm._state.user_capital_limit or self._balance or 1.0

            ok, reason_str = self._rm.validate_trade(capital, risk_amount)
            if not ok:
                return self._reject(order_id, symbol, side, size, sl, tp, f"risk: {reason_str}")

            # ── 3. Capital authorisation ──────────────────────────────────
            position_value = price * size
            if not self._cm.request_capital(position_value):
                return self._reject(order_id, symbol, side, size, sl, tp,
                                    "capital: limit exceeded or recovery phase active")

            # ── 4. Audit entry (before execution) ────────────────────────
            audit_payload = {
                "order_id":   order_id,
                "action":     "place_order",
                "symbol":     symbol,
                "side":       side,
                "size":       size,
                "price":      price,
                "sl":         sl,
                "tp":         tp,
                "order_type": order_type,
                "risk_amount": round(risk_amount, 6),
                "mode":       self._mode,
                "reason":     reason,
                "capital":    self._cm.status(),
                "ts":         _now(),
            }
            self._append_log(audit_payload)

            # ── 5. Execute ────────────────────────────────────────────────
            if self._mode == "paper":
                result = self._execute_paper(order_id, symbol, side, size, price, sl, tp, risk_amount)
            elif self._mode == "semi":
                result = self._execute_semi(order_id, symbol, side, size, price, sl, tp, risk_amount)
            else:  # auto
                result = self._execute_auto(order_id, symbol, side, size, price, sl, tp, risk_amount)

            # ── 6. Post-execution state update ────────────────────────────
            if result.status in ("filled", "simulated"):
                self._rm.record_trade_risk(risk_amount)
                pos = Position(
                    symbol=symbol, side=side, size=size, entry_price=price,
                    sl=sl, tp=tp, order_id=order_id,
                )
                self._positions[symbol] = pos
                self._save_positions()
                self._emit("TRADE_SIGNAL", result.to_dict())
            elif result.status == "pending":
                self._pending[order_id] = audit_payload
                self._save_pending()

            self._audit("ibkr_place_order",
                        f"{side} {size} {symbol} @ {price:.2f}  status={result.status}")
            return result

    def close_position(self, symbol: str) -> OrderResult:
        """Close an open position for the given symbol."""
        with self._lock:
            pos = self._positions.get(symbol)
            if not pos:
                return self._reject(
                    str(uuid.uuid4())[:12], symbol, "close", 0, None, None,
                    f"no open position for {symbol}",
                )

            price = self.get_market_price(symbol)
            pnl   = (price - pos.entry_price) * pos.size * (1 if pos.side == "buy" else -1)

            self._append_log({
                "action":  "close_position",
                "symbol":  symbol,
                "side":    "sell" if pos.side == "buy" else "buy",
                "size":    pos.size,
                "price":   price,
                "pnl":     round(pnl, 6),
                "mode":    self._mode,
                "ts":      _now(),
            })

            # Release capital and record profit/loss
            self._cm.release_capital(price * pos.size)
            if pnl > 0:
                self._cm.record_profit(pnl)
            elif pnl < 0:
                self._cm.record_loss(abs(pnl))
            self._rm.update_balance(self._balance + pnl)

            del self._positions[symbol]
            self._save_positions()

            self._audit("ibkr_close_position", f"{symbol}  pnl={pnl:+.4f}  price={price:.2f}")

            return OrderResult(
                order_id=pos.order_id, symbol=symbol,
                side="sell" if pos.side == "buy" else "buy",
                size=pos.size, price=price, sl=None, tp=None,
                status="filled", mode=self._mode, reason=None,
                risk_amount=0.0, capital_state=self._cm.status(),
            )

    def modify_order(
        self,
        order_id: str,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> bool:
        """Modify SL/TP on a pending order or open position."""
        with self._lock:
            # Check positions first
            for pos in self._positions.values():
                if pos.order_id == order_id:
                    if sl is not None:
                        pos.sl = sl
                    if tp is not None:
                        pos.tp = tp
                    self._save_positions()
                    self._append_log({
                        "action": "modify_order", "order_id": order_id,
                        "sl": sl, "tp": tp, "ts": _now(),
                    })
                    return True
            # Check pending
            if order_id in self._pending:
                if sl is not None:
                    self._pending[order_id]["sl"] = sl
                if tp is not None:
                    self._pending[order_id]["tp"] = tp
                self._save_pending()
                self._append_log({
                    "action": "modify_pending", "order_id": order_id,
                    "sl": sl, "tp": tp, "ts": _now(),
                })
                return True
            return False

    def confirm_pending(self, order_id: str) -> Optional[OrderResult]:
        """
        In semi mode: user confirms a pending order, causing it to execute immediately.
        Returns None if order_id not found.
        """
        with self._lock:
            order = self._pending.get(order_id)
            if not order:
                return None

            symbol = order["symbol"]
            side   = order["side"]
            size   = order["size"]
            sl     = order.get("sl")
            tp     = order.get("tp")
            risk_amount = order.get("risk_amount", 0.0)
            price  = self.get_market_price(symbol)

            del self._pending[order_id]
            self._save_pending()

            self._append_log({
                "action": "confirm_pending",
                "order_id": order_id,
                "symbol": symbol,
                "mode": self._mode,
                "ts": _now(),
            })
            self._audit("ibkr_confirm_pending", f"order_id={order_id}  {side} {size} {symbol}")

            # Execute immediately regardless of mode (user has confirmed)
            result = self._execute_auto(order_id, symbol, side, size, price, sl, tp, risk_amount)

            if result.status in ("filled",):
                self._rm.record_trade_risk(risk_amount)
                pos = Position(
                    symbol=symbol, side=side, size=size, entry_price=price,
                    sl=sl, tp=tp, order_id=order_id,
                )
                self._positions[symbol] = pos
                self._save_positions()
                self._emit("TRADE_SIGNAL", result.to_dict())

            return result

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> bool:
        if mode not in self.VALID_MODES:
            return False
        with self._lock:
            self._mode = mode
            self._audit("ibkr_mode_change", f"mode={mode}")
            self._append_log({"action": "mode_change", "mode": mode, "ts": _now()})
            return True

    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Safe mode (delegate to RiskManager)
    # ------------------------------------------------------------------

    def enter_safe_mode(self, reason: str = "manual") -> None:
        self._rm.enter_safe_mode(reason)
        self._audit("ibkr_safe_mode", f"entered: {reason}")
        self._emit("RISK_BREACH", {"reason": reason, "safe_mode": True})

    def exit_safe_mode(self) -> None:
        self._rm.exit_safe_mode()
        self._audit("ibkr_safe_mode", "exited")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "connected":  self._connected,
                "mode":       self._mode,
                "balance":    round(self._balance, 2),
                "positions":  len(self._positions),
                "pending":    len(self._pending),
                "capital":    self._cm.status(),
                "risk":       self._rm.status(),
            }

    # ------------------------------------------------------------------
    # Internal — execution engines
    # ------------------------------------------------------------------

    def _execute_paper(
        self, order_id, symbol, side, size, price, sl, tp, risk_amount
    ) -> OrderResult:
        """Paper execution: immediate fill at current market price."""
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            size=size, price=price, sl=sl, tp=tp,
            status="simulated", mode="paper", reason=None,
            risk_amount=risk_amount, capital_state=self._cm.status(),
        )

    def _execute_semi(
        self, order_id, symbol, side, size, price, sl, tp, risk_amount
    ) -> OrderResult:
        """Semi execution: order queued as pending until user confirms."""
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            size=size, price=price, sl=sl, tp=tp,
            status="pending", mode="semi", reason="awaiting_user_confirmation",
            risk_amount=risk_amount, capital_state=self._cm.status(),
        )

    def _execute_auto(
        self, order_id, symbol, side, size, price, sl, tp, risk_amount
    ) -> OrderResult:
        """
        Auto execution: place order immediately within limits.
        In simulation context: same as paper but with status="filled".
        In production: would call _place_real_order().
        """
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            size=size, price=price, sl=sl, tp=tp,
            status="filled", mode="auto", reason=None,
            risk_amount=risk_amount, capital_state=self._cm.status(),
        )

    def _place_real_order(self, symbol, side, size, sl, tp, order_type) -> Dict[str, Any]:
        """Hook for real ib_insync execution. Override to connect real API."""
        raise NotImplementedError("Real IBKR connection not configured.")

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    def _reject(
        self, order_id, symbol, side, size, sl, tp, reason
    ) -> OrderResult:
        self._append_log({
            "action": "rejected", "order_id": order_id,
            "symbol": symbol, "side": side, "size": size,
            "reason": reason, "mode": self._mode, "ts": _now(),
        })
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            size=size, price=0.0, sl=sl, tp=tp,
            status="rejected", mode=self._mode, reason=reason,
            risk_amount=0.0,
        )

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append a SHA-256 chained entry to logs/ibkr_orders.jsonl."""
        log_path = self._root / _ORDER_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        prev_hash = self._last_log_hash(log_path)
        payload   = json.dumps(entry, sort_keys=True, default=str)
        chain_hash = hashlib.sha256((prev_hash + payload).encode()).hexdigest()
        entry["hash"]      = chain_hash
        entry["prev_hash"] = prev_hash
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def _last_log_hash(self, log_path: Path) -> str:
        if not log_path.exists():
            return "0" * 64
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines):
                try:
                    return json.loads(line).get("hash", "0" * 64)
                except Exception:
                    pass
        except Exception:
            pass
        return "0" * 64

    def _load_positions(self) -> None:
        p = self._root / _POSITIONS_FILE
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for d in data:
                pos = Position(
                    symbol=d["symbol"], side=d["side"],
                    size=d["size"], entry_price=d["entry_price"],
                    sl=d.get("sl"), tp=d.get("tp"),
                    order_id=d.get("order_id", str(uuid.uuid4())[:12]),
                    opened_at=d.get("opened_at", _now()),
                    pnl=d.get("pnl", 0.0),
                )
                self._positions[pos.symbol] = pos
        except Exception:
            pass

    def _save_positions(self) -> None:
        p = self._root / _POSITIONS_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps([pos.to_dict() for pos in self._positions.values()],
                       indent=2, default=str),
            encoding="utf-8",
        )

    def _load_pending(self) -> None:
        p = self._root / _PENDING_FILE
        if not p.exists():
            return
        try:
            self._pending = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass

    def _save_pending(self) -> None:
        p = self._root / _PENDING_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._pending, indent=2, default=str), encoding="utf-8")

    def _audit(self, action: str, detail: str = "") -> None:
        rep = self._reports
        if rep and hasattr(rep, "log_event"):
            try:
                from reports import AuditEventType
                rep.log_event(
                    AuditEventType.PIPELINE_STARTED,
                    actor="ibkr_integration",
                    action=action,
                    outcome=detail,
                )
            except Exception:
                pass
        # Direct append to audit_live.jsonl
        try:
            audit_path = self._root / "logs/live/audit_live.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": _now(), "event": action, "data": {"detail": detail}
                }) + "\n")
        except Exception:
            pass

    def _emit(self, event_name: str, data: Optional[Dict[str, Any]] = None) -> None:
        if not self._bus:
            return
        try:
            from .events import EventType
            evt = getattr(EventType, event_name, None)
            if evt:
                self._bus.emit(evt, source="ibkr_integration", data=data or {})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
