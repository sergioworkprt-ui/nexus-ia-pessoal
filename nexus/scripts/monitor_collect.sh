#!/usr/bin/env bash
# Collects system/service metrics, outputs JSON, saves JSONL history (max 50 entries)
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
MONITOR_DIR="$NEXUS_HOME/monitor"
HISTORY_FILE="$MONITOR_DIR/history.jsonl"
CURRENT_FILE="$MONITOR_DIR/current.json"
MAX_ENTRIES=50

mkdir -p "$MONITOR_DIR"

# ── Service status ─────────────────────────────────────────────────
svc_status() {
    local svc="$1"
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo "active"
    else
        echo "inactive"
    fi
}

# ── Port check ───────────────────────────────────────────────────
port_open() {
    local port="$1"
    if ss -tulpn 2>/dev/null | grep -q ":${port} "; then
        echo "true"
    else
        echo "false"
    fi
}

# ── Collect data ───────────────────────────────────────────────
NEXUS_CORE_STATUS=$(svc_status nexus-core)
NEXUS_API_STATUS=$(svc_status nexus-api)
NEXUS_DASHBOARD_STATUS=$(svc_status nexus-dashboard)
NEXUS_WS_STATUS=$(svc_status nexus-ws)

PORT_8000=$(port_open 8000)
PORT_8001=$(port_open 8001)
PORT_8801=$(port_open 8801)
PORT_9000=$(port_open 9000)

GIT_COMMIT=$(git -C "$NEXUS_HOME" rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git -C "$NEXUS_HOME" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
LAST_DEPLOY=$(grep "DEPLOY_STATUS=OK" "$NEXUS_HOME/logs/deploy.log" 2>/dev/null | tail -1 | cut -d'[' -f2 | cut -d']' -f1 || echo "unknown")

AUTOHEAL_FILE="$NEXUS_HOME/autoheal_state.json"
AUTOHEAL_FAILURES=$(python3 -c "import json,sys; d=json.load(open('$AUTOHEAL_FILE')); print(d.get('consecutive_failures',0))" 2>/dev/null || echo "0")
AUTOHEAL_LAST=$(python3 -c "import json,sys; d=json.load(open('$AUTOHEAL_FILE')); print(d.get('last_action','none'))" 2>/dev/null || echo "none")

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Generate JSON via Python (avoids bash escaping issues) ──────────────────
export NEXUS_CORE_STATUS NEXUS_API_STATUS NEXUS_DASHBOARD_STATUS NEXUS_WS_STATUS
export PORT_8000 PORT_8001 PORT_8801 PORT_9000
export GIT_COMMIT GIT_BRANCH LAST_DEPLOY
export AUTOHEAL_FAILURES AUTOHEAL_LAST TIMESTAMP

JSON=$(python3 << 'PYEOF'
import os, json, psutil

def b(v): return v.lower() == "true"

cpu = psutil.cpu_percent(interval=0.5)
mem = psutil.virtual_memory()
disk = psutil.disk_usage("/")

data = {
    "timestamp": os.environ["TIMESTAMP"],
    "services": {
        "nexus-core":      os.environ["NEXUS_CORE_STATUS"],
        "nexus-api":       os.environ["NEXUS_API_STATUS"],
        "nexus-dashboard": os.environ["NEXUS_DASHBOARD_STATUS"],
        "nexus-ws":        os.environ["NEXUS_WS_STATUS"],
    },
    "ports": {
        "8000": b(os.environ["PORT_8000"]),
        "8001": b(os.environ["PORT_8001"]),
        "8801": b(os.environ["PORT_8801"]),
        "9000": b(os.environ["PORT_9000"]),
    },
    "resources": {
        "cpu_percent": cpu,
        "memory_percent": mem.percent,
        "memory_used_mb": mem.used // 1024 // 1024,
        "memory_total_mb": mem.total // 1024 // 1024,
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
    },
    "git": {
        "commit": os.environ["GIT_COMMIT"],
        "branch": os.environ["GIT_BRANCH"],
        "last_deploy": os.environ["LAST_DEPLOY"],
    },
    "autoheal": {
        "consecutive_failures": int(os.environ["AUTOHEAL_FAILURES"]),
        "last_action": os.environ["AUTOHEAL_LAST"],
    },
}
print(json.dumps(data))
PYEOF
)

# ── Save current ──────────────────────────────────────────────────────
echo "$JSON" > "$CURRENT_FILE"

# ── Append to history (keep max 50) ───────────────────────────────────────
echo "$JSON" >> "$HISTORY_FILE"
LINES=$(wc -l < "$HISTORY_FILE")
if [ "$LINES" -gt "$MAX_ENTRIES" ]; then
    EXCESS=$((LINES - MAX_ENTRIES))
    tail -n "+$((EXCESS + 1))" "$HISTORY_FILE" > "$HISTORY_FILE.tmp"
    mv "$HISTORY_FILE.tmp" "$HISTORY_FILE"
fi

echo "Monitor collected: $TIMESTAMP"
