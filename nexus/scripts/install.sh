#!/usr/bin/env bash
# =============================================================================
# NEXUS — Instalador para Ubuntu 22.04 (VPS / Google Cloud)
# =============================================================================
# Uso: sudo bash nexus/scripts/install.sh
# Flags:
#   --skip-docker     não instala Docker (já instalado)
#   --skip-python     não instala Python venv
#   --no-services     não activa/inicia serviços systemd
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Cores e helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${GREEN}[NEXUS]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERRO]${NC}  $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}"; }

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
SKIP_DOCKER=0; SKIP_PYTHON=0; NO_SERVICES=0
for arg in "$@"; do
  case $arg in
    --skip-docker)  SKIP_DOCKER=1  ;;
    --skip-python)  SKIP_PYTHON=1  ;;
    --no-services)  NO_SERVICES=1  ;;
    *) warn "Flag desconhecida: $arg" ;;
  esac
done

# ---------------------------------------------------------------------------
# Verificações iniciais
# ---------------------------------------------------------------------------
[[ $EUID -eq 0 ]] || err "Corre como root: sudo bash install.sh"
[[ -f /etc/os-release ]] && source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || warn "Sistema não é Ubuntu — pode haver incompatibilidades."
info "Sistema: ${PRETTY_NAME:-desconhecido}"
info "Kernel:  $(uname -r)"

# ---------------------------------------------------------------------------
# Passo 1 — Reparar e limpar APT
# ---------------------------------------------------------------------------
step "Reparar APT"
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a          # suprimir prompts needrestart no GCP

log "Eliminar locks residuais..."
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock \
       /var/cache/apt/archives/lock /var/lib/apt/lists/lock 2>/dev/null || true
dpkg --configure -a || true

log "Remover pacotes conflituosos (docker.io / containerd antigos)..."
apt-get remove -yq --allow-change-held-packages \
    docker docker-engine docker.io containerd runc \
    docker-compose docker-compose-plugin 2>/dev/null || true

log "Limpar cache APT..."
apt-get clean -q
rm -rf /var/lib/apt/lists/*

log "Atualizar índices APT..."
apt-get update -qq

log "Corrigir pacotes presos (dist-upgrade conservador)..."
apt-get -yq -o Dpkg::Options::="--force-confdef" \
             -o Dpkg::Options::="--force-confold" \
             --fix-broken install
apt-get -yq -o Dpkg::Options::="--force-confdef" \
             -o Dpkg::Options::="--force-confold" \
             --with-new-pkgs upgrade || warn "upgrade parcial — continuando"

# ---------------------------------------------------------------------------
# Passo 2 — Dependências base
# ---------------------------------------------------------------------------
step "Dependências base"
BASE_PKGS=(
    ca-certificates curl gnupg lsb-release
    git wget unzip
    build-essential
    portaudio19-dev libsndfile1 ffmpeg espeak
    python3.11 python3.11-venv python3.11-dev python3-pip
    software-properties-common apt-transport-https
)

log "A instalar pacotes base..."
apt-get install -yq \
    --no-install-recommends \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    "${BASE_PKGS[@]}" || {
    warn "Instalação directa falhou — a tentar um a um..."
    for pkg in "${BASE_PKGS[@]}"; do
        apt-get install -yq --no-install-recommends "$pkg" 2>/dev/null \
            && info "  OK: $pkg" \
            || warn "  SKIP (não disponível): $pkg"
    done
}

# ---------------------------------------------------------------------------
# Passo 3 — Docker CE (via repositório oficial)
# ---------------------------------------------------------------------------
if [[ $SKIP_DOCKER -eq 0 ]]; then
  step "Docker CE"

  if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version 2>/dev/null || true)
    info "Docker já instalado: $DOCKER_VER"
  else
    log "Adicionar chave GPG do Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    ARCH=$(dpkg --print-architecture)
    CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
    log "Adicionar repositório Docker (arch=$ARCH codename=$CODENAME)..."
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -yq \
        --no-install-recommends \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    log "Docker instalado: $(docker --version)"
  fi

  log "Activar e iniciar Docker..."
  systemctl enable docker --now
  docker run --rm hello-world &>/dev/null \
      && log "Docker a funcionar correctamente." \
      || warn "docker run hello-world falhou — verifica o daemon."
else
  info "[--skip-docker] Docker ignorado."
fi

# ---------------------------------------------------------------------------
# Passo 4 — Utilizador nexus
# ---------------------------------------------------------------------------
step "Utilizador nexus"
if id nexus &>/dev/null; then
  info "Utilizador nexus já existe."
else
  useradd -r -m -s /bin/bash nexus
  log "Utilizador nexus criado."
fi
[[ $SKIP_DOCKER -eq 0 ]] && usermod -aG docker nexus || true
mkdir -p /opt/nexus /data/nexus /var/log/nexus
chown -R nexus:nexus /opt/nexus /data/nexus /var/log/nexus

# ---------------------------------------------------------------------------
# Passo 5 — Repositório
# ---------------------------------------------------------------------------
step "Repositório NEXUS"
REPO_URL="https://github.com/sergioworkprt-ui/nexus-ia-pessoal.git"
REPO_BRANCH="claude/create-test-file-d1AY6"

if [[ -d /opt/nexus/.git ]]; then
  log "Repositório já existe — a actualizar..."
  git -C /opt/nexus fetch --all -q
  git -C /opt/nexus checkout "$REPO_BRANCH" -q 2>/dev/null || true
  git -C /opt/nexus pull --ff-only origin "$REPO_BRANCH" -q || warn "pull falhou — a usar versão local"
else
  log "A clonar repositório..."
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" /opt/nexus
fi
chown -R nexus:nexus /opt/nexus

# ---------------------------------------------------------------------------
# Passo 6 — Python venv
# ---------------------------------------------------------------------------
if [[ $SKIP_PYTHON -eq 0 ]]; then
  step "Python Virtual Environment"
  VENV=/opt/nexus/venv

  if [[ ! -d "$VENV" ]]; then
    log "A criar venv em $VENV..."
    python3.11 -m venv "$VENV"
  else
    info "venv já existe."
  fi

  log "A actualizar pip/wheel..."
  "$VENV"/bin/pip install -q --upgrade pip wheel setuptools

  REQ=/opt/nexus/nexus/requirements.txt
  if [[ -f "$REQ" ]]; then
    log "A instalar dependências Python..."
    "$VENV"/bin/pip install -q --no-cache-dir -r "$REQ" \
        || { warn "pip install falhou — a tentar com --no-deps"; \
             "$VENV"/bin/pip install -q --no-cache-dir --no-deps -r "$REQ"; }
    log "Dependências Python instaladas."
  else
    warn "requirements.txt não encontrado em $REQ"
  fi
else
  info "[--skip-python] Python venv ignorado."
fi

# ---------------------------------------------------------------------------
# Passo 7 — Ficheiro .env
# ---------------------------------------------------------------------------
step "Configuração .env"
ENV_FILE=/opt/nexus/.env
ENV_EXAMPLE=/opt/nexus/nexus/.env.example

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    chown nexus:nexus "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    warn ".env criado a partir do exemplo."
    warn "IMPORTANTE: edita $ENV_FILE com as tuas chaves antes de iniciar."
  else
    warn ".env.example não encontrado — a criar .env mínimo..."
    cat > "$ENV_FILE" <<'ENVEOF'
NEXUS_SECRET_KEY=muda-esta-chave-agora
OPENAI_API_KEY=
XTB_ACCOUNT_ID=
XTB_PASSWORD=
IBKR_HOST=localhost
IBKR_ACCOUNT=
ENVEOF
    chown nexus:nexus "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
else
  info ".env já existe — não foi modificado."
fi

# ---------------------------------------------------------------------------
# Passo 8 — Serviços systemd
# ---------------------------------------------------------------------------
step "Serviços systemd"

cat > /etc/systemd/system/nexus-api.service <<SVCEOF
[Unit]
Description=NEXUS API Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
Environment=PYTHONPATH=/opt/nexus
ExecStart=/opt/nexus/venv/bin/uvicorn nexus.api.rest.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5
StandardOutput=append:/var/log/nexus/api.log
StandardError=append:/var/log/nexus/api.log

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/nexus-core.service <<SVCEOF
[Unit]
Description=NEXUS Core Service
After=network-online.target nexus-api.service
Wants=network-online.target

[Service]
Type=simple
User=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
Environment=PYTHONPATH=/opt/nexus
ExecStart=/opt/nexus/venv/bin/python -m nexus.main
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5
StandardOutput=append:/var/log/nexus/core.log
StandardError=append:/var/log/nexus/core.log

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable nexus-api nexus-core
log "Serviços systemd configurados."

if [[ $NO_SERVICES -eq 0 ]]; then
  log "A iniciar nexus-api..."
  systemctl start nexus-api
  sleep 4

  if systemctl is-active --quiet nexus-api; then
    log "nexus-api está activo."
  else
    warn "nexus-api não iniciou — ver: journalctl -u nexus-api -n 30"
  fi

  log "A iniciar nexus-core..."
  systemctl start nexus-core
  sleep 4

  if systemctl is-active --quiet nexus-core; then
    log "nexus-core está activo."
  else
    warn "nexus-core não iniciou — ver: journalctl -u nexus-core -n 30"
  fi
else
  info "[--no-services] Serviços não iniciados automaticamente."
fi

# ---------------------------------------------------------------------------
# Passo 9 — Verificações finais
# ---------------------------------------------------------------------------
step "Verificações Finais"

check_version() {
  local label=$1; local cmd=$2
  local ver; ver=$(eval "$cmd" 2>/dev/null) || ver="não encontrado"
  echo -e "  ${CYAN}${label}:${NC} $ver"
}

check_version "Python"         "/opt/nexus/venv/bin/python --version"
[[ $SKIP_DOCKER -eq 0 ]] && check_version "Docker"  "docker --version"
[[ $SKIP_DOCKER -eq 0 ]] && check_version "Compose" "docker compose version"
check_version "Git"            "git --version"

echo ""
log "Instalação concluída!"
echo -e ""
echo -e "${BOLD}Próximos passos:${NC}"
echo -e "  1. Editar /opt/nexus/.env com as tuas chaves de API"
echo -e "  2. ${CYAN}sudo systemctl restart nexus-api nexus-core${NC}"
echo -e "  3. ${CYAN}curl http://localhost:8000/health${NC}"
echo -e "  4. Logs: ${CYAN}journalctl -u nexus-api -u nexus-core -f${NC}"
echo ""
