#!/usr/bin/env bash
# NEXUS Installation Script for Ubuntu 22.04
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[NEXUS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC}   $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || err "Run as root: sudo bash install.sh"

log "Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

log "Installing system dependencies..."
apt-get install -y -qq \
    python3.11 python3.11-venv python3-pip \
    docker.io docker-compose-plugin \
    portaudio19-dev libsndfile1 ffmpeg espeak \
    git curl wget unzip

log "Enabling Docker..."
systemctl enable --now docker

log "Creating NEXUS user and directories..."
useradd -r -s /bin/bash -m nexus 2>/dev/null || true
mkdir -p /opt/nexus /data/nexus /var/log/nexus
chown -R nexus:nexus /opt/nexus /data/nexus /var/log/nexus
usermod -aG docker nexus

log "Cloning/updating repository..."
if [[ -d /opt/nexus/.git ]]; then
    git -C /opt/nexus pull --ff-only
else
    git clone https://github.com/sergioworkprt-ui/nexus-ia-pessoal.git /opt/nexus
fi

log "Creating Python virtual environment..."
python3.11 -m venv /opt/nexus/venv
/opt/nexus/venv/bin/pip install --no-cache-dir -r /opt/nexus/nexus/requirements.txt

log "Setting up .env file..."
if [[ ! -f /opt/nexus/.env ]]; then
    cp /opt/nexus/nexus/.env.example /opt/nexus/.env
    warn ".env created from example — edit /opt/nexus/.env before starting NEXUS"
fi

log "Installing systemd services..."
cat > /etc/systemd/system/nexus-api.service <<'EOF'
[Unit]
Description=NEXUS API Service
After=network.target

[Service]
Type=simple
User=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
ExecStart=/opt/nexus/venv/bin/uvicorn nexus.api.rest.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=append:/var/log/nexus/api.log
StandardError=append:/var/log/nexus/api.log

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/nexus-core.service <<'EOF'
[Unit]
Description=NEXUS Core Service
After=network.target nexus-api.service

[Service]
Type=simple
User=nexus
WorkingDirectory=/opt/nexus
EnvironmentFile=/opt/nexus/.env
ExecStart=/opt/nexus/venv/bin/python -m nexus.main
Restart=always
RestartSec=10
StandardOutput=append:/var/log/nexus/core.log
StandardError=append:/var/log/nexus/core.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nexus-api nexus-core

log "Installation complete!"
log "Next steps:"
log "  1. Edit /opt/nexus/.env with your API keys"
log "  2. sudo systemctl start nexus-api nexus-core"
log "  3. Check logs: journalctl -u nexus-api -f"
