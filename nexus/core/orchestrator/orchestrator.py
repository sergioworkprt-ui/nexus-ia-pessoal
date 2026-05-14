import asyncio
from typing import Any, Dict, Optional
from nexus.services.logger.logger import get_logger

log = get_logger("orchestrator")

_MODULE_START_TIMEOUT = 10.0  # segundos por módulo


class Orchestrator:
    """Central coordinator — boots all modules, routes requests."""

    def __init__(self):
        self._modules: Dict[str, Any] = {}
        self._context: Dict[str, Any] = {}
        self._running = False

    def register(self, name: str, module: Any):
        self._modules[name] = module
        log.info("Module registered: %s", name)

    def get(self, name: str) -> Optional[Any]:
        return self._modules.get(name)

    async def _start_module(self, name: str, mod: Any) -> None:
        """Inicia um módulo com timeout individual. Nunca lança excepção."""
        try:
            await asyncio.wait_for(mod.start(), timeout=_MODULE_START_TIMEOUT)
            log.info("Module started: %s", name)
        except asyncio.TimeoutError:
            log.warning("Module '%s' start() timeout (%ss) — ignorado", name, _MODULE_START_TIMEOUT)
        except Exception as exc:
            log.warning("Module '%s' start() erro: %s", name, exc)

    async def start(self):
        self._running = True
        log.info("Orchestrator starting...")
        tasks = []
        for name, mod in self._modules.items():
            if hasattr(mod, "start") and asyncio.iscoroutinefunction(mod.start):
                tasks.append(asyncio.create_task(self._start_module(name, mod)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log.info("Orchestrator ready (%d modules)", len(self._modules))

    async def process(self, user_input: str) -> str:
        """Route user input through security → personality → response."""
        log.info("Input: %s", user_input[:80])

        security = self.get("security")
        if security and not security.validate_input(user_input):
            return "That request is outside my operational parameters."

        memory = self.get("memory")
        if memory:
            memory.add(role="user", content=user_input)

        personality = self.get("personality")
        if personality:
            response = await personality.respond(user_input, self._context)
        else:
            response = "Online. How can I help?"

        if memory:
            memory.add(role="nexus", content=response)

        tts = self.get("tts")
        if tts:
            asyncio.create_task(tts.speak(response))

        return response

    def update_context(self, key: str, value: Any):
        self._context[key] = value

    def get_context(self) -> Dict:
        return dict(self._context)

    async def stop(self):
        self._running = False
        for name, mod in self._modules.items():
            if hasattr(mod, "stop"):
                try:
                    mod.stop()
                except Exception as exc:
                    log.warning("Module '%s' stop() erro: %s", name, exc)
        log.info("Orchestrator stopped")
