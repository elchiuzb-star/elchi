"""marketplace trips hardening

Owner: A1 (wave 2.1) - modules `trips`, `marketplace`.
Content (DATA_MODEL.md §5, WAVE1_CARDS "Wave 2.1"):
  * Q63: trip_stop_occurrences / trip_segment_resources rows of a trip cannot be inserted, updated (seq/stop/
    route columns) or deleted once ANY booking_allocations row exists for the trip (active or released);
    RAISE ... USING ERRCODE = 'restrict_violation', CONSTRAINT = 'trip_stops_locked' (web.py maps it to
    409 TRIP_STOPS_LOCKED). Schedule columns (planned_arrival_at, dwell, eta) and capacity counters stay writable.
  * capacity counter trigger: trip_segment_resources *_used columns change only together with an allocation
    change in the same transaction (complements the 0048 deferred equality check, which fires only when an
    allocation row changes): a deferred constraint trigger on the segment row re-checks at COMMIT that the
    segment's counters equal the sum of its active allocations (check_violation -> 409 INTEGRITY_CONFLICT).
  * Q68: CHECK constraints on parcel_listing_details.parcel_type, parcel_listing_details.accepted_parcel_types,
    passenger_listing_details.amenities (values: frozen copies of app.contracts.enums.PARCEL_TYPE_VALUES /
    AMENITY_VALUES, asserted by tests/modules/marketplace/test_migration_0054_literals.py);
    existing free-text rows -> add NOT VALID, normalise/clean in a data step (counts in NOTICEs), then VALIDATE.
    Cleaning: value lower/trim; parcel_type outside the enum -> 'other'; accepted_parcel_types elements outside
    the enum -> 'other' (never an empty list, which would widen the offer to every type); unknown amenities are
    dropped (informational only); duplicates removed, order kept.
  * trip-offer parcel proposals carry the receiver contact (card item 7): proposal_versions.receiver_name /
    receiver_phone (both or neither); shown only to the proposing client (Q43/Q44).
FK / object dependencies: 0048 (booking_allocations), 0038 (trips, occurrences, segments), 0039 (listing details),
0040 (proposal_versions).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0054
Revises: 20260915_0053
Create Date: 2026-09-15 00:54:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0054"
down_revision: str = "20260915_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app.contracts.enums values (a migration must not change when the code changes).
PARCEL_TYPES = ("documents", "box", "bag", "electronics", "clothing", "other")
AMENITIES = ("air_conditioning", "phone_charger", "no_smoking", "pets_allowed", "large_trunk", "wifi")
STOPS_LOCKED_RULE = "trip_stops_locked"  # app.contracts.db_errors.CONSTRAINT_RULES


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _text_array(values: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{value}'" for value in values) + "]::text[]"


def _add_check_not_valid(table: str, name: str, expression: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- Q63: stops of a trip with allocations are locked -----------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trip_stop_occurrences_stops_locked() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            locked_trip BIGINT;
            old_trip BIGINT;
            new_trip BIGINT;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF (NEW.trip_id, NEW.seq, NEW.stop_id, NEW.route_version_stop_seq)
                   IS NOT DISTINCT FROM (OLD.trip_id, OLD.seq, OLD.stop_id, OLD.route_version_stop_seq) THEN
                    RETURN NEW;  -- schedule/ETA columns are not stops
                END IF;
                old_trip := OLD.trip_id;
                new_trip := NEW.trip_id;
            ELSIF TG_OP = 'INSERT' THEN
                new_trip := NEW.trip_id;
            ELSE
                old_trip := OLD.trip_id;
            END IF;
            SELECT a.trip_id INTO locked_trip FROM booking_allocations a
            WHERE a.trip_id = old_trip OR a.trip_id = new_trip
            LIMIT 1;
            IF locked_trip IS NOT NULL THEN
                RAISE EXCEPTION 'trip % stops are locked: the trip has booking allocations', locked_trip
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{STOPS_LOCKED_RULE}';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trip_segment_resources_stops_locked() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            locked_trip BIGINT;
            old_trip BIGINT;
            new_trip BIGINT;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF (NEW.trip_id, NEW.from_seq, NEW.to_seq) IS NOT DISTINCT FROM (OLD.trip_id, OLD.from_seq, OLD.to_seq) THEN
                    RETURN NEW;  -- counters/capacity are not stops (see the counter trigger below)
                END IF;
                old_trip := OLD.trip_id;
                new_trip := NEW.trip_id;
            ELSIF TG_OP = 'INSERT' THEN
                new_trip := NEW.trip_id;
            ELSE
                old_trip := OLD.trip_id;
            END IF;
            SELECT a.trip_id INTO locked_trip FROM booking_allocations a
            WHERE a.trip_id = old_trip OR a.trip_id = new_trip
            LIMIT 1;
            IF locked_trip IS NOT NULL THEN
                RAISE EXCEPTION 'trip % segments are locked: the trip has booking allocations', locked_trip
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{STOPS_LOCKED_RULE}';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_trip_stop_occurrences_stops_locked "
        "BEFORE INSERT OR UPDATE OR DELETE ON trip_stop_occurrences "
        "FOR EACH ROW EXECUTE FUNCTION trip_stop_occurrences_stops_locked()"
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_trip_segment_resources_stops_locked "
        "BEFORE INSERT OR UPDATE OR DELETE ON trip_segment_resources "
        "FOR EACH ROW EXECUTE FUNCTION trip_segment_resources_stops_locked()"
    )

    # --- capacity counters follow allocations (deferred, per segment row) ---------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trip_segment_resources_counters_match_allocations() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            bad_seq INTEGER;
        BEGIN
            SELECT s.from_seq INTO bad_seq
            FROM trip_segment_resources s
            LEFT JOIN (
                SELECT sum(seats) AS seats, sum(baggage_ml) AS baggage_ml,
                       sum(cargo_weight_g) AS cargo_weight_g, sum(cargo_volume_ml) AS cargo_volume_ml
                FROM booking_allocations
                WHERE trip_id = NEW.trip_id AND segment_from_seq = NEW.from_seq AND active
            ) a ON true
            WHERE s.trip_id = NEW.trip_id AND s.from_seq = NEW.from_seq
              AND (s.seats_used <> COALESCE(a.seats, 0)
                   OR s.baggage_used_ml <> COALESCE(a.baggage_ml, 0)
                   OR s.cargo_used_weight_g <> COALESCE(a.cargo_weight_g, 0)
                   OR s.cargo_used_volume_ml <> COALESCE(a.cargo_volume_ml, 0));
            IF bad_seq IS NOT NULL THEN
                RAISE EXCEPTION 'trip_segment_resources counters of trip % segment % changed without a matching booking allocation change',
                    NEW.trip_id, bad_seq USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_trip_segment_resources_counters_match_allocations ON trip_segment_resources"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_trip_segment_resources_counters_match_allocations "
        "AFTER INSERT OR UPDATE OF seats_used, baggage_used_ml, cargo_used_weight_g, cargo_used_volume_ml "
        "ON trip_segment_resources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION trip_segment_resources_counters_match_allocations()"
    )

    # --- Q68: strict parcel types and amenities --------------------------------------------------------------
    parcel_types, amenities = _in(PARCEL_TYPES), _in(AMENITIES)
    _add_check_not_valid(
        "parcel_listing_details",
        "ck_parcel_listing_details_parcel_type",
        f"parcel_type IS NULL OR parcel_type IN {parcel_types}",
    )
    _add_check_not_valid(
        "parcel_listing_details",
        "ck_parcel_listing_details_accepted_parcel_types",
        f"accepted_parcel_types <@ {_text_array(PARCEL_TYPES)}",
    )
    _add_check_not_valid(
        "passenger_listing_details",
        "ck_passenger_listing_details_amenities",
        f"amenities <@ {_text_array(AMENITIES)}",
    )
    op.execute(
        f"""
        DO $$
        DECLARE
            changed BIGINT;
        BEGIN
            -- One UPDATE per table: the NOT VALID checks already apply to every rewritten row, so all
            -- constrained columns of a row must be cleaned in the same statement.
            UPDATE parcel_listing_details
            SET parcel_type = CASE
                    WHEN parcel_type IS NULL OR parcel_type IN {parcel_types} THEN parcel_type
                    WHEN lower(btrim(parcel_type)) IN {parcel_types} THEN lower(btrim(parcel_type))
                    ELSE 'other' END,
                accepted_parcel_types = ARRAY(
                    SELECT t.value FROM (
                        SELECT CASE WHEN lower(btrim(u.item)) IN {parcel_types} THEN lower(btrim(u.item)) ELSE 'other' END AS value,
                               min(u.ord) AS ord
                        FROM unnest(accepted_parcel_types) WITH ORDINALITY AS u(item, ord)
                        GROUP BY 1
                    ) t ORDER BY t.ord
                )
            WHERE (parcel_type IS NOT NULL AND parcel_type NOT IN {parcel_types})
               OR NOT (accepted_parcel_types <@ {_text_array(PARCEL_TYPES)});
            GET DIAGNOSTICS changed = ROW_COUNT;
            RAISE NOTICE '0054 Q68: parcel_listing_details rows normalised (parcel_type/accepted_parcel_types)=%', changed;

            UPDATE passenger_listing_details
            SET amenities = ARRAY(
                SELECT t.value FROM (
                    SELECT lower(btrim(u.item)) AS value, min(u.ord) AS ord
                    FROM unnest(amenities) WITH ORDINALITY AS u(item, ord)
                    WHERE lower(btrim(u.item)) IN {amenities}
                    GROUP BY 1
                ) t ORDER BY t.ord
            )
            WHERE NOT (amenities <@ {_text_array(AMENITIES)});
            GET DIAGNOSTICS changed = ROW_COUNT;
            RAISE NOTICE '0054 Q68: passenger_listing_details.amenities cleaned rows=%', changed;
        END $$;
        """
    )
    op.execute("ALTER TABLE parcel_listing_details VALIDATE CONSTRAINT ck_parcel_listing_details_parcel_type")
    op.execute("ALTER TABLE parcel_listing_details VALIDATE CONSTRAINT ck_parcel_listing_details_accepted_parcel_types")
    op.execute("ALTER TABLE passenger_listing_details VALIDATE CONSTRAINT ck_passenger_listing_details_amenities")

    # --- item 7: receiver contact of a trip-offer parcel proposal ------------------------------------------------
    op.execute(
        "ALTER TABLE proposal_versions ADD COLUMN IF NOT EXISTS receiver_name VARCHAR(120) NULL, "
        "ADD COLUMN IF NOT EXISTS receiver_phone VARCHAR(32) NULL"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_proposal_versions_receiver'
                  AND conrelid = 'proposal_versions'::regclass
            ) THEN
                ALTER TABLE proposal_versions ADD CONSTRAINT ck_proposal_versions_receiver
                    CHECK ((receiver_name IS NULL) = (receiver_phone IS NULL));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
