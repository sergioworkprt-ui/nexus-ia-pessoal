import asyncio
import os
import signal
from dotenv import load_dotenv
load_dotenv()

import uvicorn
from nexus.core.orchestrator.orchestrator import Orchestrator
from nexus.core.memory.memory import Memory
from nexus.core.personality.personality import Personality
from nexus.core.security.security import SecurityManager
from nexus.core.voice.tts import TTS
from nexus.core.voice.stt import STT
from nexus.modules.trading.trading import TradingModule
from nexus.modules.ml.ml import MLModule
from nexus.modules.watchdog.watchdog import Watchdog
from nexus.services.scheduler.scheduler import Scheduler
from nexus.services.logger.logger import get_logger
from nexus.api.rest.main import app, set_nexus

log = get_logger("main")


async def main():
    nexus = Orchestrator()
    security = SecurityManager()

    nexus.register("memory",      Memory())
    nexus.register("personality", Personality())
    nexus.register("security",    security)
    nexus.register("tts",         TTS())
    nexus.register("stt",         STT(on_wake=nexus.process))
    nexus.register("trading",     TradingModule(security))
    nexus.register("ml",          MLModule())
    nexus.register("watchdog",    Watchdog())
    nexus.register("scheduler",   Scheduler())

    set_nexus(nexus)

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    cfg = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(cfg)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_stop(nexus, server)))

    log.info(f"NEXUS starting on {host}:{port}")
    await asyncio.gather(
        nexus.start(),
        server.serve(),
        return_exceptions=True,
    )


async def _stop(nexus, server):
    log.info("Shutting down NEXUS")
    await nexus.stop()
    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(main())
