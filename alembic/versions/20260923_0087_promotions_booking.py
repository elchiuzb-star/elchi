"""promotions booking integration: consent, booking promo terms, client features, deferred money checks (stage 4)

Owner: referral stage 4 (ADR-0023 §18; Q104, Q110, Q111, Q116, Q120-Q122) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promo_consents`` - the client's consent to spend passenger bonus: user, proposal version *or* amendment, service
    type, F, P, F_cash, quote fingerprint, contract version, the client's declared features, expiry. One active consent
    per proposal version / amendment; amounts immutable; ``active -> used | superseded`` only (trigger).
  * ``promo_booking_terms`` - the immutable financial snapshot of a promo booking (append-only, one row per agreement:
    ``seq`` 1 at accept, ``seq`` n per accepted amendment). ``bookings.commission_minor`` stays C; F_cash, P, H, C_net,
    O and M live here. CHECKs repeat the identities F_cash = F - P, C_net = C - P - H and the promo margin floor.
  * ``promo_client_features`` - what each user's client last declared in ``X-Elchi-Client-Features`` (a rendering
    capability, never an authority, Q110) so the counterparty of a new promo deal is known.
  * ``promo_redemptions.terms_seq`` - which agreement a reservation belongs to; the unique key becomes
    ``(lot_id, booking_id, terms_seq)`` so an amendment can re-reserve the same lot atomically.
  * ``promo_reviews`` kind ``reinstate_unfulfilled`` (Q122).
  * Deferred money check ``promo_booking_terms_verify`` (constraint triggers on bookings, promo_booking_terms,
    promo_redemptions and wallet_holds). A legacy booking (no ``terms_snapshot.promo`` marker) never has terms; a
    stage-4 plain booking has neither terms nor live redemptions; a booking marked applied has terms; the latest terms
    match the booking's F, bps and C; the commission hold equals C_net; live redemptions equal P and H by instrument
    (reserved while held, consumed once captured, none after release); a booking not marked applied has no terms.
  * ``promo_booking_finance`` - internal read-only report view: F, C, P, H, F_cash, C_net, hold status, captured and
    reversed real money, consumed P and H, per promo booking.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260923_0087
Revises: 20260923_0086
Create Date: 2026-09-23 00:87:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0087"
down_revision: str = "20260923_0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
REVIEW_KINDS = ("identity_match", "qualification_risk", "post_grant_recheck", "party_not_active", "reinstate_unfulfilled")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- client features (Q110) ------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_client_features (
            user_id BIGINT PRIMARY KEY,
            features JSONB NOT NULL DEFAULT '[]'::jsonb,
            declared_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT fk_promo_client_features_user FOREIGN KEY (user_id) REFERENCES users (id),
            CONSTRAINT ck_promo_client_features_array CHECK (jsonb_typeof(features) = 'array')
        )
        """
    )

    # --- consent (Q104) --------------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_consents (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            client_user_id BIGINT NOT NULL,
            proposal_version_id BIGINT,
            amendment_id BIGINT,
            booking_id BIGINT,
            service_type VARCHAR(16) NOT NULL,
            contract_version SMALLINT NOT NULL,
            fare_minor BIGINT NOT NULL,
            passenger_bonus_minor BIGINT NOT NULL,
            cash_due_minor BIGINT NOT NULL,
            quote_fingerprint CHAR(64) NOT NULL,
            client_features JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_consents_public_id UNIQUE (public_id),
            CONSTRAINT fk_promo_consents_client FOREIGN KEY (client_user_id) REFERENCES users (id),
            CONSTRAINT fk_promo_consents_version FOREIGN KEY (proposal_version_id) REFERENCES proposal_versions (id),
            CONSTRAINT fk_promo_consents_amendment FOREIGN KEY (amendment_id) REFERENCES booking_amendments (id),
            CONSTRAINT fk_promo_consents_booking FOREIGN KEY (booking_id) REFERENCES bookings (id),
            CONSTRAINT ck_promo_consents_subject CHECK ((proposal_version_id IS NULL) <> (amendment_id IS NULL)),
            CONSTRAINT ck_promo_consents_amendment_booking CHECK (amendment_id IS NULL OR booking_id IS NOT NULL),
            CONSTRAINT ck_promo_consents_amounts CHECK (
                fare_minor > 0 AND passenger_bonus_minor > 0 AND cash_due_minor >= 0
                AND cash_due_minor = fare_minor - passenger_bonus_minor
            ),
            CONSTRAINT ck_promo_consents_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_promo_consents_status CHECK (status IN ('active', 'used', 'superseded')),
            CONSTRAINT ck_promo_consents_used CHECK ((status = 'used') = (used_at IS NOT NULL)),
            CONSTRAINT ck_promo_consents_features CHECK (jsonb_typeof(client_features) = 'array')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_consents_active_version ON promo_consents (proposal_version_id) "
        "WHERE status = 'active' AND proposal_version_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_consents_active_amendment ON promo_consents (amendment_id) "
        "WHERE status = 'active' AND amendment_id IS NOT NULL"
    )
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
                NEW.quote_fingerprint, NEW.client_features, NEW.expires_at, NEW.created_at)
               IS DISTINCT FROM
               (OLD.public_id, OLD.client_user_id, OLD.proposal_version_id, OLD.amendment_id, OLD.service_type,
                OLD.contract_version, OLD.fare_minor, OLD.passenger_bonus_minor, OLD.cash_due_minor,
                OLD.quote_fingerprint, OLD.client_features, OLD.expires_at, OLD.created_at) THEN
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
    _trigger("trg_promo_consents_guard", "promo_consents",
             "TRIGGER trg_promo_consents_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_consents "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_consents_guard()")

    # --- booking promo terms (immutable financial snapshot) --------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_booking_terms (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL,
            seq INTEGER NOT NULL,
            amendment_id BIGINT,
            consent_id BIGINT,
            contract_version SMALLINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            fare_minor BIGINT NOT NULL,
            fee_bps INTEGER NOT NULL,
            base_commission_minor BIGINT NOT NULL,
            passenger_bonus_minor BIGINT NOT NULL,
            driver_credit_minor BIGINT NOT NULL,
            cash_due_minor BIGINT NOT NULL,
            net_commission_minor BIGINT NOT NULL,
            variable_cost_minor BIGINT,
            min_margin_minor BIGINT,
            quote_fingerprint CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_booking_terms_booking_seq UNIQUE (booking_id, seq),
            CONSTRAINT fk_promo_booking_terms_booking FOREIGN KEY (booking_id) REFERENCES bookings (id),
            CONSTRAINT fk_promo_booking_terms_amendment FOREIGN KEY (amendment_id) REFERENCES booking_amendments (id),
            CONSTRAINT fk_promo_booking_terms_consent FOREIGN KEY (consent_id) REFERENCES promo_consents (id),
            CONSTRAINT ck_promo_booking_terms_seq CHECK (seq >= 1 AND ((seq = 1) = (amendment_id IS NULL))),
            CONSTRAINT ck_promo_booking_terms_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_promo_booking_terms_identities CHECK (
                fare_minor > 0 AND fee_bps > 0 AND base_commission_minor > 0
                AND passenger_bonus_minor >= 0 AND driver_credit_minor >= 0
                AND (passenger_bonus_minor + driver_credit_minor > 0 OR seq > 1)
                AND cash_due_minor = fare_minor - passenger_bonus_minor AND cash_due_minor >= 0
                AND net_commission_minor = base_commission_minor - passenger_bonus_minor - driver_credit_minor
            ),
            -- an amendment may shrink the discount to nothing (Q116: never grow it); a row with a discount keeps the floor
            CONSTRAINT ck_promo_booking_terms_margin CHECK (
                passenger_bonus_minor + driver_credit_minor = 0 OR (
                variable_cost_minor IS NOT NULL AND variable_cost_minor >= 0
                AND min_margin_minor IS NOT NULL AND min_margin_minor > 0
                AND net_commission_minor > 0
                AND net_commission_minor - variable_cost_minor >= min_margin_minor)
            ),
            CONSTRAINT ck_promo_booking_terms_consent CHECK (passenger_bonus_minor = 0 OR consent_id IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_booking_terms_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'promo_booking_terms rows are immutable; an amendment appends a new seq'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
        END;
        $$
        """
    )
    _trigger("trg_promo_booking_terms_append_only", "promo_booking_terms",
             "TRIGGER trg_promo_booking_terms_append_only BEFORE UPDATE OR DELETE ON promo_booking_terms "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_booking_terms_append_only()")
    _trigger("trg_promo_booking_terms_no_truncate", "promo_booking_terms",
             "TRIGGER trg_promo_booking_terms_no_truncate BEFORE TRUNCATE ON promo_booking_terms "
             "FOR EACH STATEMENT EXECUTE FUNCTION public.promo_booking_terms_append_only()")

    # --- redemptions belong to one agreement ------------------------------------------------------------------
    op.execute("ALTER TABLE promo_redemptions ADD COLUMN IF NOT EXISTS terms_seq INTEGER NOT NULL DEFAULT 1")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_promo_redemptions_terms_seq') THEN
                ALTER TABLE promo_redemptions ADD CONSTRAINT ck_promo_redemptions_terms_seq CHECK (terms_seq >= 1);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_promo_redemptions_lot_booking_seq') THEN
                ALTER TABLE promo_redemptions
                    ADD CONSTRAINT uq_promo_redemptions_lot_booking_seq UNIQUE (lot_id, booking_id, terms_seq);
            END IF;
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_promo_redemptions_lot_booking') THEN
                ALTER TABLE promo_redemptions DROP CONSTRAINT uq_promo_redemptions_lot_booking;
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_redemptions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_redemptions rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'reserved' THEN
                    RAISE EXCEPTION 'promo_redemptions are created as reserved'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.lot_id, NEW.booking_id, NEW.amount_minor, NEW.public_id, NEW.terms_seq)
               IS DISTINCT FROM (OLD.lot_id, OLD.booking_id, OLD.amount_minor, OLD.public_id, OLD.terms_seq) THEN
                RAISE EXCEPTION 'promo_redemptions identity and amount are immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status <> OLD.status AND NOT (OLD.status = 'reserved' AND NEW.status IN ('consumed', 'released')) THEN
                RAISE EXCEPTION 'promo_redemptions: % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    # --- review kinds (Q122) ---------------------------------------------------------------------------------
    op.execute("ALTER TABLE promo_reviews DROP CONSTRAINT IF EXISTS ck_promo_reviews_kind")
    op.execute(f"ALTER TABLE promo_reviews ADD CONSTRAINT ck_promo_reviews_kind CHECK (kind IN {_in(REVIEW_KINDS)})")

    # --- deferred money check ---------------------------------------------------------------------------------
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
                -- legacy booking (accepted before stage 4): P = H = 0 by definition, it can never carry terms
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
            RETURN NULL;
        END;
        $$
        """
    )
    for table, events in (
        ("bookings", "INSERT OR UPDATE OF total_minor, commission_minor, fee_bps, terms_snapshot"),
        ("promo_booking_terms", "INSERT"),
        ("promo_redemptions", "INSERT OR UPDATE"),
        ("wallet_holds", "INSERT OR UPDATE OF status, amount_minor"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_promo_terms_verify ON {table}")
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_promo_terms_verify AFTER {events} ON {table} "
            f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.promo_booking_terms_verify()"
        )

    # --- internal finance report (ADR-0023 §6, stage 4) --------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW promo_booking_finance AS
        SELECT t.booking_id, t.seq AS terms_seq, t.currency,
               t.fare_minor, t.base_commission_minor, t.passenger_bonus_minor, t.driver_credit_minor,
               t.cash_due_minor, t.net_commission_minor,
               h.status AS hold_status, h.captured_minor, h.reversed_minor,
               COALESCE(r.consumed_p, 0) AS consumed_passenger_bonus_minor,
               COALESCE(r.consumed_h, 0) AS consumed_driver_credit_minor
          FROM promo_booking_terms t
          JOIN (SELECT booking_id, max(seq) AS seq FROM promo_booking_terms GROUP BY booking_id) latest
            ON latest.booking_id = t.booking_id AND latest.seq = t.seq
          LEFT JOIN wallet_holds h ON h.booking_id = t.booking_id AND h.charge_kind = 'commission'
          LEFT JOIN (SELECT rr.booking_id,
                            SUM(rr.amount_minor) FILTER (WHERE rr.status = 'consumed' AND l.instrument = 'passenger_bonus') AS consumed_p,
                            SUM(rr.amount_minor) FILTER (WHERE rr.status = 'consumed' AND l.instrument = 'driver_credit') AS consumed_h
                       FROM promo_redemptions rr JOIN promo_lots l ON l.id = rr.lot_id
                      GROUP BY rr.booking_id) r ON r.booking_id = t.booking_id
        """
    )


def downgrade() -> None:
    """Dev/test tool only (ADR-0016): not a rollback strategy."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP VIEW IF EXISTS promo_booking_finance")
    for table in ("bookings", "promo_booking_terms", "promo_redemptions", "wallet_holds"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_promo_terms_verify ON {table}")
    op.execute("DROP FUNCTION IF EXISTS public.promo_booking_terms_verify() CASCADE")
    op.execute("ALTER TABLE promo_reviews DROP CONSTRAINT IF EXISTS ck_promo_reviews_kind")
    op.execute(
        "ALTER TABLE promo_reviews ADD CONSTRAINT ck_promo_reviews_kind CHECK (kind IN "
        "('identity_match', 'qualification_risk', 'post_grant_recheck', 'party_not_active'))"
    )
    op.execute("DROP TABLE IF EXISTS promo_booking_terms")
    op.execute("DROP FUNCTION IF EXISTS public.promo_booking_terms_append_only() CASCADE")
    op.execute("DROP TABLE IF EXISTS promo_consents")
    op.execute("DROP FUNCTION IF EXISTS public.promo_consents_guard() CASCADE")
    op.execute("DROP TABLE IF EXISTS promo_client_features")
    op.execute("ALTER TABLE promo_redemptions DROP CONSTRAINT IF EXISTS uq_promo_redemptions_lot_booking_seq")
    op.execute("ALTER TABLE promo_redemptions DROP CONSTRAINT IF EXISTS ck_promo_redemptions_terms_seq")
    op.execute("ALTER TABLE promo_redemptions ADD CONSTRAINT uq_promo_redemptions_lot_booking UNIQUE (lot_id, booking_id)")
    op.execute("ALTER TABLE promo_redemptions DROP COLUMN IF EXISTS terms_seq")
