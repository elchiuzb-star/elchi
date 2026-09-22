# PostgreSQL 16.15 + PostGIS 3.5.3 on Debian 13 "trixie" (glibc 2.41).
# Used by docker-compose.prod.yml (db) and docker-compose.test.yml (postgis).
#
# Why a local image (decision 34): no official postgis/postgis tag combines
# PG 16 + PostGIS 3.5 with a supported Debian. `postgis/postgis:16-3.5` is Debian 11
# "bullseye" (EOL) and PG 16.9. apt.postgresql.org's trixie-pgdg main repo now only
# carries PostGIS 3.6.x; the 3.5.x builds for trixie live in trixie-pgdg-archive.
#
# Reproducibility: the base is pinned by tag AND digest, packages by exact version,
# and the build asserts both versions. Bump all three together, then rerun tests/pg
# and docs/ops/rehearsal/rehearse_postgis_switch.sh.
FROM postgres:16.15-trixie@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94

ARG POSTGIS_PACKAGE_VERSION=3.5.3+dfsg-2.pgdg13+1

LABEL org.opencontainers.image.title="elchi-postgis" \
      org.opencontainers.image.description="PostgreSQL 16.15 + PostGIS 3.5.3 (Debian trixie) for Elchi" \
      org.opencontainers.image.base.name="postgres:16.15-trixie"

# The base image already trusts the apt.postgresql.org signing key; the archive
# repository is signed with the same key. The archive is HTTPS-only (HTTP redirects),
# so CA certificates are installed first.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates; \
    echo "deb [ signed-by=/usr/local/share/keyrings/postgres.gpg.asc ] https://apt-archive.postgresql.org/pub/repos/apt trixie-pgdg-archive main" \
        > /etc/apt/sources.list.d/pgdg-archive.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "postgresql-16-postgis-3=${POSTGIS_PACKAGE_VERSION}" \
        "postgresql-16-postgis-3-scripts=${POSTGIS_PACKAGE_VERSION}"; \
    apt-mark hold postgresql-16-postgis-3 postgresql-16-postgis-3-scripts; \
    rm -rf /var/lib/apt/lists/*; \
    test "$(dpkg-query -W -f='${Version}' postgresql-16-postgis-3)" = "${POSTGIS_PACKAGE_VERSION}"; \
    postgres --version | grep -q ' 16\.15 '
