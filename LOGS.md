# NEXUS Structured Logging + ELK Stack

## Overview

NEXUS emits structured JSON logs via `nexus/services/logger/structured.py`. Every HTTP request is logged with method, path, status, duration, and client IP. Logs can be shipped to an ELK Stack (Elasticsearch + Logstash + Kibana) for search, visualization, and alerting.

## Log Format

Every log line is a JSON object:

```json
{"timestamp": "2026-05-13T10:00:00+00:00", "level": "INFO", "logger": "nexus.http", "message": "GET /health 200", "method": "GET", "path": "/health", "status": 200, "duration_ms": 1.4, "client": "1.2.3.4"}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO8601 | UTC timestamp |
| `level` | string | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `logger` | string | Logger name (e.g. `nexus.http`, `nexus.api`) |
| `message` | string | Human-readable message |
| `method` | string | HTTP method (on HTTP log lines) |
| `path` | string | HTTP path |
| `status` | int | HTTP status code |
| `duration_ms` | float | Request duration in milliseconds |
| `client` | string | Client IP address |

## Querying Logs

### On VPS (direct files)

```bash
# Tail all logs
tail -f /opt/nexus/logs/core.log

# Filter by level
grep '"level": "ERROR"' /opt/nexus/logs/core.log | jq .

# Filter HTTP errors
grep '"status": 5' /opt/nexus/logs/core.log | jq '{ts: .timestamp, path: .path, status: .status}'

# Slow requests (> 500ms)
cat /opt/nexus/logs/core.log | python3 -c "
import json, sys
for line in sys.stdin:
    try:
        d = json.loads(line)
        if d.get('duration_ms', 0) > 500:
            print(json.dumps(d))
    except: pass
"

# Recent automation API calls
tail -50 /opt/nexus/logs/automation_audit.log

# Alert history
tail -100 /opt/nexus/logs/alerts.log
```

### Via Automation API

```bash
curl -H "X-API-Key: $KEY" "http://VPS:8000/api/logs?service=core&lines=100"
curl -H "X-API-Key: $KEY" "http://VPS:8000/api/logs?service=alerts&lines=50"
```

## ELK Stack Installation

```bash
ssh user@35.241.151.115
sudo bash /opt/nexus/scripts/install_elk.sh
```

This installs Elasticsearch 8, Logstash, and Kibana on the VPS.

**Resource requirements**: at least 2GB RAM (ELK heap is set to 512MB by default).

Override heap:
```bash
ELK_HEAP=1g sudo bash install_elk.sh
```

## Accessing Kibana

Kibana runs on `127.0.0.1:5601` (localhost only). Access via SSH tunnel:

```bash
ssh -L 5601:127.0.0.1:5601 user@35.241.151.115
```

Then open: **http://localhost:5601**

## Setting Up Kibana

### 1. Create Data View
1. Menu → **Discover** → **Create data view**
2. Name: `NEXUS Logs`
3. Index pattern: `nexus-logs-*`
4. Timestamp field: `@timestamp`
5. Click **Save data view to Kibana**

### 2. Useful KQL Queries

```kql
# All errors
level: "ERROR"

# HTTP 5xx responses
status >= 500

# Slow requests (>200ms)
duration_ms > 200

# Deploy events
log_module: "DR" OR log_module: "BACKUP" OR log_module: "AUTOHEAL"

# Alert events
log_module: "ALERT"

# Specific path
path: "/chat"

# Combined
level: "ERROR" AND path: "/api/*"
```

### 3. Creating Dashboards

1. Menu → **Dashboard** → **Create dashboard**
2. **Add panel** → **Aggregation based**
3. Suggested visualizations:
   - **Line chart**: Request count over time (`@timestamp` x-axis, `count` y-axis)
   - **Bar chart**: Errors by path (`path` terms, count)
   - **Metric**: Total requests today
   - **Data table**: Top 10 slowest paths (avg `duration_ms`, grouped by `path`)

### 4. Creating Alerts

1. Menu → **Rules** → **Create rule**
2. Type: **Elasticsearch query**
3. Example — Alert when > 10 errors in 5 minutes:
   ```json
   {"query": {"bool": {"must": [{"term": {"level": "ERROR"}}]}},
    "size": 0, "aggs": {"error_count": {"value_count": {"field": "level"}}}}
   ```
4. Threshold: `error_count > 10`
5. Action: Email or webhook notification

## Log Retention

| Log type | Location | Retention |
|----------|----------|----------|
| VPS files | `/opt/nexus/logs/*.log` | Manual / logrotate |
| Elasticsearch | `nexus-logs-*` indices | 30 days (ILM policy) |
| Backup log | `/opt/nexus/logs/backup.log` | Indefinite |
| Audit log | `/opt/nexus/logs/automation_audit.log` | Indefinite |

### Set up logrotate on VPS

```bash
cat > /etc/logrotate.d/nexus << 'EOF'
/opt/nexus/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 640 root root
}
EOF
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Elasticsearch won't start | Check heap: `journalctl -u elasticsearch -n 30` |
| No logs in Kibana | Verify Logstash: `curl http://127.0.0.1:9600` |
| Index not created | Check `sincedb`: `ls /var/lib/logstash/nexus_sincedb` |
| Kibana 502 | Wait 60s; Kibana takes time to start |
| Too much disk usage | Reduce ILM retention or add disk space |
