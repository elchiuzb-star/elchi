"""legacy naive timestamps -> timestamptz

Owner: A10b (wave 5) - Q9, DATA_MODEL §3 ("Naive timestamp ustunlar"), AGENTS §6 (time), spec §18.1.

Eleven v1 columns are ``timestamp without time zone``:

    orders.published_at, accepted_at, picked_up_at, in_transit_at, delivered_at, confirmed_at, cancelled_at
    disputes.resolved_at, driver_documents.reviewed_at, order_offers.shown_at, order_offers.responded_at

**The conversion rule is proven, not assumed.** Every v1 writer stores an aware UTC value
(``datetime.now(timezone.utc)``, see ``app/services/*``), the API container and both PostgreSQL stacks run with
``TimeZone=UTC`` (``docker-compose.prod.yml``, ``docker-compose.test.yml``), so the stored wall clock is UTC. That
claim is *verified against the actual rows* before anything is altered: each of these columns sits in a row whose
``created_at``/``updated_at`` are already ``timestamptz``, written by the same transaction, so a lifecycle value
read as UTC must fall inside ``[created_at - 1h, updated_at + 1h]``. Reading a UTC+5 value as UTC (or the reverse)
moves it five hours and leaves that window. If any row fails the check the migration **stops** with counts only
(no timestamps, no PII) - a forward fix and a decision, never a silent cast (Q29 style, spec §18.3).
``scripts/legacy_timestamp_audit.py`` runs the same check read-only on any database before a deploy.

Conversion: ``SET LOCAL TimeZone = 'UTC'`` + ``ALTER COLUMN ... TYPE timestamptz`` **without** a ``USING`` clause.
The zone is pinned by this transaction (never the ambient session), and PostgreSQL >= 12 can then skip the table
rewrite, so the ACCESS EXCLUSIVE lock is short. A ``USING`` expression would force a full rewrite for the same
result. No index or constraint uses these columns (checked on 0065's schema).

Dependent views: 0065's ``legacy_parcel_orders_v`` / ``legacy_disputes_v`` select these columns, and PostgreSQL
refuses to alter a column a view depends on. The migration captures the *current* definition, comment and INSTEAD
OF triggers of those views, drops them, alters, and recreates them exactly as they were - so the projection cannot
drift from 0065 through a hand-copied SQL text.

v1 compatibility (AGENTS §2: the v1 response shape does not change): these columns are serialized by v1 handlers
through ``app.utils.legacy_time.v1_naive``, which keeps the historical offset-free ISO string. The database type
changes, the Android wire format does not.

Rules: idempotent (already-converted columns are skipped, second run is a no-op); do not change the revision id,
file name or down_revision; single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260916_0066
Revises: 20260916_0065
Create Date: 2026-09-17 07:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0066"
down_revision: str = "20260916_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_NAIVE_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": (
        "published_at", "accepted_at", "picked_up_at", "in_transit_at", "delivered_at", "confirmed_at",
        "cancelled_at",
    ),
    "disputes": ("resolved_at",),
    "driver_documents": ("reviewed_at",),
    "order_offers": ("shown_at", "responded_at"),
}
# Clock skew plus the gap between "row created" and "commit"; a zone error is 5 hours, 300x larger.
TOLERANCE = "1 hour"


def _naive_columns(bind) -> list[tuple[str, str]]:  # noqa: ANN001 - alembic connection
    found: list[tuple[str, str]] = []
    for table, columns in LEGACY_NAIVE_COLUMNS.items():
        for column in columns:
            row = bind.exec_driver_sql(
                "SELECT data_type FROM information_schema.columns "
                f"WHERE table_schema = 'public' AND table_name = '{table}' AND column_name = '{column}'"
            ).fetchone()
            if row is not None and row[0] == "timestamp without time zone":
                found.append((table, column))
    return found


def _assert_utc_semantics(bind, table: str, column: str) -> None:  # noqa: ANN001
    """Q9 proof for one column: every stored value, read as UTC, lies inside its own row's lifetime."""
    total, mismatched = bind.exec_driver_sql(
        f"""
        SELECT count({column}) AS non_null,
               count(*) FILTER (
                   WHERE {column} IS NOT NULL
                     AND ({column} AT TIME ZONE 'UTC') NOT BETWEEN created_at - INTERVAL '{TOLERANCE}'
                                                               AND updated_at + INTERVAL '{TOLERANCE}'
               ) AS mismatched
        FROM public.{table}
        """
    ).fetchone()
    if mismatched:
        raise RuntimeError(
            f"0066 refuses to convert public.{table}.{column}: {mismatched} of {total} values do not read as UTC "
            "inside their own row's created_at/updated_at window. The zone semantics of this column are not "
            "proven - run scripts/legacy_timestamp_audit.py, decide the rule with the owner and fix forward. "
            "Nothing was altered."
        )


def _capture_views(bind, tables: set[str]) -> list[dict[str, object]]:  # noqa: ANN001
    """Definition, comment and INSTEAD OF triggers of every view that depends on ``tables`` (0065's projection)."""
    if not tables:
        return []
    names = ", ".join(f"'{table}'" for table in sorted(tables))
    rows = bind.exec_driver_sql(
        f"""
        SELECT DISTINCT v.oid, v.relname
        FROM pg_class v
        JOIN pg_namespace n ON n.oid = v.relnamespace AND n.nspname = 'public'
        JOIN pg_depend d ON d.refobjid = v.oid AND d.classid = 'pg_rewrite'::regclass
        JOIN pg_rewrite r ON r.oid = d.objid AND r.ev_class = v.oid
        JOIN pg_depend dep ON dep.objid = r.oid AND dep.classid = 'pg_rewrite'::regclass
        JOIN pg_class t ON t.oid = dep.refobjid AND t.relname IN ({names})
        WHERE v.relkind = 'v'
        ORDER BY v.relname
        """
    ).fetchall()
    captured: list[dict[str, object]] = []
    for oid, name in rows:
        definition = bind.exec_driver_sql(f"SELECT pg_get_viewdef({oid}, true)").fetchone()[0]
        comment = bind.exec_driver_sql(f"SELECT obj_description({oid}, 'pg_class')").fetchone()[0]
        triggers = [
            row[0]
            for row in bind.exec_driver_sql(
                f"SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t WHERE t.tgrelid = {oid} AND NOT t.tgisinternal"
            ).fetchall()
        ]
        captured.append({"name": name, "definition": definition, "comment": comment, "triggers": triggers})
    return captured


def _restore_views(captured: list[dict[str, object]]) -> None:
    for view in captured:
        op.execute(f"CREATE OR REPLACE VIEW public.{view['name']} AS {view['definition']}")
        comment = view["comment"]
        if comment:
            escaped = str(comment).replace("'", "''")
            op.execute(f"COMMENT ON VIEW public.{view['name']} IS '{escaped}'")
        for definition in view["triggers"]:  # type: ignore[union-attr]
            op.execute(str(definition))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    pending = _naive_columns(bind)
    if not pending:
        return  # already converted: second run is a no-op

    for table, column in pending:
        _assert_utc_semantics(bind, table, column)

    captured = _capture_views(bind, {table for table, _ in pending})
    for view in captured:
        op.execute(f"DROP VIEW IF EXISTS public.{view['name']}")

    # The zone is pinned here, so the result cannot depend on the ambient session setting.
    op.execute("SET LOCAL TimeZone = 'UTC'")
    for table, column in pending:
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN {column} TYPE TIMESTAMPTZ")

    _restore_views(captured)


def downgrade() -> None:
    """Dev/test only (ADR-0016): back to naive UTC wall clock, same instants, no row is lost."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    converted = [
        (table, column)
        for table, columns in LEGACY_NAIVE_COLUMNS.items()
        for column in columns
        if (
            row := bind.exec_driver_sql(
                "SELECT data_type FROM information_schema.columns "
                f"WHERE table_schema = 'public' AND table_name = '{table}' AND column_name = '{column}'"
            ).fetchone()
        )
        is not None
        and row[0] == "timestamp with time zone"
    ]
    if not converted:
        return
    captured = _capture_views(bind, {table for table, _ in converted})
    for view in captured:
        op.execute(f"DROP VIEW IF EXISTS public.{view['name']}")
    op.execute("SET LOCAL TimeZone = 'UTC'")
    for table, column in converted:
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN {column} TYPE TIMESTAMP")
    _restore_views(captured)
