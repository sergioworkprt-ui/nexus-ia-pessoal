import asyncio
from typing import List
from ibkr.strategies.base import BaseStrategy
from ibkr.logger import get_logger

log = get_logger("scheduler")


class Scheduler:
    def __init__(self):
        self._strategies: List[BaseStrategy] = []

    def add(self, strategy: BaseStrategy):
        self._strategies.append(strategy)
        log.info(f"Registered strategy: {strategy.name}")

    async def run_all(self):
        if not self._strategies:
            log.warning("No strategies registered — scheduler idle")
            return
        log.info(f"Running {len(self._strategies)} strategies")
        await asyncio.gather(
            *[asyncio.create_task(s.run()) for s in self._strategies],
            return_exceptions=True,
        )

    def stop_all(self):
        for s in self._strategies:
            s.stop()
        log.info("All strategies stopped")
