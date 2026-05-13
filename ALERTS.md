# NEXUS Alert System

## Overview

`alert.sh` dispatches notifications via **Telegram** and/or **SMTP email** for 5 critical event types. All alerts are logged to `/opt/nexus/logs/alerts.log`.

## Alert Types

| Type | Severity | Trigger |
|------|----------|---------|
| `ALERT_DEPLOY_FAIL` | CRITICAL | CI/CD deploy or health check failed |
| `ALERT_HEALTH_FAIL` | HIGH | Weekly health audit degraded |
| `ALERT_SECURITY_FAIL` | CRITICAL | Security audit found critical issues |
| `ALERT_BACKUP_FAIL` | MEDIUM | Daily backup failed |
| `ALERT_AUTOHEAL_TRIGGERED` | HIGH | Autoheal rollback activated |

## Usage

```bash
bash /opt/nexus/scripts/alert.sh <ALERT_TYPE> "<details>"
```

**Examples:**
```bash
bash scripts/alert.sh ALERT_DEPLOY_FAIL "Commit abc123 — health check timeout"
bash scripts/alert.sh ALERT_HEALTH_FAIL "nexus-core inactive after deploy"
bash scripts/alert.sh TEST "Manual test from VPS"
```

## Configuration

Add to `/opt/nexus/.env`:

### Telegram

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
```

**Setup:**
1. Message `@BotFather` on Telegram → `/newbot`
2. Copy the token
3. Add the bot to your group or channel
4. Get your chat ID: `curl https://api.telegram.org/bot<TOKEN>/getUpdates`

### SMTP Email

```env
ALERT_EMAIL_TO=admin@example.com
ALERT_EMAIL_FROM=nexus@yourdomain.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=nexus@yourdomain.com
SMTP_PASS=your-app-password
```

**Gmail setup:**
1. Enable 2FA on your Google account
2. Go to Security → App Passwords
3. Generate a password for "Mail"
4. Use it as `SMTP_PASS`

## Alert Test Workflow

Go to **GitHub Actions → Alert Test → Run workflow**.

This sends a `TEST` alert to all configured channels and confirms setup.

## Integrated Workflows

| Workflow | Alert Triggered When |
|----------|---------------------|
| `deploy.yml` | Deploy fails + rollback triggers |
| `weekly-health-audit.yml` | Health status is DEGRADED |
| `security-audit.yml` | Security audit finds critical issues |
| `daily-backup.yml` | Backup job fails |
| `autoheal-check.yml` | Autoheal cannot recover services |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No Telegram message | Check token: `curl https://api.telegram.org/bot<TOKEN>/getMe` |
| Wrong chat ID | Use negative ID for groups (e.g., `-1001234567890`) |
| Email not arriving | Check spam; verify `SMTP_HOST`/`SMTP_PORT` |
| Gmail auth fails | Use App Password, not account password |
| Both channels unconfigured | Script exits 0; check `alerts.log` |

Check logs: `tail -50 /opt/nexus/logs/alerts.log`
