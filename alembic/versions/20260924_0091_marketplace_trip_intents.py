"""marketplace trip intents: a client's saved trip/parcel request, one live booking per request (ADR-0025)

Owner: marketplace (ADR-0025) - integrator A0a.
Content (DATA_MODEL.md §5):
  * ``trip_intents`` - private, reusable request of one client: service type, status (active / booked / closed),
    ``current_version_no``, ``terms_version`` (bumped only by a material edit), ``booking_id`` while booked, row
    ``version``. Owner and service are frozen; ``status = booked`` exactly when ``booking_id`` is set; the status moves
    only along STATE_MACHINES ``trip_intent`` (trigger).
  * ``trip_intent_versions`` - append-only terms: ends (stop, or district + optional point/address), time window,
    quantity, optional price hint (basis + unit together), parcel type/weight/size and receiver (owner-only).
  * ``proposal_threads.trip_intent_id`` + ``trip_intent_terms_version`` (both or neither) - frozen once written
    (trigger ``trip_intent_link_frozen``): an offer cannot be taken out of its request's one-booking protection.
  * ``bookings.trip_intent_id`` - equal to its thread's request on INSERT (trigger ``booking_trip_intent_mismatch``),
    frozen afterwards; ``uq_bookings_trip_intent_binding``: one non-cancelled booking per request (the database
    guarantee behind the accept-time check).

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260924_0091
Revises: 20260924_0090
Create Date: 2026-09-24 00:91:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260924_0091"
down_revision: str = "20260924_0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARCEL_TYPES = ("documents", "box", "bag", "electronics", "clothing", "other")  # enums.ParcelType (Q68, Q75)


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _add_constraint(table: str, name: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trip_intents (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            owner_user_id BIGINT NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            current_version_no INTEGER NOT NULL DEFAULT 1,
            terms_version INTEGER NOT NULL DEFAULT 1,
            booking_id BIGINT,
            closed_reason VARCHAR(32),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_trip_intents_public_id UNIQUE (public_id),
            CONSTRAINT fk_trip_intents_owner FOREIGN KEY (owner_user_id) REFERENCES users (id),
            CONSTRAINT fk_trip_intents_booking FOREIGN KEY (booking_id) REFERENCES bookings (id),
            CONSTRAINT ck_trip_intents_service CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_trip_intents_status CHECK (status IN ('active', 'booked', 'closed')),
            CONSTRAINT ck_trip_intents_booked CHECK ((status = 'booked') = (booking_id IS NOT NULL)),
            CONSTRAINT ck_trip_intents_counters CHECK (current_version_no >= 1 AND terms_version >= 1 AND version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trip_intents_owner_status ON trip_intents (owner_user_id, status, id)")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS trip_intent_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            intent_id BIGINT NOT NULL,
            version_no INTEGER NOT NULL,
            terms_version INTEGER NOT NULL,
            origin_stop_id BIGINT,
            origin_district_id BIGINT,
            origin_lat NUMERIC(10, 7),
            origin_lng NUMERIC(10, 7),
            origin_address VARCHAR(500),
            destination_stop_id BIGINT,
            destination_district_id BIGINT,
            destination_lat NUMERIC(10, 7),
            destination_lng NUMERIC(10, 7),
            destination_address VARCHAR(500),
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL,
            quantity SMALLINT NOT NULL,
            price_basis VARCHAR(16),
            unit_price_minor BIGINT,
            parcel_type VARCHAR(32),
            weight_g INTEGER,
            length_cm INTEGER,
            width_cm INTEGER,
            height_cm INTEGER,
            receiver_name VARCHAR(120),
            receiver_phone VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_trip_intent_versions_no UNIQUE (intent_id, version_no),
            CONSTRAINT fk_trip_intent_versions_intent FOREIGN KEY (intent_id) REFERENCES trip_intents (id),
            CONSTRAINT fk_trip_intent_versions_origin_stop FOREIGN KEY (origin_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_trip_intent_versions_destination_stop FOREIGN KEY (destination_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_trip_intent_versions_origin_district FOREIGN KEY (origin_district_id) REFERENCES geo_districts (id),
            CONSTRAINT fk_trip_intent_versions_destination_district FOREIGN KEY (destination_district_id)
                REFERENCES geo_districts (id),
            CONSTRAINT ck_trip_intent_versions_ends CHECK (
                (origin_stop_id IS NOT NULL OR origin_district_id IS NOT NULL)
                AND (destination_stop_id IS NOT NULL OR destination_district_id IS NOT NULL)
                AND ((origin_lat IS NULL) = (origin_lng IS NULL))
                AND ((destination_lat IS NULL) = (destination_lng IS NULL))
            ),
            CONSTRAINT ck_trip_intent_versions_window CHECK (window_end > window_start),
            CONSTRAINT ck_trip_intent_versions_quantity CHECK (quantity BETWEEN 1 AND 60),
            CONSTRAINT ck_trip_intent_versions_price CHECK (
                (price_basis IS NULL) = (unit_price_minor IS NULL)
                AND (price_basis IS NULL OR price_basis IN ('per_seat', 'total'))
                AND (unit_price_minor IS NULL OR unit_price_minor > 0)
            ),
            CONSTRAINT ck_trip_intent_versions_parcel CHECK (
                (parcel_type IS NULL OR parcel_type IN ({_in(PARCEL_TYPES)}))
                AND (weight_g IS NULL OR weight_g > 0) AND (length_cm IS NULL OR length_cm > 0)
                AND (width_cm IS NULL OR width_cm > 0) AND (height_cm IS NULL OR height_cm > 0)
                AND ((receiver_name IS NULL) = (receiver_phone IS NULL))
            )
        )
        """
    )

    # trip_intent_versions: append-only
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trip_intent_versions_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'trip_intent_versions rows are immutable'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
        END;
        $$
        """
    )
    _trigger("trg_trip_intent_versions_append_only", "trip_intent_versions",
             "TRIGGER trg_trip_intent_versions_append_only BEFORE UPDATE OR DELETE ON trip_intent_versions "
             "FOR EACH ROW EXECUTE FUNCTION public.trip_intent_versions_append_only()")

    # trip_intents: owner/service frozen, status only along the machine, never deleted
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trip_intents_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'trip_intents rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF NEW.owner_user_id <> OLD.owner_user_id OR NEW.service_type <> OLD.service_type
               OR NEW.public_id <> OLD.public_id OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'trip_intents owner, service and identity are frozen'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'trip_intent_link_frozen';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                   (OLD.status = 'active' AND NEW.status IN ('booked', 'closed'))
                OR (OLD.status = 'booked' AND NEW.status IN ('active', 'closed'))) THEN
                RAISE EXCEPTION 'trip_intents: % -> % is not a transition', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'trip_intent_invalid_transition';
            END IF;
            IF NEW.terms_version < OLD.terms_version OR NEW.current_version_no < OLD.current_version_no THEN
                RAISE EXCEPTION 'trip_intents version counters never go back'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'trip_intent_link_frozen';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_trip_intents_guard", "trip_intents",
             "TRIGGER trg_trip_intents_guard BEFORE UPDATE OR DELETE ON trip_intents "
             "FOR EACH ROW EXECUTE FUNCTION public.trip_intents_guard()")

    # proposal_threads: the request link, written once
    op.execute("ALTER TABLE proposal_threads ADD COLUMN IF NOT EXISTS trip_intent_id BIGINT")
    op.execute("ALTER TABLE proposal_threads ADD COLUMN IF NOT EXISTS trip_intent_terms_version INTEGER")
    _add_constraint("proposal_threads", "fk_proposal_threads_trip_intent",
                    "FOREIGN KEY (trip_intent_id) REFERENCES trip_intents (id)")
    _add_constraint("proposal_threads", "ck_proposal_threads_trip_intent_pair",
                    "CHECK ((trip_intent_id IS NULL) = (trip_intent_terms_version IS NULL))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_proposal_threads_trip_intent ON proposal_threads (trip_intent_id, state) "
               "WHERE trip_intent_id IS NOT NULL")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.proposal_threads_trip_intent_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.trip_intent_id IS DISTINCT FROM OLD.trip_intent_id
               OR NEW.trip_intent_terms_version IS DISTINCT FROM OLD.trip_intent_terms_version THEN
                RAISE EXCEPTION 'an offer stays linked to the saved request it was made from'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'trip_intent_link_frozen';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_proposal_threads_trip_intent_frozen", "proposal_threads",
             "TRIGGER trg_proposal_threads_trip_intent_frozen BEFORE UPDATE ON proposal_threads "
             "FOR EACH ROW EXECUTE FUNCTION public.proposal_threads_trip_intent_frozen()")

    # bookings: the request of the accepted thread, one live booking per request
    op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS trip_intent_id BIGINT")
    _add_constraint("bookings", "fk_bookings_trip_intent", "FOREIGN KEY (trip_intent_id) REFERENCES trip_intents (id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_trip_intent_binding ON bookings (trip_intent_id) "
               "WHERE trip_intent_id IS NOT NULL AND service_status <> 'cancelled'")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.bookings_trip_intent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            thread_intent BIGINT;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT trip_intent_id INTO thread_intent FROM public.proposal_threads WHERE id = NEW.proposal_thread_id;
                IF thread_intent IS DISTINCT FROM NEW.trip_intent_id THEN
                    RAISE EXCEPTION 'a booking carries the saved request of the offer it was accepted from'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'booking_trip_intent_mismatch';
                END IF;
            ELSIF NEW.trip_intent_id IS DISTINCT FROM OLD.trip_intent_id THEN
                RAISE EXCEPTION 'bookings.trip_intent_id is frozen'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'trip_intent_link_frozen';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_bookings_trip_intent_guard", "bookings",
             "TRIGGER trg_bookings_trip_intent_guard BEFORE INSERT OR UPDATE ON bookings "
             "FOR EACH ROW EXECUTE FUNCTION public.bookings_trip_intent_guard()")


def downgrade() -> None:
    """Dev/test only (not a rollback, spec §18.3)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_bookings_trip_intent_guard ON bookings")
    op.execute("DROP INDEX IF EXISTS uq_bookings_trip_intent_binding")
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS fk_bookings_trip_intent")
    op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS trip_intent_id")
    op.execute("DROP TRIGGER IF EXISTS trg_proposal_threads_trip_intent_frozen ON proposal_threads")
    op.execute("DROP INDEX IF EXISTS ix_proposal_threads_trip_intent")
    op.execute("ALTER TABLE proposal_threads DROP CONSTRAINT IF EXISTS ck_proposal_threads_trip_intent_pair")
    op.execute("ALTER TABLE proposal_threads DROP CONSTRAINT IF EXISTS fk_proposal_threads_trip_intent")
    op.execute("ALTER TABLE proposal_threads DROP COLUMN IF EXISTS trip_intent_terms_version")
    op.execute("ALTER TABLE proposal_threads DROP COLUMN IF EXISTS trip_intent_id")
    op.execute("DROP TABLE IF EXISTS trip_intent_versions")
    op.execute("DROP TABLE IF EXISTS trip_intents")
