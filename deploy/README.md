# Deploy artifacts

Operational files used during production deployment to a single VM (e.g.
Oracle Cloud Free Tier). Designed for: docker compose stack + systemd
auto-start + cron-driven daily backup to Telegram.

## Files

- `bot-claws.service` — systemd unit. Brings up the docker compose stack
  at boot via `docker compose up -d`. Place at `/etc/systemd/system/bot-claws.service`.
- `backup.sh` — daily backup script. Snapshots SQLite via the `.backup`
  API (atomic), gzips, sends to Telegram via `sendDocument`, rotates the
  14 newest. Runs from cron (see header of the file for the cron line).

## Install (on a fresh VM, after `git clone` to /opt/bot-claws)

```bash
# systemd unit
sudo cp /opt/bot-claws/deploy/bot-claws.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bot-claws.service

# Backup cron (runs as the user that owns /opt/bot-claws — usually `ubuntu`)
sudo touch /var/log/bot-claws-backup.log
sudo chown $USER:$USER /var/log/bot-claws-backup.log
( crontab -l 2>/dev/null; echo "0 3 * * * /opt/bot-claws/deploy/backup.sh >> /var/log/bot-claws-backup.log 2>&1" ) | crontab -
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
