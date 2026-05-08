from ibkr.config import config
from ibkr.logger import get_logger

log = get_logger("risk")


class RiskManager:
    def __init__(self):
        self._daily_pnl: float = 0.0
        self._locked: bool = False
        self._seen_orders: set = set()

    def reset_daily(self):
        self._daily_pnl = 0.0
        self._locked = False
        self._seen_orders.clear()
        log.info("Daily risk counters reset")

    def record_pnl(self, pnl: float):
        self._daily_pnl += pnl
        self._check_limits()

    def _check_limits(self):
        if self._daily_pnl <= -abs(config.risk.max_daily_loss):
            self._locked = True
            log.critical(f"MAX DAILY LOSS reached ({self._daily_pnl:.2f}). Trading LOCKED.")
        elif self._daily_pnl >= config.risk.max_daily_gain:
            self._locked = True
            log.critical(f"MAX DAILY GAIN reached ({self._daily_pnl:.2f}). Trading LOCKED.")

    def validate(self, symbol: str, qty: int, price: float,
                 sl: float = None, order_ref: str = None) -> bool:
        if self._locked:
            log.error(f"REJECTED (locked): {symbol} qty={qty}")
            return False

        if order_ref and order_ref in self._seen_orders:
            log.error(f"REJECTED (duplicate): {order_ref}")
            return False

        order_value = abs(qty * price)
        if order_value > config.risk.max_order_value:
            log.error(f"REJECTED (too large): {symbol} value={order_value:.2f} limit={config.risk.max_order_value}")
            return False

        if config.risk.require_sl and sl is None:
            log.error(f"REJECTED (missing SL): {symbol}")
            return False

        if order_ref:
            self._seen_orders.add(order_ref)

        log.info(f"Risk OK: {symbol} qty={qty} value={order_value:.2f}")
        return True

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl
