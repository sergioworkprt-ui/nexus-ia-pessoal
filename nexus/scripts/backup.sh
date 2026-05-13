#!/usr/bin/env bash
# Full NEXUS backup: tar.gz + SHA256, keeps last 10 backups
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
BACKUP_DIR="${BACKUP_DIR:-$NEXUS_HOME/backups}"
LOG="$NEXUS_HOME/logs/backup.log"
MAX_BACKUPS=10

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG")"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [BACKUP] $*" | tee -a "$LOG"; }

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/nexus_backup_$TIMESTAMP.tar.gz"
SHA_FILE="$BACKUP_FILE.sha256"

log "Starting backup → $BACKUP_FILE"

tar -czf "$BACKUP_FILE" \
    --exclude="$NEXUS_HOME/venv" \
    --exclude="$NEXUS_HOME/node_modules" \
    --exclude="$NEXUS_HOME/dashboard/frontend/node_modules" \
    --exclude="$NEXUS_HOME/dashboard/frontend/dist" \
    --exclude="$NEXUS_HOME/dashboard/frontend/.vite" \
    --exclude="$NEXUS_HOME/.git/objects" \
    --exclude="$NEXUS_HOME/backups" \
    --exclude="$NEXUS_HOME/__pycache__" \
    --exclude="*.pyc" \
    -C "$(dirname "$NEXUS_HOME")" \
    "$(basename "$NEXUS_HOME")" \
    2>/dev/null

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
sha256sum "$BACKUP_FILE" > "$SHA_FILE"
SHA=$(cut -d' ' -f1 < "$SHA_FILE")

log "Backup created: $SIZE — SHA256: ${SHA:0:16}..."

sha256sum -c "$SHA_FILE" --quiet 2>/dev/null && log "Integrity check: OK" || {
    log "CRITICAL: Integrity check FAILED"
    exit 1
}

# ── Rotate: keep only last MAX_BACKUPS ────────────────────────────────────────
BACKUP_COUNT=$(ls "$BACKUP_DIR"/nexus_backup_*.tar.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    REMOVE=$((BACKUP_COUNT - MAX_BACKUPS))
    ls -t "$BACKUP_DIR"/nexus_backup_*.tar.gz | tail -"$REMOVE" | while read -r old; do
        rm -f "$old" "${old}.sha256"
        log "Removed old backup: $(basename "$old")"
    done
fi

FINAL_COUNT=$(ls "$BACKUP_DIR"/nexus_backup_*.tar.gz 2>/dev/null | wc -l)
log "BACKUP_STATUS=OK file=$(basename "$BACKUP_FILE") size=$SIZE backups=$FINAL_COUNT"
echo "$BACKUP_FILE"
