"""Task Manager — persistent queue with approval workflow."""
from __future__ import annotations
import json, uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from nexus.services.logger.logger import get_logger

log = get_logger("tasks")


class TaskManager:
    def __init__(self, data_dir: str = "/data/nexus"):
        self._path = Path(data_dir) / "tasks.json"
        self._tasks: dict[str, dict] = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text()) if self._path.exists() else {}
        except Exception:
            return {}

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._tasks, indent=2, default=str))
        except Exception as e:
            log.warning(f"tasks save: {e}")

    def create(self, title: str, type_: str, payload: dict | None = None, needs_approval: bool = False) -> dict:
        tid = str(uuid.uuid4())[:8]
        task = {
            "id": tid, "title": title, "type": type_,
            "status": "waiting_approval" if needs_approval else "pending",
            "payload": payload or {}, "result": None, "error": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._tasks[tid] = task
        self._save()
        log.info(f"task created: {tid} [{type_}] {title}")
        return task

    def get(self, tid: str) -> dict | None:
        return self._tasks.get(tid)

    def list_tasks(self, status: str | None = None, type_: str | None = None) -> list[dict]:
        items = list(self._tasks.values())
        if status:
            items = [t for t in items if t["status"] == status]
        if type_:
            items = [t for t in items if t["type"] == type_]
        return sorted(items, key=lambda t: t["created_at"], reverse=True)

    def approve(self, tid: str) -> bool:
        if t := self._tasks.get(tid):
            t.update({"status": "pending", "updated_at": datetime.utcnow().isoformat()})
            self._save()
            log.info(f"task approved: {tid}")
            return True
        return False

    def update(self, tid: str, status: str, result: Any = None, error: str | None = None):
        if t := self._tasks.get(tid):
            t.update({"status": status, "updated_at": datetime.utcnow().isoformat()})
            if result is not None:
                t["result"] = result
            if error is not None:
                t["error"] = error
            self._save()

    def delete(self, tid: str) -> bool:
        if tid in self._tasks:
            del self._tasks[tid]
            self._save()
            return True
        return False

    async def start(self):
        log.info("TaskManager started")

    def stop(self):
        pass
