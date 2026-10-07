"""trips route positions: A->B positions along the confirmed road and interval capacity claims (ADR-0028 phase 1)

Owner: trips + marketplace + bookings (ADR-0028, Q159) - integrator A0a.
Phase 1 is *expand + dual write*: nothing here changes a decision. The stop/segment model still decides capacity,
ETA and matching; this migration adds the position model next to it and proves, at every commit, that the two agree.

Content (DATA_MODEL.md §5):
  * ``trips.route_start_m`` / ``route_end_m`` - the part of the confirmed road the trip drives, in metres from the
    road's start (``round(line_fraction * distance_m)``). Backfilled from the first/last stop occurrence.
  * ``proposal_versions.pickup_position_m`` / ``dropoff_position_m`` - written by new versions only: versions are
    immutable (0044), so open pre-0097 versions get their positions computed at accept.
  * ``bookings.pickup_position_m`` / ``dropoff_position_m`` - the agreed places projected on the booking's road; set
    once (NULL -> value), never changed. Backfilled from the point or, for legacy stop ends, the stop's point.
  * ``trip_capacity_claims`` - one active claim per booking: the interval ``[from_m, to_m)`` of road it occupies and
    the resources. Content immutable, ``active`` true -> false once (release contract, ADR-0017 §11), no delete.
    ``trip_capacity_claims_within_capacity``: at every point of the road the active claims fit the trip's capacity
    (checked at claim starts, under the trip row lock). Backfilled: one claim per booking with active allocations.
  * Dual-write proof (deferred): a booking has an active allocation <=> it has an active claim.
  * Q63 successor: the trip's road span and route version are locked once it has any claim.

Why the capacity trigger cannot refuse what the segment model accepted: a claim's interval lies inside the segments
its booking holds (or, for a place before the first / after the last stop, it is held on that end segment), so the
interval load at any point never exceeds the load of the segment containing it - and that is CHECKed <= capacity.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20261006_0097
Revises: 20261006_0096
Create Date: 2026-10-06 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261006_0097"
down_revision: str = "20261006_0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SPAN_LOCKED_RULE = "trip_stops_locked"  # same error as Q63 (app.contracts.db_errors)
CAPACITY_RULE = "trip_capacity_claims_exceeded"
POSITIONS_RULE = "booking_positions_set_once"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _add_check(table: str, name: str, condition: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition});
            END IF;
        END $$
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- columns ---------------------------------------------------------------------------------------------------
    op.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS route_start_m INTEGER")
    op.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS route_end_m INTEGER")
    _add_check(
        "trips",
        "ck_trips_route_span",
        "(route_start_m IS NULL) = (route_end_m IS NULL) AND (route_start_m IS NULL OR (route_start_m >= 0 AND route_start_m <= route_end_m))",
    )
    for table, prefix in (("proposal_versions", ""), ("bookings", "")):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {prefix}pickup_position_m INTEGER")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {prefix}dropoff_position_m INTEGER")
        _add_check(
            table,
            f"ck_{table}_positions",
            "(pickup_position_m IS NULL OR pickup_position_m >= 0) AND (dropoff_position_m IS NULL OR dropoff_position_m >= 0)",
        )
    for table in ("trips", "proposal_versions", "bookings"):
        for column in (
            ("route_start_m", "route_end_m") if table == "trips" else ("pickup_position_m", "dropoff_position_m")
        ):
            op.execute(
                f"COMMENT ON COLUMN {table}.{column} IS 'ADR-0028 (Q159): metres along the confirmed road from its start "
                f"(round(ST_LineLocatePoint * distance_m)). Not the *_route_offset_m lateral distance.'"
            )

    # --- trip_capacity_claims ----------------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trip_capacity_claims (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            trip_id BIGINT NOT NULL CONSTRAINT fk_trip_capacity_claims_trip_id REFERENCES trips (id),
            booking_id BIGINT NOT NULL CONSTRAINT fk_trip_capacity_claims_booking_id REFERENCES bookings (id),
            from_m INTEGER NOT NULL,
            to_m INTEGER NOT NULL,
            seats INTEGER NOT NULL DEFAULT 0,
            baggage_ml INTEGER NOT NULL DEFAULT 0,
            cargo_weight_g INTEGER NOT NULL DEFAULT 0,
            cargo_volume_ml INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT true,
            released_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_trip_capacity_claims_span CHECK (from_m >= 0 AND from_m < to_m),
            CONSTRAINT ck_trip_capacity_claims_amounts CHECK (
                seats >= 0 AND baggage_ml >= 0 AND cargo_weight_g >= 0 AND cargo_volume_ml >= 0
                AND seats + baggage_ml + cargo_weight_g + cargo_volume_ml > 0
            ),
            CONSTRAINT ck_trip_capacity_claims_released CHECK (active = (released_at IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_trip_capacity_claims_booking_active ON trip_capacity_claims (booking_id) "
        "WHERE active"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_trip_capacity_claims_trip_active ON trip_capacity_claims (trip_id, from_m) "
        "WHERE active"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trip_capacity_claims_booking ON trip_capacity_claims (booking_id, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trip_capacity_claims_trip ON trip_capacity_claims (trip_id)")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trip_capacity_claims_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            booking_trip BIGINT;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'trip_capacity_claims cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                SELECT trip_id INTO booking_trip FROM bookings WHERE id = NEW.booking_id;
                IF booking_trip IS DISTINCT FROM NEW.trip_id THEN
                    RAISE EXCEPTION 'claim trip % does not match booking trip %', NEW.trip_id, booking_trip
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NOT NEW.active THEN
                    RAISE EXCEPTION 'claims are created active' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.id, NEW.trip_id, NEW.booking_id, NEW.from_m, NEW.to_m, NEW.seats, NEW.baggage_ml,
                NEW.cargo_weight_g, NEW.cargo_volume_ml, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.trip_id, OLD.booking_id, OLD.from_m, OLD.to_m, OLD.seats, OLD.baggage_ml,
                OLD.cargo_weight_g, OLD.cargo_volume_ml, OLD.created_at) THEN
                RAISE EXCEPTION 'capacity claim content is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.active AND NOT OLD.active THEN
                RAISE EXCEPTION 'a released claim cannot be re-activated (release contract)'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NOT OLD.active AND NEW.released_at IS DISTINCT FROM OLD.released_at THEN
                RAISE EXCEPTION 'released claim is final' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    _trigger(
        "trg_trip_capacity_claims_guard",
        "trip_capacity_claims",
        "TRIGGER trg_trip_capacity_claims_guard BEFORE INSERT OR UPDATE OR DELETE ON trip_capacity_claims "
        "FOR EACH ROW EXECUTE FUNCTION trip_capacity_claims_guard()",
    )
    _trigger(
        "trg_trip_capacity_claims_no_truncate",
        "trip_capacity_claims",
        "TRIGGER trg_trip_capacity_claims_no_truncate BEFORE TRUNCATE ON trip_capacity_claims "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    # Capacity backstop. The peak of a sum of intervals is reached at some interval's start, so only the new claim's
    # start and the starts of active claims inside it are checked. The trip row lock serialises claimers on one trip
    # (the service already holds it - re-entrant; FOR NO KEY UPDATE, ADR-0017).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trip_capacity_claims_within_capacity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            cap RECORD;
            peak RECORD;
        BEGIN
            IF NOT NEW.active THEN
                RETURN NULL;
            END IF;
            SELECT seat_capacity, baggage_capacity_ml, cargo_capacity_weight_g, cargo_capacity_volume_ml INTO cap
              FROM trips WHERE id = NEW.trip_id FOR NO KEY UPDATE;
            SELECT b.at_m,
                   sum(c.seats) AS seats, sum(c.baggage_ml) AS baggage_ml,
                   sum(c.cargo_weight_g) AS cargo_weight_g, sum(c.cargo_volume_ml) AS cargo_volume_ml
              INTO peak
              FROM (
                  SELECT NEW.from_m AS at_m
                  UNION
                  SELECT o.from_m FROM trip_capacity_claims o
                   WHERE o.trip_id = NEW.trip_id AND o.active AND o.from_m > NEW.from_m AND o.from_m < NEW.to_m
              ) b
              JOIN trip_capacity_claims c
                ON c.trip_id = NEW.trip_id AND c.active AND c.from_m <= b.at_m AND b.at_m < c.to_m
             GROUP BY b.at_m
            HAVING sum(c.seats) > cap.seat_capacity
                OR sum(c.baggage_ml) > cap.baggage_capacity_ml
                OR sum(c.cargo_weight_g) > cap.cargo_capacity_weight_g
                OR sum(c.cargo_volume_ml) > cap.cargo_capacity_volume_ml
             ORDER BY b.at_m
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'trip % capacity exceeded at %m by active claims', NEW.trip_id, peak.at_m
                    USING ERRCODE = 'check_violation', CONSTRAINT = '{CAPACITY_RULE}';
            END IF;
            RETURN NULL;
        END $$
        """
    )
    _trigger(
        "trg_trip_capacity_claims_within_capacity",
        "trip_capacity_claims",
        "TRIGGER trg_trip_capacity_claims_within_capacity AFTER INSERT ON trip_capacity_claims "
        "FOR EACH ROW EXECUTE FUNCTION trip_capacity_claims_within_capacity()",
    )

    # --- bookings: positions are written once ----------------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION bookings_positions_set_once() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.pickup_position_m IS NOT NULL AND NEW.pickup_position_m IS DISTINCT FROM OLD.pickup_position_m)
               OR (OLD.dropoff_position_m IS NOT NULL AND NEW.dropoff_position_m IS DISTINCT FROM OLD.dropoff_position_m)
            THEN
                RAISE EXCEPTION 'booking route positions are written once (ADR-0028)'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{POSITIONS_RULE}';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    _trigger(
        "trg_bookings_positions_set_once",
        "bookings",
        "TRIGGER trg_bookings_positions_set_once BEFORE UPDATE OF pickup_position_m, dropoff_position_m ON bookings "
        "FOR EACH ROW EXECUTE FUNCTION bookings_positions_set_once()",
    )

    # --- Q63 successor: the road span is locked once the trip has a claim -------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trips_route_span_locked() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.route_start_m IS NULL AND OLD.route_end_m IS NULL
               AND NEW.route_version_id IS NOT DISTINCT FROM OLD.route_version_id THEN
                RETURN NEW;  -- the span is being written for the first time
            END IF;
            IF (NEW.route_version_id, NEW.route_start_m, NEW.route_end_m)
               IS DISTINCT FROM (OLD.route_version_id, OLD.route_start_m, OLD.route_end_m)
               AND EXISTS (SELECT 1 FROM trip_capacity_claims c WHERE c.trip_id = OLD.id) THEN
                RAISE EXCEPTION 'trip % road span is locked: the trip has capacity claims', OLD.id
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{SPAN_LOCKED_RULE}';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    _trigger(
        "trg_trips_route_span_locked",
        "trips",
        "TRIGGER trg_trips_route_span_locked BEFORE UPDATE OF route_version_id, route_start_m, route_end_m ON trips "
        "FOR EACH ROW EXECUTE FUNCTION trips_route_span_locked()",
    )

    # --- backfill (idempotent: only NULL positions, only bookings without an active claim) --------------------------
    op.execute(
        """
        UPDATE trips t
           SET route_start_m = span.start_m, route_end_m = span.end_m
          FROM (
              SELECT o.trip_id,
                     round(min(rvs.line_fraction) * rv.distance_m)::int AS start_m,
                     round(max(rvs.line_fraction) * rv.distance_m)::int AS end_m
                FROM trip_stop_occurrences o
                JOIN trips tt ON tt.id = o.trip_id
                JOIN route_versions rv ON rv.id = tt.route_version_id
                JOIN route_version_stops rvs
                  ON rvs.route_version_id = tt.route_version_id AND rvs.seq = o.route_version_stop_seq
               GROUP BY o.trip_id, rv.distance_m
          ) span
         WHERE t.id = span.trip_id AND t.route_start_m IS NULL
        """
    )
    # A marked point is projected; a legacy stop end takes the road's *stored* fraction of the trip occurrence it was
    # agreed at - the segment model's own boundary, so every claim stays inside the segments its booking holds.
    for end in ("pickup", "dropoff"):
        op.execute(
            f"""
            UPDATE bookings b
               SET {end}_position_m = round(CASE
                       WHEN b.{end}_point IS NOT NULL THEN ST_LineLocatePoint(rv.geometry, b.{end}_point)
                       ELSE (SELECT rvs.line_fraction
                               FROM trip_stop_occurrences o
                               JOIN route_version_stops rvs
                                 ON rvs.route_version_id = rv.id AND rvs.seq = o.route_version_stop_seq
                              WHERE o.trip_id = b.trip_id AND o.seq = b.{end}_occurrence_seq)
                   END * rv.distance_m)::int
              FROM route_versions rv
             WHERE rv.id = b.route_version_id AND b.{end}_position_m IS NULL
            """
        )
    op.execute(
        """
        INSERT INTO trip_capacity_claims
            (trip_id, booking_id, from_m, to_m, seats, baggage_ml, cargo_weight_g, cargo_volume_ml, active, created_at)
        SELECT b.trip_id, b.id, b.pickup_position_m, GREATEST(b.dropoff_position_m, b.pickup_position_m + 1),
               a.seats, a.baggage_ml, a.cargo_weight_g, a.cargo_volume_ml, true, a.created_at
          FROM bookings b
          JOIN LATERAL (
              SELECT seats, baggage_ml, cargo_weight_g, cargo_volume_ml, created_at
                FROM booking_allocations
               WHERE booking_id = b.id AND active
               ORDER BY segment_from_seq
               LIMIT 1
          ) a ON true
         WHERE b.pickup_position_m IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM trip_capacity_claims c WHERE c.booking_id = b.id AND c.active)
         ORDER BY b.trip_id, b.id
        """
    )

    # --- dual-write proof: active allocation <=> active claim, per booking, at commit ---------------------------------
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
    op.execute("DROP TRIGGER IF EXISTS trg_booking_allocations_claim_parity ON booking_allocations")
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_booking_allocations_claim_parity AFTER INSERT OR UPDATE OF active "
        "ON booking_allocations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION trip_capacity_claims_parity()"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_trip_capacity_claims_parity ON trip_capacity_claims")
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_trip_capacity_claims_parity AFTER INSERT OR UPDATE OF active "
        "ON trip_capacity_claims DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION trip_capacity_claims_parity()"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_booking_allocations_claim_parity ON booking_allocations")
    op.execute("DROP TRIGGER IF EXISTS trg_trips_route_span_locked ON trips")
    op.execute("DROP TRIGGER IF EXISTS trg_bookings_positions_set_once ON bookings")
    op.execute("DROP TABLE IF EXISTS trip_capacity_claims")
    op.execute("DROP FUNCTION IF EXISTS trip_capacity_claims_parity()")
    op.execute("DROP FUNCTION IF EXISTS trip_capacity_claims_within_capacity()")
    op.execute("DROP FUNCTION IF EXISTS trip_capacity_claims_guard()")
    op.execute("DROP FUNCTION IF EXISTS trips_route_span_locked()")
    op.execute("DROP FUNCTION IF EXISTS bookings_positions_set_once()")
    for table in ("bookings", "proposal_versions"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_positions")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS dropoff_position_m")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS pickup_position_m")
    op.execute("ALTER TABLE trips DROP CONSTRAINT IF EXISTS ck_trips_route_span")
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS route_end_m")
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS route_start_m")
