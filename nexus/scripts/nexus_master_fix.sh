#!/usr/bin/env bash
# nexus_master_fix.sh — Reparação completa do NEXUS no VPS
# Uso: sudo bash /opt/nexus/nexus/scripts/nexus_master_fix.sh
#
# ARQUITECTURA CORRECRA:
#   Porta 8000 — nexus-core   : REST API (uvicorn nexus.main)
#   Porta 8801 — nexus-ws     : WebSocket standalone (ws_server.py)
#   Porta 9000 — nexus-dashboard : dashboard React
#
# nexus-api foi REMOVIDO (conflito de porta 8000 com nexus-core)
set -uo pipefail

NEXUS_HOME="/opt/nexus"
VENV="$NEXUS_HOME/venv"
BRANCH="claude/create-test-file-d1AY6"
LOG_DIR="$NEXUS_HOME/logs"
LOG_FILE="$LOG_DIR/master_fix_$(date +%Y%m%d_%H%M%S).log"
ENV_FILE="$NEXUS_HOME/.env"
SVC_DIR="/etc/systemd/system"

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

# ─── STEP 1: Parar todos os serviços (incluindo os conflituosos) ───────────────
info "[1/10] A parar serviços NEXUS..."
for svc in nexus-core nexus-api nexus-ws nexus-dashboard nexus-backend; do
    if systemctl is-active --quiet "$svc" 2>/dev/null || \
       systemctl is-failed --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc" 2>/dev/null && ok "  $svc parado" || warn "  $svc: erro ao parar"
    else
        warn "  $svc já estava inactivo"
    fi
done

# ─── STEP 2: git pull ─────────────────────────────────────────────────────
info "[2/10] git pull ($BRANCH)..."
cd "$NEXUS_HOME"
if git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" && \
   git reset --hard "origin/$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Código actualizado: $(git rev-parse --short HEAD)"
else
    warn "  git pull falhou — a continuar com código actual"
fi

# ─── STEP 3: Actualizar dependências Python ────────────────────────────────
info "[3/10] Actualizar dependências Python..."
REQ="$NEXUS_HOME/nexus/requirements.txt"
if [[ -f "$VENV/bin/pip" ]]; then
    "$VENV/bin/pip" install --upgrade pip -q 2>&1 | tail -1 | tee -a "$LOG_FILE" || true
    if "$VENV/bin/pip" install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE"; then
        ok "  pip (venv): dependências actualizadas"
    else
        warn "  pip install falhou — a continuar"
    fi
elif command -v pip3 &>/dev/null; then
    if pip3 install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE"; then
        ok "  pip3: dependências actualizadas"
    else
        warn "  pip3 install falhou"
    fi
else
    warn "  pip não encontrado — cria o venv: python3 -m venv $VENV"
fi

# ─── STEP 4: Verificar e criar .env ───────────────────────────────────────
info "[4/10] A verificar .env..."
if [[ ! -f "$ENV_FILE" ]]; then
    warn "  .env não encontrado — a criar mínimo funcional..."
    cat > "$ENV_FILE" <<MINENV
NEXUS_HOME=/opt/nexus
NEXUS_API_KEY=nexus-change-me
AUTOMATION_API_KEY=
LOG_DIR=/opt/nexus/logs
API_HOST=0.0.0.0
API_PORT=8000
WS_HOST=0.0.0.0
WS_PORT=8801
DASHBOARD_PORT=9000
MINENV
    chmod 640 "$ENV_FILE"
    ok "  .env criado com WS_PORT=8801"
else
    ok "  .env existe"
fi

# CORRIGIR WS_PORT no .env existente: 8001 → 8801
# Esta é a causa raiz do WebSocket "Failed to fetch" — o frontend usa 8801
if grep -q 'WS_PORT=8001' "$ENV_FILE" 2>/dev/null; then
    sed -i 's/WS_PORT=8001/WS_PORT=8801/g' "$ENV_FILE"
    ok "  .env: WS_PORT corrigido de 8001 → 8801 (frontend usa 8801)"
elif ! grep -q 'WS_PORT' "$ENV_FILE" 2>/dev/null; then
    echo 'WS_PORT=8801' >> "$ENV_FILE"
    ok "  .env: WS_PORT=8801 adicionado"
else
    WS_VAL=$(grep 'WS_PORT' "$ENV_FILE" | cut -d= -f2 | head -1)
    ok "  .env: WS_PORT=$WS_VAL (ok)"
fi

# ─── STEP 5: Criar directorios necessários ─────────────────────────────────
info "[5/10] A criar directorios necessários..."
for d in \
    "$NEXUS_HOME/logs" \
    "$NEXUS_HOME/monitor" \
    "$NEXUS_HOME/backups" \
    "$NEXUS_HOME/data" \
    "/var/log/nexus"
do
    mkdir -p "$d" 2>/dev/null && ok "  $d" || warn "  Não foi possível criar $d"
done

# ─── STEP 6: Corrigir ficheiros de serviço systemd ─────────────────────────
info "[6/10] A corrigir serviços systemd..."

# Determinar Python a usar (venv preferido)
if [[ -f "$VENV/bin/python" ]]; then
    PYTHON="$VENV/bin/python"
elif [[ -f "$VENV/bin/uvicorn" ]]; then
    PYTHON="$VENV/bin/python"
else
    PYTHON=$(command -v python3 || echo python3)
fi
ok "  Python: $PYTHON"

# Determinar utilizador do serviço
SVC_USER="nexus"
if ! id -u "$SVC_USER" &>/dev/null; then
    SVC_USER=$(stat -c '%U' "$NEXUS_HOME" 2>/dev/null || echo root)
    warn "  Utilizador 'nexus' não existe — a usar '$SVC_USER'"
fi

# 6a. Desactivar nexus-api (conflituava com nexus-core na porta 8000)
if systemctl is-enabled --quiet nexus-api 2>/dev/null; then
    systemctl disable nexus-api 2>/dev/null || true
    rm -f "$SVC_DIR/nexus-api.service"
    ok "  nexus-api: DESACTIVADO e ficheiro removido"
else
    ok "  nexus-api: já não estava activo"
fi

# 6b. Desactivar nexus-backend (criado por nexus_fix.sh, conflituava na porta 8000)
if systemctl is-enabled --quiet nexus-backend 2>/dev/null; then
    systemctl disable nexus-backend 2>/dev/null || true
    rm -f "$SVC_DIR/nexus-backend.service"
    ok "  nexus-backend: DESACTIVADO e ficheiro removido"
else
    ok "  nexus-backend: já não estava activo"
fi

# 6c. Criar/actualizar nexus-core.service (REST API em 8000)
cat > "$SVC_DIR/nexus-core.service" <<SVC_CORE
[Unit]
Description=NEXUS AI — Core (REST API porta 8000 + WS thread 8801)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$NEXUS_HOME
EnvironmentFile=-$ENV_FILE
Environment=PYTHONPATH=$NEXUS_HOME
Environment=LOG_DIR=/var/log/nexus
ExecStart=$PYTHON -m nexus.main
Restart=always
RestartSec=10
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-core

[Install]
WantedBy=multi-user.target
SVC_CORE
ok "  nexus-core.service: actualizado"

# 6d. Criar/actualizar nexus-ws.service (WebSocket standalone porta 8801)
cat > "$SVC_DIR/nexus-ws.service" <<SVC_WS
[Unit]
Description=NEXUS AI — WebSocket standalone (porta 8801)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$NEXUS_HOME
EnvironmentFile=-$ENV_FILE
Environment=PYTHONPATH=$NEXUS_HOME
Environment=WS_PORT=8801
Environment=WS_HOST=0.0.0.0
ExecStart=$PYTHON $NEXUS_HOME/nexus/ws_server.py
Restart=always
RestartSec=5
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-ws

[Install]
WantedBy=multi-user.target
SVC_WS
ok "  nexus-ws.service: actualizado (WS_PORT=8801)"

# 6e. Activar serviços correctos
systemctl daemon-reload
for svc in nexus-core nexus-ws nexus-dashboard; do
    if [[ -f "$SVC_DIR/${svc}.service" ]]; then
        systemctl enable "$svc" 2>/dev/null && ok "  $svc: enabled" || warn "  $svc: enable falhou"
    fi
done

# ─── STEP 7: Iniciar serviços ───────────────────────────────────────────
info "[7/10] A iniciar serviços..."

# Iniciar nexus-ws PRIMEIRO (ocupa porta 8801 antes do nexus-core tentar)
systemctl start nexus-ws 2>/dev/null && sleep 2 || true
if systemctl is-active --quiet nexus-ws; then
    ok "  nexus-ws: ACTIVE (ws://0.0.0.0:8801)"
else
    fail "  nexus-ws: não ficou activo"
    journalctl -u nexus-ws -n 15 --no-pager 2>/dev/null | tail -10 | tee -a "$LOG_FILE" || true
fi

# Depois nexus-core (API + WS thread como fallback)
systemctl start nexus-core 2>/dev/null || true
sleep 5
if systemctl is-active --quiet nexus-core; then
    ok "  nexus-core: ACTIVE (api://0.0.0.0:8000)"
else
    fail "  nexus-core: não ficou activo"
    journalctl -u nexus-core -n 15 --no-pager 2>/dev/null | tail -10 | tee -a "$LOG_FILE" || true
fi

# Dashboard por último
if systemctl is-enabled --quiet nexus-dashboard 2>/dev/null; then
    systemctl start nexus-dashboard 2>/dev/null || true
    sleep 3
    if systemctl is-active --quiet nexus-dashboard; then
        ok "  nexus-dashboard: ACTIVE (:9000)"
    else
        fail "  nexus-dashboard: não ficou activo"
        journalctl -u nexus-dashboard -n 10 --no-pager 2>/dev/null | tail -8 | tee -a "$LOG_FILE" || true
    fi
fi

# ─── STEP 8: Rebuild do dashboard ────────────────────────────────────────
info "[8/10] Rebuild do dashboard..."
VPS_IP=$(
    curl -s --max-time 5 https://api.ipify.org 2>/dev/null ||
    curl -s --max-time 5 https://ifconfig.me 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{print $1}'
)
[[ -z "$VPS_IP" ]] && VPS_IP="35.241.151.115"
ok "  IP detectado: $VPS_IP"

# O rebuild vai gerar VITE_WS_URL=ws://$VPS_IP:8801 (correcto)
if bash "$NEXUS_HOME/nexus/scripts/rebuild_dashboard.sh" "$VPS_IP" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Dashboard rebuild OK (VITE_WS_URL=ws://$VPS_IP:8801)"
else
    warn "  Dashboard rebuild falhou — a continuar"
fi

# ─── STEP 9: Health check ────────────────────────────────────────────────
info "[9/10] Health check..."
sleep 5
bash "$NEXUS_HOME/nexus/scripts/health_check.sh" 2>&1 | tee -a "$LOG_FILE"
HC_STATUS=$?

# ─── STEP 10: Sumário final ────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
info "[10/10] Sumário final"
echo "" | tee -a "$LOG_FILE"

for svc in nexus-core nexus-ws nexus-dashboard; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "n/a")
    if [[ "$status" == "active" ]]; then
        ok "  $svc: $status"
    else
        warn "  $svc: $status"
    fi
done
echo ""

for entry in "8000:REST API" "8801:WebSocket" "9000:Dashboard"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    if ss -tulpn 2>/dev/null | grep -q ":${PORT}"; then
        ok "  :$PORT ($LABEL): ABERTO"
    else
        warn "  :$PORT ($LABEL): FECHADO"
    fi
done
echo ""

API_RESP=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || echo "")
if echo "$API_RESP" | grep -q '"status"'; then
    ok "  GET :8000/health → $API_RESP"
else
    fail "  GET :8000/health → sem resposta"
fi

DASH_RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -1 || echo "")
if echo "$DASH_RESP" | grep -qi '<!doctype\|<html'; then
    ok "  GET :9000/ → HTML OK"
else
    fail "  GET :9000/ → sem resposta"
fi

echo ""
echo "  Log completo: $LOG_FILE"
echo ""

if [[ $HC_STATUS -eq 0 ]]; then
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  NEXUS: OPERACIONAL ✔${NC}"
    echo -e "${GREEN}  Dashboard:  http://${VPS_IP}:9000${NC}"
    echo -e "${GREEN}  API:        http://${VPS_IP}:8000${NC}"
    echo -e "${GREEN}  WebSocket:  ws://${VPS_IP}:8801${NC}"
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
    echo "    journalctl -u nexus-ws        -n 50 --no-pager"
    echo "    journalctl -u nexus-dashboard -n 50 --no-pager"
    echo "    cat $LOG_FILE"
    exit 1
fi
