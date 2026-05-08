import asyncio
from ibkr.logger import get_logger


class BaseStrategy:
    """
    Inherit from this class to create a strategy.

    Override:
      - on_start()  — called once before the loop
      - on_tick()   — called every `interval` seconds
      - on_stop()   — called on shutdown
    """

    def __init__(self, nexus, name: str, interval: int = 60):
        self.nexus = nexus
        self.name = name
        self.interval = interval
        self.running = False
        self.log = get_logger(f"strategy.{name}")

    async def on_start(self):
        pass

    async def on_tick(self):
        raise NotImplementedError

    async def on_stop(self):
        pass

    async def run(self):
        self.running = True
        await self.on_start()
        self.log.info(f"Strategy '{self.name}' started (interval={self.interval}s)")
        while self.running:
            try:
                await self.on_tick()
            except Exception as e:
                self.log.error(f"Tick error in '{self.name}': {e}", exc_info=True)
            await asyncio.sleep(self.interval)
        await self.on_stop()
        self.log.info(f"Strategy '{self.name}' stopped")

    def stop(self):
        self.running = False
