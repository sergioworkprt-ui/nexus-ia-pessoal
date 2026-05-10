"""NEXUS logger — safe for systemd, stdout fallback, absolute paths.

Design rules:
- Never raises: if the log file can't be opened, falls back to stdout only.
- Absolute default path /var/log/nexus (never a relative path).
- Sets file permissions explicitly after creation (0o664) so the nexus
  user can always write, regardless of umask or previous root runs.
- StreamHandler is always present — systemd/journald captures stdout.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import stat
import sys

# The single source of truth for the log directory.
# Override with LOG_DIR env var (must be an absolute path).
_LOG_DIR: str | None = None
_LOG_LEVEL: int | None = None

_FMT = logging.Formatter(
    "%(asctime)s [%(name)-20s] %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _resolve_log_dir() -> str:
    """Return an absolute log directory, guaranteed to exist and be writable."""
    global _LOG_DIR
    if _LOG_DIR is not None:
        return _LOG_DIR

    raw = os.getenv("LOG_DIR", "/var/log/nexus")
    # Reject relative paths — convert to absolute using a safe base.
    if not os.path.isabs(raw):
        raw = os.path.join("/var/log/nexus", raw.lstrip("./"))

    try:
        os.makedirs(raw, mode=0o775, exist_ok=True)
    except OSError:
        # Fallback: try /tmp/nexus-logs (always writable)
        raw = "/tmp/nexus-logs"
        os.makedirs(raw, mode=0o775, exist_ok=True)

    _LOG_DIR = raw
    return _LOG_DIR


def _resolve_level() -> int:
    global _LOG_LEVEL
    if _LOG_LEVEL is not None:
        return _LOG_LEVEL
    raw = os.getenv("LOG_LEVEL", "INFO").upper()
    _LOG_LEVEL = getattr(logging, raw, logging.INFO)
    return _LOG_LEVEL


def _make_file_handler(log_dir: str, name: str) -> logging.Handler | None:
    """Build a RotatingFileHandler, returning None on any failure."""
    log_path = os.path.join(log_dir, f"{name}.log")
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            delay=False,
            encoding="utf-8",
        )
        # Explicitly set permissions so nexus user can always write,
        # even if a previous root run created the file with 0o600.
        try:
            os.chmod(log_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
        except OSError:
            pass  # best-effort
        handler.setFormatter(_FMT)
        return handler
    except (OSError, PermissionError) as exc:
        # Do not crash — caller will use stdout only.
        print(
            f"[NEXUS logger] WARNING: cannot write to {log_path}: {exc}. "
            "Using stdout only.",
            file=sys.stderr,
        )
        return None


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name.

    Safe to call at import time or inside functions. Idempotent.
    """
    logger = logging.getLogger(f"nexus.{name}")
    if logger.handlers:
        return logger

    level = _resolve_level()
    logger.setLevel(level)
    logger.propagate = False  # don't double-log via root logger

    # 1. Stdout handler — always present (journald captures this)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(_FMT)
    logger.addHandler(ch)

    # 2. File handler — optional, degraded gracefully on failure
    log_dir = _resolve_log_dir()
    fh = _make_file_handler(log_dir, name)
    if fh is not None:
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)

    return logger
