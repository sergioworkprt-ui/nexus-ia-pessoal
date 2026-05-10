import json
import os
from datetime import datetime
from typing import List, Dict
from nexus.services.logger.logger import get_logger

log = get_logger("memory")


class Memory:
    def __init__(self, max_short: int = 50, history_file: str = "data/memory.json"):
        self._short: List[Dict] = []
        self._max = max_short
        self._file = history_file
        self._load()

    def add(self, role: str, content: str):
        entry = {"role": role, "content": content, "ts": datetime.utcnow().isoformat()}
        self._short.append(entry)
        if len(self._short) > self._max:
            self._short.pop(0)
        self._save()

    def get_recent(self, n: int = 10) -> List[Dict]:
        return self._short[-n:]

    def search(self, query: str, n: int = 5) -> List[Dict]:
        return [e for e in self._short if query.lower() in e["content"].lower()][-n:]

    def clear(self):
        self._short.clear()
        self._save()
        log.info("Memory cleared")

    def _save(self):
        os.makedirs(os.path.dirname(self._file) or ".", exist_ok=True)
        with open(self._file, "w") as f:
            json.dump(self._short, f, indent=2)

    def _load(self):
        if os.path.exists(self._file):
            try:
                with open(self._file) as f:
                    self._short = json.load(f)
                log.info(f"Loaded {len(self._short)} memory entries")
            except Exception:
                self._short = []
