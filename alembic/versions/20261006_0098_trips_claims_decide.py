"""trips claims decide: road claims are the capacity decision, legacy segment allocations stay history (ADR-0028 phase 2)

Owner: trips + bookings (ADR-0028, Q159) - integrator A0a.
Phase 2 switches the capacity decision to the road claims (``trip_capacity_claims``). A new booking gets a claim only:
two places inside one legacy segment may share a seat one after the other, which the segment counters cannot express.
Content (DATA_MODEL.md §5):
  * ``trip_capacity_claims_parity()`` - from ``active allocation <=> active claim`` to ``active allocation => active
    claim``: a booking made before phase 2 still releases both together; a new booking has no allocation.
  * Q63 triggers of 0054 (``trip_stop_occurrences_stops_locked``, ``trip_segment_resources_stops_locked``) also count
    road claims: a trip any booking ever claimed keeps its stops, whether or not a legacy allocation exists.

Rules: idempotent (CREATE OR REPLACE); single head; downgrade() is a dev/test tool, not a rollback (ADR-0016).

Revision ID: 20261006_0098
Revises: 20261006_0097
Create Date: 2026-10-06 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261006_0098"
down_revision: str = "20261006_0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STOPS_LOCKED_RULE = "trip_stops_locked"  # app.contracts.db_errors.CONSTRAINT_RULES


def _stops_locked_function(name: str, table_check: str, what: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION {name}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            locked_trip BIGINT;
            old_trip BIGINT;
            new_trip BIGINT;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF {table_check} THEN
                    RETURN NEW;
                END IF;
                old_trip := OLD.trip_id;
                new_trip := NEW.trip_id;
            ELSIF TG_OP = 'INSERT' THEN
                new_trip := NEW.trip_id;
            ELSE
                old_trip := OLD.trip_id;
            END IF;
            SELECT t.trip_id INTO locked_trip FROM (
                SELECT a.trip_id FROM booking_allocations a WHERE a.trip_id = old_trip OR a.trip_id = new_trip
                UNION ALL
                SELECT c.trip_id FROM trip_capacity_claims c WHERE c.trip_id = old_trip OR c.trip_id = new_trip
            ) t
            LIMIT 1;
            IF locked_trip IS NOT NULL THEN
                RAISE EXCEPTION 'trip % {what} are locked: the trip has bookings', locked_trip
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{STOPS_LOCKED_RULE}';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END $$
        """


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trip_capacity_claims_parity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM booking_allocations WHERE booking_id = NEW.booking_id AND active)
               AND NOT EXISTS (SELECT 1 FROM trip_capacity_claims WHERE booking_id = NEW.booking_id AND active) THEN
                RAISE EXCEPTION 'booking % holds a legacy allocation without an active road claim (ADR-0028)',
                    NEW.booking_id USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        _stops_locked_function(
            "trip_stop_occurrences_stops_locked",
            "(NEW.trip_id, NEW.seq, NEW.stop_id, NEW.route_version_stop_seq) "
            "IS NOT DISTINCT FROM (OLD.trip_id, OLD.seq, OLD.stop_id, OLD.route_version_stop_seq)",
            "stops",
        )
    )
    op.execute(
        _stops_locked_function(
            "trip_segment_resources_stops_locked",
            "(NEW.trip_id, NEW.from_seq, NEW.to_seq) IS NOT DISTINCT FROM (OLD.trip_id, OLD.from_seq, OLD.to_seq)",
            "segments",
        )
    )


def downgrade() -> None:
    """Dev/test only: phase-1 parity again (the 0054 functions keep counting claims - harmless without bookings)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trip_capacity_claims_parity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            has_allocation BOOLEAN;
            has_claim BOOLEAN;
        BEGIN
            has_allocation := EXISTS (SELECT 1 FROM booking_allocations WHERE booking_id = NEW.booking_id AND active);
            has_claim := EXISTS (SELECT 1 FROM trip_capacity_claims WHERE booking_id = NEW.booking_id AND active);
            IF has_allocation IS DISTINCT FROM has_claim THEN
                RAISE EXCEPTION 'booking % capacity models disagree: active allocation %, active claim % (ADR-0028 dual write)',
                    NEW.booking_id, has_allocation, has_claim USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$
        """
    )
