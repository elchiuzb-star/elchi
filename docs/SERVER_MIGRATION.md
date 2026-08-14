# Moving the API to another server

Runbook for moving the backend from one host to another with a few minutes of
downtime. Written for `5.182.26.98` → `178.104.56.36`, but nothing here is
specific to those addresses.

> ⚠️ The current host is in **Uzbekistan**; the new one is Hetzner in
> **Germany**. That moves personal data out of the country, which conflicts with
> ZRU-547 and with the claim in the published privacy policy that data is stored
> on servers in Uzbekistan. Update the policy in the same change, not after.

## What moves, and who moves it

| Item | How |
|---|---|
| `.env.production` | by hand — secrets |
| PostgreSQL data | `pg_dump` → `psql` |
| Uploads (driver documents, cargo photos) | volume tarball, below |
| Code | `git clone` on the new host |
| TLS certificates | **not copied** — Caddy re-issues automatically |

Copying `caddy_data` across would move certificates that are bound to the old
IP's ACME account. Let Caddy get fresh ones; it takes seconds.

---

## 1. Lower the DNS TTL first

Do this **at least an hour before** the migration, at ahost:

```
api  A  5.182.26.98   TTL 300
```

A short TTL means the cutover propagates in minutes instead of hours. Raise it
back afterwards.

## 2. Prepare the new server

```bash
ssh root@178.104.56.36
curl -fsSL https://raw.githubusercontent.com/elchiuzb-star/elchi/main/scripts/server_bootstrap.sh | bash
```

Installs Docker, clones to `/opt/elchi`, opens 22/80/443, creates the volumes.

## 3. Export from the old server

```bash
ssh root@5.182.26.98
cd /opt/elchi
C="docker compose --env-file .env.production -f docker-compose.prod.yml"

# Database
$C exec -T db pg_dump -U elchi -d elchi --clean --if-exists > /root/elchi.sql

# Uploads volume
docker run --rm -v elchi_uploads:/data -v /root:/backup alpine \
  tar czf /backup/uploads.tgz -C /data .

ls -lh /root/elchi.sql /root/uploads.tgz
```

Check both are non-trivial in size before continuing. An empty dump means the
container name or credentials were wrong.

## 4. Transfer

Send it **straight from the old server to the new one**. Both have public IPs,
so there is no reason to pull everything down to your Mac and push it back up —
that turns one fast server-to-server hop into two slow ones over your home
connection, and leaves every secret sitting in your `/tmp`.

Still on the old server:

```bash
scp /root/elchi.sql /root/uploads.tgz /opt/elchi/.env.production \
    root@178.104.56.36:/root/
```

It will ask to accept the new host's fingerprint (`yes`), then prompt for the
new server's root password. No key setup is needed while password auth is still
enabled on the fresh box.

If `scp` is missing on the old server: `apt-get update && apt-get install -y openssh-client`.

Then, on the new server, put the env file where compose expects it:

```bash
mv /root/.env.production /opt/elchi/ && chmod 600 /opt/elchi/.env.production
```

> Going via your Mac also works if the servers cannot reach each other, but
> delete the local copies afterwards — `.env.production` holds every secret you
> have.

## 5. Restore on the new server

```bash
ssh root@178.104.56.36
cd /opt/elchi
C="docker compose --env-file .env.production -f docker-compose.prod.yml"

docker run --rm -v elchi_uploads:/data -v /root:/backup alpine \
  tar xzf /backup/uploads.tgz -C /data

$C up -d db
sleep 10
cat /root/elchi.sql | $C exec -T db psql -U elchi -d elchi

# sanity check: should match the old server
$C exec -T db psql -U elchi -d elchi -c \
  "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM orders) AS orders;"
```

## 6. Cut over

Only now change DNS at ahost:

```
api  A  178.104.56.36   TTL 300
```

Wait for it to propagate, then start the stack:

```bash
cd /opt/elchi && ./scripts/deploy.sh
```

Caddy obtains a certificate during this step, which is why it has to come after
the DNS change. `deploy.sh` retries the health check for 60s while that happens.

Verify from your Mac:

```bash
dig +short api.elchigo.uz            # expect 178.104.56.36
curl -s https://api.elchigo.uz/api/v1/health
curl -s https://api.elchigo.uz/api/v1/cities | head -c 120
```

Also open one driver document in the admin panel — that proves the uploads
volume came across, which a health check does not.

## 7. Afterwards

- Leave the old server running for a day in case of rollback, then destroy it
- Restore the DNS TTL to its normal value
- Re-point `ELCHI_CORS_ORIGINS` only if your frontend domains changed (they do
  not, in this move)
- Update the privacy policy's data-location statement
- Rotate any credentials that were pasted into chat or shell history

## Rolling back

Nothing on the old server is deleted by this procedure. If the new host
misbehaves, point the DNS record back at the old IP; it is still running with
its data intact. That is the reason for the short TTL.
