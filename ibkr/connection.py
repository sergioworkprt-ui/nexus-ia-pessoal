import asyncio
from ib_insync import IB
from ibkr.config import config
from ibkr.logger import get_logger

log = get_logger("connection")


class IBKRConnection:
    def __init__(self):
        self.ib = IB()
        self._reconnect_delay = 5
        self._max_delay = 60

    async def connect(self):
        delay = self._reconnect_delay
        while True:
            try:
                await self.ib.connectAsync(
                    config.ibkr.host,
                    config.ibkr.port,
                    clientId=config.ibkr.client_id,
                    timeout=config.ibkr.timeout,
                )
                log.info(f"Connected to IBKR {'PAPER' if config.ibkr.use_paper else 'LIVE'} port={config.ibkr.port}")
                self.ib.disconnectedEvent += self._on_disconnect
                delay = self._reconnect_delay
                break
            except Exception as e:
                log.error(f"Connection failed: {e}. Retrying in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_delay)

    def _on_disconnect(self):
        log.warning("Disconnected from IBKR — scheduling reconnect")
        asyncio.ensure_future(self.connect())

    @property
    def connected(self) -> bool:
        return self.ib.isConnected()
