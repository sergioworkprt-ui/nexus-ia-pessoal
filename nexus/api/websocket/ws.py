import asyncio
import json
from typing import Set
from fastapi import WebSocket, WebSocketDisconnect
from nexus.services.logger.logger import get_logger

log = get_logger("ws")


class ConnectionManager:
    def __init__(self):
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._active.add(ws)
        log.info(f"WS connected. Active: {len(self._active)}")

    def disconnect(self, ws: WebSocket):
        self._active.discard(ws)

    async def broadcast(self, event: str, data: dict):
        dead = set()
        msg = json.dumps({"event": event, "data": data})
        for ws in self._active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self._active -= dead


manager = ConnectionManager()


async def ws_endpoint(websocket: WebSocket, nexus=None):
    await manager.connect(websocket)
    try:
        await manager.broadcast("connected", {"message": "NEXUS online"})
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            evt = data.get("type", "")

            if evt == "chat" and nexus:
                await manager.broadcast("avatar", {"state": "thinking"})
                response = await nexus.process(data.get("message", ""))
                await manager.broadcast("avatar", {"state": "speaking"})
                await websocket.send_text(json.dumps(
                    {"event": "chat_response", "data": {"response": response}}
                ))
                await manager.broadcast("avatar", {"state": "idle"})

            elif evt == "status" and nexus:
                ctx = nexus.get_context()
                await websocket.send_text(json.dumps(
                    {"event": "status", "data": ctx}
                ))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        log.info("WS disconnected")
