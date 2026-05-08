import asyncio
from typing import Optional, List, Dict
from ib_insync import IB, Trade, Position
from ibkr.connection import IBKRConnection
from ibkr.risk import RiskManager
from ibkr.config import config
import ibkr.orders as ord_
from ibkr.logger import get_logger

log = get_logger("nexus")


class NexusIBKR:
    """Simplified NEXUS wrapper for IBKR operations."""

    def __init__(self):
        self._conn = IBKRConnection()
        self.risk = RiskManager()

    @property
    def ib(self) -> IB:
        return self._conn.ib

    async def start(self):
        await self._conn.connect()
        log.info("NexusIBKR ready")

    # ------------------------------------------------------------------ orders

    def place_order(
        self,
        symbol: str,
        action: str,          # "BUY" | "SELL"
        qty: int,
        price: float = None,  # None = market order
        sl: float = None,
        tp: float = None,
        sec_type: str = "STK",
        currency: str = "USD",
        order_ref: str = None,
    ) -> Optional[Trade]:
        entry_price = price or self._last_price(symbol, sec_type, currency)
        if not self.risk.validate(symbol, qty, entry_price, sl, order_ref):
            return None

        contract = ord_.make_contract(symbol, sec_type, currency)
        self.ib.qualifyContracts(contract)

        if sl and tp and price:
            orders = ord_.bracket(self.ib, action, qty, price, sl, tp)
            trades = [self.ib.placeOrder(contract, o) for o in orders]
            log.info(f"Bracket: {action} {qty} {symbol} entry={price} sl={sl} tp={tp}")
            return trades[0]

        order = ord_.limit(action, qty, price) if price else ord_.market(action, qty)
        trade = self.ib.placeOrder(contract, order)
        log.info(f"Order: {action} {qty} {symbol} @ {'MKT' if not price else price}")
        return trade

    def close_order(self, trade: Trade) -> bool:
        self.ib.cancelOrder(trade.order)
        log.info(f"Cancelled order {trade.order.orderId}")
        return True

    def close_position(self, symbol: str, sec_type: str = "STK",
                       currency: str = "USD") -> Optional[Trade]:
        contract = ord_.make_contract(symbol, sec_type, currency)
        self.ib.qualifyContracts(contract)
        for pos in self.ib.positions():
            if pos.contract.symbol == symbol:
                action = "SELL" if pos.position > 0 else "BUY"
                trade = self.ib.placeOrder(contract, ord_.market(action, abs(int(pos.position))))
                log.info(f"Closed position: {symbol} qty={pos.position}")
                return trade
        log.warning(f"No open position for {symbol}")
        return None

    def update_sl(self, trade: Trade, new_sl: float):
        trade.order.auxPrice = new_sl
        self.ib.placeOrder(trade.contract, trade.order)
        log.info(f"SL updated → {new_sl} (order {trade.order.orderId})")

    def update_tp(self, trade: Trade, new_tp: float):
        trade.order.lmtPrice = new_tp
        self.ib.placeOrder(trade.contract, trade.order)
        log.info(f"TP updated → {new_tp} (order {trade.order.orderId})")

    # -------------------------------------------------------------------- data

    def get_positions(self) -> List[Position]:
        return self.ib.positions()

    def get_price(self, symbol: str, sec_type: str = "STK",
                  currency: str = "USD") -> float:
        return self._last_price(symbol, sec_type, currency)

    def get_account_info(self) -> Dict[str, float]:
        tags = {"NetLiquidation", "TotalCashValue", "BuyingPower", "AvailableFunds"}
        return {
            v.tag: float(v.value)
            for v in self.ib.accountValues()
            if v.tag in tags and v.currency == "USD"
        }

    def get_pnl(self) -> Dict[str, float]:
        pnl_list = self.ib.pnl()
        if pnl_list:
            p = pnl_list[0]
            pnl = {"daily": p.dailyPnL or 0, "unrealized": p.unrealizedPnL or 0,
                   "realized": p.realizedPnL or 0}
            self.risk.record_pnl(pnl["daily"])
            return pnl
        return {"daily": 0.0, "unrealized": 0.0, "realized": 0.0}

    # ----------------------------------------------------------------- private

    def _last_price(self, symbol: str, sec_type: str, currency: str) -> float:
        contract = ord_.make_contract(symbol, sec_type, currency)
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(1)
        price = ticker.last or ticker.close or 0.0
        self.ib.cancelMktData(contract)
        return price
