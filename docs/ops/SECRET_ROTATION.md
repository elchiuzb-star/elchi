# Secret rotation

Owner: A10a · 2026-09-14 (wave 1.5, BR #8) · ADR-0018 · spec §17.5–17.6 · AGENTS.md §6 (N5)

## 1. Model: master secret, derived subkeys, keyring

`ELCHI_SECRET_KEY` is a **master**; features never use it raw. They derive per-purpose subkeys:
`derive_subkey(master, purpose, v) = HMAC-SHA256(master, "elchi:<purpose>:v<v>")` (`app/contracts/crypto.py`).

For rotation the contract provides a **keyring** (N5):

```python
build_keyring(purpose, current_master, previous_masters=(), *, version=1, previous_versions=())
KEY_ROTATION_VERIFICATION_WINDOW = timedelta(hours=48)
verify_proof_code(keyring, booking_public_id, proof_kind, rotation, provided)   # tries current + previous, constant work
```

New codes and signatures always use the **current** subkey. Previous subkeys stay accepted for **48 h**, then are removed from configuration.

| Purpose / consumer | Key source | Keyring today? | Effect of rotating `ELCHI_SECRET_KEY` with the keyring procedure (§2) |
|---|---|---|---|
| Booking proof codes (`booking-proof-code-key`) | `ELCHI_PROOF_CODE_KEY` if set, else derived from the master | **Yes** (`build_keyring` + `verify_proof_code`) | Codes already shown to users keep verifying for 48 h. Newly displayed codes use the new key. |
| Cursor signing (`cursor-signing-key`) | `ELCHI_CURSOR_SIGNING_KEY` if set, else derived | Derived; verification with previous keys is not wired | An outstanding cursor fails and the client restarts from page one. Harmless. |
| File URL signing (`elchi:file-url-signing-key:v1`) | `ELCHI_FILE_URL_SIGNING_KEY` if set, else derived | No | Only if the explicit key is unset: signed links die (≤ 15 min TTL); clients refetch. |
| JWT access/refresh (HS256) | **raw** master (`app/core/security.py`) | **No: open item for A0a** | Every token is invalid, so **all users and staff are logged out**. |
| OTP hash `sha256(master:otp)` | raw master (`auth_service.otp_hash`) | No | OTPs issued in the last ≤ 180 s fail. |
| Refresh-session `token_hash`, share/tracking tokens | unkeyed SHA-256 of random tokens | n/a | Not affected. |

**Settings (done, A0a wave 1.5):** `app/core/config.py` reads `ELCHI_PREVIOUS_SECRET_KEYS` (comma-separated), `ELCHI_PROOF_CODE_KEY` and `ELCHI_CURSOR_SIGNING_KEY`, and provides:
- `proof_code_keyring()`: `build_keyring(PURPOSE_BOOKING_PROOF_CODE, proof_code_key or secret_key, previous_masters=previous_secret_keys)`;
- `cursor_signing_secret()`.

**A4 must derive and verify proof codes only through `proof_code_keyring()`**, never with `derive_subkey(settings.secret_key, …)` directly; otherwise §2 step 2 has no effect on proof codes.

**Open items for A0a** (not done here):
1. A JWT keyring: add a `kid` header; sign with the current key; accept keys from `ELCHI_PREVIOUS_SECRET_KEYS` for `refresh_token_expire_days`, not just 48 h.
2. Have `otp_hash` also try previous masters.

Until then, a master rotation still means a global logout.

## 2. Procedure: rotate the master (`ELCHI_SECRET_KEY`)

`C="docker compose --env-file .env.app -f docker-compose.prod.yml"`. App keys live in `.env.app`; database admin credentials in `.env.db-admin`. Generate values with `openssl rand -hex 32`. Every step goes in the ops log (who, when, why; never the value).

1. **Pin the dedicated subkeys first** (one-time, before stage-2 launch). Set `ELCHI_PROOF_CODE_KEY` and `ELCHI_CURSOR_SIGNING_KEY` to values derived from the *current* master, or rotate them separately (§3). After that, a master rotation no longer touches proof codes at all.
2. **Add the previous master:** `ELCHI_PREVIOUS_SECRET_KEYS=<current value>` (comma-separated, newest first).
3. **Rotate:** `ELCHI_SECRET_KEY=<new value>`, then `$C up -d --force-recreate api worker` (no migrate).
4. **Verify:** `/api/v1/health` is 200; log in with a staff account; one in-flight proof code (staging) still verifies; for 48 h, watch the login/OTP rate and the SMS daily cap (`ELCHI_OTP_GLOBAL_DAILY_CAP`), because JWTs are not on a keyring yet.
5. **Wait 48 h** (`KEY_ROTATION_VERIFICATION_WINDOW`).
6. **Remove** the old value from `ELCHI_PREVIOUS_SECRET_KEYS` and recreate api/worker again. Now the old master is unusable.

## 3. Procedure: rotate a dedicated subkey

| Key | Procedure |
|---|---|
| `ELCHI_PROOF_CODE_KEY` | Put the current value into the proof keyring's previous list (A4 wiring via `build_keyring(..., previous_masters=...)`), set the new value, recreate api/worker, wait 48 h, remove the previous. If a key **leaked**: re-issue codes for active bookings by incrementing `code_rotation` (ADR-0018 §2) instead of waiting. |
| `ELCHI_CURSOR_SIGNING_KEY` | Set the new value, recreate api. Old cursors fail, clients restart pagination. |
| `ELCHI_FILE_URL_SIGNING_KEY` | Set the new value, recreate api. Links older than the TTL were dead anyway. |

## 4. Other secrets

| Secret (env) | Blast radius | Procedure |
|---|---|---|
| `POSTGRES_PASSWORD` (bootstrap superuser, `.env.db-admin`) | Nothing online: pg_hba rejects this user over TCP; db-roles and backups use the local socket | `$C exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER USER \"$POSTGRES_USER\" PASSWORD '"'"'<new>'"'"'"'`; update `.env.db-admin`. The env var only matters at initdb. |
| `ELCHI_DB_OWNER_PASSWORD` + `ELCHI_MIGRATION_DATABASE_URL` (`.env.db-admin`) | migrate job | Update both values; `$C run --rm db-roles` resets the password (idempotent). |
| `ELCHI_DB_APP_PASSWORD` (`.env.db-admin`) + `ELCHI_DATABASE_URL` (`.env.app`) | api/worker lose the DB until they restart | Update both files (`deploy.sh` checks they match); `$C run --rm db-roles && $C up -d --force-recreate api worker`. Seconds of 5xx: do it in low traffic. |
| `REDIS_PASSWORD` + `ELCHI_REDIS_URL` | Readiness `degraded` for seconds; no data loss (ADR-0012) | Update both; `$C up -d --force-recreate redis api worker`. |
| `ELCHI_ESKIZ_PASSWORD` | SMS/OTP delivery | Change in the Eskiz cabinet, update the env, recreate api (drops the cached token). Send one OTP to a staff phone. |
| `ELCHI_GOOGLE_MAPS_API_KEY`, `ELCHI_YANDEX_GEOCODER_API_KEY`, `ELCHI_GEO_GEOAPIFY_API_KEY` | Geocoding/routing during the swap | Create the new key (IP-restricted), deploy, verify, then delete the old key in the console. |
| `ELCHI_REVIEW_LOGIN_OTP` / `ELCHI_REVIEW_LOGIN_PHONES` | Store reviewers | **Clear both** when store review ends (Q8). Before removing a phone (Q39), clear its open items first: (1) `$C run --rm --no-deps api python scripts/check_review_account_orders.py <phone>`, which exits 1 while open orders, active bids or open disputes remain; (2) close them (admin cancel, dispute resolution); (3) re-run until it exits 0; (4) only then edit `ELCHI_REVIEW_LOGIN_PHONES` and recreate api/worker. Removing the phone first turns the review account's leftovers into items visible to real users. |
| Staff passwords | Individual | `scripts/set_staff_password.py`; block the account on offboarding. |
| Backup GPG keypair | Reading backups | New keypair, update `BACKUP_GPG_RECIPIENT`, **keep the old private key** offline until its last backup has expired, test-decrypt one old and one new backup. |
| Backup SSH key | Off-box shipping | New key in the backup host's `authorized_keys` (write-only `rrsync`), one backup, remove the old key. |
| Future FCM service account / VAPID keys | Push | FCM: new key, deploy, revoke old. **VAPID rotation invalidates all Web Push subscriptions.** |

## 5. Host migration (Germany → Uzbekistan)

Generate every secret fresh on the new host. The exception is `ELCHI_SECRET_KEY`: carrying it over avoids a global logout at cutover, but then rotate it with §2 within a week, because the old host, shell histories and chat may hold it. Rotate the Eskiz/Google/Yandex credentials in their consoles right after cutover.

## 6. Triggers

Suspected compromise (immediately, and skip the 48 h window for the leaked key) · staff or contractor offboarding · host migration or decommissioning · a secret pasted into chat, a ticket or shell history · annually for API keys and backup SSH keys.
