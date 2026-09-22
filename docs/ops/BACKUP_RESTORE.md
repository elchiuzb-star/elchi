# Backup and restore

Owner: A10a · 2026-09-13 · spec §19.1–19.2, §18.3 · ADR-0011 (K3) · AC40

> **Production model (decision 35): daily encrypted dumps, RPO ≤ 24 h** (plus backup duration). WAL archiving / PITR is **not allowed in production** until WAL encryption exists: `scripts/deploy.sh` refuses `PG_ARCHIVE_MODE=on`, and `scripts/backup.sh` refuses `BACKUP_WAL`/`BACKUP_BASEBACKUP` for `ELCHI_ENVIRONMENT=production`.
> **Production RPO and RTO are unmeasured.** The spec targets RPO ≤ 15 min and RTO ≤ 2 h (§19.2); those are goals, not claims. The only measured figures are from local drills on synthetic data (§7).
>
> Financial follow-up after a restore or account deletion (refunds of prepaid balances): [FINANCE_REFUNDS.md](FINANCE_REFUNDS.md) (owner A3).

## 1. What is backed up

| Item | How | File in the backup set |
|---|---|---|
| Database | `pg_dump -Fc` inside an exported REPEATABLE READ snapshot, **piped straight into gpg** | `db.dump.gpg` |
| Manifest | Row count and md5 of every table **computed in the same snapshot**; snapshot time, server version, locale, alembic head; sha256 of the plaintext dump and uploads archive (computed from the streams); uploads file count | `manifest.tsv.gpg` |
| Roles | `pg_dumpall --globals-only --no-role-passwords` | `globals.sql.gpg` |
| Uploads (private driver documents, cargo photos) | read-only mount of the `uploads` volume into the already-present db image (`docker run --rm --network none -v elchi_uploads:...:ro`; no build, no pull, no api container), tar → gzip → gpg, taken **after** the DB snapshot so every file the DB references is included | `uploads.tar.gz.gpg`, `uploads-files.txt.gpg` (listing) |
| PITR base (non-production only) | `pg_basebackup -Ft -z -X fetch` → gpg | `base.tar.gz.gpg` |
| WAL (non-production only) | archived by Postgres into the `pgwal_archive` volume (plaintext), shipped by rsync, shipped segments removed locally | `wal/` on the remote |
| Integrity | `sha256sum` of the encrypted files | `SHA256SUMS` |

No plaintext data touches the disk (BR #12). Only checksums and the file counter live in a temporary directory during the run.

**Not in the backup set:** `.env.app`, `.env.db-admin` and `/etc/elchi/backup.env`. Keep them in the team password manager or an offline encrypted store. A backup that also holds the secrets to decrypt it and to impersonate the API is one breach away from total loss.

## 2. Where (K3 residency, failure domain)

- **In Uzbekistan.** The backup target must be in Uzbekistan too: another provider, or at least another datacenter and account of the same provider. It must not share the server's power, network, account or credentials.
- **Append-only from production.** The server's SSH key may only write, never delete. Use `rrsync -wo /srv/elchi` in the backup host's `authorized_keys` (`command="rrsync -wo /srv/elchi",restrict ssh-ed25519 …`). `backup.sh` never uses `--delete`. Retention runs on the backup host.
- **Encrypted before leaving the server.** gpg with a **public key** only: the private key is not on the server. Keep it offline, with two named custodians. Losing the private key means losing every backup; test decryption during each drill.

## 3. Schedule and retention (proposal; confirm with the legal retention review)

| Copy | Schedule | Retention |
|---|---|---|
| Local staging (`/var/backups/elchi`) | daily 02:15 UTC (07:15 Tashkent) | 7 days (`BACKUP_RETENTION_DAYS`) |
| Remote daily | same run | 14 days |
| Remote weekly (Sunday run) | — | 8 weeks |
| Remote monthly (1st) | — | 12 months |
| WAL archive (if PITR on) | continuous, shipped every 5 min | back to the oldest retained base backup |
| Pre-deploy copy | every `deploy.sh` with schema present | local 7 days |

GPS raw points are proposed to live 7 days (spec §10.7), but database backups contain them for the backup retention period. Include this in the retention review (UZ_HOSTING_RUNBOOK.md L6).

## 4. Setup (on the server)

```bash
# Offline machine, once: create the backup keypair; export ONLY the public key.
gpg --quick-gen-key "Elchi backup <ops@elchi.uz>" rsa4096 encrypt 2y
gpg --armor --export ops@elchi.uz > elchi-backup-public.asc     # copy to the server

# Server:
gpg --import elchi-backup-public.asc
install -d -m 700 /etc/elchi /var/backups/elchi
cat > /etc/elchi/backup.env <<'EOF'
BACKUP_GPG_RECIPIENT=<fingerprint from gpg --list-keys>
BACKUP_REMOTE=elchi-backup@<backup-host-in-UZ>:/srv/elchi
BACKUP_RSYNC_SSH=ssh -i /root/.ssh/elchi_backup -o BatchMode=yes -o StrictHostKeyChecking=yes
BACKUP_RETENTION_DAYS=7
BACKUP_CHECKSUMS=1
EOF
chmod 600 /etc/elchi/backup.env
crontab -e
#   15 2 * * *  /opt/elchi/scripts/backup.sh >> /var/log/elchi-backup.log 2>&1
# (daily encrypted dump only; the weekly base backup / WAL shipping below is staging-only)
```

### PITR option: staging / non-production only (decision 35)
Blocked for production until WAL encryption exists: archived WAL segments sit unencrypted in `pgwal_archive` and are shipped as plaintext. A gpg `archive_command`/`restore_command` wrapper is **not implemented** (optional in decision 35). When it is built and PITR-tested, this section changes to "ready, off by default".

If PITR is used on staging:
- **Pruning (BR #10):** `backup.sh` ships with `rsync --remove-source-files`, so a segment is deleted locally only after its transfer was confirmed.
- **Volume alert:** alert when `pgwal_archive` exceeds, e.g., 5 GB or 20 % of the disk. A failing shipper silently fills the disk and eventually stops PostgreSQL (`archive_command` keeps failing and WAL piles up in `pg_wal`).
  `du -sh "$(docker volume inspect elchi_pgwal_archive -f '{{.Mountpoint}}')"`.

1. In the env file set `PG_ARCHIVE_MODE=on` and `PG_ARCHIVE_TIMEOUT=300`. Restart db in a window (`$C up -d db`).
2. Ship WAL every 5 minutes. The bound on data loss becomes about `archive_timeout` + ship interval (≈10 min), **but only after a PITR restore has been rehearsed.**
   `*/5 * * * * rsync -a -e "ssh -i /root/.ssh/elchi_backup -o BatchMode=yes" "$(docker volume inspect elchi_pgwal_archive -f '{{.Mountpoint}}')/" elchi-backup@<host>:/srv/elchi/wal/`
3. Take a weekly base backup (staging crontab; `backup.sh` refuses these variables when `ELCHI_ENVIRONMENT=production`):
   `30 3 * * 0  BACKUP_BASEBACKUP=1 BACKUP_WAL=1 /opt/elchi/scripts/backup.sh --tag weekly >> /var/log/elchi-backup.log 2>&1`
4. Monitor `SELECT archived_count, failed_count, last_failed_time FROM pg_stat_archiver;`. A growing `failed_count` fills the disk and makes PITR impossible.
5. Prune archived WAL older than the oldest retained base backup on the backup host (`pg_archivecleanup`), not on the server.

PITR restore outline:
- Extract `base.tar.gz` into an empty data dir of the same image.
- Put `restore_command = 'cp /wal/%f %p'` and `recovery_target_time = '<UTC time>'` in `postgresql.auto.conf`, and `touch recovery.signal`.
- Start, check, then `SELECT pg_wal_replay_resume();`.

**Status:** WAL archiving (compose entrypoint + `archive_command`) and a PITR restore were rehearsed **locally on synthetic data** (§7.2). The production WAL shipping cron, the backup-host pruning and a PITR restore from the real backup host are **not** rehearsed. Until they are, do not claim an RPO below 24 h.

## 5. Restore drill (`scripts/restore_drill.sh`)

The drill restores into a **disposable local container**: `--network none`, same PostGIS image and initdb locale as production, removed afterwards. It proves:
- the dump restores (`--exit-on-error --single-transaction`);
- every table's row count and checksum equals the manifest from the source snapshot;
- `pg_amcheck --heapallindexed` is clean;
- the alembic head is as expected, and the dump and uploads archive match the manifest's sha256 and file count;
- **ledger:** debit = credit for every transaction and currency;
- **attachments:** every upload key referenced by `driver_documents.file_url` / `orders.cargo_photo_url` is in the archive;
- v1 orders by status; active v2 bookings by status once A4's `bookings` table exists (placeholder until then);
- optionally (`--app-image`), the API starts against the restored DB with dummy secrets, sharing only the drill container's loopback, and answers `/api/v1/health` and readiness;
- how long each step took.

```bash
./scripts/restore_drill.sh --dump   /var/backups/elchi/<stamp>/db.dump.gpg \
                           --manifest /var/backups/elchi/<stamp>/manifest.tsv.gpg \
                           --uploads  /var/backups/elchi/<stamp>/uploads.tar.gz.gpg \
                           --expect-head <alembic head>
```

It refuses a non-local Docker endpoint (`DOCKER_HOST`/context) unless `ELCHI_DRILL_ALLOW_REMOTE_DOCKER=1`.

**Image (Q58, Q73).** Once the UZ registry is set, meaning `ELCHI_POSTGIS_IMAGE` is present in the environment or in `.env.app` (`ELCHI_APP_ENV_FILE` overrides the path), the drill runs **only** a digest-pinned image `<registry>/elchi-postgis@sha256:<64 hex>`:
- a tag is refused with exit 2 before Docker is touched;
- an `ELCHI_DRILL_DB_IMAGE` override must also be digest-pinned.

Without a registry, the local dev tag `elchi-postgis:16.15-3.5.3-trixie` is used with a warning. Such a drill is **not** launch or RTO evidence. `ELCHI_DRILL_REQUIRE_DIGEST=1` forbids that fallback, so use it on the UZ drill host. Check the image without running a drill: `scripts/restore_drill.sh --print-image`. Record the printed digest in the ops log next to the timing table.

**Cadence:** monthly, before every release that contains a migration, and after any backup-configuration change. Run drills with real backups **on a host in Uzbekistan** controlled by the team, never on a personal laptop. Record the timing table in the ops log: that record is the only admissible RTO evidence.

## 6. Real restore into the production stack

1. Stop writers and the database: `$C stop api worker db`.
2. Keep the damaged data for forensics. Compose uses a fixed volume name, so copy it aside before removing it (or restore on a fresh host instead):
   ```bash
   docker volume create elchi_pgdata_broken_$(date -u +%Y%m%d)
   docker run --rm -v elchi_pgdata_pg16_postgis:/from:ro -v elchi_pgdata_broken_$(date -u +%Y%m%d):/to alpine cp -a /from/. /to/
   $C rm -f db && docker volume rm elchi_pgdata_pg16_postgis    # compose recreates it empty on the next `up`
   ```
3. Restore with POSTGRES_POSTGIS_MIGRATION.md §5.3 steps 2–6 (same commands, same checks).
4. `$C run --rm migrate` (no-op if the backup is at head), then `$C up -d api worker`.
5. **Money/booking history after the backup point is lost from the DB.** Reconcile from outbox/audit/SMS logs and operator records. Never "fix" by replaying old dumps over newer financial rows (spec §18.3).

## 7. Measured results (local drill, synthetic data)

Everything below ran on the A10a Windows laptop (Docker Desktop 29.6.2, Git Bash), with dummy secrets and synthetic data only. **These numbers are not production RPO/RTO.**

### 7.0 Wave 1.5 (2026-09-14): streaming encryption, business checks, app smoke

Stack: `docker compose -p a10s --env-file <dummy.env> -f docker-compose.prod.yml`. It ran `elchi-postgis:16.15-3.5.3-trixie`, the db-roles job, migrate as `elchi_owner` (head `20260914_0044`), api/worker as `elchi_app`, and 2 upload files.

| Check | Result |
|---|---|
| Plaintext-mode backup under load | 200 concurrent `INSERT`s. Backup exit 0 in 6.9 s while writes were still running. The manifest records `audit_logs` = **211**: the table went 200 → 400 during the run, and the manifest reflects the snapshot. `sha256sum -c`: 5/5 OK. |
| Drill of that backup with `--app-image` | Dump sha256 matches the manifest; `C`/`C.UTF-8`, head `20260914_0044`; **59 tables / 236 rows match by checksum**; `pg_amcheck` clean; ledger balanced (0 entries); uploads intact, 2 files, archive sha256 matches; 0 referenced keys (no seeded documents) all present. The api image started against the restored DB with `--network container:<drill>`: `GET /api/v1/health` 200, `/health/ready` `database: ok, migrations: ok`. **Total 22.6 s.** |
| gpg-mode backup (BR #12) | Keypair generated in a container (the offline "operator"). Only the public key was imported into the host gpg. `backup.sh` exit 0 in 5.1 s; 5 `.gpg` files + `SHA256SUMS`, **0 plaintext data files on disk**; the server keyring cannot decrypt. |
| Drill of the gpg backup | Decrypted with the offline key: dump sha256 matches; 59 tables / 425 rows match; `pg_amcheck` clean; uploads + sha256 match. **Total 15.6 s.** |
| Business-check negative controls | A referenced upload missing from the archive → `FAIL: 1 referenced upload key(s) missing … cargo/2026/09/8/box.jpg`, exit 1. An unbalanced ledger transaction (500 debit / 400 credit) → `FAIL: ledger: 1 transaction/currency group(s) with debit != credit`, exit 1. The complete, balanced case → PASS (3 referenced keys found, 2 transactions balanced). |
| Guards | No gpg recipient → refuses. Production env + `BACKUP_WAL=1` → refuses (decision 35). |
| Bug found and fixed | `wait $!` after a `tee >(sha256sum)` pipeline waited on the snapshot coprocess instead of the checksum (hung). Replaced with a bounded wait on the checksum files. |

### 7.2 Wave 5 (2026-09-17): the drill at head `20260916_0067`

Why again: the business checks of the drill were written in wave 1, before A4's `bookings` table existed. Against
a wave-5 schema the drill **failed on its own query** (`SELECT status ... FROM bookings` - the column is
`service_status`), so the AC40 tooling had to be fixed before it could be evidence for anything.

Dataset (synthetic, no real data): `scripts/seed_admin_required_data.py` + `scripts/seed_demo_marketplace_data.py`
- 14 cities, 176 districts, 10 clients, 10 approved drivers, 30 v1 orders with bids, offers, ratings and status
history. `pg_dump -Fc` = 669 672 bytes.

```bash
scripts/restore_drill.sh --dump <scratch>/drill.dump --expect-head 20260916_0067
```

| Check | Result |
|---|---|
| Restore | `alembic_version = 20260916_0067`, `pg_amcheck --heapallindexed` clean |
| Ledger | balanced per currency (0 transactions in this dataset) |
| Q4 / AC37 | **no legacy order reached the v2 `bookings` table**; the legacy projection restored 30 rows = `orders` |
| Q50 | 67 revision lineage edges restored |
| v1 orders by status | accepted 5, bidding 5, cancelled 1, confirmed 4, delivered 3, disputed 1, in_transit 3, picked_up 3, published 5 |
| Timing | decrypt 0.0 s · db start 2.6 s · `pg_restore` 3.3 s · analyze 0.7 s · verify + amcheck 6.6 s · **total 13.3 s** |
| Fixed in the script | booking status columns (`service_status`, `commission_status`), the AC37 check, the projection row count and the lineage count |

**Not proven by this run:** the image was the **unpinned local dev tag** (the script says so itself), so this is
not Q34/Q51/Q73 evidence and not an RTO number for the real database; no manifest was given, so row counts were
not compared against a source snapshot; no uploads archive, so attachment references were not checked; the
encrypted daily-dump path (Q35) was exercised in §7.0, not here. The official AC40 drill runs on the deployment
host with `scripts/backup.sh --local-only` output (dump + manifest + uploads) and a digest-pinned registry image.

### 7.1 `backup.sh` + `restore_drill.sh` against the local prod-compose stack (wave 1, 2026-09-13)

Stack: `docker compose -p a10s --env-file <dummy.env> -f docker-compose.prod.yml` (all 41 migrations applied, `seed_cities.py`, 2 upload files).

```bash
# 200 INSERTs into audit_logs running concurrently in the background
ELCHI_ENV_FILE=<dummy.env> ELCHI_COMPOSE_PROJECT=a10s BACKUP_CONFIG=/nonexistent \
BACKUP_DIR=<scratch>/backups BACKUP_ALLOW_PLAINTEXT=1 scripts/backup.sh --local-only --tag smoke
scripts/restore_drill.sh --dump <b>/db.dump --manifest <b>/manifest.tsv --uploads <b>/uploads.tar.gz --expect-head 20260913_0041
```

| Check | Result |
|---|---|
| Backup | exit 0 in 4.0 s. Writes were still running when it finished. `sha256sum -c SHA256SUMS`: all OK |
| Snapshot consistency | `audit_logs` went 700 → 900 during the run; the manifest records **708** (snapshot 17:43:33Z). The drill matched **58 tables / 2 931 rows by checksum**, so dump and manifest come from the same snapshot. |
| Drill | `datcollate C`, `datctype C.UTF-8`, `alembic_version = 20260913_0041`, `pg_amcheck` clean, uploads archive intact with 2 files matching the manifest. **Total 13.8 s (dump 331 KB).** |
| Negative controls | tampered row count + wrong head → `FAIL` ×2, exit 1. Truncated uploads archive → `FAIL`, exit 1. No leftover containers. |
| Guards | no `BACKUP_GPG_RECIPIENT` → refuses; no `BACKUP_REMOTE` without `--local-only` → refuses |
| Encryption | Git Bash's gpg could not start `gpg-agent` on this host, so the gpg step of `backup.sh` was **not executed end-to-end here**. The exact commands were run in the PostGIS image (gpg 2.2.27): `gpg --batch --yes --trust-model always --recipient <fpr> --encrypt` with only the public key present (the "server" could not decrypt), then `gpg --batch --decrypt` with the private key produced an identical file. Run `backup.sh` with a real recipient once on the Linux server before relying on it. |
| Bug found and fixed by this drill | uploads were listed with `tar -tzf <path>`: a `C:/` path was taken as a remote host and the count silently became 0, and the drill printed a false "ok". Both scripts now read from stdin and fail on listing errors. |

### 7.2 PITR (WAL archive → base backup → point in time)

db service from the prod compose with `PG_ARCHIVE_MODE=on`: `archived_count=6, failed_count=0`. Sequence:
1. Insert batch A (1 000 rows).
2. `pg_basebackup -Ft -z -X fetch` (4.2 MB, 1.8 s).
3. Insert batch B (500 rows); record the target time.
4. Insert batch C (700 rows); `pg_switch_wal()`.
5. Restore the base backup into a new `--network none` container with `restore_command`, `recovery_target_time`, and `recovery_target_action=promote`.

Result:
- Log lines: `starting point-in-time recovery to 2026-09-13 17:25:47.198+00` … `recovery stopping before commit of transaction 746` … `selected new timeline ID: 2`.
- Rows recovered: **A=1000, B=500, no C**.
- Extract + replay + promote took **6.5 s**.

### 7.3 What is still unmeasured
- **Production RPO/RTO:** no production-size data, no real network transfer to a backup host in Uzbekistan, no drill on the target hardware.
- `rsync` shipping to a real backup host, including `--remove-source-files` WAL pruning (staging only).
- A PITR restore from shipped (remote) WAL; an encrypted WAL wrapper does not exist (production PITR is refused).
- `backup.sh` on a Linux server (it ran with Git Bash + Docker Desktop; the gpg path ran with the host gpg on Windows).

## 8. Monitoring

- Alert if the newest remote backup is older than 26 h (check on the backup host, not the server).
- Alert on non-zero exit of `backup.sh` (log to `/var/log/elchi-backup.log`; ship to monitoring).
- Alert if `pg_stat_archiver.failed_count` increases (PITR on).
- Track backup size; a sudden drop means an empty or truncated dump.
