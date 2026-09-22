#!/usr/bin/env bash
# Prepare a fresh Linux server (any provider) to run Elchi. Run ON THE NEW SERVER as root.
#
#   git clone --branch <release-tag> https://github.com/elchiuzb-star/elchi.git /opt/elchi
#   /opt/elchi/scripts/server_bootstrap.sh
#
# Prefer cloning a reviewed tag over `curl ... | bash` from a moving branch.
# Installs Docker and a few tools, prepares the firewall and directories. It
# deliberately does NOT touch .env.app / .env.db-admin, backups or the database -- those
# carry secrets and live data (docs/ops/UZ_HOSTING_RUNBOOK.md).
set -euo pipefail

REPO="${REPO:-https://github.com/elchiuzb-star/elchi.git}"
REF="${REF:-main}"
TARGET="${TARGET:-/opt/elchi}"
ENABLE_UFW="${ENABLE_UFW:-0}"

say() { printf '\n==> %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }

say "Base packages"
if command -v apt-get >/dev/null 2>&1; then
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -q
	# chrony: JWT/OTP expiry and signed URLs depend on a correct clock.
	# gnupg/rsync: scripts/backup.sh encryption and off-box shipping.
	apt-get install -y -q ca-certificates curl git gnupg rsync chrony ufw
else
	echo "    not a Debian/Ubuntu host: install curl git gnupg rsync chrony and a firewall manually"
fi

say "Docker"
if command -v docker >/dev/null 2>&1; then
	echo "    already installed: $(docker --version)"
else
	# Review https://get.docker.com before running it on a production host, or
	# install docker-ce from the distribution's documented repository.
	curl -fsSL https://get.docker.com | sh
	systemctl enable --now docker
fi
docker compose version >/dev/null || { echo "docker compose plugin missing" >&2; exit 1; }

say "Repository at $TARGET"
if [ -d "$TARGET/.git" ]; then
	echo "    already present at $(git -C "$TARGET" rev-parse --short HEAD); update with scripts/deploy.sh"
else
	git clone --branch "$REF" "$REPO" "$TARGET"
fi

say "Firewall"
# Only Caddy publishes ports (80 for the ACME HTTP challenge + redirect, 443).
# Postgres and Redis are on an internal Docker network and never published.
# Note: Docker-published ports bypass ufw, so never add `ports:` to db/redis.
if command -v ufw >/dev/null 2>&1; then
	ufw default deny incoming >/dev/null
	ufw default allow outgoing >/dev/null
	ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
	ufw allow 80/tcp >/dev/null
	ufw allow 443/tcp >/dev/null
	if [ "$ENABLE_UFW" = "1" ]; then
		ufw --force enable
	else
		echo "    rules staged for 22, 80, 443 (enable with: ufw enable, or rerun with ENABLE_UFW=1)"
	fi
else
	echo "    no ufw; allow only 22, 80 and 443 inbound"
fi

say "Directories"
install -d -m 700 /var/backups/elchi /etc/elchi
echo "    /var/backups/elchi (local backup staging), /etc/elchi (backup.env)"
# Volumes are created by docker compose. Do NOT pre-create "elchi_pgdata": that
# is the legacy postgres:16-alpine volume name and scripts/deploy.sh treats it
# as un-migrated data.

say "Clock"
timedatectl show -p Timezone -p NTPSynchronized 2>/dev/null || date -u

say "Done"
cat <<'EOF'

Next (docs/ops/UZ_HOSTING_RUNBOOK.md):
  1. Harden SSH (keys only, no root password login) -- by hand, with a second session open.
  2. cp app.env.example .env.app && cp db-admin.env.example .env.db-admin && chmod 600 .env.app .env.db-admin
     Fill both in (admin credentials ONLY in .env.db-admin); set ELCHI_POSTGIS_IMAGE to the UZ registry
     digest (docker login <registry>), ELCHI_DOMAIN, ELCHI_MONITORING_CIDRS and, only after verifying
     hosting + registry + backup location, ELCHI_DATA_RESIDENCY=UZ.
  3. Create /etc/elchi/backup.env (BACKUP_GPG_RECIPIENT, BACKUP_REMOTE) and import
     the backup PUBLIC key: gpg --import elchi-backup-public.asc
  4. Restore data (docs/ops/POSTGRES_POSTGIS_MIGRATION.md) and uploads.
  5. Point DNS at this server, then ./scripts/deploy.sh
EOF
