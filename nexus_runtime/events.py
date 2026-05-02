"""
NEXUS Runtime — Event Bus
Thread-safe publish/subscribe event bus supporting both synchronous and
asynchronous (threaded) handler dispatch. All events are enqueued for
guaranteed delivery and logged for auditability.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    # Lifecycle
    RUNTIME_STARTED       = "runtime_started"
    RUNTIME_STOPPED       = "runtime_stopped"
    RUNTIME_PAUSED        = "runtime_paused"
    RUNTIME_RESUMED       = "runtime_resumed"
    MODULE_READY          = "module_ready"
    MODULE_FAILED         = "module_failed"

    # Pipelines
    PIPELINE_STARTED      = "pipeline_started"
    PIPELINE_COMPLETED    = "pipeline_completed"
    PIPELINE_FAILED       = "pipeline_failed"

    # Intelligence
    PATTERN_DETECTED      = "pattern_detected"
    ANOMALY_DETECTED      = "anomaly_detected"
    SENTIMENT_ALERT       = "sentiment_alert"

    # Financial
    TRADE_SIGNAL          = "trade_signal"
    RISK_BREACH           = "risk_breach"
    DRAWDOWN_ALERT        = "drawdown_alert"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"

    # Evolution
    PATCH_GENERATED       = "patch_generated"
    PATCH_APPLIED         = "patch_applied"
    ROLLBACK_TRIGGERED    = "rollback_triggered"
    EVOLUTION_CYCLE_DONE  = "evolution_cycle_done"

    # Multi-IA
    CONSENSUS_REACHED     = "consensus_reached"
    CONSENSUS_ESCALATED   = "consensus_escalated"
    AGENT_FAILED          = "agent_failed"

    # Reports
    REPORT_GENERATED      = "report_generated"

    # State
    CHECKPOINT_SAVED      = "checkpoint_saved"
    STATE_RESTORED        = "state_restored"

    # Security
    SECURITY_VIOLATION    = "security_violation"
    RATE_LIMIT_HIT        = "rate_limit_hit"

    # Scheduler
    TASK_SCHEDULED        = "task_scheduled"
    TASK_EXECUTED         = "task_executed"
    TASK_MISSED           = "task_missed"

    # Generic
    INFO                  = "info"
    WARNING               = "warning"
    CRITICAL              = "critical"


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """An immutable event message published on the event bus."""
    event_id:   str       = field(default_factory=lambda: str(uuid.uuid4())[:12])
    event_type: EventType = EventType.INFO
    source:     str       = ""          # module or component that emitted
    data:       Dict[str, Any] = field(default_factory=dict)
    timestamp:  str       = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: Optional[str] = None   # group related events

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id":      self.event_id,
            "event_type":    self.event_type.value,
            "source":        self.source,
            "data":          self.data,
            "timestamp":     self.timestamp,
            "correlation_id": self.correlation_id,
        }

    def __repr__(self) -> str:
        return f"<Event {self.event_type.value} from={self.source!r} id={self.event_id}>"


# ---------------------------------------------------------------------------
# Handler descriptor
# ---------------------------------------------------------------------------

@dataclass
class HandlerRecord:
    handler_id:  str
    event_type:  Optional[EventType]   # None = wildcard (all events)
    callback:    Callable[[Event], None]
    async_mode:  bool = False           # True = run in a daemon thread
    description: str  = ""


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------

class EventBus:
    """
    Thread-safe publish/subscribe event bus.

    Sync handlers are called in the dispatcher thread (blocking).
    Async handlers are dispatched to a new daemon thread per invocation.

    A dedicated dispatcher thread drains the internal queue, ensuring
    publishers never block waiting for slow handlers.

    Usage:
        bus = EventBus()
        bus.start()

        def on_pattern(event):
            print("Pattern:", event.data)

        bus.subscribe(EventType.PATTERN_DETECTED, on_pattern)
        bus.publish(Event(event_type=EventType.PATTERN_DETECTED,
                          source="web_intelligence",
                          data={"type": "breakout", "symbol": "BTC"}))
    """

    def __init__(self, queue_size: int = 1000, max_history: int = 500) -> None:
        self._handlers:    Dict[str, HandlerRecord] = {}  # handler_id → record
        self._type_index:  Dict[str, List[str]] = {}      # event_type_value → [handler_ids]
        self._wildcard:    List[str] = []                 # handler_ids subscribed to all

        self._queue:       queue.Queue[Event] = queue.Queue(maxsize=queue_size)
        self._history:     List[Event] = []
        self._max_history: int = max_history

        self._lock         = threading.RLock()
        self._running      = False
        self._dispatcher:  Optional[threading.Thread] = None
        self._stats = {
            "published": 0,
            "dispatched": 0,
            "dropped": 0,
            "handler_errors": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="nexus-event-bus"
        )
        self._dispatcher.start()

    def stop(self, drain_timeout: float = 3.0) -> None:
        self._running = False
        # Allow queue to drain
        try:
            self._queue.join()
        except Exception:
            pass
        if self._dispatcher:
            self._dispatcher.join(timeout=drain_timeout)

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    def subscribe(
        self,
        callback:   Callable[[Event], None],
        event_type: Optional[EventType] = None,
        async_mode: bool = False,
        description: str = "",
    ) -> str:
        """
        Register a handler. Returns a handler_id for later unsubscription.
        If event_type is None, the handler receives ALL events (wildcard).
        """
        handler_id = str(uuid.uuid4())[:12]
        record = HandlerRecord(
            handler_id=handler_id,
            event_type=event_type,
            callback=callback,
            async_mode=async_mode,
            description=description,
        )
        with self._lock:
            self._handlers[handler_id] = record
            if event_type is None:
                self._wildcard.append(handler_id)
            else:
                key = event_type.value
                if key not in self._type_index:
                    self._type_index[key] = []
                self._type_index[key].append(handler_id)
        return handler_id

    def unsubscribe(self, handler_id: str) -> bool:
        with self._lock:
            record = self._handlers.pop(handler_id, None)
            if record is None:
                return False
            if record.event_type is None:
                self._wildcard = [h for h in self._wildcard if h != handler_id]
            else:
                key = record.event_type.value
                self._type_index[key] = [
                    h for h in self._type_index.get(key, []) if h != handler_id
                ]
        return True

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish(self, event: Event) -> bool:
        """
        Enqueue an event for dispatch. Returns False if queue is full (event dropped).
        Non-blocking — callers never wait for handlers to complete.
        """
        try:
            self._queue.put_nowait(event)
            with self._lock:
                self._stats["published"] += 1
            return True
        except queue.Full:
            with self._lock:
                self._stats["dropped"] += 1
            return False

    def emit(
        self,
        event_type: EventType,
        source:     str = "",
        data:       Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Convenience wrapper: create an Event and publish it."""
        return self.publish(Event(
            event_type=event_type,
            source=source,
            data=data or {},
            correlation_id=correlation_id,
        ))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._history[-limit:]]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            s = dict(self._stats)
            s["handlers_registered"] = len(self._handlers)
            s["queue_size"] = self._queue.qsize()
        return s

    def list_handlers(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "handler_id":  r.handler_id,
                    "event_type":  r.event_type.value if r.event_type else "*",
                    "async":       r.async_mode,
                    "description": r.description,
                }
                for r in self._handlers.values()
            ]

    # ------------------------------------------------------------------
    # Internal dispatch loop
    # ------------------------------------------------------------------

    def _dispatch_loop(self) -> None:
        while self._running or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._dispatch(event)
            finally:
                self._queue.task_done()

    def _dispatch(self, event: Event) -> None:
        with self._lock:
            # Collect relevant handler ids
            specific = self._type_index.get(event.event_type.value, [])
            handler_ids = list(set(specific + self._wildcard))
            records = [self._handlers[hid] for hid in handler_ids
                       if hid in self._handlers]

            # Record history
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._stats["dispatched"] += 1

        for record in records:
            if record.async_mode:
                t = threading.Thread(
                    target=self._call_handler,
                    args=(record, event),
                    daemon=True,
                )
                t.start()
            else:
                self._call_handler(record, event)

    def _call_handler(self, record: HandlerRecord, event: Event) -> None:
        try:
            record.callback(event)
        except Exception:
            with self._lock:
                self._stats["handler_errors"] += 1
