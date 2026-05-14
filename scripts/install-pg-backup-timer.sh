#!/usr/bin/env bash
# Install the pg_dump backup as a systemd timer. Run once on the Dell.
set -euo pipefail

SUDO=$(command -v sudo || echo)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

$SUDO tee /etc/systemd/system/dh-pg-backup.service >/dev/null <<EOF
[Unit]
Description=Domain Hunter — nightly pg_dump of dh-pg
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=pronav
ExecStart=$REPO_DIR/scripts/backup-dh-pg.sh
EOF

$SUDO tee /etc/systemd/system/dh-pg-backup.timer >/dev/null <<EOF
[Unit]
Description=Run Domain Hunter pg_dump nightly at 03:15 UTC

[Timer]
OnCalendar=*-*-* 03:15:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now dh-pg-backup.timer
$SUDO systemctl list-timers dh-pg-backup.timer --no-pager
echo "OK: dh-pg-backup.timer installed and started"
