"""
NEXUS Runtime — State Manager
Persistent runtime state with checkpoint/restore and safe rollback.
State is serialized to JSON; a rolling window of checkpoints is maintained.
Thread-safe. No external dependencies.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass
class RuntimeState:
    """Snapshot of the NEXUS runtime at a point in time."""
    state_id:       str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    created_at:     str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    runtime_mode:   str   = "simulation"
    started_at:     Optional[str] = None
    uptime_seconds: float = 0.0
    cycle_count:    int   = 0
    last_cycle_at:  Optional[str] = None

    # Module readiness flags
    modules: Dict[str, bool] = field(default_factory=lambda: {
        "core":             False,
        "auto_evolution":   False,
        "profit_engine":    False,
        "web_intelligence": False,
        "multi_ia":         False,
        "reports":          False,
    })

    # Pipeline last-run timestamps
    pipeline_last_run: Dict[str, Optional[str]] = field(default_factory=lambda: {
        "intelligence": None,
        "financial":    None,
        "evolution":    None,
        "consensus":    None,
        "reporting":    None,
    })

    # Counters
    pipeline_runs:    Dict[str, int] = field(default_factory=lambda: {
        "intelligence": 0, "financial": 0, "evolution": 0,
        "consensus": 0, "reporting": 0,
    })
    pipeline_errors:  Dict[str, int] = field(default_factory=lambda: {
        "intelligence": 0, "financial": 0, "evolution": 0,
        "consensus": 0, "reporting": 0,
    })

    # Arbitrary key-value store for cross-pipeline context
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id":          self.state_id,
            "created_at":        self.created_at,
            "runtime_mode":      self.runtime_mode,
            "started_at":        self.started_at,
            "uptime_seconds":    round(self.uptime_seconds, 2),
            "cycle_count":       self.cycle_count,
            "last_cycle_at":     self.last_cycle_at,
            "modules":           self.modules,
            "pipeline_last_run": self.pipeline_last_run,
            "pipeline_runs":     self.pipeline_runs,
            "pipeline_errors":   self.pipeline_errors,
            "context":           self.context,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RuntimeState":
        s = cls()
        s.state_id       = d.get("state_id",       s.state_id)
        s.created_at     = d.get("created_at",     s.created_at)
        s.runtime_mode   = d.get("runtime_mode",   s.runtime_mode)
        s.started_at     = d.get("started_at",     s.started_at)
        s.uptime_seconds = float(d.get("uptime_seconds", 0))
        s.cycle_count    = int(d.get("cycle_count", 0))
        s.last_cycle_at  = d.get("last_cycle_at",  None)
        s.modules.update(d.get("modules", {}))
        s.pipeline_last_run.update(d.get("pipeline_last_run", {}))
        s.pipeline_runs.update(d.get("pipeline_runs", {}))
        s.pipeline_errors.update(d.get("pipeline_errors", {}))
        s.context.update(d.get("context", {}))
        return s


# ---------------------------------------------------------------------------
# Checkpoint metadata
# ---------------------------------------------------------------------------

@dataclass
class Checkpoint:
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    path:          str = ""
    created_at:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state_id:      str = ""
    cycle_count:   int = 0
    size_bytes:    int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "path":          self.path,
            "created_at":    self.created_at,
            "state_id":      self.state_id,
            "cycle_count":   self.cycle_count,
            "size_bytes":    self.size_bytes,
        }


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """
    Manages NEXUS runtime state: create, update, checkpoint, restore, rollback.

    Checkpoints are written as numbered JSON files in a rolling window.
    An index file tracks the available checkpoints.

    Usage:
        sm = StateManager(checkpoint_path="data/runtime/checkpoint.json")
        sm.restore_or_init()

        # Mutate state
        sm.state.cycle_count += 1
        sm.state.pipeline_last_run["financial"] = datetime.now(timezone.utc).isoformat()

        # Save checkpoint
        sm.save_checkpoint()

        # Rollback to previous checkpoint
        sm.rollback()
    """

    INDEX_FILENAME = "checkpoint_index.json"

    def __init__(
        self,
        checkpoint_path: str    = "data/runtime/checkpoint.json",
        max_checkpoints: int    = 5,
    ) -> None:
        self._lock           = threading.RLock()
        self._base_path      = checkpoint_path
        self._dir            = os.path.dirname(checkpoint_path) or "."
        self._max_cp         = max_checkpoints
        self._checkpoints:   List[Checkpoint] = []
        self._start_mono:    float = time.monotonic()
        self.state:          RuntimeState = RuntimeState()

    # ------------------------------------------------------------------
    # Init / restore
    # ------------------------------------------------------------------

    def restore_or_init(self, runtime_mode: str = "simulation") -> bool:
        """
        Try to restore state from the latest checkpoint.
        Returns True if restored, False if starting fresh.
        """
        self._load_index()
        if self._checkpoints:
            latest = self._checkpoints[-1]
            try:
                self._load_checkpoint_file(latest.path)
                self._start_mono = time.monotonic() - self.state.uptime_seconds
                return True
            except Exception:
                pass

        # Fresh start
        self.state = RuntimeState(runtime_mode=runtime_mode)
        self.state.started_at = datetime.now(timezone.utc).isoformat()
        return False

    # ------------------------------------------------------------------
    # Update helpers
    # ------------------------------------------------------------------

    def mark_module_ready(self, module_name: str) -> None:
        with self._lock:
            self.state.modules[module_name] = True

    def record_pipeline_run(self, pipeline_name: str, ok: bool) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self.state.pipeline_last_run[pipeline_name] = now
            self.state.pipeline_runs[pipeline_name] = (
                self.state.pipeline_runs.get(pipeline_name, 0) + 1
            )
            if not ok:
                self.state.pipeline_errors[pipeline_name] = (
                    self.state.pipeline_errors.get(pipeline_name, 0) + 1
                )

    def increment_cycle(self) -> int:
        with self._lock:
            self.state.cycle_count += 1
            self.state.last_cycle_at = datetime.now(timezone.utc).isoformat()
            self.state.uptime_seconds = time.monotonic() - self._start_mono
            return self.state.cycle_count

    def set_context(self, key: str, value: Any) -> None:
        with self._lock:
            self.state.context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.state.context.get(key, default)

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def save_checkpoint(self) -> Checkpoint:
        with self._lock:
            self.state.uptime_seconds = time.monotonic() - self._start_mono
            os.makedirs(self._dir, exist_ok=True)

            idx     = len(self._checkpoints) % self._max_cp
            cp_path = os.path.join(
                self._dir, f"checkpoint_{idx:02d}.json"
            )
            data    = self.state.to_dict()
            content = json.dumps(data, indent=2, default=str)

            with open(cp_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            cp = Checkpoint(
                path=cp_path,
                state_id=self.state.state_id,
                cycle_count=self.state.cycle_count,
                size_bytes=len(content.encode()),
            )
            self._checkpoints.append(cp)
            if len(self._checkpoints) > self._max_cp:
                self._checkpoints.pop(0)
            self._save_index()
        return cp

    def rollback(self) -> bool:
        """Restore state from the second-to-last checkpoint (undo last save)."""
        with self._lock:
            if len(self._checkpoints) < 2:
                return False
            target = self._checkpoints[-2]
            try:
                self._load_checkpoint_file(target.path)
                return True
            except Exception:
                return False

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [cp.to_dict() for cp in self._checkpoints]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def current_state_dict(self) -> Dict[str, Any]:
        with self._lock:
            self.state.uptime_seconds = time.monotonic() - self._start_mono
            return self.state.to_dict()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_checkpoint_file(self, path: str) -> None:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.state = RuntimeState.from_dict(data)

    def _save_index(self) -> None:
        index_path = os.path.join(self._dir, self.INDEX_FILENAME)
        with open(index_path, "w", encoding="utf-8") as fh:
            json.dump([cp.to_dict() for cp in self._checkpoints],
                      fh, indent=2, default=str)

    def _load_index(self) -> None:
        index_path = os.path.join(self._dir, self.INDEX_FILENAME)
        if not os.path.isfile(index_path):
            return
        try:
            with open(index_path, encoding="utf-8") as fh:
                items = json.load(fh)
            self._checkpoints = []
            for item in items:
                cp = Checkpoint(
                    checkpoint_id=item.get("checkpoint_id", str(uuid.uuid4())[:12]),
                    path=item.get("path", ""),
                    created_at=item.get("created_at", ""),
                    state_id=item.get("state_id", ""),
                    cycle_count=item.get("cycle_count", 0),
                    size_bytes=item.get("size_bytes", 0),
                )
                if os.path.isfile(cp.path):
                    self._checkpoints.append(cp)
        except (json.JSONDecodeError, OSError):
            self._checkpoints = []
