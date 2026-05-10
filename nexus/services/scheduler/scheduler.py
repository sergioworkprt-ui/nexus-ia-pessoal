import asyncio
from typing import Callable, List, Tuple
from nexus.services.logger.logger import get_logger

log = get_logger("scheduler")


class Scheduler:
    def __init__(self):
        self._tasks: List[Tuple[int, Callable]] = []
        self._running = False

    def every(self, seconds: int, fn: Callable):
        self._tasks.append((seconds, fn))
        log.info(f"Scheduled: {fn.__name__} every {seconds}s")

    async def start(self):
        self._running = True
        if not self._tasks:
            return
        await asyncio.gather(*[self._loop(s, fn) for s, fn in self._tasks])

    async def _loop(self, interval: int, fn: Callable):
        while self._running:
            try:
                if asyncio.iscoroutinefunction(fn):
                    await fn()
                else:
                    fn()
            except Exception as e:
                log.error(f"Error in {fn.__name__}: {e}")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False
