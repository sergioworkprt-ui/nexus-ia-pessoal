import asyncio
import signal
from ibkr.nexus_ibkr import NexusIBKR
from ibkr.heartbeat import Heartbeat
from ibkr.strategies.scheduler import Scheduler
from ibkr.strategies.example import ExampleStrategy
from ibkr.logger import get_logger

log = get_logger("main")


async def main():
    nexus = NexusIBKR()
    await nexus.start()

    heartbeat = Heartbeat(nexus)
    scheduler = Scheduler()

    # --- Register strategies here ---
    scheduler.add(ExampleStrategy(nexus))
    # scheduler.add(MyOtherStrategy(nexus))

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda: asyncio.create_task(_shutdown(heartbeat, scheduler, nexus))
        )

    log.info("NEXUS-IBKR running")
    await asyncio.gather(heartbeat.start(), scheduler.run_all())


async def _shutdown(heartbeat, scheduler, nexus):
    log.info("Shutdown initiated")
    heartbeat.stop()
    scheduler.stop_all()
    nexus.ib.disconnect()
    asyncio.get_event_loop().stop()


if __name__ == "__main__":
    asyncio.run(main())
