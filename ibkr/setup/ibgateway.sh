#!/bin/bash
# Launches IB Gateway with virtual display
export DISPLAY=:99

# Start virtual display if not running
if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :99 -screen 0 1024x768x24 -ac &
    sleep 2
fi

exec /opt/ibgateway/ibgateway -J-Xmx512m
