import os
import time
from typing import Dict, List, Optional
from nexus.services.logger.logger import get_logger

log = get_logger("trading")

MAX_ORDER = 10.0
MAX_EXPOSURE = 10.0
MIN_INTERVAL = 60


class TradingModule:
    def __init__(self, security):
        self._security = security
        self._real = False
        self._broker = os.getenv("TRADING_BROKER", "simulation")
        self._last_order = 0.0
        self._exposure = 0.0
        self._orders: List[Dict] = []

    # ---------------------------------------------------------------- control

    def enable_real(self, code: str) -> bool:
        if code == os.getenv("TRADING_CONFIRM_CODE", "NEXUS-REAL-CONFIRM"):
            self._real = True
            self._security.authorize_financial()
            log.warning("REAL TRADING ENABLED")
            return True
        log.warning("Invalid confirmation code")
        return False

    def disable_real(self):
        self._real = False
        self._security.revoke_financial()
        log.info("Simulation mode")

    # ------------------------------------------------------------------ orders

    def place_order(self, symbol: str, action: str, amount: float,
                    sl: float = None, tp: float = None) -> Dict:
        # Rate limit
        now = time.time()
        elapsed = now - self._last_order
        if elapsed < MIN_INTERVAL:
            return {"error": f"Rate limit: wait {MIN_INTERVAL - elapsed:.0f}s"}

        # Security
        if self._real and not self._security.validate_financial(amount):
            return {"error": "Financial validation failed"}

        if amount > MAX_ORDER:
            return {"error": f"{amount}€ > max {MAX_ORDER}€"}

        if self._exposure + amount > MAX_EXPOSURE:
            return {"error": f"Would exceed max exposure {MAX_EXPOSURE}€"}

        self._last_order = now
        self._exposure += amount

        order: Dict = {
            "id": f"ORD-{int(now)}",
            "symbol": symbol, "action": action,
            "amount": amount, "sl": sl, "tp": tp,
            "mode": "REAL" if self._real else "SIM",
            "broker": self._broker, "status": "pending",
        }

        order["status"] = self._execute(order) if self._real else "filled_sim"
        self._orders.append(order)
        log.info(f"{order['id']} {action} {symbol} {amount}€ [{order['status']}]")
        return order

    def _execute(self, order: Dict) -> str:
        if self._broker == "xtb":
            return self._xtb(order)
        if self._broker == "ibkr":
            return self._ibkr(order)
        return "no_broker"

    def _xtb(self, o: Dict) -> str:
        log.info(f"XTB: {o}")
        return "submitted_xtb"

    def _ibkr(self, o: Dict) -> str:
        log.info(f"IBKR: {o}")
        return "submitted_ibkr"

    # -------------------------------------------------------------------- data

    def get_orders(self) -> List[Dict]:
        return list(self._orders)

    def status(self) -> Dict:
        return {
            "mode": "REAL" if self._real else "SIM",
            "broker": self._broker,
            "exposure_eur": self._exposure,
            "orders": len(self._orders),
            "max_order_eur": MAX_ORDER,
            "max_exposure_eur": MAX_EXPOSURE,
        }
