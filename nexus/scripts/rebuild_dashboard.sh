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
echo -e "${BLUE}   NEXUS Dashboard Rebuild                         ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# ── 0. Diagnóstico inicial ───────────────────────────────────────────────────
info "[0] Estado actual..."
echo ""
echo -e "${YELLOW}=== dist/ actual ===${NC}"
ls -la "$FRONTEND/dist/" 2>/dev/null || echo "dist/ NAO EXISTE"
echo ""
echo -e "${YELLOW}=== dist/index.html actual ===${NC}"
cat "$FRONTEND/dist/index.html" 2>/dev/null || echo "index.html NAO EXISTE"
echo ""
echo -e "${YELLOW}=== ExecStart do nexus-dashboard ===${NC}"
grep -i execstart /etc/systemd/system/nexus-dashboard.service 2>/dev/null || echo "nexus-dashboard.service nao encontrado"
echo ""

# ── 1. Detectar IP do VPS ──────────────────────────────────────────────
info "[1] A detectar IP do VPS..."

if [[ -z "$VPS_IP" ]]; then
    if [[ -f "$BACKEND_ENV" ]]; then
        _env_ip=$(grep -E "^(VPS_IP|API_HOST|HOST)=" "$BACKEND_ENV" 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'" | tr -d ' ')
        if [[ -n "$_env_ip" && "$_env_ip" != "0.0.0.0" && "$_env_ip" != "localhost" ]]; then
            VPS_IP="$_env_ip"
        fi
    fi
fi

if [[ -z "$VPS_IP" || "$VPS_IP" == "0.0.0.0" || "$VPS_IP" == "localhost" ]]; then
    VPS_IP=$(
        curl -s --max-time 5 https://api.ipify.org 2>/dev/null ||
        curl -s --max-time 5 https://ifconfig.me 2>/dev/null ||
        hostname -I 2>/dev/null | awk '{print $1}'
    )
fi

if [[ -z "$VPS_IP" ]]; then
    fail "Não foi possível detectar o IP."
    fail "Usa: sudo bash rebuild_dashboard.sh <IP>"
    exit 1
fi

ok "IP: $VPS_IP"

API_PORT="8000"; WS_PORT="8001"
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
info "[2] A verificar package.json..."
[[ -f "$FRONTEND/package.json" ]] || { fail "package.json não encontrado: $FRONTEND"; exit 1; }
ok "$FRONTEND/package.json"

# ── 3. Criar .env com URLs correctos ─────────────────────────────────────────────
info "[3] A criar $FRONTEND/.env..."
cat > "$FRONTEND/.env" <<ENVEOF
# Gerado por rebuild_dashboard.sh em $(date)
# VITE injeta estas vars no bundle em build time — não em runtime!
VITE_API_URL=${VITE_API_URL}
VITE_WS_URL=${VITE_WS_URL}
ENVEOF
ok ".env:"
cat "$FRONTEND/.env"
echo ""

# ── 4. Verificar Node.js ──────────────────────────────────────────────────────────
info "[4] Node.js..."
if ! command -v node &>/dev/null; then
    warn "Node.js não encontrado — a instalar Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>/dev/null
    apt-get install -y nodejs 2>/dev/null
fi
ok "Node $(node --version)  npm $(npm --version)"

# ── 5. npm install ───────────────────────────────────────────────────────────────
info "[5] npm install..."
cd "$FRONTEND"
npm install --prefer-offline 2>&1 | tail -3
ok "Dependências OK"

# ── 6. npm run build ─────────────────────────────────────────────────────────────
info "[6] npm run build..."
npm run build  # output completo visível para diagnosticar erros de TypeScript

BUILD_OK=$?
if [[ $BUILD_OK -ne 0 ]]; then
    fail "npm run build falhou (exit code $BUILD_OK)"
    exit 1
fi
ok "Build concluída!"

# ── 7. Verificar o dist gerado ─────────────────────────────────────────────────
info "[7] A verificar dist/..."
echo ""
echo -e "${YELLOW}=== dist/index.html (deve ter type=module e assets/) ===${NC}"
cat "$FRONTEND/dist/index.html" 2>/dev/null || fail "index.html NAO encontrado em dist/!"
echo ""
echo -e "${YELLOW}=== Ficheiros em dist/ ===${NC}"
ls -lh "$FRONTEND/dist/" 2>/dev/null
ls -lh "$FRONTEND/dist/assets/" 2>/dev/null | head -6
echo ""

# Verificar que o IP está no bundle
if grep -r "$VPS_IP" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    ok "IP $VPS_IP confirmado no bundle"
else
    fail "IP $VPS_IP NAO encontrado no bundle! O .env não foi lido pelo Vite."
    warn "Verifica se o ficheiro é: $FRONTEND/.env (não .env.local ou outro)"
fi

# Verificar que NAO há 'import.meta.env' no bundle (deve ser substituído pelo Vite)
if grep -r "import\.meta\.env" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    fail "'import.meta.env' encontrado no bundle! O build não substituiu as vars do Vite."
    warn "Isto causaria o erro 'Cannot use import.meta outside a module' no browser."
else
    ok "import.meta.env correctamente substituído no bundle"
fi

# ── 8. Reiniciar nexus-dashboard ─────────────────────────────────────────────
info "[8] A reiniciar nexus-dashboard..."
systemctl restart nexus-dashboard 2>/dev/null && ok "nexus-dashboard reiniciado" \
  || warn "nexus-dashboard não encontrado como serviço"
sleep 2

# ── 9. Testar o que o servidor responde ───────────────────────────────────────────
info "[9] Resposta do servidor ao GET / ..."
echo ""
DASHBOARD_RESPONSE=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -10)
echo "$DASHBOARD_RESPONSE"
if echo "$DASHBOARD_RESPONSE" | grep -qi "<!doctype\|<html"; then
    ok "Servidor está a servir HTML"
else
    fail "Servidor NAO está a servir HTML — pode estar a devolver JSON (frontend_not_built)"
fi
echo ""

# ── 10. Validação das portas ───────────────────────────────────────────────
info "[10] Portas..."
for entry in "8000:API" "8001:WebSocket" "9000:Dashboard"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    ss -tulpn 2>/dev/null | grep -q ":${PORT}" && ok "$LABEL (${PORT}): ABERTO" || warn "$LABEL (${PORT}): FECHADO"
done

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
echo "Dashboard : http://${VPS_IP}:9000"
echo "Healthz   : http://${VPS_IP}:9000/healthz"
echo ""
echo "Para ver o bundle com IP correcto no browser:"
echo "  Ctrl+Shift+R (hard refresh) OU abre em aba privada"
echo ""
