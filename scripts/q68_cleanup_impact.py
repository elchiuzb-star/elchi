"""BR L4: read-only preview of the data migration 0054's Q68 cleanup would rewrite.

Stdlib only (runs on the deploy host). The allowed values are read from the migration file itself (its frozen
PARCEL_TYPES / AMENITIES), so the preview cannot drift from the migration. The WHERE clauses mirror 0054:

* ``parcel_rows``: parcel_listing_details rows the UPDATE touches (case/space normalisation included);
* ``parcel_type_to_other``: rows whose parcel_type becomes ``'other'``;
* ``accepted_elements_to_other``: accepted_parcel_types elements that become ``'other'``;
* ``amenity_rows``: passenger_listing_details rows whose amenities are cleaned;
* ``dropped_amenity_elements``: unknown amenity elements that are dropped.

Usage (scripts/deploy.sh, before ``migrate``)::

    psql ... -c "$(python3 scripts/q68_cleanup_impact.py --print-sql)"
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Sequence
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260915_0054_marketplace_trips_hardening.py"
_SAFE_VALUE = re.compile(r"^[a-z][a-z0-9_]*$")


def frozen_values(path: Path = MIGRATION) -> tuple[tuple[str, ...], tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PARCEL_TYPES", "AMENITIES"):
                found[node.targets[0].id] = tuple(ast.literal_eval(node.value))
    if set(found) != {"PARCEL_TYPES", "AMENITIES"}:
        raise SystemExit(f"q68_cleanup_impact: PARCEL_TYPES/AMENITIES not found in {path}")
    return found["PARCEL_TYPES"], found["AMENITIES"]


def _literals(values: Sequence[str]) -> list[str]:
    if not values or any(not isinstance(v, str) or not _SAFE_VALUE.match(v) for v in values):
        raise ValueError(f"unexpected enum literal in {values!r}")
    return [f"'{v}'" for v in values]


def impact_sql(parcel_types: Sequence[str], amenities: Sequence[str]) -> str:
    """One SELECT returning a single ``key=value ...`` text column. Reads only; unqualified table names."""
    p_list = ", ".join(_literals(parcel_types))
    a_list = ", ".join(_literals(amenities))
    p_in, p_arr = f"({p_list})", f"ARRAY[{p_list}]::text[]"
    a_in, a_arr = f"({a_list})", f"ARRAY[{a_list}]::text[]"
    parcel_where = f"(parcel_type IS NOT NULL AND parcel_type NOT IN {p_in}) OR NOT (accepted_parcel_types <@ {p_arr})"
    amenity_where = f"NOT (amenities <@ {a_arr})"
    return (
        "SELECT format('parcel_rows=%s parcel_type_to_other=%s accepted_elements_to_other=%s "
        "amenity_rows=%s dropped_amenity_elements=%s', "
        f"(SELECT count(*) FROM parcel_listing_details WHERE {parcel_where}), "
        f"(SELECT count(*) FROM parcel_listing_details WHERE parcel_type IS NOT NULL AND lower(btrim(parcel_type)) NOT IN {p_in}), "
        f"(SELECT count(*) FROM parcel_listing_details d, unnest(d.accepted_parcel_types) AS u(item) "
        f"WHERE NOT (d.accepted_parcel_types <@ {p_arr}) AND lower(btrim(u.item)) NOT IN {p_in}), "
        f"(SELECT count(*) FROM passenger_listing_details WHERE {amenity_where}), "
        f"(SELECT count(*) FROM passenger_listing_details d, unnest(d.amenities) AS u(item) "
        f"WHERE NOT (d.amenities <@ {a_arr}) AND lower(btrim(u.item)) NOT IN {a_in}))"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 scripts/q68_cleanup_impact.py")
    parser.add_argument("--print-sql", action="store_true", help="print the read-only psql command text")
    args = parser.parse_args(argv)
    if not args.print_sql:
        parser.print_help()
        return 2
    print("BEGIN READ ONLY; " + impact_sql(*frozen_values()) + "; COMMIT;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
