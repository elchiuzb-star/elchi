#!/usr/bin/env bash
# Daily backup (spec §19.2, K3, ADR-0011): snapshot-consistent database dump +
# manifest + uploads, streamed straight into gpg (no plaintext data on disk, BR #12),
# shipped off-box to storage in Uzbekistan.
#
#   scripts/backup.sh                 # full run (dump, encrypt, ship, prune)
#   scripts/backup.sh --local-only    # no shipping (pre-deploy safety copy, drills)
#   scripts/backup.sh --tag pre-deploy
#
# cron (host clock in UTC):
#   15 2 * * * /opt/elchi/scripts/backup.sh >> /var/log/elchi-backup.log 2>&1
#
# Configuration: environment, or KEY=VALUE lines in $BACKUP_CONFIG
# (default /etc/elchi/backup.env, mode 600). The file is parsed, never sourced.
#   BACKUP_DIR               local staging (default /var/backups/elchi, created 0700)
#   BACKUP_RETENTION_DAYS    local copies to keep (default 7)
#   BACKUP_GPG_RECIPIENT     public key fingerprint; the private key is NOT on this server.
#                            Required unless BACKUP_ALLOW_PLAINTEXT=1 (local drills only).
#   BACKUP_REMOTE            rsync target, e.g. elchi-backup@backup.example.uz:/srv/elchi
#                            (Uzbekistan, different provider/datacenter = different failure domain)
#   BACKUP_RSYNC_SSH         ssh command for rsync (default: ssh -o BatchMode=yes)
#   BACKUP_CHECKSUMS         1 (default) = per-table md5 in the manifest; 0 = counts only
#   BACKUP_WAL               1 = ship the WAL archive and prune shipped segments (non-production only)
#   BACKUP_BASEBACKUP        1 = also take a pg_basebackup (PITR base; non-production only)
#   ELCHI_APP_ENV_FILE       compose --env-file / app env (default .env.app); read for ELCHI_ENVIRONMENT
#   ELCHI_DB_ADMIN_ENV_FILE  db-admin env file passed through to compose (default .env.db-admin)
#   ELCHI_COMPOSE_PROJECT    compose project name override (default elchi)
#
# Output per run: db.dump, manifest.tsv, globals.sql, uploads.tar.gz, uploads-files.txt
# (all *.gpg unless plaintext is allowed) and SHA256SUMS of the files on disk. The
# manifest records sha256 of the plaintext dump/archive for scripts/restore_drill.sh.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
case "$(uname -s)" in MINGW* | MSYS* | CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;; esac

LOCAL_ONLY=0
TAG="daily"
while [[ $# -gt 0 ]]; do
	case "$1" in
	--local-only) LOCAL_ONLY=1; shift ;;
	--tag) TAG="$2"; shift 2 ;;
	-h | --help) sed -n '2,31p' "$0"; exit 0 ;;
	*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
done

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# Parse KEY=VALUE without executing anything; environment wins over the file.
BACKUP_CONFIG="${BACKUP_CONFIG:-/etc/elchi/backup.env}"
if [[ -f "$BACKUP_CONFIG" ]]; then
	while IFS='=' read -r key value; do
		[[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
		[[ -n "${!key:-}" ]] || export "$key=$value"
	done < <(grep -E '^[A-Z_][A-Z0-9_]*=' "$BACKUP_CONFIG")
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/elchi}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
BACKUP_CHECKSUMS="${BACKUP_CHECKSUMS:-1}"
BACKUP_RSYNC_SSH="${BACKUP_RSYNC_SSH:-ssh -o BatchMode=yes}"
ENV_FILE="${ELCHI_APP_ENV_FILE:-.env.app}"
export ELCHI_APP_ENV_FILE="$ENV_FILE" ELCHI_DB_ADMIN_ENV_FILE="${ELCHI_DB_ADMIN_ENV_FILE:-.env.db-admin}"
PROJECT="${ELCHI_COMPOSE_PROJECT:-elchi}"

[[ -f "$ENV_FILE" ]] || die "$ENV_FILE is missing"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)
[[ -n "${ELCHI_COMPOSE_PROJECT:-}" ]] && COMPOSE+=(-p "$ELCHI_COMPOSE_PROJECT")
ENVIRONMENT="$(grep -E '^ELCHI_ENVIRONMENT=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]' || true)"

if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
	command -v gpg >/dev/null || die "gpg is not installed"
	gpg --batch --list-keys "$BACKUP_GPG_RECIPIENT" >/dev/null 2>&1 || die "public key $BACKUP_GPG_RECIPIENT is not imported"
elif [[ "${BACKUP_ALLOW_PLAINTEXT:-}" != "1" ]]; then
	die "BACKUP_GPG_RECIPIENT is not set; refusing to write unencrypted backups (BACKUP_ALLOW_PLAINTEXT=1 is for local drills only)"
elif [[ "$ENVIRONMENT" == "production" ]]; then
	die "BACKUP_ALLOW_PLAINTEXT=1 is refused for ELCHI_ENVIRONMENT=production (BR wave 1.6 N6); set BACKUP_GPG_RECIPIENT"
fi
if [[ "$LOCAL_ONLY" == 0 && -z "${BACKUP_REMOTE:-}" ]]; then
	die "BACKUP_REMOTE is not set; a backup on the same server does not survive losing the server (use --local-only deliberately)"
fi
if [[ "$ENVIRONMENT" == "production" && ( "${BACKUP_WAL:-0}" == "1" || "${BACKUP_BASEBACKUP:-0}" == "1" ) ]]; then
	die "BACKUP_WAL/BACKUP_BASEBACKUP are not allowed in production until WAL encryption exists (decision 35)"
fi

umask 077
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/$STAMP-$TAG"
mkdir -p "$DEST"
chmod 700 "$BACKUP_DIR" "$DEST"
META="$(mktemp -d)" # checksums and counters only (no data)
trap 'rm -rf "$META"' EXIT
started=$(date +%s)

# Process substitutions (checksums, listings) finish asynchronously and `$!` does not
# reliably point at them (it may be the coproc), so wait for their output files instead.
wait_for_file() {
	local file="$1" waited=0
	until [[ -s "$file" ]]; do
		((waited++ < 600)) || die "timed out waiting for $file"
		sleep 0.1
	done
	sleep 0.2 # the writer may still be flushing its single line
}

# stdin -> $1(.gpg). Plaintext only when explicitly allowed.
encrypt_to() {
	if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
		gpg --batch --yes --trust-model always --recipient "$BACKUP_GPG_RECIPIENT" --encrypt --output "$1.gpg"
	else
		cat >"$1"
	fi
}

db_container="$("${COMPOSE[@]}" ps -q db)"
[[ -n "$db_container" ]] || die "db service is not running"

# ── 1. database: dump and manifest from ONE snapshot ─────────────────────────
# A REPEATABLE READ transaction exports its snapshot; pg_dump reuses it and the
# manifest (row counts/checksums) is computed inside the same transaction.
log "exporting snapshot"
coproc SNAP { "${COMPOSE[@]}" exec -T db sh -c 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
snap_pid=$SNAP_PID # bash unsets SNAP/SNAP_PID when the coprocess exits
exec {SNAP_IN}>&"${SNAP[1]}" {SNAP_OUT}<&"${SNAP[0]}"
printf '%s\n' "\\pset fieldsep '\\t'" "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;" "SELECT pg_export_snapshot();" >&"$SNAP_IN"
IFS= read -r -t 60 snapshot <&"$SNAP_OUT" || die "could not export a snapshot"
[[ "$snapshot" =~ ^[0-9A-F-]+$ ]] || die "unexpected snapshot id: $snapshot"

log "pg_dump (custom format) | encrypt -> $DEST/db.dump"
"${COMPOSE[@]}" exec -T db sh -c "exec pg_dump -Fc -Z 6 --snapshot='$snapshot' -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"" |
	tee >(sha256sum | cut -d' ' -f1 >"$META/db.sha256.tmp" && mv "$META/db.sha256.tmp" "$META/db.sha256") | encrypt_to "$DEST/db.dump"
wait_for_file "$META/db.sha256"

log "manifest (same snapshot)"
manifest_args=(--print-manifest-sql)
[[ "$BACKUP_CHECKSUMS" == "1" ]] || manifest_args+=(--counts-only)
{
	printf '%s\n' "SELECT '# snapshot_at' || E'\\t' || to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"');"
	printf '%s\n' "SELECT '# server_version' || E'\\t' || current_setting('server_version');"
	printf '%s\n' "SELECT '# datcollate' || E'\\t' || datcollate || '/' || datctype FROM pg_database WHERE datname = current_database();"
	printf '%s\n' "SELECT '# alembic_version' || E'\\t' || coalesce((SELECT string_agg(version_num, ',') FROM alembic_version), '');"
	bash "$REPO_ROOT/scripts/restore_drill.sh" "${manifest_args[@]}"
	printf '%s\n' "SELECT '__MANIFEST_END__';" "COMMIT;" '\q'
} >&"$SNAP_IN"
manifest_lines=()
while IFS= read -r -t 3600 line <&"$SNAP_OUT"; do
	[[ "$line" == "__MANIFEST_END__" ]] && break
	manifest_lines+=("$line")
done
exec {SNAP_IN}>&- {SNAP_OUT}<&-
wait "$snap_pid" 2>/dev/null || true
[[ "${manifest_lines[0]:-}" == "# snapshot_at"$'\t'* ]] || die "manifest is incomplete"
[[ -s "$META/db.sha256" ]] || die "dump checksum missing (pg_dump failed?)"

log "globals (roles, no passwords) | encrypt"
"${COMPOSE[@]}" exec -T db sh -c 'exec pg_dumpall --globals-only --no-role-passwords -U "$POSTGRES_USER"' | encrypt_to "$DEST/globals.sql"

# ── 2. uploads (after the DB snapshot => a superset of referenced files) ─────
# Read-only mount of the volume into the already-present db image: no build, no pull
# and no dependency on the api container (BR #11).
db_image="$(docker inspect --format '{{.Config.Image}}' "$db_container")"
log "uploads volume ${PROJECT}_uploads | tar | gzip | encrypt"
docker run --rm --network none -v "${PROJECT}_uploads:/app/storage/uploads:ro" --entrypoint tar "$db_image" \
	-cf - -C /app/storage uploads |
	tee >(tar -tf - | tee >({ grep -vc '/$' || true; } >"$META/uploads.count.tmp" && mv "$META/uploads.count.tmp" "$META/uploads.count") |
		encrypt_to "$DEST/uploads-files.txt") |
	gzip -6 | tee >(sha256sum | cut -d' ' -f1 >"$META/uploads.sha256.tmp" && mv "$META/uploads.sha256.tmp" "$META/uploads.sha256") |
	encrypt_to "$DEST/uploads.tar.gz"
wait_for_file "$META/uploads.count"
wait_for_file "$META/uploads.sha256"

{
	printf '%s\n' "${manifest_lines[@]}"
	printf '# db_dump_sha256\t%s\n' "$(cat "$META/db.sha256")"
	printf '# uploads_files\t%s\n' "$(cat "$META/uploads.count")"
	printf '# uploads_sha256\t%s\n' "$(cat "$META/uploads.sha256")"
} | encrypt_to "$DEST/manifest.tsv"

# ── 3. optional PITR base backup (non-production) ────────────────────────────
if [[ "${BACKUP_BASEBACKUP:-0}" == "1" ]]; then
	log "pg_basebackup (tar, gzip) | encrypt"
	"${COMPOSE[@]}" exec -T db sh -c 'exec pg_basebackup -U "$POSTGRES_USER" -D - -Ft -z -X fetch --checkpoint=fast' | encrypt_to "$DEST/base.tar.gz"
fi

[[ -n "${BACKUP_GPG_RECIPIENT:-}" ]] || log "WARNING: BACKUP_ALLOW_PLAINTEXT=1 -- files are NOT encrypted"
(cd "$DEST" && sha256sum -- * >SHA256SUMS)

# ── 4. ship off-box ──────────────────────────────────────────────────────────
if [[ "$LOCAL_ONLY" == 0 ]]; then
	log "shipping to $BACKUP_REMOTE"
	# No --delete: the remote side keeps its own retention and should not let
	# this server remove history (compromised-server / ransomware case).
	rsync -a --partial -e "$BACKUP_RSYNC_SSH" "$DEST" "$BACKUP_REMOTE/"
	if [[ "${BACKUP_WAL:-0}" == "1" ]]; then
		wal_dir="$(docker volume inspect "${PROJECT}_pgwal_archive" --format '{{.Mountpoint}}')"
		log "shipping WAL archive $wal_dir (shipped segments are removed locally, BR #10)"
		# --remove-source-files deletes a segment only after rsync confirmed its transfer;
		# the newest segments still being written by archive_command are not yet present.
		rsync -a --partial --remove-source-files -e "$BACKUP_RSYNC_SSH" "$wal_dir/" "$BACKUP_REMOTE/wal/"
	fi
fi

# ── 5. local retention ───────────────────────────────────────────────────────
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '*Z-*' -mtime "+$BACKUP_RETENTION_DAYS" -exec rm -rf {} +

log "done in $(($(date +%s) - started))s: $DEST ($(du -sh "$DEST" | cut -f1)), $(wc -l <"$DEST/SHA256SUMS" | tr -d ' ') files"
