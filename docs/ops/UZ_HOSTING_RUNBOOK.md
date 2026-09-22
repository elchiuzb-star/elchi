# Uzbekistan hosting runbook (stage-2 launch gate)

Owner: A10a · 2026-09-13 · ADR-0011 (K3), ADR-0013, ADR-0012 · spec §17.7, §19 · AC34, AC40
Supersedes `docs/SERVER_MIGRATION.md` for any move involving personal data.

> **Status.** No provider is chosen, nothing is purchased, and nothing here has been executed against a real server. Production still runs on a shared Hetzner server in Germany (`docs/SERVER_MIGRATION.md`). This document gives no legal conclusions; §2 lists checkpoints for qualified counsel.

## 0. Decisions the user must make

| # | Decision | Needed before |
|---|---|---|
| U1 | UZ provider for the primary server (§1 checklist) | §3 |
| U2 | Second failure domain in UZ for backups (another provider/DC) | §3 |
| U3 | Legal review owner and scope (§2) | §4 cutover |
| U4 | Maintenance window date (v1 users see downtime) | §5 |
| U5 | Whether stage-2 launch and the v1 move happen together (recommended: move v1 first, stage-2 later on the same host) | §5 |
| U6 | Private container registry in Uzbekistan for the PostGIS image (Q51): provider, access, pull-only credentials | §3 |

## 0.1 Stage-2 production launch gate (checklist)

| # | Gate | Evidence / check | Owner |
|---|---|---|---|
| G1 | Hosting, registry and backup storage in Uzbekistan (K3) | L1/L3 answered; `ELCHI_DATA_RESIDENCY=UZ` | user + counsel |
| G2 | PostGIS image built once, pushed to the UZ registry, deployed by digest (Q51) | `ELCHI_POSTGIS_IMAGE=…@sha256:…`; `deploy.sh` refuses otherwise; image ID in the ops log | ops |
| G3 | **Q48: no production v2 money flow until the DB role split (Q36) and A3's balance guard fix (0047, `pg_trigger_depth()`) are deployed** | `deploy.sh` Q48 gate: A3's `q48_gate_status` via `python -m app.ops.gates status` in the api image, or the SQL fallback while it does not exist. Without `--v1-only` a production deploy requires the gate to pass. With `--v1-only "<reason>"` (logged) the deploy **refuses if any `feature_flag_values` row is enabled** for `passenger_enabled`, `parcel_enabled`, `driver_listing_enabled`, `corridor_matching_enabled`, `tracking_enabled` or `card_payments_enabled` (Q56) | A3 + ops |
| G4 | Env split: api/worker never receive DB admin credentials | `deploy.sh` file + rendered-config checks pass | ops |
| G5 | Backups encrypted and off-box in UZ; restore drill on the UZ host | BACKUP_RESTORE.md §5 record | ops |
| G6 | Revision lineage in the DB, so an older image can tell "ahead" from "unknown" (Q50) | Design by A0a; **not implemented**. Until then a rollback to an older image reads 503 (§7) | A0a |
| G7 | Monitoring CIDRs set; readiness restricted | `ELCHI_MONITORING_CIDRS` validated by `deploy.sh`; Caddy healthy | ops |
| G8 | Passenger legal gate (K7), Geoapify off (Q24/Q46), legacy-rate check (Q29), seed policy confirmed (Q28) | flags / `wallet.checks legacy-rate` / super_admin confirmation | user + A2/A3 |
| G9 | **Support contact before `passenger_enabled` (Q87):** the pilot has no support phone, so `ELCHI_SUPPORT_PHONE` is empty and S13 answers `available=false`. Enabling the passenger service requires a number that is actually answered plus honest opening hours (a 24/7 or response-time promise is refused, §5.2/§16) | `ELCHI_SUPPORT_PHONE` / `ELCHI_SUPPORT_HOURS_TEXT` set in `.env.app`; `GET /api/v2/support/contacts` returns `available=true` | user + ops |

## 1. Provider requirements (host-agnostic)

Any provider that satisfies these works. Nothing in the repo uses a provider-specific API.

- [ ] Datacenter physically in Uzbekistan, stated in the contract or SLA (address/city), including where **provider-side snapshots/backups** are kept.
- [ ] Linux VM (Ubuntu 24.04 LTS or Debian 12/13), **2–4 vCPU, 4–8 GB RAM, SSD**, disk ≥ 80 GB (spec §19.1 sizing hypothesis, unverified).
- [ ] Public IPv4, inbound 80/443 allowed, outbound HTTPS to Eskiz, Google, Yandex (and later FCM/routing provider).
- [ ] Root/SSH access; KVM console for recovery; ability to attach extra disk.
- [ ] Contract: data location, sub-processors, incident notification, support hours, deletion/erasure on termination, no provider access to disk contents without a ticket.
- [ ] Backup target (U2): separate account, reachable over SSH (rsync) or an S3-compatible endpoint **inside UZ**.
- [ ] Price and support contact recorded in the ops log.

## 2. Legality checkpoints (for counsel; not conclusions)

Record for each: question, answer, who answered, date, evidence file.

| # | Checkpoint |
|---|---|
| L1 | Which Elchi data falls under the localisation requirement (driver documents, phone numbers, GPS, names, cargo photos, audit logs, backups, logs)? `SERVER_MIGRATION.md` cites ZRU-547. |
| L2 | Is registration/notification as a personal-data operator or database owner required, and was it done? |
| L3 | Does the chosen provider's location and contract satisfy L1, **including provider snapshots and our backup target**? |
| L4 | Transfer of the existing copy **from Germany back to Uzbekistan**: permitted steps, required documentation, and required **deletion of the German copies** (server disk, Hetzner snapshots/backups, local backup files, operator laptops). |
| L5 | External processors in `EXTERNAL_DATA_FLOWS.md` (Eskiz, Google, Yandex, future FCM/routing): is sending each listed field abroad or to a third party permitted, and with what consent text? |
| L6 | Retention periods: raw GPS 7 d, thinned track 30 d, receipts 8 d (proposal ADR-0011 §6), backups (BACKUP_RESTORE.md §3), audit and ledger. |
| L7 | Privacy policy statement on data location matches reality on the cutover day, not after. |
| L8 | Passenger service legal gate (K7), independent of hosting: `passenger_enabled=false` until cleared. |

Only after L1, L3 and L4 are answered, and the server and backup location were checked, set `ELCHI_DATA_RESIDENCY=UZ` in `.env.app`. `scripts/deploy.sh` refuses `ELCHI_ENVIRONMENT=production` without it.

## 3. Provision and harden the new host

```bash
# as root on the new host
git clone --branch <release-tag> https://github.com/elchiuzb-star/elchi.git /opt/elchi
/opt/elchi/scripts/server_bootstrap.sh            # docker, chrony, gnupg, rsync, ufw rules, dirs
```

By hand, keeping a second SSH session open:
1. Create a sudo user and add SSH keys; in `/etc/ssh/sshd_config` set `PasswordAuthentication no` and `PermitRootLogin prohibit-password`; `systemctl reload ssh`.
2. `ufw enable` (rules for 22/80/443 were staged). Docker-published ports bypass ufw, and only Caddy publishes any.
3. Enable unattended security upgrades (`apt install unattended-upgrades`).
4. Host clock in UTC with NTP synced: `timedatectl` shows `NTPSynchronized=yes`.
5. **Two env files (BR wave 1.6 N2)**: `cp app.env.example .env.app && cp db-admin.env.example .env.db-admin && chmod 600 .env.app .env.db-admin`. Fill both in and generate new secrets (SECRET_ROTATION.md §5). Both names are gitignored.
   - **`.env.app`** (api, worker, compose interpolation):
     - `ELCHI_POSTGIS_IMAGE` (registry digest, §0.1 G2), `ELCHI_DOMAIN`, `ELCHI_MONITORING_CIDRS` (space-separated CIDRs of your monitor; `0.0.0.0/0`/`::/0` refused);
     - `ELCHI_DATABASE_URL` as `elchi_app`, `REDIS_PASSWORD`/`ELCHI_REDIS_URL`, app keys;
     - `PG_ARCHIVE_MODE=off` (production PITR refused, no override).
   - **`.env.db-admin`** (db service, db-roles and migrate jobs only):
     - `POSTGRES_USER`/`PASSWORD`/`DB` (bootstrap superuser, socket-only);
     - `ELCHI_DB_ADMIN_URL=postgresql://<superuser>@/<db>?host=/var/run/postgresql`;
     - `ELCHI_DB_OWNER_PASSWORD` + `ELCHI_MIGRATION_DATABASE_URL`, `ELCHI_DB_APP_PASSWORD`.
   - All passwords are hex, ≥ 24 characters. `deploy.sh` fails if an admin key appears in `.env.app` or in the rendered api/worker environment, or if the app password differs between the files.
   - `docker login <registry>` with pull-only credentials for the PostGIS image.
6. Backup config and key import: BACKUP_RESTORE.md §4.

## 4. Rehearse on the new host (synthetic data, then a real drill)

1. **Synthetic smoke:**
   - `ELCHI_ENVIRONMENT=staging` with dummy secrets;
   - `./scripts/deploy.sh --no-pull --skip-backup` (with `ELCHI_ALLOW_EMPTY_DB=1`);
   - check `/api/v1/health` and `/health/ready`;
   - `docker compose ... down -v` afterwards.
2. **Restore drill with the latest real encrypted backup:** `scripts/restore_drill.sh` (BACKUP_RESTORE.md §5). This measures the restore time on the real hardware and becomes the downtime estimate.
3. **Outbound reachability** from the api container:
   - `docker compose ... exec api python -c "import httpx; print(httpx.get('https://notify.eskiz.uz').status_code)"`;
   - the same check for `maps.googleapis.com` and `geocode-maps.yandex.ru`.

## 5. Cutover

| When | Step |
|---|---|
| T−24 h | DNS TTL of the API record → 300 s. Announce the window. Freeze deploys. |
| T−1 h | Final check of §2 and §4. Latest backup drill PASSED. |
| T0 | Old host: `stop api` → snapshot dump + manifest + uploads (`backup.sh --local-only --tag move`) |
| T0+ | Encrypted server-to-server transfer (L4) → restore, verify, migrate: POSTGRES_POSTGIS_MIGRATION.md §5 |
| T0+ | New host: `./scripts/deploy.sh --no-pull --skip-backup` (TLS will fail until DNS moves; that's expected) |
| T0+ | Change the DNS A/AAAA record to the new IP. Caddy obtains the certificate via HTTP-01 once DNS resolves. |
| T0+ | Verify from outside: `dig +short $DOMAIN`, `curl -fsS https://$DOMAIN/api/v1/health`, `/api/v1/cities`, `/health/ready`, staff login, open one driver document. |
| T0+ | First encrypted backup on the new host ships to the UZ backup target; drill it the same day. |
| T+24 h | Raise the DNS TTL. Keep the old host **stopped, not destroyed**, for the rollback window agreed with counsel (L4). |
| T+N | Decommission Germany: wipe volumes (`docker volume rm`, then provider disk wipe), delete provider snapshots and backups and local copies; file the deletion evidence (L4). **Rotate all secrets** (SECRET_ROTATION.md §5). Update the privacy policy (L7). |

Frozen clients (`android-app`, `frontend`) keep using the same domain and `/api/v1`. No client change is needed if the domain is unchanged.

## 6. Operating minimum after cutover (spec §19.2)

- **External uptime checks:**
  - `GET /api/v1/health` and `GET /health/live` are public.
  - `GET /health/ready` answers only to `ELCHI_MONITORING_CIDRS` at Caddy (decision 33); everyone else gets 404. The monitor's source IPs must be listed.
  - Alert on HTTP 503, **and** on body `status: degraded`, `production_invariants: fail` or `migrations: ahead`.
- **Deploy gates** (`scripts/deploy.sh`):
  - normalised `ELCHI_ENVIRONMENT` must equal the DB marker;
  - a production deploy fails unless readiness shows `production_invariants: ok`; an override is `--accept-degraded "<reason>"`, logged to `/var/log/elchi-deploy.log` and syslog;
  - `PG_ARCHIVE_MODE=on` in production is refused;
  - the legacy-rate check runs once A3 ships `app.modules.wallet.checks`.
- **Logs:** api and worker write JSON lines (`ts`, `level`, `logger`, `message`, `request_id`, `actor_id`, `error_code`). Phones, passport numbers, JWT/bearer tokens and `sig`/`exp`/`token`/`otp` query params are redacted before output (`app/ops/logging.py`). Ship them with the Docker json-file driver to your log system.
- **Disk:** alert at 80 % on `/var/lib/docker`.
- **Backups:** age of the newest remote backup (BACKUP_RESTORE.md §8).
- **Certificates:** expiry (Caddy renews; alert if under 14 days).
- **Logs:** `docker compose logs` are rotated (10 MB × 5 per container). Caddy access logs never contain signed-URL `exp`/`sig`.

### 6.1 Resource limits and PostgreSQL memory

Compose sets limits (`deploy.resources.limits`). The defaults target a 4 GB / 2–4 vCPU host; adjust them via env:

| Service | Memory | CPUs | Env |
|---|---|---|---|
| db | 2g | 2 | `PG_MEMORY_LIMIT`, `PG_CPUS` |
| api (2 uvicorn workers) | 1g | 1.5 | `API_MEMORY_LIMIT`, `API_CPUS` |
| worker | 512m | 0.5 | `WORKER_MEMORY_LIMIT`, `WORKER_CPUS` |
| redis (`maxmemory 256mb`, `volatile-lru`) | 384m | 0.5 | fixed |
| caddy | 256m | 0.5 | fixed |

PostgreSQL rules of thumb, relative to the **db container limit**:
- `PG_SHARED_BUFFERS` ≈ 25 % (512MB for 2g);
- `PG_EFFECTIVE_CACHE_SIZE` ≈ 75 % (1536MB). This is a planner hint, not an allocation.
- `PG_WORK_MEM` 8MB. It is per sort/hash per connection, so `max_connections × work_mem` must fit.
- `PG_MAX_CONNECTIONS` 100. It must exceed api workers × pool size + worker + jobs + admin. SQLAlchemy's default pool is 5 + 10 overflow per process, so 2 api workers + 1 worker ≈ 45.
- Raising `shared_buffers` needs a db restart; `shm_size` is 256m.
- For an 8 GB host use `PG_MEMORY_LIMIT=4g`, `PG_SHARED_BUFFERS=1GB`, `PG_EFFECTIVE_CACHE_SIZE=3GB`.
- Verify with `SHOW shared_buffers;` and watch `docker stats` for the first week; an OOM kill of db shows as exit code 137.

Redis `volatile-lru` evicts only keys with a TTL. A key without TTL makes writes fail loudly under memory pressure instead of silently disappearing (BR #16). Rate-limit and cache keys must carry a TTL.

## 7. Health probe semantics (for monitors)

| Endpoint | 200 | 503 |
|---|---|---|
| `/api/v1/health` | process up (unchanged v1 contract; container HEALTHCHECK) | — |
| `/health/live` | process up (public) | never |
| `/health/ready` `status=ready` | DB reachable, schema at head, Redis ok, invariants ok / not applicable | — |
| `/health/ready` `status=degraded` | `database: busy` (pool exhausted), `migrations: ahead` (DB newer than this build but a known descendant; decision 32), Redis down or not configured, or `production_invariants` = `fail`/`error`/`not_available` | — |
| `/health/ready` `status=unavailable` | — | DB unreachable, or `migrations` = `mismatch` (DB behind or divergent) / `unknown` (revision not in this build's script graph) |

- **Access:** readiness is IP-restricted at Caddy (404 outside `ELCHI_MONITORING_CIDRS`).
- **Caching:** results are cached 3 s behind a lock, so concurrent probes share one run (BR #5).
- **Notices (Q57):** the body carries `notices: [...]` with informational names. Notices never change `status` or the HTTP code. Monitors should raise a ticket, not a page. Examples:
  - `unconfirmed_seed_policy_active` (Q28): production quotes/holds stay blocked until a super_admin confirms the seed rate.
  - Geo notices from `geo.service.readiness_notices` (wave 2.1), e.g. `routing_provider_disabled` (Q46) and `q47_violations_present` (Q47). A missing or crashing geo hook is logged (`readiness_notice_hook_error`) and ignored.
- **Worker jobs (wave 2.1):** `python -m app.worker --list-jobs` prints each job as `wired` or `pending`. Each job runs its owner's service function in its own DB transaction, under a per-job advisory lock (`job.<name>`), so extra worker replicas skip a job instead of running it twice. A failing job is logged (`worker_task_failed`) and does not stop other jobs.
  - Expiry jobs run every `ELCHI_WORKER_EXPIRY_INTERVAL_SECONDS` (default 60): listings, proposals, amendments.
  - Signal jobs run every `ELCHI_WORKER_SIGNAL_INTERVAL_SECONDS` (default 300): `booking.confirmation_overdue`, including parcels `delivered` for 24 h going to the operator queue (Q65), and `wallet.hold.escalation_due`.
  - Geo routing-cache cleanup runs hourly.
  - **Wave 3 jobs (wired in 3.1):** tracking staleness and tracking-window signals every
    `ELCHI_WORKER_TRACKING_SIGNAL_INTERVAL_SECONDS` (default 60, because staleness is a 120 s rule); dispute
    escalation and rating publication on the signal interval; reputation snapshots every
    `ELCHI_WORKER_REPUTATION_INTERVAL_SECONDS` (default 900); saved-search expiry on the expiry interval; the
    outbox dispatcher every `ELCHI_WORKER_OUTBOX_INTERVAL_SECONDS` (default 5) and last in the round, so events
    written by the other jobs leave in the same round.
  - **Own-lock module tasks:** tracking retention (`ELCHI_WORKER_TRACKING_RETENTION_INTERVAL_SECONDS`, default
    3600) creates and drops daily partitions, builds simplified tracks, copies the raw points of disputed trips
    (M1) and purges expired rows; push delivery (`ELCHI_WORKER_PUSH_INTERVAL_SECONDS`, default 10) does nothing
    while no push provider is configured (U3).
  - **M1 evidence:** a partition holding not-yet-copied points of a trip with an open dispute is **skipped** by
    the drop, so disk grows until the copy succeeds. If `tracking_points` keeps partitions older than 7 days,
    check the retention job log (`tracking_retention`) instead of dropping them by hand.
  - **Wave 4 jobs (A13):** `operations.refresh_kpi_daily` (`ELCHI_WORKER_KPI_INTERVAL_SECONDS`, default 3600)
    recomputes the last three finished days of `kpi_daily` per corridor, so a late completion or cancellation moves
    the numbers instead of freezing them; `operations.expire_share_links` revokes links past `expires_at`.
  - A job whose function is not shipped yet is logged at start as `worker_job_pending`.
- **Q48 gate:** once A3's `q48_gate_status` exists, its result is part of `production_invariants`, so a failing gate reads `fail`/`degraded`. Details: `docker compose … exec api python -m app.ops.gates status`.
- **Invariants (BR N1):** a violation deliberately stays HTTP 200. A data problem must page an operator, not take v1 clients offline. The details are only in the API log (`production_invariants_failed`, logger `elchi.health`).
- **During a deploy:** between the migrate job and container replacement, the old api container reports `migrations: unknown` (503), because an image cannot know revisions written after it was built. Monitors should tolerate 503 for about 1 minute around a deploy.
- **Rollback to an older image (Q50, accepted):** redeploying an image older than the database schema reports `migrations: unknown` with **HTTP 503 for as long as that image runs**, although the v1 and v2 APIs keep working (expand-only migrations). Monitors must treat this as "rollback in progress", not as an outage: page on `database: unavailable` or a failing `/api/v1/health`, and only warn on `migrations: unknown` while a rollback is recorded in the ops log. A DB-side revision lineage that lets old images report `ahead` instead is a launch-gate item designed by A0a (§0.1 G6); it is not implemented.

## 8. Rollback (spec §18.3; never `alembic downgrade`)

1. **Feature problem:** turn the feature flag off (F3, audited). Existing bookings, GPS and money finalisation keep working.
   - **F3 procedure (Q72):** change v2 service flags only through the admin API: `PUT /api/v2/admin/feature-flags/{flag_key}/scopes/{scope_type}/{scope_ref}`, then check `GET …/history`.
   - **Enabling:** a psql or migration `UPDATE feature_flag_values SET enabled = true` is refused by the DB guard (`flag_enable_source_refused`, migration 0057) in every environment. Enabling also requires the Q48 gate in production (Q56).
   - **Disabling:** the DB also allows an emergency psql `enabled = false`. Record it in the ops log, because that path writes no admin-API audit row.
2. **Bad release:** redeploy the previous image. Migrations are expand-only (ADR-0016), so old code runs on the new schema:
   `ELCHI_IMAGE=elchi-api:<previous-sha> docker compose --env-file .env.app -f docker-compose.prod.yml up -d api worker` (readiness then reads 503 `migrations: unknown`, see §7)
   (images are tagged by commit in `deploy.sh`; keep the last 3).
3. **Bad data/schema change:** forward migration that repairs.
4. **Lost/corrupted database:** restore (BACKUP_RESTORE.md §6), accepting the RPO, and reconcile.
5. **Host move rollback:** only before the new host accepted writes (POSTGRES_POSTGIS_MIGRATION.md §9).

## 9. Local verification of this repository's deploy artefacts

### 9.1 Wave 1.5 (2026-09-14)

Local only. Compose project `a10s`, dummy secrets, `ELCHI_ENVIRONMENT=staging`, Caddy on `127.0.0.1:18080/18443` via a scratch override (ports only; the probes router is now wired into `app.main` by A0a).

| Check | Result |
|---|---|
| Images | `elchi-postgis:16.15-3.5.3-trixie` built (PG 16.15, PostGIS 3.5.3 pinned and held, Debian 13.6, glibc 2.41); api image built without pytest |
| Compose | `config --quiet` exit 0 for prod (with `--profile ops`) and test. A missing `ELCHI_MIGRATION_DATABASE_URL` fails interpolation with its message |
| Limits | db 1g/2 CPU (from `PG_MEMORY_LIMIT`), api 1g/1.5, worker 512m/0.5, redis 384m/0.5, caddy 256m/0.5 as seen by `docker inspect`; `shared_buffers=256MB` from env; redis `maxmemory-policy volatile-lru` |
| Roles | `run --rm db-roles` then `run --rm migrate` as `elchi_owner` (all migrations; second run 0); marker set via `python -m app.modules.platform.environment set staging`. Inside the api container `elchi_app` (super=false, bypassrls=false) was refused for `DISABLE TRIGGER`, `SET session_replication_role`, `COPY … PROGRAM`, `TRUNCATE`, and `UPDATE platform_environment` (`InsufficientPrivilege`) |
| Readiness through Caddy | Allowed CIDR: `/health/ready` 200 `ready`. With `ELCHI_MONITORING_CIDRS=192.0.2.1/32`: `/health/ready` **404**, `/health/live` 200, `/api/v1/health` 200. Gate as `deploy.sh` runs it (curl inside the api container): 200 |
| JSON logs | uvicorn access and app logs are JSON lines. A request with `?exp=…&sig=SMOKESECRET` was logged as `exp=[redacted]&sig=[redacted]`; `SMOKESECRET` occurrences in api logs: 0 |
| `deploy.sh` preflight | Run inside the api image with a 0600 env: refuses `ELCHI_ENVIRONMENT=prod`, a 0644 env file, production without `ELCHI_DATA_RESIDENCY=UZ`, production + `PG_ARCHIVE_MODE=on`, `ELCHI_DATABASE_URL` as superuser, the migration URL as the app role, a weak password, a missing migration URL. `Staging` is normalised with a warning; `local` is accepted |

Caddy IP restriction, live test (real Caddyfile, stub upstream, containers with fixed IPs on `10.77.0.0/24`):

| `ELCHI_MONITORING_CIDRS` | monitor 10.77.0.50 `/health/ready` | other 10.77.0.99 `/health/ready` | both `/health/live`, `/api/v1/health` |
|---|---|---|---|
| unset (default `0.0.0.0/32`) | 404 | 404 | 200 |
| `10.77.0.50/32` | 200 (also `/health/ready/`) | 404 | 200 |
| `192.0.2.0/24 10.77.0.99/32` | 404 | 200 | 200 |

Bypass attempts from the non-monitor peer against the monitor-only config all returned **404**: `X-Forwarded-For: 10.77.0.50`, `X-Real-IP`, `?x=1`, `/health/%72eady`, `/health//ready`, `/health/./ready`. `caddy validate` passes with the variable unset and with two CIDRs.

**Not run end-to-end:** the full `deploy.sh` (its `git pull`, public ACME, pre-deploy backup, marker check and readiness gate were exercised as separate commands, not in one script run), `server_bootstrap.sh`, real DNS/TLS, remote `rsync`.

### 9.2 Wave 1 (2026-09-13)

Local only (Windows laptop, Docker Desktop 29.6.2). Dummy secrets. Compose project `a10s` (not `elchi`). Caddy published on `127.0.0.1:18080/18443` through a scratch override file; nothing else published, so no clash with the test stack (55432/36379). The override also mounted the probes router, because the integrator had not wired it into `app.main` yet. **Never run against real data; no real server was contacted.**

| Check | Command | Result |
|---|---|---|
| Compose renders | `docker compose --env-file dummy.env -f docker-compose.prod.yml config --quiet` | exit 0; a missing `POSTGRES_PASSWORD` fails with the `:?` message |
| Caddyfile | `caddy validate` (caddy 2.11.4 pinned image) | `Valid configuration` |
| Caddy headers/logs | stub upstream + real Caddyfile | upstream `no-referrer` wins; default `strict-origin-when-cross-origin` otherwise; `exp`/`sig` absent from access and error logs (0 matches), other query params kept |
| Image | `docker build` | Python 3.12.14, runs as uid 1000, 90 MB |
| db | `up -d --wait db` | 16.9, `timezone=UTC`, `data_checksums=on`, `C/C.UTF-8`, `scram-sha-256`; no extensions/`template_postgis` from the image init script; WAL archive dir `postgres:700`, `archived_count=2 failed_count=0` |
| redis | `up -d --wait redis` | `NOAUTH` without password, `PONG` with; `protected-mode yes`, `save ""`; password not in process args; runs as `redis` |
| Isolation | `docker inspect` | db/redis only on `backend` (`internal=true`), no published ports; outbound TCP from db fails |
| Migrate job | `run --rm migrate` ×2 | 0001 → 0041 on an empty DB; second run: 0 `Running upgrade` lines |
| api/worker hardening | `docker inspect` | `ReadonlyRootfs=true`, `CapDrop=[ALL]`, `no-new-privileges`, user `elchi`; worker healthcheck `healthy`; caddy only `NET_BIND_SERVICE` |
| Through Caddy (TLS, internal CA) | `curl -k https://localhost:18443/...` | `/api/v1/health` 200 + HSTS + `Referrer-Policy: no-referrer`; `/health/live` 200; `/health/ready` 200 `ready` (all checks `ok`); HTTP → 308 to HTTPS |
| Redis stopped | `stop redis` | `/health/ready` **200 `degraded`**, `redis: unavailable`; back to `ready` after start |
| DB stopped | `stop db` | `/health/ready` **503 `unavailable`**; `/health/live` 200; `/api/v1/health` 200; back to `ready` after start |
| Rehearsal | `docs/ops/rehearsal/rehearse_postgis_switch.sh` | PASSED (POSTGRES_POSTGIS_MIGRATION.md §7) |

Not run: `scripts/deploy.sh` end-to-end (it does `git pull`, public ACME and a production-residency gate; its preflight guards were read-reviewed only), `scripts/server_bootstrap.sh` (needs a fresh root Linux host), any real DNS/TLS, uvicorn with 2 workers under `read_only` (the smoke override used 1 worker; the image CMD uses 2).
