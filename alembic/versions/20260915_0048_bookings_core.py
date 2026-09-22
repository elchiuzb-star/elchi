"""bookings core: bookings, booking_allocations, booking_status_history (A4, wave 2)

Owner: A4 (wave 2) - module `bookings`.
Content (DATA_MODEL.md §1.7, §2; STATE_MACHINES §4-§7; spec §13, §15):
  * bookings - immutable agreement snapshot of the accepted proposal version (price, quantity, demand,
    pickup/dropoff occurrences and windows, route_version_id + trip_version, fee_policy_id/fee_bps/
    commission_minor, listing_version + listing_terms_version (Q54), flags snapshot) with three independent
    status columns (service_status, cash_status, commission_status) and contact-visibility timestamps (Q44:
    service_started_at, service_terminal_at).
    DB invariants: UNIQUE(accepted_proposal_version_id) (AC08); one non-cancelled binding booking per request
    listing (partial unique, AC06); D3 CHECK (fee_bps = 0) = (commission_status = 'exempt'); status CHECKs from
    app.contracts.enums per service type; total formula; client <> driver; guard trigger (snapshot columns
    immutable, terminal service/commission statuses final, no delete, no truncate).
  * booking_allocations - one row per trip segment [pickup, dropoff) with the reserved resources and the
    `active` flag of the release contract (ADR-0017 §11): only true -> false, once. A deferred constraint trigger
    proves at COMMIT that every trip segment's used counters equal the sum of its active allocations (no leak,
    no double release).
  * booking_status_history - append-only transition log of every machine.

Deliberately NOT in this migration (see A4 report, requests to owners):
  * FK wallet_holds.booking_id / ledger_transactions.booking_id -> bookings(id): A3's PG tests create holds with
    synthetic booking ids and the A3 ORM models declare no ForeignKey (the ORM drift test would fail). Added in a
    forward migration once A3 switches its tests/models.
  * composite FK booking_allocations(trip_id, segment_from_seq) -> trip_segment_resources(trip_id, from_seq):
    A1 ``patch_trip`` deletes and recreates segments of a trip without active usage (released allocations would
    block it) and detour insertions renumber segments; the deferred consistency trigger is the stronger check.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0048
Revises: 20260914_0047
Create Date: 2026-09-15 00:48:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0048"
down_revision: str = "20260914_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app.contracts.enums values (a migration must not change when the code changes);
# tests/modules/bookings/test_migration_literals.py asserts they equal the contract enums.
SERVICE_TYPES = ("passenger", "parcel")
PASSENGER_STATUSES = ("confirmed", "awaiting_pickup", "onboard", "arrived", "completed", "cancelled", "no_show")
PARCEL_STATUSES = (
    "confirmed",
    "awaiting_pickup",
    "picked_up",
    "in_transit",
    "delivered",
    "completed",
    "cancelled",
    "return_required",
    "returned",
    "delivery_failed",
)
CASH_STATUSES = ("unpaid", "reported_paid", "acknowledged", "contested")
COMMISSION_STATUSES = ("exempt", "held", "captured", "released", "partially_reversed", "reversed")
ACTOR_SIDES = ("client", "driver", "operator", "system")
FAULT_SIDES = ("client", "driver", "platform", "none")
HISTORY_MACHINES = ("service", "cash", "commission", "no_show_review", "custody_case", "amendment", "proof")
TERMINAL_SERVICE_STATUSES = ("completed", "cancelled", "no_show", "returned")
TERMINAL_COMMISSION_STATUSES = ("exempt", "released", "reversed")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION bookings_reject_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% cannot be truncated', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bookings_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only (%)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )

    # --- bookings ------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS bookings (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            service_status VARCHAR(24) NOT NULL,
            cash_status VARCHAR(16) NOT NULL DEFAULT 'unpaid',
            commission_status VARCHAR(24) NOT NULL,
            client_user_id INTEGER NOT NULL CONSTRAINT fk_bookings_client_user_id REFERENCES users (id),
            driver_user_id INTEGER NOT NULL CONSTRAINT fk_bookings_driver_user_id REFERENCES users (id),
            trip_id BIGINT NOT NULL CONSTRAINT fk_bookings_trip_id REFERENCES trips (id),
            corridor_id BIGINT NOT NULL CONSTRAINT fk_bookings_corridor_id REFERENCES service_corridors (id),
            request_listing_id BIGINT CONSTRAINT fk_bookings_request_listing_id REFERENCES listings (id),
            supply_listing_id BIGINT CONSTRAINT fk_bookings_supply_listing_id REFERENCES listings (id),
            proposal_thread_id BIGINT NOT NULL
                CONSTRAINT fk_bookings_proposal_thread_id REFERENCES proposal_threads (id),
            accepted_proposal_version_id BIGINT NOT NULL
                CONSTRAINT fk_bookings_accepted_proposal_version_id REFERENCES proposal_versions (id),
            route_version_id BIGINT NOT NULL CONSTRAINT fk_bookings_route_version_id REFERENCES route_versions (id),
            trip_version INTEGER NOT NULL,
            pickup_stop_id BIGINT NOT NULL CONSTRAINT fk_bookings_pickup_stop_id REFERENCES corridor_stops (id),
            dropoff_stop_id BIGINT NOT NULL CONSTRAINT fk_bookings_dropoff_stop_id REFERENCES corridor_stops (id),
            pickup_occurrence_seq SMALLINT NOT NULL,
            dropoff_occurrence_seq SMALLINT NOT NULL,
            pickup_window_start TIMESTAMPTZ NOT NULL,
            pickup_window_end TIMESTAMPTZ NOT NULL,
            dropoff_window_start TIMESTAMPTZ,
            dropoff_window_end TIMESTAMPTZ,
            quantity INTEGER NOT NULL,
            seats INTEGER NOT NULL DEFAULT 0,
            baggage_ml INTEGER NOT NULL DEFAULT 0,
            cargo_weight_g INTEGER NOT NULL DEFAULT 0,
            cargo_volume_ml INTEGER NOT NULL DEFAULT 0,
            price_basis VARCHAR(16) NOT NULL,
            unit_price_minor BIGINT NOT NULL,
            total_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            payment_method VARCHAR(16) NOT NULL DEFAULT 'cash',
            fee_policy_id BIGINT NOT NULL CONSTRAINT fk_bookings_fee_policy_id REFERENCES commission_policies (id),
            fee_bps INTEGER NOT NULL,
            commission_minor BIGINT NOT NULL,
            listing_version INTEGER NOT NULL,
            listing_terms_version INTEGER NOT NULL,
            terms_snapshot JSONB NOT NULL,
            arrived_at_pickup_at TIMESTAMPTZ,
            service_started_at TIMESTAMPTZ,
            service_ended_at TIMESTAMPTZ,
            service_terminal_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            cancelled_by_side VARCHAR(16),
            cancelled_by_user_id INTEGER CONSTRAINT fk_bookings_cancelled_by_user_id REFERENCES users (id),
            cancel_reason_code VARCHAR(64),
            cancel_comment TEXT,
            fault_side VARCHAR(16),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_bookings_public_id UNIQUE (public_id),
            CONSTRAINT uq_bookings_accepted_proposal_version UNIQUE (accepted_proposal_version_id),
            CONSTRAINT ck_bookings_service_type CHECK (service_type IN {_in(SERVICE_TYPES)}),
            CONSTRAINT ck_bookings_service_status CHECK (
                (service_type = 'passenger' AND service_status IN {_in(PASSENGER_STATUSES)})
                OR (service_type = 'parcel' AND service_status IN {_in(PARCEL_STATUSES)})
            ),
            CONSTRAINT ck_bookings_cash_status CHECK (cash_status IN {_in(CASH_STATUSES)}),
            CONSTRAINT ck_bookings_commission_status CHECK (commission_status IN {_in(COMMISSION_STATUSES)}),
            CONSTRAINT ck_bookings_exempt_iff_zero_bps CHECK ((fee_bps = 0) = (commission_status = 'exempt')),
            CONSTRAINT ck_bookings_fee_bps CHECK (fee_bps BETWEEN 0 AND 10000),
            CONSTRAINT ck_bookings_commission_minor CHECK (commission_minor >= 0 AND (fee_bps > 0 OR commission_minor = 0)),
            CONSTRAINT ck_bookings_parties CHECK (client_user_id <> driver_user_id),
            CONSTRAINT ck_bookings_listing_present CHECK (request_listing_id IS NOT NULL OR supply_listing_id IS NOT NULL),
            CONSTRAINT ck_bookings_occurrence_order CHECK (
                pickup_occurrence_seq >= 1 AND pickup_occurrence_seq < dropoff_occurrence_seq
            ),
            CONSTRAINT ck_bookings_pickup_window CHECK (pickup_window_end > pickup_window_start),
            CONSTRAINT ck_bookings_dropoff_window CHECK (
                (dropoff_window_start IS NULL) = (dropoff_window_end IS NULL)
                AND (dropoff_window_end IS NULL OR dropoff_window_end > dropoff_window_start)
            ),
            CONSTRAINT ck_bookings_quantity CHECK (quantity > 0 AND (service_type <> 'parcel' OR quantity = 1)),
            CONSTRAINT ck_bookings_resources CHECK (
                seats >= 0 AND baggage_ml >= 0 AND cargo_weight_g >= 0 AND cargo_volume_ml >= 0
                AND (service_type <> 'passenger' OR seats = quantity)
                AND (service_type <> 'parcel' OR seats = 0)
            ),
            CONSTRAINT ck_bookings_price_basis CHECK (
                price_basis IN ('per_seat', 'total') AND (service_type <> 'parcel' OR price_basis = 'total')
            ),
            CONSTRAINT ck_bookings_total_minor CHECK (
                unit_price_minor > 0
                AND total_minor = CASE price_basis WHEN 'per_seat' THEN unit_price_minor * quantity ELSE unit_price_minor END
            ),
            CONSTRAINT ck_bookings_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_bookings_payment_method CHECK (payment_method = 'cash'),
            CONSTRAINT ck_bookings_cancelled CHECK (
                (service_status = 'cancelled') = (cancelled_at IS NOT NULL)
                AND (cancelled_at IS NULL OR (cancelled_by_side IS NOT NULL AND cancel_reason_code IS NOT NULL
                                              AND fault_side IS NOT NULL))
            ),
            CONSTRAINT ck_bookings_cancelled_by_side CHECK (cancelled_by_side IS NULL OR cancelled_by_side IN {_in(ACTOR_SIDES)}),
            CONSTRAINT ck_bookings_fault_side CHECK (fault_side IS NULL OR fault_side IN {_in(FAULT_SIDES)}),
            CONSTRAINT ck_bookings_versions CHECK (
                version >= 1 AND trip_version >= 1 AND listing_version >= 1 AND listing_terms_version >= 1
            )
        )
        """
    )
    # AC06: one non-cancelled binding booking per client demand (request listing).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_request_listing_binding ON bookings (request_listing_id) "
        "WHERE request_listing_id IS NOT NULL AND service_status <> 'cancelled'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_client_created ON bookings (client_user_id, created_at, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_driver_created ON bookings (driver_user_id, created_at, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_trip_id ON bookings (trip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_corridor_status ON bookings (corridor_id, service_status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_supply_listing_id ON bookings (supply_listing_id)")

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION bookings_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'bookings cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.public_id, NEW.service_type, NEW.client_user_id, NEW.driver_user_id, NEW.trip_id,
                NEW.corridor_id, NEW.request_listing_id, NEW.supply_listing_id, NEW.proposal_thread_id,
                NEW.accepted_proposal_version_id, NEW.route_version_id, NEW.fee_policy_id, NEW.fee_bps, NEW.currency,
                NEW.payment_method, NEW.listing_version, NEW.listing_terms_version, NEW.terms_snapshot, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.public_id, OLD.service_type, OLD.client_user_id, OLD.driver_user_id, OLD.trip_id,
                OLD.corridor_id, OLD.request_listing_id, OLD.supply_listing_id, OLD.proposal_thread_id,
                OLD.accepted_proposal_version_id, OLD.route_version_id, OLD.fee_policy_id, OLD.fee_bps, OLD.currency,
                OLD.payment_method, OLD.listing_version, OLD.listing_terms_version, OLD.terms_snapshot, OLD.created_at)
            THEN
                RAISE EXCEPTION 'booking agreement snapshot is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.service_status IS DISTINCT FROM OLD.service_status
               AND OLD.service_status IN {_in(TERMINAL_SERVICE_STATUSES)} THEN
                RAISE EXCEPTION 'booking service status % is terminal', OLD.service_status
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.commission_status IS DISTINCT FROM OLD.commission_status
               AND OLD.commission_status IN {_in(TERMINAL_COMMISSION_STATUSES)} THEN
                RAISE EXCEPTION 'booking commission status % is terminal', OLD.commission_status
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.version < OLD.version THEN
                RAISE EXCEPTION 'booking version cannot decrease' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_bookings_guard",
        "bookings",
        "TRIGGER trg_bookings_guard BEFORE UPDATE OR DELETE ON bookings FOR EACH ROW EXECUTE FUNCTION bookings_guard()",
    )
    _trigger(
        "trg_bookings_no_truncate",
        "bookings",
        "TRIGGER trg_bookings_no_truncate BEFORE TRUNCATE ON bookings "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    # --- booking_allocations (release contract, ADR-0017 §11) -------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS booking_allocations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_booking_allocations_booking_id REFERENCES bookings (id),
            trip_id BIGINT NOT NULL CONSTRAINT fk_booking_allocations_trip_id REFERENCES trips (id),
            segment_from_seq SMALLINT NOT NULL,
            seats INTEGER NOT NULL DEFAULT 0,
            baggage_ml INTEGER NOT NULL DEFAULT 0,
            cargo_weight_g INTEGER NOT NULL DEFAULT 0,
            cargo_volume_ml INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT true,
            released_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_booking_allocations_segment CHECK (segment_from_seq >= 1),
            CONSTRAINT ck_booking_allocations_amounts CHECK (
                seats >= 0 AND baggage_ml >= 0 AND cargo_weight_g >= 0 AND cargo_volume_ml >= 0
                AND seats + baggage_ml + cargo_weight_g + cargo_volume_ml > 0
            ),
            CONSTRAINT ck_booking_allocations_released CHECK (active = (released_at IS NULL))
        )
        """
    )
    # One ACTIVE allocation per booking segment. Released rows stay as history, so an amendment can release the old
    # allocation (true -> false) and reserve a new one on the same segment (DATA_MODEL UNIQUE(booking, segment) made
    # partial on `active`; the invariant "a booking holds a segment at most once" is unchanged).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_allocations_booking_segment_active "
        "ON booking_allocations (booking_id, segment_from_seq) WHERE active"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_booking_allocations_trip_active ON booking_allocations (trip_id, segment_from_seq) "
        "WHERE active"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_booking_allocations_booking ON booking_allocations (booking_id, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION booking_allocations_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            booking_trip BIGINT;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'booking_allocations cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                SELECT trip_id INTO booking_trip FROM bookings WHERE id = NEW.booking_id;
                IF booking_trip IS DISTINCT FROM NEW.trip_id THEN
                    RAISE EXCEPTION 'allocation trip % does not match booking trip %', NEW.trip_id, booking_trip
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NOT NEW.active THEN
                    RAISE EXCEPTION 'allocations are created active' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.id, NEW.booking_id, NEW.trip_id, NEW.segment_from_seq, NEW.seats, NEW.baggage_ml,
                NEW.cargo_weight_g, NEW.cargo_volume_ml, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.booking_id, OLD.trip_id, OLD.segment_from_seq, OLD.seats, OLD.baggage_ml,
                OLD.cargo_weight_g, OLD.cargo_volume_ml, OLD.created_at) THEN
                RAISE EXCEPTION 'booking allocation content is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.active AND NOT OLD.active THEN
                RAISE EXCEPTION 'a released allocation cannot be re-activated (release contract)'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NOT OLD.active AND NEW.released_at IS DISTINCT FROM OLD.released_at THEN
                RAISE EXCEPTION 'released allocation is final' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_booking_allocations_guard",
        "booking_allocations",
        "TRIGGER trg_booking_allocations_guard BEFORE INSERT OR UPDATE OR DELETE ON booking_allocations "
        "FOR EACH ROW EXECUTE FUNCTION booking_allocations_guard()",
    )
    _trigger(
        "trg_booking_allocations_no_truncate",
        "booking_allocations",
        "TRIGGER trg_booking_allocations_no_truncate BEFORE TRUNCATE ON booking_allocations "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )
    # Deferred proof of the capacity accounting (AC07, AC21, release contract): at COMMIT every segment of the
    # trip carries exactly the resources of its active allocations, and no active allocation points to a
    # segment that does not exist.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION booking_allocations_assert_capacity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            bad_seq INTEGER;
        BEGIN
            SELECT s.from_seq INTO bad_seq
            FROM trip_segment_resources s
            LEFT JOIN (
                SELECT segment_from_seq, sum(seats) AS seats, sum(baggage_ml) AS baggage_ml,
                       sum(cargo_weight_g) AS cargo_weight_g, sum(cargo_volume_ml) AS cargo_volume_ml
                FROM booking_allocations
                WHERE trip_id = NEW.trip_id AND active
                GROUP BY segment_from_seq
            ) a ON a.segment_from_seq = s.from_seq
            WHERE s.trip_id = NEW.trip_id
              AND (s.seats_used <> COALESCE(a.seats, 0)
                   OR s.baggage_used_ml <> COALESCE(a.baggage_ml, 0)
                   OR s.cargo_used_weight_g <> COALESCE(a.cargo_weight_g, 0)
                   OR s.cargo_used_volume_ml <> COALESCE(a.cargo_volume_ml, 0))
            ORDER BY s.from_seq
            LIMIT 1;
            IF bad_seq IS NOT NULL THEN
                RAISE EXCEPTION 'trip % segment % used capacity does not equal its active booking allocations',
                    NEW.trip_id, bad_seq USING ERRCODE = 'check_violation';
            END IF;
            IF EXISTS (
                SELECT 1 FROM booking_allocations a
                WHERE a.trip_id = NEW.trip_id AND a.active
                  AND NOT EXISTS (
                      SELECT 1 FROM trip_segment_resources s WHERE s.trip_id = a.trip_id AND s.from_seq = a.segment_from_seq
                  )
            ) THEN
                RAISE EXCEPTION 'trip % has an active allocation on a missing segment', NEW.trip_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_booking_allocations_capacity_consistent ON booking_allocations")
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_booking_allocations_capacity_consistent AFTER INSERT OR UPDATE "
        "ON booking_allocations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION booking_allocations_assert_capacity()"
    )

    # --- booking_status_history (append-only) -----------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS booking_status_history (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_booking_status_history_booking_id REFERENCES bookings (id),
            machine VARCHAR(24) NOT NULL,
            from_status VARCHAR(24),
            to_status VARCHAR(24) NOT NULL,
            command VARCHAR(48) NOT NULL,
            actor_user_id INTEGER CONSTRAINT fk_booking_status_history_actor_user_id REFERENCES users (id),
            actor_side VARCHAR(16) NOT NULL,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_booking_status_history_machine CHECK (machine IN {_in(HISTORY_MACHINES)}),
            CONSTRAINT ck_booking_status_history_actor_side CHECK (actor_side IN {_in(ACTOR_SIDES)})
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_booking_status_history_booking ON booking_status_history (booking_id, id)"
    )
    _trigger(
        "trg_booking_status_history_append_only",
        "booking_status_history",
        "TRIGGER trg_booking_status_history_append_only BEFORE UPDATE OR DELETE ON booking_status_history "
        "FOR EACH ROW EXECUTE FUNCTION bookings_append_only()",
    )
    _trigger(
        "trg_booking_status_history_no_truncate",
        "booking_status_history",
        "TRIGGER trg_booking_status_history_no_truncate BEFORE TRUNCATE ON booking_status_history "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
