#!/usr/bin/env bash
# Prepare a fresh server to run the Elchi API. Run this ON THE NEW SERVER as root.
#
#   curl -fsSL https://raw.githubusercontent.com/elchiuzb-star/elchi/main/scripts/server_bootstrap.sh | bash
#   # or: git clone ... && ./scripts/server_bootstrap.sh
#
# Installs Docker, clones the repo to /opt/elchi and creates the upload volume.
# It deliberately does NOT touch .env.production or the database — those carry
# secrets and live data, and are copied across by hand.
set -euo pipefail

REPO="${REPO:-https://github.com/elchiuzb-star/elchi.git}"
TARGET="${TARGET:-/opt/elchi}"

say() { printf '\n==> %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }

say "Docker"
if command -v docker >/dev/null 2>&1; then
	echo "    already installed: $(docker --version)"
else
	curl -fsSL https://get.docker.com | sh
	systemctl enable --now docker
fi

say "Repository at $TARGET"
if [ -d "$TARGET/.git" ]; then
	git -C "$TARGET" pull --ff-only
else
	git clone "$REPO" "$TARGET"
fi
cd "$TARGET"

say "Firewall"
# Caddy needs 80 for the ACME HTTP challenge as well as 443 for traffic.
if command -v ufw >/dev/null 2>&1; then
	ufw allow 22/tcp  >/dev/null 2>&1 || true
	ufw allow 80/tcp  >/dev/null 2>&1 || true
	ufw allow 443/tcp >/dev/null 2>&1 || true
	echo "    ufw rules added for 22, 80, 443 (enable with: ufw enable)"
else
	echo "    no ufw; make sure 22, 80 and 443 are reachable"
fi

say "Volumes"
# Created up front so uploads can be restored before the stack first starts.
docker volume create elchi_uploads >/dev/null
docker volume create elchi_pgdata  >/dev/null
echo "    elchi_uploads, elchi_pgdata ready"

say "Done"
cat <<'EOF'

Still to do by hand, in this order:

  1. Copy .env.production into /opt/elchi  (chmod 600)
  2. Restore the uploads archive:
       docker run --rm -v elchi_uploads:/data -v /root:/backup alpine \
         tar xzf /backup/uploads.tgz -C /data
  3. Start the database only, then restore the dump:
       cd /opt/elchi
       docker compose --env-file .env.production -f docker-compose.prod.yml up -d db
       cat /root/elchi.sql | docker compose --env-file .env.production \
         -f docker-compose.prod.yml exec -T db psql -U elchi -d elchi
  4. Point api.elchigo.uz at this server's IP
  5. ./scripts/deploy.sh

Caddy cannot obtain a TLS certificate until step 4 has propagated, so run
step 5 after the DNS change, not before.
EOF
