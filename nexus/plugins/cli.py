#!/usr/bin/env python3
"""NEXUS Plugin CLI.

Usage:
    python -m nexus.plugins list
    python -m nexus.plugins enable <name>
    python -m nexus.plugins disable <name>
    python -m nexus.plugins info <name>
"""
from __future__ import annotations
import sys
from nexus.plugins.loader import discover, enable, disable


def _check_name(args: list[str]) -> str:
    if len(args) < 2:
        print(f"Usage: {args[0]} <plugin-name>", file=sys.stderr)
        sys.exit(1)
    return args[1]


def cmd_list() -> None:
    plugins = discover()
    if not plugins:
        print("No plugins found in nexus/plugins/")
        return
    print(f"{'Name':<22} {'Version':<10} {'Enabled':<10} Description")
    print("-" * 72)
    for p in plugins:
        status = "✔ yes" if p["_enabled"] else "  no"
        desc = p.get("description", "")[:38]
        print(f"{p['name']:<22} {p['version']:<10} {status:<10} {desc}")


def cmd_enable(name: str) -> None:
    if enable(name):
        print(f"Plugin '{name}' enabled.")
    else:
        print(f"Plugin '{name}' not found.", file=sys.stderr)
        sys.exit(1)


def cmd_disable(name: str) -> None:
    if disable(name):
        print(f"Plugin '{name}' disabled.")
    else:
        print(f"Plugin '{name}' not found or already disabled.")


def cmd_info(name: str) -> None:
    for p in discover():
        if p["name"] == name:
            print(f"Plugin: {p['name']}")
            for k, v in p.items():
                if not k.startswith("_"):
                    print(f"  {k}: {v}")
            print(f"  enabled: {p['_enabled']}")
            print(f"  path:    {p['_path']}")
            return
    print(f"Plugin '{name}' not found.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "enable":
        cmd_enable(_check_name(args))
    elif cmd == "disable":
        cmd_disable(_check_name(args))
    elif cmd == "info":
        cmd_info(_check_name(args))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Commands: list, enable, disable, info", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
