#!/bin/bash
# Watchdog: restart services if they die
LOG="/var/log/nexus/watchdog.log"
mkdir -p /var/log/nexus

while true; do
    for svc in nexus-ibgateway nexus-ibkr; do
        if ! systemctl is-active --quiet "${svc}"; then
            echo "$(date -u '+%Y-%m-%d %H:%M:%S') [watchdog] ${svc} DOWN — restarting" >> "${LOG}"
            systemctl restart "${svc}"
        fi
    done
    sleep 30
done
