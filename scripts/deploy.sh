#!/usr/bin/env bash
# Deploy / redeploy the API on the server.
#   ./scripts/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env.production ]]; then
	echo "error: .env.production is missing." >&2
	echo "       cp .env.production.example .env.production && chmod 600 .env.production" >&2
	exit 1
fi

COMPOSE=(docker compose --env-file .env.production -f docker-compose.prod.yml)

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building API image"
"${COMPOSE[@]}" build api

echo "==> Starting database"
"${COMPOSE[@]}" up -d db

echo "==> Applying migrations"
# Runs against the built image, before any new API container serves traffic.
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "==> Starting API and Caddy"
"${COMPOSE[@]}" up -d

echo "==> Status"
"${COMPOSE[@]}" ps

echo
# On a first deploy Caddy still has to obtain a certificate from Let's Encrypt,
# which takes a few seconds. Curling immediately fails with a TLS alert, so
# retry for a minute before calling it broken.
echo "Health check (waiting for TLS if this is the first deploy)..."
for attempt in $(seq 1 12); do
	if curl -fsS --max-time 5 https://api.elchigo.uz/api/v1/health; then
		echo
		echo "OK — https://api.elchigo.uz/docs"
		exit 0
	fi
	printf '  attempt %s/12 not ready yet, retrying in 5s\n' "$attempt"
	sleep 5
done

echo >&2
echo "Still not reachable after 60s. Check the logs:" >&2
echo "  ${COMPOSE[*]} logs --tail=50 caddy api" >&2
exit 1
