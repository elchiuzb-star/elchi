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
echo "Health check:"
curl -fsS https://api.elchigo.uz/api/v1/health && echo || {
	echo "  not reachable yet — check: ${COMPOSE[*]} logs -f caddy api" >&2
}
