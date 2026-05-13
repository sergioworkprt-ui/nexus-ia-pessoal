# Example Plugin

Demonstrates the NEXUS plugin API with two hooks: `on_startup` and `on_chat`.

## Hooks

| Hook | Signature | Description |
|------|-----------|-------------|
| `on_startup` | `() -> None` | Called once when NEXUS initialises |
| `on_chat` | `(message: str) -> str \| None` | Called per chat message; return `str` to intercept |

## Enable this plugin

```bash
# Via CLI
python -m nexus.plugins enable example

# Via bash wrapper
bash scripts/plugins.sh enable example
```

## Verify

```bash
python -m nexus.plugins list
# example   1.0.0   ✔ yes   Example plugin demonstrating the NEXUS plugin API
```
