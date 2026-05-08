#!/bin/bash
# Weekly backup script for bot-claws-yuliia.
#
# Cron entry (every Sunday at 03:00 server-time):
#   0 3 * * 0 /opt/bot-claws/deploy/backup.sh >> /var/log/bot-claws-backup.log 2>&1
#
# What it does:
#   1. Atomic SQLite snapshot via the `.backup` API (runs inside the bot
#      container, so we don't need sqlite3 installed on the host).
#   2. Gzips the snapshot to ./data/backups/.
#   3. Sends the gzipped file to OWNER_CHAT_ID via Telegram Bot API.
#   4. Rotates: keeps the 14 newest backups, deletes the rest.

set -euo pipefail

cd /opt/bot-claws

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./data/backups"
mkdir -p "$BACKUP_DIR"

# ---- 1. Atomic snapshot via the bot container's stdlib sqlite3 -----------
docker compose exec -T bot python3 - "$DATE" <<'PYEOF'
import sqlite3
import sys

date = sys.argv[1]
src = sqlite3.connect("/data/bot.db")
dst = sqlite3.connect(f"/data/backups/bot-{date}.db")
with dst:
    src.backup(dst)
src.close()
dst.close()
PYEOF

TMP="$BACKUP_DIR/bot-${DATE}.db"
gzip -f "$TMP"
FINAL="${TMP}.gz"

# ---- 2. Pick BOT_TOKEN, OWNER_CHAT_ID, and optional BACKUP_CHAT_ID -------
# We grep for specific keys instead of `source .env` so weird characters in
# unrelated values can't break the script.
BOT_TOKEN=$(grep -E '^BOT_TOKEN=' ./.env | cut -d= -f2- | tr -d '\r"')
OWNER_CHAT_ID=$(grep -E '^OWNER_CHAT_ID=' ./.env | cut -d= -f2- | tr -d '\r"')
# BACKUP_CHAT_ID is optional. If set (e.g. to a private channel id like
# -1001234567890), backups go there instead of the main owner chat. Lets the
# operator keep their main bot conversation clean of backup spam.
BACKUP_CHAT_ID=$(grep -E '^BACKUP_CHAT_ID=' ./.env | cut -d= -f2- | tr -d '\r"' || true)

if [ -z "${BOT_TOKEN:-}" ] || [ -z "${OWNER_CHAT_ID:-}" ]; then
    echo "[$(date)] [backup] missing BOT_TOKEN or OWNER_CHAT_ID in .env" >&2
    exit 1
fi

DEST_CHAT_ID="${BACKUP_CHAT_ID:-$OWNER_CHAT_ID}"

# ---- 3. Send the file to Telegram (silent — no notification ping) -------
HTTP_CODE=$(curl -s -o /tmp/tg-resp.json -w "%{http_code}" \
  -F "chat_id=${DEST_CHAT_ID}" \
  -F "document=@${FINAL}" \
  -F "caption=📦 Weekly backup ${DATE}" \
  -F "disable_notification=true" \
  "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument")

if [ "$HTTP_CODE" != "200" ]; then
    echo "[$(date)] [backup] Telegram upload FAILED (HTTP $HTTP_CODE)" >&2
    cat /tmp/tg-resp.json >&2
    exit 1
fi

# ---- 4. Rotate: keep 14 newest -------------------------------------------
ls -t "$BACKUP_DIR"/bot-*.db.gz 2>/dev/null | tail -n +15 | xargs -r rm

echo "[$(date)] [backup] OK: $(basename "$FINAL")"
