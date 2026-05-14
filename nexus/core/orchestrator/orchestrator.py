import asyncio
from typing import Any, Dict, Optional
from nexus.services.logger.logger import get_logger

log = get_logger("orchestrator")

_MODULE_START_TIMEOUT = 10.0


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
        """Pipeline completo com try/except por etapa — nunca propaga excepção."""
        log.info("[process] input: %s", user_input[:80])
        response = "Online. Como posso ajudar?"

        try:
            # 1. Validação de segurança
            security = self.get("security")
            if security:
                try:
                    if not security.validate_input(user_input):
                        return "Esse pedido está fora dos meus parâmetros operacionais."
                except Exception as exc:
                    log.warning("[process] security.validate_input erro: %s", exc)

            # 2. Guardar input na memória
            memory = self.get("memory")
            if memory:
                try:
                    memory.add(role="user", content=user_input)
                except Exception as exc:
                    log.warning("[process] memory.add(user) erro: %s", exc)

            # 3. Gerar resposta via personality
            personality = self.get("personality")
            if personality:
                try:
                    response = await personality.respond(user_input, self._context)
                except Exception as exc:
                    log.error("[process] personality.respond erro: %s", exc, exc_info=True)
                    response = self._simple_fallback(user_input)
            else:
                response = self._simple_fallback(user_input)

            # 4. Guardar resposta na memória
            if memory:
                try:
                    memory.add(role="nexus", content=response)
                except Exception as exc:
                    log.warning("[process] memory.add(nexus) erro: %s", exc)

            # 5. TTS (fire-and-forget, nunca bloqueia)
            tts = self.get("tts")
            if tts:
                try:
                    asyncio.create_task(tts.speak(response))
                except Exception as exc:
                    log.warning("[process] tts.speak erro: %s", exc)

        except Exception as exc:
            log.error("[process] erro não capturado: %s", exc, exc_info=True)
            response = "Ocorreu um erro interno no orquestrador."

        return response

    def _simple_fallback(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["trade", "compra", "venda", "ordem", "buy", "sell"]):
            return "Módulo de trading pronto. Especifica símbolo, acção e quantidade."
        if any(w in t for w in ["preço", "mercado", "price", "market"]):
            return "A obter dados de mercado."
        if "status" in t or "estado" in t:
            return "Todos os sistemas operacionais."
        return "Entendido. Como posso ajudar?"

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
