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

# ---- 2. Pick relevant keys out of .env -----------------------------------
# We grep for specific keys instead of `source .env` so weird characters in
# unrelated values can't break the script.
BOT_TOKEN=$(grep -E '^BOT_TOKEN=' ./.env | cut -d= -f2- | tr -d '\r"')
OWNER_CHAT_ID=$(grep -E '^OWNER_CHAT_ID=' ./.env | cut -d= -f2- | tr -d '\r"')
ADMIN_CHAT_IDS=$(grep -E '^ADMIN_CHAT_IDS=' ./.env | cut -d= -f2- | tr -d '\r"' || true)
# Optional override. If set (e.g. id of a dedicated private channel), all
# backups go there and per-admin fan-out is skipped.
BACKUP_CHAT_ID=$(grep -E '^BACKUP_CHAT_ID=' ./.env | cut -d= -f2- | tr -d '\r"' || true)

if [ -z "${BOT_TOKEN:-}" ] || [ -z "${OWNER_CHAT_ID:-}" ]; then
    echo "[$(date)] [backup] missing BOT_TOKEN or OWNER_CHAT_ID in .env" >&2
    exit 1
fi

# Build the destination list (in priority order):
#   1. BACKUP_CHAT_ID — single explicit override (e.g. a private channel).
#   2. ADMIN_CHAT_IDS — comma-separated list; backup goes to every admin so
#      the developer who maintains the deploy gets their copy. The master
#      (OWNER_CHAT_ID) deliberately does NOT receive backups in this mode —
#      they shouldn't be bothered with operational files. Add their id to
#      ADMIN_CHAT_IDS too if they should receive backups.
#   3. OWNER_CHAT_ID — fallback for single-user deployments.
DEST_LIST=""
if [ -n "${BACKUP_CHAT_ID:-}" ]; then
    DEST_LIST="$BACKUP_CHAT_ID"
elif [ -n "${ADMIN_CHAT_IDS:-}" ]; then
    DEST_LIST=$(echo "$ADMIN_CHAT_IDS" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' | tr '\n' ' ')
else
    DEST_LIST="$OWNER_CHAT_ID"
fi

# ---- 3. Send the file to each destination (silent — no notification ping) ----
ANY_FAILED=0
for DEST_CHAT_ID in $DEST_LIST; do
    HTTP_CODE=$(curl -s -o /tmp/tg-resp.json -w "%{http_code}" \
      -F "chat_id=${DEST_CHAT_ID}" \
      -F "document=@${FINAL}" \
      -F "caption=📦 Weekly backup ${DATE}" \
      -F "disable_notification=true" \
      "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument")
    if [ "$HTTP_CODE" != "200" ]; then
        echo "[$(date)] [backup] Telegram upload to chat ${DEST_CHAT_ID} FAILED (HTTP $HTTP_CODE)" >&2
        cat /tmp/tg-resp.json >&2
        ANY_FAILED=1
    fi
done

if [ "$ANY_FAILED" = "1" ]; then
    exit 1
fi

# ---- 4. Rotate: keep 14 newest -------------------------------------------
ls -t "$BACKUP_DIR"/bot-*.db.gz 2>/dev/null | tail -n +15 | xargs -r rm

echo "[$(date)] [backup] OK: $(basename "$FINAL")"
