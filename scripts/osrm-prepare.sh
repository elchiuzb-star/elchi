#!/usr/bin/env bash
#
# Build the routing graph our own OSRM serves.
#
# Why we run a router at all: the `fake` provider draws straight lines between stops, which is honest
# about being synthetic and useless as a road, and `geoapify` is a third party outside the country that
# Q24 keeps switched off until a legal review. OSRM on an OpenStreetMap extract is the same routing
# quality with neither problem - nothing leaves this machine, so there is no external data flow to
# review (see docs/ops/EXTERNAL_DATA_FLOWS.md, E9).
#
# This is a **one-time** step per extract. `osrm-routed` serves a prepared graph; it does not build one.
#
#   scripts/osrm-prepare.sh                 # download the extract if missing, then prepare it
#   scripts/osrm-prepare.sh --refresh       # download a fresh extract first (Geofabrik updates daily)
#
# Then:
#   docker compose -f docker-compose.dev.yml --profile routing up -d osrm
#   ELCHI_GEO_ROUTING_PROVIDER=osrm   in .env
#
# Cost: ~120 MB download, a few minutes of CPU, a couple of GB of RAM while it runs. The prepared graph
# is a few hundred MB in docker/osrm/data and is gitignored.
set -euo pipefail

# Pinned by digest, like every other image in this repo (decision 51 for the db image; same rule here).
IMAGE="osrm/osrm-backend:v5.25.0@sha256:bdfa60e64ae1376bff6ff5605991be50600132a27469a4a9e77c23afd3a6d555"
EXTRACT_URL="https://download.geofabrik.de/asia/uzbekistan-latest.osm.pbf"
PBF_NAME="uzbekistan-latest.osm.pbf"
GRAPH_NAME="uzbekistan-latest.osrm"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT/docker/osrm/data"

# Git Bash rewrites anything that looks like a Unix path into a Windows one before it reaches the
# container, so `/opt/car.lua` arrives as `C:/Program Files/Git/opt/car.lua` and osrm-extract refuses
# it. Both variables are needed: one for the path, one for the arguments.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

# docker -v needs a Windows-style host path on Windows, and a plain one everywhere else.
if command -v cygpath >/dev/null 2>&1; then
  HOST_DATA="$(cygpath -w "$DATA_DIR")"
else
  HOST_DATA="$DATA_DIR"
fi

mkdir -p "$DATA_DIR"

if [ "${1:-}" = "--refresh" ] || [ ! -f "$DATA_DIR/$PBF_NAME" ]; then
  echo "== downloading $EXTRACT_URL"
  curl -fL --progress-bar -o "$DATA_DIR/$PBF_NAME" "$EXTRACT_URL"
fi

run_osrm() {
  docker run --rm -v "$HOST_DATA:/data" "$IMAGE" "$@"
}

echo "== osrm-extract (car profile)"
run_osrm osrm-extract -p /opt/car.lua "/data/$PBF_NAME"

echo "== osrm-partition"
run_osrm osrm-partition "/data/$GRAPH_NAME"

echo "== osrm-customize"
run_osrm osrm-customize "/data/$GRAPH_NAME"

echo
echo "prepared. Start the router with:"
echo "  docker compose -f docker-compose.dev.yml --profile routing up -d osrm"
echo "and point the app at it with ELCHI_GEO_ROUTING_PROVIDER=osrm in .env"
