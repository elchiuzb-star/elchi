"""promotions referral: codes, protected identities, attributions, enrollments (referral stage 2, ADR-0023)

Owner: referral stage 2 (Q106, Q108, Q112, Q117-Q119) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promo_identities`` + ``promo_identity_digests`` - the protected phone identifier (HMAC-SHA256, key never
    stored). Digests are unique per key version; rotation adds a new-version digest to the *same* identity, so
    history is not lost. ``retain_until`` is NULL until a retention period is approved (Q108).
  * ``referral_codes`` - random public codes, unique in the DB, one active code per owner; the owner never changes
    (trigger). Revoking a code does not touch attributions or obligations made with it.
  * ``referral_attributions`` - who invited whom: one per ``(referee, family)``, first wins, immutable
    referrer/referee/code/window (trigger); the 72 h window bounds are stored on the row.
  * ``promo_enrollments`` - which campaign version's terms were accepted: pinned version, service type, family,
    terms fingerprint, enrollment and qualification-deadline times (separate from the attribution window and from
    the reward spend validity). At most one live enrollment per identity and per user per family; idempotency key
    per referee with the request fingerprint.
  * ``promo_obligations.enrollment_id`` (additive FK).
  * Nothing here touches bookings, the real money ledger or a feature flag.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); single head; downgrade() is a dev/test
tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260923_0085
Revises: 20260923_0084
Create Date: 2026-09-23 00:85:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0085"
down_revision: str = "20260923_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ATTRIBUTION_WINDOW_SECONDS = 72 * 3600  # app.contracts.promo.ATTRIBUTION_WINDOW (Q106)
_FAMILIES = "'client_acquisition', 'driver_acquisition'"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _add_column(table: str, column: str, definition: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")


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
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- protected identities (Q108) ---------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_identities (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            current_user_id BIGINT,
            first_window_started_at TIMESTAMPTZ NOT NULL,
            retain_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_promo_identities_current_user FOREIGN KEY (current_user_id) REFERENCES users (id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_identities_current_user ON promo_identities (current_user_id) "
        "WHERE current_user_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_identity_digests (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            identity_id BIGINT NOT NULL,
            key_version SMALLINT NOT NULL,
            digest CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_identity_digests_version_digest UNIQUE (key_version, digest),
            CONSTRAINT uq_promo_identity_digests_identity_version UNIQUE (identity_id, key_version),
            CONSTRAINT fk_promo_identity_digests_identity FOREIGN KEY (identity_id) REFERENCES promo_identities (id),
            CONSTRAINT ck_promo_identity_digests_version CHECK (key_version >= 1),
            CONSTRAINT ck_promo_identity_digests_hex CHECK (digest ~ '^[0-9a-f]{64}$')
        )
        """
    )

    # --- referral codes (Q117) -------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_codes (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            code VARCHAR(16) NOT NULL,
            owner_user_id BIGINT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            revoked_at TIMESTAMPTZ,
            revoke_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_referral_codes_public_id UNIQUE (public_id),
            CONSTRAINT uq_referral_codes_code UNIQUE (code),
            CONSTRAINT fk_referral_codes_owner FOREIGN KEY (owner_user_id) REFERENCES users (id),
            CONSTRAINT ck_referral_codes_status CHECK (status IN ('active', 'revoked')),
            CONSTRAINT ck_referral_codes_format CHECK (code ~ '^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{8}$'),
            CONSTRAINT ck_referral_codes_revoked CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_referral_codes_one_active_per_owner ON referral_codes (owner_user_id) "
        "WHERE status = 'active'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.referral_codes_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'referral_codes rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF (NEW.code, NEW.owner_user_id, NEW.public_id, NEW.created_at)
               IS DISTINCT FROM (OLD.code, OLD.owner_user_id, OLD.public_id, OLD.created_at) THEN
                RAISE EXCEPTION 'referral_codes: code and owner never change'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
                RAISE EXCEPTION 'referral_codes: a revoked code stays revoked'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_referral_codes_guard", "referral_codes",
             "TRIGGER trg_referral_codes_guard BEFORE UPDATE OR DELETE ON referral_codes "
             "FOR EACH ROW EXECUTE FUNCTION public.referral_codes_guard()")

    # --- attributions (Q106, Q117) -----------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS referral_attributions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            referee_user_id BIGINT NOT NULL,
            referee_identity_id BIGINT,
            family VARCHAR(32) NOT NULL,
            referrer_user_id BIGINT NOT NULL,
            referral_code_id BIGINT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'attributed',
            attributed_at TIMESTAMPTZ NOT NULL,
            window_started_at TIMESTAMPTZ NOT NULL,
            window_ends_at TIMESTAMPTZ NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            request_hash CHAR(64) NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_referral_attributions_public_id UNIQUE (public_id),
            CONSTRAINT uq_referral_attributions_referee_family UNIQUE (referee_user_id, family),
            CONSTRAINT fk_referral_attributions_referee FOREIGN KEY (referee_user_id) REFERENCES users (id),
            CONSTRAINT fk_referral_attributions_referrer FOREIGN KEY (referrer_user_id) REFERENCES users (id),
            CONSTRAINT fk_referral_attributions_identity FOREIGN KEY (referee_identity_id) REFERENCES promo_identities (id),
            CONSTRAINT fk_referral_attributions_code FOREIGN KEY (referral_code_id) REFERENCES referral_codes (id),
            CONSTRAINT ck_referral_attributions_family CHECK (family IN ({_FAMILIES})),
            CONSTRAINT ck_referral_attributions_not_self CHECK (referrer_user_id <> referee_user_id),
            CONSTRAINT ck_referral_attributions_status CHECK (
                status IN ('attributed', 'qualifying', 'qualified', 'rejected', 'expired')
            ),
            CONSTRAINT ck_referral_attributions_window CHECK (
                window_ends_at = window_started_at + interval '{ATTRIBUTION_WINDOW_SECONDS} seconds'
                AND attributed_at >= window_started_at AND attributed_at < window_ends_at
            ),
            CONSTRAINT ck_referral_attributions_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_referral_attributions_referrer ON referral_attributions (referrer_user_id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.referral_attributions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'referral_attributions rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF (NEW.referee_user_id, NEW.family, NEW.referrer_user_id, NEW.referral_code_id, NEW.attributed_at,
                NEW.window_started_at, NEW.window_ends_at, NEW.idempotency_key, NEW.request_hash, NEW.public_id)
               IS DISTINCT FROM
               (OLD.referee_user_id, OLD.family, OLD.referrer_user_id, OLD.referral_code_id, OLD.attributed_at,
                OLD.window_started_at, OLD.window_ends_at, OLD.idempotency_key, OLD.request_hash, OLD.public_id) THEN
                RAISE EXCEPTION 'referral_attributions: who invited whom never changes'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_referral_attributions_guard", "referral_attributions",
             "TRIGGER trg_referral_attributions_guard BEFORE UPDATE OR DELETE ON referral_attributions "
             "FOR EACH ROW EXECUTE FUNCTION public.referral_attributions_guard()")

    # --- enrollments (Q117, Q118) ------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS promo_enrollments (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            attribution_id BIGINT NOT NULL,
            campaign_id BIGINT NOT NULL,
            campaign_version_id BIGINT NOT NULL,
            family VARCHAR(32) NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            referrer_user_id BIGINT NOT NULL,
            referee_user_id BIGINT NOT NULL,
            referee_identity_id BIGINT NOT NULL,
            terms_fingerprint CHAR(64) NOT NULL,
            enrolled_at TIMESTAMPTZ NOT NULL,
            qualification_deadline TIMESTAMPTZ NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'promised',
            idempotency_key VARCHAR(128) NOT NULL,
            request_hash CHAR(64) NOT NULL,
            decided_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_enrollments_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_enrollments_attribution_campaign UNIQUE (attribution_id, campaign_id),
            CONSTRAINT uq_promo_enrollments_idempotency UNIQUE (referee_user_id, idempotency_key),
            CONSTRAINT fk_promo_enrollments_attribution FOREIGN KEY (attribution_id) REFERENCES referral_attributions (id),
            CONSTRAINT fk_promo_enrollments_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_enrollments_version FOREIGN KEY (campaign_version_id, campaign_id)
                REFERENCES promo_campaign_versions (id, campaign_id),
            CONSTRAINT fk_promo_enrollments_referrer FOREIGN KEY (referrer_user_id) REFERENCES users (id),
            CONSTRAINT fk_promo_enrollments_referee FOREIGN KEY (referee_user_id) REFERENCES users (id),
            CONSTRAINT fk_promo_enrollments_identity FOREIGN KEY (referee_identity_id) REFERENCES promo_identities (id),
            CONSTRAINT ck_promo_enrollments_family CHECK (family IN ({_FAMILIES})),
            CONSTRAINT ck_promo_enrollments_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_promo_enrollments_status CHECK (status IN ('promised', 'granted', 'released')),
            CONSTRAINT ck_promo_enrollments_deadline CHECK (qualification_deadline > enrolled_at),
            CONSTRAINT ck_promo_enrollments_not_self CHECK (referrer_user_id <> referee_user_id),
            CONSTRAINT ck_promo_enrollments_version CHECK (version >= 1)
        )
        """
    )
    # Q106/Q117: one live "new client" (or "new driver") enrollment per person, whichever service it came through.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_enrollments_identity_family ON promo_enrollments "
        "(referee_identity_id, family) WHERE status <> 'released'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_enrollments_user_family ON promo_enrollments "
        "(referee_user_id, family) WHERE status <> 'released'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_enrollments_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_enrollments rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'promised' THEN
                    RAISE EXCEPTION 'promo_enrollments are created as promised'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.attribution_id, NEW.campaign_id, NEW.campaign_version_id, NEW.family, NEW.service_type,
                NEW.referrer_user_id, NEW.referee_user_id, NEW.referee_identity_id, NEW.terms_fingerprint,
                NEW.enrolled_at, NEW.qualification_deadline, NEW.idempotency_key, NEW.request_hash, NEW.public_id)
               IS DISTINCT FROM
               (OLD.attribution_id, OLD.campaign_id, OLD.campaign_version_id, OLD.family, OLD.service_type,
                OLD.referrer_user_id, OLD.referee_user_id, OLD.referee_identity_id, OLD.terms_fingerprint,
                OLD.enrolled_at, OLD.qualification_deadline, OLD.idempotency_key, OLD.request_hash, OLD.public_id) THEN
                RAISE EXCEPTION 'promo_enrollments: accepted terms are immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status <> OLD.status AND NOT (OLD.status = 'promised' AND NEW.status IN ('granted', 'released')) THEN
                RAISE EXCEPTION 'promo_enrollments: % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_enrollments_guard", "promo_enrollments",
             "TRIGGER trg_promo_enrollments_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_enrollments "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_enrollments_guard()")

    # --- obligations know their enrollment ---------------------------------------------------------------------
    _add_column("promo_obligations", "enrollment_id", "BIGINT")
    _add_constraint("promo_obligations", "fk_promo_obligations_enrollment",
                    "FOREIGN KEY (enrollment_id) REFERENCES promo_enrollments (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_promo_obligations_enrollment ON promo_obligations (enrollment_id)")
    # enrollment_id joins the immutable obligation terms (0084 guard compares a fixed column list; this one adds it)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_obligations_enrollment_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.enrollment_id IS DISTINCT FROM OLD.enrollment_id THEN
                RAISE EXCEPTION 'promo_obligations.enrollment_id is immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_obligations_enrollment_frozen", "promo_obligations",
             "TRIGGER trg_promo_obligations_enrollment_frozen BEFORE UPDATE ON promo_obligations "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_obligations_enrollment_frozen()")


def downgrade() -> None:
    """Dev/test only (ADR-0016). Never a production rollback."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_promo_obligations_enrollment_frozen ON promo_obligations")
    op.execute("DROP FUNCTION IF EXISTS public.promo_obligations_enrollment_frozen()")
    op.execute("DROP INDEX IF EXISTS ix_promo_obligations_enrollment")
    op.execute("ALTER TABLE promo_obligations DROP CONSTRAINT IF EXISTS fk_promo_obligations_enrollment")
    op.execute("ALTER TABLE promo_obligations DROP COLUMN IF EXISTS enrollment_id")
    for table in ("promo_enrollments", "referral_attributions", "referral_codes", "promo_identity_digests", "promo_identities"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for function in ("promo_enrollments_guard", "referral_attributions_guard", "referral_codes_guard"):
        op.execute(f"DROP FUNCTION IF EXISTS public.{function}() CASCADE")
