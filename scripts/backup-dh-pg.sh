#!/usr/bin/env bash
# Nightly pg_dump of dh-pg → /var/backups/dh/, kept 14 days.
# Existing host restic chain backs up /var/backups/* incidentally.
#
# Install on Dell as a systemd timer (see scripts/install-pg-backup-timer.sh).
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/dh}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date -u +%F-%H%M)"
OUT="$BACKUP_DIR/dh-$STAMP.pgdump"

mkdir -p "$BACKUP_DIR"

# pg_dump --format=custom (compressed, restorable via pg_restore)
docker exec dh-pg pg_dump -Fc -U dh -d dh -f "/var/backups/dh/$(basename "$OUT")"

# Verify size > 0
if [ ! -s "$OUT" ]; then
    echo "FAIL: $OUT is empty" >&2
    exit 1
fi
echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"

# Retention: drop dumps older than KEEP_DAYS
find "$BACKUP_DIR" -maxdepth 1 -name "dh-*.pgdump" -type f -mtime "+$KEEP_DAYS" -print -delete

# Trigger restic if MOC's restic script is installed (best-effort, non-fatal)
if [ -x /home/pronav/docker/moc/infra/scripts/moc-backup-restic.sh ]; then
    echo "(restic kick is handled by its own cron; pg_dump file will be included on next run)"
fi
