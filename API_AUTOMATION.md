# NEXUS Automation API

## Overview

The Automation API exposes secure endpoints under `/api/*` for CI/CD integrations, scripts, and external tools. Every request requires an `X-API-Key` header and is rate-limited and audit-logged.

## Authentication

All endpoints require:
```
X-API-Key: <your-automation-key>
```

### Generating an API Key

```bash
# Generate a cryptographically secure key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Add to /opt/nexus/.env
AUTOMATION_API_KEY=your-generated-key-here
```

Restart `nexus-api` after changing `.env`:
```bash
systemctl restart nexus-api
```

## Rate Limiting

| Setting | Default | Override via .env |
|---------|---------|-------------------|
| Requests per window | 60 | `AUTOMATION_RATE_LIMIT` |
| Window (seconds) | 60 | `AUTOMATION_RATE_WINDOW` |

On limit exceeded: HTTP 429 + `Retry-After` header.

## Endpoints

### GET /api/health

System health check with basic resource metrics.

```bash
curl -H "X-API-Key: $KEY" http://35.241.151.115:8000/api/health
```

Response:
```json
{
  "status": "ok",
  "message": "ok",
  "data": {"api": "ok", "cpu_percent": 12.4, "memory_percent": 68.2, "disk_percent": 45.1}
}
```

---

### POST /api/deploy

Trigger `deploy_vps.sh` on the server.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"commit": "abc123", "reason": "hotfix"}' \
     http://35.241.151.115:8000/api/deploy
```

Request body:
```json
{"commit": "HEAD", "reason": "scheduled-deploy"}
```

Response:
```json
{
  "status": "ok",
  "message": "deploy completed",
  "data": {"exit_code": 0, "stdout": "...", "stderr": ""}
}
```

---

### POST /api/rollback

Trigger `rollback.sh` on the server.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"commits_back": 1, "reason": "bad-deploy"}' \
     http://35.241.151.115:8000/api/rollback
```

---

### GET /api/logs

Fetch recent log lines from a named service log.

```bash
# Available services: core, api, dashboard, backup, autoheal, alerts, automation_audit
curl -H "X-API-Key: $KEY" \
     "http://35.241.151.115:8000/api/logs?service=core&lines=50"
```

Max `lines`: 500.

---

### GET /api/metrics

System resource metrics as JSON.

```bash
curl -H "X-API-Key: $KEY" http://35.241.151.115:8000/api/metrics
```

Response:
```json
{
  "status": "ok",
  "data": {
    "cpu_percent": 8.2,
    "memory_percent": 65.1,
    "memory_used_mb": 1050,
    "memory_total_mb": 1614,
    "disk_percent": 42.3,
    "disk_free_gb": 17.4,
    "load_avg": {"1m": 0.12, "5m": 0.08, "15m": 0.06}
  }
}
```

---

### GET /api/plugins

List all plugins and their enabled status.

```bash
curl -H "X-API-Key: $KEY" http://35.241.151.115:8000/api/plugins
```

---

### POST /api/plugins/enable

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"name": "example"}' \
     http://35.241.151.115:8000/api/plugins/enable
```

---

### POST /api/plugins/disable

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"name": "example"}' \
     http://35.241.151.115:8000/api/plugins/disable
```

---

## Prometheus Metrics

`GET /metrics` returns Prometheus exposition format (no auth required for scraping):

```bash
curl http://35.241.151.115:8000/metrics
```

```
# HELP nexus_cpu_percent CPU utilization percent
# TYPE nexus_cpu_percent gauge
nexus_cpu_percent 12.3

# HELP nexus_service_up Service is active (1) or inactive (0)
# TYPE nexus_service_up gauge
nexus_service_up{service="nexus-core"} 1
nexus_service_up{service="nexus-api"} 1
...
```

## Error Responses

| HTTP Code | Meaning |
|-----------|--------|
| 401 | Invalid or missing `X-API-Key` |
| 404 | Script not found on server |
| 429 | Rate limit exceeded |
| 503 | `AUTOMATION_API_KEY` not configured |
| 504 | Script timed out (120s) |

All errors return:
```json
{"detail": {"error": "description of the problem"}}
```

## Audit Log

All API calls are logged to `/opt/nexus/logs/automation_audit.log`:
```
[2026-05-13T10:00:00Z] [AUDIT] action=POST /api/deploy ip=1.2.3.4 commit=abc123 reason=hotfix
```

Access via API:
```bash
curl -H "X-API-Key: $KEY" "http://VPS:8000/api/logs?service=automation_audit&lines=100"
```

## Best Practices

- Rotate `AUTOMATION_API_KEY` every 90 days
- Use a dedicated key per automation tool (CI, scripts, n8n)
- Monitor the audit log for unexpected calls
- Set `AUTOMATION_RATE_LIMIT` higher for batch operations
- Always use HTTPS in production (nginx/caddy reverse proxy with TLS)
