#!/usr/bin/env bash
# rebuild_dashboard.sh — Reconstrói o bundle React com URLs correctos
# Uso: sudo bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh [IP_DO_VPS]
#
# ARQUITECTURA DE PORTAS:
#   Porto 9000 (dashboard): serve frontend + proxy /api/* → :8000 + proxy /ws → :8000/ws
#   Porto 8000 (nexus-core): REST API interna + endpoint WS /ws
#   Porto 8801 (nexus-ws): standalone WS (não usado pelo frontend via proxy)
#
# O frontend usa SEMPRE o porto 9000:
#   VITE_API_URL = http://IP:9000/api   (dashboard faz proxy para :8000)
#   VITE_WS_URL  = ws://IP:9000/ws      (dashboard faz proxy para :8000/ws)

set -uo pipefail

NEXUS_HOME="/opt/nexus"
FRONTEND="$NEXUS_HOME/nexus/dashboard/frontend"
BACKEND_ENV="$NEXUS_HOME/.env"
VPS_IP="${1:-}"
SERVICE_USER="nexus"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
fail() { echo -e "${RED}✘ $*${NC}"; }
info() { echo -e "${BLUE}▸ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS Dashboard Rebuild${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# ── 0. Diagnóstico: mostrar ficheiros .env actuais ─────────────────────────────
info "[0] Ficheiros .env existentes no frontend..."
echo -e "${YELLOW}=== $FRONTEND/.env ===${NC}"
cat "$FRONTEND/.env" 2>/dev/null || echo "(não existe)"
echo -e "${YELLOW}=== $FRONTEND/.env.local ===${NC}"
cat "$FRONTEND/.env.local" 2>/dev/null || echo "(não existe)"
echo ""

# ── 1. Detectar IP do VPS ──────────────────────────────────────────────────────
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
    fail "Usa: sudo bash rebuild_dashboard.sh <IP_DO_VPS>"
    exit 1
fi
ok "IP: $VPS_IP"

# ── 2. Definir URLs do frontend ────────────────────────────────────────────────
# IMPORTANTE: tudo passa pelo porto 9000 (dashboard server).
# O dashboard server faz proxy:
#   /api/* → http://localhost:8000/*   (REST API interna)
#   /ws    → ws://localhost:8000/ws    (WebSocket interno)
#
# NÃO ler as portas do backend .env — usar sempre 9000 para o frontend.
# Isto elimina dependência de valores incorrectos no .env do servidor.
VITE_API_URL="http://${VPS_IP}:9000/api"
VITE_WS_URL="ws://${VPS_IP}:9000/ws"
ok "VITE_API_URL = $VITE_API_URL"
ok "VITE_WS_URL  = $VITE_WS_URL"

# ── 3. Verificar frontend ──────────────────────────────────────────────────────
info "[3] A verificar package.json..."
[[ -f "$FRONTEND/package.json" ]] || { fail "package.json não encontrado: $FRONTEND"; exit 1; }
ok "$FRONTEND/package.json"

# ── 4. Escrever .env E .env.local com URLs correctos ──────────────────────────
info "[4] A escrever .env e .env.local..."

ENV_CONTENT="# Gerado por rebuild_dashboard.sh em $(date)
# VITE injeta estas vars no bundle em build time -- nao em runtime!
# IMPORTANTE: .env.local tem prioridade sobre .env no Vite.
VITE_API_URL=${VITE_API_URL}
VITE_WS_URL=${VITE_WS_URL}
"

echo "$ENV_CONTENT" > "$FRONTEND/.env"
echo "$ENV_CONTENT" > "$FRONTEND/.env.local"

ok ".env escrito:"
cat "$FRONTEND/.env"
ok ".env.local escrito (sobrepõe-se a qualquer .env.local anterior)"

# ── 5. Verificar Node.js ────────────────────────────────────────────────────────
info "[5] Node.js..."
if ! command -v node &>/dev/null; then
    warn "Node.js não encontrado — a instalar Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>/dev/null
    apt-get install -y nodejs 2>/dev/null
fi
ok "Node $(node --version)  npm $(npm --version)"

# ── 6. Limpar cache de build anterior ──────────────────────────────────────────
info "[6] A limpar cache de build e dist/ anterior..."
rm -rf "$FRONTEND/dist" "$FRONTEND/.vite" "$FRONTEND/node_modules/.vite"
ok "Cache limpa"

# ── 7. npm install ─────────────────────────────────────────────────────────────
info "[7] npm install..."
cd "$FRONTEND"
npm install --prefer-offline 2>&1 | tail -3
ok "Dependências OK"

# ── 8. npm run build ───────────────────────────────────────────────────────────
info "[8] npm run build..."
npm run build
if [[ $? -ne 0 ]]; then
    fail "npm run build falhou"
    exit 1
fi
ok "Build concluída!"

# ── 9. Verificar bundle gerado ─────────────────────────────────────────────────
info "[9] A verificar bundle..."
echo ""
echo -e "${YELLOW}=== dist/index.html ===${NC}"
cat "$FRONTEND/dist/index.html" 2>/dev/null || { fail "index.html NAO encontrado em dist/!"; exit 1; }
echo ""

# Confirmar IP e porto 9000 no bundle
if grep -r "$VPS_IP" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    ok "IP $VPS_IP confirmado no bundle"
else
    fail "IP $VPS_IP NAO encontrado no bundle!"
fi

if grep -r ":9000" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    ok "Porto 9000 confirmado no bundle (proxy approach)"
else
    fail "Porto 9000 NAO encontrado no bundle!"
fi

if grep -rl "import\.meta\.env" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    fail "'import.meta.env' ainda no bundle — Vite NAO substituiu as vars de ambiente."
else
    ok "import.meta.env substituído correctamente"
fi

# ── 10. Permissões ─────────────────────────────────────────────────────────────
info "[10] A corrigir permissões ($SERVICE_USER)..."
if id -u "$SERVICE_USER" &>/dev/null; then
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "$FRONTEND/dist" 2>/dev/null && \
        ok "dist/ chown $SERVICE_USER" || warn "chown falhou (possível sem impacto)"
else
    warn "Utilizador '$SERVICE_USER' não encontrado — a saltar chown"
fi

find "$NEXUS_HOME/nexus/dashboard" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$NEXUS_HOME/nexus/dashboard" -name "*.pyc" -delete 2>/dev/null || true
ok "__pycache__ do dashboard limpo"

# ── 11. Reiniciar nexus-dashboard ──────────────────────────────────────────────
info "[11] A reiniciar nexus-dashboard..."
systemctl restart nexus-dashboard 2>/dev/null && ok "nexus-dashboard reiniciado" \
    || warn "nexus-dashboard não encontrado como serviço"
sleep 3

# ── 12. Testar resposta do servidor ────────────────────────────────────────────
info "[12] Resposta http://localhost:9000/ ..."
RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -5)
echo "$RESP"
if echo "$RESP" | grep -qi "<!doctype\|<html"; then
    ok "Servidor a devolver HTML"
else
    fail "Servidor NAO devolve HTML"
fi

# Testar healthz
if curl -s http://localhost:9000/healthz 2>/dev/null | grep -q dist_exists; then
    echo ""
    info "Healthz:"
    curl -s http://localhost:9000/healthz 2>/dev/null
    echo ""
fi

# ── 13. Estado final ───────────────────────────────────────────────────────────
echo ""
for entry in "8000:REST-API-interno" "9000:Dashboard+Proxy"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    ss -tulpn 2>/dev/null | grep -q ":${PORT}" && ok "$LABEL (${PORT}): ABERTO" || warn "$LABEL (${PORT}): FECHADO"
done

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
echo "Dashboard : http://${VPS_IP}:9000"
echo "API proxy : http://${VPS_IP}:9000/api/health"
echo "WS proxy  : ws://${VPS_IP}:9000/ws"
echo "Healthz   : http://${VPS_IP}:9000/healthz"
echo ""
echo "IMPORTANTE: abre o dashboard em aba PRIVADA para garantir zero cache."
echo ""
