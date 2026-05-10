"""XTB Trading Client — WebSocket JSON protocol."""
from __future__ import annotations
import asyncio, json, os, ssl
import websockets
from nexus.services.logger.logger import get_logger

log = get_logger("xtb")

_SERVERS = {
    "demo": "wss://ws.xtb.com/demo",
    "real": "wss://ws.xtb.com/real",
}


class XTBClient:
    def __init__(self):
        self._account = os.getenv("XTB_ACCOUNT_ID", "")
        self._password = os.getenv("XTB_PASSWORD", "")
        self._server = os.getenv("XTB_SERVER", "demo")
        self._ws = None
        self._session: str | None = None
        self._connected = False
        self._positions: list = []
        self._balance: dict = {}
        self._mode = "simulation"
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None

    async def _send(self, cmd: str, args: dict | None = None) -> dict:
        async with self._lock:
            if not self._ws:
                return {"status": False, "error": "not connected"}
            payload: dict = {"command": cmd}
            if args:
                payload["arguments"] = args
            await self._ws.send(json.dumps(payload))
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            return json.loads(raw)

    async def connect(self) -> bool:
        if not self._account or not self._password:
            log.info("XTB: no credentials — simulation mode")
            return False
        url = _SERVERS.get(self._server, _SERVERS["demo"])
        try:
            self._ws = await websockets.connect(
                url, ssl=ssl.create_default_context(), ping_interval=30
            )
            resp = await self._send("login", {"userId": self._account, "password": self._password})
            if resp.get("status"):
                self._session = resp.get("streamSessionId")
                self._connected = True
                log.info(f"XTB connected ({self._server})")
                return True
            log.error(f"XTB login failed: {resp.get('errorDescr', 'unknown')}")
        except Exception as e:
            log.error(f"XTB connect: {e}")
        self._connected = False
        return False

    async def get_balance(self) -> dict:
        if not self.connected:
            return self._balance
        resp = await self._send("getMarginLevel")
        if resp.get("status"):
            self._balance = resp.get("returnData", {})
        return self._balance

    async def get_positions(self) -> list:
        if not self.connected:
            return self._positions
        resp = await self._send("getTrades", {"openedOnly": True})
        if resp.get("status"):
            self._positions = resp.get("returnData", [])
        return self._positions

    async def place_order(self, symbol: str, cmd: int, volume: float,
                          sl: float = 0.0, tp: float = 0.0, price: float = 0.0) -> dict:
        if self._mode == "simulation":
            log.info(f"[SIM] XTB: {symbol} cmd={cmd} vol={volume}")
            return {"status": True, "simulation": True, "symbol": symbol,
                    "cmd": cmd, "volume": volume}
        if not self.connected:
            return {"status": False, "error": "not connected"}
        return await self._send("tradeTransaction", {
            "tradeTransInfo": {
                "cmd": cmd, "symbol": symbol, "volume": volume,
                "sl": sl, "tp": tp, "price": price, "type": 0,
                "comment": "NEXUS", "expiration": 0,
            }
        })

    def enable_real(self, confirm_code: str) -> bool:
        if confirm_code == os.getenv("TRADING_CONFIRM_CODE", "NEXUS-REAL-CONFIRM"):
            self._mode = "real"
            log.warning("XTB REAL mode enabled")
            return True
        return False

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "server": self._server,
            "mode": self._mode,
            "positions_cached": len(self._positions),
            "configured": bool(self._account),
        }

    async def _keepalive(self):
        while True:
            await asyncio.sleep(55)
            if not self._connected:
                await asyncio.sleep(10)
                await self.connect()
                continue
            try:
                await self._send("ping")
            except Exception:
                self._connected = False

    async def start(self):
        if self._account and self._password:
            await self.connect()
        asyncio.create_task(self._keepalive())
        log.info(f"XTBClient started (mode={self._mode})")

    def stop(self):
        self._connected = False
