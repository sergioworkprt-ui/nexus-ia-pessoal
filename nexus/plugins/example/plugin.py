"""Example NEXUS plugin — demonstrates plugin registration and hooks."""
from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger("nexus.plugin.example")

_api: Any = None


def register(api: Any) -> None:
    """Called by the plugin loader when this plugin is loaded."""
    global _api
    _api = api
    log.info("Example plugin registered")
    if isinstance(api, dict) and "on_startup" in api:
        api["on_startup"](on_startup)


def on_startup() -> None:
    """Hook: called when NEXUS starts."""
    log.info("Example plugin: startup hook called")


def on_chat(message: str) -> str | None:
    """Hook: called for every chat message.

    Return a non-None string to inject a response; return None to pass through.
    """
    if "example" in message.lower() or "plugin" in message.lower():
        return "👋 Example plugin is active and intercepted your message!"
    return None
