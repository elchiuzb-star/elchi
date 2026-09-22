"""geo stop evidence + price bands (wave 1.6)

Owner: A2 (wave 1.6) - module `geo`.
Content (DATA_MODEL.md §5, wave 1.6):
  * Q47: continuous guards for corridors in pilot/active - at least 2 active stops and stop
    evidence (meeting note or photo, Q27) enforced on every stop/corridor change, not only on the
    rollout transition;
  * Q42: corridor segment price band config (operator-configured floor/ceiling per segment and
    service type, versioned, audited); marketplace enforcement is A1's.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the
revision id, file name or down_revision; single head. downgrade() is not a rollback strategy
(ADR-0016, spec §18.3).

Revision ID: 20260914_0046
Revises: 20260914_0045
Create Date: 2026-09-14 00:46:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260914_0046"
down_revision: str = "20260914_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_constraint_trigger(name: str, table: str, events: str, function: str) -> None:
    # CREATE OR REPLACE is not used for constraint triggers; create once, guarded.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = '{name}' AND NOT tgisinternal) THEN
                CREATE CONSTRAINT TRIGGER {name} AFTER {events} ON {table}
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}();
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- Q47: continuous public-corridor stop guards -----------------------------------------------
    # Deferred to commit so a transaction may add a stop before retiring another. The corridor row is
    # locked FOR NO KEY UPDATE first, so concurrent writers on one corridor are serialised and each
    # check (new statement snapshot under READ COMMITTED) sees the other's committed change.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_assert_public_corridor_stops(p_corridor_id BIGINT) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            state TEXT;
            active_count INTEGER;
            missing_count INTEGER;
        BEGIN
            SELECT rollout_state INTO state FROM service_corridors WHERE id = p_corridor_id FOR NO KEY UPDATE;
            IF state IS NULL OR state NOT IN ('pilot', 'active') THEN
                RETURN;
            END IF;
            SELECT count(*) FILTER (WHERE is_active),
                   count(*) FILTER (WHERE is_active
                                      AND (meeting_note IS NULL OR btrim(meeting_note) = '')
                                      AND meeting_photo_file_id IS NULL)
              INTO active_count, missing_count
              FROM corridor_stops WHERE corridor_id = p_corridor_id;
            IF active_count < 2 THEN
                RAISE EXCEPTION 'service corridor %: pilot/active corridors need at least 2 active stops (Q47)', p_corridor_id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF missing_count > 0 THEN
                RAISE EXCEPTION 'service corridor %: every active stop needs a meeting note or photo (Q27/Q47)', p_corridor_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_corridor_stops_public_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                PERFORM geo_assert_public_corridor_stops(OLD.corridor_id);
            END IF;
            IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.corridor_id IS DISTINCT FROM OLD.corridor_id) THEN
                PERFORM geo_assert_public_corridor_stops(NEW.corridor_id);
            END IF;
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_service_corridors_public_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.rollout_state IN ('pilot', 'active') THEN
                PERFORM geo_assert_public_corridor_stops(NEW.id);
            END IF;
            RETURN NULL;
        END
        $$
        """
    )
    _create_constraint_trigger("trg_corridor_stops_public_guard", "corridor_stops", "INSERT OR UPDATE OR DELETE", "geo_corridor_stops_public_guard")
    _create_constraint_trigger("trg_service_corridors_public_guard", "service_corridors", "UPDATE", "geo_service_corridors_public_guard")

    # --- Q42: corridor price bands ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corridor_price_bands (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            corridor_id BIGINT NOT NULL,
            service_type TEXT NOT NULL,
            price_basis TEXT NOT NULL,
            origin_stop_id BIGINT NULL,
            destination_stop_id BIGINT NULL,
            floor_minor BIGINT NOT NULL,
            ceiling_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            is_active BOOLEAN NOT NULL DEFAULT true,
            reason TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_corridor_price_bands_public_id UNIQUE (public_id),
            CONSTRAINT fk_corridor_price_bands_corridor FOREIGN KEY (corridor_id) REFERENCES service_corridors (id),
            CONSTRAINT fk_corridor_price_bands_origin_stop FOREIGN KEY (origin_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_corridor_price_bands_destination_stop FOREIGN KEY (destination_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_corridor_price_bands_updated_by FOREIGN KEY (updated_by) REFERENCES users (id),
            CONSTRAINT ck_corridor_price_bands_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_corridor_price_bands_price_basis CHECK (
                (service_type = 'passenger' AND price_basis = 'per_seat') OR (service_type = 'parcel' AND price_basis = 'total')
            ),
            CONSTRAINT ck_corridor_price_bands_amounts CHECK (floor_minor > 0 AND ceiling_minor > 0 AND floor_minor <= ceiling_minor),
            CONSTRAINT ck_corridor_price_bands_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_corridor_price_bands_segment CHECK (
                (origin_stop_id IS NULL) = (destination_stop_id IS NULL)
                AND (origin_stop_id IS NULL OR origin_stop_id <> destination_stop_id)
            ),
            CONSTRAINT ck_corridor_price_bands_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
            CONSTRAINT ck_corridor_price_bands_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_corridor_price_bands_corridor_scope "
        "ON corridor_price_bands (corridor_id, service_type) WHERE origin_stop_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_corridor_price_bands_segment_scope "
        "ON corridor_price_bands (corridor_id, service_type, origin_stop_id, destination_stop_id) WHERE origin_stop_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corridor_price_band_changes (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            band_id BIGINT NOT NULL,
            corridor_id BIGINT NOT NULL,
            service_type TEXT NOT NULL,
            origin_stop_id BIGINT NULL,
            destination_stop_id BIGINT NULL,
            band_version INTEGER NOT NULL,
            old_floor_minor BIGINT NULL,
            old_ceiling_minor BIGINT NULL,
            old_is_active BOOLEAN NULL,
            new_floor_minor BIGINT NOT NULL,
            new_ceiling_minor BIGINT NOT NULL,
            new_is_active BOOLEAN NOT NULL,
            actor_user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_corridor_price_band_changes_version UNIQUE (band_id, band_version),
            CONSTRAINT fk_corridor_price_band_changes_band FOREIGN KEY (band_id) REFERENCES corridor_price_bands (id),
            CONSTRAINT fk_corridor_price_band_changes_corridor FOREIGN KEY (corridor_id) REFERENCES service_corridors (id),
            CONSTRAINT fk_corridor_price_band_changes_origin_stop FOREIGN KEY (origin_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_corridor_price_band_changes_destination_stop FOREIGN KEY (destination_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_corridor_price_band_changes_actor FOREIGN KEY (actor_user_id) REFERENCES users (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_corridor_price_band_changes_corridor ON corridor_price_band_changes (corridor_id, id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_corridor_price_bands_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'corridor_price_bands rows cannot be deleted; deactivate the band instead'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.corridor_id IS DISTINCT FROM OLD.corridor_id
                   OR NEW.service_type IS DISTINCT FROM OLD.service_type OR NEW.price_basis IS DISTINCT FROM OLD.price_basis
                   OR NEW.origin_stop_id IS DISTINCT FROM OLD.origin_stop_id
                   OR NEW.destination_stop_id IS DISTINCT FROM OLD.destination_stop_id
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'corridor_price_bands scope columns are immutable' USING ERRCODE = 'restrict_violation';
                END IF;
                IF NEW.version IS DISTINCT FROM OLD.version + 1 THEN
                    RAISE EXCEPTION 'corridor_price_bands.version must increase by exactly 1' USING ERRCODE = 'check_violation';
                END IF;
                NEW.updated_at := now();
            END IF;
            IF NEW.origin_stop_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM corridor_stops s
                WHERE s.id IN (NEW.origin_stop_id, NEW.destination_stop_id) AND s.corridor_id <> NEW.corridor_id
            ) THEN
                RAISE EXCEPTION 'corridor_price_bands: segment stops must belong to the corridor' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_corridor_price_bands_guard BEFORE INSERT OR UPDATE OR DELETE ON corridor_price_bands "
        "FOR EACH ROW EXECUTE FUNCTION geo_corridor_price_bands_guard()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_corridor_price_bands_record_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO corridor_price_band_changes (
                band_id, corridor_id, service_type, origin_stop_id, destination_stop_id, band_version,
                old_floor_minor, old_ceiling_minor, old_is_active, new_floor_minor, new_ceiling_minor, new_is_active,
                actor_user_id, reason, changed_at
            ) VALUES (
                NEW.id, NEW.corridor_id, NEW.service_type, NEW.origin_stop_id, NEW.destination_stop_id, NEW.version,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.floor_minor END,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.ceiling_minor END,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.is_active END,
                NEW.floor_minor, NEW.ceiling_minor, NEW.is_active, NEW.updated_by, NEW.reason, now()
            );
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_corridor_price_bands_record_change AFTER INSERT OR UPDATE ON corridor_price_bands "
        "FOR EACH ROW EXECUTE FUNCTION geo_corridor_price_bands_record_change()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_corridor_price_band_changes_append_only BEFORE UPDATE OR DELETE ON corridor_price_band_changes "
        "FOR EACH ROW EXECUTE FUNCTION geo_append_only()"
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_corridor_price_band_changes_no_truncate BEFORE TRUNCATE ON corridor_price_band_changes "
        "FOR EACH STATEMENT EXECUTE FUNCTION geo_append_only()"
    )


def downgrade() -> None:
    pass
