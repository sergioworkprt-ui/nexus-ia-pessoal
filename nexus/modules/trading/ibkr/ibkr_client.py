"""IBKR Client — via ib_insync."""
from __future__ import annotations
import asyncio, os
from nexus.services.logger.logger import get_logger

log = get_logger("ibkr")


class IBKRClient:
    def __init__(self):
        self._host = os.getenv("IBKR_HOST", "127.0.0.1")
        self._port = int(os.getenv("IBKR_PORT", "5000"))
        self._client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
        self._account = os.getenv("IBKR_ACCOUNT", "")
        self._ib = None
        self._connected = False
        self._mode = "simulation"

    @property
    def connected(self) -> bool:
        return self._connected and self._ib is not None

    async def connect(self) -> bool:
        try:
            from ib_insync import IB
            self._ib = IB()
            await self._ib.connectAsync(self._host, self._port, clientId=self._client_id)
            self._connected = True
            log.info(f"IBKR connected ({self._host}:{self._port})")
            return True
        except ImportError:
            log.warning("ib_insync not installed")
        except Exception as e:
            log.warning(f"IBKR connect: {e}")
        return False

    async def get_positions(self) -> list:
        if not self.connected:
            return []
        try:
            return [
                {
                    "symbol": str(p.contract.symbol),
                    "side": "BUY" if p.position > 0 else "SELL",
                    "size": abs(p.position),
                    "avg_cost": p.avgCost,
                    "broker": "ibkr",
                }
                for p in self._ib.positions()
            ]
        except Exception as e:
            log.warning(f"IBKR positions: {e}")
            return []

    async def get_account_summary(self) -> dict:
        if not self.connected:
            return {}
        try:
            return {item.tag: item.value for item in self._ib.accountSummary(self._account)}
        except Exception as e:
            log.warning(f"IBKR account: {e}")
            return {}

    async def place_order(self, symbol: str, action: str, quantity: float) -> dict:
        if self._mode == "simulation":
            log.info(f"[SIM] IBKR: {action} {quantity} {symbol}")
            return {"status": True, "simulation": True}
        if not self.connected:
            return {"status": False, "error": "not connected"}
        try:
            from ib_insync import Stock, MarketOrder
            contract = Stock(symbol, "SMART", "USD")
            trade = self._ib.placeOrder(contract, MarketOrder(action, quantity))
            return {"status": True, "orderId": trade.order.orderId}
        except Exception as e:
            log.error(f"IBKR order: {e}")
            return {"status": False, "error": str(e)}

    def enable_real(self, confirm_code: str) -> bool:
        if confirm_code == os.getenv("TRADING_CONFIRM_CODE", "NEXUS-REAL-CONFIRM"):
            self._mode = "real"
            log.warning("IBKR REAL mode enabled")
            return True
        return False

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "host": self._host,
            "port": self._port,
            "mode": self._mode,
            "account": self._account,
        }

    async def start(self):
        await self.connect()
        log.info(f"IBKRClient started (mode={self._mode})")

    def stop(self):
        if self._ib:
            try:
                self._ib.disconnect()
            except Exception:
                pass
        self._connected = False
