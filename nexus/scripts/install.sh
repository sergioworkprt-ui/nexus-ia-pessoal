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

# ---------------------------------------------------------------------------
# Cores
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${GREEN}[NEXUS]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERRO]${NC}  $*" >&2; }
step() { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}"; }

# ---------------------------------------------------------------------------
# Contadores de resultado
# ---------------------------------------------------------------------------
PKGS_OK=();  PKGS_SKIP=(); PKGS_FAIL=()

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Função: instalar UM pacote com fallback
# ---------------------------------------------------------------------------
try_install_pkg() {
  local pkg="$1"
  if dpkg -s "$pkg" &>/dev/null; then
    info "  [JÁ INST] $pkg"
    PKGS_OK+=("$pkg")
    return 0
  fi

  apt-get install -yq \
    --no-install-recommends \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    -o APT::Get::Fix-Broken=true \
    "$pkg" &>/tmp/nexus_pkg_err 2>&1

  local rc=$?
  if [[ $rc -eq 0 ]]; then
    log "  [OK]      $pkg"
    PKGS_OK+=("$pkg")
  else
    local reason
    reason=$(grep -m1 'E:' /tmp/nexus_pkg_err 2>/dev/null | sed 's/^E: //' || true)
    warn "  [FALHOU]  $pkg — ${reason:-erro desconhecido}"
    PKGS_FAIL+=("$pkg")
  fi
  return 0   # nunca propaga erro
}

# ---------------------------------------------------------------------------
# Função: instalar lista de pacotes um a um
# ---------------------------------------------------------------------------
install_pkgs() {
  for pkg in "$@"; do
    try_install_pkg "$pkg"
  done
}

# ---------------------------------------------------------------------------
# Passo 1 — Reparar APT (sempre, mesmo em --safe-mode)
# ---------------------------------------------------------------------------
step "Reparar APT"

log "Remover locks residuais..."
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock \
       /var/cache/apt/archives/lock /var/lib/apt/lists/lock 2>/dev/null || true

log "dpkg --configure -a ..."
dpkg --configure -a 2>/dev/null || warn "dpkg --configure -a reportou avisos (ignorado)"

log "apt --fix-broken install ..."
apt-get -yq \
  -o Dpkg::Options::="--force-confdef" \
  -o Dpkg::Options::="--force-confold" \
  --fix-broken install 2>/dev/null || warn "--fix-broken install reportou avisos (ignorado)"

log "dpkg --audit ..."
HELD=$(dpkg --audit 2>/dev/null | grep -oP '^\S+' || true)
if [[ -n "$HELD" ]]; then
  warn "Pacotes problemáticos detectados — a fazer unhold:"
  echo "$HELD" | while read -r p; do
    apt-mark unhold "$p" 2>/dev/null && warn "  unhold: $p" || true
  done
fi

log "Actualizar índices APT..."
apt-get update -qq 2>/dev/null || warn "apt-get update reportou erros (ignorado)"

# ---------------------------------------------------------------------------
# Passo 2 — Dependências de sistema (ignorado em --safe-mode)
# ---------------------------------------------------------------------------
if [[ $SAFE_MODE -eq 0 ]]; then
  step "Dependências de sistema (instalação individual)"
  warn "Cada pacote é instalado separadamente — falhas individuais são avisadas mas não param o script."

  # Ferramentas essenciais
  install_pkgs \
    ca-certificates curl gnupg wget git unzip \
    lsb-release software-properties-common apt-transport-https

  # Python
  install_pkgs \
    python3.11 python3.11-venv python3.11-dev python3-pip

  # Build tools
  install_pkgs build-essential

  # Áudio / multimédia (opcionais para o core, falha é aceitável)
  install_pkgs portaudio19-dev libsndfile1 ffmpeg espeak

else
  info "[--safe-mode] Instalação de pacotes Ubuntu ignorada."
fi

# ---------------------------------------------------------------------------
# Passo 3 — Docker CE (repositório oficial)
# ---------------------------------------------------------------------------
if [[ $SKIP_DOCKER -eq 0 ]]; then
  step "Docker CE"

  if command -v docker &>/dev/null; then
    info "Docker já instalado: $(docker --version 2>/dev/null || true)"
  else
    log "A remover versões antigas (docker.io, containerd)..."
    for old in docker docker-engine docker.io containerd runc \
                docker-compose docker-compose-plugin; do
      apt-get remove -yq "$old" 2>/dev/null || true
    done

    log "Adicionar chave GPG Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg 2>/dev/null
    chmod a+r /etc/apt/keyrings/docker.gpg

    ARCH=$(dpkg --print-architecture)
    CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")
    log "Repositório Docker (arch=$ARCH codename=$CODENAME)..."
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq 2>/dev/null || warn "apt-get update após Docker repo reportou erros"

    # Docker: instalação individual para isolar conflitos
    install_pkgs docker-ce docker-ce-cli containerd.io \
                 docker-buildx-plugin docker-compose-plugin

    if command -v docker &>/dev/null; then
      log "Docker instalado: $(docker --version)"
    else
      warn "Docker não instalado — continua sem Docker."
    fi
  fi

  if command -v docker &>/dev/null; then
    systemctl enable docker --now 2>/dev/null || warn "systemctl enable docker falhou"
    docker run --rm hello-world &>/dev/null \
      && log "Docker a funcionar correctamente." \
      || warn "docker run hello-world falhou — verifica o daemon."
  fi
else
  info "[--skip-docker] Docker ignorado."
fi

# ---------------------------------------------------------------------------
# Passo 4 — Utilizador nexus
# ---------------------------------------------------------------------------
step "Utilizador nexus"
if ! id nexus &>/dev/null; then
  useradd -r -m -s /bin/bash nexus && log "Utilizador nexus criado."
else
  info "Utilizador nexus já existe."
fi
command -v docker &>/dev/null && usermod -aG docker nexus 2>/dev/null || true
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
  git -C /opt/nexus fetch --all -q 2>/dev/null || warn "git fetch falhou"
  git -C /opt/nexus checkout "$REPO_BRANCH" -q 2>/dev/null || warn "checkout falhou"
  git -C /opt/nexus pull --ff-only origin "$REPO_BRANCH" -q 2>/dev/null \
    || warn "git pull falhou — a usar versão local"
else
  log "A clonar repositório..."
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" /opt/nexus 2>/dev/null \
    || warn "git clone falhou — verifica conectividade"
fi
chown -R nexus:nexus /opt/nexus 2>/dev/null || true

# ---------------------------------------------------------------------------
# Passo 6 — Python venv
# ---------------------------------------------------------------------------
if [[ $SKIP_PYTHON -eq 0 ]]; then
  step "Python Virtual Environment"
  VENV=/opt/nexus/venv

  # Encontrar python3.11 ou fallback para python3
  PY_BIN=""
  for candidate in python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
      PY_BIN=$(command -v "$candidate")
      break
    fi
  done

  if [[ -z "$PY_BIN" ]]; then
    warn "Nenhum Python encontrado — venv ignorado."
    PKGS_FAIL+=("python-venv")
  else
    info "Python usado: $PY_BIN ($($PY_BIN --version 2>&1))"

    if [[ ! -d "$VENV" ]]; then
      log "A criar venv..."
      "$PY_BIN" -m venv "$VENV" 2>/dev/null || { warn "venv falhou"; PKGS_FAIL+=("python-venv"); }
    else
      info "venv já existe."
    fi

    if [[ -d "$VENV" ]]; then
      log "A actualizar pip/wheel..."
      "$VENV"/bin/pip install -q --upgrade pip wheel setuptools 2>/dev/null \
        || warn "upgrade pip/wheel falhou (ignorado)"

      REQ=/opt/nexus/nexus/requirements.txt
      if [[ -f "$REQ" ]]; then
        log "A instalar requirements.txt..."
        if ! "$VENV"/bin/pip install -q --no-cache-dir -r "$REQ" 2>/tmp/nexus_pip_err; then
          warn "pip install falhou — a tentar pacote a pacote..."
          while IFS= read -r line; do
            # ignora comentários e linhas vazias
            [[ "$line" =~ ^\s*# ]] && continue
            [[ -z "${line//[[:space:]]/}" ]] && continue
            pkg_name=$(echo "$line" | sed 's/[>=<!].*//' | tr -d ' ')
            if "$VENV"/bin/pip install -q --no-cache-dir "$line" 2>/dev/null; then
              PKGS_OK+=("py:$pkg_name")
            else
              warn "  [FALHOU pip] $pkg_name"
              PKGS_FAIL+=("py:$pkg_name")
            fi
          done < "$REQ"
        else
          log "requirements.txt instalado com sucesso."
          PKGS_OK+=("python-requirements")
        fi
      else
        warn "requirements.txt não encontrado em $REQ"
      fi
    fi
  fi
else
  info "[--skip-python] Python venv ignorado."
fi

# ---------------------------------------------------------------------------
# Passo 7 — .env
# ---------------------------------------------------------------------------
step "Configuração .env"
ENV_FILE=/opt/nexus/.env
ENV_EXAMPLE=/opt/nexus/nexus/.env.example

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  else
    cat > "$ENV_FILE" <<'ENVEOF'
NEXUS_SECRET_KEY=muda-esta-chave-agora
OPENAI_API_KEY=
XTB_ACCOUNT_ID=
XTB_PASSWORD=
IBKR_HOST=localhost
IBKR_ACCOUNT=
ENVEOF
  fi
  chown nexus:nexus "$ENV_FILE"; chmod 600 "$ENV_FILE"
  warn ".env criado — edita $ENV_FILE com as tuas chaves."
else
  info ".env já existe — não modificado."
fi

# ---------------------------------------------------------------------------
# Passo 8 — Serviços systemd
# ---------------------------------------------------------------------------
step "Serviços systemd"

cat > /etc/systemd/system/nexus-api.service <<'SVCEOF'
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
StandardOutput=append:/var/log/nexus/api.log
StandardError=append:/var/log/nexus/api.log

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
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
Environment=PYTHONPATH=/opt/nexus
ExecStart=/opt/nexus/venv/bin/python -m nexus.main
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/nexus/core.log
StandardError=append:/var/log/nexus/core.log

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable nexus-api nexus-core 2>/dev/null || warn "systemctl enable falhou"
log "Serviços systemd configurados."

if [[ $NO_SERVICES -eq 0 ]]; then
  log "A iniciar nexus-api..."
  systemctl start nexus-api 2>/dev/null || warn "nexus-api não iniciou"
  sleep 4
  systemctl is-active --quiet nexus-api \
    && log "nexus-api ACTIVO." \
    || warn "nexus-api inactivo — ver: journalctl -u nexus-api -n 30"

  log "A iniciar nexus-core..."
  systemctl start nexus-core 2>/dev/null || warn "nexus-core não iniciou"
  sleep 4
  systemctl is-active --quiet nexus-core \
    && log "nexus-core ACTIVO." \
    || warn "nexus-core inactivo — ver: journalctl -u nexus-core -n 30"
else
  info "[--no-services] Serviços não iniciados automaticamente."
fi

# ---------------------------------------------------------------------------
# Passo 9 — Relatório final
# ---------------------------------------------------------------------------
step "Relatório de Instalação"

echo -e "\n${BOLD}Pacotes instalados com sucesso (${#PKGS_OK[@]}):${NC}"
if [[ ${#PKGS_OK[@]} -gt 0 ]]; then
  for p in "${PKGS_OK[@]}"; do echo -e "  ${GREEN}✔${NC} $p"; done
else
  echo "  (nenhum)"
fi

echo -e "\n${BOLD}Pacotes ignorados/já presentes (${#PKGS_SKIP[@]}):${NC}"
if [[ ${#PKGS_SKIP[@]} -gt 0 ]]; then
  for p in "${PKGS_SKIP[@]}"; do echo -e "  ${CYAN}–${NC} $p"; done
else
  echo "  (nenhum)"
fi

echo -e "\n${BOLD}Pacotes que falharam (${#PKGS_FAIL[@]}):${NC}"
if [[ ${#PKGS_FAIL[@]} -gt 0 ]]; then
  for p in "${PKGS_FAIL[@]}"; do echo -e "  ${RED}✘${NC} $p"; done
  warn "Pacotes em falta podem limitar funcionalidade (voz/áudio). O núcleo NEXUS funciona sem eles."
else
  echo -e "  ${GREEN}(nenhuma falha)${NC}"
fi

echo ""
log "Instalação concluída!"
echo -e ""
echo -e "${BOLD}Próximos passos:${NC}"
echo -e "  1. Edita  ${CYAN}/opt/nexus/.env${NC} com as tuas chaves"
echo -e "  2. Reinicia: ${CYAN}sudo systemctl restart nexus-api nexus-core${NC}"
echo -e "  3. Testa:    ${CYAN}curl http://localhost:8000/health${NC}"
echo -e "  4. Logs:     ${CYAN}journalctl -u nexus-api -u nexus-core -f${NC}"
echo ""
