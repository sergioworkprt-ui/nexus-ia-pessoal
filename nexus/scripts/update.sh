#!/usr/bin/env bash
# NEXUS Update Script
set -euo pipefail

GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[NEXUS]${NC} $*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

log "Stopping services..."
systemctl stop nexus-core nexus-api || true

log "Pulling latest code..."
git -C /opt/nexus pull --ff-only

log "Updating Python dependencies..."
/opt/nexus/venv/bin/pip install --no-cache-dir -r /opt/nexus/nexus/requirements.txt

log "Restarting services..."
systemctl start nexus-api
sleep 3
systemctl start nexus-core

log "Update complete. Status:"
systemctl status nexus-api nexus-core --no-pager -l
