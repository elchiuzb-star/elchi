"""How much of the v2 API the stage-2 client (`mobile-app/`) actually uses - measured, not estimated.

For every operation in the committed `mobile-app/src/api/generated/openapi-v2.json` it answers two questions:

1. **wrapper** - is there an exported function in `mobile-app/src/api/v2/*.api.ts` whose body calls
   `v2Request` / `v2RequestFull` / `v2AdminRequest` / `v2AdminRequestFull` with this path and method?
   Paths are normalised: `{param}` in the schema and `${...}` in the code both become `{}`.
2. **screen** - is that function (or a re-export of it) referenced outside `src/api/**` and outside test files,
   i.e. by a screen or component under `src/app/**`, `src/components/**` or `src/pages/**`?

An operation is `UI` (wrapper + screen), `WRAPPER_ONLY` or `NONE`. Operations the product decided not to call from
this client (and that no screen calls anyway) are listed in `INTENTIONALLY_UNCALLED` with the decision that says so, and reported separately - they
are not counted as gaps, and they are never counted as covered either.

Usage::

    py scripts/client_coverage.py            # summary
    py scripts/client_coverage.py --list     # plus every NONE / WRAPPER_ONLY operation
    py scripts/client_coverage.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "mobile-app" / "src"
SCHEMA = CLIENT / "api" / "generated" / "openapi-v2.json"
WRAPPERS = CLIENT / "api" / "v2"
SCREEN_DIRS = [CLIENT / "app", CLIENT / "components", CLIENT / "pages"]
METHODS = ("get", "post", "put", "patch", "delete")

#: Not called by this client on purpose; each entry names the decision. Kept out of both the covered and the gap count.
INTENTIONALLY_UNCALLED: dict[tuple[str, str], str] = {
    ("GET", "/proposals/{}/messages"): "Q100: price talk is not free-text chat",
    ("POST", "/proposals/{}/messages"): "Q100: price talk is not free-text chat",
    ("POST", "/tracking/sessions"): "GPS is sent by the driver's Android app (spec §10.3)",
    ("POST", "/tracking/sessions/{}/points:batch"): "GPS is sent by the driver's Android app (spec §10.3)",
    ("POST", "/tracking/sessions/{}/close"): "GPS is sent by the driver's Android app (spec §10.3)",
    ("POST", "/devices/push-token"): "Q82: no push provider until FCM go-live (ADR-0022)",
    ("DELETE", "/devices/{}"): "Q82: no push provider until FCM go-live (ADR-0022)",
    ("POST", "/routes/preview"): "Q24/Q46: routing provider off",
    ("POST", "/routes/{}/confirm"): "Q24/Q46: routing provider off",
    ("GET", "/events"): "diagnostics surface, not a product screen",
    ("GET", "/me"): "ADR-0006: identity stays on v1 in this client",
    ("DELETE", "/me"): "ADR-0006: account deletion stays on v1 in this client",
    ("POST", "/me/roles"): "ADR-0006: role switch stays on v1 in this client",
}

CALL = re.compile(
    r"v2(?:Admin)?Request(?:Full)?\s*<[^;]*?>\s*\(\s*([`\"])(?P<path>.+?)\1(?P<rest>(?:[^()]|\([^()]*\))*?)\)", re.S
)
FUNC = re.compile(r"export\s+(?:async\s+)?function\s+(\w+)\s*\(")
REEXPORT = re.compile(r"export\s*\{([^}]*)\}\s*from")
IMPORT_AS = re.compile(r"(\w+)\s+as\s+(\w+)")


def norm(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    return re.sub(r"\{[^}]*\}", "{}", path)


def schema_operations() -> list[tuple[str, str]]:
    spec = json.loads(SCHEMA.read_text(encoding="utf-8"))
    ops = []
    for path, item in spec["paths"].items():
        short = path.removeprefix("/api/v2")
        for method in METHODS:
            if method in item:
                ops.append((method.upper(), norm(short)))
    return ops


def wrapper_functions() -> dict[tuple[str, str], set[str]]:
    """(METHOD, path) -> names of exported functions that call it."""
    found: dict[tuple[str, str], set[str]] = {}
    for file in sorted(WRAPPERS.glob("*.api.ts")):
        text = file.read_text(encoding="utf-8")
        starts = [(m.start(), m.group(1)) for m in FUNC.finditer(text)]
        for call in CALL.finditer(text):
            owner_at = next(((pos, name) for pos, name in reversed(starts) if pos < call.start()), None)
            if owner_at is None:
                continue
            start, owner = owner_at
            # The method is inline, or in an `options` object built earlier in the same function.
            method = re.search(r"method:\s*\"(\w+)\"", call.group("rest"))
            if method is None and "options" in call.group("rest"):
                earlier = re.findall(r"method:\s*\"(\w+)\"", text[start:call.start()])
                method = re.match(r"(\w+)", earlier[-1]) if earlier else None
            key = ((method.group(1) if method else "GET").upper(), norm(call.group("path")))
            found.setdefault(key, set()).add(owner)
    return found


def used_names() -> set[str]:
    """Identifiers referenced by screens/components (tests and the api folder excluded), aliases resolved."""
    names: set[str] = set()
    for folder in SCREEN_DIRS:
        for file in folder.rglob("*.ts*"):
            if ".test." in file.name:
                continue
            text = file.read_text(encoding="utf-8")
            names.update(re.findall(r"\b[A-Za-z_]\w*\b", text))
            names.update(original for original, _alias in IMPORT_AS.findall(text))
    # A wrapper re-exported by another api module (e.g. safety.api.ts) is used when its re-export is used.
    for file in WRAPPERS.glob("*.api.ts"):
        for group in REEXPORT.findall(file.read_text(encoding="utf-8")):
            for part in group.split(","):
                bits = part.strip().split(" as ")
                if bits and bits[-1].strip() in names:
                    names.add(bits[0].strip())
    return names


def matches(pattern: tuple[str, str], op: tuple[str, str]) -> bool:
    """A wrapper path matches an operation segment by segment; a `{}` in the wrapper (a runtime value such as
    `${action}`) matches any one segment of the schema path, so `/amendments/{}/{}` covers `/amendments/{}/reject`."""
    if pattern[0] != op[0]:
        return False
    left, right = pattern[1].split("/"), op[1].split("/")
    return len(left) == len(right) and all(a == b or a == "{}" for a, b in zip(left, right))


def classify() -> dict[str, object]:
    ops = schema_operations()
    wrappers = wrapper_functions()
    used = used_names()
    rows = []
    for key in ops:
        functions = set().union(*(names for pattern, names in wrappers.items() if matches(pattern, key)))
        if functions and functions & used:
            status = "UI"
        elif key in INTENTIONALLY_UNCALLED:
            status = "INTENTIONAL"
        elif functions:
            status = "WRAPPER_ONLY"
        else:
            status = "NONE"
        rows.append({"method": key[0], "path": key[1], "status": status, "wrappers": sorted(functions),
                     "reason": INTENTIONALLY_UNCALLED.get(key)})
    counts = Counter(row["status"] for row in rows)
    in_scope = len(rows) - counts["INTENTIONAL"]
    return {
        "operations": len(rows),
        "counts": dict(counts),
        "ui_share_of_all": round(100 * counts["UI"] / len(rows), 1),
        "ui_share_of_in_scope": round(100 * counts["UI"] / in_scope, 1) if in_scope else 0.0,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list NONE / WRAPPER_ONLY / INTENTIONAL operations")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = classify()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    counts = result["counts"]
    print(f"v2 operations: {result['operations']}")
    for status in ("UI", "WRAPPER_ONLY", "NONE", "INTENTIONAL"):
        print(f"  {status:<13} {counts.get(status, 0)}")
    print(f"UI share of all operations:      {result['ui_share_of_all']}%")
    print(f"UI share of in-scope operations: {result['ui_share_of_in_scope']}%  (intentional exclusions removed)")
    if args.list:
        for row in result["rows"]:
            if row["status"] != "UI":
                extra = row["reason"] or ", ".join(row["wrappers"]) or ""
                print(f"  {row['status']:<13} {row['method']:<6} {row['path']}  {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
