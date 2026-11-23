#!/usr/bin/env bash
# Restore a backup made by backup.sh.
#
#   ./restore.sh backups/uptime-20261123T021500Z.dump            # into a scratch DB (safe test)
#   ./restore.sh backups/uptime-20261123T021500Z.dump --replace  # replace the live DB
#
# Without --replace the dump is restored into a separate database
# "uptime_restore_test" and row counts are printed: this is the regular
# restore drill that proves the backups actually work.
set -euo pipefail

DUMP="${1:?usage: restore.sh <dump file> [--replace]}"
MODE="${2:-}"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml" --project-directory "$APP_DIR")
psql() { "${COMPOSE[@]}" exec -T postgres psql -U app -v ON_ERROR_STOP=1 "$@"; }

if [ "$MODE" = "--replace" ]; then
  TARGET=uptime
  echo "Stopping the application so nothing writes during the restore..."
  "${COMPOSE[@]}" stop api worker beat
else
  TARGET=uptime_restore_test
fi

psql -d postgres -c "DROP DATABASE IF EXISTS $TARGET WITH (FORCE);"
psql -d postgres -c "CREATE DATABASE $TARGET OWNER app;"
"${COMPOSE[@]}" exec -T postgres pg_restore -U app -d "$TARGET" --no-owner < "$DUMP"

echo "Restored $DUMP into $TARGET. Row counts:"
psql -d "$TARGET" -c "SELECT 'users' AS table, count(*) FROM users
                      UNION ALL SELECT 'monitors', count(*) FROM monitors
                      UNION ALL SELECT 'check_results', count(*) FROM check_results
                      UNION ALL SELECT 'incidents', count(*) FROM incidents;"

if [ "$MODE" = "--replace" ]; then
  "${COMPOSE[@]}" up -d api worker beat
else
  psql -d postgres -c "DROP DATABASE $TARGET;"
  echo "Restore test passed; scratch database removed."
fi
