"""
NEXUS Core — Task Manager
Priority task queue with synchronous and asynchronous execution support.
"""

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from queue import PriorityQueue
from typing import Any, Callable, Dict, List, Optional


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatus(str):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(order=True)
class Task:
    priority: Priority
    created_at: str = field(compare=False, default_factory=lambda: datetime.now(timezone.utc).isoformat())
    task_id: str = field(compare=False, default_factory=lambda: str(uuid.uuid4()))
    name: str = field(compare=False, default="unnamed")
    fn: Optional[Callable[..., Any]] = field(compare=False, default=None)
    args: tuple = field(compare=False, default_factory=tuple)
    kwargs: Dict[str, Any] = field(compare=False, default_factory=dict)
    status: str = field(compare=False, default=TaskStatus.PENDING)
    result: Optional[Any] = field(compare=False, default=None)
    error: Optional[str] = field(compare=False, default=None)
    started_at: Optional[str] = field(compare=False, default=None)
    finished_at: Optional[str] = field(compare=False, default=None)

    def run(self) -> Any:
        if self.fn is None:
            raise ValueError(f"Task '{self.name}' has no callable attached.")
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()
        try:
            self.result = self.fn(*self.args, **self.kwargs)
            self.status = TaskStatus.DONE
        except Exception as exc:
            self.error = traceback.format_exc()
            self.status = TaskStatus.FAILED
            raise exc
        finally:
            self.finished_at = datetime.now(timezone.utc).isoformat()
        return self.result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "priority": self.priority.name,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class TaskManager:
    """
    Thread-safe task queue with a configurable worker pool.
    Supports synchronous submission (blocking) and fire-and-forget execution.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._queue: PriorityQueue[Task] = PriorityQueue()
        self._history: List[Task] = []
        self._history_lock = threading.Lock()
        self._max_workers = max_workers
        self._active_workers = 0
        self._worker_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._workers: List[threading.Thread] = []
        self._start_workers()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        fn: Callable[..., Any],
        name: str = "task",
        priority: Priority = Priority.NORMAL,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Enqueue a task and return the Task object immediately."""
        task = Task(
            priority=priority,
            name=name,
            fn=fn,
            args=args,
            kwargs=kwargs or {},
        )
        self._queue.put(task)
        return task

    def submit_sync(
        self,
        fn: Callable[..., Any],
        name: str = "task",
        priority: Priority = Priority.NORMAL,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = 30.0,
    ) -> Any:
        """Submit a task and block until it completes, then return its result."""
        done_event = threading.Event()
        result_holder: Dict[str, Any] = {}

        def wrapped() -> Any:
            result_holder["value"] = fn(*args, **(kwargs or {}))
            done_event.set()
            return result_holder["value"]

        task = self.submit(wrapped, name=name, priority=priority)
        if not done_event.wait(timeout=timeout):
            task.status = TaskStatus.CANCELLED
            raise TimeoutError(f"Task '{name}' timed out after {timeout}s.")
        if task.status == TaskStatus.FAILED:
            raise RuntimeError(f"Task '{name}' failed: {task.error}")
        return result_holder.get("value")

    def cancel(self, task_id: str) -> bool:
        """Mark a pending task as cancelled (best-effort — already running tasks are unaffected)."""
        with self._history_lock:
            for task in self._history:
                if task.task_id == task_id and task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    return True
        return False

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._history_lock:
            return [t.to_dict() for t in self._history[-limit:]]

    def stats(self) -> Dict[str, Any]:
        with self._history_lock:
            statuses = [t.status for t in self._history]
        return {
            "queued": self._queue.qsize(),
            "active_workers": self._active_workers,
            "max_workers": self._max_workers,
            "total_tasks": len(statuses),
            "done": statuses.count(TaskStatus.DONE),
            "failed": statuses.count(TaskStatus.FAILED),
            "cancelled": statuses.count(TaskStatus.CANCELLED),
        }

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully stop all worker threads."""
        self._shutdown.set()
        if wait:
            for w in self._workers:
                w.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal worker loop
    # ------------------------------------------------------------------

    def _start_workers(self) -> None:
        for _ in range(self._max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                task = self._queue.get(timeout=1.0)
            except Exception:
                continue

            if task.status == TaskStatus.CANCELLED:
                self._queue.task_done()
                continue

            with self._worker_lock:
                self._active_workers += 1
            try:
                task.run()
            except Exception:
                pass  # error already captured in task.error
            finally:
                with self._history_lock:
                    self._history.append(task)
                with self._worker_lock:
                    self._active_workers -= 1
                self._queue.task_done()
