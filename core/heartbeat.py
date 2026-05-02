"""
NEXUS Core — Heartbeat
Periodic system health monitoring, diagnostics, and uptime tracking.
"""

import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HealthCheck:
    name: str
    fn: Callable[[], bool]
    critical: bool = False
    last_status: Optional[bool] = None
    last_checked: Optional[str] = None
    failure_count: int = 0


@dataclass
class HeartbeatSnapshot:
    timestamp: str
    uptime_seconds: float
    status: str               # "healthy" | "degraded" | "unhealthy"
    checks: Dict[str, Any]
    system_info: Dict[str, str]

    def is_healthy(self) -> bool:
        return self.status == "healthy"


# ---------------------------------------------------------------------------
# Heartbeat Monitor
# ---------------------------------------------------------------------------

class Heartbeat:
    """
    Runs registered health checks at a configurable interval.
    Exposes the last snapshot and notifies listeners on status changes.
    """

    def __init__(self, interval_seconds: float = 30.0) -> None:
        self._interval = interval_seconds
        self._checks: Dict[str, HealthCheck] = {}
        self._listeners: List[Callable[[HeartbeatSnapshot], None]] = []
        self._last_snapshot: Optional[HeartbeatSnapshot] = None
        self._started_at: Optional[float] = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the periodic heartbeat loop in a daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._started_at = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="nexus-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 2)

    def beat(self) -> HeartbeatSnapshot:
        """Run all checks immediately and return a fresh snapshot."""
        snapshot = self._run_checks()
        with self._lock:
            self._last_snapshot = snapshot
        self._notify(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_check(self, name: str, fn: Callable[[], bool], critical: bool = False) -> None:
        with self._lock:
            self._checks[name] = HealthCheck(name=name, fn=fn, critical=critical)

    def unregister_check(self, name: str) -> bool:
        with self._lock:
            return self._checks.pop(name, None) is not None

    def on_status_change(self, listener: Callable[[HeartbeatSnapshot], None]) -> None:
        """Register a callback invoked whenever the overall status changes."""
        self._listeners.append(listener)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def last_snapshot(self) -> Optional[HeartbeatSnapshot]:
        with self._lock:
            return self._last_snapshot

    @property
    def uptime_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def diagnostics(self) -> Dict[str, Any]:
        """Return a comprehensive diagnostics report."""
        snapshot = self.beat()
        return {
            "uptime_seconds": snapshot.uptime_seconds,
            "status": snapshot.status,
            "checks": snapshot.checks,
            "system": snapshot.system_info,
            "interval_seconds": self._interval,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.wait(timeout=self._interval):
            try:
                snapshot = self._run_checks()
                prev = self._last_snapshot
                with self._lock:
                    self._last_snapshot = snapshot
                if prev is None or prev.status != snapshot.status:
                    self._notify(snapshot)
            except Exception:
                pass  # heartbeat must never crash the process

    def _run_checks(self) -> HeartbeatSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        check_results: Dict[str, Any] = {}
        any_critical_failed = False
        any_failed = False

        with self._lock:
            checks_snapshot = list(self._checks.values())

        for check in checks_snapshot:
            try:
                ok = check.fn()
            except Exception as exc:
                ok = False
                check_results[check.name] = {"status": "error", "detail": str(exc)}
            else:
                check_results[check.name] = {"status": "ok" if ok else "fail"}

            check.last_status = ok
            check.last_checked = now
            if not ok:
                check.failure_count += 1
                any_failed = True
                if check.critical:
                    any_critical_failed = True
            else:
                check.failure_count = 0

        if any_critical_failed:
            overall = "unhealthy"
        elif any_failed:
            overall = "degraded"
        else:
            overall = "healthy"

        return HeartbeatSnapshot(
            timestamp=now,
            uptime_seconds=self.uptime_seconds,
            status=overall,
            checks=check_results,
            system_info=self._system_info(),
        )

    def _notify(self, snapshot: HeartbeatSnapshot) -> None:
        for listener in self._listeners:
            try:
                listener(snapshot)
            except Exception:
                pass

    @staticmethod
    def _system_info() -> Dict[str, str]:
        return {
            "python": platform.python_version(),
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "node": platform.node(),
        }
