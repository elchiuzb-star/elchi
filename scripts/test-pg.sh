#!/usr/bin/env bash
# Run the PostgreSQL 16 + PostGIS test suite (tests/pg) against docker-compose.test.yml.
#
#   scripts/test-pg.sh                 # up (if needed), wait healthy, pytest -m pg, leave stack running
#   scripts/test-pg.sh --down          # ... and tear the stack down afterwards
#   scripts/test-pg.sh -- -k harness   # extra pytest arguments after --
#   PYTHON=/path/to/python scripts/test-pg.sh
#
# Works in Git Bash on Windows, Linux and macOS.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/docker-compose.test.yml"
project="elchi-test"
down=0
pytest_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --down) down=1; shift ;;
    --) shift; pytest_args+=("$@"); break ;;
    *) pytest_args+=("$1"); shift ;;
  esac
done

# Port 45432 (Q76): 55432 sat inside a Windows excluded TCP range (`netsh
# interface ipv4 show excludedportrange protocol=tcp`), which made the
# postgis container fail with "access permissions".
export ELCHI_TEST_PG_URL="${ELCHI_TEST_PG_URL:-postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_test}"
# The stack was just started: an unreachable server must fail loudly, never skip.
export ELCHI_TEST_PG_REQUIRED=1

if [[ -n "${PYTHON:-}" ]]; then python_cmd=("$PYTHON")
elif command -v py >/dev/null 2>&1; then python_cmd=(py)
elif command -v python3 >/dev/null 2>&1; then python_cmd=(python3)
else python_cmd=(python); fi

docker info --format '{{.ServerVersion}}' >/dev/null || { echo "Docker daemon is not reachable. Start Docker first." >&2; exit 1; }

teardown() {
  if [[ "$down" == 1 ]]; then
    echo "==> docker compose down ($project)"
    docker compose -p "$project" -f "$compose_file" down -v --remove-orphans
  fi
}
trap teardown EXIT

echo "==> docker compose up ($project)"
docker compose -p "$project" -f "$compose_file" up -d --wait

cd "$repo_root"
echo "==> ELCHI_TEST_PG_REQUIRED=1 ${python_cmd[*]} -m pytest -m pg tests/pg ${pytest_args[*]:-}"
set +e
# ${arr[@]+"${arr[@]}"}: an empty array is an "unbound variable" under set -u in bash < 4.4 (macOS 3.2).
"${python_cmd[@]}" -m pytest -m pg tests/pg ${pytest_args[@]+"${pytest_args[@]}"}
status=$?
set -e
exit "$status"
