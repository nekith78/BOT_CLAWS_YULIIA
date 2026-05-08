#!/bin/bash
# One-shot bootstrap installer for bot-claws-yuliia on a fresh Linux VM.
#
# What it does end-to-end (8 steps):
#   1. Update apt + base utils
#   2. Install Docker + compose plugin
#   3. Add invoking user to the docker group
#   4. Set up 2 GB swap (safety net for 1 GB RAM hosts)
#   5. Clone the repo to /opt/bot-claws
#   6. Pick up .env from $HOME/bot-claws.env (uploaded via scp), or bail
#      with a clear instruction
#   7. Build and start the docker compose stack
#   8. Install the systemd unit + nightly Telegram-backup cron
#
# Usage on the VM (after `ssh ubuntu@<vm>`):
#   git clone https://github.com/nekith78/BOT_CLAWS_YULIIA.git /tmp/bot-claws-installer
#   sudo bash /tmp/bot-claws-installer/deploy/install.sh
#
# Pre-requisite from your laptop:
#   scp -i ~/.ssh/oracle_bot_claws ~/path/to/.env ubuntu@<vm>:~/bot-claws.env

set -euo pipefail

# --- helpers --------------------------------------------------------------
log() { echo -e "\033[1;32m[install]\033[0m $*"; }
warn() { echo -e "\033[1;33m[install]\033[0m $*"; }
err() { echo -e "\033[1;31m[install]\033[0m $*" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    err "Run with sudo:  sudo bash $0"
    exit 1
fi

# Determine the user that invoked sudo (we add THEM to docker group, install
# THEIR crontab, and own the repo as them — not as root).
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ubuntu)}"

# Resolve the user's home directory. Try a few methods in order of how likely
# the underlying tool is to be available on a minimal Ubuntu image.
if [ -d "/home/$REAL_USER" ]; then
    REAL_HOME="/home/$REAL_USER"
elif command -v getent > /dev/null 2>&1; then
    REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
elif [ -f /etc/passwd ]; then
    REAL_HOME=$(awk -F: -v u="$REAL_USER" '$1==u {print $6}' /etc/passwd)
else
    REAL_HOME=$(eval echo "~$REAL_USER")
fi

if [ -z "$REAL_HOME" ] || [ ! -d "$REAL_HOME" ]; then
    err "Can't resolve home directory for user '$REAL_USER'."
    exit 1
fi

REPO_DIR=/opt/bot-claws
REPO_URL="https://github.com/nekith78/BOT_CLAWS_YULIIA.git"
ENV_UPLOAD="$REAL_HOME/bot-claws.env"

# --- step 1: apt --------------------------------------------------------
log "[1/8] apt update + base utilities"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl ca-certificates gnupg lsb-release nano cron htop git tzdata

# --- step 2: docker -----------------------------------------------------
if command -v docker > /dev/null && docker compose version > /dev/null 2>&1; then
    log "[2/8] Docker already installed, skipping"
else
    log "[2/8] installing Docker + compose plugin"
    install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
    fi
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
fi

# --- step 3: docker group ------------------------------------------------
log "[3/8] adding $REAL_USER to docker group"
usermod -aG docker "$REAL_USER"

# --- step 4: swap --------------------------------------------------------
if swapon --show | grep -q '/swapfile'; then
    log "[4/8] swap already active, skipping"
else
    log "[4/8] creating 2 GB swap"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile > /dev/null
    swapon /swapfile
    if ! grep -q '^/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
fi

# --- step 5: clone repo --------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
    log "[5/8] repo already at $REPO_DIR, pulling latest"
    sudo -u "$REAL_USER" git -C "$REPO_DIR" pull --ff-only || true
else
    log "[5/8] cloning $REPO_URL → $REPO_DIR"
    mkdir -p "$REPO_DIR"
    chown "$REAL_USER:$REAL_USER" "$REPO_DIR"
    sudo -u "$REAL_USER" git clone "$REPO_URL" "$REPO_DIR"
fi

# --- step 6: .env --------------------------------------------------------
log "[6/8] preparing .env"
if [ -f "$REPO_DIR/.env" ]; then
    log "      $REPO_DIR/.env already in place, leaving as-is"
elif [ -f "$ENV_UPLOAD" ]; then
    log "      moving $ENV_UPLOAD → $REPO_DIR/.env"
    mv "$ENV_UPLOAD" "$REPO_DIR/.env"
    chown "$REAL_USER:$REAL_USER" "$REPO_DIR/.env"
    chmod 600 "$REPO_DIR/.env"
else
    err "No .env found. Upload it from your laptop first:"
    err ""
    err "  scp -i ~/.ssh/oracle_bot_claws ~/path/to/.env ${REAL_USER}@$(hostname -I | awk '{print $1}'):~/bot-claws.env"
    err ""
    err "Then re-run this installer."
    exit 1
fi

# Sanity-check the critical keys
if ! grep -qE '^BOT_TOKEN=.+' "$REPO_DIR/.env"; then
    err ".env missing BOT_TOKEN. Open $REPO_DIR/.env and fill it, then re-run."
    exit 1
fi
if ! grep -qE '^OWNER_CHAT_ID=.+' "$REPO_DIR/.env"; then
    err ".env missing OWNER_CHAT_ID. Open $REPO_DIR/.env and fill it, then re-run."
    exit 1
fi

mkdir -p "$REPO_DIR/data" "$REPO_DIR/data/backups"
chown -R "$REAL_USER:$REAL_USER" "$REPO_DIR/data"

# Match container's `bot` UID/GID to the host user. On most distros the
# default user sits at UID 1000, but Oracle Cloud Ubuntu uses 1001 — without
# this the container can't write to the mounted ./data volume. We export the
# build args so docker compose's interpolation (${BOT_UID}) picks them up.
HOST_UID=$(id -u "$REAL_USER")
HOST_GID=$(id -g "$REAL_USER")
log "      UID/GID for in-container bot user: ${HOST_UID}:${HOST_GID}"
export BOT_UID="$HOST_UID"
export BOT_GID="$HOST_GID"

# --- step 7: build + run --------------------------------------------------
log "[7/8] building and starting docker compose stack (this takes 3-5 min)"
cd "$REPO_DIR"
BOT_UID="$HOST_UID" BOT_GID="$HOST_GID" docker compose up -d --build

# --- step 8: systemd + cron + tz -----------------------------------------
log "[8/8] systemd unit + nightly backup cron"
cp "$REPO_DIR/deploy/bot-claws.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bot-claws.service

touch /var/log/bot-claws-backup.log
chown "$REAL_USER:$REAL_USER" /var/log/bot-claws-backup.log

# Idempotent cron entry: only add if not already there. Schedule is weekly
# (every Sunday at 03:00) — single-user bot's data doesn't change often
# enough to justify daily backups; weekly + 14-snapshot rotation gives
# ~3 months of history.
CRON_TAG="$REPO_DIR/deploy/backup.sh"
CRON_LINE="0 3 * * 0 $CRON_TAG >> /var/log/bot-claws-backup.log 2>&1"
EXISTING_CRON=$(sudo -u "$REAL_USER" crontab -l 2>/dev/null || true)
if ! echo "$EXISTING_CRON" | grep -qF "$CRON_TAG"; then
    log "      adding cron entry: weekly (Sunday 03:00) Telegram backup"
    {
        if [ -n "$EXISTING_CRON" ]; then echo "$EXISTING_CRON"; fi
        echo "$CRON_LINE"
    } | sudo -u "$REAL_USER" crontab -
else
    # Already present — replace to update from old daily schedule, if any.
    NEW_CRON=$(echo "$EXISTING_CRON" | grep -vF "$CRON_TAG")
    {
        if [ -n "$NEW_CRON" ]; then echo "$NEW_CRON"; fi
        echo "$CRON_LINE"
    } | sudo -u "$REAL_USER" crontab -
    log "      cron entry refreshed (now weekly)"
fi

# Set TZ so cron's 03:00 matches the user's local clock (Asia/Almaty per spec).
timedatectl set-timezone Asia/Almaty 2>/dev/null || warn "could not set timezone"

# --- done ----------------------------------------------------------------
echo ""
log "✅ Install complete."
echo ""
log "Verifying stack..."
sleep 3
docker compose ps || true
echo ""
log "Next steps:"
log "  • Send /start in Telegram — bot should reply with main menu."
log "  • Tail logs:                docker compose logs bot -f"
log "  • Manual backup test:       $REPO_DIR/deploy/backup.sh"
log "  • Reboot test (later):      sudo reboot — bot should auto-start via systemd."
echo ""
warn "If you ran any 'docker' commands manually before this, log out and back in"
warn "to pick up the docker group membership for $REAL_USER (only matters for"
warn "running docker commands without sudo afterwards)."
