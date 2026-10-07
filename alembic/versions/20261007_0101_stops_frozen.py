"""stops frozen: no stop anywhere in the product - every end is a point, stop structures are read-only history (Q160)

Owner: geo + trips + marketplace + bookings (ADR-0028 phase 4, Q160) - integrator A0a.
Content (DATA_MODEL.md §5):
  * History becomes points: every listing / proposal version / booking end that was a stop gets that stop's point and
    district (``*_point``, ``*_district_id``) - one-off; the proposal-version immutability trigger is disabled for that
    statement only (the place itself does not change, it is only written as a place).
    Open (not terminal) listings drop the stop id; saved searches naming a stop name its district instead; saved trip
    requests (ADR-0025 history) get the stop's district and point where they had none.
  * ``ck_<table>_<end>_end_one`` (0076: exactly one of stop / point) -> ``ck_<table>_<end>_point_required``: every end is
    a point. ``trg_<table>_no_new_stop`` (listings, proposal_versions, bookings, corridor_price_bands,
    trip_intent_versions): no row may gain a
    stop id or a legacy occurrence seq; old rows keep theirs as history and still change status. Saved searches name no
    stop at all (``ck_saved_searches_<end>_no_stop``).
  * ``corridor_stops``, ``route_version_stops``, ``trip_stop_occurrences``, ``trip_segment_resources``,
    ``booking_allocations``: any INSERT / UPDATE / DELETE is refused (``stops_retired``) - frozen history.
  * The ADR-0028 phase-1/2 parity triggers go: a legacy allocation is history, the road claim alone holds capacity.

Nothing is dropped (AGENTS §2). Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback.

Revision ID: 20261007_0101
Revises: 20261007_0100
Create Date: 2026-10-07 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007_0101"
down_revision: str = "20261007_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENDS: dict[str, tuple[str, str]] = {
    "listings": ("origin", "destination"),
    "proposal_versions": ("pickup", "dropoff"),
    "bookings": ("pickup", "dropoff"),
}
FROZEN_TABLES = (
    "corridor_stops", "route_version_stops", "trip_stop_occurrences", "trip_segment_resources", "booking_allocations",
)
RULE = "stops_retired"  # app.contracts.db_errors.CONSTRAINT_RULES
TERMINAL_LISTING_STATUSES = "('fulfilled', 'cancelled', 'expired')"


def _check(table: str, name: str, condition: str, *, valid: bool) -> None:
    op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE public.{table} ADD CONSTRAINT {name} CHECK ({condition}){'' if valid else ' NOT VALID'}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # 1. history as points (one-off). The 0076 "exactly one of stop / point" check goes first; proposal versions are
    #    immutable agreements, so their guard is off for this statement only (table owner, no superuser needed).
    for table, ends in ENDS.items():
        for end in ends:
            op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS ck_{table}_{end}_end_one")
    op.execute("ALTER TABLE public.proposal_versions DISABLE TRIGGER trg_proposal_versions_immutable")
    for table, ends in ENDS.items():
        for end in ends:
            op.execute(
                f"""
                UPDATE public.{table} t
                   SET {end}_point = s.point, {end}_district_id = s.geo_district_id
                  FROM public.corridor_stops s
                 WHERE s.id = t.{end}_stop_id AND t.{end}_point IS NULL
                """
            )
    op.execute("ALTER TABLE public.proposal_versions ENABLE TRIGGER trg_proposal_versions_immutable")
    # saved trip requests (ADR-0025, retired) are append-only history too: a stop end is read as its district and point
    op.execute("ALTER TABLE public.trip_intent_versions DISABLE TRIGGER trg_trip_intent_versions_append_only")
    for end in ("origin", "destination"):
        op.execute(
            f"""
            UPDATE public.trip_intent_versions v
               SET {end}_district_id = COALESCE(v.{end}_district_id, s.geo_district_id),
                   {end}_lat = COALESCE(v.{end}_lat, round(ST_Y(s.point)::numeric, 7)),
                   {end}_lng = COALESCE(v.{end}_lng, round(ST_X(s.point)::numeric, 7))
              FROM public.corridor_stops s
             WHERE s.id = v.{end}_stop_id AND (v.{end}_district_id IS NULL OR v.{end}_lat IS NULL)
            """
        )
    op.execute("ALTER TABLE public.trip_intent_versions ENABLE TRIGGER trg_trip_intent_versions_append_only")
    for end in ("origin", "destination"):
        op.execute(
            f"UPDATE public.listings SET {end}_stop_id = NULL "
            f"WHERE {end}_stop_id IS NOT NULL AND status NOT IN {TERMINAL_LISTING_STATUSES}"
        )
        op.execute(
            f"""
            UPDATE public.saved_searches ss
               SET {end}_district_id = s.geo_district_id, {end}_stop_id = NULL
              FROM public.corridor_stops s
             WHERE s.id = ss.{end}_stop_id
            """
        )

    # 2. every end is a point. No row may *gain* a stop id or a legacy seq - a trigger, not a CHECK, so the old rows
    #    keep theirs as history and still move through their own life (a NOT VALID CHECK would refuse their updates).
    for table, ends in ENDS.items():
        for end in ends:
            _check(table, f"ck_{table}_{end}_point_required", f"{end}_point IS NOT NULL", valid=True)
    for end in ("origin", "destination"):
        _check("saved_searches", f"ck_saved_searches_{end}_no_stop", f"{end}_stop_id IS NULL", valid=True)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.no_new_stop_reference() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            col TEXT;
            new_row JSONB := to_jsonb(NEW);
            old_row JSONB := CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) ELSE '{{}}'::jsonb END;
        BEGIN
            FOREACH col IN ARRAY TG_ARGV LOOP
                IF new_row ->> col IS NOT NULL AND (new_row -> col) IS DISTINCT FROM (old_row -> col) THEN
                    RAISE EXCEPTION '%.% may not be set: ELCHI has no stops (Q160)', TG_TABLE_NAME, col
                        USING ERRCODE = 'check_violation', CONSTRAINT = '{RULE}';
                END IF;
            END LOOP;
            RETURN NEW;
        END $$
        """
    )
    guarded = {
        "listings": ("origin_stop_id", "destination_stop_id"),
        "proposal_versions": ("pickup_stop_id", "dropoff_stop_id", "pickup_occurrence_seq", "dropoff_occurrence_seq"),
        "bookings": ("pickup_stop_id", "dropoff_stop_id", "pickup_occurrence_seq", "dropoff_occurrence_seq"),
        "corridor_price_bands": ("origin_stop_id", "destination_stop_id"),
        "trip_intent_versions": ("origin_stop_id", "destination_stop_id"),
    }
    for table, columns in guarded.items():
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_new_stop ON public.{table}")
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_new_stop BEFORE INSERT OR UPDATE ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.no_new_stop_reference({args})"
        )

    # 3. stop structures are read-only history
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.stops_retired_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is frozen history: ELCHI has no stops (Q160)', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation', CONSTRAINT = '{RULE}';
        END $$
        """
    )
    for table in FROZEN_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_stops_retired ON public.{table}")
        op.execute(
            f"CREATE TRIGGER trg_{table}_stops_retired BEFORE INSERT OR UPDATE OR DELETE ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.stops_retired_guard()"
        )

    # 4. the phase-1/2 dual-write proof: legacy allocations are frozen, the claim alone holds capacity
    op.execute("DROP TRIGGER IF EXISTS trg_booking_allocations_claim_parity ON public.booking_allocations")
    op.execute("DROP TRIGGER IF EXISTS trg_trip_capacity_claims_parity ON public.trip_capacity_claims")


def downgrade() -> None:
    """Dev/test only: unfreeze (the backfilled points stay - they are the same places)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in FROZEN_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_stops_retired ON public.{table}")
    op.execute("DROP FUNCTION IF EXISTS public.stops_retired_guard()")
    for table in ("listings", "proposal_versions", "bookings", "corridor_price_bands", "trip_intent_versions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_new_stop ON public.{table}")
    op.execute("DROP FUNCTION IF EXISTS public.no_new_stop_reference()")
    for table, ends in ENDS.items():
        for end in ends:
            op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS ck_{table}_{end}_point_required")
    for end in ("origin", "destination"):
        op.execute(f"ALTER TABLE public.saved_searches DROP CONSTRAINT IF EXISTS ck_saved_searches_{end}_no_stop")
