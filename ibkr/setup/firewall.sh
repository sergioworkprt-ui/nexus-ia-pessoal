#!/bin/bash
# Configure UFW to allow IBKR API ports only from NEXUS IP
NEXUS_IP="${1:-CHANGE_ME}"

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                                   # SSH
ufw allow from "${NEXUS_IP}" to any port 7497 proto tcp  # Paper API
ufw allow from "${NEXUS_IP}" to any port 7496 proto tcp  # Live API
ufw --force enable

echo "Firewall active. IBKR ports open only for: ${NEXUS_IP}"
ufw status verbose
