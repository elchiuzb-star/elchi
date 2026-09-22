#!/usr/bin/env bash
# LOCAL rehearsal of docs/ops/POSTGRES_POSTGIS_MIGRATION.md on synthetic data.
# Never connects to a real server. Everything is named a10r-* and removed at the end.
#
#   docs/ops/rehearsal/rehearse_postgis_switch.sh            # needs the app and PostGIS images
#   APP_IMAGE=elchi-api:local KEEP=1 docs/ops/rehearsal/rehearse_postgis_switch.sh
#
# Steps: v1 schema (alembic 0029) + seeds + tricky text on postgres:16-alpine (musl) ->
# freeze -> pg_dump -Fc -> scripts/restore_drill.sh into the production PostGIS image
# (glibc 2.41, C / C.UTF-8) -> REINDEX lower()/upper() expression indexes + pg_amcheck ->
# compare ORDER BY / lower() / index lookups -> roles bootstrap (scripts/db_roles.py) ->
# alembic upgrade head as the owner role, twice -> app-role bypass checks -> v1 smoke as
# the app role -> prove the alpine volume is untouched.
set -euo pipefail

case "$(uname -s)" in MINGW* | MSYS* | CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;; esac
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

APP_IMAGE="${APP_IMAGE:-elchi-api:a10a-smoke}"
DB_IMAGE="${DB_IMAGE:-elchi-postgis:16.15-3.5.3-trixie}"
# The production service today uses the floating tag; pin what you rehearse with.
ALPINE_IMAGE="${ALPINE_IMAGE:-postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685}"
NET=a10r-net
SRC=a10r-alpine
DST=a10r-postgis
VOL=a10r-alpine-data
PW=rehearsal-only-password
SRC_URL="postgresql+psycopg://elchi:$PW@$SRC:5432/elchi"
ADMIN_PW=rehearsaladminpassword0000000000
OWNER_PW=rehearsalownerpassword0000000000
APP_PW=rehearsalapppassword000000000000
WORK="$(mktemp -d)"

step() { printf '\n==> [%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
now_ms() { date +%s%3N; }
secs() { awk -v ms="$1" 'BEGIN { printf "%.1f", ms / 1000 }'; }
check() { # check <label> <expected> <actual>
	if [[ "$2" == "$3" ]]; then echo "  PASS $1"; else echo "  FAIL $1: expected [$2] got [$3]"; FAILED=1; fi
}
FAILED=0

cleanup() {
	local status=$?
	if [[ "${KEEP:-0}" != 1 ]]; then
		docker rm -f "$SRC" "$DST" a10r-api >/dev/null 2>&1 || true
		docker volume rm "$VOL" >/dev/null 2>&1 || true
		docker network rm "$NET" >/dev/null 2>&1 || true
	fi
	rm -rf "$WORK"
	exit "$status"
}
trap cleanup EXIT

src_psql() { docker exec -i "$SRC" psql -X -q -At -v ON_ERROR_STOP=1 -U elchi -d elchi "$@"; }
dst_psql() { docker exec -i "$DST" psql -X -q -At -v ON_ERROR_STOP=1 -U elchi -d elchi "$@"; }
as_app() { docker exec -i -e PGPASSWORD="$APP_PW" "$DST" psql -X -q -At -h 127.0.0.1 -U elchi_app -d elchi "$@"; }
app() { docker run --rm --network "$NET" -e ELCHI_ENVIRONMENT=development -e "ELCHI_DATABASE_URL=$1" "${@:2}"; }
wait_pg() {
	for _ in $(seq 1 90); do
		docker exec "$1" pg_isready -q -h 127.0.0.1 -U elchi -d elchi 2>/dev/null && return 0
		sleep 1
	done
	echo "database $1 did not start" >&2
	return 1
}

for image in "$APP_IMAGE" "$DB_IMAGE"; do
	docker image inspect "$image" >/dev/null || { echo "image $image not found (docker build -t elchi-api:... . / docker build -t $DB_IMAGE docker/postgis)" >&2; exit 2; }
done
docker rm -f "$SRC" "$DST" a10r-api >/dev/null 2>&1 || true
docker volume rm "$VOL" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
docker network create --internal "$NET" >/dev/null

step "1. Source: $ALPINE_IMAGE with the current production schema (alembic 20260803_0029)"
docker run -d --name "$SRC" --network "$NET" -v "$VOL:/var/lib/postgresql/data" \
	-e POSTGRES_USER=elchi -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=elchi "$ALPINE_IMAGE" >/dev/null
wait_pg "$SRC"
app "$SRC_URL" "$APP_IMAGE" alembic upgrade 20260803_0029 2>&1 | grep -c 'Running upgrade' | sed 's/^/  migrations applied: /'
app "$SRC_URL" "$APP_IMAGE" python scripts/seed_cities.py | tail -1
app "$SRC_URL" "$APP_IMAGE" python scripts/seed_demo_marketplace_data.py | tail -2 || echo "  (demo seed failed; continuing with synthetic rows)"
src_psql <<'SQL'
INSERT INTO users (phone, username, full_name, role, status, is_phone_verified)
SELECT '+99877' || lpad(g::text, 7, '0'),
       CASE WHEN g % 50 = 0 THEN (ARRAY['Ali', 'ali', 'ALI', 'a-li', '_ali'])[1 + (g / 50) % 5] || g END,
       (ARRAY['Ali', 'ALI', 'ali', 'A-li', '_ali', 'Çağrı', 'Шерзод', 'шерзод', 'O‘tkir', 'O''tkir',
              'Zebo', 'zebo', 'Ёқуб', 'Ўктам', 'a b', 'ab', 'Ğani', 'ısmoil', 'Jo‘ra', '-z'])[1 + g % 20] || ' ' || g,
       CASE WHEN g % 10 = 0 THEN 'driver' ELSE 'client' END, 'active', true
FROM generate_series(1, 20000) AS g;
INSERT INTO audit_logs (entity_type, action) SELECT 'rehearsal', 'created_' || (g % 7) FROM generate_series(1, 3000) AS g;
ANALYZE;
SQL
src_psql -F $'\t' -c "SELECT 'source', current_setting('server_version'), datcollate, datctype, datlocprovider, coalesce(datcollversion, 'NULL'), current_setting('TimeZone') FROM pg_database WHERE datname = 'elchi'"

step "2. Capture pre-migration evidence (application stopped = no writes)"
bash "$REPO_ROOT/scripts/restore_drill.sh" --print-manifest-sql | src_psql -F $'\t' >"$WORK/manifest.rows"
{
	printf '# snapshot_at\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf '# alembic_version\t%s\n' "$(src_psql -c 'SELECT version_num FROM alembic_version')"
	cat "$WORK/manifest.rows"
} >"$WORK/manifest.tsv"
echo "  tables=$(wc -l <"$WORK/manifest.rows" | tr -d ' ') rows=$(awk -F'\t' '{s+=$2} END {print s}' "$WORK/manifest.rows")"
ORDER_SQL="SELECT md5(string_agg(full_name, '|' ORDER BY full_name, id)) FROM users"
CITY_ORDER_SQL="SELECT string_agg(name_uz, '|' ORDER BY name_uz, id) FROM cities"
CASE_SQL="SELECT lower('ШЕРЗОД ÇAĞRI ЎКТАМ O‘TKIR ĞANI İ') || '/' || upper('шерзод çağrı ўктам o‘tkir ğani ı')"
LOWER_SET_SQL="SELECT md5(string_agg(lower(full_name), '|' ORDER BY id)) FROM users"
src_order="$(src_psql -c "$ORDER_SQL")"
src_city_order="$(src_psql -c "$CITY_ORDER_SQL")"
src_case="$(src_psql -c "$CASE_SQL")"
src_lower_set="$(src_psql -c "$LOWER_SET_SQL")"

step "3. Downtime window starts: pg_dump -Fc from the alpine server"
t_dump0=$(now_ms)
docker exec "$SRC" pg_dump -Fc -Z 6 -U elchi -d elchi >"$WORK/elchi.dump"
t_dump1=$(now_ms)
echo "  dump $(wc -c <"$WORK/elchi.dump" | tr -d ' ') bytes in $(secs $((t_dump1 - t_dump0))) s"

step "4. Restore into the production PostGIS image + verify (scripts/restore_drill.sh)"
t_restore0=$(now_ms)
ELCHI_DRILL_DB_IMAGE="$DB_IMAGE" bash "$REPO_ROOT/scripts/restore_drill.sh" --dump "$WORK/elchi.dump" \
	--manifest "$WORK/manifest.tsv" --expect-head 20260803_0029 --keep --name "$DST" --network "$NET"
t_restore1=$(now_ms)
dst_psql -c "ALTER USER elchi PASSWORD '$ADMIN_PW'" >/dev/null

step "5. musl -> glibc 2.41: REINDEX lower()/upper() expression indexes, then pg_amcheck"
mapfile -t expr_indexes < <(dst_psql -c "SELECT i.indexrelid::regclass FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
	JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND pg_get_indexdef(i.indexrelid) ~* '(lower|upper)\\('")
echo "  expression indexes using lower()/upper(): ${#expr_indexes[@]} (${expr_indexes[*]:-none})"
for index in "${expr_indexes[@]}"; do dst_psql -c "REINDEX INDEX $index"; done
check "pg_amcheck --heapallindexed clean after reindex" "0" "$(docker exec "$DST" pg_amcheck -U elchi -d elchi --install-missing --heapallindexed >/dev/null 2>&1; echo $?)"
dst_psql -F $'\t' -c "SELECT 'target', current_setting('server_version'), datcollate, datctype, datlocprovider, coalesce(datcollversion, 'NULL'), current_setting('TimeZone') FROM pg_database WHERE datname = 'elchi'"
check "ORDER BY users.full_name identical" "$src_order" "$(dst_psql -c "$ORDER_SQL")"
check "ORDER BY cities.name_uz identical" "$src_city_order" "$(dst_psql -c "$CITY_ORDER_SQL")"
check "lower()/upper() on Cyrillic/Uzbek/Turkish letters identical" "$src_case" "$(dst_psql -c "$CASE_SQL")"
check "lower(full_name) over 20 000 names identical" "$src_lower_set" "$(dst_psql -c "$LOWER_SET_SQL")"
probe_phone="$(src_psql -c "SELECT phone FROM users ORDER BY id DESC LIMIT 1")"
check "unique phone found through the index" "1" "$(dst_psql -c "SET enable_seqscan = off; SELECT count(*) FROM users WHERE phone = '$probe_phone'")"
check "SHOW timezone" "UTC" "$(dst_psql -c 'SHOW timezone')"

step "6. Roles (decision 36): scripts/db_roles.py as the bootstrap superuser"
ADMIN_URL="postgresql://elchi:$ADMIN_PW@$DST:5432/elchi"
OWNER_URL="postgresql+psycopg://elchi_owner:$OWNER_PW@$DST:5432/elchi"
APP_URL="postgresql+psycopg://elchi_app:$APP_PW@$DST:5432/elchi"
roles_env=(-e "ELCHI_DB_ADMIN_URL=$ADMIN_URL" -e "ELCHI_DB_OWNER_PASSWORD=$OWNER_PW" -e "ELCHI_DB_APP_PASSWORD=$APP_PW" -e POSTGRES_DB=elchi)
app "$OWNER_URL" "${roles_env[@]}" "$APP_IMAGE" python scripts/db_roles.py | head -1

step "7. Expand migrations as the owner role: alembic upgrade head, twice"
t_mig0=$(now_ms)
app "$OWNER_URL" "$APP_IMAGE" alembic upgrade head >"$WORK/upgrade1.log" 2>&1 || { tail -20 "$WORK/upgrade1.log"; FAILED=1; }
t_mig1=$(now_ms)
echo "  $(grep -c 'Running upgrade' "$WORK/upgrade1.log") migrations applied as elchi_owner (0030 -> head)"
app "$OWNER_URL" "$APP_IMAGE" alembic upgrade head >"$WORK/upgrade2.log" 2>&1
check "second upgrade head is a no-op" "0" "$(grep -c 'Running upgrade' "$WORK/upgrade2.log" || true)"
check "alembic current is the script head" "yes" "$(app "$OWNER_URL" "$APP_IMAGE" alembic current 2>/dev/null | grep -q '(head)' && echo yes || echo no)"
check "roles bootstrap converges after migrations (0 ownership changes)" \
	"0" "$(app "$OWNER_URL" "${roles_env[@]}" "$APP_IMAGE" python scripts/db_roles.py | head -1 | sed -E 's/.*; ([0-9]+) ownership.*/\1/')"
check "postgis 3.5.3 + btree_gist installed" "btree_gist,postgis 3.5.3" \
	"$(dst_psql -c "SELECT string_agg(extname, ',' ORDER BY extname) || ' ' || max(extversion) FILTER (WHERE extname = 'postgis') FROM pg_extension WHERE extname IN ('postgis', 'btree_gist')")"
check "no tiger/topology extensions in the app database" "0" "$(dst_psql -c "SELECT count(*) FROM pg_extension WHERE extname LIKE 'postgis_t%'")"
check "pg_amcheck clean after migrations" "0" "$(docker exec "$DST" pg_amcheck -U elchi -d elchi --heapallindexed >/dev/null 2>&1; echo $?)"
check "row counts unchanged by migrations (users)" "$(awk -F'\t' '$1 == "public.users" {print $2}' "$WORK/manifest.rows")" "$(dst_psql -c 'SELECT count(*) FROM users')"
check "every public table owned by elchi_owner" "elchi_owner" "$(dst_psql -c "SELECT string_agg(DISTINCT pg_get_userbyid(c.relowner), ',') FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND c.relname <> 'spatial_ref_sys'")"

step "8. App role cannot bypass DB-level invariants"
check "app role attributes (super, bypassrls)" "f|f" "$(as_app -c "SELECT rolsuper || '|' || rolbypassrls FROM pg_roles WHERE rolname = current_user" | sed 's/false/f/g; s/true/t/g')"
for statement in "ALTER TABLE audit_logs DISABLE TRIGGER ALL" "SET session_replication_role = replica" \
	"COPY (SELECT 1) TO PROGRAM 'true'" "TRUNCATE audit_logs" "CREATE TABLE app_probe (id int)" \
	"UPDATE alembic_version SET version_num = version_num"; do
	if as_app -c "$statement" >/dev/null 2>"$WORK/err"; then
		check "refused: $statement" "permission denied" "EXECUTED"
	else
		check "refused: $statement" "permission denied" "$(grep -o -m1 'permission denied\|must be owner' "$WORK/err" | sed 's/must be owner/permission denied/')"
	fi
done

step "9. v1 smoke against the restored database, as the app role"
docker run -d --name a10r-api --network "$NET" -e ELCHI_ENVIRONMENT=development -e "ELCHI_DATABASE_URL=$APP_URL" "$APP_IMAGE" >/dev/null
for _ in $(seq 1 40); do docker exec a10r-api curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1 && break; sleep 1; done
t_up=$(now_ms)
check "GET /api/v1/health" '{"success":true,"message":"OK"}' "$(docker exec a10r-api curl -fsS http://127.0.0.1:8000/api/v1/health)"
api_cities="$(docker exec a10r-api curl -fsS http://127.0.0.1:8000/api/v1/cities | docker exec -i a10r-api python -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(len(d if isinstance(d, list) else d.get("items", [])))')"
check "GET /api/v1/cities returns every active city" "$(dst_psql -c 'SELECT count(*) FROM cities WHERE is_active')" "$api_cities"
ready="$(docker exec a10r-api curl -s http://127.0.0.1:8000/health/ready)"
echo "  /health/ready: $ready"
check "readiness database+migrations ok as app role" "yes" "$(grep -q '"database":"ok","migrations":"ok"' <<<"$ready" && echo yes || echo no)"
check "api logs are JSON lines" "yes" "$(docker logs a10r-api 2>&1 | grep -m1 '^{' | python -c 'import json,sys; json.loads(sys.stdin.read()); print("yes")' 2>/dev/null || py -c 'import json,sys; json.loads(sys.stdin.read()); print("yes")' <<<"$(docker logs a10r-api 2>&1 | grep -m1 '^{')" 2>/dev/null || echo no)"

step "10. Rollback path: the alpine volume is untouched"
docker restart "$SRC" >/dev/null
wait_pg "$SRC"
bash "$REPO_ROOT/scripts/restore_drill.sh" --print-manifest-sql | src_psql -F $'\t' >"$WORK/manifest.after"
check "alpine manifest after rehearsal == before" "$(md5sum <"$WORK/manifest.rows" | cut -c1-32)" "$(md5sum <"$WORK/manifest.after" | cut -c1-32)"
check "alembic_version on alpine still 0029" "20260803_0029" "$(src_psql -c 'SELECT version_num FROM alembic_version')"

cat <<EOF

==> Measured window (this laptop, synthetic data; NOT a production estimate)
  pg_dump                    $(secs $((t_dump1 - t_dump0))) s
  restore + verify (drill)   $(secs $((t_restore1 - t_restore0))) s
  alembic upgrade head       $(secs $((t_mig1 - t_mig0))) s
  api start to healthy       $(secs $((t_up - t_mig1))) s
  total                      $(secs $((t_up - t_dump0))) s
EOF
if [[ "$FAILED" != 0 ]]; then
	echo "==> REHEARSAL FAILED"
	exit 1
fi
echo "==> REHEARSAL PASSED"
