# Deploy artifacts

Operational files used during production deployment to a single VM (e.g.
Oracle Cloud Free Tier). Designed for: docker compose stack + systemd
auto-start + cron-driven daily backup to Telegram.

## Files

- `install.sh` — one-shot bootstrap installer. Run with `sudo` on a fresh
  VM. Does everything: apt update, Docker install, swap, repo clone,
  docker compose build/up, systemd unit, backup cron, timezone.
- `bot-claws.service` — systemd unit. Brings up the docker compose stack
  at boot via `docker compose up -d`. Installed by `install.sh`.
- `backup.sh` — daily backup script. Snapshots SQLite via the `.backup`
  API (atomic), gzips, sends to Telegram via `sendDocument`, rotates the
  14 newest. Cron-driven (entry installed by `install.sh`).

## One-shot deploy on a fresh VM

```bash
# === On your laptop ===
# 1. Upload the .env (with BOT_TOKEN, OWNER_CHAT_ID, OPENAI_API_KEY, etc.)
scp -i ~/.ssh/oracle_bot_claws ~/path/to/BOT_CLAWS_YULIIA/.env ubuntu@<VM_IP>:~/bot-claws.env

# 2. SSH to the VM
ssh -i ~/.ssh/oracle_bot_claws ubuntu@<VM_IP>

# === On the VM ===
# 3. Clone the repo and run the installer
git clone https://github.com/nekith78/BOT_CLAWS_YULIIA.git /tmp/bot-claws-installer
sudo bash /tmp/bot-claws-installer/deploy/install.sh
```

The installer takes 3-5 minutes. When done, `/start` in Telegram should
work; the systemd unit + nightly backup cron are installed and active.

## Manual install (if you don't want to run the script)

See the full step-by-step in the original walkthrough below; it's the
same commands the installer runs, just executed by hand:

```bash
# 1. apt + Docker (see official Docker docs for Ubuntu 22.04)
# 2. usermod -aG docker $USER && newgrp docker
# 3. fallocate /swapfile 2G && mkswap && swapon
# 4. git clone https://github.com/nekith78/BOT_CLAWS_YULIIA.git /opt/bot-claws
# 5. nano /opt/bot-claws/.env  (or scp from laptop)
# 6. cd /opt/bot-claws && docker compose up -d --build
# 7. sudo cp deploy/bot-claws.service /etc/systemd/system/
#    sudo systemctl daemon-reload && sudo systemctl enable --now bot-claws.service
# 8. (crontab -l; echo "0 3 * * * /opt/bot-claws/deploy/backup.sh >> /var/log/bot-claws-backup.log 2>&1") | crontab -
```

## Verifying

```bash
systemctl status bot-claws.service        # should be active (exited)
docker compose ps                          # bot + redis up
tail -n 50 /var/log/bot-claws-backup.log   # after first 03:00
```

## Manual backup test (don't wait until 03:00)

```bash
/opt/bot-claws/deploy/backup.sh
```

A Telegram message «📦 Daily backup …» should arrive.
