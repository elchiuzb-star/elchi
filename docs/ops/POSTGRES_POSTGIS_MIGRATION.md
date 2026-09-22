# PostgreSQL `postgres:16-alpine` → PostGIS (Debian) migration

Owner: A10a · 2026-09-13 · ADR-0013, ADR-0011, ADR-0016 · spec §18.3, §19 · AC40
Status: **rehearsed locally on synthetic data only.** Nothing here has been run against production.

## 1. Why, and the one rule that matters

Stage 2 needs PostGIS (`ST_DWithin` on geography, GiST) and `btree_gist` (exclusion constraints for trip/vehicle and commission-policy overlap). The official alpine image has no PostGIS; `postgis/postgis` images are Debian/glibc.

**Rule: never open the alpine data directory with the PostGIS image.** musl and glibc sort text differently under the same locale name, and PostgreSQL cannot warn (musl records no collation version). A0b proved the result locally: an index lookup returned 0 rows where 9 existed, and `bt_index_check` reported `item order invariant violated` (BASELINE_TESTS.md §6.4). Data moves **only** by logical dump/restore, which rebuilds every index under the new rules.

Guards in the repo:
- `docker-compose.prod.yml` uses a **new** volume, `pgdata_pg16_postgis`. The legacy `pgdata` volume is not declared at all, so this compose file cannot mount it.
- `scripts/deploy.sh` refuses to start when `elchi_pgdata` exists but `elchi_pgdata_pg16_postgis` does not.
- `scripts/deploy.sh` refuses to migrate when the running DB image has no PostGIS (ADR-0013). **Migration `20260913_0030` must not reach production before the image switch.**

## 2. Source and target

| | Source (today) | Target |
|---|---|---|
| Image | `postgres:16-alpine` (floating tag; the running digest is unknown, see §6 check P1) | `<registry>/elchi-postgis@sha256:<digest>` (`ELCHI_POSTGIS_IMAGE`, Q51), built once from `docker/postgis/Dockerfile`: `postgres:16.15-trixie@sha256:f1c3376c…df6f94` + `postgresql-16-postgis-3{,-scripts}=3.5.3+dfsg-2.pgdg13+1`. The same variable drives `docker-compose.test.yml` and `restore_drill.sh` (Q58); the local tag `elchi-postgis:16.15-3.5.3-trixie` is only the dev fallback until the registry exists |
| Server | PostgreSQL 16.15 (BASELINE_TESTS.md) | PostgreSQL 16.15, PostGIS 3.5.3 |
| libc | musl | glibc 2.41 (Debian 13 "trixie", supported) |
| Locale | `en_US.utf8`, libc provider, `datcollversion = NULL` | `LC_COLLATE=C`, `LC_CTYPE=C.UTF-8`, `UTF8`, data checksums on |
| Volume | `elchi_pgdata` | `elchi_pgdata_pg16_postgis` |
| Roles | one superuser `elchi` used by everything | bootstrap superuser (`POSTGRES_USER`), owner `elchi_owner` (migrate), app `elchi_app` (api/worker), decision 36 |

**Why a local image (decision 34).** The official `postgis/postgis:16-3.5` is Debian 11 "bullseye" (end of life) with PG 16.9. No official tag combines PG 16 + PostGIS 3.5 on a supported Debian. apt.postgresql.org's `trixie-pgdg` main repo only carries PostGIS 3.6.x; the 3.5.x build for trixie lives in `trixie-pgdg-archive`. The Dockerfile pins the base by digest and the PostGIS packages by exact version, and asserts both at build time. The image is built **once**, pushed to the private registry in Uzbekistan and deployed **by digest** (§2.1). The server never builds it, and `deploy.sh` records the pulled image ID next to the digest in the ops log. Transitive libraries are listed in `docker/postgis/packages.lock`. `tests/pg` and restore drills run on the same digest by setting `ELCHI_POSTGIS_IMAGE` (Q58).

**16.15 → 16.15**: same minor version as the current alpine server, so the old minor-version downgrade question no longer applies.

### 2.1 Build once, push to the private registry in Uzbekistan, deploy by digest (Q51)

The db image is **never built on the server**. `scripts/deploy.sh` does not build `db` and refuses a production `ELCHI_POSTGIS_IMAGE` without `@sha256:`. `docker-compose.test.yml` may still build locally for development.

```bash
# On a trusted build machine (not the production server):
export ELCHI_REGISTRY=<registry.your-domain.uz/elchi>      # private registry hosted in Uzbekistan (K3)
docker build --pull -t "$ELCHI_REGISTRY/elchi-postgis:16.15-3.5.3-trixie" docker/postgis
# Bill of materials of what you are about to ship; diff against docker/postgis/packages.lock in review
docker run --rm --entrypoint dpkg-query "$ELCHI_REGISTRY/elchi-postgis:16.15-3.5.3-trixie" -W -f '${Package}=${Version}\n' | sort > image.pkgs
docker push "$ELCHI_REGISTRY/elchi-postgis:16.15-3.5.3-trixie"
docker buildx imagetools inspect "$ELCHI_REGISTRY/elchi-postgis:16.15-3.5.3-trixie" --format '{{.Manifest.Digest}}'
# -> set in .env.app on the server:
#    ELCHI_POSTGIS_IMAGE=<registry.your-domain.uz/elchi>/elchi-postgis@sha256:<digest>
```

- **Server access:** the server needs pull-only credentials for this registry (`docker login`; credentials in root's docker config, never in the env files).
- **Ops log:** `deploy.sh` records the pulled image ID next to the digest (`OPS-LOG: images … db=… db_id=…` in `/var/log/elchi-deploy.log`).
- **Pinning:** the Dockerfile pins the base by digest and PostGIS packages by exact version. The 94 transitive Debian/pgdg libraries (GDAL, GEOS, PROJ …) **cannot be pinned practically**: Debian's trixie and trixie-security repositories drop superseded versions. They are recorded in `docker/postgis/packages.lock`, taken from the image built 2026-09-13, `sha256:35bf2116…`. The pushed digest is the reproducibility guarantee.
- **Local build:** built here (`elchi-postgis:16.15-3.5.3-trixie`, image ID `sha256:35bf2116ee7a52a0442bdf84ba90a442f74376056b6dace42d4669e7d6a95819`), not pushed; no registry exists yet.

## 3. Collation decision

`POSTGRES_INITDB_ARGS="--encoding=UTF8 --lc-collate=C --lc-ctype=C.UTF-8 --data-checksums"`

- **`LC_COLLATE=C` keeps today's ordering.** musl `en_US.utf8` compares by code point in practice. `C` compares UTF-8 bytes, and for UTF-8 byte order equals code-point order. So `ORDER BY name_uz` (cities, districts) and every text index behave exactly as users see them today: uppercase before lowercase, Latin before Cyrillic. The rehearsal checks this by comparing ordered hashes (§7).
- **Immune to OS upgrades.** `C` does not depend on glibc tables, so a future base-image bump (Debian 11 → 12 → 13) cannot corrupt indexes again. `en_US.UTF-8` on glibc would re-open the K4 class of risk at every glibc change.
- **`LC_CTYPE=C.UTF-8`** keeps `lower()`/`upper()` and `ILIKE` correct for Cyrillic and Uzbek letters (e.g. `ix_districts_city_lower_name_uz`). The rehearsal compares `lower()`/`upper()` output between source and target.
- **If linguistic sorting is ever wanted** (Uzbek alphabetical order in a UI list), add an explicit ICU collation on that column or query (`COLLATE "und-x-icu"`) in a migration. Do not change the database default.

## 4. Preconditions (all must be true)

- [ ] Target host passed UZ_HOSTING_RUNBOOK.md §2 (residency verified) and §3 (hardening).
- [ ] PostGIS image pushed to the private UZ registry and `ELCHI_POSTGIS_IMAGE=<registry>/elchi-postgis@sha256:…` set in `.env.app` (§2.1). Images pulled by digest: `docker compose --env-file .env.app -f docker-compose.prod.yml pull db redis caddy`.
- [ ] Free disk on target ≥ 3 × `pg_database_size` + uploads size.
- [ ] A fresh encrypted backup exists and `scripts/restore_drill.sh` **passed on the target host** with that backup. Do this on the UZ host, not on a laptop: a real production dump on a personal machine is itself a data transfer.
- [ ] Production checks P1–P9 (§6) were run with the user's permission and the output is attached to the change record.
- [ ] Maintenance window announced. The frozen v1 apps will show network errors during the window.
- [ ] DNS TTL lowered to 300 s at least one hour before, if the host changes.
- [ ] The release containing `0030` is built on the target but not started.

## 5. Procedure

`C="docker compose --env-file .env.app -f docker-compose.prod.yml"` (new host; the db-admin file is referenced per service by the compose file). On the **old** host use its existing `.env.production` command.

### 5.1 On the old server: freeze and export
```bash
# 1. Stop writers. Caddy answers 502 while api is down; v1 clients retry.
$C stop api            # (old compose has no worker)

# 2. Snapshot-consistent dump + manifest (row counts and per-table checksums
#    from the same snapshot) + uploads, encrypted. Staged locally, then transferred.
BACKUP_DIR=/root/elchi-move ./scripts/backup.sh --local-only --tag move
#    NOTE: the old checkout must contain the new scripts/backup.sh and
#    scripts/restore_drill.sh (copy both files; they only read the database).

# 3. Record the source facts next to the dump
$C exec -T db psql -U elchi -d elchi -Atc "SELECT version(); SHOW timezone; SELECT datcollate, datctype FROM pg_database WHERE datname='elchi';"
```

### 5.2 Transfer (only when the host changes)
Move the **encrypted** files server-to-server (`rsync -a -e ssh /root/elchi-move/ root@NEW:/root/elchi-move/`). Verify `sha256sum -c SHA256SUMS` on arrival. Transferring out of Germany into Uzbekistan is a legal checkpoint (UZ_HOSTING_RUNBOOK.md §2, L4). Decrypt only on the target host.

### 5.3 On the target: restore
```bash
cd /opt/elchi
D=/root/elchi-move/<stamp>-move
# 1. Verify the dump in a throwaway container first (no network, removed after).
./scripts/restore_drill.sh --dump $D/db.dump.gpg --manifest $D/manifest.tsv.gpg \
    --uploads $D/uploads.tar.gz.gpg --expect-head 20260803_0029

# 2. Start ONLY the new database (empty volume; initdb with the §3 locale).
$C up -d --wait db

# 3. Restore into it. Owner stays the POSTGRES_USER (same name on both sides).
gpg --decrypt $D/db.dump.gpg | $C exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error --single-transaction'

# 4. Compare with the manifest taken in the source snapshot.
scripts/restore_drill.sh --print-manifest-sql | $C exec -T db sh -c \
  'psql -X -q -At -F "$(printf "\t")" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | sort > /root/restored.tsv
gpg --decrypt $D/manifest.tsv.gpg | grep -v '^#' | sort > /root/expected.tsv
# keep only tables that exist in the source manifest (the target may have more later, e.g. after 0030)
awk -F'\t' 'NR==FNR { t[$1] = 1; next } ($1 in t)' /root/expected.tsv /root/restored.tsv > /root/restored.filtered.tsv
diff /root/expected.tsv /root/restored.filtered.tsv && echo "MANIFEST MATCH"

# 5. musl -> glibc: rebuild expression indexes that depend on LC_CTYPE (lower()/upper()),
#    then structural checks. pg_restore already built them fresh; the explicit REINDEX
#    makes the step independent of how the data arrived (decision 34).
$C exec -T db sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT i.indexrelid::regclass FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '"'"'public'"'"' AND pg_get_indexdef(i.indexrelid) ~* '"'"'(lower|upper)\('"'"'"' \
  | while read -r idx; do $C exec -T db sh -c "psql -X -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c 'REINDEX INDEX $idx'"; done
$C exec -T db sh -c 'pg_amcheck -U "$POSTGRES_USER" -d "$POSTGRES_DB" --install-missing --heapallindexed' && echo AMCHECK CLEAN
$C exec -T db sh -c 'vacuumdb -U "$POSTGRES_USER" -d "$POSTGRES_DB" --analyze-only'
$C exec -T db psql -U elchi -d elchi -Atc "SHOW timezone; SELECT datcollate, datctype FROM pg_database WHERE datname='elchi'; SELECT version_num FROM alembic_version;"
#    expect: UTC | C | C.UTF-8 | 20260803_0029

# 6. Uploads into the uploads volume (created by compose on first use).
gpg --decrypt $D/uploads.tar.gz.gpg | docker run --rm -i -v elchi_uploads:/app/storage alpine tar -xz -C /app/storage
```

### 5.4 Roles, marker, expand and start
```bash
$C run --rm db-roles        # superuser via local socket: owner/app roles, postgis+btree_gist, ownership -> elchi_owner, grants
$C run --rm db-roles        # second run: "0 ownership change(s)"; lists session-guarded tables made read-only
# First stage-2 deploy only, after 0031 exists (deploy.sh tells you when): set the DB marker as the owner role
$C run --rm migrate python -m app.modules.platform.environment set production --by "cutover:<date>:<operator>"
./scripts/deploy.sh --no-pull --skip-backup   # roles job, marker check, legacy-rate check, migrate (0030+) as owner, start, readiness gate
$C run --rm migrate                           # second run: must print no "Running upgrade"
$C run --rm db-roles python scripts/db_roles.py --expected-guarded scripts/db_roles.expected-guarded-tables.txt
```
**Always `run --rm db-roles` after any manual `migrate`** (wave 1.7 NEW-5). New tables otherwise keep the owner's default DML grant for the app role until the next db-roles run. That includes a newly guarded table, which would stay writable. `deploy.sh` does this automatically and fails when the detected guarded tables differ from `scripts/db_roles.expected-guarded-tables.txt`.

Each listed table has a class (wave 2.1):
- **`read-only`** (`ledger_account_balances`): the app role loses INSERT/UPDATE/DELETE, because only a SECURITY DEFINER trigger may write the table.
- **`app-marker`** (`bookings` and `booking_amendments` from 0056 Q60, `feature_flag_values` from 0057 Q72): the guard reads a transaction marker that the application itself sets, so the app role keeps DML. These guards stop accidental psql/migration writes, not a deliberate actor with app-role credentials.

A newly detected table that is not listed stays read-only (fail-safe). Classify it in the same change as its migration.

**Q68 data impact (BR L4):** before `migrate`, `deploy.sh` prints and ops-logs how many rows migration 0054 would rewrite, as `parcel_rows`, `parcel_type_to_other`, `accepted_elements_to_other`, `amenity_rows` and `dropped_amenity_elements`. It is a read-only query from `scripts/q68_cleanup_impact.py --print-sql`. Review the numbers before continuing; all are 0 once 0054 is applied.
A restored v1 dump is owned by the bootstrap superuser. `db_roles.py` moves every table, sequence, view, function and type in `public` to `elchi_owner` (rehearsal: 21 changes). Migrations then run as a non-superuser. `deploy.sh` runs db-roles again after migrations, so tables created by new migrations get their privilege class.

The api/worker connect as `elchi_app` and cannot:
- disable triggers, `TRUNCATE`, `SET session_replication_role` or `COPY … PROGRAM`;
- write `alembic_version`, `platform_environment(_history)` or `ledger_account_balances` (BR wave 1.6 N1: the guard trusts a session setting, so it is read-only for the app role, and A3's SECURITY DEFINER trigger keeps maintaining it);
- `UPDATE`/`DELETE` the ledger or audit log;
- `DELETE` wallets, holds, top-ups, adjustments, policies or reconciliation runs.

**Extensions stay superuser-owned (BR wave 1.6 N10).** `postgis` is not a trusted extension, so the owner role cannot create, own or alter it.
- `db-roles` (superuser, local socket) creates `postgis` and `btree_gist`; migrations `0030`/`0038` are `IF NOT EXISTS` no-ops as the owner.
- **PostGIS upgrades** after a new image (e.g. 3.5.3 → 3.5.x) run only in the superuser step: `$C run --rm db-roles python scripts/db_roles.py --update-extensions`, then `SELECT postgis_full_version();`.
- **Never** put `ALTER EXTENSION … UPDATE` or `CREATE EXTENSION postgis` (without `IF NOT EXISTS`) into an owner-run migration; it fails with "must be owner of extension". Note for A0a to add to ADR-0016.

**pg_hba (BR wave 1.6 N2):** the bootstrap superuser is rejected over TCP (`host all "<POSTGRES_USER>" all reject`) and can log in only through the local socket. Inside the db container that means `docker compose exec db psql`; `db-roles` uses the socket volume. The owner and app roles use TCP with `scram-sha-256`.
Smoke: `/api/v1/health`, `/api/v1/cities`, one admin login, opening one driver document (proves uploads came across), and `/health/ready` once the router is wired.

## 6. Production checks for the user to run later (read-only; needs permission)

Run on the **current** production host before planning the window. Paste the output into the change record.

```bash
C="docker compose --env-file .env.production -f docker-compose.prod.yml"
# P1 exact image and digest the db container runs
docker inspect --format '{{.Config.Image}} {{.Image}}' "$($C ps -q db)"
# P2 server version, timezone (ADR-0004 expects UTC), encoding/locale, collation versions
$C exec -T db psql -U elchi -d elchi -c "SELECT version();" -c "SHOW timezone;" -c "SHOW log_timezone;" \
  -c "SELECT datname, pg_encoding_to_char(encoding), datcollate, datctype, datlocprovider, datcollversion FROM pg_database;"
# P3 sizes (drives downtime and disk)
$C exec -T db psql -U elchi -d elchi -c "SELECT pg_size_pretty(pg_database_size('elchi'));" \
  -c "SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 15;"
docker run --rm -v elchi_uploads:/u alpine du -sh /u
# P4 migration state
$C exec -T db psql -U elchi -d elchi -Atc "SELECT version_num FROM alembic_version;"   # expect 20260803_0029
# P5 structural health of the source BEFORE the move (so problems are not blamed on it)
$C exec -T db sh -c 'pg_amcheck -U "$POSTGRES_USER" -d "$POSTGRES_DB" --install-missing --heapallindexed'
# P6 in-flight business state (spec §18.1 M0)
$C exec -T db psql -U elchi -d elchi -c "SELECT status, count(*) FROM orders GROUP BY status ORDER BY 1;"
# P7 extension availability on the running image (expect 0 rows for postgis on alpine)
$C exec -T db psql -U elchi -d elchi -c "SELECT name, default_version FROM pg_available_extensions WHERE name IN ('postgis','btree_gist','amcheck');"
# P8 long transactions / connections at the planned time
$C exec -T db psql -U elchi -d elchi -c "SELECT state, count(*), max(now()-xact_start) FROM pg_stat_activity GROUP BY state;"
# P9 volumes and free disk
docker volume ls | grep elchi_; df -h /var/lib/docker
# P10 who connects today (expect the single superuser; decision 36 splits it)
$C exec -T db psql -U elchi -d elchi -c "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolcanlogin;" \
  -c "SELECT usename, count(*) FROM pg_stat_activity WHERE usename IS NOT NULL GROUP BY 1;"
# P11 expression indexes that depend on LC_CTYPE (to be REINDEXed after restore)
$C exec -T db psql -U elchi -d elchi -At -c "SELECT indexrelid::regclass, pg_get_indexdef(indexrelid) FROM pg_index WHERE pg_get_indexdef(indexrelid) ~* '(lower|upper)\\(';"
```

## 7. Local rehearsal (actually run)

Script: `docs/ops/rehearsal/rehearse_postgis_switch.sh`. It uses only local, disposable, network-isolated containers and removes everything at the end.

**Wave 1.5 run (current image):** 2026-09-13 22:40–22:42 UTC on the A10a Windows laptop (Docker Desktop 29.6.2). The app image was built from the working tree (`alembic heads` = `20260914_0044`) and the PostGIS image from `docker/postgis/Dockerfile`. Command:

```bash
docker build -t elchi-postgis:16.15-3.5.3-trixie docker/postgis
docker build -t elchi-api:a10a-smoke .
bash docs/ops/rehearsal/rehearse_postgis_switch.sh        # exit 0, "REHEARSAL PASSED", 0 FAIL lines
```

| Step | Result |
|---|---|
| Source | `postgres:16-alpine@sha256:cf78e766…`: 16.15, `en_US.utf8`, provider `c`, `datcollversion NULL`, UTC. Schema at `20260803_0029` (27 migrations); `seed_cities.py`, demo seed, 20 000 users with mixed-case Latin/Cyrillic/Uzbek/Turkish names, 3 000 audit rows. **20 tables, 23 017 rows.** |
| Dump | `pg_dump -Fc -Z 6`: 258 949 bytes, 0.6 s |
| Restore drill into `elchi-postgis:16.15-3.5.3-trixie` | 16.15, `C` / `C.UTF-8`, UTC; `alembic_version = 20260803_0029`; **20 tables, 23 017 rows, all per-table checksums match**; `pg_amcheck --heapallindexed` clean; drill total 11.8 s |
| musl → glibc 2.41 | 1 LC_CTYPE-dependent expression index found (`ix_districts_city_lower_name_uz`), `REINDEX`ed; `pg_amcheck` clean afterwards |
| Ordering and case | `ORDER BY users.full_name` over 20 000 names **identical**; `ORDER BY cities.name_uz` identical; `lower()`/`upper()` on `ШЕРЗОД ÇAĞRI ЎКТАМ O‘TKIR ĞANI İ` identical; `lower(full_name)` over all 20 000 names identical; unique phone found through an index scan; `SHOW timezone` = UTC |
| Roles (decision 36) | `scripts/db_roles.py` as bootstrap superuser: 21 ownership changes (every restored object → `elchi_owner`). Re-run after migrations: 0 changes. Every public table owned by `elchi_owner`. |
| Expand as owner | `alembic upgrade head` as **`elchi_owner` (non-superuser)**: 15 migrations 0030 → 0044 in 4.9 s; second run no-op; `alembic current` = head; `postgis 3.5.3` + `btree_gist` only (no tiger/topology); `pg_amcheck` clean; users count unchanged |
| App role | `elchi_app`: not superuser, not bypassrls. Refused: `ALTER TABLE … DISABLE TRIGGER ALL`, `SET session_replication_role`, `COPY … TO PROGRAM`, `TRUNCATE`, `CREATE TABLE`, `UPDATE alembic_version` |
| v1 smoke as app role | `GET /api/v1/health` OK; `GET /api/v1/cities` returns every active city; `/health/ready` `database: ok, migrations: ok`; logs are JSON lines |
| Rollback path | alpine data re-checked after restart: manifest (counts + checksums) **identical**; `alembic_version` still `0029` |
| Window (laptop, 259 KB dump) | dump 0.6 s · restore+verify 12.7 s · migrate 4.9 s · api healthy 20.9 s · **total 46.6 s** |

The wave 1 run (2026-09-13 17:34 UTC, previous `postgis/postgis:16-3.5` image, PG 16.9) also passed; it is superseded by this run.

Also rehearsed (wave 1 and 1.5): `scripts/restore_drill.sh` negative controls:
- a tampered manifest count and a wrong expected head: `FAIL` ×2, exit 1;
- a truncated uploads archive: `FAIL`;
- a referenced upload missing from the archive: `FAIL`;
- an unbalanced ledger transaction: `FAIL`.

BACKUP_RESTORE.md §7 has the details.

Not rehearsed: real production data, the network transfer, uploads volume size, the destructive path (A0b already demonstrated it in BASELINE_TESTS.md §6.4).

## 8. Verification checklist (production)

- [ ] `restore_drill.sh` PASSED on the target with the move backup.
- [ ] Manifest diff empty (all tables: row counts and checksums).
- [ ] `pg_amcheck --heapallindexed` clean, before and after `0030`.
- [ ] `SHOW timezone` = `UTC`; `datcollate` = `C`, `datctype` = `C.UTF-8`.
- [ ] `alembic current` = script head; a second `run --rm migrate` is a no-op.
- [ ] Active orders by status (P6) identical before and after.
- [ ] v1 smoke and one document download passed.
- [ ] Old volume `elchi_pgdata` still present and untouched (do not `docker volume rm` for at least 14 days).

## 9. Rollback

- **Before the new server accepts writes:** stop the new stack and start the old one. On the old host, redeploy the previous release, whose compose still mounts `elchi_pgdata`: `git checkout <previous tag>` there, then `docker compose ... up -d`. If DNS changed, point it back. The alpine volume was only read, so nothing is lost.
- **After new writes were accepted:** blindly returning to the old volume loses those bookings (spec §18.3). Stay on the new server and fix forward: feature flag off, hotfix, forward migration. If the new database itself is unusable, restore the latest backup of the *new* database with this document's procedure. **Never run `alembic downgrade`.**

## 10. Downtime estimate

Window = stop api + snapshot dump + (transfer) + drill + restore + manifest/amcheck + analyze + migrate + start + smoke.

The only measured numbers are from the local rehearsal on synthetic data (§7); they are not a production estimate. For production, time a dump of the real database on the target hardware during the drill (§4): the restore is typically comparable to or longer than the dump, and `pg_amcheck --heapallindexed` scales with index size. The pilot database is small (see P3), so the expectation is minutes rather than hours, but **that is unverified until P3 and a target-host drill exist.**
