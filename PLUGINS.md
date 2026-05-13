# NEXUS Plugin System

## Overview

NEXUS supports a lightweight plugin system that allows extending functionality without modifying core code. Plugins are discovered automatically from `nexus/plugins/` and loaded at startup.

## Plugin Structure

Each plugin lives in its own subdirectory under `nexus/plugins/`:

```
nexus/plugins/
├── my_plugin/
│   ├── plugin.json   ← required: manifest
│   ├── plugin.py     ← required: code (entrypoint)
│   └── README.md     ← recommended: documentation
├── enabled.json      ← auto-managed: list of enabled plugins
├── loader.py         ← dynamic loader
└── cli.py            ← CLI interface
```

## plugin.json Manifest

```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "What this plugin does",
  "entrypoint": "plugin.py",
  "hooks": ["on_chat", "on_startup"]
}
```

**Required fields**: `name`, `version`, `description`, `entrypoint`

## Plugin Code

Minimal `plugin.py`:

```python
def register(api: object) -> None:
    """Called by the loader. Use api to hook into NEXUS."""
    print("My plugin loaded!")
```

With hooks:

```python
def register(api):
    if isinstance(api, dict) and "on_startup" in api:
        api["on_startup"](on_startup)

def on_startup():
    print("Plugin started!")

def on_chat(message: str) -> str | None:
    if "hello" in message:
        return "Hello from my plugin!"
    return None  # pass through
```

## Available Hooks

| Hook | Signature | Trigger |
|------|-----------|--------|
| `on_startup` | `() -> None` | NEXUS initialisation |
| `on_chat` | `(msg: str) -> str \| None` | Every chat message |

## CLI Commands

```bash
# List all plugins and their status
python -m nexus.plugins list
bash scripts/plugins.sh list

# Enable a plugin
python -m nexus.plugins enable my_plugin
bash scripts/plugins.sh enable my_plugin

# Disable a plugin
python -m nexus.plugins disable my_plugin
bash scripts/plugins.sh disable my_plugin

# Show plugin details
python -m nexus.plugins info my_plugin
bash scripts/plugins.sh info my_plugin
```

## Creating a New Plugin

1. Create a directory: `mkdir nexus/plugins/my_plugin`
2. Write `plugin.json` with the required fields
3. Write `plugin.py` with a `register(api)` function
4. Enable it: `python -m nexus.plugins enable my_plugin`
5. Restart NEXUS for the plugin to be loaded

## How Plugins Are Loaded

1. `loader.py` scans all subdirectories of `nexus/plugins/`
2. Each directory with a valid `plugin.json` is a candidate
3. Only plugins listed in `enabled.json` are imported
4. For each enabled plugin, `importlib` loads the entrypoint module
5. If the module exposes `register(api)`, it is called with the NEXUS API object
6. A plugin that crashes during load is skipped — it never brings down the system

## Best Practices

- Keep plugins self-contained (no cross-plugin imports)
- Handle all exceptions inside hooks — never let a plugin crash NEXUS
- Use `logging.getLogger("nexus.plugin.<name>")` for log output
- Keep `register()` fast (no blocking I/O)
- Document hooks in your `README.md`
- Pin dependencies in a `requirements.txt` inside your plugin directory

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Plugin not appearing in `list` | Check `plugin.json` has all required fields |
| Plugin not loading after enable | Check entrypoint path; look at nexus-core logs |
| `register()` not called | Ensure the function signature is `register(api)` |
| Import error in plugin | Test manually: `python nexus/plugins/my_plugin/plugin.py` |
