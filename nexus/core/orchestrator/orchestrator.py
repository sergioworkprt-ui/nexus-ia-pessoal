import asyncio
import re
from typing import Any, Dict, Optional
from nexus.services.logger.logger import get_logger

log = get_logger("orchestrator")

_MODULE_START_TIMEOUT = 10.0

# Mensagens de sistema — sempre PT-PT
_MSG_BLOCKED  = "Esse pedido esta fora dos meus parametros operacionais."
_MSG_FALLBACK = "Entendido. Como posso ajudar?"
_MSG_ERROR    = "Ocorreu um erro interno no orquestrador. Tenta novamente."

_YT_DOMAIN_RE = re.compile(r"youtube\.com|youtu\.be")
_YT_URL_RE    = re.compile(r"https?://\S*(?:youtube\.com|youtu\.be)\S+")


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
        """Inicia um modulo com timeout individual. Nunca lanca excepcao."""
        try:
            await asyncio.wait_for(mod.start(), timeout=_MODULE_START_TIMEOUT)
            log.info("Module started: %s", name)
        except asyncio.TimeoutError:
            log.warning("Module '%s' start() timeout (%ss) — ignorado", name, _MODULE_START_TIMEOUT)
        except Exception as exc:
            log.warning("Module '%s' start() erro: %s", name, exc)

    async def start(self):
        self._running = True
        log.info("Orchestrator a iniciar...")
        tasks = []
        for name, mod in self._modules.items():
            if hasattr(mod, "start") and asyncio.iscoroutinefunction(mod.start):
                tasks.append(asyncio.create_task(self._start_module(name, mod)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log.info("Orchestrator pronto (%d modulos)", len(self._modules))

    async def process(self, user_input: str) -> str:
        """Pipeline completo com try/except por etapa — sempre devolve PT-PT."""
        log.info("[process] input: %.80s", user_input)
        response = _MSG_FALLBACK

        try:
            memory = self.get("memory")

            # 0. Detectar URL YouTube → pipeline de video
            if _YT_DOMAIN_RE.search(user_input):
                video = self.get("video_analysis")
                if video:
                    try:
                        urls = _YT_URL_RE.findall(user_input)
                        url = urls[0] if urls else user_input.strip()
                        log.info("[process] YouTube URL detectado: %s", url)
                        if memory:
                            try:
                                memory.add(role="user", content=user_input)
                            except Exception:
                                pass
                        result = await video.analyze(url)
                        response = video.format_chat_response(result)
                        if memory:
                            try:
                                memory.add(role="nexus", content=response)
                            except Exception:
                                pass
                        return response
                    except Exception as exc:
                        log.error("[process] video_analysis erro: %s", exc, exc_info=True)
                        return "Ocorreu um erro ao analisar o video. Tenta novamente."

            # 1. Validacao de seguranca
            security = self.get("security")
            if security:
                try:
                    if not security.validate_input(user_input):
                        return _MSG_BLOCKED
                except Exception as exc:
                    log.warning("[process] security.validate_input erro: %s", exc)

            # 2. Guardar input na memoria
            if memory:
                try:
                    memory.add(role="user", content=user_input)
                except Exception as exc:
                    log.warning("[process] memory.add(user) erro: %s", exc)

            # 3. Gerar resposta via personality (ou fallback)
            personality = self.get("personality")
            if personality:
                try:
                    response = await personality.respond(user_input, self._context)
                except Exception as exc:
                    log.error("[process] personality.respond erro: %s", exc, exc_info=True)
                    response = self._fallback(user_input)
            else:
                response = self._fallback(user_input)

            # 4. Guardar resposta na memoria
            if memory:
                try:
                    memory.add(role="nexus", content=response)
                except Exception as exc:
                    log.warning("[process] memory.add(nexus) erro: %s", exc)

            # 5. TTS (fire-and-forget)
            tts = self.get("tts")
            if tts:
                try:
                    asyncio.create_task(tts.speak(response))
                except Exception as exc:
                    log.warning("[process] tts.speak erro: %s", exc)

        except Exception as exc:
            log.error("[process] erro nao capturado: %s", exc, exc_info=True)
            return _MSG_ERROR

        return response if isinstance(response, str) and response.strip() else _MSG_FALLBACK

    def _fallback(self, text: str) -> str:
        """Fallback local sem LLM — sempre PT-PT."""
        t = text.lower()
        if any(w in t for w in ["trade", "compra", "venda", "ordem", "buy", "sell"]):
            return "Modulo de trading pronto. Indica simbolo, accao e volume."
        if any(w in t for w in ["preco", "mercado", "price", "market"]):
            return "A obter dados de mercado. Qual o activo que pretendes?"
        if any(w in t for w in ["status", "estado", "saude"]):
            return "Todos os sistemas operacionais."
        return _MSG_FALLBACK

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
        log.info("Orchestrator parado")
