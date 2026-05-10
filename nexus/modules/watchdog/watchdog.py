import asyncio
from typing import Dict, List
import psutil
from nexus.services.logger.logger import get_logger

log = get_logger("watchdog")


class Watchdog:
    def __init__(self, interval: int = 30):
        self._interval = interval
        self._running = False
        self._alerts: List[str] = []

    async def start(self):
        self._running = True
        log.info("Watchdog started")
        while self._running:
            await asyncio.sleep(self._interval)
            self._check()

    def _check(self):
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        log.debug(f"CPU={cpu}% MEM={mem}% DISK={disk}%")
        for label, val in [("CPU", cpu), ("MEM", mem), ("DISK", disk)]:
            if val > 90:
                alert = f"HIGH {label}: {val}%"
                log.warning(alert)
                self._alerts.append(alert)
                if len(self._alerts) > 100:
                    self._alerts.pop(0)

    def stop(self):
        self._running = False

    def status(self) -> Dict:
        return {
            "cpu": psutil.cpu_percent(),
            "memory": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage("/").percent,
            "alerts": self._alerts[-5:],
        }
