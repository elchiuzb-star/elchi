#!/usr/bin/env bash
# Dump the database and the uploads volume to ./backups, keeping 14 days.
# Wire into cron on the server:
#   0 3 * * * /opt/elchi/scripts/backup.sh >> /var/log/elchi-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose --env-file .env.production -f docker-compose.prod.yml)
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="backups"
RETENTION_DAYS=14

mkdir -p "$DEST"

# shellcheck disable=SC1091
source .env.production

echo "==> Dumping database -> $DEST/db-$STAMP.sql.gz"
"${COMPOSE[@]}" exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
	| gzip >"$DEST/db-$STAMP.sql.gz"

echo "==> Archiving uploads -> $DEST/uploads-$STAMP.tar.gz"
"${COMPOSE[@]}" run --rm -T --entrypoint sh api \
	-c 'tar -cz -C /app/storage uploads' >"$DEST/uploads-$STAMP.tar.gz"

echo "==> Pruning backups older than $RETENTION_DAYS days"
find "$DEST" -name '*.gz' -type f -mtime "+$RETENTION_DAYS" -delete

echo "==> Done"
ls -lh "$DEST" | tail -5

# NOTE: this only protects against data loss, not against losing the server.
# Copy $DEST off-box (rclone/rsync to object storage) for that.
