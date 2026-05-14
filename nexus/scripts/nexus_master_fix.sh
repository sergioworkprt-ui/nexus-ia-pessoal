#!/usr/bin/env bash
# nexus_master_fix.sh — Reparação completa do NEXUS no VPS
# Uso: sudo bash /opt/nexus/nexus/scripts/nexus_master_fix.sh
#
# ARQUITECTURA:
#   Porto 8000 — nexus-core : REST API (uvicorn nexus.api_server:app)
#   Porto 9000 — nexus-dashboard : dashboard React + proxy /api/* e /ws
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

# ─── STEP 1: Parar todos os serviços ─────────────────────────────────────────────
info "[1/10] A parar serviços NEXUS..."
for svc in nexus-core nexus-api nexus-ws nexus-dashboard nexus-backend; do
    if systemctl is-active --quiet "$svc" 2>/dev/null || \
       systemctl is-failed --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc" 2>/dev/null && ok "  $svc parado" || warn "  $svc: erro ao parar"
    else
        warn "  $svc já estava inactivo"
    fi
done
# Garantir que nenhum processo ocupa a porta 8000
if ss -tulpn 2>/dev/null | grep -q ':8000'; then
    warn "  Porto 8000 ainda em uso após stop! A matar processo..."
    fuser -k 8000/tcp 2>/dev/null || true
    sleep 2
    ss -tulpn 2>/dev/null | grep -q ':8000' && fail "  Porto 8000 AINDA em uso" || ok "  Porto 8000 livre"
else
    ok "  Porto 8000 livre"
fi

# ─── STEP 2: git pull ───────────────────────────────────────────────────────
info "[2/10] git pull ($BRANCH)..."
cd "$NEXUS_HOME"
if git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" && \
   git reset --hard "origin/$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Código actualizado: $(git rev-parse --short HEAD)"
else
    warn "  git pull falhou — a continuar com código actual"
fi

# ─── STEP 3: Actualizar dependências Python ──────────────────────────────────────
info "[3/10] Actualizar dependências Python..."
REQ="$NEXUS_HOME/nexus/requirements.txt"
if [[ -f "$VENV/bin/pip" ]]; then
    "$VENV/bin/pip" install --upgrade pip -q 2>&1 | tail -1 | tee -a "$LOG_FILE" || true
    if "$VENV/bin/pip" install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE"; then
        ok "  pip (venv): dependências actualizadas"
    else
        warn "  pip install falhou (alguns pacotes podem estar em falta)"
    fi
elif command -v pip3 &>/dev/null; then
    pip3 install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE" || true
else
    warn "  pip não encontrado — cria o venv: python3 -m venv $VENV"
fi

# ─── STEP 4: Verificar e corrigir .env ──────────────────────────────────────────
info "[4/10] A verificar .env..."
if [[ ! -f "$ENV_FILE" ]]; then
    warn "  .env não encontrado — a criar mínimo funcional..."
    cat > "$ENV_FILE" <<MINENV
NEXUS_HOME=/opt/nexus
NEXUS_API_KEY=nexus-change-me
AUTOMATION_API_KEY=
LOG_DIR=/var/log/nexus
API_HOST=0.0.0.0
API_PORT=8000
NEXUS_API_URL=http://localhost:8000
WS_HOST=0.0.0.0
WS_PORT=8801
DASHBOARD_PORT=9000
MINENV
    chmod 640 "$ENV_FILE"
    ok "  .env criado"
else
    ok "  .env existe"
fi
# Fix WS_PORT: 8001 → 8801
if grep -q 'WS_PORT=8001' "$ENV_FILE" 2>/dev/null; then
    sed -i 's/WS_PORT=8001/WS_PORT=8801/g' "$ENV_FILE"
    ok "  .env: WS_PORT corrigido de 8001 → 8801"
elif ! grep -q 'WS_PORT' "$ENV_FILE" 2>/dev/null; then
    echo 'WS_PORT=8801' >> "$ENV_FILE"
fi
# Fix API_PORT: deve ser 8000
if grep -q 'API_PORT=' "$ENV_FILE" 2>/dev/null; then
    _ap=$(grep 'API_PORT=' "$ENV_FILE" | cut -d= -f2 | head -1 | tr -d "\"'" | xargs)
    if [[ "$_ap" != "8000" ]]; then
        sed -i "s/API_PORT=.*/API_PORT=8000/g" "$ENV_FILE"
        ok "  .env: API_PORT corrigido para 8000 (era $_ap)"
    else
        ok "  .env: API_PORT=8000 (ok)"
    fi
else
    echo 'API_PORT=8000' >> "$ENV_FILE"
    ok "  .env: API_PORT=8000 adicionado"
fi
# Garantir NEXUS_API_URL
if ! grep -q 'NEXUS_API_URL=' "$ENV_FILE" 2>/dev/null; then
    echo 'NEXUS_API_URL=http://localhost:8000' >> "$ENV_FILE"
    ok "  .env: NEXUS_API_URL adicionado"
else
    ok "  .env: NEXUS_API_URL existe"
fi

# ─── STEP 5: Criar directorios necessários ─────────────────────────────────────────
info "[5/10] A criar directorios..."
for d in "$NEXUS_HOME/logs" "$NEXUS_HOME/monitor" "$NEXUS_HOME/backups" "$NEXUS_HOME/data"; do
    mkdir -p "$d" 2>/dev/null && ok "  $d" || true
done
# /var/log/nexus: criar E dar permissões ao utilizador nexus
mkdir -p /var/log/nexus 2>/dev/null || true
chown -R nexus:nexus /var/log/nexus 2>/dev/null || \
    chmod 777 /var/log/nexus 2>/dev/null || true
ok "  /var/log/nexus (com permissões)"

# ─── STEP 6: Corrigir ficheiros de serviço systemd ───────────────────────────────
info "[6/10] A corrigir serviços systemd..."

if [[ -f "$VENV/bin/uvicorn" ]]; then
    UVICORN="$VENV/bin/uvicorn"
else
    UVICORN=$(command -v uvicorn 2>/dev/null || echo "uvicorn")
fi
ok "  Uvicorn: $UVICORN"

SVC_USER="nexus"
if ! id -u "$SVC_USER" &>/dev/null; then
    SVC_USER=$(stat -c '%U' "$NEXUS_HOME" 2>/dev/null || echo root)
    warn "  Utilizador 'nexus' não existe — a usar '$SVC_USER'"
fi

# Remover serviços obsoletos
for obsolete in nexus-api nexus-ws nexus-backend; do
    systemctl disable "$obsolete" 2>/dev/null || true
    rm -f "$SVC_DIR/${obsolete}.service" 2>/dev/null || true
done
ok "  Serviços obsoletos removidos (nexus-api, nexus-ws, nexus-backend)"

cat > "$SVC_DIR/nexus-core.service" <<SVC_CORE
[Unit]
Description=NEXUS AI — REST API (porta 8000)
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
ExecStart=$UVICORN nexus.api_server:app --host 0.0.0.0 --port 8000 --log-level info
Restart=always
RestartSec=10
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-core

[Install]
WantedBy=multi-user.target
SVC_CORE
ok "  nexus-core.service: actualizado (nexus.api_server:app em :8000)"

systemctl daemon-reload
systemctl enable nexus-core 2>/dev/null || true
if [[ -f "$SVC_DIR/nexus-dashboard.service" ]]; then
    systemctl enable nexus-dashboard 2>/dev/null || true
fi

# ─── STEP 6.5: Teste de importação (diagnóstico antes de arrancar) ──────────────
info "[6.5] Teste de importação Python..."
PYTHON="${VENV}/bin/python"
[[ -f "$PYTHON" ]] || PYTHON=$(command -v python3)

# Testar nexus.api_server (entry point resiliente — DEVE sempre funcionar)
if "$PYTHON" -c "
import sys
sys.path.insert(0, '$NEXUS_HOME')
from nexus.api_server import app, _import_error
if _import_error:
    print(f'[WARN] nexus.api_server em modo MINIMO: {_import_error}')
else:
    print('[OK] nexus.api_server carregado em modo COMPLETO')
" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  nexus.api_server: import OK (modo completo ou mínimo)"
else
    fail "  nexus.api_server: FALHOU! Isto não devia acontecer."
fi

# Testar nexus.api.rest.main directamente para diagnóstico
FULL_IMPORT_RESULT=$(
    "$PYTHON" -c "
import sys
sys.path.insert(0, '$NEXUS_HOME')
try:
    from nexus.api.rest.main import app
    print('FULL_API_OK')
except Exception as e:
    import traceback
    print(f'FULL_API_FAIL: {type(e).__name__}: {e}')
    traceback.print_exc()
" 2>&1
)
echo "$FULL_IMPORT_RESULT" | tee -a "$LOG_FILE"
if echo "$FULL_IMPORT_RESULT" | grep -q 'FULL_API_OK'; then
    ok "  nexus.api.rest.main: import OK (modo COMPLETO)"
elif echo "$FULL_IMPORT_RESULT" | grep -q 'FULL_API_FAIL'; then
    FAIL_REASON=$(echo "$FULL_IMPORT_RESULT" | grep 'FULL_API_FAIL' | head -1)
    warn "  nexus.api.rest.main: import FALHOU ($FAIL_REASON)"
    warn "  nexus-core vai arrancar em modo MÍNIMO mas com /health funcional"
    warn "  Para ver o erro completo: journalctl -u nexus-core -n 50 --no-pager"
fi

# ─── STEP 7: Iniciar serviços ────────────────────────────────────────────────────
info "[7/10] A iniciar serviços..."

systemctl start nexus-core 2>/dev/null || true
sleep 6
if systemctl is-active --quiet nexus-core; then
    ok "  nexus-core: ACTIVE"
    HC=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || echo "")
    if echo "$HC" | grep -q '"status"'; then
        if echo "$HC" | grep -q '"degraded"'; then
            warn "  /health responde em modo MÍNIMO: $HC"
            warn "  Causa do modo mínimo está em /health acima"
        else
            ok "  /health responde: $HC"
        fi
    else
        fail "  /health sem resposta (port bind falhou?)"
        journalctl -u nexus-core -n 30 --no-pager 2>/dev/null | tail -20 | tee -a "$LOG_FILE" || true
    fi
else
    fail "  nexus-core: não ficou activo"
    journalctl -u nexus-core -n 30 --no-pager 2>/dev/null | tail -20 | tee -a "$LOG_FILE" || true
fi

if [[ -f "$SVC_DIR/nexus-dashboard.service" ]]; then
    systemctl start nexus-dashboard 2>/dev/null || true
    sleep 3
    if systemctl is-active --quiet nexus-dashboard; then
        ok "  nexus-dashboard: ACTIVE (:9000)"
    else
        fail "  nexus-dashboard: não ficou activo"
        journalctl -u nexus-dashboard -n 10 --no-pager 2>/dev/null | tail -8 | tee -a "$LOG_FILE" || true
    fi
fi

# ─── STEP 8: Rebuild do dashboard ───────────────────────────────────────────────
info "[8/10] Rebuild do dashboard..."
VPS_IP=$(
    curl -s --max-time 5 https://api.ipify.org 2>/dev/null ||
    curl -s --max-time 5 https://ifconfig.me 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{print $1}'
)
[[ -z "$VPS_IP" ]] && VPS_IP="35.241.151.115"
ok "  IP detectado: $VPS_IP"

if bash "$NEXUS_HOME/nexus/scripts/rebuild_dashboard.sh" "$VPS_IP" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Dashboard rebuild OK"
else
    warn "  Dashboard rebuild falhou — a continuar"
fi

# ─── STEP 9: Health check ─────────────────────────────────────────────────────
info "[9/10] Health check..."
sleep 3
bash "$NEXUS_HOME/nexus/scripts/health_check.sh" 2>&1 | tee -a "$LOG_FILE" || true

# ─── STEP 10: Sumário final ──────────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
info "[10/10] Sumário final"
echo "" | tee -a "$LOG_FILE"

for svc in nexus-core nexus-dashboard; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "n/a")
    [[ "$status" == "active" ]] && ok "  $svc: $status" || warn "  $svc: $status"
done
echo ""

for entry in "8000:REST API" "9000:Dashboard"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    ss -tulpn 2>/dev/null | grep -q ":${PORT}" && ok "  :$PORT ($LABEL): ABERTO" || fail "  :$PORT ($LABEL): FECHADO"
done
echo ""

API_RESP=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || echo "")
if echo "$API_RESP" | grep -q '"status"'; then
    if echo "$API_RESP" | grep -q '"degraded"'; then
        warn "  :8000/health → MODO MÍNIMO (ver 'error' abaixo)"
        echo "  $API_RESP"
        echo ""
        warn "  DIAGNÓSTICO: o erro acima explica porque nexus.api.rest.main falhou."
        warn "  Fix: corre 'journalctl -u nexus-core -n 50 --no-pager' para ver traceback completo."
    else
        ok "  :8000/health → $API_RESP"
    fi
else
    fail "  :8000/health → sem resposta"
    journalctl -u nexus-core -n 20 --no-pager 2>/dev/null | tail -15 | tee -a "$LOG_FILE" || true
fi

PROXY_RESP=$(curl -s --max-time 5 http://localhost:9000/api/health 2>/dev/null || echo "")
if echo "$PROXY_RESP" | grep -q '"status"'; then
    ok "  :9000/api/health → proxy OK"
else
    fail "  :9000/api/health → proxy falhou"
fi

DASH_RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -1 || echo "")
echo "$DASH_RESP" | grep -qi '<!doctype\|<html' && ok "  :9000/ → HTML OK" || fail "  :9000/ → sem HTML"

echo ""
echo "  Log completo: $LOG_FILE"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Dashboard : http://${VPS_IP}:9000"
echo -e "  API proxy : http://${VPS_IP}:9000/api/health"
echo -e "  WS proxy  : ws://${VPS_IP}:9000/ws"
echo -e "  Diagnóstico erros: journalctl -u nexus-core -n 50 --no-pager"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
