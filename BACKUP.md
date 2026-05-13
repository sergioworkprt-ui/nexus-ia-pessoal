# NEXUS Backup System

## Overview

Daily automated backups at 03:00 UTC via GitHub Actions. Backups are stored locally on the VPS and optionally uploaded to S3/Minio.

## Backup Contents

Each backup includes:
- All Python source code (`nexus/`)
- Configuration files (`.env`, `pyproject.toml`, etc.)
- Scripts (`scripts/`)
- Workflow files (`.github/`)
- Monitor/autoheal state files

**Excluded** (too large or reproducible):
- `venv/` — recreate with `pip install -r requirements.txt`
- `node_modules/` — recreate with `npm install`
- `dist/` — recreate with `npm run build`
- `.git/objects/` — use Git history
- `backups/` — prevent recursive inclusion

## Storage

- **Location**: `/opt/nexus/backups/`
- **Format**: `nexus_backup_YYYYMMDD_HHMMSS.tar.gz`
- **Integrity**: SHA256 checksum alongside each backup
- **Retention**: Last 10 backups kept locally

## Restore Instructions

### 1. Verify backup integrity
```bash
cd /opt/nexus/backups
sha256sum -c nexus_backup_YYYYMMDD_HHMMSS.tar.gz.sha256
```

### 2. Stop services
```bash
systemctl stop nexus-core nexus-api nexus-dashboard nexus-ws
```

### 3. Extract backup
```bash
cd /opt
tar -xzf /opt/nexus/backups/nexus_backup_YYYYMMDD_HHMMSS.tar.gz
```

### 4. Restart services
```bash
systemctl start nexus-core nexus-api nexus-dashboard nexus-ws
systemctl status nexus-core
```

### 5. Verify
```bash
curl http://localhost:8000/health
```

## Remote Backup Configuration

Configure S3/Minio in `/opt/nexus/.env`:
```env
S3_BUCKET=nexus-backups
S3_ENDPOINT=https://s3.amazonaws.com
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

Remote backups require either:
- **AWS CLI**: `pip install awscli` or `apt install awscli`
- **Minio Client**: `mc` binary from min.io

## Manual Backup

Run on VPS:
```bash
cd /opt/nexus
bash scripts/backup.sh           # Local backup
bash scripts/backup_remote.sh    # Upload to S3/Minio (if configured)
```

## Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| `daily-backup.yml` | 03:00 UTC daily | Local + remote backup |
| `autoheal-check.yml` | Hourly | Health check + auto-restart |
| `scaling-advisor.yml` | Every 6h | Load monitoring + recommendations |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Backup fails | Check disk space: `df -h /opt/nexus` |
| SHA256 mismatch | Re-run backup; disk may be corrupted |
| Remote upload fails | Check `.env` credentials and network |
| Old backups accumulate | Max 10 kept automatically by `backup.sh` |
