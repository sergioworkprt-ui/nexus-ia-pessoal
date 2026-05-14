"""NEXUS API Server — entry point resiliente para uvicorn.

Tenta carregar nexus.api.rest.main:app.
Se falhar por qualquer razão (ImportError, PermissionError, etc.),
arranca um app mínimo que SEMPRE responde em :8000 e exibe o erro
via GET /health — visível no browser e no proxy do dashboard.

Uso (uvicorn):
  uvicorn nexus.api_server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import sys
import traceback

# Garantir que o projecto está no PYTHONPATH
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Carregar .env se python-dotenv estiver instalado
try:
    from dotenv import load_dotenv  # type: ignore
    _ep = os.path.join(_ROOT, ".env")
    if os.path.exists(_ep):
        load_dotenv(_ep)
except ImportError:
    pass

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
_log = logging.getLogger("nexus.api_server")

_import_error: str | None = None
_import_tb: str | None = None

try:
    from nexus.api.rest.main import app  # type: ignore  # noqa: F401
    _log.info("[api_server] nexus.api.rest.main carregado com sucesso")
except Exception as _exc:
    _import_error = f"{type(_exc).__name__}: {_exc}"
    _import_tb = traceback.format_exc()
    _log.error(
        "[api_server] nexus.api.rest.main falhou: %s\n%s",
        _import_error, _import_tb,
    )
    print(f"[NEXUS API] ERRO DE IMPORT: {_import_error}", flush=True)
    print(_import_tb, flush=True)

    # Criar app mínimo que SEMPRE responde — expondo o erro via /health
    from fastapi import FastAPI, WebSocket
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="NEXUS API (mínimo)", version="2.0.0")  # type: ignore[assignment]
    app.add_middleware(  # type: ignore[arg-type]
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _err_snapshot = _import_error
    _tb_snapshot = _import_tb

    @app.get("/health")  # type: ignore[misc]
    def _health():
        return {
            "status": "degraded",
            "version": "2.0.0",
            "mode": "minimal",
            "error": _err_snapshot,
            "fix": "journalctl -u nexus-core -n 50 --no-pager",
        }

    @app.get("/status")  # type: ignore[misc]
    def _status():
        return {"api": "minimal", "error": _err_snapshot}

    @app.post("/chat")  # type: ignore[misc]
    def _chat(body: dict = None):  # type: ignore[assignment]
        return {
            "response": f"NEXUS em modo mínimo. Erro: {_err_snapshot}",
            "nexus_ready": False,
        }

    _ws_clients: list = []

    @app.websocket("/ws")  # type: ignore[misc]
    async def _ws(websocket: WebSocket):
        import json
        await websocket.accept()
        try:
            await websocket.send_text(json.dumps({
                "type": "connected",
                "mode": "minimal",
                "error": _err_snapshot,
            }))
            while True:
                try:
                    import asyncio
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    if json.loads(raw).get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except asyncio.TimeoutError:
                    await websocket.send_text(json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "nexus.api_server:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        log_level="info",
    )
