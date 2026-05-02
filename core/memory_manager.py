"""
NEXUS Core — Memory Manager
Short-term (in-process) and long-term (file-persisted) memory system.
"""

import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MemoryEntry:
    key: str
    value: Any
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ttl_seconds: Optional[int] = None  # None = never expires
    tags: List[str] = field(default_factory=list)
    access_count: int = 0

    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        age = time.time() - datetime.fromisoformat(self.created_at).timestamp()
        return age > self.ttl_seconds

    def touch(self) -> None:
        self.accessed_at = datetime.now(timezone.utc).isoformat()
        self.access_count += 1


class ShortTermMemory:
    """
    Thread-safe LRU cache for ephemeral session data.
    Entries expire by TTL or are evicted when capacity is exceeded.
    """

    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._store: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._lock = threading.RLock()

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = 3600, tags: Optional[List[str]] = None) -> None:
        with self._lock:
            self._evict_expired()
            if len(self._store) >= self._capacity:
                self._store.popitem(last=False)  # evict LRU
            self._store[key] = MemoryEntry(key=key, value=value, ttl_seconds=ttl_seconds, tags=tags or [])
            self._store.move_to_end(key)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del self._store[key]
                return None
            entry.touch()
            self._store.move_to_end(key)
            return entry.value

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def keys(self) -> List[str]:
        with self._lock:
            self._evict_expired()
            return list(self._store.keys())

    def stats(self) -> Dict[str, int]:
        with self._lock:
            self._evict_expired()
            return {"size": len(self._store), "capacity": self._capacity}

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._store.items() if v.is_expired()]
        for k in expired:
            del self._store[k]


class LongTermMemory:
    """
    Persistent memory backed by a JSON file.
    Suitable for facts, preferences, and accumulated knowledge.
    """

    def __init__(self, storage_path: str = "data/long_term_memory.json") -> None:
        self._path = Path(storage_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._store: Dict[str, MemoryEntry] = {}
        self._load()

    def set(self, key: str, value: Any, tags: Optional[List[str]] = None) -> None:
        with self._lock:
            existing = self._store.get(key)
            if existing:
                existing.value = value
                existing.touch()
            else:
                self._store[key] = MemoryEntry(key=key, value=value, tags=tags or [])
            self._persist()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            entry.touch()
            self._persist()
            return entry.value

    def delete(self, key: str) -> bool:
        with self._lock:
            existed = self._store.pop(key, None) is not None
            if existed:
                self._persist()
            return existed

    def search_by_tag(self, tag: str) -> Dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._store.items() if tag in v.tags}

    def all_keys(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"entries": len(self._store)}

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw: Dict[str, dict] = json.loads(self._path.read_text(encoding="utf-8"))
            self._store = {k: MemoryEntry(**v) for k, v in raw.items()}
        except (json.JSONDecodeError, TypeError):
            self._store = {}

    def _persist(self) -> None:
        data = {k: asdict(v) for k, v in self._store.items()}
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class MemoryManager:
    """
    Unified facade for short-term and long-term memory.
    Callers should interact through this class only.
    """

    def __init__(
        self,
        stm_capacity: int = 512,
        ltm_path: str = "data/long_term_memory.json",
    ) -> None:
        self.short_term = ShortTermMemory(capacity=stm_capacity)
        self.long_term = LongTermMemory(storage_path=ltm_path)

    def remember(self, key: str, value: Any, permanent: bool = False, **kwargs: Any) -> None:
        """Store a value in short-term memory (and optionally long-term)."""
        self.short_term.set(key, value, **kwargs)
        if permanent:
            self.long_term.set(key, value, tags=kwargs.get("tags"))

    def recall(self, key: str, fallback_to_ltm: bool = True) -> Optional[Any]:
        """Retrieve a value, checking short-term first, then long-term."""
        value = self.short_term.get(key)
        if value is None and fallback_to_ltm:
            value = self.long_term.get(key)
            if value is not None:
                self.short_term.set(key, value)  # promote to STM
        return value

    def forget(self, key: str, permanent: bool = False) -> None:
        self.short_term.delete(key)
        if permanent:
            self.long_term.delete(key)

    def stats(self) -> Dict[str, Any]:
        return {
            "short_term": self.short_term.stats(),
            "long_term": self.long_term.stats(),
        }
