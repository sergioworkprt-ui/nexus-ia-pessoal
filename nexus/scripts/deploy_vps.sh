#!/usr/bin/env bash
# deploy_vps.sh — Executado pelo GitHub Actions no VPS
# Uso: bash /opt/nexus/nexus/scripts/deploy_vps.sh [COMMIT_SHA]

set -euo pipefail

COMMIT="${1:-unknown}"
NEXUS_HOME="/opt/nexus"
BRANCH="claude/create-test-file-d1AY6"
LOG_DIR="$NEXUS_HOME/logs"
LOG_FILE="$LOG_DIR/deploy.log"

mkdir -p "$LOG_DIR"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

{
  echo ""
  echo "=================================================================="
  echo "DEPLOY $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$COMMIT  branch=$BRANCH"
  echo "=================================================================="
} >> "$LOG_FILE"

log "[1/5] git pull..."
cd "$NEXUS_HOME"
git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE"
git reset --hard "origin/$BRANCH" 2>&1 | tee -a "$LOG_FILE"
log "    code at $(git rev-parse --short HEAD)"

log "[2/5] Actualizar dependências Python..."
VENV="$NEXUS_HOME/venv"
REQ="$NEXUS_HOME/nexus/requirements.txt"
if [[ -f "$VENV/bin/pip" ]]; then
    "$VENV/bin/pip" install --upgrade pip -q 2>&1 | tail -1 | tee -a "$LOG_FILE" || true
    "$VENV/bin/pip" install -r "$REQ" -q 2>&1 | tail -3 | tee -a "$LOG_FILE" && \
        log "    pip (venv) OK" || log "    AVISO: pip install falhou (ver log)"
elif command -v pip3 &>/dev/null; then
    pip3 install -r "$REQ" -q 2>&1 | tail -3 | tee -a "$LOG_FILE" && \
        log "    pip3 OK" || log "    AVISO: pip3 install falhou (ver log)"
else
    log "    AVISO: pip não encontrado — a saltar"
fi

log "[3/5] Reiniciar nexus-core e nexus-api..."
for svc in nexus-core nexus-api; do
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        systemctl restart "$svc" 2>&1 | tee -a "$LOG_FILE" && log "    $svc OK" || log "    $svc FALHOU"
    else
        log "    $svc nao encontrado (skip)"
    fi
done

log "[4/5] Rebuild do dashboard..."
bash "$NEXUS_HOME/nexus/scripts/rebuild_dashboard.sh" 35.241.151.115 2>&1 | tee -a "$LOG_FILE"

log "[5/5] Deploy concluido com sucesso."
echo "DEPLOY_STATUS=OK  commit=$COMMIT  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"
