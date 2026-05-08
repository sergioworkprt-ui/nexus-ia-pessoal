from typing import List
from ib_insync import (
    IB, Contract, Stock, Forex, Future,
    MarketOrder, LimitOrder, StopOrder, StopLimitOrder, Trade
)
from ibkr.logger import get_logger

log = get_logger("orders")


def make_contract(symbol: str, sec_type: str = "STK",
                  currency: str = "USD", exchange: str = "SMART") -> Contract:
    if sec_type == "STK":
        return Stock(symbol, exchange, currency)
    elif sec_type == "CASH":
        return Forex(symbol)
    elif sec_type == "FUT":
        return Future(symbol, exchange=exchange, currency=currency)
    raise ValueError(f"Unsupported sec_type: {sec_type}")


def market(action: str, qty: int) -> MarketOrder:
    return MarketOrder(action, qty)


def limit(action: str, qty: int, price: float) -> LimitOrder:
    return LimitOrder(action, qty, price)


def stop(action: str, qty: int, stop_price: float) -> StopOrder:
    return StopOrder(action, qty, stop_price)


def stop_limit(action: str, qty: int, limit_price: float, stop_price: float) -> StopLimitOrder:
    return StopLimitOrder(action, qty, limitPrice=limit_price, stopPrice=stop_price)


def bracket(ib: IB, action: str, qty: int,
            entry: float, sl: float, tp: float) -> List:
    close = "SELL" if action == "BUY" else "BUY"

    parent = LimitOrder(action, qty, entry, transmit=False)
    parent.orderId = ib.client.getReqId()

    sl_order = StopOrder(close, qty, sl, parentId=parent.orderId, transmit=False)
    sl_order.orderId = ib.client.getReqId()

    tp_order = LimitOrder(close, qty, tp, parentId=parent.orderId, transmit=True)
    tp_order.orderId = ib.client.getReqId()

    log.info(f"Bracket built: {action} {qty} entry={entry} sl={sl} tp={tp}")
    return [parent, sl_order, tp_order]
