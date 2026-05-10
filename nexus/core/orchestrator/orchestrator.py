import asyncio
from typing import Any, Dict, Optional
from nexus.services.logger.logger import get_logger

log = get_logger("orchestrator")


class Orchestrator:
    """Central coordinator — boots all modules, routes requests."""

    def __init__(self):
        self._modules: Dict[str, Any] = {}
        self._context: Dict[str, Any] = {}
        self._running = False

    def register(self, name: str, module: Any):
        self._modules[name] = module
        log.info(f"Module registered: {name}")

    def get(self, name: str) -> Optional[Any]:
        return self._modules.get(name)

    async def start(self):
        self._running = True
        log.info("Orchestrator started")
        tasks = []
        for name, mod in self._modules.items():
            if hasattr(mod, "start") and asyncio.iscoroutinefunction(mod.start):
                tasks.append(asyncio.create_task(mod.start()))
                log.info(f"Module started: {name}")
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def process(self, user_input: str) -> str:
        """Route user input through security → personality → response."""
        log.info(f"Input: {user_input[:80]}")

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
                mod.stop()
        log.info("Orchestrator stopped")
