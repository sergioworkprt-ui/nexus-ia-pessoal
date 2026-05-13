#!/usr/bin/env bash
# install_prometheus_grafana.sh — Install Prometheus, Node Exporter, and Grafana for NEXUS
# Usage: sudo bash nexus/scripts/install_prometheus_grafana.sh
# Override versions: PROM_VERSION=2.52.0 NEXUS_PORT=8000 sudo bash ...
set -euo pipefail

PROM_VERSION="${PROM_VERSION:-2.51.2}"
NODE_EXP_VERSION="${NODE_EXP_VERSION:-1.8.0}"
NEXUS_HOST="${NEXUS_HOST:-localhost}"
NEXUS_PORT="${NEXUS_PORT:-8000}"
NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
PROM_DIR="/opt/prometheus"
NODE_EXP_DIR="/opt/node_exporter"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64)  GO_ARCH="amd64" ;;
  aarch64) GO_ARCH="arm64" ;;
  armv7l)  GO_ARCH="armv7" ;;
  *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

check_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run as root or with sudo"
    exit 1
  fi
}

# ── STEP 1: System dependencies ──────────────────────────────────────────────
step1_deps() {
  log "STEP 1: Installing system dependencies"
  apt-get update -qq
  apt-get install -y -qq curl wget tar adduser libfontconfig1 apt-transport-https \
    software-properties-common gnupg2 ca-certificates
}

# ── STEP 2: Create prometheus system user ────────────────────────────────────
step2_user() {
  log "STEP 2: Creating prometheus system user"
  if ! id prometheus &>/dev/null; then
    useradd --no-create-home --shell /bin/false prometheus
  fi
  if ! id node_exporter &>/dev/null; then
    useradd --no-create-home --shell /bin/false node_exporter
  fi
}

# ── STEP 3: Install Prometheus ───────────────────────────────────────────────
step3_prometheus() {
  log "STEP 3: Installing Prometheus ${PROM_VERSION}"
  local url="https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-${GO_ARCH}.tar.gz"
  local tmp="/tmp/prometheus-${PROM_VERSION}.tar.gz"

  wget -q --show-progress -O "$tmp" "$url"
  tar -xzf "$tmp" -C /tmp

  mkdir -p "$PROM_DIR" /etc/prometheus /var/lib/prometheus
  cp "/tmp/prometheus-${PROM_VERSION}.linux-${GO_ARCH}/prometheus" /usr/local/bin/
  cp "/tmp/prometheus-${PROM_VERSION}.linux-${GO_ARCH}/promtool" /usr/local/bin/
  cp -r "/tmp/prometheus-${PROM_VERSION}.linux-${GO_ARCH}/consoles" /etc/prometheus/
  cp -r "/tmp/prometheus-${PROM_VERSION}.linux-${GO_ARCH}/console_libraries" /etc/prometheus/

  chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
  chmod +x /usr/local/bin/prometheus /usr/local/bin/promtool

  rm -rf "$tmp" "/tmp/prometheus-${PROM_VERSION}.linux-${GO_ARCH}"
  log "  Prometheus $(prometheus --version 2>&1 | head -1)"
}

# ── STEP 4: Write prometheus.yml ─────────────────────────────────────────────
step4_config() {
  log "STEP 4: Writing Prometheus configuration"
  cat > /etc/prometheus/prometheus.yml <<PROMCFG
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    monitor: 'nexus'

rule_files: []

alertmanager_configs: []

scrape_configs:
  - job_name: 'nexus-api'
    static_configs:
      - targets: ['${NEXUS_HOST}:${NEXUS_PORT}']
    metrics_path: '/metrics'
    scrape_interval: 15s
    scrape_timeout: 10s

  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
    scrape_interval: 15s

  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
PROMCFG

  chown prometheus:prometheus /etc/prometheus/prometheus.yml
  log "  Config written to /etc/prometheus/prometheus.yml"
}

# ── STEP 5: Create Prometheus systemd service ────────────────────────────────
step5_prometheus_service() {
  log "STEP 5: Creating Prometheus systemd service"
  cat > /etc/systemd/system/nexus-prometheus.service <<SVC
[Unit]
Description=Prometheus Monitoring (NEXUS)
After=network-online.target
Wants=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \\
  --config.file=/etc/prometheus/prometheus.yml \\
  --storage.tsdb.path=/var/lib/prometheus \\
  --storage.tsdb.retention.time=30d \\
  --web.console.templates=/etc/prometheus/consoles \\
  --web.console.libraries=/etc/prometheus/console_libraries \\
  --web.listen-address=127.0.0.1:9090 \\
  --web.enable-lifecycle
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

  systemctl daemon-reload
  systemctl enable nexus-prometheus
  systemctl restart nexus-prometheus
  sleep 3
  if systemctl is-active --quiet nexus-prometheus; then
    log "  Prometheus active on 127.0.0.1:9090"
  else
    log "  WARNING: Prometheus may not have started — check: journalctl -u nexus-prometheus -n 30"
  fi
}

# ── STEP 6: Install Node Exporter ────────────────────────────────────────────
step6_node_exporter() {
  log "STEP 6: Installing Node Exporter ${NODE_EXP_VERSION}"
  local url="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXP_VERSION}/node_exporter-${NODE_EXP_VERSION}.linux-${GO_ARCH}.tar.gz"
  local tmp="/tmp/node_exporter-${NODE_EXP_VERSION}.tar.gz"

  wget -q --show-progress -O "$tmp" "$url"
  tar -xzf "$tmp" -C /tmp
  cp "/tmp/node_exporter-${NODE_EXP_VERSION}.linux-${GO_ARCH}/node_exporter" /usr/local/bin/
  chown node_exporter:node_exporter /usr/local/bin/node_exporter
  chmod +x /usr/local/bin/node_exporter
  rm -rf "$tmp" "/tmp/node_exporter-${NODE_EXP_VERSION}.linux-${GO_ARCH}"

  cat > /etc/systemd/system/nexus-node-exporter.service <<SVC
[Unit]
Description=Node Exporter (NEXUS)
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter --web.listen-address=127.0.0.1:9100
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

  systemctl daemon-reload
  systemctl enable nexus-node-exporter
  systemctl restart nexus-node-exporter
  sleep 2
  if systemctl is-active --quiet nexus-node-exporter; then
    log "  Node Exporter active on 127.0.0.1:9100"
  else
    log "  WARNING: Node Exporter may not have started — check: journalctl -u nexus-node-exporter -n 30"
  fi
}

# ── STEP 7: Install Grafana ──────────────────────────────────────────────────
step7_grafana() {
  log "STEP 7: Installing Grafana from APT"
  mkdir -p /etc/apt/keyrings
  wget -q -O /etc/apt/keyrings/grafana.gpg \
    https://apt.grafana.com/gpg.key
  echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
    > /etc/apt/sources.list.d/grafana.list
  apt-get update -qq
  apt-get install -y -qq grafana
  systemctl daemon-reload
  systemctl enable grafana-server
  systemctl restart grafana-server
  sleep 4
  if systemctl is-active --quiet grafana-server; then
    log "  Grafana active on 127.0.0.1:3000 (admin/admin)"
  else
    log "  WARNING: Grafana may not have started — check: journalctl -u grafana-server -n 30"
  fi
}

# ── STEP 8: Auto-provision Grafana datasource ────────────────────────────────
step8_provisioning() {
  log "STEP 8: Provisioning Grafana datasource for Prometheus"
  local prov_dir="/etc/grafana/provisioning/datasources"
  mkdir -p "$prov_dir"
  cat > "${prov_dir}/nexus-prometheus.yaml" <<DS
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:9090
    isDefault: true
    editable: false
DS

  local dash_prov_dir="/etc/grafana/provisioning/dashboards"
  mkdir -p "$dash_prov_dir" /var/lib/grafana/dashboards
  cat > "${dash_prov_dir}/nexus-dashboards.yaml" <<DP
apiVersion: 1
providers:
  - name: NEXUS
    orgId: 1
    folder: NEXUS
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
DP

  # Basic NEXUS overview dashboard JSON
  cat > /var/lib/grafana/dashboards/nexus-overview.json <<'DASH'
{
  "title": "NEXUS Overview",
  "uid": "nexus-overview",
  "schemaVersion": 38,
  "refresh": "30s",
  "panels": [
    {
      "type": "stat",
      "title": "CPU Usage",
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
      "targets": [{"expr": "nexus_cpu_percent", "datasource": "Prometheus"}],
      "fieldConfig": {"defaults": {"unit": "percent", "thresholds": {"steps": [{"color": "green", "value": null}, {"color": "yellow", "value": 60}, {"color": "red", "value": 80}]}}}
    },
    {
      "type": "stat",
      "title": "RAM Usage",
      "gridPos": {"h": 4, "w": 6, "x": 6, "y": 0},
      "targets": [{"expr": "nexus_ram_percent", "datasource": "Prometheus"}],
      "fieldConfig": {"defaults": {"unit": "percent", "thresholds": {"steps": [{"color": "green", "value": null}, {"color": "yellow", "value": 60}, {"color": "red", "value": 80}]}}}
    },
    {
      "type": "stat",
      "title": "Disk Usage",
      "gridPos": {"h": 4, "w": 6, "x": 12, "y": 0},
      "targets": [{"expr": "nexus_disk_percent", "datasource": "Prometheus"}],
      "fieldConfig": {"defaults": {"unit": "percent", "thresholds": {"steps": [{"color": "green", "value": null}, {"color": "yellow", "value": 70}, {"color": "red", "value": 90}]}}}
    },
    {
      "type": "stat",
      "title": "Uptime (seconds)",
      "gridPos": {"h": 4, "w": 6, "x": 18, "y": 0},
      "targets": [{"expr": "nexus_uptime_seconds", "datasource": "Prometheus"}],
      "fieldConfig": {"defaults": {"unit": "s"}}
    },
    {
      "type": "timeseries",
      "title": "HTTP Requests / minute",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
      "targets": [{"expr": "rate(nexus_http_requests_total[1m]) * 60", "legendFormat": "{{method}} {{path}}", "datasource": "Prometheus"}]
    },
    {
      "type": "timeseries",
      "title": "HTTP Error Rate",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
      "targets": [{"expr": "rate(nexus_http_errors_total[1m]) * 60", "legendFormat": "{{path}}", "datasource": "Prometheus"}]
    },
    {
      "type": "gauge",
      "title": "WebSocket Connections",
      "gridPos": {"h": 4, "w": 8, "x": 0, "y": 12},
      "targets": [{"expr": "nexus_websocket_connections", "datasource": "Prometheus"}],
      "fieldConfig": {"defaults": {"min": 0, "max": 100}}
    },
    {
      "type": "timeseries",
      "title": "Request Latency p99 (ms)",
      "gridPos": {"h": 4, "w": 16, "x": 8, "y": 12},
      "targets": [{"expr": "nexus_request_latency_p99_ms", "legendFormat": "{{path}}", "datasource": "Prometheus"}]
    }
  ],
  "time": {"from": "now-3h", "to": "now"}
}
DASH

  chown -R grafana:grafana /var/lib/grafana/dashboards /etc/grafana/provisioning
  systemctl restart grafana-server
  log "  Dashboards provisioned in /var/lib/grafana/dashboards/"
}

# ── STEP 9: Wait for Grafana API and set admin password ──────────────────────
step9_grafana_ready() {
  log "STEP 9: Waiting for Grafana to become ready"
  local attempts=0
  until curl -sf http://127.0.0.1:3000/api/health | grep -q '"database": "ok"' || [[ $attempts -ge 20 ]]; do
    sleep 3
    ((attempts++))
  done
  if [[ $attempts -ge 20 ]]; then
    log "  WARNING: Grafana not fully ready yet — may need a moment after install"
  else
    log "  Grafana is ready"
  fi
}

# ── STEP 10: Summary ─────────────────────────────────────────────────────────
step10_summary() {
  log "STEP 10: Installation complete"
  echo
  echo "════════════════════════════════════════════════════════"
  echo "  NEXUS Prometheus + Grafana Installation Summary"
  echo "════════════════════════════════════════════════════════"
  echo
  printf "  %-30s %s\n" "Prometheus:" "http://127.0.0.1:9090  (local only)"
  printf "  %-30s %s\n" "Node Exporter:" "http://127.0.0.1:9100  (local only)"
  printf "  %-30s %s\n" "Grafana:" "http://127.0.0.1:3000  (admin/admin)"
  printf "  %-30s %s\n" "NEXUS /metrics:" "http://${NEXUS_HOST}:${NEXUS_PORT}/metrics"
  echo
  echo "  SSH Tunnel to Grafana:"
  echo "    ssh -L 3000:127.0.0.1:3000 user@your-server"
  echo "    → then open http://localhost:3000"
  echo
  echo "  SSH Tunnel to Prometheus:"
  echo "    ssh -L 9090:127.0.0.1:9090 user@your-server"
  echo "    → then open http://localhost:9090"
  echo
  echo "  Services:"
  for svc in nexus-prometheus nexus-node-exporter grafana-server; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    printf "    %-35s %s\n" "$svc" "$status"
  done
  echo
  echo "  IMPORTANT: Change Grafana admin password!"
  echo "    http://localhost:3000 → Profile → Change Password"
  echo "════════════════════════════════════════════════════════"
}

main() {
  check_root
  step1_deps
  step2_user
  step3_prometheus
  step4_config
  step5_prometheus_service
  step6_node_exporter
  step7_grafana
  step8_provisioning
  step9_grafana_ready
  step10_summary
}

main "$@"
