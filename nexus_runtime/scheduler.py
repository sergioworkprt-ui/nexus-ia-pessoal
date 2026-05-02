"""
NEXUS Runtime — Scheduler
Cron-like task scheduler supporting recurring and one-shot tasks.
All tasks run in daemon threads; the scheduler itself is a background thread.
Thread-safe. No external dependencies.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"   # one-shot: ran once
    FAILED    = "failed"
    CANCELLED = "cancelled"
    RECURRING = "recurring"   # still active, ran at least once


@dataclass
class TaskResult:
    task_id:    str
    task_name:  str
    started_at: str
    finished_at: str
    ok:         bool
    error:      Optional[str] = None
    duration_s: float = 0.0


@dataclass
class ScheduledTask:
    """A task registered with the Scheduler."""
    task_id:          str
    name:             str
    callback:         Callable[[], Any]
    interval_seconds: float              # 0 = one-shot
    next_run_at:      float              # time.monotonic() deadline
    is_recurring:     bool = True
    status:           TaskStatus = TaskStatus.PENDING
    run_count:        int = 0
    last_result:      Optional[TaskResult] = None
    description:      str = ""
    tags:             List[str] = field(default_factory=list)

    @property
    def is_one_shot(self) -> bool:
        return not self.is_recurring

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id":          self.task_id,
            "name":             self.name,
            "interval_seconds": self.interval_seconds,
            "is_recurring":     self.is_recurring,
            "status":           self.status.value,
            "run_count":        self.run_count,
            "next_run_in_s":    max(0.0, round(self.next_run_at - time.monotonic(), 1)),
            "description":      self.description,
            "tags":             self.tags,
        }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Background scheduler that fires tasks at configured intervals.

    - `schedule()`: register a recurring task (fires every interval_seconds)
    - `schedule_once()`: register a one-shot task (fires after delay_seconds)
    - `cancel()`: remove a task by name or task_id
    - Tasks run in isolated daemon threads — slow tasks don't block others
    - A missed-task threshold alerts when a task runs late

    Usage:
        sched = Scheduler(tick_interval=1.0)
        sched.start()
        sched.schedule("heartbeat", lambda: print("tick"), interval_seconds=5)
        sched.schedule_once("startup_check", check_fn, delay_seconds=0)
    """

    MISSED_THRESHOLD_S = 10.0   # warn if task is this many seconds overdue

    def __init__(
        self,
        tick_interval:   float = 1.0,
        max_concurrent:  int   = 8,
        on_task_done:    Optional[Callable[[TaskResult], None]] = None,
        on_task_missed:  Optional[Callable[[ScheduledTask], None]] = None,
    ) -> None:
        self._tick        = tick_interval
        self._max_conc    = max_concurrent
        self._on_done     = on_task_done
        self._on_missed   = on_task_missed
        self._tasks:      Dict[str, ScheduledTask] = {}
        self._lock        = threading.RLock()
        self._running     = False
        self._thread:     Optional[threading.Thread] = None
        self._semaphore   = threading.Semaphore(max_concurrent)
        self._history:    List[TaskResult] = []
        self._stats = {"executed": 0, "failed": 0, "missed": 0, "cancelled": 0}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="nexus-scheduler"
        )
        self._thread.start()

    def stop(self, wait: float = 3.0) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=wait)

    # ------------------------------------------------------------------
    # Task registration
    # ------------------------------------------------------------------

    def schedule(
        self,
        name:             str,
        callback:         Callable[[], Any],
        interval_seconds: float,
        run_immediately:  bool = False,
        description:      str  = "",
        tags:             Optional[List[str]] = None,
    ) -> str:
        """Register a recurring task. Returns task_id."""
        task_id   = str(uuid.uuid4())[:12]
        delay     = 0.0 if run_immediately else interval_seconds
        next_run  = time.monotonic() + delay
        task = ScheduledTask(
            task_id=task_id,
            name=name,
            callback=callback,
            interval_seconds=interval_seconds,
            next_run_at=next_run,
            is_recurring=True,
            description=description,
            tags=tags or [],
        )
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def schedule_once(
        self,
        name:          str,
        callback:      Callable[[], Any],
        delay_seconds: float = 0.0,
        description:   str   = "",
        tags:          Optional[List[str]] = None,
    ) -> str:
        """Register a one-shot task. Returns task_id."""
        task_id  = str(uuid.uuid4())[:12]
        next_run = time.monotonic() + delay_seconds
        task = ScheduledTask(
            task_id=task_id,
            name=name,
            callback=callback,
            interval_seconds=0,
            next_run_at=next_run,
            is_recurring=False,
            description=description,
            tags=tags or [],
        )
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def cancel(self, identifier: str) -> bool:
        """Cancel by task_id or name. Returns True if found and cancelled."""
        with self._lock:
            # Try by task_id first
            if identifier in self._tasks:
                self._tasks[identifier].status = TaskStatus.CANCELLED
                del self._tasks[identifier]
                self._stats["cancelled"] += 1
                return True
            # Try by name
            for tid, task in list(self._tasks.items()):
                if task.name == identifier:
                    task.status = TaskStatus.CANCELLED
                    del self._tasks[tid]
                    self._stats["cancelled"] += 1
                    return True
        return False

    def reschedule(self, identifier: str, interval_seconds: float) -> bool:
        """Change the interval of an existing recurring task."""
        with self._lock:
            task = self._tasks.get(identifier)
            if task is None:
                for t in self._tasks.values():
                    if t.name == identifier:
                        task = t
                        break
            if task is None:
                return False
            task.interval_seconds = interval_seconds
            task.next_run_at = time.monotonic() + interval_seconds
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    def get_task(self, identifier: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(identifier)
            if task is None:
                for t in self._tasks.values():
                    if t.name == identifier:
                        task = t
                        break
            return task.to_dict() if task else None

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "task_id":    r.task_id,
                    "name":       r.task_name,
                    "ok":         r.ok,
                    "duration_s": round(r.duration_s, 3),
                    "started_at": r.started_at,
                    "error":      r.error,
                }
                for r in self._history[-limit:]
            ]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            s = dict(self._stats)
            s["active_tasks"] = len(self._tasks)
        return s

    # ------------------------------------------------------------------
    # Scheduler loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            now = time.monotonic()
            due: List[ScheduledTask] = []

            with self._lock:
                for task in list(self._tasks.values()):
                    if task.status == TaskStatus.RUNNING:
                        continue
                    if task.next_run_at <= now:
                        due.append(task)
                        task.status = TaskStatus.RUNNING

            for task in due:
                overdue = now - task.next_run_at
                if overdue > self.MISSED_THRESHOLD_S and self._on_missed:
                    try:
                        self._on_missed(task)
                    except Exception:
                        pass
                    with self._lock:
                        self._stats["missed"] += 1

                t = threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"nexus-task-{task.name}",
                )
                t.start()

            time.sleep(self._tick)

    def _run_task(self, task: ScheduledTask) -> None:
        self._semaphore.acquire()
        started = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        ok    = True
        error = None

        try:
            task.callback()
        except Exception as exc:
            ok    = False
            error = str(exc)
        finally:
            duration = time.perf_counter() - t0
            finished = datetime.now(timezone.utc).isoformat()
            self._semaphore.release()

        result = TaskResult(
            task_id=task.task_id,
            task_name=task.name,
            started_at=started,
            finished_at=finished,
            ok=ok,
            error=error,
            duration_s=duration,
        )

        with self._lock:
            task.run_count  += 1
            task.last_result = result
            if ok:
                task.status = TaskStatus.RECURRING if task.is_recurring else TaskStatus.COMPLETED
                self._stats["executed"] += 1
            else:
                task.status = TaskStatus.FAILED if task.is_one_shot else TaskStatus.RECURRING
                self._stats["failed"] += 1

            if task.is_recurring:
                task.next_run_at = time.monotonic() + task.interval_seconds
                if task.status == TaskStatus.FAILED:
                    task.status = TaskStatus.RECURRING   # keep alive even on error
            else:
                # One-shot completed — remove from active tasks
                self._tasks.pop(task.task_id, None)

            self._history.append(result)
            if len(self._history) > 200:
                self._history.pop(0)

        if self._on_done:
            try:
                self._on_done(result)
            except Exception:
                pass
