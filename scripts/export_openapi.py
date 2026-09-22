"""Export the v2 OpenAPI schema for the client type generation (ADR-0010 §4, spec §12).

    python scripts/export_openapi.py                       # -> mobile-app/src/api/generated/openapi-v2.json
    python scripts/export_openapi.py --out path.json       # somewhere else
    python scripts/export_openapi.py --check               # exit 3 if the file on disk is stale (CI)
    python scripts/export_openapi.py --include-v1          # the whole schema, for inspection only

Only ``/api/v2`` paths (plus the prefix-less health routes when ``--include-health`` is given) are exported: v1
clients are frozen and keep their hand-written types, and no new hand-written DTO is added anywhere (ADR-0010 §5).

The export imports the application, so it needs the app's environment (``ELCHI_ENVIRONMENT`` and friends) but no
database connection: FastAPI builds the schema from the routers alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "mobile-app" / "src" / "api" / "generated" / "openapi-v2.json"
V2_PREFIX = "/api/v2"
HEALTH_PATHS = ("/health/live", "/health/ready")


def build_schema(*, include_v1: bool = False, include_health: bool = False) -> dict:
    """The application's OpenAPI document, filtered to the paths clients may generate types from."""
    sys.path.insert(0, str(REPO_ROOT))
    from app.main import app  # imported late: it configures logging and ports

    schema = app.openapi()
    if include_v1:
        return schema
    kept = {
        path: item
        for path, item in schema["paths"].items()
        if path.startswith(V2_PREFIX) or (include_health and path in HEALTH_PATHS)
    }
    filtered = {key: value for key, value in schema.items() if key != "paths"}
    filtered["paths"] = dict(sorted(kept.items()))
    return filtered


def render(schema: dict) -> str:
    """Stable text: sorted keys and a trailing newline, so ``--check`` compares content, not formatting."""
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/export_openapi.py")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"output file (default: {DEFAULT_OUT})")
    parser.add_argument("--check", action="store_true", help="do not write; exit 3 when the file is stale")
    parser.add_argument("--include-v1", action="store_true", help="export the whole schema (inspection only)")
    parser.add_argument("--include-health", action="store_true", help="also export /health/live and /health/ready")
    args = parser.parse_args(argv)

    schema = build_schema(include_v1=args.include_v1, include_health=args.include_health)
    payload = render(schema)
    out = Path(args.out)
    operations = sum(
        1
        for item in schema["paths"].values()
        for method in item
        if method in ("get", "post", "put", "patch", "delete")
    )
    if args.check:
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        if current != payload:
            print(f"export_openapi: {out} is stale; run python scripts/export_openapi.py", file=sys.stderr)
            return 3
        print(f"export_openapi: {out} is up to date ({operations} operations)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")
    print(f"export_openapi: wrote {out} ({operations} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
