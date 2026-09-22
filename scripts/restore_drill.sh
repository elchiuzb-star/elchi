#!/usr/bin/env bash
# Restore drill (AC40, spec §19.2): restore a backup into a DISPOSABLE LOCAL
# PostGIS container and prove it is complete. Never touches a real server.
#
#   scripts/restore_drill.sh --dump FILE [--manifest FILE] [--uploads FILE] [--app-image IMAGE]
#                            [--expect-head REV] [--keep] [--name NAME] [--network NAME]
#   scripts/restore_drill.sh --print-manifest-sql [--counts-only]
#   scripts/restore_drill.sh --print-image        (resolve + validate the db image, exit 2 if refused)
#
#   db image (Q73): with ELCHI_POSTGIS_IMAGE set (env or .env.app) only <registry>@sha256:<digest>;
#                 ELCHI_DRILL_DB_IMAGE overrides it but must also be digest-pinned then
#
#   --dump        db.dump[.gpg] from scripts/backup.sh (pg_dump custom format)
#   --manifest    manifest.tsv[.gpg] written in the dump's snapshot: every table's row count
#                 and checksum must match, plus the dump/uploads sha256 when recorded
#   --uploads     uploads.tar.gz[.gpg]: integrity, file count, and every upload key
#                 referenced by driver_documents/orders must be present
#   --app-image   also start the API image against the restored DB (dummy secrets, sharing
#                 only the drill container's loopback) and check /api/v1/health + readiness
#   --expect-head alembic revision the restored database must report
#   --keep        leave the container running for inspection (default: removed)
#   --network     attach to an existing docker network (default: none -- no network)
#
# Business checks (AC40): ledger debit = credit per transaction and currency; v1 orders by
# status; active v2 bookings by status once the bookings table exists (A4).
#
# *.gpg inputs are decrypted with `gpg --decrypt` into a private temp dir; the
# private key must be available to the operator running the drill.
#
# Output ends with a timing table. Only these measured numbers may be quoted as
# RTO for the dataset/machine used; see docs/ops/BACKUP_RESTORE.md.
set -euo pipefail

case "$(uname -s)" in MINGW* | MSYS* | CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;; esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/preflight.sh
source "$SCRIPT_DIR/lib/preflight.sh" # is_digest_pinned (pure, no side effects)

# Keep in sync with docker-compose.prod.yml (db service).
# Image (Q58, Q73): once the UZ registry is set -- ELCHI_POSTGIS_IMAGE in the environment or in the app
# env file (ELCHI_APP_ENV_FILE, default <repo>/.env.app) -- the drill runs ONLY a digest-pinned image
# (<registry>/elchi-postgis@sha256:<64 hex>); a tag is refused, also for an ELCHI_DRILL_DB_IMAGE override.
# Without a registry the local dev build tag is a fallback and the drill is not launch evidence.
DEV_FALLBACK_DB_IMAGE="elchi-postgis:16.15-3.5.3-trixie"
if [[ -z "${ELCHI_POSTGIS_IMAGE:-}" ]]; then
	env_file="${ELCHI_APP_ENV_FILE:-$REPO_ROOT/.env.app}"
	if [[ -r "$env_file" ]]; then
		ELCHI_POSTGIS_IMAGE="$(sed -n 's/^[[:space:]]*ELCHI_POSTGIS_IMAGE[[:space:]]*=[[:space:]]*//p' "$env_file" | tail -1 | tr -d '\r"'"'")"
	fi
fi
resolve_drill_image() {
	local image
	if [[ -n "${ELCHI_POSTGIS_IMAGE:-}" ]]; then
		image="${ELCHI_DRILL_DB_IMAGE:-$ELCHI_POSTGIS_IMAGE}"
		if ! is_digest_pinned "$image"; then
			echo "restore_drill: registry is set (ELCHI_POSTGIS_IMAGE) -- refusing image '$image': use <registry>/elchi-postgis@sha256:<64 hex digest> (Q73)" >&2
			return 2
		fi
	elif [[ "${ELCHI_DRILL_REQUIRE_DIGEST:-}" == "1" ]]; then
		echo "restore_drill: ELCHI_DRILL_REQUIRE_DIGEST=1 but ELCHI_POSTGIS_IMAGE is not set (Q73)" >&2
		return 2
	else
		image="${ELCHI_DRILL_DB_IMAGE:-$DEV_FALLBACK_DB_IMAGE}"
		is_digest_pinned "$image" ||
			echo "restore_drill: warning: no registry set, using unpinned dev image '$image' -- this drill is NOT launch/RTO evidence" >&2
	fi
	printf '%s\n' "$image"
}
INITDB_ARGS="--encoding=UTF8 --lc-collate=C --lc-ctype=C.UTF-8 --data-checksums"
DB_USER="${ELCHI_DRILL_DB_USER:-elchi}"
DB_NAME="${ELCHI_DRILL_DB_NAME:-elchi}"

# Session settings that make row text (and therefore checksums) independent of
# server defaults, timezone and collation. Used identically on both sides.
manifest_sql() {
	local mode="${1:-checksums}" hash_expr
	if [[ "$mode" == "counts" ]]; then
		hash_expr="'-'"
	else
		hash_expr="(xpath('/row/h/text()', query_to_xml(format('SELECT md5(coalesce(string_agg(r, E''\\n'' ORDER BY r COLLATE \"C\"), '''')) AS h FROM (SELECT t::text AS r FROM %I.%I t) s', n.nspname, c.relname), false, true, '')))[1]::text"
	fi
	cat <<SQL
SET TimeZone = 'UTC';
SET DateStyle = 'ISO, YMD';
SET IntervalStyle = 'postgres';
SET extra_float_digits = 3;
SET bytea_output = 'hex';
SELECT format('%I.%I', n.nspname, c.relname),
       (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text,
       ${hash_expr}
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
ORDER BY 1;
SQL
}

die() { echo "restore_drill: $*" >&2; exit 2; }
now_ms() { date +%s%3N; }
secs() { awk -v ms="$1" 'BEGIN { printf "%.1f", ms / 1000 }'; }

DUMP="" MANIFEST="" UPLOADS="" EXPECT_HEAD="" KEEP=0 NETWORK="none" NAME="" APP_IMAGE=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--print-manifest-sql)
		if [[ "${2:-}" == "--counts-only" ]]; then manifest_sql counts; else manifest_sql checksums; fi
		exit 0
		;;
	--print-image)
		# Resolve and validate the db image only (no Docker); exit 2 when refused.
		resolve_drill_image || exit 2
		exit 0
		;;
	--dump) DUMP="$2"; shift 2 ;;
	--manifest) MANIFEST="$2"; shift 2 ;;
	--uploads) UPLOADS="$2"; shift 2 ;;
	--expect-head) EXPECT_HEAD="$2"; shift 2 ;;
	--keep) KEEP=1; shift ;;
	--network) NETWORK="$2"; shift 2 ;;
	--name) NAME="$2"; shift 2 ;;
	--app-image) APP_IMAGE="$2"; shift 2 ;;
	-h | --help) sed -n '2,30p' "$0"; exit 0 ;;
	*) die "unknown argument: $1" ;;
	esac
done
[[ -n "$DUMP" ]] || die "--dump is required"
[[ -f "$DUMP" ]] || die "dump not found: $DUMP"
[[ -z "$MANIFEST" || -f "$MANIFEST" ]] || die "manifest not found: $MANIFEST"
[[ -z "$UPLOADS" || -f "$UPLOADS" ]] || die "uploads archive not found: $UPLOADS"
DB_IMAGE="$(resolve_drill_image)" || exit 2

# ── safety: local Docker daemon only ─────────────────────────────────────────
endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
[[ -n "${DOCKER_HOST:-}" ]] && endpoint="$DOCKER_HOST"
case "$endpoint" in
unix://* | npipe://*) ;;
*)
	[[ "${ELCHI_DRILL_ALLOW_REMOTE_DOCKER:-}" == "1" ]] ||
		die "refusing non-local Docker endpoint '$endpoint' (drills run on a disposable local daemon; set ELCHI_DRILL_ALLOW_REMOTE_DOCKER=1 only for a disposable drill host)"
	;;
esac

NAME="${NAME:-elchi-drill-$(date +%Y%m%d%H%M%S)-$RANDOM}"
WORK="$(mktemp -d)"
chmod 700 "$WORK"
cleanup() {
	local status=$?
	rm -rf "$WORK"
	if [[ "$KEEP" == 1 ]]; then
		echo "==> --keep: container $NAME left running (docker rm -f $NAME)"
	else
		docker rm -f "$NAME" >/dev/null 2>&1 || true
	fi
	exit "$status"
}
trap cleanup EXIT

decrypt_if_needed() {
	local src="$1" out
	if [[ "$src" == *.gpg ]]; then
		out="$WORK/$(basename "${src%.gpg}")"
		gpg --batch --quiet --decrypt --output "$out" "$src"
		echo "$out"
	else
		echo "$src"
	fi
}

psql_c() { docker exec -i "$NAME" psql -X -q -At -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" "$@"; }
table_exists() { [[ "$(psql_c -c "SELECT to_regclass('public.$1') IS NOT NULL")" == "t" ]]; }
DB_PASSWORD="drill-$RANDOM$RANDOM$RANDOM"

failures=0
fail() { echo "  FAIL: $*"; failures=$((failures + 1)); }
ok() { echo "  ok:   $*"; }

T0=$(now_ms)
echo "==> Decrypting inputs (if encrypted)"
DUMP_PLAIN="$(decrypt_if_needed "$DUMP")"
UPLOADS_PLAIN=""
[[ -n "$UPLOADS" ]] && UPLOADS_PLAIN="$(decrypt_if_needed "$UPLOADS")"
[[ -n "$MANIFEST" ]] && MANIFEST="$(decrypt_if_needed "$MANIFEST")"
T_DECRYPT=$(now_ms)

echo "==> Starting disposable database $NAME ($DB_IMAGE, network=$NETWORK)"
docker run -d --name "$NAME" --network "$NETWORK" \
	-e POSTGRES_USER="$DB_USER" -e POSTGRES_DB="$DB_NAME" \
	-e POSTGRES_PASSWORD="$DB_PASSWORD" \
	-e POSTGRES_INITDB_ARGS="$INITDB_ARGS" -e TZ=UTC \
	--tmpfs /docker-entrypoint-initdb.d \
	--shm-size 256m \
	"$DB_IMAGE" postgres -c timezone=UTC -c log_timezone=UTC >/dev/null
for _ in $(seq 1 120); do
	# -h 127.0.0.1 only answers after the entrypoint's temporary init server is gone.
	if docker exec "$NAME" pg_isready -q -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" 2>/dev/null; then break; fi
	sleep 1
done
docker exec "$NAME" pg_isready -q -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" || die "database did not become ready"
T_READY=$(now_ms)

if [[ -n "$MANIFEST" ]]; then
	expected_sha="$(awk -F'\t' '$1 == "# db_dump_sha256" { print $2 }' "$MANIFEST")"
	if [[ -n "$expected_sha" ]]; then
		actual_sha="$(sha256sum <"$DUMP_PLAIN" | cut -d' ' -f1)"
		[[ "$actual_sha" == "$expected_sha" ]] && ok "dump sha256 matches the manifest" || fail "dump sha256 $actual_sha != manifest $expected_sha"
	fi
fi

echo "==> pg_restore (single transaction, exit on error)"
docker exec -i "$NAME" pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl --exit-on-error --single-transaction <"$DUMP_PLAIN"
T_RESTORE=$(now_ms)

echo "==> ANALYZE"
docker exec "$NAME" vacuumdb -q -U "$DB_USER" -d "$DB_NAME" --analyze-only
T_ANALYZE=$(now_ms)

echo "==> Verification"
psql_c -F $'\t' -c "SELECT 'server_version', current_setting('server_version') UNION ALL SELECT 'timezone', current_setting('TimeZone') UNION ALL SELECT 'datcollate', datcollate FROM pg_database WHERE datname = current_database() UNION ALL SELECT 'datctype', datctype FROM pg_database WHERE datname = current_database()" |
	sed 's/^/  info: /'

restored_head="$(psql_c -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version" 2>/dev/null || echo "<no alembic_version>")"
if [[ -n "$EXPECT_HEAD" ]]; then
	[[ "$restored_head" == "$EXPECT_HEAD" ]] && ok "alembic_version = $restored_head" || fail "alembic_version = $restored_head, expected $EXPECT_HEAD"
else
	echo "  info: alembic_version = $restored_head"
fi

if [[ -n "$MANIFEST" ]]; then
	mode=checksums
	grep -v '^#' "$MANIFEST" | awk -F'\t' '$3 == "-" { found = 1 } END { exit !found }' && mode=counts
	manifest_sql "$mode" | psql_c -F $'\t' >"$WORK/restored.tsv"
	grep -v '^#' "$MANIFEST" | sort >"$WORK/expected.tsv"
	sort "$WORK/restored.tsv" >"$WORK/restored.sorted.tsv"
	expected_tables=$(wc -l <"$WORK/expected.tsv" | tr -d ' ')
	while IFS=$'\t' read -r table count hash; do
		line="$(awk -F'\t' -v t="$table" '$1 == t' "$WORK/restored.sorted.tsv")"
		if [[ -z "$line" ]]; then
			fail "$table missing after restore"
			continue
		fi
		r_count="$(cut -f2 <<<"$line")"
		r_hash="$(cut -f3 <<<"$line")"
		[[ "$r_count" == "$count" ]] || fail "$table rows $r_count != manifest $count"
		[[ "$mode" == counts || "$r_hash" == "$hash" ]] || fail "$table checksum differs"
	done <"$WORK/expected.tsv"
	extra="$(cut -f1 "$WORK/restored.sorted.tsv" | grep -vxF -f <(cut -f1 "$WORK/expected.tsv") || true)"
	[[ -z "$extra" ]] || echo "  info: tables present only after restore: $(tr '\n' ' ' <<<"$extra")"
	total_rows=$(awk -F'\t' '{ s += $2 } END { print s + 0 }' "$WORK/expected.tsv")
	[[ $failures -eq 0 ]] && ok "$expected_tables tables, $total_rows rows match the manifest ($mode)"
	manifest_uploads="$(awk -F'\t' '$1 == "# uploads_files" { print $2 }' "$MANIFEST")"
else
	echo "  info: no manifest given -- row counts NOT verified against the source"
	manifest_uploads=""
fi

echo "==> pg_amcheck --heapallindexed (B-tree + heap)"
if docker exec "$NAME" pg_amcheck -U "$DB_USER" -d "$DB_NAME" --install-missing --heapallindexed >"$WORK/amcheck.log" 2>&1; then
	ok "pg_amcheck clean"
else
	fail "pg_amcheck reported corruption:"
	sed 's/^/        /' "$WORK/amcheck.log" | head -20
fi
echo "==> Business checks (AC40)"
if table_exists ledger_entries; then
	unbalanced="$(psql_c -c "SELECT count(*) FROM (SELECT transaction_id, currency FROM ledger_entries GROUP BY 1, 2
		HAVING sum(amount_minor) FILTER (WHERE direction = 'debit') IS DISTINCT FROM sum(amount_minor) FILTER (WHERE direction = 'credit')) t")"
	totals="$(psql_c -F ' ' -c "SELECT count(DISTINCT transaction_id), count(*) FROM ledger_entries")"
	[[ "$unbalanced" == "0" ]] && ok "ledger: every transaction balanced per currency (transactions/entries: $totals)" ||
		fail "ledger: $unbalanced transaction/currency group(s) with debit != credit"
else
	echo "  info: ledger_entries not in this backup (pre-wallet schema)"
fi
if table_exists bookings; then
	# A4's column is service_status (wave 2); the wave 1 placeholder queried "status" and failed here.
	echo "  info: v2 bookings by service status:"
	psql_c -F ' ' -c "SELECT service_status, count(*) FROM bookings GROUP BY service_status ORDER BY service_status" | sed 's/^/        /'
	echo "  info: v2 bookings by commission status: $(psql_c -F '=' -c "SELECT commission_status, count(*) FROM bookings GROUP BY commission_status ORDER BY commission_status" | tr '
' ' ')"
	# Q4/AC37: a v1 order must never have been copied into the v2 write table.
	if table_exists orders; then
		legacy_rows="$(psql_c -c "SELECT count(*) FROM bookings b JOIN orders o ON o.order_number = b.public_id::text")"
		[[ "$legacy_rows" == "0" ]] && ok "no legacy order reached the v2 bookings table (Q4)" ||
			fail "AC37: $legacy_rows booking row(s) look like copied v1 orders"
	fi
else
	echo "  info: bookings table not present -- active v2 booking comparison is a placeholder until A4"
fi
if table_exists legacy_parcel_orders_v; then
	projected="$(psql_c -c "SELECT count(*) FROM legacy_parcel_orders_v")"
	source_rows="$(psql_c -c "SELECT count(*) FROM orders")"
	[[ "$projected" == "$source_rows" ]] && ok "legacy projection restored: $projected row(s) = orders" ||
		fail "legacy projection shows $projected row(s) for $source_rows order(s)"
fi
if table_exists alembic_revision_lineage; then
	echo "  info: revision lineage edges: $(psql_c -c "SELECT count(*) FROM alembic_revision_lineage") (Q50)"
fi
if table_exists orders; then
	echo "  info: v1 orders by status: $(psql_c -F '=' -c "SELECT status, count(*) FROM orders GROUP BY status ORDER BY status" | tr '\n' ' ')"
fi
T_VERIFY=$(now_ms)

if [[ -n "$UPLOADS_PLAIN" ]]; then
	echo "==> Uploads archive"
	# stdin, not a path: some tars read "C:/..." as host:path. A listing error is a failure.
	if gzip -t <"$UPLOADS_PLAIN" 2>/dev/null && listing="$(tar -tzf - <"$UPLOADS_PLAIN")"; then
		files=$(grep -vc '/$' <<<"$listing" || true)
		if [[ -n "$manifest_uploads" && "$files" != "$manifest_uploads" ]]; then
			fail "uploads archive has $files files, manifest says $manifest_uploads"
		else
			ok "uploads archive intact, $files files${manifest_uploads:+ (matches manifest)}"
		fi
		manifest_uploads_sha="$(awk -F'\t' '$1 == "# uploads_sha256" { print $2 }' "${MANIFEST:-/dev/null}" 2>/dev/null || true)"
		if [[ -n "$manifest_uploads_sha" ]]; then
			[[ "$(sha256sum <"$UPLOADS_PLAIN" | cut -d' ' -f1)" == "$manifest_uploads_sha" ]] &&
				ok "uploads archive sha256 matches the manifest" || fail "uploads archive sha256 differs from the manifest"
		fi
		# Every upload key referenced by the database must be in the archive (stored as /uploads/<key>).
		refs_sql="SELECT DISTINCT regexp_replace(ref, '^.*?/uploads/', '') FROM ("
		refs_parts=()
		table_exists driver_documents && refs_parts+=("SELECT file_url AS ref FROM driver_documents")
		table_exists orders && refs_parts+=("SELECT cargo_photo_url AS ref FROM orders")
		if [[ ${#refs_parts[@]} -gt 0 ]]; then
			joined="$(printf ' UNION ALL %s' "${refs_parts[@]}")"
			psql_c -c "$refs_sql${joined# UNION ALL } ) r WHERE ref LIKE '%/uploads/%'" | sort -u >"$WORK/referenced.txt"
			sed -n 's#^uploads/##p' <<<"$listing" | grep -v '/$' | sort -u >"$WORK/archived.txt"
			missing="$(comm -23 "$WORK/referenced.txt" "$WORK/archived.txt")"
			referenced=$(wc -l <"$WORK/referenced.txt" | tr -d ' ')
			if [[ -z "$missing" ]]; then
				ok "all $referenced upload key(s) referenced by driver_documents/orders are in the archive"
			else
				fail "$(wc -l <<<"$missing" | tr -d ' ') referenced upload key(s) missing from the archive, e.g. $(head -3 <<<"$missing" | tr '\n' ' ')"
			fi
		fi
	else
		fail "uploads archive is not a readable tar.gz"
	fi
else
	echo "  info: no uploads archive given -- attachment references NOT verified"
fi

if [[ -n "$APP_IMAGE" ]]; then
	echo "==> App smoke ($APP_IMAGE, dummy secrets, no network beyond the drill database)"
	api="$NAME-api"
	# Shares only the drill container's loopback: no route anywhere else.
	docker run -d --name "$api" --network "container:$NAME" --read-only --tmpfs /tmp --tmpfs /app/storage/uploads:uid=1000 \
		-e ELCHI_ENVIRONMENT=test -e ELCHI_DEBUG=false -e ELCHI_SMS_ENABLED=false \
		-e ELCHI_SECRET_KEY="drill-$RANDOM$RANDOM-dummy-secret-key-000" \
		-e ELCHI_DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME" \
		"$APP_IMAGE" uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-config app/ops/uvicorn_log_config.json >/dev/null
	health=""
	for _ in $(seq 1 40); do
		health="$(docker exec "$api" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/health 2>/dev/null || true)"
		[[ "$health" == "200" ]] && break
		sleep 1
	done
	[[ "$health" == "200" ]] && ok "GET /api/v1/health 200" || { fail "api did not answer /api/v1/health (HTTP ${health:-none})"; docker logs "$api" 2>&1 | tail -5; }
	ready="$(docker exec "$api" curl -s -w ' HTTP %{http_code}' http://127.0.0.1:8000/health/ready 2>/dev/null || true)"
	echo "  info: /health/ready -> $ready"
	grep -q '"database":"ok"' <<<"$ready" && ok "readiness: database ok" || fail "readiness: database not ok"
	docker rm -f "$api" >/dev/null 2>&1 || true
fi
T_END=$(now_ms)

dump_bytes=$(wc -c <"$DUMP_PLAIN" | tr -d ' ')
cat <<EOF

==> Timing (this machine, this dataset; dump $dump_bytes bytes)
  decrypt            $(secs $((T_DECRYPT - T0))) s
  start database     $(secs $((T_READY - T_DECRYPT))) s
  pg_restore         $(secs $((T_RESTORE - T_READY))) s
  analyze            $(secs $((T_ANALYZE - T_RESTORE))) s
  verify + amcheck   $(secs $((T_VERIFY - T_ANALYZE))) s
  uploads check      $(secs $((T_END - T_VERIFY))) s
  total (drill RTO)  $(secs $((T_END - T0))) s
EOF
if [[ -n "$MANIFEST" ]]; then
	created="$(awk -F'\t' '$1 == "# snapshot_at" { print $2 }' "$MANIFEST")"
	[[ -n "$created" ]] && echo "  data recovered up to snapshot_at = $created (RPO of this backup = incident time - that)"
fi

if [[ $failures -gt 0 ]]; then
	echo "==> DRILL FAILED ($failures problem(s))"
	exit 1
fi
echo "==> DRILL PASSED"
