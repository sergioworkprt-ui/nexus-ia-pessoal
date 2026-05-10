#!/usr/bin/env bash
# NEXUS Repair Script — resets state and restarts everything
set -euo pipefail

YELLOW='\033[1;33m'; GREEN='\033[0;32m'; NC='\033[0m'
log()  { echo -e "${GREEN}[NEXUS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

warn "This will restart all NEXUS services and clear runtime caches."
read -rp "Continue? [y/N] " ans
[[ $ans =~ ^[Yy]$ ]] || exit 0

log "Stopping services..."
systemctl stop nexus-core nexus-api || true

log "Clearing runtime cache..."
find /data/nexus -name '*.lock' -delete
find /opt/nexus/nexus -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

log "Checking Python environment..."
/opt/nexus/venv/bin/pip check || {
    warn "Dependency issues found — reinstalling..."
    /opt/nexus/venv/bin/pip install --no-cache-dir -r /opt/nexus/nexus/requirements.txt
}

log "Restarting services..."
systemctl daemon-reload
systemctl start nexus-api
sleep 5
systemctl start nexus-core

log "Repair complete. Logs:"
journalctl -u nexus-api -u nexus-core -n 30 --no-pager
