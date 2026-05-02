"""
NEXUS Profit Engine — Shared Types
Primitive data structures used across all profit_engine sub-modules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Side(str, Enum):
    BUY  = "buy"
    SELL = "sell"

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET     = "market"
    LIMIT      = "limit"
    STOP       = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING   = "pending"
    FILLED    = "filled"
    PARTIAL   = "partial"
    CANCELLED = "cancelled"
    REJECTED  = "rejected"


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    """Single OHLCV bar for a symbol."""
    symbol:    str
    timestamp: str
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float

    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol, "timestamp": self.timestamp,
            "open": self.open, "high": self.high,
            "low": self.low, "close": self.close, "volume": self.volume,
        }


# ---------------------------------------------------------------------------
# Orders & fills
# ---------------------------------------------------------------------------

@dataclass
class Order:
    """A trading order before execution."""
    symbol:      str
    side:        Side
    order_type:  OrderType
    quantity:    float                     # always positive
    order_id:    str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    limit_price: Optional[float] = None
    stop_price:  Optional[float] = None
    status:      OrderStatus = OrderStatus.PENDING
    created_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata:    Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive, got {self.quantity}.")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError("LIMIT orders require a limit_price.")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError("STOP orders require a stop_price.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id, "symbol": self.symbol,
            "side": self.side.value, "type": self.order_type.value,
            "quantity": self.quantity, "limit_price": self.limit_price,
            "stop_price": self.stop_price, "status": self.status.value,
            "created_at": self.created_at,
        }


@dataclass
class Fill:
    """Confirmed execution of (part of) an order."""
    order_id:   str
    symbol:     str
    side:       Side
    quantity:   float
    price:      float
    commission: float
    timestamp:  str
    fill_id:    str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    slippage:   float = 0.0

    @property
    def gross_value(self) -> float:
        return self.quantity * self.price

    @property
    def net_value(self) -> float:
        return self.gross_value + self.commission

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_id": self.fill_id, "order_id": self.order_id,
            "symbol": self.symbol, "side": self.side.value,
            "quantity": self.quantity, "price": self.price,
            "commission": self.commission, "slippage": self.slippage,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Positions & trades
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """An open position in the portfolio."""
    symbol:       str
    side:         Side
    quantity:     float
    entry_price:  float
    current_price: float
    opened_at:    str
    position_id:  str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    metadata:     Dict[str, Any] = field(default_factory=dict)

    @property
    def unrealised_pnl(self) -> float:
        diff = self.current_price - self.entry_price
        return diff * self.quantity if self.side is Side.BUY else -diff * self.quantity

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.entry_price

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id, "symbol": self.symbol,
            "side": self.side.value, "quantity": self.quantity,
            "entry_price": self.entry_price, "current_price": self.current_price,
            "unrealised_pnl": round(self.unrealised_pnl, 6),
            "market_value": round(self.market_value, 6),
            "opened_at": self.opened_at,
        }


@dataclass
class Trade:
    """A fully closed round-trip trade."""
    symbol:      str
    side:        Side
    quantity:    float
    entry_price: float
    exit_price:  float
    entry_time:  str
    exit_time:   str
    commission:  float
    trade_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    metadata:    Dict[str, Any] = field(default_factory=dict)

    @property
    def pnl(self) -> float:
        diff = self.exit_price - self.entry_price
        gross = diff * self.quantity if self.side is Side.BUY else -diff * self.quantity
        return gross - self.commission

    @property
    def pnl_pct(self) -> float:
        cost = self.entry_price * self.quantity
        return (self.pnl / cost * 100) if cost else 0.0

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id, "symbol": self.symbol,
            "side": self.side.value, "quantity": self.quantity,
            "entry_price": self.entry_price, "exit_price": self.exit_price,
            "entry_time": self.entry_time, "exit_time": self.exit_time,
            "commission": self.commission,
            "pnl": round(self.pnl, 6),
            "pnl_pct": round(self.pnl_pct, 4),
        }
