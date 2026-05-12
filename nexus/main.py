"""NEXUS V2 — entry point adaptativo.

Modo COMPLETO  : usa Orchestrator + nexus.api.rest.main  (se disponível)
Modo MÍNIMO   : FastAPI inline + /health + /ws  (garante sempre API+WS)
Porta API : API_PORT  (default 8000)
Porta WS  : WS_PORT   (default 8001)
"""
from __future__ import annotations
import asyncio, json, logging, os, signal, sys

# ─ PYTHONPATH auto-fix: garante que /opt/nexus está sempre no path ─────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ─ Carregar .env ─────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _ep = os.path.join(_ROOT, ".env")
    if os.path.exists(_ep):
        load_dotenv(_ep)
        print(f"[NEXUS] .env carregado de {_ep}", flush=True)
except ImportError:
    print("[NEXUS] AVISO: python-dotenv não instalado", flush=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")
log = logging.getLogger("nexus.main")

import uvicorn

# ─ Tentar modo COMPLETO, cair para modo MÍNIMO se falhar ──────────────────
_FULL = False
try:
    from nexus.api.rest.main import app, set_nexus          # type: ignore
    from nexus.core.orchestrator.orchestrator import Orchestrator  # type: ignore
    _FULL = True
    log.info("Modo COMPLETO: nexus.api.rest.main + Orchestrator carregados")
except Exception as _e:
    log.warning("Modo MÍNIMO (módulos completos indisponíveis: %s)", _e)
    from fastapi import FastAPI, WebSocket as _FWS
    from fastapi.middleware.cors import CORSMiddleware
    app = FastAPI(title="NEXUS API", version="2.0.0", docs_url="/docs")  # type: ignore
    app.add_middleware(CORSMiddleware,                                   # type: ignore
                       allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")                                                  # type: ignore
    def _h():
        return {"status": "ok", "version": "2.0.0", "mode": "minimal"}

    @app.get("/status")                                                  # type: ignore
    def _st():
        return {"status": "minimal", "api": "running",
                "ws_port": int(os.getenv("WS_PORT", "8001"))}

    _ws_conns: set = set()

    @app.websocket("/ws")                                                # type: ignore
    async def _wse(ws: _FWS):
        await ws.accept()
        _ws_conns.add(ws)
        try:
            await ws.send_json({"type": "connected", "mode": "minimal", "version": "2.0"})
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=30)
                    if json.loads(msg).get("type") == "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "heartbeat"})
                except Exception:
                    break
        except Exception:
            pass
        finally:
            _ws_conns.discard(ws)

    def set_nexus(_): pass  # type: ignore  # noqa: E301


# ─ WS standalone porta 8001 ──────────────────────────────────────────────
async def _start_ws() -> None:
    h = os.getenv("WS_HOST", "0.0.0.0")
    p = int(os.getenv("WS_PORT", "8001"))

    # Log imediato para garantir visibilidade no journal
    log.info("[WS] _start_ws() → host=%s port=%d  python=%s", h, p, sys.executable)
    print(f"[NEXUS WS] _start_ws() host={h} port={p} python={sys.executable}", flush=True)

    # ── Tentativa 1: ws_server.py dedicado ───────────────────────────────
    try:
        from nexus.ws_server import start_ws  # type: ignore
        log.info("[WS] nexus.ws_server importado — a chamar start_ws()")
        await start_ws(h, p)
        return  # só chega aqui se start_ws() terminar normalmente (cancelado)
    except ImportError as ex:
        log.warning("[WS] nexus.ws_server não disponível (%s) — a tentar fallback inline", ex)
    except asyncio.CancelledError:
        raise
    except Exception as ex:
        # Log com stacktrace COMPLETO para diagnóstico
        log.exception("[WS] nexus.ws_server.start_ws() falhou — a tentar fallback inline")
    # NOTA: não fazemos return aqui — continuamos para o fallback

    # ── Tentativa 2: websockets inline ───────────────────────────────────
    log.info("[WS] A iniciar fallback websockets inline em ws://%s:%d", h, p)
    try:
        import websockets  # type: ignore
        ws_ver = getattr(websockets, "__version__", "?")
        log.info("[WS] websockets inline — versão=%s", ws_ver)

        _cl: set = set()

        async def _hh(ws: object) -> None:
            _cl.add(ws)
            try:
                await ws.send(json.dumps({"type": "connected", "mode": "inline"}))  # type: ignore
                async for _ in ws:  # type: ignore
                    pass
            except Exception:
                pass
            finally:
                _cl.discard(ws)

        async with websockets.serve(_hh, h, p):  # type: ignore
            log.info("[WS] Fallback inline ONLINE em ws://%s:%d", h, p)
            print(f"[NEXUS WS] fallback inline ONLINE ws://{h}:{p}", flush=True)
            await asyncio.Future()

    except ImportError as ex:
        log.error(
            "[WS] ERRO FATAL: websockets não instalado no venv activo.\n"
            "  Python: %s\n"
            "  Erro:   %s\n"
            "  Fix:    %s -m pip install 'websockets==10.4'",
            sys.executable, ex, sys.executable,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("[WS] Fallback inline falhou em %s:%d", h, p)


# ─ Módulos opcionais (modo completo) ───────────────────────────────────────
_MODS = [
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


def _load(lbl, fn):
    try:
        r = fn()
        log.info("  ✓ %s", lbl)
        return r
    except Exception as e:
        log.warning("  ✗ %s: %s", lbl, e)
        return None


# ─ Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    log.info("═══ NEXUS v2 a iniciar (%s) ═══", "COMPLETO" if _FULL else "MÍNIMO")
    log.info("Python: %s", sys.executable)

    ah = os.getenv("API_HOST", os.getenv("HOST", "0.0.0.0"))
    ap = int(os.getenv("API_PORT", os.getenv("PORT", "8000")))

    _nexus = None
    if _FULL:
        _nexus = Orchestrator()  # type: ignore
        for n, mp, cn in _MODS:
            obj = _load(n, lambda p=mp, c=cn:
                        getattr(__import__(p, fromlist=[c]), c)())
            if obj:
                _nexus.register(n, obj)
        stt = _load("stt", lambda: getattr(
            __import__("nexus.core.voice.stt", fromlist=["STT"]), "STT"
        )(on_wake=_nexus.process))
        if stt:
            _nexus.register("stt", stt)
        sec = _nexus.get("security")
        if sec:
            tm = _load("trading", lambda s=sec: getattr(
                __import__("nexus.modules.trading.trading", fromlist=["TradingModule"]),
                "TradingModule")(s))
            if tm:
                _nexus.register("trading", tm)
        set_nexus(_nexus)  # type: ignore

    cfg    = uvicorn.Config(app, host=ah, port=ap, log_level="info", access_log=True)
    server = uvicorn.Server(cfg)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            _sv = server
            _nx = _nexus
            loop.add_signal_handler(
                sig, lambda s=_sv, n=_nx: asyncio.create_task(_stop(n, s))
            )
        except NotImplementedError:
            pass

    log.info("API  → http://%s:%d  (%s)", ah, ap, "full" if _FULL else "minimal")
    log.info("Docs → http://%s:%d/docs", ah, ap)
    log.info("WS   → ws://%s:%s",
             os.getenv("WS_HOST", "0.0.0.0"), os.getenv("WS_PORT", "8001"))

    tasks = [server.serve(), _start_ws()]
    if _FULL and _nexus:
        tasks.insert(0, _nexus.start())
    await asyncio.gather(*tasks, return_exceptions=True)


async def _stop(nexus, server) -> None:
    log.info("A parar NEXUS...")
    if nexus:
        try:
            await nexus.stop()
        except Exception:
            pass
    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(main())
