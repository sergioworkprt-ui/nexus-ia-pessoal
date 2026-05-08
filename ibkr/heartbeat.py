import asyncio
from ibkr.config import config
from ibkr.logger import get_logger

log = get_logger("heartbeat")


class Heartbeat:
    def __init__(self, nexus):
        self._nexus = nexus
        self._interval = config.heartbeat_interval
        self._running = False
        self._failures = 0
        self._max_failures = 3

    async def start(self):
        self._running = True
        log.info(f"Heartbeat started (interval={self._interval}s)")
        while self._running:
            await asyncio.sleep(self._interval)
            await self._beat()

    async def _beat(self):
        try:
            if self._nexus.ib.isConnected():
                await self._nexus.ib.reqCurrentTimeAsync()
                self._failures = 0
                log.debug("Heartbeat OK")
            else:
                raise ConnectionError("IBKR not connected")
        except Exception as e:
            self._failures += 1
            log.warning(f"Heartbeat failed ({self._failures}/{self._max_failures}): {e}")
            if self._failures >= self._max_failures:
                log.error("Max heartbeat failures — forcing reconnect")
                self._failures = 0
                asyncio.ensure_future(self._nexus._conn.connect())

    def stop(self):
        self._running = False
        log.info("Heartbeat stopped")
