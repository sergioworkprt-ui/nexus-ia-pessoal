"""IBKR Client — via ib_insync. Totalmente opcional; falha em simulation."""
from __future__ import annotations
import asyncio
import os
from nexus.services.logger.logger import get_logger

log = get_logger("ibkr")

_CONNECT_TIMEOUT = 8.0  # segundos para tentar ligar ao IB Gateway


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
        """Tenta ligar ao IB Gateway com timeout. Sempre retorna sem travar."""
        try:
            from ib_insync import IB  # type: ignore
            self._ib = IB()
            await asyncio.wait_for(
                self._ib.connectAsync(
                    self._host, self._port, clientId=self._client_id
                ),
                timeout=_CONNECT_TIMEOUT,
            )
            self._connected = True
            log.info("IBKR connected (%s:%s)", self._host, self._port)
            return True
        except ImportError:
            log.warning("ib_insync nao instalado — IBKR em modo simulation")
        except asyncio.TimeoutError:
            log.warning(
                "IBKR connect timeout (%ss) — Gateway em %s:%s nao responde",
                _CONNECT_TIMEOUT, self._host, self._port,
            )
        except RuntimeError as exc:
            # ib_insync usa event loop interno; pode colidir com o loop do uvicorn
            msg = str(exc)
            if "different loop" in msg or "attached to" in msg:
                log.warning(
                    "IBKR event loop conflict — modo simulation (normal se nao houver Gateway)"
                )
            else:
                log.warning("IBKR RuntimeError: %s", exc)
        except Exception as exc:
            log.warning("IBKR connect erro: %s", exc)
        self._ib = None
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
        except Exception as exc:
            log.warning("IBKR positions: %s", exc)
            return []

    async def get_account_summary(self) -> dict:
        if not self.connected:
            return {}
        try:
            return {item.tag: item.value for item in self._ib.accountSummary(self._account)}
        except Exception as exc:
            log.warning("IBKR account: %s", exc)
            return {}

    async def place_order(self, symbol: str, action: str, quantity: float) -> dict:
        if self._mode == "simulation":
            log.info("[SIM] IBKR: %s %s %s", action, quantity, symbol)
            return {"status": True, "simulation": True}
        if not self.connected:
            return {"status": False, "error": "not connected"}
        try:
            from ib_insync import Stock, MarketOrder  # type: ignore
            contract = Stock(symbol, "SMART", "USD")
            trade = self._ib.placeOrder(contract, MarketOrder(action, quantity))
            return {"status": True, "orderId": trade.order.orderId}
        except Exception as exc:
            log.error("IBKR order: %s", exc)
            return {"status": False, "error": str(exc)}

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

    async def start(self) -> None:
        """Tenta ligar; se falhar fica em simulation. Nunca bloqueia."""
        await self.connect()
        log.info("IBKRClient started (mode=%s)", self._mode)

    def stop(self) -> None:
        if self._ib:
            try:
                self._ib.disconnect()
            except Exception:
                pass
        self._connected = False
        self._ib = None
