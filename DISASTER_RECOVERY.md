# NEXUS Disaster Recovery

## Overview

`disaster_recovery.sh` performs a complete system restore from the most recent local backup in 10 automated steps. It handles: integrity check, service shutdown, pre-DR snapshot, extraction, .env restoration, dependency reinstall, dashboard rebuild, service restart, and health validation.

## When to Use DR

| Scenario | Recommended Action |
|---------|-------------------|
| VPS data corruption | Full DR |
| OS reinstall | Full DR + manual .env fill |
| Accidental deletion of code | Full DR |
| Failed deploy/migration | Try `rollback.sh` first |
| Service won’t start | Check logs, then rollback |

## Automatic DR (GitHub Actions)

1. Go to **Actions → Disaster Recovery**
2. Click **Run workflow**
3. Type `CONFIRM` in the confirmation field (required — double confirmation)
4. Enter the reason (e.g. "VPS disk corruption")
5. Click **Run workflow**

The workflow:
- Validates the `CONFIRM` input before proceeding
- Runs `disaster_recovery.sh` on the VPS via SSH
- Uploads the full recovery report as a GitHub artifact (retained 365 days)

## Manual DR Steps

```bash
ssh user@35.241.151.115
cd /opt/nexus

# 1. Find latest backup
ls -lt backups/nexus_backup_*.tar.gz | head -5

# 2. Verify integrity
sha256sum -c backups/nexus_backup_TIMESTAMP.tar.gz.sha256

# 3. Stop services
systemctl stop nexus-core nexus-api nexus-dashboard nexus-ws

# 4. Extract backup
tar -xzf backups/nexus_backup_TIMESTAMP.tar.gz -C /opt

# 5. Check .env
ls -la .env && head -5 .env

# 6. Reinstall Python deps
venv/bin/pip install -r nexus/requirements.txt

# 7. Rebuild dashboard
bash nexus/scripts/rebuild_dashboard.sh 35.241.151.115

# 8. Start services
systemctl start nexus-core nexus-api nexus-dashboard nexus-ws

# 9. Validate
bash nexus/scripts/health_check.sh
```

## Run DR Automatically

```bash
bash /opt/nexus/scripts/disaster_recovery.sh
```

The script generates a report at `/tmp/nexus_dr_report_TIMESTAMP.md`.

## Validating Recovery

```bash
# All services active?
systemctl is-active nexus-core nexus-api nexus-dashboard

# API responding?
curl http://localhost:8000/health

# Dashboard accessible?
curl -I http://localhost:9000

# Check logs for errors
journalctl -u nexus-core -n 30
```

## Testing DR Without Affecting Production

**Safe test procedure:**

1. Provision a test VM (same OS as VPS)
2. Copy a backup from production: `scp user@vps:/opt/nexus/backups/latest.tar.gz .`
3. Extract and run `disaster_recovery.sh` in isolation
4. Verify health check passes

**Never run DR on production unless data is already compromised.**

## Recovery Time Estimates

| Step | Duration |
|------|----------|
| Backup integrity check | ~5s |
| Backup extraction | ~30s |
| pip install | 2–5 min |
| Dashboard rebuild | 3–5 min |
| Service start | ~10s |
| Health validation | ~5s |
| **Total** | **~10 min** |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No backup found | Check `/opt/nexus/backups/` — run `backup.sh` first |
| SHA256 mismatch | Use an older backup: `ls -t backups/*.tar.gz` |
| pip install fails | Check network; try `venv/bin/pip install -r nexus/requirements.txt` manually |
| Health check fails | `journalctl -u nexus-core -n 50` |
| .env missing | Copy `.env.template` and fill in all secrets |
| Dashboard shows localhost | Re-run `rebuild_dashboard.sh <VPS_IP>` |
