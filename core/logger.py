"""
NEXUS Core — Logger
Internal logging and audit trail for all system components.
"""

import logging
import json
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    AUDIT = "AUDIT"


class NexusLogger:
    """
    Centralised logger for the NEXUS system.

    Emits structured JSON entries to a rotating log file and to stdout.
    Thread-safe. All public methods are safe to call from any module.
    """

    _instance: Optional["NexusLogger"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "NexusLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        log_dir: str = "logs",
        log_file: str = "nexus.log",
        level: LogLevel = LogLevel.INFO,
        enable_console: bool = True,
    ) -> None:
        if getattr(self, "_initialised", False):
            return

        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / log_file
        self._audit_path = self._log_dir / "audit.log"
        self._level = level
        self._enable_console = enable_console
        self._write_lock = threading.Lock()

        self._stdlib_logger = self._build_stdlib_logger(level, enable_console)
        self._initialised = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def debug(self, module: str, message: str, **extra: Any) -> None:
        self._emit(LogLevel.DEBUG, module, message, **extra)

    def info(self, module: str, message: str, **extra: Any) -> None:
        self._emit(LogLevel.INFO, module, message, **extra)

    def warning(self, module: str, message: str, **extra: Any) -> None:
        self._emit(LogLevel.WARNING, module, message, **extra)

    def error(self, module: str, message: str, **extra: Any) -> None:
        self._emit(LogLevel.ERROR, module, message, **extra)

    def critical(self, module: str, message: str, **extra: Any) -> None:
        self._emit(LogLevel.CRITICAL, module, message, **extra)

    def audit(self, actor: str, action: str, target: str, outcome: str, **extra: Any) -> None:
        """Write an immutable audit entry (separate audit.log file)."""
        entry = self._build_entry(
            LogLevel.AUDIT,
            module="audit",
            message=f"{actor} → {action} on {target}: {outcome}",
            actor=actor,
            action=action,
            target=target,
            outcome=outcome,
            **extra,
        )
        with self._write_lock:
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        if self._enable_console:
            self._stdlib_logger.info("[AUDIT] %s", entry["message"])

    def set_level(self, level: LogLevel) -> None:
        self._level = level
        self._stdlib_logger.setLevel(level.value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, level: LogLevel, module: str, message: str, **extra: Any) -> None:
        if not self._should_log(level):
            return
        entry = self._build_entry(level, module, message, **extra)
        with self._write_lock:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        getattr(self._stdlib_logger, level.value.lower(), self._stdlib_logger.info)(
            "[%s] %s", module.upper(), message
        )

    def _should_log(self, level: LogLevel) -> bool:
        order = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]
        try:
            return order.index(level) >= order.index(self._level)
        except ValueError:
            return True

    @staticmethod
    def _build_entry(level: LogLevel, module: str, message: str, **extra: Any) -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level.value,
            "module": module,
            "message": message,
            **extra,
        }

    @staticmethod
    def _build_stdlib_logger(level: LogLevel, enable_console: bool) -> logging.Logger:
        logger = logging.getLogger("nexus")
        logger.setLevel(level.value)
        if enable_console and not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
            )
            logger.addHandler(handler)
        return logger


# Module-level singleton accessor
def get_logger() -> NexusLogger:
    """Return the shared NexusLogger singleton."""
    return NexusLogger()
