"""marketplace: listings with passenger and parcel details

Owner: A1 (wave 1) - module `marketplace`.
Content (DATA_MODEL.md §1.5, §5): listings (kind/service/status/price_basis CHECKs,
trip_offer requires trip_id, parcel requires price_basis=total, total_minor CHECK, partial unique
trip_id+service_type for open trip offers), passenger_listing_details (seat_count > 0, adults >= 1,
adults + children = seat_count), parcel_listing_details (positive g/ml/cm, payer CHECK).
Tables: listings, passenger_listing_details, parcel_listing_details.
FK dependencies: users (legacy), trips (0038), service_corridors and corridor_stops (0034).

D9 note: listings.quantity = passenger_listing_details.seat_count for requests is enforced by
the marketplace service and proven by a PG test (DATA_MODEL §1.5); it spans two rows.

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0039
Revises: 20260913_0038
Create Date: 2026-09-13 00:39:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0039"
down_revision: str = "20260913_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            owner_user_id INTEGER NOT NULL CONSTRAINT fk_listings_owner_user_id REFERENCES users (id),
            kind VARCHAR(16) NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            trip_id BIGINT NULL CONSTRAINT fk_listings_trip_id REFERENCES trips (id),
            corridor_id BIGINT NOT NULL CONSTRAINT fk_listings_corridor_id REFERENCES service_corridors (id),
            origin_stop_id BIGINT NOT NULL CONSTRAINT fk_listings_origin_stop_id REFERENCES corridor_stops (id),
            destination_stop_id BIGINT NOT NULL
                CONSTRAINT fk_listings_destination_stop_id REFERENCES corridor_stops (id),
            departure_window_start TIMESTAMPTZ NOT NULL,
            departure_window_end TIMESTAMPTZ NOT NULL,
            timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Tashkent',
            price_basis VARCHAR(16) NOT NULL,
            unit_price_minor BIGINT NOT NULL,
            quantity INTEGER NOT NULL,
            total_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            payment_method VARCHAR(16) NOT NULL DEFAULT 'cash',
            expires_at TIMESTAMPTZ NOT NULL,
            comment TEXT NULL,
            created_by_operator_id INTEGER NULL
                CONSTRAINT fk_listings_created_by_operator_id REFERENCES users (id),
            consent_reference VARCHAR(255) NULL,
            version INTEGER NOT NULL DEFAULT 1,
            published_at TIMESTAMPTZ NULL,
            cancelled_at TIMESTAMPTZ NULL,
            cancelled_by_user_id INTEGER NULL CONSTRAINT fk_listings_cancelled_by_user_id REFERENCES users (id),
            cancelled_reason VARCHAR(64) NULL,
            cancel_comment TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_listings_public_id UNIQUE (public_id),
            CONSTRAINT ck_listings_kind CHECK (kind IN ('request', 'trip_offer')),
            CONSTRAINT ck_listings_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_listings_status
                CHECK (status IN ('draft', 'published', 'paused', 'fulfilled', 'expired', 'cancelled')),
            CONSTRAINT ck_listings_price_basis CHECK (price_basis IN ('per_seat', 'total')),
            CONSTRAINT ck_listings_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_listings_payment_method CHECK (payment_method = 'cash'),
            CONSTRAINT ck_listings_trip_offer_has_trip CHECK (kind <> 'trip_offer' OR trip_id IS NOT NULL),
            CONSTRAINT ck_listings_request_has_no_trip CHECK (kind <> 'request' OR trip_id IS NULL),
            CONSTRAINT ck_listings_parcel_total_price CHECK (service_type <> 'parcel' OR price_basis = 'total'),
            CONSTRAINT ck_listings_passenger_offer_per_seat
                CHECK (kind <> 'trip_offer' OR service_type <> 'passenger' OR price_basis = 'per_seat'),
            CONSTRAINT ck_listings_parcel_single_quantity CHECK (service_type <> 'parcel' OR quantity = 1),
            CONSTRAINT ck_listings_departure_window CHECK (departure_window_end > departure_window_start),
            CONSTRAINT ck_listings_expires_within_window CHECK (expires_at <= departure_window_end),
            CONSTRAINT ck_listings_positive_price_quantity CHECK (unit_price_minor > 0 AND quantity > 0),
            CONSTRAINT ck_listings_total_minor CHECK (
                total_minor = CASE price_basis
                    WHEN 'per_seat' THEN unit_price_minor * quantity
                    ELSE unit_price_minor
                END
            ),
            CONSTRAINT ck_listings_distinct_stops CHECK (origin_stop_id <> destination_stop_id),
            CONSTRAINT ck_listings_version CHECK (version >= 1),
            CONSTRAINT ck_listings_cancelled_at CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
            CONSTRAINT ck_listings_published_at CHECK (status IN ('draft', 'cancelled') OR published_at IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_listings_open_trip_offer ON listings (trip_id, service_type)
        WHERE kind = 'trip_offer' AND status NOT IN ('cancelled', 'expired')
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_listings_feed ON listings (service_type, status, departure_window_start, id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_listings_corridor_status ON listings (corridor_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_listings_owner_created ON listings (owner_user_id, created_at, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_listings_trip_id ON listings (trip_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS passenger_listing_details (
            listing_id BIGINT PRIMARY KEY
                CONSTRAINT fk_passenger_listing_details_listing_id REFERENCES listings (id) ON DELETE CASCADE,
            seat_count SMALLINT NOT NULL,
            adults SMALLINT NOT NULL,
            children SMALLINT NOT NULL DEFAULT 0,
            child_seat_required BOOLEAN NOT NULL DEFAULT false,
            baggage_pieces SMALLINT NOT NULL DEFAULT 0,
            baggage_total_weight_g INTEGER NOT NULL DEFAULT 0,
            baggage_total_volume_ml INTEGER NULL,
            special_assistance TEXT NULL,
            amenities TEXT[] NOT NULL DEFAULT '{}',
            CONSTRAINT ck_passenger_listing_details_seat_count CHECK (seat_count > 0),
            CONSTRAINT ck_passenger_listing_details_adults CHECK (adults >= 1),
            CONSTRAINT ck_passenger_listing_details_children CHECK (children >= 0),
            CONSTRAINT ck_passenger_listing_details_party_size CHECK (adults + children = seat_count),
            CONSTRAINT ck_passenger_listing_details_baggage CHECK (
                baggage_pieces >= 0 AND baggage_total_weight_g >= 0
                AND (baggage_total_volume_ml IS NULL OR baggage_total_volume_ml >= 0)
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS parcel_listing_details (
            listing_id BIGINT PRIMARY KEY
                CONSTRAINT fk_parcel_listing_details_listing_id REFERENCES listings (id) ON DELETE CASCADE,
            parcel_type VARCHAR(32) NULL,
            weight_g INTEGER NULL,
            length_cm INTEGER NULL,
            width_cm INTEGER NULL,
            height_cm INTEGER NULL,
            fragile BOOLEAN NOT NULL DEFAULT false,
            declared_value_minor BIGINT NULL,
            photo_file_id VARCHAR(255) NULL,
            payer VARCHAR(16) NULL,
            sender_name VARCHAR(120) NULL,
            sender_phone VARCHAR(32) NULL,
            receiver_name VARCHAR(120) NULL,
            receiver_phone VARCHAR(32) NULL,
            pickup_window_start TIMESTAMPTZ NULL,
            pickup_window_end TIMESTAMPTZ NULL,
            dropoff_window_start TIMESTAMPTZ NULL,
            dropoff_window_end TIMESTAMPTZ NULL,
            max_weight_g INTEGER NULL,
            max_volume_ml INTEGER NULL,
            max_dimension_cm INTEGER NULL,
            accepted_parcel_types TEXT[] NOT NULL DEFAULT '{}',
            CONSTRAINT ck_parcel_listing_details_dimensions CHECK (
                (weight_g IS NULL OR weight_g > 0) AND (length_cm IS NULL OR length_cm > 0)
                AND (width_cm IS NULL OR width_cm > 0) AND (height_cm IS NULL OR height_cm > 0)
            ),
            CONSTRAINT ck_parcel_listing_details_limits CHECK (
                (max_weight_g IS NULL OR max_weight_g > 0) AND (max_volume_ml IS NULL OR max_volume_ml > 0)
                AND (max_dimension_cm IS NULL OR max_dimension_cm > 0)
            ),
            CONSTRAINT ck_parcel_listing_details_declared_value
                CHECK (declared_value_minor IS NULL OR declared_value_minor >= 0),
            CONSTRAINT ck_parcel_listing_details_payer CHECK (payer IS NULL OR payer IN ('sender', 'receiver')),
            CONSTRAINT ck_parcel_listing_details_pickup_window CHECK (
                pickup_window_start IS NULL OR pickup_window_end IS NULL OR pickup_window_end > pickup_window_start
            ),
            CONSTRAINT ck_parcel_listing_details_dropoff_window CHECK (
                dropoff_window_start IS NULL OR dropoff_window_end IS NULL OR dropoff_window_end > dropoff_window_start
            )
        )
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
