#!/usr/bin/env bash
# security_audit.sh — Auditoria de segurança do VPS NEXUS
# Uso: bash /opt/nexus/nexus/scripts/security_audit.sh
# Exit code: 0 = sem falhas críticas, 1 = falhas críticas detectadas

set -uo pipefail

NEXUS_HOME="/opt/nexus"
LOG_DIR="$NEXUS_HOME/logs"
LOG_FILE="$LOG_DIR/security.log"
FAIL=0
WARN=0

mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; WARN=$((WARN+1)); }
fail() { echo -e "${RED}✘ $*${NC}"; FAIL=$((FAIL+1)); }
info() { echo -e "${BLUE}▸ $*${NC}"; }

{
  echo ""
  echo "=== SECURITY_AUDIT $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
} >> "$LOG_FILE"

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS Security Audit                   ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

# ── 1. Permissões de ficheiros sensíveis ─────────────────────────────────────
info "[1] Permissões de ficheiros sensíveis..."
for f in "$NEXUS_HOME/.env" "$NEXUS_HOME/.env.local"; do
    if [[ -f "$f" ]]; then
        PERM=$(stat -c '%a' "$f" 2>/dev/null || stat -f '%OLp' "$f" 2>/dev/null)
        if [[ "${PERM:-999}" -le 640 ]]; then
            ok "  $f: $PERM"
        else
            warn "  $f: $PERM (deve ser <=640) — a corrigir..."
            chmod 640 "$f" 2>/dev/null && ok "    → corrigido para 640" || fail "    → falha ao corrigir"
        fi
    fi
done

if [[ -d "$HOME/.ssh" ]]; then
    PERM=$(stat -c '%a' "$HOME/.ssh" 2>/dev/null || echo '700')
    [[ "${PERM:-999}" -le 700 ]] && ok "  ~/.ssh: $PERM" || warn "  ~/.ssh: $PERM (deve ser 700)"
fi

# ── 2. Portas expostas ────────────────────────────────────────────────────────
info "[2] Portas expostas..."
EXPECTED="8000 8001 8801 9000"
OPEN=$(ss -tlnp 2>/dev/null | awk '/LISTEN/{print $4}' | grep -oE '[0-9]+$' | sort -un)
for port in $OPEN; do
    if echo "$EXPECTED" | grep -qw "$port"; then
        ok "  :$port — esperada"
    elif [[ "$port" -lt 1024 ]]; then
        warn "  :$port — porta de sistema (normal)"
    else
        warn "  :$port — inesperada (não está em EXPECTED=$EXPECTED)"
    fi
done

# ── 3. Serviços NEXUS ─────────────────────────────────────────────────────────
info "[3] Serviços systemd..."
for svc in nexus-core nexus-api nexus-dashboard; do
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        if systemctl is-active --quiet "$svc"; then
            ok "  $svc: active"
        else
            fail "  $svc: INACTIVE (deveria estar a correr)"
        fi
    fi
done

# ── 4. Python venv isolado ────────────────────────────────────────────────────
info "[4] Python virtual environment..."
VENV="$NEXUS_HOME/venv"
if [[ -d "$VENV" ]]; then
    ok "  venv: $VENV"
    OUTDATED=$("$VENV/bin/pip" list --outdated --format=columns 2>/dev/null | grep -v '^Package\|^-' | wc -l)
    if [[ "$OUTDATED" -gt 0 ]]; then
        warn "  $OUTDATED pacote(s) desactualizados no venv"
        "$VENV/bin/pip" list --outdated --format=columns 2>/dev/null | grep -v '^Package\|^-' | head -10 | sed 's/^/      /'
    else
        ok "  Sem pacotes desactualizados"
    fi
else
    warn "  venv não encontrado em $VENV"
fi

# ── 5. Valores default inseguros no .env ─────────────────────────────────────
info "[5] Valores .env..."
ENV_FILE="$NEXUS_HOME/.env"
if [[ -f "$ENV_FILE" ]]; then
    if grep -qiE 'nexus-change-me|changeme|secret123|password123|admin123|test123' "$ENV_FILE" 2>/dev/null; then
        fail "  .env contém credenciais default inseguras!"
    else
        ok "  .env sem credenciais default detectadas"
    fi
fi

# ── 6. Configuração SSH ───────────────────────────────────────────────────────
info "[6] Configuração sshd..."
SSHD="/etc/ssh/sshd_config"
if [[ -f "$SSHD" ]]; then
    grep -q '^PermitRootLogin yes' "$SSHD" 2>/dev/null \
        && warn "  PermitRootLogin yes — desactiva em produção" \
        || ok "  PermitRootLogin não é 'yes'"
    grep -q '^PasswordAuthentication yes' "$SSHD" 2>/dev/null \
        && warn "  PasswordAuthentication yes — usa só chaves SSH" \
        || ok "  PasswordAuthentication não é 'yes'"
fi

# ── 7. Actualizações de segurança ────────────────────────────────────────────
info "[7] Actualizações de segurança (apt)..."
if command -v apt-get &>/dev/null; then
    SECURITY=$(apt-get -s upgrade 2>/dev/null | grep -c '^Inst.*security' || echo 0)
    TOTAL=$(apt-get -s upgrade 2>/dev/null | grep -c '^Inst' || echo 0)
    if [[ "$SECURITY" -gt 0 ]]; then
        warn "  $SECURITY actualizações de segurança pendentes (total: $TOTAL)"
    else
        ok "  Sem actualizações de segurança pendentes (total disponível: $TOTAL)"
    fi
fi

# ── 8. Firewall (ufw) ─────────────────────────────────────────────────────────
info "[8] Firewall..."
if command -v ufw &>/dev/null; then
    UFW=$(ufw status 2>/dev/null | head -1)
    echo "$UFW" | grep -q 'active' && ok "  ufw: $UFW" || warn "  ufw: $UFW — considera activar"
else
    warn "  ufw não encontrado"
fi

# ── Resultado ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
if [[ $FAIL -gt 0 ]]; then
    echo -e "   Falhas críticas : ${RED}$FAIL${NC}"
else
    echo -e "   Falhas críticas : ${GREEN}0${NC}"
fi
echo -e "   Avisos          : ${YELLOW}$WARN${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

echo "SECURITY_AUDIT FAIL=$FAIL WARN=$WARN  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
