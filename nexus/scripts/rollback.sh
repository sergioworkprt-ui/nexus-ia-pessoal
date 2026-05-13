#!/usr/bin/env bash
# rollback.sh — Reverte o VPS para um commit anterior
# Uso: sudo bash /opt/nexus/nexus/scripts/rollback.sh [auto|manual] [N] [motivo]
# Exemplos:
#   sudo bash rollback.sh auto 1
#   sudo bash rollback.sh manual 2 "hotfix pendente"

set -uo pipefail

MODE="${1:-auto}"
N="${2:-1}"
REASON="${3:-sem motivo especificado}"
NEXUS_HOME="/opt/nexus"
LOG_DIR="$NEXUS_HOME/logs"
LOG_FILE="$LOG_DIR/deploy.log"

mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { local m="$*"; echo -e "${GREEN}✔ ${m}${NC}"; echo "[RB] OK: $m" >> "$LOG_FILE"; }
fail() { local m="$*"; echo -e "${RED}✘ ${m}${NC}"; echo "[RB] FAIL: $m" >> "$LOG_FILE"; }
info() { echo -e "${BLUE}▸ $*${NC}"; }

{
  echo ""
  echo "================================================================"
  echo "ROLLBACK $(date -u +%Y-%m-%dT%H:%M:%SZ)  mode=$MODE  n=$N"
  echo "reason=$REASON"
  echo "================================================================"
} >> "$LOG_FILE"

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS Rollback [$MODE, -${N} commit(s)]   ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
info "Motivo: $REASON"

cd "$NEXUS_HOME"

CURRENT=$(git rev-parse HEAD 2>/dev/null) || { fail "Não é um repositório git válido"; exit 1; }
TARGET=$(git rev-parse "HEAD~${N}" 2>/dev/null) || {
    fail "Commit HEAD~${N} não existe (histórico insuficiente)"
    exit 1
}

info "Commit actual : $(git log -1 --oneline $CURRENT)"
info "Rollback para : $(git log -1 --oneline $TARGET)"
echo ""

# Reverter ficheiros para o commit alvo (mantém HEAD do git intacto)
git checkout "$TARGET" -- . 2>&1 | tee -a "$LOG_FILE" || {
    fail "git checkout falhou"
    exit 1
}
ok "Ficheiros revertidos para $TARGET"

# Reiniciar serviços
info "A reiniciar serviços..."
for svc in nexus-core nexus-api nexus-dashboard; do
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        systemctl restart "$svc" 2>&1 | tee -a "$LOG_FILE" \
            && ok "  $svc reiniciado" \
            || fail "  $svc falhou ao reiniciar"
    fi
done

sleep 5

# Health check pós-rollback
info "A verificar saúde dos serviços..."
bash "$NEXUS_HOME/nexus/scripts/health_check.sh" && {
    ok "Rollback concluído e serviços OK"
    echo "ROLLBACK=OK  target=$TARGET  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"
} || {
    fail "Rollback aplicado mas health check falhou — verifica os serviços manualmente"
    echo "ROLLBACK=PARTIAL  target=$TARGET  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"
    exit 1
}
