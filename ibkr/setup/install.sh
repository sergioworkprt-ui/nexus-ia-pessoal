#!/bin/bash
# =============================================================
# NEXUS-IBKR VPS Setup Script
# Run as root on Ubuntu 22.04+
# Usage: bash install.sh <nexus_ip>
# =============================================================
set -e

NEXUS_IP="${1:-CHANGE_ME}"
INSTALL_DIR="/opt/nexus-ibkr"
VENV="/opt/nexus-venv"
IB_VERSION="10.19.2b"
IB_INSTALLER="ibgateway-${IB_VERSION}-standalone-linux-x64.sh"
IB_URL="https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/${IB_INSTALLER}"

echo "[1/6] Installing system dependencies"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    xvfb x11vnc wget curl unzip ufw \
    openjdk-11-jre-headless

echo "[2/6] Downloading IB Gateway ${IB_VERSION}"
wget -q -O /tmp/${IB_INSTALLER} "${IB_URL}"
chmod +x /tmp/${IB_INSTALLER}

echo "[3/6] Installing IB Gateway (headless)"
Xvfb :99 -screen 0 1024x768x24 -ac &
XVFB_PID=$!
export DISPLAY=:99
sleep 2
/tmp/${IB_INSTALLER} -q -dir /opt/ibgateway || true
kill $XVFB_PID 2>/dev/null || true

echo "[4/6] Setting up Python environment"
mkdir -p ${INSTALL_DIR}
cp -r /opt/nexus-ia-pessoal/ibkr/* ${INSTALL_DIR}/ 2>/dev/null || true
python3 -m venv ${VENV}
${VENV}/bin/pip install --quiet --upgrade pip
${VENV}/bin/pip install --quiet -r ${INSTALL_DIR}/requirements.txt

echo "[5/6] Installing systemd services"
cp ${INSTALL_DIR}/setup/nexus-ibgateway.service /etc/systemd/system/
cp ${INSTALL_DIR}/setup/nexus-ibkr.service      /etc/systemd/system/
cp ${INSTALL_DIR}/setup/nexus-watchdog.service  /etc/systemd/system/
systemctl daemon-reload
systemctl enable nexus-ibgateway nexus-ibkr nexus-watchdog

echo "[6/6] Configuring firewall"
bash ${INSTALL_DIR}/setup/firewall.sh ${NEXUS_IP}

echo ""
echo "=== Install complete ==="
echo "Next: configure /opt/ibgateway/jts.ini then:"
echo "  systemctl start nexus-ibgateway"
echo "  systemctl start nexus-ibkr"
