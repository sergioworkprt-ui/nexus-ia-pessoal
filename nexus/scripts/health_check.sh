#!/usr/bin/env bash
# health_check.sh — Verifica se os serviços NEXUS estão activos
# Uso: bash /opt/nexus/nexus/scripts/health_check.sh
# Exit code: 0 = tudo OK, 1 = algum serviço falhou

set -uo pipefail

NEXUS_HOME="/opt/nexus"
LOG_DIR="$NEXUS_HOME/logs"
LOG_FILE="$LOG_DIR/deploy.log"
FAIL=0

mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { local msg="$*"; echo -e "${GREEN}✔ ${msg}${NC}"; echo "[HC] OK: $msg" >> "$LOG_FILE"; }
fail() { local msg="$*"; echo -e "${RED}✘ ${msg}${NC}"; echo "[HC] FAIL: $msg" >> "$LOG_FILE"; FAIL=1; }
info() { echo -e "${BLUE}▸ $*${NC}"; }

echo "--- health_check $(date -u +%Y-%m-%dT%H:%M:%SZ) ---" >> "$LOG_FILE"

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS Health Check${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# 1. systemd services
# nexus-api foi REMOVIDO (conflito de porta 8000 com nexus-core)
# nexus-ws gere o WebSocket standalone na porta 8801
info "Serviços systemd:"
for svc in nexus-core nexus-ws nexus-dashboard; do
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        if systemctl is-active --quiet "$svc"; then
            ok "  $svc: ACTIVE"
        else
            fail "  $svc: INACTIVE"
            systemctl status "$svc" --no-pager -l 2>/dev/null | tail -5 || true
        fi
    else
        echo -e "${YELLOW}  $svc: não registado (skip)${NC}"
    fi
done

# 2. Portas abertas
# 8000: nexus-core REST API
# 8801: nexus-ws WebSocket (não 8001 — frontend usa 8801)
# 9000: nexus-dashboard
info "Portas TCP:"
for entry in "8000:REST-API" "8801:WebSocket" "9000:Dashboard"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    if ss -tulpn 2>/dev/null | grep -q ":${PORT}"; then
        ok "  :${PORT} ${LABEL}: ABERTA"
    else
        fail "  :${PORT} ${LABEL}: FECHADA"
    fi
done

# 3. HTTP health endpoints
info "Endpoints HTTP:"
API_RESP=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null)
if echo "$API_RESP" | grep -q '"status"'; then
    ok "  GET :8000/health → $API_RESP"
else
    fail "  GET :8000/health → sem resposta válida"
fi

DASH_RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -1)
if echo "$DASH_RESP" | grep -qi '<!doctype\|<html'; then
    ok "  GET :9000/ → HTML OK"
else
    fail "  GET :9000/ → não devolve HTML"
fi

# 4. Resultado final
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}   NEXUS: TUDO OK${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo "HEALTH_CHECK=PASS  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"
    exit 0
else
    echo -e "${RED}════════════════════════════════════════${NC}"
    echo -e "${RED}   NEXUS: FALHAS DETECTADAS${NC}"
    echo -e "${RED}   Log: $LOG_FILE${NC}"
    echo -e "${RED}════════════════════════════════════════${NC}"
    echo "HEALTH_CHECK=FAIL  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"
    exit 1
fi
