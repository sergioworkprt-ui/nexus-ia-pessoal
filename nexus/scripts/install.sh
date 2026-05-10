#!/usr/bin/env bash
# =============================================================================
# NEXUS — Instalador para Ubuntu 22.04 (VPS / Google Cloud)
# =============================================================================
# Uso: sudo bash nexus/scripts/install.sh [FLAGS]
#
# FLAGS:
#   --safe-mode      Não toca em pacotes Ubuntu — só Docker, venv, serviços
#   --skip-docker    Não instala Docker
#   --skip-python    Não instala Python venv
#   --no-services    Não inicia serviços systemd
# =============================================================================
set -uo pipefail   # SEM -e : o script nunca para por erros individuais

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${GREEN}[NEXUS]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERRO]${NC}  $*" >&2; }
step() { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}"; }

PKGS_OK=(); PKGS_FAIL=()

SAFE_MODE=0; SKIP_DOCKER=0; SKIP_PYTHON=0; NO_SERVICES=0
for arg in "${@:-}"; do
  case $arg in
    --safe-mode)   SAFE_MODE=1   ;;
    --skip-docker) SKIP_DOCKER=1 ;;
    --skip-python) SKIP_PYTHON=1 ;;
    --no-services) NO_SERVICES=1 ;;
    *) warn "Flag desconhecida: $arg" ;;
  esac
done

[[ $EUID -eq 0 ]] || { err "Corre como root: sudo bash install.sh"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

try_install_pkg() {
  local pkg="$1"
  if dpkg -s "$pkg" &>/dev/null; then
    PKGS_OK+=("$pkg"); return 0
  fi
  apt-get install -yq --no-install-recommends \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    -o APT::Get::Fix-Broken=true \
    "$pkg" &>/tmp/nexus_pkg_err 2>&1
  if [[ $? -eq 0 ]]; then
    log "  [OK]      $pkg"; PKGS_OK+=("$pkg")
  else
    local reason; reason=$(grep -m1 'E:' /tmp/nexus_pkg_err 2>/dev/null | sed 's/^E: //' || true)
    warn "  [FALHOU]  $pkg — ${reason:-erro desconhecido}"; PKGS_FAIL+=("$pkg")
  fi
  return 0
}
install_pkgs() { for pkg in "$@"; do try_install_pkg "$pkg"; done; }

# ---------------------------------------------------------------------------
step "Reparar APT"
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock \
       /var/cache/apt/archives/lock /var/lib/apt/lists/lock 2>/dev/null || true
dpkg --configure -a 2>/dev/null || warn "dpkg --configure -a (ignorado)"
apt-get -yq -o Dpkg::Options::="--force-confdef" \
             -o Dpkg::Options::="--force-confold" \
             --fix-broken install 2>/dev/null || warn "--fix-broken (ignorado)"
HELD=$(dpkg --audit 2>/dev/null | grep -oP '^\S+' || true)
[[ -n "$HELD" ]] && echo "$HELD" | while read -r p; do
  apt-mark unhold "$p" 2>/dev/null && warn "  unhold: $p" || true
done
apt-get update -qq 2>/dev/null || warn "apt-get update (ignorado)"

# ---------------------------------------------------------------------------
if [[ $SAFE_MODE -eq 0 ]]; then
  step "Dependências de sistema (individual)"
  install_pkgs ca-certificates curl gnupg wget git unzip \
               lsb-release software-properties-common apt-transport-https
  install_pkgs python3.11 python3.11-venv python3.11-dev python3-pip
  install_pkgs build-essential
  install_pkgs portaudio19-dev libsndfile1 ffmpeg espeak
else
  info "[--safe-mode] Pacotes Ubuntu ignorados."
fi

# ---------------------------------------------------------------------------
if [[ $SKIP_DOCKER -eq 0 ]]; then
  step "Docker CE"
  if command -v docker &>/dev/null; then
    info "Docker já instalado: $(docker --version 2>/dev/null || true)"
  else
    for old in docker docker-engine docker.io containerd runc \
                docker-compose docker-compose-plugin; do
      apt-get remove -yq "$old" 2>/dev/null || true
    done
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg 2>/dev/null
    chmod a+r /etc/apt/keyrings/docker.gpg
    ARCH=$(dpkg --print-architecture)
    CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq 2>/dev/null || true
    install_pkgs docker-ce docker-ce-cli containerd.io \
                 docker-buildx-plugin docker-compose-plugin
    command -v docker &>/dev/null \
      && log "Docker instalado: $(docker --version)" \
      || warn "Docker não instalado."
  fi
  command -v docker &>/dev/null && {
    systemctl enable docker --now 2>/dev/null || true
    docker run --rm hello-world &>/dev/null \
      && log "Docker a funcionar." || warn "docker hello-world falhou."
  }
else
  info "[--skip-docker] Docker ignorado."
fi

# ---------------------------------------------------------------------------
step "Utilizador nexus e directorias"
id nexus &>/dev/null || useradd -r -m -s /bin/bash nexus
command -v docker &>/dev/null && usermod -aG docker nexus 2>/dev/null || true

# Criar directorias com ownership correcto ANTES de qualquer serviço arrancar
mkdir -p /opt/nexus /data/nexus /var/log/nexus
chown -R nexus:nexus /opt/nexus /data/nexus /var/log/nexus
chmod 775 /var/log/nexus

# Limpar logs antigos criados por root que causam PermissionError
if [[ -d /opt/nexus/logs ]]; then
  chown -R nexus:nexus /opt/nexus/logs 2>/dev/null || true
  chmod -R 664 /opt/nexus/logs 2>/dev/null || true
  chmod 775 /opt/nexus/logs 2>/dev/null || true
  warn "Directoria /opt/nexus/logs encontrada — ownership corrigido."
fi

# ---------------------------------------------------------------------------
step "Repositório NEXUS"
REPO_URL="https://github.com/sergioworkprt-ui/nexus-ia-pessoal.git"
REPO_BRANCH="claude/create-test-file-d1AY6"

if [[ -d /opt/nexus/.git ]]; then
  git -C /opt/nexus fetch --all -q 2>/dev/null || warn "git fetch falhou"
  git -C /opt/nexus checkout "$REPO_BRANCH" -q 2>/dev/null || warn "checkout falhou"
  git -C /opt/nexus pull --ff-only origin "$REPO_BRANCH" -q 2>/dev/null \
    || warn "git pull falhou — a usar versão local"
else
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" /opt/nexus 2>/dev/null \
    || warn "git clone falhou"
fi
chown -R nexus:nexus /opt/nexus 2>/dev/null || true

# ---------------------------------------------------------------------------
if [[ $SKIP_PYTHON -eq 0 ]]; then
  step "Python Virtual Environment"
  VENV=/opt/nexus/venv
  PY_BIN=""
  for candidate in python3.11 python3 python; do
    command -v "$candidate" &>/dev/null && { PY_BIN=$(command -v "$candidate"); break; }
  done

  if [[ -z "$PY_BIN" ]]; then
    warn "Nenhum Python encontrado — venv ignorado."; PKGS_FAIL+=("python-venv")
  else
    info "Python: $PY_BIN ($($PY_BIN --version 2>&1))"
    [[ ! -d "$VENV" ]] && "$PY_BIN" -m venv "$VENV" 2>/dev/null \
      || { warn "venv falhou"; PKGS_FAIL+=("python-venv"); }

    if [[ -d "$VENV" ]]; then
      "$VENV"/bin/pip install -q --upgrade pip wheel setuptools 2>/dev/null || true
      REQ=/opt/nexus/nexus/requirements.txt
      if [[ -f "$REQ" ]]; then
        if ! "$VENV"/bin/pip install -q --no-cache-dir -r "$REQ" 2>/tmp/nexus_pip_err; then
          warn "pip install -r falhou — a tentar pacote a pacote..."
          while IFS= read -r line; do
            [[ "$line" =~ ^\s*# ]] && continue
            [[ -z "${line//[[:space:]]/}" ]] && continue
            pkg_name=$(echo "$line" | sed 's/[>=<!].*//' | tr -d ' ')
            "$VENV"/bin/pip install -q --no-cache-dir "$line" 2>/dev/null \
              && PKGS_OK+=("py:$pkg_name") \
              || { warn "  [FALHOU pip] $pkg_name"; PKGS_FAIL+=("py:$pkg_name"); }
          done < "$REQ"
        else
          PKGS_OK+=("python-requirements"); log "requirements.txt instalado."
        fi
      fi
    fi
  fi
else
  info "[--skip-python] Python venv ignorado."
fi

# ---------------------------------------------------------------------------
step "Configuração .env"
ENV_FILE=/opt/nexus/.env
if [[ ! -f "$ENV_FILE" ]]; then
  [[ -f /opt/nexus/nexus/.env.example ]] \
    && cp /opt/nexus/nexus/.env.example "$ENV_FILE" \
    || cat > "$ENV_FILE" <<'ENVEOF'
NEXUS_API_KEY=nexus-change-me
NEXUS_SECRET_KEY=nexus-change-me
LOG_DIR=/var/log/nexus
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
TTS_ENABLED=false
STT_ENABLED=false
TRADING_BROKER=simulation
ENVEOF
  chown nexus:nexus "$ENV_FILE"; chmod 600 "$ENV_FILE"
  warn ".env criado — edita $ENV_FILE com as tuas chaves."
else
  # Garantir que LOG_DIR é absoluto no .env existente
  if grep -q '^LOG_DIR=logs$' "$ENV_FILE" 2>/dev/null; then
    sed -i 's|^LOG_DIR=logs$|LOG_DIR=/var/log/nexus|' "$ENV_FILE"
    warn ".env: LOG_DIR corrigido para /var/log/nexus"
  fi
  info ".env já existe — não modificado (excepto LOG_DIR)."
fi

# ---------------------------------------------------------------------------
step "Serviços systemd"
# Regra: sem StandardOutput=append para ficheiros — o journald captura stdout.
# O logger Python escreve para /var/log/nexus/ por conta própria com permissões correctas.
# LOG_DIR e LOG_LEVEL injectados explicitamente para não depender só do .env.

cat > /etc/systemd/system/nexus-api.service <<'SVCEOF'
[Unit]
Description=NEXUS API Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nexus
Group=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
Environment=PYTHONPATH=/opt/nexus
Environment=LOG_DIR=/var/log/nexus
Environment=LOG_LEVEL=INFO
UMask=0002
ExecStart=/opt/nexus/venv/bin/uvicorn nexus.api.rest.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-api

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/nexus-core.service <<'SVCEOF'
[Unit]
Description=NEXUS Core Service
After=network-online.target nexus-api.service
Wants=network-online.target

[Service]
Type=simple
User=nexus
Group=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
Environment=PYTHONPATH=/opt/nexus
Environment=LOG_DIR=/var/log/nexus
Environment=LOG_LEVEL=INFO
UMask=0002
ExecStart=/opt/nexus/venv/bin/python -m nexus.main
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-core

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/nexus-dashboard.service <<'SVCEOF'
[Unit]
Description=NEXUS Dashboard Service
After=network-online.target nexus-api.service
Wants=network-online.target

[Service]
Type=simple
User=nexus
Group=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
Environment=PYTHONPATH=/opt/nexus
Environment=LOG_DIR=/var/log/nexus
Environment=LOG_LEVEL=INFO
Environment=DASHBOARD_PORT=9000
UMask=0002
ExecStart=/opt/nexus/venv/bin/python -m nexus.dashboard.server
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-dashboard

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable nexus-api nexus-core nexus-dashboard 2>/dev/null || warn "systemctl enable falhou"
log "Serviços systemd configurados."

if [[ $NO_SERVICES -eq 0 ]]; then
  for svc in nexus-api nexus-core nexus-dashboard; do
    log "A iniciar $svc..."
    systemctl restart "$svc" 2>/dev/null || warn "$svc restart falhou"
    sleep 4
    systemctl is-active --quiet "$svc" \
      && log "$svc ACTIVO." \
      || warn "$svc inactivo — ver: journalctl -u $svc -n 50 --no-pager"
  done
else
  info "[--no-services] Serviços não iniciados automaticamente."
fi

# ---------------------------------------------------------------------------
step "Relatório Final"
echo -e "\n${BOLD}Instalados (${#PKGS_OK[@]}):${NC}"
[[ ${#PKGS_OK[@]} -gt 0 ]] \
  && for p in "${PKGS_OK[@]}"; do echo -e "  ${GREEN}✔${NC} $p"; done \
  || echo "  (nenhum)"
echo -e "\n${BOLD}Falharam (${#PKGS_FAIL[@]}):${NC}"
if [[ ${#PKGS_FAIL[@]} -gt 0 ]]; then
  for p in "${PKGS_FAIL[@]}"; do echo -e "  ${RED}✘${NC} $p"; done
  warn "Pacotes em falta podem limitar funcionalidade de voz/áudio. Core não é afectado."
else
  echo -e "  ${GREEN}(nenhuma falha)${NC}"
fi
echo ""
log "Instalação concluída!"
echo -e "\n${BOLD}Próximos passos:${NC}"
echo -e "  1. Edita  ${CYAN}/opt/nexus/.env${NC}"
echo -e "  2. Reinicia: ${CYAN}sudo systemctl restart nexus-api nexus-core nexus-dashboard${NC}"
echo -e "  3. API:       ${CYAN}curl http://localhost:8000/health${NC}"
echo -e "  4. Dashboard: ${CYAN}curl http://localhost:9000/health${NC}"
echo -e "  5. Logs:      ${CYAN}journalctl -u nexus-core -f${NC}"
echo ""
