#!/usr/bin/env bash
# NEXUS Alert System — dispatches alerts via Telegram and/or SMTP email
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
LOG="$NEXUS_HOME/logs/alerts.log"

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [ALERT] $*" | tee -a "$LOG"; }

# ── Load .env ──────────────────────────────────────────────────────────────────────────
if [ -f "$NEXUS_HOME/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$NEXUS_HOME/.env"
    set +a
fi

ALERT_TYPE="${1:-TEST}"
DETAILS="${2:-No details provided}"

HOSTNAME_VAL=$(hostname -f 2>/dev/null || hostname)
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

case "$ALERT_TYPE" in
    ALERT_DEPLOY_FAIL)
        SUBJECT="🔴 NEXUS Deploy FAILED — $HOSTNAME_VAL"
        EMOJI="🔴"
        SEVERITY="CRITICAL"
        ;;
    ALERT_HEALTH_FAIL)
        SUBJECT="🟠 NEXUS Health Check FAILED — $HOSTNAME_VAL"
        EMOJI="🟠"
        SEVERITY="HIGH"
        ;;
    ALERT_SECURITY_FAIL)
        SUBJECT="🔴 NEXUS Security Audit FAILED — $HOSTNAME_VAL"
        EMOJI="🔴"
        SEVERITY="CRITICAL"
        ;;
    ALERT_BACKUP_FAIL)
        SUBJECT="🟡 NEXUS Backup FAILED — $HOSTNAME_VAL"
        EMOJI="🟡"
        SEVERITY="MEDIUM"
        ;;
    ALERT_AUTOHEAL_TRIGGERED)
        SUBJECT="🟠 NEXUS Autoheal TRIGGERED — $HOSTNAME_VAL"
        EMOJI="🟠"
        SEVERITY="HIGH"
        ;;
    TEST)
        SUBJECT="✅ NEXUS Alert Test — $HOSTNAME_VAL"
        EMOJI="✅"
        SEVERITY="INFO"
        ;;
    *)
        SUBJECT="⚠️ NEXUS Alert: $ALERT_TYPE — $HOSTNAME_VAL"
        EMOJI="⚠️"
        SEVERITY="UNKNOWN"
        ;;
esac

log "Sending alert: $ALERT_TYPE | $SEVERITY"
SENT=0

# ── Telegram ───────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    TG_MSG=$(printf '%s *%s*\nHost: %s\nTime: %s\nSeverity: %s\nDetails: %s' \
        "$EMOJI" "$ALERT_TYPE" "$HOSTNAME_VAL" "$TIMESTAMP" "$SEVERITY" "$DETAILS")
    TG_PAYLOAD=$(python3 -c "
import json, sys
print(json.dumps({
    'chat_id': '$TELEGRAM_CHAT_ID',
    'text': sys.stdin.read(),
    'parse_mode': 'Markdown'
}))" <<< "$TG_MSG")
    HTTP_CODE=$(curl -sf -w "%{http_code}" -o /tmp/tg_response.json \
        -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H 'Content-Type: application/json' \
        -d "$TG_PAYLOAD" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log "Telegram: sent OK"
        SENT=$((SENT + 1))
    else
        log "Telegram: FAILED (HTTP $HTTP_CODE)"
    fi
else
    log "Telegram: not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing)"
fi

# ── SMTP / Email ──────────────────────────────────────────────────────────────────────────
ALERT_EMAIL_TO="${ALERT_EMAIL_TO:-}"
ALERT_EMAIL_FROM="${ALERT_EMAIL_FROM:-nexus@localhost}"
SMTP_HOST="${SMTP_HOST:-}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-}"
SMTP_PASS="${SMTP_PASS:-}"

if [ -n "$ALERT_EMAIL_TO" ] && [ -n "$SMTP_HOST" ]; then
    EMAIL_BODY=$(cat << EMAIL_EOF
Subject: ${SUBJECT}
From: ${ALERT_EMAIL_FROM}
To: ${ALERT_EMAIL_TO}
Content-Type: text/plain; charset=utf-8

NEXUS Alert System
==================
Type:     ${ALERT_TYPE}
Severity: ${SEVERITY}
Host:     ${HOSTNAME_VAL}
Time:     ${TIMESTAMP}

Details:
${DETAILS}

--
NEXUS Autonomous AI System
EMAIL_EOF
)
    CURL_AUTH=""
    [ -n "$SMTP_USER" ] && CURL_AUTH="--user ${SMTP_USER}:${SMTP_PASS}"
    # shellcheck disable=SC2086
    HTTP_CODE=$(echo "$EMAIL_BODY" | curl -sf -w "%{http_code}" \
        --url "smtps://${SMTP_HOST}:${SMTP_PORT}" \
        $CURL_AUTH \
        --mail-from "$ALERT_EMAIL_FROM" \
        --mail-rcpt "$ALERT_EMAIL_TO" \
        --upload-file - 2>/tmp/smtp_err || echo "000")
    if [ "$HTTP_CODE" = "250" ] || [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "0" ]; then
        log "Email: sent OK to $ALERT_EMAIL_TO"
        SENT=$((SENT + 1))
    elif command -v sendmail &>/dev/null; then
        echo "$EMAIL_BODY" | sendmail -t 2>/dev/null && {
            log "Email: sent via sendmail"
            SENT=$((SENT + 1))
        } || log "Email: sendmail FAILED"
    else
        log "Email: FAILED (HTTP $HTTP_CODE) — $(cat /tmp/smtp_err 2>/dev/null | tail -3 || true)"
    fi
else
    log "Email: not configured (ALERT_EMAIL_TO/SMTP_HOST missing)"
fi

# ── Result ──────────────────────────────────────────────────────────────────────────────
if [ "$SENT" -gt 0 ]; then
    log "ALERT_STATUS=OK type=$ALERT_TYPE channels=$SENT"
else
    log "ALERT_STATUS=NO_CHANNEL type=$ALERT_TYPE — configure Telegram or SMTP in .env"
fi
# Always exit 0 so alert failure never blocks calling workflows
exit 0
