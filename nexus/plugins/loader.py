"""Dynamic plugin loader for NEXUS."""
from __future__ import annotations
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("nexus.plugins")

PLUGINS_DIR = Path(__file__).parent
ENABLED_FILE = PLUGINS_DIR / "enabled.json"
REQUIRED_FIELDS = {"name", "version", "description", "entrypoint"}


def _load_enabled() -> set[str]:
    if ENABLED_FILE.exists():
        try:
            return set(json.loads(ENABLED_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_enabled(names: set[str]) -> None:
    ENABLED_FILE.write_text(json.dumps(sorted(names), indent=2))


def discover() -> list[dict]:
    """Return metadata dicts for all valid plugins (enabled and disabled)."""
    plugins: list[dict] = []
    enabled = _load_enabled()
    for path in sorted(PLUGINS_DIR.iterdir()):
        if not path.is_dir():
            continue
        manifest_file = path / "plugin.json"
        if not manifest_file.exists():
            continue
        try:
            manifest: dict = json.loads(manifest_file.read_text())
        except Exception as exc:
            log.warning("Plugin %s: invalid plugin.json (%s)", path.name, exc)
            continue
        missing = REQUIRED_FIELDS - set(manifest)
        if missing:
            log.warning("Plugin %s: missing fields %s", path.name, missing)
            continue
        manifest["_path"] = str(path)
        manifest["_enabled"] = manifest["name"] in enabled
        plugins.append(manifest)
    return plugins


def enable(name: str) -> bool:
    """Enable a plugin by name. Returns True if the plugin was found."""
    for p in discover():
        if p["name"] == name:
            enabled = _load_enabled()
            enabled.add(name)
            _save_enabled(enabled)
            log.info("Plugin '%s' enabled", name)
            return True
    return False


def disable(name: str) -> bool:
    """Disable a plugin by name. Returns True if it was enabled."""
    enabled = _load_enabled()
    if name in enabled:
        enabled.discard(name)
        _save_enabled(enabled)
        log.info("Plugin '%s' disabled", name)
        return True
    return False


def load_all(api: Any = None) -> list[str]:
    """Import and register all enabled plugins. Returns list of successfully loaded names."""
    loaded: list[str] = []
    enabled = _load_enabled()
    for plugin in discover():
        if plugin["name"] not in enabled:
            continue
        plugin_dir = Path(plugin["_path"])
        entrypoint = plugin_dir / plugin["entrypoint"]
        if not entrypoint.exists():
            log.warning("Plugin '%s': entrypoint '%s' not found", plugin["name"], entrypoint)
            continue
        try:
            module_name = f"nexus_plugin_{plugin['name']}"
            spec = importlib.util.spec_from_file_location(module_name, entrypoint)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            if hasattr(mod, "register"):
                mod.register(api or {})
            loaded.append(plugin["name"])
            log.info("Plugin '%s' v%s loaded", plugin["name"], plugin.get("version", "?"))
        except Exception as exc:
            # Plugin load failure must never crash the main system
            log.error("Plugin '%s' failed to load: %s", plugin["name"], exc)
    return loaded


class PluginLoader:
    """Convenience wrapper around the plugin loader module-level functions."""

    def __init__(self, api: Any = None) -> None:
        self.api = api
        self._loaded: list[str] = []

    def load(self) -> list[str]:
        """Load all enabled plugins and return their names."""
        self._loaded = load_all(self.api)
        return self._loaded

    @property
    def loaded(self) -> list[str]:
        return self._loaded

    @staticmethod
    def discover() -> list[dict]:
        return discover()

    @staticmethod
    def enable(name: str) -> bool:
        return enable(name)

    @staticmethod
    def disable(name: str) -> bool:
        return disable(name)
