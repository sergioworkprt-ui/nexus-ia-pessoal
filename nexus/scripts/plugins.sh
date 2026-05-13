#!/usr/bin/env bash
# NEXUS Plugin CLI bash wrapper
# Usage: bash scripts/plugins.sh <list|enable|disable|info> [name]
NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
cd "$NEXUS_HOME"
exec "$NEXUS_HOME/venv/bin/python" -m nexus.plugins "$@"
