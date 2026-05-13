#!/usr/bin/env bash
# rebuild_dashboard.sh — Cria .env/.env.local do frontend com IP do VPS e reconstrói o bundle
# Uso: sudo bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh [IP_DO_VPS]
# Exemplo: sudo bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh 35.241.151.115

set -uo pipefail

NEXUS_HOME="/opt/nexus"
FRONTEND="$NEXUS_HOME/nexus/dashboard/frontend"
BACKEND_ENV="$NEXUS_HOME/.env"
VPS_IP="${1:-}"
SERVICE_USER="nexus"  # utilizador do systemd (definido pelo install.sh)

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

# ── 0. Diagnóstico: mostrar ficheiros .env actuais ─────────────────────────────
info "[0] Ficheiros .env existentes no frontend..."
echo -e "${YELLOW}=== $FRONTEND/.env ===${NC}"
cat "$FRONTEND/.env" 2>/dev/null || echo "(não existe)"
echo -e "${YELLOW}=== $FRONTEND/.env.local ===${NC}"
cat "$FRONTEND/.env.local" 2>/dev/null || echo "(não existe)"
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
    fail "Usa: sudo bash rebuild_dashboard.sh <IP_DO_VPS>"
    exit 1
fi

ok "IP: $VPS_IP"

# Portas:
# API_PORT: REST API do nexus-core (porta 8000)
# WS_PORT:  WebSocket do nexus-core (porta 8801) — DIFERENTE da porta 8001 do nexus-api
API_PORT="8000"; WS_PORT="8801"
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

# ── 3. Escrever .env E .env.local com URLs correctos ───────────────────────────
info "[3] A escrever .env e .env.local (Vite: .env.local tem prioridade sobre .env)..."

ENV_CONTENT="# Gerado por rebuild_dashboard.sh em $(date)
# VITE injeta estas vars no bundle em build time -- nao em runtime!
# IMPORTANTE: .env.local tem prioridade sobre .env no Vite.
VITE_API_URL=${VITE_API_URL}
VITE_WS_URL=${VITE_WS_URL}
"

# Escrever ambos para garantir que nao ha ficheiro antigo a sobrepor-se
echo "$ENV_CONTENT" > "$FRONTEND/.env"
echo "$ENV_CONTENT" > "$FRONTEND/.env.local"

ok ".env escrito:"
cat "$FRONTEND/.env"
ok ".env.local escrito (sobrepõe-se a qualquer .env.local anterior)"

# ── 4. Verificar Node.js ──────────────────────────────────────────────────────────
info "[4] Node.js..."
if ! command -v node &>/dev/null; then
    warn "Node.js não encontrado — a instalar Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>/dev/null
    apt-get install -y nodejs 2>/dev/null
fi
ok "Node $(node --version)  npm $(npm --version)"

# ── 5. Limpar cache de build anterior ────────────────────────────────────────────
info "[5] A limpar cache de build e dist/ anterior..."
rm -rf "$FRONTEND/dist" "$FRONTEND/.vite" "$FRONTEND/node_modules/.vite"
ok "Cache limpa"

# ── 6. npm install ───────────────────────────────────────────────────────────────
info "[6] npm install..."
cd "$FRONTEND"
npm install --prefer-offline 2>&1 | tail -3
ok "Dependências OK"

# ── 7. npm run build ─────────────────────────────────────────────────────────────
info "[7] npm run build..."
npm run build
if [[ $? -ne 0 ]]; then
    fail "npm run build falhou"
    exit 1
fi
ok "Build concluída!"

# ── 8. Verificar bundle gerado ─────────────────────────────────────────────────
info "[8] A verificar bundle..."
echo ""
echo -e "${YELLOW}=== dist/index.html ===${NC}"
cat "$FRONTEND/dist/index.html" 2>/dev/null || { fail "index.html NAO encontrado em dist/!"; exit 1; }
echo ""

# Confirmar IP no bundle
if grep -r "$VPS_IP" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    ok "IP $VPS_IP confirmado no bundle"
else
    fail "IP $VPS_IP NAO encontrado no bundle!"
    warn "Possivel causa: outro ficheiro .env.* com prioridade superior tem valores antigos."
    echo "Ficheiros .env* existentes:"
    ls -la "$FRONTEND"/.env* 2>/dev/null
fi

# Confirmar que a porta WS correcta está no bundle
if grep -r "${WS_PORT}" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    ok "Porta WS ${WS_PORT} confirmada no bundle"
else
    fail "Porta WS ${WS_PORT} NAO encontrada no bundle!"
    warn "O dashboard vai tentar ligar à porta errada."
fi

# Confirmar que import.meta.env foi substituído pelo Vite
if grep -rl "import\.meta\.env" "$FRONTEND/dist/" &>/dev/null 2>&1; then
    fail "'import.meta.env' ainda no bundle! O Vite NAO substituiu as vars de ambiente."
    warn "Causa: o Vite ignorou o ficheiro .env (verifique erros de build acima)."
else
    ok "import.meta.env substituído correctamente (bom sinal)"
fi

# ── 9. Permissões (service user do install.sh é 'nexus') ────────────────────────
info "[9] A corrigir permissões ($SERVICE_USER)..."
if id -u "$SERVICE_USER" &>/dev/null; then
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "$FRONTEND/dist" 2>/dev/null && \
        ok "dist/ chown $SERVICE_USER" || warn "chown falhou (possível sem impacto)"
else
    warn "Utilizador '$SERVICE_USER' não encontrado — a saltar chown"
fi

# Limpar __pycache__ do server.py (evita usar versão compilada antiga)
find "$NEXUS_HOME/nexus/dashboard" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$NEXUS_HOME/nexus/dashboard" -name "*.pyc" -delete 2>/dev/null || true
ok "__pycache__ do dashboard limpo"

# ── 10. Reiniciar nexus-dashboard ─────────────────────────────────────────────
info "[10] A reiniciar nexus-dashboard..."
systemctl restart nexus-dashboard 2>/dev/null && ok "nexus-dashboard reiniciado" \
    || warn "nexus-dashboard não encontrado como serviço"
sleep 3

# ── 11. Testar resposta do servidor ─────────────────────────────────────────────
info "[11] Resposta http://localhost:9000/ ..."
RESP=$(curl -s --max-time 5 http://localhost:9000/ 2>/dev/null | head -5)
echo "$RESP"
if echo "$RESP" | grep -qi "<!doctype\|<html"; then
    ok "Servidor a devolver HTML"
    if echo "$RESP" | grep -qi 'type="module"'; then
        ok "HTML contém type=\"module\" (bundle Vite correcto)"
    fi
else
    fail "Servidor NAO devolve HTML — provavelmente frontend_not_built ainda activo"
    fail "Verifica dist/: ls -la $FRONTEND/dist/"
fi

# healthz endpoint
if curl -s http://localhost:9000/healthz 2>/dev/null | grep -q dist_exists; then
    echo ""
    info "Healthz:"
    curl -s http://localhost:9000/healthz 2>/dev/null
    echo ""
fi

# ── 12. Estado final ─────────────────────────────────────────────────────────────
echo ""
for entry in "8000:API(nexus-core)" "8001:API(nexus-api)" "8801:WebSocket(nexus-core)" "9000:Dashboard"; do
    PORT="${entry%%:*}"; LABEL="${entry##*:}"
    ss -tulpn 2>/dev/null | grep -q ":${PORT}" && ok "$LABEL (${PORT}): ABERTO" || warn "$LABEL (${PORT}): FECHADO"
done

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""
echo "Dashboard : http://${VPS_IP}:9000"
echo "Healthz   : http://${VPS_IP}:9000/healthz"
echo ""
echo "IMPORTANTE: abre o dashboard em aba privada para garantir zero cache."
echo ""
