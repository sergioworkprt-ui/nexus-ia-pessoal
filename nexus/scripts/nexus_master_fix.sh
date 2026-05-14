#!/usr/bin/env bash
# nexus_master_fix.sh — Reparação completa do NEXUS no VPS
# Uso: sudo bash /opt/nexus/nexus/scripts/nexus_master_fix.sh
#
# Executa quando o sistema está quebrado e o deploy normal não funciona.
# Faz: stop services → git pull → pip install → .env check → mkdir
#      → restart services → rebuild dashboard → health check → sumário
set -uo pipefail

NEXUS_HOME="/opt/nexus"
BRANCH="claude/create-test-file-d1AY6"
LOG_DIR="$NEXUS_HOME/logs"
LOG_FILE="$LOG_DIR/master_fix_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; echo "[OK]   $*" >> "$LOG_FILE"; }
fail() { echo -e "${RED}✘ $*${NC}"; echo "[FAIL] $*" >> "$LOG_FILE"; }
info() { echo -e "${BLUE}▸ $*${NC}"; echo "[INFO] $*" >> "$LOG_FILE"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; echo "[WARN] $*" >> "$LOG_FILE"; }

{
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "  NEXUS Master Fix — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "═══════════════════════════════════════════════════════"
} | tee -a "$LOG_FILE"

# ─── STEP 1: Parar todos os serviços ───────────────────────────────────────
info "[1/9] A parar serviços NEXUS..."
for svc in nexus-core nexus-api nexus-dashboard nexus-ws; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc" 2>/dev/null && ok "  $svc parado" || warn "  $svc: erro ao parar"
    else
        warn "  $svc já estava parado"
    fi
done

# ─── STEP 2: git pull ────────────────────────────────────────────────────
info "[2/9] git pull ($BRANCH)..."
cd "$NEXUS_HOME"
if git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" && \
   git reset --hard "origin/$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Código actualizado: $(git rev-parse --short HEAD)"
else
    warn "  git pull falhou — a continuar com código actual"
fi

# ─── STEP 3: Actualizar dependências Python ────────────────────────────────
info "[3/9] Actualizar dependências Python..."
VENV="$NEXUS_HOME/venv"
REQ="$NEXUS_HOME/nexus/requirements.txt"
if [[ -f "$VENV/bin/pip" ]]; then
    "$VENV/bin/pip" install --upgrade pip -q 2>&1 | tail -1 | tee -a "$LOG_FILE" || true
    if "$VENV/bin/pip" install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE"; then
        ok "  pip (venv): dependências actualizadas"
    else
        warn "  pip install falhou — continuar assim mesmo"
    fi
elif command -v pip3 &>/dev/null; then
    if pip3 install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE"; then
        ok "  pip3: dependências actualizadas"
    else
        warn "  pip3 install falhou — continuar assim mesmo"
    fi
else
    warn "  pip não encontrado — venv não existe em $VENV"
    warn "  Cria o venv: python3 -m venv $VENV && $VENV/bin/pip install -r $REQ"
fi

# ─── STEP 4: Verificar e criar .env ───────────────────────────────────────
info "[4/9] A verificar .env..."
ENV_FILE="$NEXUS_HOME/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    warn "  .env não encontrado — a criar de .env.example..."
    EXAMPLE="$NEXUS_HOME/nexus/.env.example"
    if [[ -f "$EXAMPLE" ]]; then
        cp "$EXAMPLE" "$ENV_FILE"
        chmod 640 "$ENV_FILE"
        ok "  .env criado de .env.example — EDITA as variáveis antes de usar!"
    else
        warn "  .env.example também não encontrado em $EXAMPLE"
        # Criar .env mínimo funcional
        cat > "$ENV_FILE" <<MINENV
NEXUS_HOME=/opt/nexus
NEXUS_API_KEY=nexus-change-me
LOG_DIR=/opt/nexus/logs
API_PORT=8000
WS_PORT=8801
MINENV
        chmod 640 "$ENV_FILE"
        ok "  .env mínimo criado — actualiza NEXUS_API_KEY!"
    fi
else
    ok "  .env existe"
fi

# ─── STEP 5: Criar directorios necessários ─────────────────────────────────
info "[5/9] A criar directorios necessários..."
for d in \
    "$NEXUS_HOME/logs" \
    "$NEXUS_HOME/monitor" \
    "$NEXUS_HOME/backups" \
    "$NEXUS_HOME/data" \
    "/var/log/nexus"
do
    mkdir -p "$d" 2>/dev/null && ok "  $d" || warn "  Não foi possível criar $d"
done

# ─── STEP 6: Reiniciar serviços ───────────────────────────────────────────
info "[6/9] A reiniciar serviços..."
for svc in nexus-core nexus-api nexus-ws; do
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        if systemctl restart "$svc" 2>&1 | tee -a "$LOG_FILE"; then
            sleep 2
            if systemctl is-active --quiet "$svc"; then
                ok "  $svc: ACTIVE"
            else
                fail "  $svc: FAILED após restart"
                echo "  ▸ journalctl -u $svc -n 20 --no-pager:"
                journalctl -u "$svc" -n 20 --no-pager 2>/dev/null | tail -10 | tee -a "$LOG_FILE" || true
            fi
        else
            fail "  $svc: restart falhou"
        fi
    else
        warn "  $svc não está em systemd (skip)"
    fi
done
sleep 3

# ─── STEP 7: Rebuild do dashboard ────────────────────────────────────────
info "[7/9] Rebuild do dashboard..."
VPS_IP=$(
    curl -s --max-time 5 https://api.ipify.org 2>/dev/null ||
    curl -s --max-time 5 https://ifconfig.me 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{print $1}'
)
if [[ -z "$VPS_IP" ]]; then
    warn "  Não foi possível detectar o IP público — a usar 35.241.151.115"
    VPS_IP="35.241.151.115"
fi
ok "  IP detectado: $VPS_IP"

if bash "$NEXUS_HOME/nexus/scripts/rebuild_dashboard.sh" "$VPS_IP" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Dashboard rebuild OK"
else
    warn "  Dashboard rebuild falhou — continuar"
fi

# ─── STEP 8: Health check ────────────────────────────────────────────────
info "[8/9] Health check..."
sleep 5
bash "$NEXUS_HOME/nexus/scripts/health_check.sh" 2>&1 | tee -a "$LOG_FILE"
HC_STATUS=$?

# ─── STEP 9: Sumário final ──────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
info "[9/9] Sumário final"
echo "" | tee -a "$LOG_FILE"

# Estado dos serviços
for svc in nexus-core nexus-api nexus-dashboard nexus-ws; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "n/a")
    if [[ "$status" == "active" ]]; then
        ok "  $svc: $status"
    else
        warn "  $svc: $status"
    fi
done

echo ""

# Estado das portas
for entry in "8000:nexus-core API" "8001:nexus-api" "8801:WebSocket" "9000:Dashboard"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    if ss -tulpn 2>/dev/null | grep -q ":${PORT}"; then
        ok "  :$PORT ($LABEL): ABERTO"
    else
        warn "  :$PORT ($LABEL): FECHADO"
    fi
done

echo ""

# Teste rápido de endpoints
API_RESP=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || echo "")
if echo "$API_RESP" | grep -q '"status"'; then
    ok "  GET :8000/health → $API_RESP"
else
    fail "  GET :8000/health → sem resposta (API não responde)"
fi

DASH_RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -1 || echo "")
if echo "$DASH_RESP" | grep -qi '<!doctype\|<html'; then
    ok "  GET :9000/ → HTML OK"
else
    fail "  GET :9000/ → dashboard não responde"
fi

echo ""
echo "  Log completo: $LOG_FILE"
echo ""

if [[ $HC_STATUS -eq 0 ]]; then
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  NEXUS: OPERACIONAL ✔${NC}"
    echo -e "${GREEN}  Dashboard: http://${VPS_IP}:9000${NC}"
    echo -e "${GREEN}  API:       http://${VPS_IP}:8000${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    exit 0
else
    echo -e "${RED}═══════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  NEXUS: FALHAS DETECTADAS${NC}"
    echo -e "${RED}  Ver log: $LOG_FILE${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Diagnóstico adicional:"
    echo "    journalctl -u nexus-core      -n 50 --no-pager"
    echo "    journalctl -u nexus-api       -n 50 --no-pager"
    echo "    journalctl -u nexus-dashboard -n 50 --no-pager"
    echo "    cat $LOG_FILE"
    exit 1
fi
