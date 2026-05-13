#!/usr/bin/env bash
# Upload latest NEXUS backup to S3/Minio remote storage
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
LOG="$NEXUS_HOME/logs/backup.log"

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [BACKUP-REMOTE] $*" | tee -a "$LOG"; }

# Load env vars
if [ -f "$NEXUS_HOME/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$NEXUS_HOME/.env"
    set +a
fi

S3_BUCKET="${S3_BUCKET:-}"
S3_ENDPOINT="${S3_ENDPOINT:-}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}"

if [ -z "$S3_BUCKET" ]; then
    log "S3_BUCKET not configured — skipping remote backup"
    exit 0
fi

# ── Find latest local backup ────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-$NEXUS_HOME/backups}"
LATEST=$(ls -t "$BACKUP_DIR"/nexus_backup_*.tar.gz 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    log "No local backup found — run backup.sh first"
    exit 1
fi

BASENAME=$(basename "$LATEST")
log "Uploading $BASENAME to s3://$S3_BUCKET"

# ── Try aws CLI first, fallback to mc (Minio) ───────────────────────────────
if command -v aws &>/dev/null; then
    ENDPOINT_ARG=""
    [ -n "$S3_ENDPOINT" ] && ENDPOINT_ARG="--endpoint-url $S3_ENDPOINT"
    AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    aws s3 cp "$LATEST" "s3://$S3_BUCKET/nexus/$BASENAME" $ENDPOINT_ARG --no-progress 2>&1 | tee -a "$LOG"
    AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    aws s3 cp "${LATEST}.sha256" "s3://$S3_BUCKET/nexus/${BASENAME}.sha256" $ENDPOINT_ARG --no-progress 2>&1 | tee -a "$LOG"
elif command -v mc &>/dev/null; then
    mc alias set nexus-remote "$S3_ENDPOINT" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" 2>/dev/null
    mc cp "$LATEST" "nexus-remote/$S3_BUCKET/nexus/$BASENAME" 2>&1 | tee -a "$LOG"
    mc cp "${LATEST}.sha256" "nexus-remote/$S3_BUCKET/nexus/${BASENAME}.sha256" 2>&1 | tee -a "$LOG"
else
    log "Neither aws CLI nor mc found — cannot upload to remote storage"
    exit 1
fi

log "REMOTE_BACKUP_STATUS=OK file=$BASENAME bucket=$S3_BUCKET"
