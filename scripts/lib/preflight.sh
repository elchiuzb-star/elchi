#!/usr/bin/env bash
# Pure preflight checks shared by scripts/deploy.sh and tests/pg/ops/test_deploy_preflight.py.
# Source it; every function prints problems to stderr and returns non-zero on failure.
# No docker, no network, no side effects.

# Keys that must never reach the api/worker containers (BR N2): database superuser and owner
# credentials. They belong only in the db-admin env file (db, db-roles, migrate).
ELCHI_ADMIN_ONLY_KEYS=(
	POSTGRES_PASSWORD
	ELCHI_DB_OWNER_PASSWORD
	ELCHI_MIGRATION_DATABASE_URL
	ELCHI_DB_ADMIN_URL
)

# is_ipv4_cidr "10.0.0.0/8" -> 0 when a.b.c.d/nn with octets 0-255 and prefix 0-32.
is_ipv4_cidr() {
	local value="$1" ip prefix octet
	[[ "$value" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})/([0-9]{1,2})$ ]] || return 1
	prefix="${BASH_REMATCH[5]}"
	((10#$prefix <= 32)) || return 1
	for octet in "${BASH_REMATCH[@]:1:4}"; do
		((10#$octet <= 255)) || return 1
	done
	ip="${value%/*}"
	[[ -n "$ip" ]]
}

# is_ipv6_cidr "2001:db8::/32" -> 0 for hex groups with at most one "::" and prefix 0-128.
# Deliberately conservative; the final authority is `caddy validate` on the rendered config.
is_ipv6_cidr() {
	local value="$1" addr prefix groups
	[[ "$value" =~ ^([0-9A-Fa-f:]+)/([0-9]{1,3})$ ]] || return 1
	addr="${BASH_REMATCH[1]}"
	prefix="${BASH_REMATCH[2]}"
	((10#$prefix <= 128)) || return 1
	[[ "$addr" == *:* ]] || return 1
	[[ "$addr" != *:::* ]] || return 1
	local doubles="${addr//[^:]/}"
	[[ "$(grep -o '::' <<<"$addr" | wc -l | tr -d ' ')" -le 1 ]] || return 1
	groups="$(tr ':' '\n' <<<"$addr" | grep -c . || true)"
	((groups <= 8)) || return 1
	[[ ${#doubles} -le 7 || "$addr" == *::* ]] || return 1
	! tr ':' '\n' <<<"$addr" | grep -Eqv '^([0-9A-Fa-f]{1,4})?$'
}

# validate_monitoring_cidrs "<value>" (BR N5, decision 33)
#   empty -> ok (compose falls back to 0.0.0.0/32 = deny everyone)
#   every space-separated token must be an IPv4/IPv6 CIDR; no placeholders; never "everyone".
validate_monitoring_cidrs() {
	local value="$1" token bad=0
	if [[ -z "${value//[[:space:]]/}" ]]; then
		return 0
	fi
	if [[ "$value" == *"<"* || "$value" == *">"* ]]; then
		echo "ELCHI_MONITORING_CIDRS still holds a <placeholder>" >&2
		return 1
	fi
	if [[ "$value" == *,* ]]; then
		echo "ELCHI_MONITORING_CIDRS must be space-separated, not comma-separated" >&2
		return 1
	fi
	for token in $value; do
		case "$token" in
		0.0.0.0/0 | ::/0 | 0::/0)
			echo "ELCHI_MONITORING_CIDRS token '$token' would expose readiness to everyone" >&2
			bad=1
			continue
			;;
		esac
		if ! is_ipv4_cidr "$token" && ! is_ipv6_cidr "$token"; then
			echo "ELCHI_MONITORING_CIDRS token '$token' is not a CIDR (use a.b.c.d/nn or an IPv6 prefix)" >&2
			bad=1
		fi
	done
	return "$bad"
}

# app_env_forbidden_keys <env-file> -> prints admin-only keys present in the file; 1 if any.
app_env_forbidden_keys() {
	local file="$1" key found=0
	for key in "${ELCHI_ADMIN_ONLY_KEYS[@]}"; do
		if grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$file"; then
			echo "$key"
			found=1
		fi
	done
	return "$found"
}

# JSON helpers for `docker compose config --format json` (wave 1.7 NEW-6).
# Parsing uses Python, taken from ELCHI_PREFLIGHT_PYTHON (a command, split on spaces), default
# "python3". scripts/deploy.sh points it at the api image it just built
# (`docker run --rm -i --network none --entrypoint python <image>`): the deploy host then needs
# no Python of its own, and the interpreter is the pinned 3.12 of the release. Tests pass
# sys.executable.
_preflight_python() {
	local -a cmd
	read -r -a cmd <<<"${ELCHI_PREFLIGHT_PYTHON:-python3}"
	"${cmd[@]}" "$@"
}

# rendered_env_forbidden_keys <service> < compose-config.json
#   prints admin-only keys present in the service's environment; returns 1 if any,
#   2 if the service or its environment block cannot be found (never "ok" by accident).
rendered_env_forbidden_keys() {
	local service="$1"
	_preflight_python -c '
import json, sys
service, keys = sys.argv[1], sys.argv[2:]
try:
    config = json.load(sys.stdin)
except ValueError as exc:
    print(f"rendered config is not JSON: {exc}", file=sys.stderr); sys.exit(2)
svc = (config.get("services") or {}).get(service)
if svc is None:
    print(f"service {service!r} not found in rendered config", file=sys.stderr); sys.exit(2)
env = svc.get("environment")
if not env:
    print(f"service {service!r} has no environment block in rendered config", file=sys.stderr); sys.exit(2)
names = set(env) if isinstance(env, dict) else {str(item).split("=", 1)[0] for item in env}
found = [key for key in keys if key in names]
print("\n".join(found))
sys.exit(1 if found else 0)
' "$service" "${ELCHI_ADMIN_ONLY_KEYS[@]}"
}

# rendered_service_image <service> < compose-config.json -> image reference; 2 if absent.
rendered_service_image() {
	_preflight_python -c '
import json, sys
svc = (json.load(sys.stdin).get("services") or {}).get(sys.argv[1]) or {}
image = svc.get("image")
if not image:
    print(f"service {sys.argv[1]!r} has no image in rendered config", file=sys.stderr); sys.exit(2)
print(image)
' "$1"
}

# diff_guarded_tables <expected-file> <actual-comma-list> -> 0 when equal as sets (comments ignored).
diff_guarded_tables() {
	local expected actual
	# First column only: "<table> [read-only|app-marker]  # comment" (scripts/db_roles.py read_guard_classes).
	expected="$(sed 's/#.*//' "$1" | awk 'NF { print $1 }' | sort -u | paste -sd, -)"
	actual="$(tr ',' '\n' <<<"$2" | tr -d '[:space:]' | grep -v '^$' | sort -u | paste -sd, -)"
	if [[ "$expected" != "$actual" ]]; then
		echo "session/depth-guarded tables differ: expected [$expected] detected [$actual]" >&2
		return 1
	fi
}

# is_digest_pinned "<image>" -> 0 for name@sha256:<64 hex>
is_digest_pinned() {
	[[ "$1" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]
}
