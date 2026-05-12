#!/usr/bin/env bash
# rebuild_dashboard.sh — Cria .env do frontend com IP do VPS e reconstrói o bundle
# Uso: sudo bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh [IP_DO_VPS]
# Exemplo: sudo bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh 35.241.151.115

set -uo pipefail

NEXUS_HOME="/opt/nexus"
FRONTEND="$NEXUS_HOME/nexus/dashboard/frontend"
BACKEND_ENV="$NEXUS_HOME/.env"
VPS_IP="${1:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
fail() { echo -e "${RED}✘ $*${NC}"; }
info() { echo -e "${BLUE}▸ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS Dashboard Rebuild (frontend .env + build)  ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# ── 1. Detectar IP do VPS ──────────────────────────────────────────────
info "[1] A detectar IP do VPS..."

if [[ -z "$VPS_IP" ]]; then
    # Tentar ler do .env do backend
    if [[ -f "$BACKEND_ENV" ]]; then
        _env_ip=$(grep -E "^(VPS_IP|API_HOST|HOST)=" "$BACKEND_ENV" 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'" | tr -d ' ')
        if [[ -n "$_env_ip" && "$_env_ip" != "0.0.0.0" && "$_env_ip" != "localhost" ]]; then
            VPS_IP="$_env_ip"
        fi
    fi
fi

if [[ -z "$VPS_IP" || "$VPS_IP" == "0.0.0.0" || "$VPS_IP" == "localhost" ]]; then
    # Auto-detectar IP público da máquina
    VPS_IP=$(
        curl -s --max-time 5 https://api.ipify.org 2>/dev/null ||
        curl -s --max-time 5 https://ifconfig.me 2>/dev/null ||
        hostname -I 2>/dev/null | awk '{print $1}'
    )
fi

if [[ -z "$VPS_IP" ]]; then
    fail "Não foi possível detectar o IP do VPS."
    fail "Usa: sudo bash rebuild_dashboard.sh <IP_DO_VPS>"
    fail "Exemplo: sudo bash rebuild_dashboard.sh 35.241.151.115"
    exit 1
fi

ok "IP do VPS: $VPS_IP"

# Ler portas do .env (com defaults)
API_PORT="8000"
WS_PORT="8001"
if [[ -f "$BACKEND_ENV" ]]; then
    _p=$(grep -E "^API_PORT=" "$BACKEND_ENV" 2>/dev/null | cut -d= -f2 | tr -d '"')
    _w=$(grep -E "^WS_PORT=" "$BACKEND_ENV" 2>/dev/null | cut -d= -f2 | tr -d '"')
    [[ -n "$_p" ]] && API_PORT="$_p"
    [[ -n "$_w" ]] && WS_PORT="$_w"
fi

VITE_API_URL="http://${VPS_IP}:${API_PORT}"
VITE_WS_URL="ws://${VPS_IP}:${WS_PORT}"

ok "VITE_API_URL = $VITE_API_URL"
ok "VITE_WS_URL  = $VITE_WS_URL"

# ── 2. Verificar frontend ───────────────────────────────────────────────────
info "[2] A verificar directoria frontend..."
if [[ ! -f "$FRONTEND/package.json" ]]; then
    fail "package.json não encontrado: $FRONTEND"
    exit 1
fi
ok "package.json: $FRONTEND/package.json"

# ── 3. Criar .env do frontend com URLs correctos ─────────────────────────────
info "[3] A criar $FRONTEND/.env..."
cat > "$FRONTEND/.env" <<ENVEOF
# Gerado por rebuild_dashboard.sh em $(date)
# IMPORTANTE: estas variáveis são injectadas no bundle em tempo de build (Vite).
# Mudar o ficheiro sem correr 'npm run build' nao tem efeito no dashboard.
VITE_API_URL=${VITE_API_URL}
VITE_WS_URL=${VITE_WS_URL}
ENVEOF
ok ".env criado:"
cat "$FRONTEND/.env"
echo ""

# ── 4. Verificar Node.js e npm ───────────────────────────────────────────────
info "[4] A verificar Node.js e npm..."
if ! command -v node &>/dev/null; then
    warn "Node.js não encontrado — a instalar Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>/dev/null
    apt-get install -y nodejs 2>/dev/null
fi
ok "Node.js: $(node --version 2>&1)"
ok "npm:     $(npm --version 2>&1)"

# ── 5. npm install ────────────────────────────────────────────────────────────────
info "[5] npm install..."
cd "$FRONTEND"
npm install --prefer-offline 2>&1 | tail -5
ok "Dependências OK"

# ── 6. npm run build ───────────────────────────────═────────────────────────────
info "[6] npm run build..."
if ! npm run build; then
    fail "npm run build falhou"
    exit 1
fi
ok "Build concluída!"
echo "  Bundle em: $FRONTEND/dist/"
ls -lh "$FRONTEND/dist/" 2>/dev/null | grep -v "^total" | head -8 || true

# Verificar que o bundle tem a URL correcta
if grep -r "$VPS_IP" "$FRONTEND/dist/" &>/dev/null; then
    ok "IP $VPS_IP confirmado no bundle"
else
    warn "IP $VPS_IP não encontrado no bundle — verifica o .env"
fi

# ── 7. Reiniciar nexus-dashboard ─────────────────────────────────────────────
info "[7] A reiniciar nexus-dashboard..."
if systemctl restart nexus-dashboard 2>/dev/null; then
    ok "nexus-dashboard reiniciado"
else
    warn "nexus-dashboard não existe como serviço (dashboard server pode estar integrado no backend)"
fi
sleep 2

# ── 8. Validação ───────────────────────────────────────────────────────────────
info "[8] Validação das portas..."
echo ""
for entry in "8000:nexus-backend (API)" "8001:nexus-ws (WebSocket)" "9000:nexus-dashboard"; do
    PORT="${entry%%:*}"
    LABEL="${entry##*:}"
    if ss -tulpn 2>/dev/null | grep -q ":${PORT}"; then
        ok "Porta $PORT ($LABEL): ABERTA"
    else
        warn "Porta $PORT ($LABEL): FECHADA"
    fi
done

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
echo "Dashboard: http://${VPS_IP}:9000"
echo ""
echo "O browser vai agora ligar a:"
echo "  API : $VITE_API_URL"
echo "  WS  : $VITE_WS_URL"
echo ""
echo "Se ainda mostrar 'WS offline', limpa a cache do browser (Ctrl+Shift+R)"
echo "e verifica no DevTools (F12 > Console) se há erros de conexão."
echo ""
