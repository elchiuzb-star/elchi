"""Q9 evidence: what do the naive legacy timestamps actually mean? (A10b, wave 5; migration 0066.)

Eleven v1 columns are ``timestamp without time zone``::

    orders.published_at, accepted_at, picked_up_at, in_transit_at, delivered_at, confirmed_at, cancelled_at
    disputes.resolved_at, driver_documents.reviewed_at, order_offers.shown_at, order_offers.responded_at

Converting them to ``timestamptz`` needs a *proven* rule, not an assumption: ``ALTER TABLE ... USING`` without an
explicit zone silently adopts the session's TimeZone, which would shift every historical instant if the writer had
used another zone. This script proves (or refuses) the rule from the data itself.

Method: each of these columns lives in a row that also has ``created_at``/``updated_at`` - and those two are
``timestamptz``, written by the same transaction (server default ``now()`` / SQLAlchemy ``onupdate``). A lifecycle
timestamp is therefore bounded: it cannot be earlier than the row was created nor later than it was last updated
(plus a small tolerance for clock and flush ordering). Interpreting the naive value in the *wrong* zone moves it by
the zone offset (Asia/Tashkent is UTC+5), which pushes it outside that window for practically every row. So for
each column the script counts, per candidate zone, how many stored values land inside the row's own window:

    verdict "utc"        - UTC fits every row and Asia/Tashkent does not (the conversion rule is proven);
    verdict "tashkent"   - the mirror case;
    verdict "mixed"      - both or neither fit: the semantics differ per row -> conversion stays BLOCKED;
    verdict "no_data"    - the column has no value at all here (a fresh or empty database proves nothing).

The script only reads (SELECT). Point it at a copy, a staging restore or - by the operations owner, with a
read-only role - at production; it prints counts, never timestamps of a particular user.

Usage::

    py scripts/legacy_timestamp_audit.py --url postgresql://user@host/db [--zone Asia/Tashkent] [--json]
    ELCHI_DATABASE_URL=... py scripts/legacy_timestamp_audit.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass

import psycopg

# column -> the aware columns bounding it in the same row
LEGACY_NAIVE_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": ("published_at", "accepted_at", "picked_up_at", "in_transit_at", "delivered_at", "confirmed_at",
               "cancelled_at"),
    "disputes": ("resolved_at",),
    "driver_documents": ("reviewed_at",),
    "order_offers": ("shown_at", "responded_at"),
}
BOUND_LOW, BOUND_HIGH = "created_at", "updated_at"
# Clock skew and the gap between "row created" and "flush committed"; generous on purpose - a 5 hour zone error
# is 300 times larger, so the test still separates the two hypotheses.
TOLERANCE = "1 hour"
UTC = "UTC"


@dataclass(frozen=True)
class ColumnAudit:
    table: str
    column: str
    rows: int
    non_null: int
    fits_utc: int
    fits_zone: int
    zone: str
    verdict: str

    @property
    def blocking(self) -> bool:
        return self.verdict == "mixed"


def audit_column(conn: psycopg.Connection, table: str, column: str, zone: str) -> ColumnAudit:
    row = conn.execute(
        f"""
        SELECT count(*) AS rows,
               count({column}) AS non_null,
               count(*) FILTER (
                   WHERE {column} IS NOT NULL
                     AND ({column} AT TIME ZONE %(utc)s) BETWEEN {BOUND_LOW} - INTERVAL %(tol)s
                                                             AND {BOUND_HIGH} + INTERVAL %(tol)s
               ) AS fits_utc,
               count(*) FILTER (
                   WHERE {column} IS NOT NULL
                     AND ({column} AT TIME ZONE %(zone)s) BETWEEN {BOUND_LOW} - INTERVAL %(tol)s
                                                              AND {BOUND_HIGH} + INTERVAL %(tol)s
               ) AS fits_zone
        FROM public.{table}
        """,
        {"utc": UTC, "zone": zone, "tol": TOLERANCE},
    ).fetchone()
    rows, non_null, fits_utc, fits_zone = row
    if non_null == 0:
        verdict = "no_data"
    elif fits_utc == non_null and fits_zone < non_null:
        verdict = "utc"
    elif fits_zone == non_null and fits_utc < non_null:
        verdict = "tashkent"
    else:
        verdict = "mixed"
    return ColumnAudit(table=table, column=column, rows=rows, non_null=non_null, fits_utc=fits_utc,
                       fits_zone=fits_zone, zone=zone, verdict=verdict)


def audit(conn: psycopg.Connection, zone: str) -> list[ColumnAudit]:
    results: list[ColumnAudit] = []
    for table, columns in LEGACY_NAIVE_COLUMNS.items():
        if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None:
            continue
        for column in columns:
            data_type = conn.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
                (table, column),
            ).fetchone()
            if data_type is None:
                continue
            if data_type[0] != "timestamp without time zone":
                results.append(ColumnAudit(table, column, 0, 0, 0, 0, zone, "already_typed"))
                continue
            results.append(audit_column(conn, table, column, zone))
    return results


def summary(results: list[ColumnAudit]) -> str:
    verdicts = {result.verdict for result in results}
    if "mixed" in verdicts:
        return "BLOCKED: at least one column has mixed or unexplained zone semantics; 0066 must not convert it."
    if verdicts <= {"already_typed"}:
        return "DONE: every legacy column is already timestamptz."
    if "utc" in verdicts and "tashkent" not in verdicts:
        return "UTC: every column with data is consistent with values stored as UTC wall clock."
    if "tashkent" in verdicts and "utc" not in verdicts:
        return "LOCAL: values look like Asia/Tashkent wall clock; 0066 must convert with that zone."
    return "NO EVIDENCE: no column carries data here; run this against a database that has legacy rows."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Q9 legacy timestamp semantics audit (read-only).")
    parser.add_argument("--url", default=os.environ.get("ELCHI_DATABASE_URL", ""), help="libpq URL (or ELCHI_DATABASE_URL)")
    parser.add_argument("--zone", default="Asia/Tashkent", help="the local zone to test against UTC")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.url:
        parser.error("no database URL: pass --url or set ELCHI_DATABASE_URL")

    url = args.url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute("SET default_transaction_read_only = on")
        results = audit(conn, args.zone)
        server_zone = conn.execute("SHOW timezone").fetchone()[0]

    if args.json:
        print(json.dumps({"server_timezone": server_zone, "summary": summary(results),
                          "columns": [asdict(result) for result in results]}, indent=2))
    else:
        print(f"server TimeZone: {server_zone}")
        print(f"{'table.column':<34}{'rows':>8}{'set':>8}{'fits UTC':>10}{'fits zone':>11}  verdict")
        for result in results:
            name = f"{result.table}.{result.column}"
            print(f"{name:<34}{result.rows:>8}{result.non_null:>8}{result.fits_utc:>10}{result.fits_zone:>11}"
                  f"  {result.verdict}")
        print(f"\n{summary(results)}")
    return 1 if any(result.blocking for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
