# NEXUS Metrics — Prometheus + Grafana

This document describes the metrics exposed by NEXUS, how to install Prometheus and Grafana, and how to access dashboards.

---

## Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `nexus_cpu_percent` | gauge | CPU usage percentage (0–100) |
| `nexus_ram_percent` | gauge | RAM usage percentage (0–100) |
| `nexus_ram_used_mb` | gauge | RAM used in megabytes |
| `nexus_ram_total_mb` | gauge | Total RAM in megabytes |
| `nexus_disk_percent` | gauge | Root disk usage percentage |
| `nexus_disk_used_gb` | gauge | Root disk used in gigabytes |
| `nexus_disk_total_gb` | gauge | Root disk total in gigabytes |
| `nexus_load_1m` | gauge | System load average (1 minute) |
| `nexus_load_5m` | gauge | System load average (5 minutes) |
| `nexus_load_15m` | gauge | System load average (15 minutes) |
| `nexus_uptime_seconds` | gauge | NEXUS API uptime in seconds |
| `nexus_websocket_connections` | gauge | Active WebSocket connections |
| `nexus_service_up` | gauge | Service health: 1=up, 0=down (label: `service`) |
| `nexus_http_requests_total` | counter | Total HTTP requests (labels: `method`, `path`, `status`) |
| `nexus_http_errors_total` | counter | Total HTTP 5xx errors (label: `path`) |
| `nexus_request_latency_p99_ms` | gauge | p99 request latency in milliseconds (label: `path`) |

---

## Installation

### Install Prometheus + Grafana

```bash
# On your NEXUS server (requires sudo)
sudo bash nexus/scripts/install_prometheus_grafana.sh
```

**What it installs:**
- Prometheus `v2.51.2` — scrapes `/metrics` every 15s, stores 30 days of data
- Node Exporter `v1.8.0` — exposes system-level OS metrics
- Grafana (latest stable from APT) — pre-configured with Prometheus datasource and NEXUS overview dashboard

**Systemd services created:**
- `nexus-prometheus` (port 9090, localhost only)
- `nexus-node-exporter` (port 9100, localhost only)
- `grafana-server` (port 3000, localhost only)

All services bind to `127.0.0.1` only — use SSH tunnels to access them remotely.

---

## Accessing Grafana

Grafana listens on `127.0.0.1:3000` — not exposed to the internet.

### SSH Tunnel

```bash
# Open tunnel (keep terminal open)
ssh -L 3000:127.0.0.1:3000 user@your-server

# Then open in browser
open http://localhost:3000
```

**Default credentials:** `admin` / `admin` (change on first login).

A pre-built **NEXUS Overview** dashboard is available under `Dashboards → NEXUS`.

---

## Accessing Prometheus

```bash
# Open tunnel
ssh -L 9090:127.0.0.1:9090 user@your-server

# Open UI
open http://localhost:9090

# Quick query examples
curl -s 'http://localhost:9090/api/v1/query?query=nexus_cpu_percent' | jq '.data.result'
curl -s 'http://localhost:9090/api/v1/query?query=rate(nexus_http_requests_total[5m])' | jq .
```

---

## Accessing /metrics Directly

The NEXUS API exposes metrics at `GET /metrics` in Prometheus exposition format:

```bash
curl http://localhost:8000/metrics
```

Example output:
```
# HELP nexus_cpu_percent CPU usage percent
# TYPE nexus_cpu_percent gauge
nexus_cpu_percent 12.4

# HELP nexus_http_requests_total Total HTTP requests
# TYPE nexus_http_requests_total counter
nexus_http_requests_total{method="GET",path="/health",status="200"} 4821
```

---

## Creating Dashboards in Grafana

1. Open Grafana at `http://localhost:3000`
2. Go to **Dashboards → New → New Dashboard**
3. Click **Add visualization**
4. Select **Prometheus** as data source
5. Enter a PromQL query, e.g.:
   - CPU: `nexus_cpu_percent`
   - Request rate: `rate(nexus_http_requests_total[5m]) * 60`
   - Error rate: `rate(nexus_http_errors_total[5m]) * 60`
   - Latency p99: `nexus_request_latency_p99_ms`
6. Save the dashboard

### Recommended panels

| Panel | Query | Visualization |
|-------|-------|---------------|
| CPU % | `nexus_cpu_percent` | Gauge / Stat |
| RAM % | `nexus_ram_percent` | Gauge / Stat |
| Disk % | `nexus_disk_percent` | Gauge / Stat |
| Request rate | `rate(nexus_http_requests_total[1m])*60` | Time series |
| Error rate | `rate(nexus_http_errors_total[1m])*60` | Time series |
| Latency p99 | `nexus_request_latency_p99_ms` | Time series |
| WS connections | `nexus_websocket_connections` | Gauge |
| Service health | `nexus_service_up` | Stat (per label) |

---

## Adding New Metrics

New metrics are added in `nexus/api/rest/prometheus_metrics.py`.

### 1. Add a gauge

```python
# In prometheus_metrics.py, inside prometheus_metrics()
out += _g("nexus_my_metric", "gauge", "Description", my_value)
```

### 2. Add a counter with labels

```python
# In the _request_count dict (already done for HTTP requests):
_request_count[(method, path, str(status))] = \
    _request_count.get((method, path, str(status)), 0) + 1

# Then render it:
for (method, path, status), val in _request_count.items():
    out.append(f'nexus_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {val}\n')
```

### 3. Record from middleware

`record_request(method, path, status, duration)` is called automatically by the HTTP middleware in `main.py`. Add any new recording logic there.

---

## Metrics Audit Workflow

The `.github/workflows/metrics-audit.yml` workflow runs every Monday at 09:00 UTC.

**What it does:**
1. Calls `GET /metrics` on the NEXUS API
2. Validates that all required metrics are present
3. Generates a Markdown audit report with current metric values
4. Uploads both the raw snapshot and the report as a 90-day artifact
5. Checks Prometheus/Grafana service status
6. Sends an alert if anything fails

**Trigger manually:**
```bash
gh workflow run metrics-audit.yml
```

**Download latest snapshot:**
```bash
gh run download --name metrics-snapshot-<run-number>
```

---

## Service Management

```bash
# Status
systemctl status nexus-prometheus nexus-node-exporter grafana-server

# Restart
sudo systemctl restart nexus-prometheus
sudo systemctl restart grafana-server

# Logs
journalctl -u nexus-prometheus -f
journalctl -u grafana-server -f

# Reload Prometheus config without restart
curl -X POST http://localhost:9090/-/reload
```

---

## Data Retention

| Store | Default retention | Override |
|-------|-------------------|----------|
| Prometheus TSDB | 30 days | `--storage.tsdb.retention.time=60d` in systemd unit |
| Grafana SQLite | Indefinite | Managed via Grafana Admin → Data Management |
| `/metrics` snapshot (CI) | 90 days | `retention-days` in `metrics-audit.yml` |
