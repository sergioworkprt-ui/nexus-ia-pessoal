"""NEXUS V2 — entry point.

Inicia:
  • FastAPI REST API + endpoint /ws   →  API_PORT  (default 8000)
  • Servidor WebSocket standalone    →  WS_PORT   (default 8001)
  • Todos os módulos NEXUS com fallback gracioso por módulo
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

# ── Garantir que /opt/nexus está sempre no sys.path ────────────────────────────────
_NEXUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _NEXUS_ROOT not in sys.path:
    sys.path.insert(0, _NEXUS_ROOT)

# ── Carregar .env ───────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(_NEXUS_ROOT, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[NEXUS] .env carregado de {_env_path}", flush=True)
    else:
        print(f"[NEXUS] AVISO: .env não encontrado em {_env_path}", flush=True)
except ImportError:
    print("[NEXUS] AVISO: python-dotenv não instalado", flush=True)

# ── Logging ───────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
try:
    from nexus.services.logger.logger import get_logger
    log = get_logger("main")
except Exception:
    log = logging.getLogger("nexus.main")


# ── Helper: importação segura ───────────────────────────────────────────────────────────
def _load(label: str, factory):
    """Importa e instancia um módulo; retorna None em caso de qualquer erro."""
    try:
        obj = factory()
        log.info("  ✓ %s", label)
        return obj
    except Exception as exc:
        log.warning("  ✗ %s: %s", label, exc)
        return None


# ── Arranque WebSocket (porta 8001) ─────────────────────────────────────────────────
async def _start_ws() -> None:
    ws_host = os.getenv("WS_HOST", "0.0.0.0")
    ws_port = int(os.getenv("WS_PORT", "8001"))
    try:
        from nexus.ws_server import start_ws
        await start_ws(ws_host, ws_port)
    except ImportError:
        log.warning("ws_server.py não encontrado — WS na porta 8001 desactivado")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.error("WS server erro: %s", exc)


# ── Módulos opcionais ────────────────────────────────────────────────────────────────
_MODULE_MAP = [
    ("memory",         "nexus.core.memory.memory",                   "Memory"),
    ("personality",    "nexus.core.personality.personality",          "Personality"),
    ("security",       "nexus.core.security.security",                "SecurityManager"),
    ("tts",            "nexus.core.voice.tts",                        "TTS"),
    ("ml",             "nexus.modules.ml.ml",                         "MLModule"),
    ("watchdog",       "nexus.modules.watchdog.watchdog",             "Watchdog"),
    ("tasks",          "nexus.modules.tasks.tasks",                   "TaskManager"),
    ("learning",       "nexus.modules.learning.learning",             "LearningModule"),
    ("video_analysis", "nexus.modules.video_analysis.video_analysis", "VideoAnalysis"),
    ("evolution",      "nexus.modules.evolution.evolution",           "Evolution"),
    ("truth_checker",  "nexus.modules.truth_checker.truth_checker",   "TruthChecker"),
    ("xtb",            "nexus.modules.trading.xtb.xtb_client",        "XTBClient"),
    ("ibkr",           "nexus.modules.trading.ibkr.ibkr_client",      "IBKRClient"),
    ("scheduler",      "nexus.services.scheduler.scheduler",          "Scheduler"),
]


# ── Main ────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    log.info("═══ NEXUS v2 a iniciar ═══")

    # Imports críticos — se falharem, o processo termina com mensagem clara
    try:
        import uvicorn
        from nexus.api.rest.main import app, set_nexus
        from nexus.core.orchestrator.orchestrator import Orchestrator
    except ImportError as exc:
        log.critical("Import crítico falhou: %s", exc)
        log.critical("Dica: PYTHONPATH=%s já devia estar definido pelo systemd", _NEXUS_ROOT)
        sys.exit(1)

    nexus = Orchestrator()

    # Carregar módulos opcionais — cada um falha de forma independente
    for name, mod_path, cls_name in _MODULE_MAP:
        obj = _load(
            name,
            lambda p=mod_path, c=cls_name:
                getattr(__import__(p, fromlist=[c]), c)()
        )
        if obj:
            nexus.register(name, obj)

    # STT precisa de nexus.process como callback
    stt = _load("stt", lambda: getattr(
        __import__("nexus.core.voice.stt", fromlist=["STT"]), "STT"
    )(on_wake=nexus.process))
    if stt:
        nexus.register("stt", stt)

    # TradingModule precisa do SecurityManager
    sec = nexus.get("security")
    if sec:
        tm = _load("trading", lambda s=sec: getattr(
            __import__("nexus.modules.trading.trading", fromlist=["TradingModule"]),
            "TradingModule",
        )(s))
        if tm:
            nexus.register("trading", tm)

    set_nexus(nexus)

    # Configuração da API
    api_host = os.getenv("API_HOST", os.getenv("HOST", "0.0.0.0"))
    api_port = int(os.getenv("API_PORT", os.getenv("PORT", "8000")))

    cfg    = uvicorn.Config(app, host=api_host, port=api_port,
                            log_level="info", access_log=True)
    server = uvicorn.Server(cfg)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(_stop(nexus, server))
            )
        except NotImplementedError:
            pass

    log.info("API  → http://%s:%d", api_host, api_port)
    log.info("Docs → http://%s:%d/docs", api_host, api_port)
    log.info("WS   → ws://%s:%s", os.getenv("WS_HOST", "0.0.0.0"), os.getenv("WS_PORT", "8001"))

    await asyncio.gather(
        nexus.start(),
        server.serve(),
        _start_ws(),
        return_exceptions=True,
    )


async def _stop(nexus, server) -> None:
    log.info("A parar NEXUS...")
    await nexus.stop()
    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(main())
