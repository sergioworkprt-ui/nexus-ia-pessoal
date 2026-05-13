"""Structured JSON logger for NEXUS — JSON formatter + HTTP middleware."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable


class JSONFormatter(logging.Formatter):
    """Formats every log record as a single-line JSON object."""

    # Fields injected via LogRecord.extra that we want to surface at top level
    _EXTRA_KEYS = ("method", "path", "status", "duration_ms", "client",
                   "module", "action", "ip", "event")

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in self._EXTRA_KEYS:
            if hasattr(record, key):
                doc[key] = getattr(record, key)
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)
        return json.dumps(doc, ensure_ascii=False)


def configure_structured_logging(log_file: str | None = None) -> None:
    """Replace all root logger handler formatters with JSONFormatter.

    Call once at application startup before any log output.
    """
    formatter = JSONFormatter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.setFormatter(formatter)
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)


async def http_logging_middleware(request: Any, call_next: Callable, record_fn: Callable | None = None) -> Any:
    """Async middleware function that logs every HTTP request as structured JSON.

    Usage in main.py:
        @app.middleware("http")
        async def _log_mw(request, call_next):
            return await http_logging_middleware(request, call_next, record_fn=record_request)
    """
    log = logging.getLogger("nexus.http")
    start = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    except Exception:
        raise
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        duration_s = duration_ms / 1000
        log.info(
            "%s %s %s",
            request.method,
            request.url.path,
            status,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": duration_ms,
                "client": request.client.host if request.client else "unknown",
            },
        )
        if record_fn:
            try:
                record_fn(request.method, request.url.path, status, duration_s)
            except Exception:
                pass
