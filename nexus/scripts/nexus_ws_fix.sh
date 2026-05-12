#!/usr/bin/env bash
# nexus_ws_fix.sh — Cria nexus-ws.service (WebSocket independente, porta 8001)
# Não depende de main.py nem do event loop do nexus-backend.
# Uso: sudo bash /opt/nexus/nexus/scripts/nexus_ws_fix.sh

set -uo pipefail

NEXUS_HOME="/opt/nexus"
VENV="$NEXUS_HOME/venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
WS_PY="$NEXUS_HOME/nexus/ws_server.py"
SVC="/etc/systemd/system/nexus-ws.service"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
fail() { echo -e "${RED}✘ $*${NC}"; }
info() { echo -e "${BLUE}▸ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS WebSocket Fix  —  nexus-ws.service        ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# ── 0. Diagnóstico inicial (detecta qual main.py está a correr) ─────────────
info "[0] Diagnóstico..."
echo ""
echo -e "${YELLOW}=== ExecStart do nexus-backend ===${NC}"
grep -i "execstart" /etc/systemd/system/nexus-backend.service 2>/dev/null \
  || warn "nexus-backend.service não encontrado"
echo ""
echo -e "${YELLOW}=== git log -3 ===${NC}"
cd "$NEXUS_HOME" && git log --oneline -3 2>/dev/null || warn "não é um repo git"
echo ""
echo -e "${YELLOW}=== main.py primeiras 10 linhas ===${NC}"
head -10 "$NEXUS_HOME/nexus/main.py" 2>/dev/null || warn "main.py não encontrado"
echo ""
echo -e "${YELLOW}=== ws_server.py existe? ===${NC}"
ls -lh "$WS_PY" 2>/dev/null || warn "ws_server.py NÃO encontrado em $WS_PY"
echo ""

# ── 1. Verificar venv ─────────────────────────────────────────────────────
info "[1] Python/venv..."
if [[ ! -x "$PY" ]]; then
    fail "venv não encontrado: $PY"
    fail "Corre primeiro nexus_fix.sh para criar o venv"
    exit 1
fi
ok "$( "$PY" --version 2>&1 )  ($PY)"

# ── 2. Garantir websockets no venv ─────────────────────────────────────
info "[2] websockets no venv..."
"$PIP" install "websockets==10.4" -q
WS_VER=$( "$PY" -c "import websockets; print(websockets.__version__)" 2>&1 ) \
  || { fail "websockets não importável"; exit 1; }
ok "websockets $WS_VER"

# ── 3. Limpar __pycache__ (evita .pyc obsoletos) ──────────────────────────
info "[3] A limpar __pycache__..."
find "$NEXUS_HOME" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$NEXUS_HOME" -name "*.pyc" -delete 2>/dev/null || true
ok "Cache limpa"

# ── 4. Teste directo websockets.serve() ─────────────────────────────────
info "[4] Teste directo websockets.serve() na porta 18099..."

# Libertar porta de teste se ocupada
if command -v fuser &>/dev/null; then
    fuser -k 18099/tcp 2>/dev/null || true
    sleep 0.5
fi

TEST_OUT=$( timeout 5 "$PY" - 2>&1 <<'PYEOF' || echo "TIMEOUT_OU_ERRO" )
import asyncio, sys

async def run():
    try:
        import websockets
        print(f"websockets={websockets.__version__} python={sys.executable}")
        async def handler(ws):
            try:
                await ws.close()
            except Exception:
                pass
        async with websockets.serve(handler, "0.0.0.0", 18099):
            print("WEBSOCKETS_OK")
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"WEBSOCKETS_FALHOU: {type(e).__name__}: {e}")

asyncio.run(run())
PYEOF

echo "  Saida do teste: $TEST_OUT"
if echo "$TEST_OUT" | grep -q "WEBSOCKETS_OK"; then
    ok "websockets.serve() funciona no venv"
else
    fail "websockets.serve() falhou ou deu timeout"
    fail "O venv não consegue abrir sockets WebSocket"
    echo "  Verifica permissões, conflito de portas, ou versão do websockets"
    exit 1
fi

# ── 5. Parar nexus-ws existente + libertar 8001 ───────────────────────────
info "[5] A parar nexus-ws e a libertar porta 8001..."
systemctl stop nexus-ws 2>/dev/null && ok "nexus-ws parado" || ok "nexus-ws não estava activo"
sleep 1
if command -v fuser &>/dev/null; then
    fuser -k 8001/tcp 2>/dev/null && warn "Processo na porta 8001 terminado" || true
    sleep 1
fi

# ── 6. Criar nexus-ws.service ────────────────────────────────────────────────
info "[6] A criar nexus-ws.service..."
cat > "$SVC" <<SVCEOF
[Unit]
Description=NEXUS WebSocket Server (porta 8001)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$NEXUS_HOME
Environment=PYTHONPATH=$NEXUS_HOME
Environment=WS_HOST=0.0.0.0
Environment=WS_PORT=8001
EnvironmentFile=-$NEXUS_HOME/.env
ExecStart=$PY $WS_PY
Restart=always
RestartSec=3
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
ok "nexus-ws.service criado"
echo "  ExecStart: $PY $WS_PY"

# ── 7. Activar e arrancar ─────────────────────────────────────────────────
info "[7] A activar e arrancar nexus-ws..."
systemctl daemon-reload
systemctl enable nexus-ws
systemctl start nexus-ws
echo "  A aguardar 4 segundos..."
sleep 4

# ── 8. Abrir firewall (se ufw activo) ─────────────────────────────────────
if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    info "[8] A abrir porta 8001 no ufw..."
    ufw allow 8001/tcp comment "NEXUS WebSocket" 2>/dev/null && ok "ufw: 8001/tcp aberto" || warn "ufw falhou"
else
    info "[8] ufw inactivo — sem regras de firewall"
fi

# ── 9. Validação ──────────────────────────────────────────────────────────
info "[9] Validação..."
echo ""
if ss -tulpn 2>/dev/null | grep -q ":8001"; then
    ok "PORTA 8001 ABERTA!"
    ss -tulpn | grep ":8001"
else
    fail "Porta 8001 ainda fechada"
    echo ""
    warn "Logs nexus-ws (últimas 30 linhas):"
    journalctl -u nexus-ws -n 30 --no-pager 2>/dev/null || true
fi

# ── 10. Estado final ────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}── Estado dos serviços ────────────────────────────────${NC}"
for svc_info in "nexus-ws:8001" "nexus-backend:8000" "nexus-dashboard:9000"; do
    SVC_NAME="${svc_info%%:*}"
    SVC_PORT="${svc_info##*:}"
    STATUS=$( systemctl is-active "$SVC_NAME" 2>/dev/null || echo "inativo" )
    if [[ "$STATUS" == "active" ]]; then
        ok "$SVC_NAME (porta $SVC_PORT): RUNNING"
    else
        warn "$SVC_NAME (porta $SVC_PORT): $STATUS"
    fi
done

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
echo "Logs WS em tempo real:"
echo "  journalctl -u nexus-ws -f"
echo ""
