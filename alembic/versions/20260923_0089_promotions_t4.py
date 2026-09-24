"""promotions T4 decisions: campaign combinations, bound client readiness, cancel fault per owner (Q123-Q129)

Owner: referral stage 5 (ADR-0023 §18.1, Q123-Q129) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promo_campaign_combinations`` (Q123) - an explicit, audited approval that a passenger-bonus campaign and a
    driver-credit campaign may meet on one booking, with the cost basis of their O: ``shared`` (both O describe the
    same booking cost - the larger is taken) or ``additive`` (each campaign carries its own cost - they are summed).
    Unordered pair stored as ``campaign_low_id < campaign_high_id``; at most one active row per pair; rows are never
    deleted and change only ``active -> revoked`` (trigger). No row = the combination is not allowed.
  * ``promo_booking_terms.passenger_campaign_id / driver_campaign_id / combination_cost_basis`` (Q123) - which single
    campaign funds P and which funds H on each agreement. ``NOT VALID`` CHECK: a discount names its campaign and two
    different campaigns name their cost basis (rows written before 0089 are left as they are).
  * ``promo_consents.passenger_campaign_id`` and ``session_ref`` (Q123, Q126) - the consent is bound to one P campaign
    and to the login session (``sid``) that gave it.
  * ``promo_party_readiness`` (Q126) - the passive party's readiness for one proposal version or one amendment: user,
    side, login session, declared features, the driver's acknowledged amounts (amendments), expiry. Replaces the
    open-ended "last declaration" as evidence; ``promo_client_features.session_ref`` keeps the last declaration only
    to *detect* a later change of client or session.
  * ``promo_redemptions.release_fault`` gains ``none`` (justified - nobody at fault) and ``undetermined`` (Q129), and
    ``restored_from`` / ``restored_until`` record a grace extension so a later fault decision can undo only the part
    that was not spent.
  * ``promo_reviews`` kinds ``cancel_fault`` (Q129) and ``restoration_uncovered`` (Q127).
  * ``promo_booking_terms_verify`` (deferred) additionally checks that every live reservation of an instrument comes
    from the campaign named for it in the latest terms.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260923_0089
Revises: 20260923_0088
Create Date: 2026-09-23 00:89:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0089"
down_revision: str = "20260923_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
REVIEW_KINDS = ("identity_match", "qualification_risk", "post_grant_recheck", "party_not_active", "reinstate_unfulfilled",
                "cancel_fault", "restoration_uncovered")
FAULTS = ("client", "driver", "platform", "none", "undetermined")
COST_BASES = ("shared", "additive")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


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
        $$
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- Q123: explicit campaign combinations -----------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS promo_campaign_combinations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            campaign_low_id BIGINT NOT NULL,
            campaign_high_id BIGINT NOT NULL,
            cost_basis VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            reason TEXT NOT NULL,
            created_by BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_by BIGINT,
            revoked_at TIMESTAMPTZ,
            revoke_reason TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_promo_campaign_combinations_public_id UNIQUE (public_id),
            CONSTRAINT fk_promo_campaign_combinations_low FOREIGN KEY (campaign_low_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_campaign_combinations_high FOREIGN KEY (campaign_high_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_campaign_combinations_created_by FOREIGN KEY (created_by) REFERENCES users (id),
            CONSTRAINT fk_promo_campaign_combinations_revoked_by FOREIGN KEY (revoked_by) REFERENCES users (id),
            CONSTRAINT ck_promo_campaign_combinations_pair CHECK (campaign_low_id < campaign_high_id),
            CONSTRAINT ck_promo_campaign_combinations_basis CHECK (cost_basis IN {_in(COST_BASES)}),
            CONSTRAINT ck_promo_campaign_combinations_status CHECK (status IN ('active', 'revoked')),
            CONSTRAINT ck_promo_campaign_combinations_reason CHECK (length(btrim(reason)) > 0),
            CONSTRAINT ck_promo_campaign_combinations_revoked CHECK (
                (status = 'revoked') = (revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason IS NOT NULL)
            ),
            CONSTRAINT ck_promo_campaign_combinations_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_campaign_combinations_active ON promo_campaign_combinations "
        "(campaign_low_id, campaign_high_id) WHERE status = 'active'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_campaign_combinations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_campaign_combinations rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'a campaign combination is created active'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.public_id, NEW.campaign_low_id, NEW.campaign_high_id, NEW.cost_basis, NEW.reason, NEW.created_by,
                NEW.created_at) IS DISTINCT FROM
               (OLD.public_id, OLD.campaign_low_id, OLD.campaign_high_id, OLD.cost_basis, OLD.reason, OLD.created_by,
                OLD.created_at) THEN
                RAISE EXCEPTION 'a campaign combination is immutable; revoke it and approve a new one'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NOT (OLD.status = 'active' AND NEW.status = 'revoked') THEN
                RAISE EXCEPTION 'promo_campaign_combinations: % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_campaign_combinations_guard", "promo_campaign_combinations",
             "TRIGGER trg_promo_campaign_combinations_guard BEFORE INSERT OR UPDATE OR DELETE ON "
             "promo_campaign_combinations FOR EACH ROW EXECUTE FUNCTION public.promo_campaign_combinations_guard()")

    # --- Q123: one campaign per instrument on each agreement ---------------------------------------------------
    op.execute("ALTER TABLE promo_booking_terms ADD COLUMN IF NOT EXISTS passenger_campaign_id BIGINT")
    op.execute("ALTER TABLE promo_booking_terms ADD COLUMN IF NOT EXISTS driver_campaign_id BIGINT")
    op.execute("ALTER TABLE promo_booking_terms ADD COLUMN IF NOT EXISTS combination_cost_basis VARCHAR(16)")
    _add_constraint("promo_booking_terms", "fk_promo_booking_terms_passenger_campaign",
                    "FOREIGN KEY (passenger_campaign_id) REFERENCES promo_campaigns (id)")
    _add_constraint("promo_booking_terms", "fk_promo_booking_terms_driver_campaign",
                    "FOREIGN KEY (driver_campaign_id) REFERENCES promo_campaigns (id)")
    _add_constraint("promo_booking_terms", "ck_promo_booking_terms_campaigns", f"""CHECK (
                (passenger_bonus_minor = 0 OR passenger_campaign_id IS NOT NULL)
                AND (driver_credit_minor = 0 OR driver_campaign_id IS NOT NULL)
                AND (combination_cost_basis IS NULL OR combination_cost_basis IN {_in(COST_BASES)})
                AND (passenger_campaign_id IS NULL OR driver_campaign_id IS NULL
                     OR passenger_campaign_id = driver_campaign_id OR combination_cost_basis IS NOT NULL)
            ) NOT VALID""")

    # --- Q123/Q126: consent bound to one campaign and one login session ------------------------------------------
    op.execute("ALTER TABLE promo_consents ADD COLUMN IF NOT EXISTS passenger_campaign_id BIGINT")
    op.execute("ALTER TABLE promo_consents ADD COLUMN IF NOT EXISTS session_ref VARCHAR(64)")
    _add_constraint("promo_consents", "fk_promo_consents_passenger_campaign",
                    "FOREIGN KEY (passenger_campaign_id) REFERENCES promo_campaigns (id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_consents_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_consents rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'promo_consents are created active'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.public_id, NEW.client_user_id, NEW.proposal_version_id, NEW.amendment_id, NEW.service_type,
                NEW.contract_version, NEW.fare_minor, NEW.passenger_bonus_minor, NEW.cash_due_minor,
                NEW.quote_fingerprint, NEW.client_features, NEW.expires_at, NEW.created_at,
                NEW.passenger_campaign_id, NEW.session_ref)
               IS DISTINCT FROM
               (OLD.public_id, OLD.client_user_id, OLD.proposal_version_id, OLD.amendment_id, OLD.service_type,
                OLD.contract_version, OLD.fare_minor, OLD.passenger_bonus_minor, OLD.cash_due_minor,
                OLD.quote_fingerprint, OLD.client_features, OLD.expires_at, OLD.created_at,
                OLD.passenger_campaign_id, OLD.session_ref) THEN
                RAISE EXCEPTION 'promo_consents terms are immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF OLD.booking_id IS NOT NULL AND NEW.booking_id IS DISTINCT FROM OLD.booking_id THEN
                RAISE EXCEPTION 'promo_consents booking link is immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status <> OLD.status AND NOT (OLD.status = 'active' AND NEW.status IN ('used', 'superseded')) THEN
                RAISE EXCEPTION 'promo_consents: % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status = 'used' AND NEW.booking_id IS NULL THEN
                RAISE EXCEPTION 'a used consent names its booking'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    # --- Q126: the passive party's readiness, bound to a version/amendment, a session and an expiry -------------
    op.execute("ALTER TABLE promo_client_features ADD COLUMN IF NOT EXISTS session_ref VARCHAR(64)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_party_readiness (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id BIGINT NOT NULL,
            side VARCHAR(16) NOT NULL,
            proposal_version_id BIGINT,
            amendment_id BIGINT,
            session_ref VARCHAR(64),
            features JSONB NOT NULL DEFAULT '[]'::jsonb,
            acknowledged JSONB,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_promo_party_readiness_user FOREIGN KEY (user_id) REFERENCES users (id),
            CONSTRAINT fk_promo_party_readiness_version FOREIGN KEY (proposal_version_id) REFERENCES proposal_versions (id),
            CONSTRAINT fk_promo_party_readiness_amendment FOREIGN KEY (amendment_id) REFERENCES booking_amendments (id),
            CONSTRAINT ck_promo_party_readiness_subject CHECK ((proposal_version_id IS NULL) <> (amendment_id IS NULL)),
            CONSTRAINT ck_promo_party_readiness_side CHECK (side IN ('client', 'driver')),
            CONSTRAINT ck_promo_party_readiness_status CHECK (status IN ('active', 'superseded')),
            CONSTRAINT ck_promo_party_readiness_features CHECK (jsonb_typeof(features) = 'array'),
            CONSTRAINT ck_promo_party_readiness_ack CHECK (acknowledged IS NULL OR jsonb_typeof(acknowledged) = 'object')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_party_readiness_version ON promo_party_readiness "
        "(proposal_version_id, user_id) WHERE status = 'active' AND proposal_version_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_party_readiness_amendment ON promo_party_readiness "
        "(amendment_id, user_id) WHERE status = 'active' AND amendment_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_party_readiness_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_party_readiness rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'readiness is recorded active'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.user_id, NEW.side, NEW.proposal_version_id, NEW.amendment_id, NEW.session_ref, NEW.features,
                NEW.acknowledged, NEW.expires_at, NEW.created_at) IS DISTINCT FROM
               (OLD.user_id, OLD.side, OLD.proposal_version_id, OLD.amendment_id, OLD.session_ref, OLD.features,
                OLD.acknowledged, OLD.expires_at, OLD.created_at)
               OR NOT (OLD.status = 'active' AND NEW.status = 'superseded') THEN
                RAISE EXCEPTION 'readiness evidence is immutable; a new confirmation supersedes it'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_party_readiness_guard", "promo_party_readiness",
             "TRIGGER trg_promo_party_readiness_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_party_readiness "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_party_readiness_guard()")

    # --- Q129: fault per owner, undetermined kept open, grace extension recorded -------------------------------
    op.execute("ALTER TABLE promo_redemptions ADD COLUMN IF NOT EXISTS restored_from TIMESTAMPTZ")
    op.execute("ALTER TABLE promo_redemptions ADD COLUMN IF NOT EXISTS restored_until TIMESTAMPTZ")
    op.execute("ALTER TABLE promo_redemptions DROP CONSTRAINT IF EXISTS ck_promo_redemptions_fault")
    op.execute(
        f"""ALTER TABLE promo_redemptions ADD CONSTRAINT ck_promo_redemptions_fault CHECK (
            (status = 'released') = (release_fault IS NOT NULL)
            AND (release_fault IS NULL OR release_fault IN {_in(FAULTS)}))"""
    )
    _add_constraint("promo_redemptions", "ck_promo_redemptions_restored",
                    "CHECK ((restored_from IS NULL) = (restored_until IS NULL) "
                    "AND (restored_until IS NULL OR restored_until > restored_from))")

    # --- review kinds (Q127, Q129) ---------------------------------------------------------------------------
    op.execute("ALTER TABLE promo_reviews DROP CONSTRAINT IF EXISTS ck_promo_reviews_kind")
    op.execute(f"ALTER TABLE promo_reviews ADD CONSTRAINT ck_promo_reviews_kind CHECK (kind IN {_in(REVIEW_KINDS)})")

    # --- deferred money check: + one campaign per instrument (Q123) ---------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_booking_terms_verify() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            target BIGINT;
            b RECORD;
            t public.promo_booking_terms%ROWTYPE;
            h RECORD;
            applied BOOLEAN;
            reserved_p BIGINT; reserved_h BIGINT; consumed_p BIGINT; consumed_h BIGINT;
        BEGIN
            target := CASE WHEN TG_TABLE_NAME = 'bookings' THEN (to_jsonb(NEW) ->> 'id')::bigint
                           ELSE (to_jsonb(NEW) ->> 'booking_id')::bigint END;
            IF target IS NULL THEN
                RETURN NULL;
            END IF;
            SELECT id, total_minor, commission_minor, fee_bps, terms_snapshot INTO b FROM public.bookings WHERE id = target;
            IF b.id IS NULL THEN
                RETURN NULL;
            END IF;
            applied := coalesce(b.terms_snapshot -> 'promo' ->> 'applied', 'false') = 'true';
            SELECT * INTO t FROM public.promo_booking_terms WHERE booking_id = target ORDER BY seq DESC LIMIT 1;
            IF NOT (b.terms_snapshot ? 'promo') THEN
                IF t.id IS NOT NULL THEN
                    RAISE EXCEPTION 'legacy booking % cannot carry promo terms', target
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
                END IF;
                RETURN NULL;
            END IF;
            IF NOT applied THEN
                IF t.id IS NOT NULL THEN
                    RAISE EXCEPTION 'booking % has promo terms but is not marked as a promo booking', target
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
                END IF;
                IF EXISTS (SELECT 1 FROM public.promo_redemptions WHERE booking_id = target AND status <> 'released') THEN
                    RAISE EXCEPTION 'booking % spends promo value without promo terms', target
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
                END IF;
                RETURN NULL;
            END IF;
            IF t.id IS NULL THEN
                RAISE EXCEPTION 'promo booking % has no promo terms', target
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
            END IF;
            IF (t.fare_minor, t.fee_bps, t.base_commission_minor) IS DISTINCT FROM (b.total_minor, b.fee_bps, b.commission_minor) THEN
                RAISE EXCEPTION 'promo terms of booking % differ from its agreement (F, bps, C)', target
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
            END IF;
            SELECT id, status, amount_minor INTO h FROM public.wallet_holds
             WHERE booking_id = target AND charge_kind = 'commission';
            IF h.id IS NULL OR h.amount_minor <> t.net_commission_minor THEN
                RAISE EXCEPTION 'commission hold of promo booking % is not C_net', target
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
            END IF;
            SELECT COALESCE(SUM(r.amount_minor) FILTER (WHERE r.status = 'reserved' AND l.instrument = 'passenger_bonus'), 0),
                   COALESCE(SUM(r.amount_minor) FILTER (WHERE r.status = 'reserved' AND l.instrument = 'driver_credit'), 0),
                   COALESCE(SUM(r.amount_minor) FILTER (WHERE r.status = 'consumed' AND l.instrument = 'passenger_bonus'), 0),
                   COALESCE(SUM(r.amount_minor) FILTER (WHERE r.status = 'consumed' AND l.instrument = 'driver_credit'), 0)
              INTO reserved_p, reserved_h, consumed_p, consumed_h
              FROM public.promo_redemptions r JOIN public.promo_lots l ON l.id = r.lot_id
             WHERE r.booking_id = target;
            IF (h.status = 'active' AND (reserved_p, reserved_h, consumed_p, consumed_h)
                    IS DISTINCT FROM (t.passenger_bonus_minor, t.driver_credit_minor, 0::bigint, 0::bigint))
               OR (h.status = 'captured' AND (reserved_p, reserved_h, consumed_p, consumed_h)
                    IS DISTINCT FROM (0::bigint, 0::bigint, t.passenger_bonus_minor, t.driver_credit_minor))
               OR (h.status = 'released' AND (reserved_p + reserved_h + consumed_p + consumed_h) <> 0) THEN
                RAISE EXCEPTION 'promo redemptions of booking % differ from P/H of its terms (hold %)', target, h.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
            END IF;
            -- Q123: P comes from exactly the campaign named for it, H likewise (terms written from 0089 on)
            IF EXISTS (
                SELECT 1 FROM public.promo_redemptions r JOIN public.promo_lots l ON l.id = r.lot_id
                 WHERE r.booking_id = target AND r.status <> 'released'
                   AND ((l.instrument = 'passenger_bonus' AND t.passenger_campaign_id IS NOT NULL
                         AND l.campaign_id <> t.passenger_campaign_id)
                     OR (l.instrument = 'driver_credit' AND t.driver_campaign_id IS NOT NULL
                         AND l.campaign_id <> t.driver_campaign_id))
            ) THEN
                RAISE EXCEPTION 'promo booking % spends an instrument from a campaign its terms do not name', target
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_booking_terms_mismatch';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )


def downgrade() -> None:
    """Dev/test tool only (ADR-0016): not a rollback strategy. The 0087 verify function is not restored."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE promo_reviews DROP CONSTRAINT IF EXISTS ck_promo_reviews_kind")
    op.execute(
        "ALTER TABLE promo_reviews ADD CONSTRAINT ck_promo_reviews_kind CHECK (kind IN ('identity_match', "
        "'qualification_risk', 'post_grant_recheck', 'party_not_active', 'reinstate_unfulfilled'))"
    )
    op.execute("ALTER TABLE promo_redemptions DROP CONSTRAINT IF EXISTS ck_promo_redemptions_restored")
    op.execute("ALTER TABLE promo_redemptions DROP COLUMN IF EXISTS restored_until")
    op.execute("ALTER TABLE promo_redemptions DROP COLUMN IF EXISTS restored_from")
    op.execute("DROP TABLE IF EXISTS promo_party_readiness")
    op.execute("DROP FUNCTION IF EXISTS public.promo_party_readiness_guard() CASCADE")
    op.execute("ALTER TABLE promo_client_features DROP COLUMN IF EXISTS session_ref")
    op.execute("ALTER TABLE promo_booking_terms DROP CONSTRAINT IF EXISTS ck_promo_booking_terms_campaigns")
    for column in ("passenger_campaign_id", "driver_campaign_id", "combination_cost_basis"):
        op.execute(f"ALTER TABLE promo_booking_terms DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS promo_campaign_combinations")
    op.execute("DROP FUNCTION IF EXISTS public.promo_campaign_combinations_guard() CASCADE")
