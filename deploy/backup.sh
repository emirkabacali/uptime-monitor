#!/usr/bin/env bash
# Daily PostgreSQL backup. Keeps the newest $KEEP dumps.
#
# Cron (as the deploy user):
#   15 2 * * * /home/deploy/uptime-monitor/backup.sh >> /home/deploy/uptime-monitor/backups/backup.log 2>&1
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
KEEP="${KEEP:-7}"
COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml" --project-directory "$APP_DIR")

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/uptime-$timestamp.dump"

# Custom format (-Fc): compressed, and pg_restore can restore it selectively.
"${COMPOSE[@]}" exec -T postgres pg_dump -U app -d uptime -Fc > "$target.partial"
mv "$target.partial" "$target"   # never leave a half-written file named like a backup
echo "$(date -u +%FT%TZ) backup written: $target ($(du -h "$target" | cut -f1))"

# Rotation: delete everything except the newest $KEEP backups.
# shellcheck disable=SC2012  # file names are generated above: no spaces or newlines
ls -1t "$BACKUP_DIR"/uptime-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm --
