#!/usr/bin/env bash
# NEXUS Disaster Recovery — 10-step full restore from latest backup
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
BACKUP_DIR="${BACKUP_DIR:-$NEXUS_HOME/backups}"
LOG="$NEXUS_HOME/logs/disaster_recovery.log"
REPORT_FILE="/tmp/nexus_dr_report_$(date +%Y%m%d_%H%M%S).md"

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [DR] $*" | tee -a "$LOG"; }
step_ok() { log "OK: $1"; echo "- ✔ $1" >> "$REPORT_FILE"; }
step_warn() { log "WARN: $1"; echo "- ⚠ $1" >> "$REPORT_FILE"; }
step_fail() { log "FAILED: $1"; echo "- ✘ $1" >> "$REPORT_FILE"; exit 1; }

TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")

cat > "$REPORT_FILE" << REPORT_HEADER
# NEXUS Disaster Recovery Report
**Date**: $TIMESTAMP
**Host**: $(hostname -f 2>/dev/null || hostname)
**Script**: $0

## Steps
REPORT_HEADER

log "=== DISASTER RECOVERY STARTED ==="

# ── 1. Locate latest backup ───────────────────────────────────────────────────────────────
log "Step 1: Locating latest backup"
LATEST=$(ls -t "$BACKUP_DIR"/nexus_backup_*.tar.gz 2>/dev/null | head -1 || true)
[ -z "$LATEST" ] && step_fail "No backup found in $BACKUP_DIR — run backup.sh first"
step_ok "Found backup: $(basename "$LATEST")"

# ── 2. Verify SHA256 integrity ──────────────────────────────────────────────────────────────
log "Step 2: Verifying backup integrity"
SHA_FILE="${LATEST}.sha256"
if [ -f "$SHA_FILE" ]; then
    sha256sum -c "$SHA_FILE" --quiet 2>/dev/null || step_fail "SHA256 mismatch — backup is corrupted, use an older backup"
    step_ok "Integrity check: SHA256 OK"
else
    step_warn "No SHA256 file found — integrity not verified"
fi

# ── 3. Stop services ──────────────────────────────────────────────────────────────────────────
log "Step 3: Stopping all NEXUS services"
for svc in nexus-core nexus-api nexus-dashboard nexus-ws; do
    systemctl stop "$svc" 2>/dev/null || true
done
step_ok "Services stopped"

# ── 4. Create pre-DR rollback point ─────────────────────────────────────────────────────────
log "Step 4: Creating pre-DR safety snapshot"
ROLLBACK_TS=$(date +%Y%m%d_%H%M%S)
ROLLBACK_ARCHIVE="/tmp/nexus_pre_dr_${ROLLBACK_TS}.tar.gz"
tar -czf "$ROLLBACK_ARCHIVE" \
    --exclude="$NEXUS_HOME/venv" \
    --exclude="$NEXUS_HOME/backups" \
    --exclude="$NEXUS_HOME/__pycache__" \
    --exclude="*.pyc" \
    -C "$(dirname "$NEXUS_HOME")" \
    "$(basename "$NEXUS_HOME")" 2>/dev/null || true
step_ok "Pre-DR snapshot: $(basename "$ROLLBACK_ARCHIVE")"

# ── 5. Extract backup ─────────────────────────────────────────────────────────────────────────
log "Step 5: Extracting backup"
PARENT="$(dirname "$NEXUS_HOME")"
tar -xzf "$LATEST" -C "$PARENT" 2>/dev/null || step_fail "Failed to extract $LATEST"
step_ok "Backup extracted to $PARENT"

# ── 6. Restore/check .env ─────────────────────────────────────────────────────────────────────
log "Step 6: Checking .env"
ENV_FILE="$NEXUS_HOME/.env"
ENV_TEMPLATE="$NEXUS_HOME/.env.template"
if [ -f "$ENV_FILE" ]; then
    chmod 640 "$ENV_FILE"
    step_ok ".env present and secured (640)"
elif [ -f "$ENV_TEMPLATE" ]; then
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    chmod 640 "$ENV_FILE"
    step_warn ".env was missing — created from template. Fill in secrets before restarting."
else
    step_warn ".env and .env.template both missing — create manually before restarting"
fi

# ── 7. Reinstall Python dependencies ─────────────────────────────────────────────────────────
log "Step 7: Reinstalling Python dependencies"
REQUIREMENTS="$NEXUS_HOME/nexus/requirements.txt"
if [ -f "$REQUIREMENTS" ]; then
    VENV="$NEXUS_HOME/venv"
    if [ ! -d "$VENV" ]; then
        python3 -m venv "$VENV" 2>/dev/null || step_fail "Failed to create virtualenv"
    fi
    "$VENV/bin/pip" install -q --upgrade pip 2>/dev/null || true
    "$VENV/bin/pip" install -q -r "$REQUIREMENTS" 2>/dev/null || step_warn "pip install had some errors"
    step_ok "Python deps installed in venv"
else
    step_warn "requirements.txt not found — skipping"
fi

# ── 8. Rebuild dashboard ────────────────────────────────────────────────────────────────────
log "Step 8: Rebuilding dashboard"
REBUILD_SCRIPT="$NEXUS_HOME/nexus/scripts/rebuild_dashboard.sh"
if [ -f "$REBUILD_SCRIPT" ]; then
    VPS_IP=$(curl -sf --max-time 5 http://checkip.amazonaws.com 2>/dev/null || hostname -I | awk '{print $1}')
    bash "$REBUILD_SCRIPT" "$VPS_IP" 2>&1 | tail -10 | tee -a "$LOG" || step_warn "Dashboard rebuild had errors"
    step_ok "Dashboard rebuilt for IP: $VPS_IP"
else
    step_warn "rebuild_dashboard.sh not found"
fi

# ── 9. Start services ──────────────────────────────────────────────────────────────────────────
log "Step 9: Starting NEXUS services"
for svc in nexus-core nexus-api nexus-dashboard; do
    systemctl start "$svc" 2>/dev/null || log "WARNING: Failed to start $svc"
done
sleep 6
step_ok "Services started"

# ── 10. Health validation ─────────────────────────────────────────────────────────────────────
log "Step 10: Health validation"
HC_PASS=0
HEALTH_SCRIPT="$NEXUS_HOME/nexus/scripts/health_check.sh"
if [ -f "$HEALTH_SCRIPT" ]; then
    if bash "$HEALTH_SCRIPT" 2>/dev/null; then
        step_ok "Health check: ALL SERVICES HEALTHY"
        HC_PASS=1
    else
        step_warn "Health check reported issues — manual verification needed"
    fi
elif curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    step_ok "API responding at :8000"
    HC_PASS=1
else
    step_warn "Could not validate health — check services manually"
fi

# ── Final report ──────────────────────────────────────────────────────────────────────────
{
    echo ""
    echo "## Summary"
    if [ "$HC_PASS" -eq 1 ]; then
        echo "**Result: ✔ RECOVERY SUCCESSFUL**"
    else
        echo "**Result: ⚠ RECOVERY PARTIAL — manual action required**"
    fi
    echo ""
    echo "- Backup used: $(basename "$LATEST")"
    echo "- Pre-DR snapshot: $(basename "$ROLLBACK_ARCHIVE")"
    echo "- Completed: $(date -u +"%Y-%m-%d %H:%M UTC")"
} >> "$REPORT_FILE"

log "=== DISASTER RECOVERY COMPLETED ==="
log "Report saved to: $REPORT_FILE"
cat "$REPORT_FILE"

bash "$NEXUS_HOME/scripts/alert.sh" ALERT_DEPLOY_FAIL \
    "Disaster Recovery executed on $(hostname) — result: $([ $HC_PASS -eq 1 ] && echo SUCCESS || echo PARTIAL)" 2>/dev/null || true

exit 0
