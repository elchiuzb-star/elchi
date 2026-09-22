#!/usr/bin/env bash
# Deploy / redeploy the stack on a server (host-agnostic). Run on the server.
#
#   ./scripts/deploy.sh                           # preflight, build api, pull db by digest, backup,
#                                                 # roles, checks, migrate, roles, start, gates
#   ./scripts/deploy.sh --no-pull                 # deploy the checked-out commit as is
#   ./scripts/deploy.sh --skip-backup             # only when a verified backup was just taken
#   ./scripts/deploy.sh --accept-degraded "why"   # production: continue although production_invariants != ok
#   ./scripts/deploy.sh --v1-only "why"           # production before the Q48 gate is satisfied: v1 only;
#                                                 # refused while any v2 service flag is enabled (Q56)
#
# Env files (BR wave 1.6 N2): $ELCHI_APP_ENV_FILE (default .env.app) for api/worker and
# interpolation, $ELCHI_DB_ADMIN_ENV_FILE (default .env.db-admin) for db/db-roles/migrate.
# Every deploy appends image ids and overrides to $ELCHI_DEPLOY_LOG (default /var/log/elchi-deploy.log).
# Rollback is NOT `alembic downgrade` (spec §18.3): see docs/ops/UZ_HOSTING_RUNBOOK.md §8.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib/preflight.sh
source scripts/lib/preflight.sh

PULL=1
BACKUP=1
ACCEPT_DEGRADED=""
V1_ONLY=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--no-pull) PULL=0; shift ;;
	--skip-backup) BACKUP=0; shift ;;
	--accept-degraded)
		[[ -n "${2:-}" && "${2:0:2}" != "--" ]] || { echo "--accept-degraded needs a reason" >&2; exit 2; }
		ACCEPT_DEGRADED="$2"; shift 2 ;;
	--v1-only)
		[[ -n "${2:-}" && "${2:0:2}" != "--" ]] || { echo "--v1-only needs a reason" >&2; exit 2; }
		V1_ONLY="$2"; shift 2 ;;
	-h | --help) sed -n '2,19p' "$0"; exit 0 ;;
	*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
done

APP_ENV_FILE="${ELCHI_APP_ENV_FILE:-.env.app}"
ADMIN_ENV_FILE="${ELCHI_DB_ADMIN_ENV_FILE:-.env.db-admin}"
DEPLOY_LOG="${ELCHI_DEPLOY_LOG:-/var/log/elchi-deploy.log}"
say() { printf '\n==> %s\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }
file_value() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2- || true; }
app_value() { file_value "$APP_ENV_FILE" "$1"; }
admin_value() { file_value "$ADMIN_ENV_FILE" "$1"; }
url_user() { sed -E 's#^[a-z+]+://([^:@/]*).*#\1#' <<<"$1"; }
ops_log() {
	local line
	line="$(date -u +%Y-%m-%dT%H:%M:%SZ) revision=${REVISION:-?} operator=${SUDO_USER:-${USER:-?}} $*"
	echo "OPS-LOG: $line"
	{ printf '%s\n' "$line" >>"$DEPLOY_LOG"; } 2>/dev/null || echo "warning: could not append to $DEPLOY_LOG" >&2
	command -v logger >/dev/null 2>&1 && logger -t elchi-deploy -- "$line" || true
}

# ── preflight: files ─────────────────────────────────────────────────────────
for file in "$APP_ENV_FILE" "$ADMIN_ENV_FILE"; do
	[[ -f "$file" ]] || die "$file is missing: cp app.env.example .env.app; cp db-admin.env.example .env.db-admin; chmod 600 both"
	perms="$(stat -c %a "$file" 2>/dev/null || echo 600)"
	[[ "$perms" =~ ^[0-7]00$ ]] || die "$file is readable by group/others (mode $perms); chmod 600 $file"
done
[[ ! -f .env.production ]] || echo "warning: .env.production is no longer used (split into .env.app / .env.db-admin); remove it" >&2

require() { # require <file> <key>...
	local file="$1" key value
	shift
	for key in "$@"; do
		value="$(file_value "$file" "$key")"
		[[ -n "$value" ]] || die "$key is not set in $file"
		[[ "$value" != *"<"* ]] || die "$key in $file still holds a <placeholder>"
	done
}
require "$APP_ENV_FILE" ELCHI_DATABASE_URL ELCHI_REDIS_URL REDIS_PASSWORD ELCHI_SECRET_KEY ELCHI_ENVIRONMENT ELCHI_POSTGIS_IMAGE
require "$ADMIN_ENV_FILE" POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB ELCHI_DB_ADMIN_URL \
	ELCHI_DB_OWNER_PASSWORD ELCHI_MIGRATION_DATABASE_URL ELCHI_DB_APP_PASSWORD

# BR wave 1.6 N2: admin credentials never in the api/worker env file.
if leaked="$(app_env_forbidden_keys "$APP_ENV_FILE")"; then :; else
	die "$APP_ENV_FILE contains database admin keys that api/worker must never receive: $(tr '\n' ' ' <<<"$leaked")-- move them to $ADMIN_ENV_FILE"
fi

# BR #4: one environment vocabulary for deploy, app settings (ALLOWED_ENVIRONMENTS) and the DB marker.
RAW_ENVIRONMENT="$(app_value ELCHI_ENVIRONMENT)"
ENVIRONMENT="$(tr '[:upper:]' '[:lower:]' <<<"$RAW_ENVIRONMENT" | tr -d '[:space:]')"
case "$ENVIRONMENT" in
production | staging | development | test) MARKER_ENVIRONMENT="$ENVIRONMENT" ;;
local) MARKER_ENVIRONMENT="development" ;;
*) die "ELCHI_ENVIRONMENT='$RAW_ENVIRONMENT' is not one of production, staging, development, test, local" ;;
esac
[[ "$RAW_ENVIRONMENT" == "$ENVIRONMENT" ]] || echo "warning: ELCHI_ENVIRONMENT='$RAW_ENVIRONMENT' normalised to '$ENVIRONMENT'; write it exactly" >&2

# Decision 36: api/worker never connect as the bootstrap superuser or the owner.
OWNER_USER="$(admin_value ELCHI_DB_OWNER_USER)"; OWNER_USER="${OWNER_USER:-elchi_owner}"
APP_USER="$(admin_value ELCHI_DB_APP_USER)"; APP_USER="${APP_USER:-elchi_app}"
SUPERUSER="$(admin_value POSTGRES_USER)"
[[ "$(url_user "$(app_value ELCHI_DATABASE_URL)")" == "$APP_USER" ]] ||
	die "ELCHI_DATABASE_URL must connect as the app role '$APP_USER' (not the superuser or owner)"
[[ "$(app_value ELCHI_DATABASE_URL)" == *":$(admin_value ELCHI_DB_APP_PASSWORD)@"* ]] ||
	die "the password in ELCHI_DATABASE_URL ($APP_ENV_FILE) differs from ELCHI_DB_APP_PASSWORD ($ADMIN_ENV_FILE)"
[[ "$(url_user "$(admin_value ELCHI_MIGRATION_DATABASE_URL)")" == "$OWNER_USER" ]] ||
	die "ELCHI_MIGRATION_DATABASE_URL must connect as the owner role '$OWNER_USER'"
[[ "$SUPERUSER" != "$APP_USER" && "$SUPERUSER" != "$OWNER_USER" ]] ||
	die "POSTGRES_USER (bootstrap superuser) must differ from the owner and app roles"
[[ "$(admin_value ELCHI_DB_ADMIN_URL)" == *"host=/var/run/postgresql"* ]] ||
	die "ELCHI_DB_ADMIN_URL must use the local socket (?host=/var/run/postgresql); superuser TCP logins are rejected by pg_hba"
for key in POSTGRES_PASSWORD ELCHI_DB_OWNER_PASSWORD ELCHI_DB_APP_PASSWORD; do
	[[ "$(admin_value "$key")" =~ ^[A-Za-z0-9._~-]{24,}$ ]] || die "$key must be >= 24 URL-safe characters (use openssl rand -hex 32)"
done
[[ "$(app_value REDIS_PASSWORD)" =~ ^[A-Za-z0-9._~-]{24,}$ ]] || die "REDIS_PASSWORD must be >= 24 URL-safe characters"

# BR wave 1.6 N5: monitoring CIDRs (empty = deny everyone).
MONITORING_CIDRS="$(app_value ELCHI_MONITORING_CIDRS)"
validate_monitoring_cidrs "$MONITORING_CIDRS" || die "ELCHI_MONITORING_CIDRS is invalid (see message above)"

DOMAIN="$(app_value ELCHI_DOMAIN)"
DOMAIN="${DOMAIN:-api.elchigo.uz}"
POSTGIS_IMAGE="$(app_value ELCHI_POSTGIS_IMAGE)"

if [[ "$ENVIRONMENT" == "production" ]]; then
	# K3 / ADR-0011 launch gate.
	[[ "$(app_value ELCHI_DATA_RESIDENCY)" == "UZ" ]] ||
		die "ELCHI_ENVIRONMENT=production requires ELCHI_DATA_RESIDENCY=UZ after hosting, registry and backup locations were verified (docs/ops/UZ_HOSTING_RUNBOOK.md §2)"
	# Decision 35 / BR wave 1.6 N4: no plaintext WAL archive in production. No override.
	[[ "$(app_value PG_ARCHIVE_MODE)" != "on" ]] ||
		die "PG_ARCHIVE_MODE=on is refused in production until WAL encryption exists (decision 35)"
	# Q51 / BR wave 1.6 N3: the db image comes from the UZ registry by digest; never built here.
	is_digest_pinned "$POSTGIS_IMAGE" ||
		die "ELCHI_POSTGIS_IMAGE must be <registry>/elchi-postgis@sha256:<digest> in production, got '$POSTGIS_IMAGE'"
elif ! is_digest_pinned "$POSTGIS_IMAGE"; then
	echo "warning: ELCHI_POSTGIS_IMAGE='$POSTGIS_IMAGE' is not digest-pinned (allowed outside production only)" >&2
fi

PROJECT="elchi"
# K4 guard (ADR-0013): legacy alpine volume present, PostGIS volume absent -> data not moved yet.
if docker volume inspect "${PROJECT}_pgdata" >/dev/null 2>&1 &&
	! docker volume inspect "${PROJECT}_pgdata_pg16_postgis" >/dev/null 2>&1 &&
	[[ "${ELCHI_ALLOW_EMPTY_DB:-}" != "1" ]]; then
	die "legacy volume ${PROJECT}_pgdata (postgres:16-alpine) exists but ${PROJECT}_pgdata_pg16_postgis does not. Move the data first: docs/ops/POSTGRES_POSTGIS_MIGRATION.md."
fi

if [[ "$PULL" == 1 ]]; then
	say "Pulling latest code"
	git pull --ff-only
fi
REVISION="$(git rev-parse --short=12 HEAD)"
export ELCHI_IMAGE="elchi-api:$REVISION"
export ELCHI_APP_ENV_FILE="$APP_ENV_FILE" ELCHI_DB_ADMIN_ENV_FILE="$ADMIN_ENV_FILE"
COMPOSE=(docker compose --env-file "$APP_ENV_FILE" -f docker-compose.prod.yml)

rendered="$("${COMPOSE[@]}" --profile ops config --format json)" || die "docker compose config failed"

say "Building $ELCHI_IMAGE (api, worker and jobs share it); pulling the db image"
"${COMPOSE[@]}" build api
if is_digest_pinned "$POSTGIS_IMAGE"; then
	"${COMPOSE[@]}" pull db
fi

# JSON parsing with the Python of the image just built (no host Python needed; wave 1.7 NEW-6).
export ELCHI_PREFLIGHT_PYTHON="docker run --rm -i --network none --entrypoint python $ELCHI_IMAGE"

# BR wave 1.6 N2: check the rendered per-service environment, not only the files.
say "Rendered compose configuration"
for service in api worker; do
	leaked="$(rendered_env_forbidden_keys "$service" <<<"$rendered")" && rc=0 || rc=$?
	case "$rc" in
	0) ;;
	1) die "rendered environment of '$service' contains admin keys: $(tr '\n' ' ' <<<"$leaked")" ;;
	*) die "could not read the rendered environment of '$service' (see message above)" ;;
	esac
done
echo "  api/worker environment contains no database admin keys"

# BR wave 1.6 N5: validate the Caddyfile with the effective domain and CIDRs before `up`.
caddy_image="$(rendered_service_image caddy <<<"$rendered")" || die "caddy image not found in the rendered configuration"
docker run --rm --network none -e "ELCHI_DOMAIN=$DOMAIN" -e "ELCHI_MONITORING_CIDRS=${MONITORING_CIDRS:-0.0.0.0/32}" \
	-v "$(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro" "$caddy_image" \
	caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null ||
	die "caddy validate failed for the rendered configuration"
echo "  Caddyfile valid for ELCHI_DOMAIN=$DOMAIN, ELCHI_MONITORING_CIDRS=${MONITORING_CIDRS:-0.0.0.0/32 (default deny)}"
ops_log "images api=$ELCHI_IMAGE api_id=$(docker image inspect -f '{{.Id}}' "$ELCHI_IMAGE") db=$POSTGIS_IMAGE db_id=$(docker image inspect -f '{{.Id}}' "$POSTGIS_IMAGE") caddy=$caddy_image environment=$ENVIRONMENT"

say "Starting db and redis"
"${COMPOSE[@]}" up -d --wait db redis

db_sql() { "${COMPOSE[@]}" exec -T db sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "$1"; }

# ADR-0013: never migrate on a server image without PostGIS.
[[ "$(db_sql "SELECT count(*) FROM pg_available_extensions WHERE name = 'postgis'")" == "1" ]] ||
	die "the db image has no PostGIS; do not migrate (ADR-0013)"

has_schema="$(db_sql "SELECT to_regclass('public.alembic_version') IS NOT NULL")"
if [[ "$BACKUP" == 1 && "$has_schema" == "t" ]]; then
	say "Pre-deploy backup (local, encrypted)"
	./scripts/backup.sh --local-only --tag "pre-deploy-$REVISION"
fi

say "Database roles, extensions and grants (superuser via local socket, idempotent)"
"${COMPOSE[@]}" run --rm db-roles

check_marker() { # BR #4: DB environment marker (A3 platform_environment) == app environment
	local when="$1" exists marker
	exists="$(db_sql "SELECT to_regclass('public.platform_environment') IS NOT NULL")"
	if [[ "$exists" != "t" ]]; then
		echo "  environment marker: table not present yet ($when)"
		return 0
	fi
	marker="$(db_sql "SELECT environment FROM platform_environment WHERE id = 1")"
	if [[ -z "$marker" ]]; then
		die "database environment marker is missing. Set it once (owner role), then rerun:
  ${COMPOSE[*]} run --rm migrate python -m app.modules.platform.environment set $MARKER_ENVIRONMENT --by \"deploy:$REVISION:${SUDO_USER:-${USER:-?}}\""
	fi
	[[ "$marker" == "$MARKER_ENVIRONMENT" ]] ||
		die "database marker is '$marker' but ELCHI_ENVIRONMENT=$ENVIRONMENT expects '$MARKER_ENVIRONMENT': wrong database or wrong env file"
	echo "  environment marker: $marker ($when)"
}
check_marker "before migrations"

say "Pre-migration checks"
# Decision 29: legacy commission rate must be valid before migrating (A3's check).
if "${COMPOSE[@]}" run --rm --no-deps migrate python -c \
	"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('app.modules.wallet.checks') else 3)"; then
	"${COMPOSE[@]}" run --rm migrate python -m app.modules.wallet.checks legacy-rate ||
		die "legacy commission rate check failed (python -m app.modules.wallet.checks legacy-rate)"
else
	echo "  warning: app.modules.wallet.checks is not in this build (A3); legacy-rate check SKIPPED" >&2
fi

# BR L4: data impact of migration 0054's Q68 cleanup, shown before migrating (read-only counts; information only).
if [[ "$(db_sql "SELECT to_regclass('public.parcel_listing_details') IS NOT NULL AND to_regclass('public.passenger_listing_details') IS NOT NULL")" == "t" ]]; then
	q68_sql="$(_preflight_python scripts/q68_cleanup_impact.py --print-sql)" || die "could not build the Q68 impact query (scripts/q68_cleanup_impact.py)"
	q68_impact="$(db_sql "$q68_sql")" || die "Q68 impact query failed"
	echo "  0054 Q68 cleanup would rewrite: $q68_impact (0 everywhere once 0054 is applied)"
	ops_log "q68_cleanup_impact $q68_impact"
else
	echo "  0054 Q68 cleanup: listing detail tables not present yet, nothing to rewrite"
fi

say "Applying migrations (one-shot job, owner role)"
"${COMPOSE[@]}" run --rm migrate
check_marker "after migrations"

say "Database roles again (grants for tables created by these migrations; guarded-table list must match)"
# NEW-5: db_roles.py exits 3 when the detected guarded tables differ from the committed list.
"${COMPOSE[@]}" run --rm db-roles python scripts/db_roles.py \
	--expected-guarded scripts/db_roles.expected-guarded-tables.txt ||
	die "db-roles failed or the session/depth-guarded tables differ from scripts/db_roles.expected-guarded-tables.txt"

# Q48 (+Q56): no production v2 money flow until the DB role split and the balance guard fix are in.
say "Q48 money-flow gate"
gate_json="$("${COMPOSE[@]}" run --rm --no-deps -T api python -m app.ops.gates status 2>/dev/null | tail -n 1 || true)"
json_field() { _preflight_python -c 'import json,sys; v=json.loads(sys.stdin.read() or "{}"); [v:=v.get(k) if isinstance(v, dict) else None for k in sys.argv[1:]]; print(json.dumps(v))' "$@" <<<"$gate_json"; }
[[ "$gate_json" == "{"* ]] || die "python -m app.ops.gates status produced no JSON; cannot evaluate the Q48 gate"
enabled_flags="$(json_field enabled_v2_service_flags)"
gate_available="$(json_field q48_gate available)"
q48_problems=()
if [[ "$gate_available" == "true" ]]; then
	[[ "$(json_field q48_gate ok)" == "true" ]] || q48_problems+=("q48_gate_status: $(json_field q48_gate failed)")
fi
[[ "$(db_sql "SELECT count(*) FROM pg_roles WHERE rolname = '$APP_USER' AND NOT rolsuper AND NOT rolbypassrls")" == "1" ]] ||
	q48_problems+=("app role $APP_USER missing or superuser/bypassrls")
if [[ "$gate_available" == "true" ]]; then
	: # A3's q48_gate_status is authoritative; the SQL fallback below is skipped
elif [[ "$(db_sql "SELECT to_regclass('public.ledger_account_balances') IS NOT NULL")" == "t" ]]; then
	[[ "$(db_sql "SELECT has_table_privilege('$APP_USER', 'public.ledger_account_balances', 'INSERT')
		OR has_table_privilege('$APP_USER', 'public.ledger_account_balances', 'UPDATE')
		OR has_table_privilege('$APP_USER', 'public.ledger_account_balances', 'DELETE')")" == "f" ]] ||
		q48_problems+=("app role can write ledger_account_balances")
	[[ "$(db_sql "SELECT coalesce(bool_or(pg_get_functiondef(p.oid) ~* 'pg_trigger_depth'), false) FROM pg_proc p
		JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname = 'ledger_account_balances_guard'")" == "t" ]] ||
		q48_problems+=("balance guard is not the pg_trigger_depth() version (A3 migration 0047)")
else
	q48_problems+=("ledger_account_balances not present")
fi
echo "  gate source: $([[ "$gate_available" == "true" ]] && echo "q48_gate_status (A3)" || echo "SQL fallback (q48_gate_status not in this build)")"
# Q56: --v1-only is only honest when no v2 service flag is enabled anywhere.
if [[ -n "$V1_ONLY" && "$ENVIRONMENT" == "production" && "$enabled_flags" != "[]" ]]; then
	die "--v1-only refused: v2 service flags are enabled in feature_flag_values: $enabled_flags"
fi
if [[ ${#q48_problems[@]} -eq 0 ]]; then
	echo "  Q48 gate satisfied"
elif [[ "$ENVIRONMENT" == "production" ]]; then
	if [[ -n "$V1_ONLY" ]]; then
		ops_log "override=v1-only q48_problems=\"${q48_problems[*]}\" enabled_v2_service_flags=$enabled_flags reason=\"$V1_ONLY\""
	else
		die "Q48 gate not satisfied (${q48_problems[*]}). Production v2 money flow is not allowed. Rerun with --v1-only \"<reason>\" (requires every v2 service flag disabled)"
	fi
else
	echo "  warning: Q48 gate not satisfied (${q48_problems[*]}); allowed outside production" >&2
fi

say "Starting api, worker and caddy"
"${COMPOSE[@]}" up -d --wait api worker
"${COMPOSE[@]}" up -d --wait caddy

say "Status"
"${COMPOSE[@]}" ps

# BR #7: readiness gate from inside the api container (monitoring CIDRs restrict it at Caddy).
say "Readiness gate"
ready_json="" ready_code=""
for attempt in $(seq 1 10); do
	out="$("${COMPOSE[@]}" exec -T api curl -s -w '\n%{http_code}' --max-time 10 http://127.0.0.1:8000/health/ready || true)"
	ready_json="$(head -n -1 <<<"$out")"
	ready_code="$(tail -n 1 <<<"$out")"
	[[ "$ready_code" == "200" || "$ready_code" == "503" ]] && break
	printf '  attempt %s/10: readiness not answering yet (HTTP %s)\n' "$attempt" "${ready_code:-none}"
	sleep 4
done
echo "  HTTP $ready_code $ready_json"
[[ "$ready_code" == "200" ]] || die "readiness is not 200 (database down or schema behind/unknown)"
if [[ "$ENVIRONMENT" == "production" ]] && ! grep -q '"production_invariants":"ok"' <<<"$ready_json"; then
	gate_json="$("${COMPOSE[@]}" exec -T api python -m app.ops.gates status 2>/dev/null | tail -n 1 || true)"
	other_failures="$(json_field invariant_failures_excluding_q48)"
	if [[ -n "$V1_ONLY" && "$other_failures" == "[]" && "$(json_field q48_gate ok)" != "true" ]]; then
		ops_log "v1-only: production_invariants not ok only because of the Q48 gate readiness=$ready_json"
	elif [[ -n "$ACCEPT_DEGRADED" ]]; then
		ops_log "override=accept-degraded readiness=$ready_json reason=\"$ACCEPT_DEGRADED\""
	else
		die "production_invariants is not ok -- the stack is running but this deploy FAILS. Investigate (logs: production_invariants_failed), or rerun with --accept-degraded \"<reason>\""
	fi
fi

echo
echo "External check via https://$DOMAIN (waiting for TLS if this is the first deploy)..."
for attempt in $(seq 1 12); do
	if curl -fsS --max-time 5 "https://$DOMAIN/api/v1/health"; then
		echo
		ops_log "deployed ok domain=$DOMAIN"
		echo "OK -- $REVISION on https://$DOMAIN"
		exit 0
	fi
	printf '  attempt %s/12 not ready yet, retrying in 5s\n' "$attempt"
	sleep 5
done

echo >&2
echo "Still not reachable after 60s. Check the logs:" >&2
echo "  ${COMPOSE[*]} logs --tail=50 caddy api" >&2
exit 1
