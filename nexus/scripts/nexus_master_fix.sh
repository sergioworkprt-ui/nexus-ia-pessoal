#!/usr/bin/env bash
# nexus_master_fix.sh — Reparacao completa do NEXUS no VPS
# Uso: sudo bash /opt/nexus/nexus/scripts/nexus_master_fix.sh
#
# ARQUITECTURA:
#   Porto 8000 — nexus-core : REST API (uvicorn nexus.api_server:app)
#   Porto 9000 — nexus-dashboard : dashboard React + proxy /api/* e /ws
set -uo pipefail

# ── Auto-copia para /tmp: imune a git reset --hard no Step 2 ──────────────────
# O bash le scripts em blocos (~8KB). O git reset --hard no Step 2 substitui
# este ficheiro no disco; o bash le o bloco seguinte da versao nova e falha.
# Copiando para /tmp antes de qualquer execucao, o git pull nunca afecta a
# execucao em curso. _NEXUS_COPY exportado evita loop infinito.
if [[ -z "${_NEXUS_COPY:-}" ]]; then
    _TMP=$(mktemp /tmp/nexus_fix_XXXXXX.sh)
    cp "$0" "$_TMP"
    chmod 700 "$_TMP"
    export _NEXUS_COPY=1
    exec bash "$_TMP" "$@"
fi

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
  echo "======================================================="
  echo "  NEXUS Master Fix -- $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "======================================================="
} | tee -a "$LOG_FILE"

# --- STEP 1: Parar todos os servicos ----------------------------------------
info "[1/10] A parar servicos NEXUS..."
for svc in nexus-core nexus-api nexus-ws nexus-dashboard nexus-backend; do
    if systemctl is-active --quiet "$svc" 2>/dev/null || \
       systemctl is-failed --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc" 2>/dev/null && ok "  $svc parado" || warn "  $svc: erro ao parar"
    else
        warn "  $svc ja estava inactivo"
    fi
done
if ss -tulpn 2>/dev/null | grep -q ':8000'; then
    warn "  Porto 8000 ainda em uso apos stop! A matar processo..."
    fuser -k 8000/tcp 2>/dev/null || true
    sleep 2
    ss -tulpn 2>/dev/null | grep -q ':8000' && fail "  Porto 8000 AINDA em uso" || ok "  Porto 8000 livre"
else
    ok "  Porto 8000 livre"
fi
if ss -tulpn 2>/dev/null | grep -q ':9000'; then
    warn "  Porto 9000 ainda em uso apos stop! A matar processo..."
    fuser -k 9000/tcp 2>/dev/null || true
    sleep 2
    ss -tulpn 2>/dev/null | grep -q ':9000' && fail "  Porto 9000 AINDA em uso" || ok "  Porto 9000 livre"
else
    ok "  Porto 9000 livre"
fi

# --- STEP 2: git pull --------------------------------------------------------
info "[2/10] git pull ($BRANCH)..."
cd "$NEXUS_HOME"
if git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" && \
   git reset --hard "origin/$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  Codigo actualizado: $(git rev-parse --short HEAD)"
else
    warn "  git pull falhou -- a continuar com codigo actual"
fi

# --- STEP 3: Actualizar dependencias Python ----------------------------------
info "[3/10] Actualizar dependencias Python..."
REQ="$NEXUS_HOME/nexus/requirements.txt"
if [[ -f "$VENV/bin/pip" ]]; then
    PYTHON="$VENV/bin/python"
    "$VENV/bin/pip" install --upgrade pip -q 2>&1 | tail -1 | tee -a "$LOG_FILE" || true
    if "$VENV/bin/pip" install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE"; then
        ok "  pip (venv): dependencias actualizadas"
    else
        warn "  pip install falhou (alguns pacotes podem estar em falta)"
    fi
elif command -v pip3 &>/dev/null; then
    PYTHON=$(command -v python3)
    pip3 install -r "$REQ" -q 2>&1 | tee -a "$LOG_FILE" || true
else
    PYTHON=$(command -v python3)
    warn "  pip nao encontrado -- cria o venv: python3 -m venv $VENV"
fi

# --- STEP 3.5: Ferramentas de analise de video --------------------------------
info "[3.5] Ferramentas de analise de video (ffmpeg + whisper + dirs)..."

# ffmpeg -- necessario para yt-dlp extrair audio para whisper
if command -v ffmpeg &>/dev/null; then
    ok "  ffmpeg: ja instalado"
else
    info "  A instalar ffmpeg via apt..."
    if apt-get install -y ffmpeg -q 2>&1 | tail -3 | tee -a "$LOG_FILE"; then
        ok "  ffmpeg instalado"
    else
        warn "  ffmpeg: apt install falhou (opcional -- so necessario para whisper)"
    fi
fi

# yt-dlp -- actualizar para versao mais recente
if [[ -f "$VENV/bin/pip" ]]; then
    "$VENV/bin/pip" install --upgrade yt-dlp -q 2>&1 | tail -1 | tee -a "$LOG_FILE" || true
    ok "  yt-dlp: actualizado"
fi

# openai-whisper -- instalacao OPCIONAL com verificacao de espaco em disco
# Nao esta em requirements.txt porque torch pesa ~2GB e pode encher o disco
if "$PYTHON" -c "import whisper" 2>/dev/null; then
    ok "  openai-whisper: ja instalado"
else
    _DISK_FREE_GB=$(df -BG "$NEXUS_HOME" 2>/dev/null | awk 'NR==2{gsub(/G/,""); print $4}' | head -1)
    _DISK_FREE_GB="${_DISK_FREE_GB:-0}"
    info "  Espaco livre em disco: ${_DISK_FREE_GB}GB"
    if [[ "$_DISK_FREE_GB" -ge 3 ]]; then
        info "  A instalar openai-whisper (pode demorar -- inclui torch CPU)..."
        if [[ -f "$VENV/bin/pip" ]]; then
            if "$VENV/bin/pip" install openai-whisper -q 2>&1 | tail -3 | tee -a "$LOG_FILE"; then
                ok "  openai-whisper instalado"
            else
                warn "  openai-whisper: falhou (videos sem legendas nao serao transcritos)"
            fi
        fi
    else
        warn "  openai-whisper: SALTADO -- apenas ${_DISK_FREE_GB}GB livres (precisa >=3GB para torch)"
        warn "  Para instalar manualmente quando houver espaco: pip install openai-whisper"
    fi
fi

# Criar directorios de video com permissoes
for d in "$NEXUS_HOME/data/video" "$NEXUS_HOME/data/video/transcripts" "$NEXUS_HOME/data/video/metadata"; do
    mkdir -p "$d" 2>/dev/null && ok "  $d" || true
done
_DATA_OWNER=$(stat -c '%U' "$NEXUS_HOME" 2>/dev/null || echo root)
chown -R "$_DATA_OWNER":"$_DATA_OWNER" "$NEXUS_HOME/data" 2>/dev/null || \
    chmod -R 777 "$NEXUS_HOME/data" 2>/dev/null || true
ok "  Permissoes data/video/ OK"

# --- STEP 4: Verificar e corrigir .env ---------------------------------------
info "[4/10] A verificar .env..."
if [[ ! -f "$ENV_FILE" ]]; then
    warn "  .env nao encontrado -- a criar minimo funcional..."
    cat > "$ENV_FILE" <<'MINENV'
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

if grep -q 'WS_PORT=8001' "$ENV_FILE" 2>/dev/null; then
    sed -i 's/WS_PORT=8001/WS_PORT=8801/g' "$ENV_FILE"
    ok "  .env: WS_PORT corrigido 8001->8801"
elif ! grep -q 'WS_PORT' "$ENV_FILE" 2>/dev/null; then
    echo 'WS_PORT=8801' >> "$ENV_FILE"
    ok "  .env: WS_PORT=8801 adicionado"
else
    ok "  .env: WS_PORT=8801 (ok)"
fi

if grep -q 'API_PORT=' "$ENV_FILE" 2>/dev/null; then
    _ap=$(grep 'API_PORT=' "$ENV_FILE" | cut -d= -f2 | head -1 | tr -d '"' | tr -d "'" | xargs)
    if [[ "$_ap" != "8000" ]]; then
        sed -i 's/API_PORT=.*/API_PORT=8000/g' "$ENV_FILE"
        ok "  .env: API_PORT corrigido para 8000 (era $_ap)"
    else
        ok "  .env: API_PORT=8000 (ok)"
    fi
else
    echo 'API_PORT=8000' >> "$ENV_FILE"
    ok "  .env: API_PORT=8000 adicionado"
fi

if ! grep -q 'NEXUS_API_URL=' "$ENV_FILE" 2>/dev/null; then
    echo 'NEXUS_API_URL=http://localhost:8000' >> "$ENV_FILE"
    ok "  .env: NEXUS_API_URL adicionado"
else
    ok "  .env: NEXUS_API_URL existe"
fi

# --- STEP 5: Criar directorios -----------------------------------------------
info "[5/10] A criar directorios..."
for d in "$NEXUS_HOME/logs" "$NEXUS_HOME/monitor" "$NEXUS_HOME/backups" "$NEXUS_HOME/data"; do
    mkdir -p "$d" 2>/dev/null && ok "  $d" || true
done
mkdir -p /var/log/nexus 2>/dev/null || true
chown -R nexus:nexus /var/log/nexus 2>/dev/null || chmod 777 /var/log/nexus 2>/dev/null || true
ok "  /var/log/nexus (com permissoes)"

# --- STEP 6: Servicos systemd ------------------------------------------------
info "[6/10] A corrigir servicos systemd..."

if [[ -f "$VENV/bin/uvicorn" ]]; then
    UVICORN="$VENV/bin/uvicorn"
else
    UVICORN=$(command -v uvicorn 2>/dev/null || echo "uvicorn")
fi
ok "  Uvicorn: $UVICORN"

SVC_USER="nexus"
if ! id -u "$SVC_USER" &>/dev/null; then
    SVC_USER=$(stat -c '%U' "$NEXUS_HOME" 2>/dev/null || echo root)
    warn "  Utilizador nexus nao existe -- a usar $SVC_USER"
fi

for obsolete in nexus-api nexus-ws nexus-backend; do
    systemctl disable "$obsolete" 2>/dev/null || true
    rm -f "$SVC_DIR/${obsolete}.service" 2>/dev/null || true
done
ok "  Servicos obsoletos removidos"

# Gerar nexus-core.service
{
    echo '[Unit]'
    echo 'Description=NEXUS AI -- REST API (porta 8000)'
    echo 'After=network-online.target'
    echo 'Wants=network-online.target'
    echo ''
    echo '[Service]'
    echo 'Type=simple'
    echo "User=$SVC_USER"
    echo "Group=$SVC_USER"
    echo "WorkingDirectory=$NEXUS_HOME"
    echo "EnvironmentFile=-$ENV_FILE"
    echo "Environment=PYTHONPATH=$NEXUS_HOME"
    echo 'Environment=LOG_DIR=/var/log/nexus'
    echo "ExecStart=$UVICORN nexus.api_server:app --host 0.0.0.0 --port 8000 --log-level info"
    echo 'Restart=always'
    echo 'RestartSec=10'
    echo 'StartLimitIntervalSec=0'
    echo 'StandardOutput=journal'
    echo 'StandardError=journal'
    echo 'SyslogIdentifier=nexus-core'
    echo ''
    echo '[Install]'
    echo 'WantedBy=multi-user.target'
} > "$SVC_DIR/nexus-core.service"
ok "  nexus-core.service gerado"

# Gerar nexus-dashboard.service (sempre regenerado -- ExecStart correcto)
{
    echo '[Unit]'
    echo 'Description=NEXUS Dashboard -- frontend React + proxy /api/* e /ws (porta 9000)'
    echo 'After=network-online.target'
    echo 'Wants=network-online.target'
    echo ''
    echo '[Service]'
    echo 'Type=simple'
    echo "User=$SVC_USER"
    echo "Group=$SVC_USER"
    echo "WorkingDirectory=$NEXUS_HOME"
    echo "EnvironmentFile=-$ENV_FILE"
    echo "Environment=PYTHONPATH=$NEXUS_HOME"
    echo 'Environment=LOG_DIR=/var/log/nexus'
    echo 'Environment=NEXUS_API_URL=http://localhost:8000'
    echo "ExecStart=$UVICORN nexus.dashboard.server:app --host 0.0.0.0 --port 9000 --log-level info"
    echo 'Restart=always'
    echo 'RestartSec=10'
    echo 'StartLimitIntervalSec=0'
    echo 'StandardOutput=journal'
    echo 'StandardError=journal'
    echo 'SyslogIdentifier=nexus-dashboard'
    echo ''
    echo '[Install]'
    echo 'WantedBy=multi-user.target'
} > "$SVC_DIR/nexus-dashboard.service"
ok "  nexus-dashboard.service gerado"

systemctl daemon-reload
systemctl enable nexus-core 2>/dev/null || true
systemctl enable nexus-dashboard 2>/dev/null || true

# --- STEP 6.5: Teste de importacao Python ------------------------------------
info "[6.5] Teste de importacao Python..."
[[ -f "$PYTHON" ]] || PYTHON=$(command -v python3)

_PY_TEST=$(mktemp /tmp/nexus_import_test_XXXXXX.py)
cat > "$_PY_TEST" <<'PYEOF'
import sys, os
nexus_home = os.environ.get('NEXUS_HOME', '/opt/nexus')
sys.path.insert(0, nexus_home)
try:
    from nexus.api_server import app, _import_error
    if _import_error:
        print('[WARN] nexus.api_server em modo MINIMO: ' + str(_import_error))
    else:
        print('[OK] nexus.api_server modo COMPLETO')
except Exception as e:
    print('[FAIL] nexus.api_server import falhou: ' + str(e))
PYEOF

if NEXUS_HOME="$NEXUS_HOME" "$PYTHON" "$_PY_TEST" 2>&1 | tee -a "$LOG_FILE"; then
    ok "  nexus.api_server: import OK"
else
    fail "  nexus.api_server: FALHOU"
fi

_PY_FULL=$(mktemp /tmp/nexus_full_test_XXXXXX.py)
cat > "$_PY_FULL" <<'PYEOF'
import sys, os
nexus_home = os.environ.get('NEXUS_HOME', '/opt/nexus')
sys.path.insert(0, nexus_home)
try:
    from nexus.api.rest.main import app
    print('FULL_API_OK')
except Exception as e:
    import traceback
    print('FULL_API_FAIL: ' + type(e).__name__ + ': ' + str(e))
    traceback.print_exc()
PYEOF

FULL_IMPORT_RESULT=$(NEXUS_HOME="$NEXUS_HOME" "$PYTHON" "$_PY_FULL" 2>&1)
echo "$FULL_IMPORT_RESULT" | tee -a "$LOG_FILE"

if echo "$FULL_IMPORT_RESULT" | grep -q 'FULL_API_OK'; then
    ok "  nexus.api.rest.main: OK (modo COMPLETO)"
elif echo "$FULL_IMPORT_RESULT" | grep -q 'FULL_API_FAIL'; then
    FAIL_REASON=$(echo "$FULL_IMPORT_RESULT" | grep 'FULL_API_FAIL' | head -1)
    warn "  nexus.api.rest.main falhou: $FAIL_REASON"
    warn "  nexus-core vai arrancar em modo MINIMO com /health funcional"
fi

# Testar import do dashboard server
_PY_DASH=$(mktemp /tmp/nexus_dash_test_XXXXXX.py)
cat > "$_PY_DASH" <<'PYEOF'
import sys, os
nexus_home = os.environ.get('NEXUS_HOME', '/opt/nexus')
sys.path.insert(0, nexus_home)
try:
    from nexus.dashboard.server import app
    print('DASH_OK')
except Exception as e:
    import traceback
    print('DASH_FAIL: ' + type(e).__name__ + ': ' + str(e))
    traceback.print_exc()
PYEOF

DASH_IMPORT_RESULT=$(NEXUS_HOME="$NEXUS_HOME" "$PYTHON" "$_PY_DASH" 2>&1)
echo "$DASH_IMPORT_RESULT" | tee -a "$LOG_FILE"

if echo "$DASH_IMPORT_RESULT" | grep -q 'DASH_OK'; then
    ok "  nexus.dashboard.server: import OK"
else
    DASH_FAIL=$(echo "$DASH_IMPORT_RESULT" | grep 'DASH_FAIL' | head -1)
    fail "  nexus.dashboard.server: FALHOU -- $DASH_FAIL"
    warn "  nexus-dashboard nao vai conseguir arrancar!"
fi

rm -f "$_PY_TEST" "$_PY_FULL" "$_PY_DASH"

# --- STEP 7: Iniciar servicos ------------------------------------------------
info "[7/10] A iniciar servicos..."

systemctl start nexus-core 2>/dev/null || true
sleep 6
if systemctl is-active --quiet nexus-core; then
    ok "  nexus-core: ACTIVE"
    HC=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || echo "")
    if echo "$HC" | grep -q 'status'; then
        if echo "$HC" | grep -q 'degraded'; then
            warn "  /health modo MINIMO: $HC"
        else
            ok "  /health responde: $HC"
        fi
    else
        fail "  /health sem resposta"
        journalctl -u nexus-core -n 30 --no-pager 2>/dev/null | tail -20 | tee -a "$LOG_FILE" || true
    fi
else
    fail "  nexus-core: nao ficou activo"
    journalctl -u nexus-core -n 30 --no-pager 2>/dev/null | tail -20 | tee -a "$LOG_FILE" || true
fi

# Iniciar nexus-dashboard (sempre -- servico gerado no STEP 6)
systemctl start nexus-dashboard 2>/dev/null || true
sleep 4
if systemctl is-active --quiet nexus-dashboard; then
    ok "  nexus-dashboard: ACTIVE (:9000)"
    DHC=$(curl -s --max-time 5 http://localhost:9000/healthz 2>/dev/null || echo "")
    if echo "$DHC" | grep -q 'dist_exists'; then
        ok "  :9000/healthz responde: $DHC"
    else
        warn "  :9000/healthz sem resposta ainda (dist pode estar em build)"
    fi
else
    fail "  nexus-dashboard: nao ficou activo"
    journalctl -u nexus-dashboard -n 30 --no-pager 2>/dev/null | tail -20 | tee -a "$LOG_FILE" || true
fi

# --- STEP 8: Rebuild do dashboard --------------------------------------------
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
    warn "  Dashboard rebuild falhou -- a continuar"
    info "  nexus-dashboard pode servir frontend antigo ou 503; corre rebuild manualmente:"
    info "  bash $NEXUS_HOME/nexus/scripts/rebuild_dashboard.sh $VPS_IP"
fi

# --- STEP 9: Health check ----------------------------------------------------
info "[9/10] Health check..."
sleep 3
bash "$NEXUS_HOME/nexus/scripts/health_check.sh" 2>&1 | tee -a "$LOG_FILE" || true

# --- STEP 10: Sumario final --------------------------------------------------
echo "" | tee -a "$LOG_FILE"
info "[10/10] Sumario final"
echo "" | tee -a "$LOG_FILE"

for svc in nexus-core nexus-dashboard; do
    _st=$(systemctl is-active "$svc" 2>/dev/null || echo "n/a")
    [[ "$_st" == "active" ]] && ok "  $svc: $_st" || warn "  $svc: $_st"
done
echo ""

for _entry in "8000:REST API" "9000:Dashboard"; do
    _port="${_entry%%:*}"; _label="${_entry##*:}"
    ss -tulpn 2>/dev/null | grep -q ":${_port}" && ok "  :$_port ($_label): ABERTO" || fail "  :$_port ($_label): FECHADO"
done
echo ""

API_RESP=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || echo "")
if echo "$API_RESP" | grep -q 'status'; then
    if echo "$API_RESP" | grep -q 'degraded'; then
        warn "  :8000/health -> MODO MINIMO"
        echo "  $API_RESP"
    else
        ok "  :8000/health -> $API_RESP"
    fi
else
    fail "  :8000/health -> sem resposta"
    journalctl -u nexus-core -n 20 --no-pager 2>/dev/null | tail -15 | tee -a "$LOG_FILE" || true
fi

PROXY_RESP=$(curl -s --max-time 5 http://localhost:9000/api/health 2>/dev/null || echo "")
if echo "$PROXY_RESP" | grep -q 'status'; then
    ok "  :9000/api/health -> proxy OK"
else
    fail "  :9000/api/health -> proxy falhou"
fi

DASH_RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -1 || echo "")
echo "$DASH_RESP" | grep -qi 'doctype\|html' && ok "  :9000/ -> HTML OK" || fail "  :9000/ -> sem HTML"

echo ""
echo "  Log: $LOG_FILE"
echo ""
echo "  Dashboard : http://${VPS_IP}:9000"
echo "  API       : http://${VPS_IP}:9000/api/health"
echo "  WS        : ws://${VPS_IP}:9000/ws"
echo "  Logs core : journalctl -u nexus-core -n 50 --no-pager"
echo "  Logs dash : journalctl -u nexus-dashboard -n 50 --no-pager"
echo ""
echo "  Teste de video via chat:"
echo "  curl -s -X POST http://localhost:8000/chat \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"Analisa este video: https://youtube.com/watch?v=dQw4w9WgXcQ\"}' | python3 -m json.tool"
