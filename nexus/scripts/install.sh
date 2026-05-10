#!/usr/bin/env bash
# =============================================================================
# NEXUS AI — VPS Installer (Ubuntu 22.04+)
# Usage:
#   sudo bash install.sh              # full install
#   sudo bash install.sh --safe-mode  # skip apt packages (already installed)
#   sudo bash install.sh --update     # re-deploy code + restart services
# =============================================================================
set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
info() { echo -e "${BLUE}[--]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
die()  { echo -e "${RED}[ERR]${NC} $*" >&2; exit 1; }

# ── flags ────────────────────────────────────────────────────────────────────
SAFE_MODE=false
UPDATE_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --safe-mode)  SAFE_MODE=true ;;
    --update)     UPDATE_ONLY=true ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

# ── paths ────────────────────────────────────────────────────────────────────
NEXUS_HOME=/opt/nexus
VENV=$NEXUS_HOME/venv
LOG_DIR=/var/log/nexus
DATA_DIR=/data/nexus
FRONTEND=$NEXUS_HOME/nexus/dashboard/frontend
SERVICE_USER=nexus

echo -e "\n${BLUE}══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   NEXUS AI — Instalador VPS${NC}"
echo -e "${BLUE}══════════════════════════════════════════════${NC}\n"

# ── 1. System packages ───────────────────────────────────────────────────────
install_pkg() {
  local pkg=$1
  if dpkg -s "$pkg" &>/dev/null; then
    info "$pkg already installed"
  else
    info "Installing $pkg…"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$pkg" || \
      warn "Could not install $pkg — continuing"
  fi
}

if [[ $SAFE_MODE == false && $UPDATE_ONLY == false ]]; then
  info "Updating apt cache…"
  apt-get update -qq

  for pkg in python3 python3-pip python3-venv python3-dev \
              build-essential libssl-dev libffi-dev \
              git curl wget ca-certificates gnupg lsb-release \
              ffmpeg portaudio19-dev \
              systemd; do
    install_pkg "$pkg"
  done

  # Node.js 20 via NodeSource
  if ! command -v node &>/dev/null || [[ $(node --version | cut -d. -f1 | tr -d v) -lt 20 ]]; then
    info "Installing Node.js 20…"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    install_pkg nodejs
  else
    ok "Node.js $(node --version) already present"
  fi
  ok "System packages ready"
else
  warn "Skipping apt packages (safe/update mode)"
fi

# ── 2. System user ───────────────────────────────────────────────────────────
if ! id -u $SERVICE_USER &>/dev/null; then
  info "Creating system user '$SERVICE_USER'…"
  useradd --system --shell /usr/sbin/nologin --home-dir $NEXUS_HOME \
    --create-home --groups audio $SERVICE_USER
  ok "User $SERVICE_USER created"
else
  ok "User $SERVICE_USER already exists"
fi

# ── 3. Directories ───────────────────────────────────────────────────────────
for d in "$NEXUS_HOME" "$LOG_DIR" "$DATA_DIR" "$DATA_DIR/memory" "$DATA_DIR/tasks" "$DATA_DIR/evolution"; do
  mkdir -p "$d"
done
chown -R $SERVICE_USER:$SERVICE_USER "$LOG_DIR" "$DATA_DIR"
chmod -R 775 "$LOG_DIR" "$DATA_DIR"
ok "Directories ready"

# ── 4. Clone / update code ───────────────────────────────────────────────────
if [[ ! -d $NEXUS_HOME/.git ]]; then
  info "Cloning NEXUS repository…"
  git clone https://github.com/sergioworkprt-ui/nexus-ia-pessoal.git $NEXUS_HOME
  cd $NEXUS_HOME
  git checkout claude/create-test-file-d1AY6
else
  info "Updating NEXUS code…"
  cd $NEXUS_HOME
  git fetch origin
  git checkout claude/create-test-file-d1AY6
  git pull origin claude/create-test-file-d1AY6
fi
chown -R $SERVICE_USER:$SERVICE_USER $NEXUS_HOME
ok "Code up to date"

# ── 5. Python venv + dependencies ────────────────────────────────────────────
if [[ ! -d $VENV ]]; then
  info "Creating Python venv…"
  python3 -m venv $VENV
fi
info "Installing Python dependencies…"
$VENV/bin/pip install --quiet --upgrade pip
$VENV/bin/pip install --quiet -r $NEXUS_HOME/nexus/requirements.txt
chown -R $SERVICE_USER:$SERVICE_USER $VENV
ok "Python venv ready"

# ── 6. Build React frontend ───────────────────────────────────────────────────
if [[ -d $FRONTEND ]]; then
  info "Building React dashboard…"
  cat > "$FRONTEND/.env.local" <<EOF
VITE_API_URL=http://localhost:8000
EOF
  cd $FRONTEND
  npm ci --silent
  npm run build --silent
  chown -R $SERVICE_USER:$SERVICE_USER "$FRONTEND/dist"
  ok "React dashboard built → $FRONTEND/dist"
else
  warn "Frontend directory not found at $FRONTEND — skipping build"
fi

# ── 7. Environment file ───────────────────────────────────────────────────────
ENV_FILE=$NEXUS_HOME/.env
if [[ ! -f $ENV_FILE ]]; then
  info "Creating .env template…"
  cat > "$ENV_FILE" <<'EOF'
# NEXUS AI — Environment Configuration
# Copy this file and fill in your secrets.

# ── Core ──────────────────────────────────────────────────────────────────────
SECRET_KEY=CHANGE_ME_use_openssl_rand_hex_32
NEXUS_PIN=                        # leave empty to set on first login

# ── AI Providers ──────────────────────────────────────────────────────────────
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# ── Trading ───────────────────────────────────────────────────────────────────
XTB_ACCOUNT_ID=
XTB_PASSWORD=
XTB_MODE=demo                      # demo | real

IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# ── Services ──────────────────────────────────────────────────────────────────
SERP_API_KEY=                       # for TruthChecker web search

# ── Paths (do not change unless you know what you're doing) ───────────────────
LOG_DIR=/var/log/nexus
DATA_DIR=/data/nexus
NEXUS_API_URL=http://localhost:8000
DASHBOARD_PORT=9000
EOF
  chown $SERVICE_USER:$SERVICE_USER "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  ok ".env template created at $ENV_FILE"
else
  # Ensure LOG_DIR is absolute in existing .env
  if grep -q 'LOG_DIR=logs' "$ENV_FILE" 2>/dev/null; then
    sed -i 's|LOG_DIR=logs|LOG_DIR=/var/log/nexus|g' "$ENV_FILE"
    warn "Fixed relative LOG_DIR in $ENV_FILE → /var/log/nexus"
  fi
  ok ".env already exists — not overwritten"
fi

# ── 8. Systemd services ───────────────────────────────────────────────────────
write_service() {
  local name=$1 desc=$2 exec_start=$3 after=${4:-network.target}
  cat > "/etc/systemd/system/${name}.service" <<EOF
[Unit]
Description=$desc
After=$after
Wants=$after

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$NEXUS_HOME
EnvironmentFile=$ENV_FILE
Environment=PYTHONPATH=$NEXUS_HOME
Environment=LOG_DIR=$LOG_DIR
Environment=LOG_LEVEL=INFO
UMask=0002
ExecStart=$exec_start
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$name

[Install]
WantedBy=multi-user.target
EOF
  ok "Service $name written"
}

write_service \
  "nexus-api" \
  "NEXUS AI — REST API (port 8000)" \
  "$VENV/bin/uvicorn nexus.api.rest.main:app --host 0.0.0.0 --port 8000 --workers 1"

write_service \
  "nexus-core" \
  "NEXUS AI — Orchestrator Core" \
  "$VENV/bin/python -m nexus.main"

write_service \
  "nexus-dashboard" \
  "NEXUS AI — Dashboard (port 9000)" \
  "$VENV/bin/uvicorn nexus.dashboard.server:app --host 0.0.0.0 --port 9000 --workers 1" \
  "network.target nexus-api.service"

systemctl daemon-reload

for svc in nexus-api nexus-core nexus-dashboard; do
  systemctl enable "$svc"
done
ok "Systemd services enabled"

# ── 9. Start / restart services ───────────────────────────────────────────────
info "Starting NEXUS services…"
for svc in nexus-api nexus-core nexus-dashboard; do
  systemctl restart "$svc" && ok "$svc started" || warn "$svc failed to start — check: journalctl -u $svc -n 50"
done

# ── 10. Firewall (optional) ───────────────────────────────────────────────────
if command -v ufw &>/dev/null; then
  ufw allow 9000/tcp comment 'NEXUS Dashboard' 2>/dev/null || true
  ok "ufw: port 9000 open"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
SERVER_IP=$(hostname -I | awk '{print $1}')
echo -e "\n${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}   NEXUS AI instalado com sucesso!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "  Dashboard : ${BLUE}http://$SERVER_IP:9000${NC}"
echo -e "  API       : ${BLUE}http://$SERVER_IP:8000/docs${NC}"
echo -e "  Logs      : journalctl -u nexus-api -f"
echo -e "  Config    : $ENV_FILE\n"
echo -e "${YELLOW}IMPORTANTE:${NC} Edita $ENV_FILE e adiciona as tuas chaves API."
echo -e "Depois: sudo systemctl restart nexus-api nexus-core nexus-dashboard\n"
