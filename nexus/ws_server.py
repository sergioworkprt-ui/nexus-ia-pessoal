"""NEXUS — Servidor WebSocket standalone (porta 8001).

Inicia um servidor WebSocket puro (não-FastAPI) que o dashboard
frontend usa para actualizações em tempo real.

Compatibilidade: Python 3.9+, websockets >= 10
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Set

log = logging.getLogger("nexus.ws_server")

_clients: Set[Any] = set()


async def broadcast(data: dict) -> None:
    """Envia data a todos os clientes WebSocket ligados."""
    if not _clients:
        return
    msg = json.dumps(data)
    dead: Set[Any] = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


async def _handler(ws: Any) -> None:
    _clients.add(ws)
    addr = getattr(ws, "remote_address", "?")
    log.info("WS client connected: %s  (total: %d)", addr, len(_clients))
    try:
        await ws.send(json.dumps({
            "type": "connected",
            "server": "nexus-ws",
            "version": "2.0",
        }))
        async for raw in ws:
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                elif msg_type == "avatar_state":
                    await broadcast(msg)
                else:
                    await broadcast({"type": "relay", "data": msg})
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass
    finally:
        _clients.discard(ws)
        log.info("WS client disconnected: %s  (total: %d)", addr, len(_clients))


async def start_ws(host: str = "0.0.0.0", port: int = 8001) -> None:
    """Inicia o servidor WebSocket. Corre indefinidamente até ser cancelado.

    Levanta ImportError se websockets não estiver instalado (para que o
    caller possa activar o fallback inline).
    Levanta OSError se a porta estiver ocupada ou sem permissão.
    """
    # Log imediato — antes de qualquer import, para garantir visibilidade no journal
    log.info("[WS] start_ws() chamado — host=%s port=%d", host, port)
    print(f"[NEXUS WS] start_ws() host={host} port={port}", flush=True)

    try:
        import websockets  # type: ignore
        ws_ver = getattr(websockets, "__version__", "desconhecida")
        log.info("[WS] websockets importado OK — versão=%s", ws_ver)
    except ImportError as exc:
        log.error(
            "[WS] ERRO: package 'websockets' não instalado no venv activo (%s). "
            "Corre: %s -m pip install 'websockets==10.4'",
            exc,
            __import__('sys').executable,
        )
        raise  # propaga para _start_ws() activar o fallback

    log.info("[WS] A iniciar websockets.serve em ws://%s:%d ...", host, port)
    try:
        async with websockets.serve(_handler, host, port):  # type: ignore[attr-defined]
            log.info("[WS] NEXUS WebSocket ONLINE em ws://%s:%d", host, port)
            print(f"[NEXUS WS] ONLINE ws://{host}:{port}", flush=True)
            await asyncio.Future()  # corre até ser cancelado
    except OSError as exc:
        log.error("[WS] Não consigo ligar a %s:%d → %s", host, port, exc)
        raise
    except asyncio.CancelledError:
        log.info("[WS] Server parado (CancelledError)")
        raise
    except Exception as exc:
        log.exception("[WS] Erro inesperado em ws://%s:%d", host, port)
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    )
    _h = os.getenv("WS_HOST", "0.0.0.0")
    _p = int(os.getenv("WS_PORT", "8001"))
    asyncio.run(start_ws(_h, _p))
