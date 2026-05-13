#!/usr/bin/env bash
# Auto-healer: health-check → restart → rollback → alert
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
STATE_FILE="$NEXUS_HOME/autoheal_state.json"
LOG="$NEXUS_HOME/logs/autoheal.log"
MAX_FAILURES=3
SERVICES=(nexus-core nexus-api nexus-dashboard)

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [AUTOHEAL] $*" | tee -a "$LOG"; }

# ── Load / init state ───────────────────────────────────────────────
if [ -f "$STATE_FILE" ]; then
    FAILURES=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('consecutive_failures',0))" 2>/dev/null || echo 0)
else
    FAILURES=0
fi

save_state() {
    local action="$1"
    python3 - <<PYEOF
import json, datetime
data = {
    "consecutive_failures": $FAILURES,
    "last_action": "$action",
    "last_check": datetime.datetime.utcnow().isoformat() + "Z"
}
with open("$STATE_FILE", "w") as f:
    json.dump(data, f, indent=2)
PYEOF
}

# ── Health check ────────────────────────────────────────────────────
FAILED_SERVICES=()
for svc in "${SERVICES[@]}"; do
    if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
        FAILED_SERVICES+=("$svc")
    fi
done

if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    FAILED_SERVICES+=("http:8000")
fi

if [ ${#FAILED_SERVICES[@]} -eq 0 ]; then
    log "All services healthy"
    FAILURES=0
    save_state "healthy"
    bash "$NEXUS_HOME/scripts/monitor_collect.sh" 2>/dev/null || true
    exit 0
fi

log "FAILED: ${FAILED_SERVICES[*]}"
FAILURES=$((FAILURES + 1))

# ── Restart attempt ───────────────────────────────────────────────────
if [ "$FAILURES" -lt "$MAX_FAILURES" ]; then
    log "Attempt $FAILURES/$MAX_FAILURES — restarting services"
    for svc in "${SERVICES[@]}"; do
        systemctl restart "$svc" 2>/dev/null || true
    done
    sleep 5
    STILL_FAILED=0
    for svc in "${SERVICES[@]}"; do
        if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
            STILL_FAILED=1
        fi
    done
    if [ "$STILL_FAILED" -eq 0 ] && curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        log "Services recovered after restart"
        FAILURES=0
        save_state "restarted"
        exit 0
    fi
    save_state "restart_failed"
    log "Restart did not recover services (failures: $FAILURES)"
    exit 1
fi

# ── Rollback trigger ──────────────────────────────────────────────────
log "MAX_FAILURES ($MAX_FAILURES) reached — triggering rollback"
save_state "rollback_triggered"

if [ -f "$NEXUS_HOME/scripts/rollback.sh" ]; then
    bash "$NEXUS_HOME/scripts/rollback.sh" auto 1 "autoheal: $FAILURES consecutive failures" 2>&1 | tee -a "$LOG"
else
    log "CRITICAL: rollback.sh not found!"
fi

# ── Alert (optional webhook) ──────────────────────────────────────────────
ALERT_WEBHOOK="${ALERT_WEBHOOK:-}"
if [ -n "$ALERT_WEBHOOK" ]; then
    SVCS_STR="${FAILED_SERVICES[*]}"
    curl -sf -X POST "$ALERT_WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "{\"text\": \"🚨 NEXUS AUTOHEAL: $FAILURES failures — rollback triggered. Services: $SVCS_STR\"}" \
        2>/dev/null || true
fi

log "AUTOHEAL_STATUS=ROLLBACK failures=$FAILURES"
exit 1
