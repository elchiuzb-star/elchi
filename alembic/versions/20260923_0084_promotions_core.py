"""promotions core: campaigns, immutable versions, budget, immutable promo ledger, obligations, lots, redemptions

Owner: referral stage 1 (ADR-0023, Q101-Q116) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promotions_enabled`` flag key (production default OFF, Q101). Enabling it in production needs an approval
    reference, the admin-API source marker (Q72 pattern) and a passed Q48 gate - checked by a new trigger; the
    existing flag triggers and the Q48/Q55 gate functions are not changed.
  * ``promo_campaigns`` + immutable ``promo_campaign_versions``. Activation is refused by the DB unless the active
    version has every financial/time parameter set (NULL is never read as 0), M > 0 (Q111) and the budget has an
    allocation (Q105).
  * ``promo_budgets`` - one row per campaign, written only by the promo ledger trigger (``pg_trigger_depth``
    guard, like ``ledger_account_balances`` in 0047). A deferred check compares it with the ledger sums.
  * ``promo_ledger_transactions`` - append-only movements between budget buckets (allocate, reduce_allocation,
    promise, release_promise, grant, consume, release_granted, reinstate). Corrections are new rows. A promise or
    reinstatement that would commit more than the allocation is refused inside the trigger after the budget row
    update, so two concurrent operations can never both take the last remainder. Budget changes are made only by
    active finance/super_admin staff; above ``TWO_PERSON_APPROVAL_THRESHOLD_MINOR`` they need an approved
    ``promo_budget_requests`` row with a different approver (Q17/Q114).
  * ``promo_obligations`` (one beneficiary's reward, unique ``reward_key``), ``promo_lots`` (the grant, one per
    obligation), ``promo_redemptions`` (one lot on one booking, unique ``(lot_id, booking_id)``). Deferred checks
    keep lot reserved/consumed equal to its redemptions; promise -> grant -> consume are stages of one obligation
    and are counted once (Q115).
  * This revision writes nothing to the real money ledger and changes no existing gate (Q55/Q48 untouched).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); single head; downgrade() is a dev/test
tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260923_0084
Revises: 20260922_0083
Create Date: 2026-09-23 00:84:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0084"
down_revision: str = "20260922_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
# app.contracts.money.TWO_PERSON_APPROVAL_THRESHOLD_MINOR (minor units; strictly above needs a second approver).
TWO_PERSON_THRESHOLD_MINOR = 100_000_000

# app.contracts.enums.FeatureFlagKey - the 0033 list plus promotions_enabled (contract: never rename).
_FLAG_KEYS = (
    "passenger_enabled",
    "parcel_enabled",
    "driver_listing_enabled",
    "corridor_matching_enabled",
    "wallet_required",
    "tracking_enabled",
    "card_payments_enabled",
    "promotions_enabled",
)
_OLD_FLAG_KEYS = _FLAG_KEYS[:-1]
_CAMPAIGN_KINDS = (
    "referral_client_client",
    "referral_driver_driver",
    "referral_driver_client",
    "cashback",
    "reactivation",
    "corridor_bonus",
    "loyalty",
)
_FAMILIES = ("client_acquisition", "driver_acquisition", "reactivation", "loyalty")
_LEDGER_KINDS = (
    "allocate",
    "reduce_allocation",
    "promise",
    "release_promise",
    "grant",
    "consume",
    "release_granted",
    "reinstate",
)
_TABLES = (
    "promo_redemptions",
    "promo_lots",
    "promo_ledger_transactions",
    "promo_budget_requests",
    "promo_obligations",
    "promo_budgets",
    "promo_campaign_versions",
    "promo_campaigns",
)


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


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


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _append_only(table: str) -> None:
    """Refuse UPDATE/DELETE (row) and TRUNCATE (statement) for every role."""
    function = f"public.{table}_append_only"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '{table} is append-only (%)', TG_OP
                USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
        END;
        $$
        """
    )
    _trigger(f"trg_{table}_append_only", table,
             f"TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
             f"FOR EACH ROW EXECUTE FUNCTION {function}()")
    _trigger(f"trg_{table}_no_truncate", table,
             f"TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
             f"FOR EACH STATEMENT EXECUTE FUNCTION {function}()")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- flag key + production guard (Q101) ----------------------------------------------------------------
    op.execute("ALTER TABLE feature_flag_values DROP CONSTRAINT IF EXISTS ck_feature_flag_values_flag_key")
    op.execute(
        f"ALTER TABLE feature_flag_values ADD CONSTRAINT ck_feature_flag_values_flag_key "
        f"CHECK (flag_key IN ({_sql_list(_FLAG_KEYS)}))"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_feature_flag_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.flag_key <> 'promotions_enabled' OR NOT NEW.enabled OR NOT geo_production_guard_active() THEN
                RETURN NEW;
            END IF;
            IF NEW.approval_reference IS NULL OR btrim(NEW.approval_reference) = '' THEN
                RAISE EXCEPTION 'feature_flag_values: enabling promotions_enabled in production requires approval_reference'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_flag_enable_refused';
            END IF;
            IF COALESCE(current_setting('elchi.flag_change_source', true), '') <> 'admin_api' THEN
                RAISE EXCEPTION 'feature_flag_values: promotions_enabled can be enabled only through the admin API'
                    USING ERRCODE = '42501', CONSTRAINT = 'flag_enable_source_refused';  -- same as 0057 (Q72)
            END IF;
            IF NOT geo_q48_gate_passed() THEN
                RAISE EXCEPTION 'feature_flag_values: enabling promotions_enabled requires the Q48 gate'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_flag_enable_refused';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_feature_flag_values_promotions_guard", "feature_flag_values",
             "TRIGGER trg_feature_flag_values_promotions_guard BEFORE INSERT OR UPDATE ON feature_flag_values "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_feature_flag_guard()")

    # --- campaigns and immutable versions ----------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS promo_campaigns (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            kind VARCHAR(32) NOT NULL,
            family VARCHAR(32) NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            name VARCHAR(120) NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            active_version_id BIGINT,
            created_by BIGINT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_campaigns_public_id UNIQUE (public_id),
            CONSTRAINT fk_promo_campaigns_created_by FOREIGN KEY (created_by) REFERENCES users (id),
            CONSTRAINT ck_promo_campaigns_kind CHECK (kind IN ({_sql_list(_CAMPAIGN_KINDS)})),
            CONSTRAINT ck_promo_campaigns_family CHECK (family IN ({_sql_list(_FAMILIES)})),
            CONSTRAINT ck_promo_campaigns_kind_family CHECK (
                (kind IN ('referral_client_client', 'referral_driver_client') AND family = 'client_acquisition')
                OR (kind = 'referral_driver_driver' AND family = 'driver_acquisition')
                OR kind NOT IN ('referral_client_client', 'referral_driver_client', 'referral_driver_driver')
            ),
            CONSTRAINT ck_promo_campaigns_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_promo_campaigns_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_promo_campaigns_name CHECK (length(btrim(name)) BETWEEN 1 AND 120),
            CONSTRAINT ck_promo_campaigns_status CHECK (status IN ('draft', 'active', 'paused', 'closed')),
            CONSTRAINT ck_promo_campaigns_active_version CHECK (status IN ('draft', 'closed') OR active_version_id IS NOT NULL),
            CONSTRAINT ck_promo_campaigns_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_campaign_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            campaign_id BIGINT NOT NULL,
            version_no INTEGER NOT NULL,
            referrer_reward_minor BIGINT,
            referee_reward_minor BIGINT,
            referrer_instrument VARCHAR(16),
            referee_instrument VARCHAR(16),
            milestone_thresholds JSONB,
            min_distinct_clients INTEGER,
            enrollment_limit INTEGER,
            qualification_window_s INTEGER,
            reward_validity_s INTEGER,
            review_sla_s INTEGER,
            restoration_grace_s INTEGER,
            max_discount_share_bps INTEGER,
            max_discount_per_booking_minor BIGINT,
            passenger_bonus_max_per_booking_minor BIGINT,
            driver_credit_max_per_booking_minor BIGINT,
            variable_cost_fixed_minor BIGINT,
            variable_cost_bps INTEGER,
            min_margin_minor BIGINT,
            approval_reference TEXT,
            note TEXT,
            created_by BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_campaign_versions_campaign_no UNIQUE (campaign_id, version_no),
            CONSTRAINT uq_promo_campaign_versions_id_campaign UNIQUE (id, campaign_id),
            CONSTRAINT fk_promo_campaign_versions_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_campaign_versions_created_by FOREIGN KEY (created_by) REFERENCES users (id),
            CONSTRAINT ck_promo_campaign_versions_no CHECK (version_no >= 1),
            CONSTRAINT ck_promo_campaign_versions_rewards CHECK (
                (referrer_reward_minor IS NULL OR referrer_reward_minor >= 0)
                AND (referee_reward_minor IS NULL OR referee_reward_minor >= 0)
            ),
            CONSTRAINT ck_promo_campaign_versions_instruments CHECK (
                (referrer_instrument IS NULL OR referrer_instrument IN ('passenger_bonus', 'driver_credit'))
                AND (referee_instrument IS NULL OR referee_instrument IN ('passenger_bonus', 'driver_credit'))
            ),
            CONSTRAINT ck_promo_campaign_versions_milestones CHECK (
                milestone_thresholds IS NULL OR jsonb_typeof(milestone_thresholds) = 'array'
            ),
            CONSTRAINT ck_promo_campaign_versions_counts CHECK (
                (min_distinct_clients IS NULL OR min_distinct_clients > 0)
                AND (enrollment_limit IS NULL OR enrollment_limit > 0)
            ),
            CONSTRAINT ck_promo_campaign_versions_durations CHECK (
                (qualification_window_s IS NULL OR qualification_window_s > 0)
                AND (reward_validity_s IS NULL OR reward_validity_s > 0)
                AND (review_sla_s IS NULL OR review_sla_s > 0)
                AND (restoration_grace_s IS NULL OR restoration_grace_s > 0)
            ),
            CONSTRAINT ck_promo_campaign_versions_bps CHECK (
                (max_discount_share_bps IS NULL OR max_discount_share_bps BETWEEN 0 AND 10000)
                AND (variable_cost_bps IS NULL OR variable_cost_bps BETWEEN 0 AND 10000)
            ),
            CONSTRAINT ck_promo_campaign_versions_caps CHECK (
                (max_discount_per_booking_minor IS NULL OR max_discount_per_booking_minor >= 0)
                AND (passenger_bonus_max_per_booking_minor IS NULL OR passenger_bonus_max_per_booking_minor >= 0)
                AND (driver_credit_max_per_booking_minor IS NULL OR driver_credit_max_per_booking_minor >= 0)
                AND (variable_cost_fixed_minor IS NULL OR variable_cost_fixed_minor >= 0)
            ),
            -- Q111: M > 0 whenever it is set; 0 is never stored as "no floor".
            CONSTRAINT ck_promo_campaign_versions_min_margin CHECK (min_margin_minor IS NULL OR min_margin_minor > 0)
        )
        """
    )
    _add_constraint(
        "promo_campaigns",
        "fk_promo_campaigns_active_version",
        "FOREIGN KEY (active_version_id, id) REFERENCES promo_campaign_versions (id, campaign_id)",
    )
    _append_only("promo_campaign_versions")

    # --- budget (cache, trigger-written) and large-change requests ------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_budgets (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            campaign_id BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            allocated_minor BIGINT NOT NULL DEFAULT 0,
            promised_minor BIGINT NOT NULL DEFAULT 0,
            granted_minor BIGINT NOT NULL DEFAULT 0,
            consumed_minor BIGINT NOT NULL DEFAULT 0,
            released_minor BIGINT NOT NULL DEFAULT 0,
            last_ledger_seq BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_budgets_campaign UNIQUE (campaign_id),
            CONSTRAINT fk_promo_budgets_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT ck_promo_budgets_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_promo_budgets_non_negative CHECK (
                allocated_minor >= 0 AND promised_minor >= 0 AND granted_minor >= 0
                AND consumed_minor >= 0 AND released_minor >= 0
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS promo_budget_requests (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            campaign_id BIGINT NOT NULL,
            kind VARCHAR(24) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            reason TEXT NOT NULL,
            evidence_reference TEXT,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            requested_by BIGINT NOT NULL,
            approved_by BIGINT,
            rejected_by BIGINT,
            reject_reason TEXT,
            decided_at TIMESTAMPTZ,
            ledger_transaction_id BIGINT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_budget_requests_public_id UNIQUE (public_id),
            CONSTRAINT fk_promo_budget_requests_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_budget_requests_requested_by FOREIGN KEY (requested_by) REFERENCES users (id),
            CONSTRAINT fk_promo_budget_requests_approved_by FOREIGN KEY (approved_by) REFERENCES users (id),
            CONSTRAINT fk_promo_budget_requests_rejected_by FOREIGN KEY (rejected_by) REFERENCES users (id),
            CONSTRAINT ck_promo_budget_requests_kind CHECK (kind IN ('allocate', 'reduce_allocation')),
            CONSTRAINT ck_promo_budget_requests_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_promo_budget_requests_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_promo_budget_requests_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
            CONSTRAINT ck_promo_budget_requests_status CHECK (status IN ('pending', 'posted', 'rejected', 'withdrawn')),
            -- Q17/Q114: the requester is never their own second approver (or rejecter).
            CONSTRAINT ck_promo_budget_requests_approver CHECK (approved_by IS NULL OR approved_by <> requested_by),
            CONSTRAINT ck_promo_budget_requests_rejecter CHECK (rejected_by IS NULL OR rejected_by <> requested_by),
            CONSTRAINT ck_promo_budget_requests_large CHECK (
                status <> 'posted' OR amount_minor <= {TWO_PERSON_THRESHOLD_MINOR} OR approved_by IS NOT NULL
            ),
            CONSTRAINT ck_promo_budget_requests_posted CHECK ((status = 'posted') = (ledger_transaction_id IS NOT NULL)),
            CONSTRAINT ck_promo_budget_requests_version CHECK (version >= 1)
        )
        """
    )

    # --- obligations, lots, redemptions ---------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_obligations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            campaign_id BIGINT NOT NULL,
            campaign_version_id BIGINT NOT NULL,
            beneficiary_user_id BIGINT NOT NULL,
            side VARCHAR(16) NOT NULL,
            milestone INTEGER NOT NULL DEFAULT 0,
            instrument VARCHAR(16) NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            amount_minor BIGINT NOT NULL,
            reward_key VARCHAR(200) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            source_id BIGINT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'promised',
            decided_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_obligations_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_obligations_reward_key UNIQUE (reward_key),
            CONSTRAINT fk_promo_obligations_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_obligations_version FOREIGN KEY (campaign_version_id, campaign_id)
                REFERENCES promo_campaign_versions (id, campaign_id),
            CONSTRAINT fk_promo_obligations_beneficiary FOREIGN KEY (beneficiary_user_id) REFERENCES users (id),
            CONSTRAINT ck_promo_obligations_side CHECK (side IN ('referrer', 'referee')),
            CONSTRAINT ck_promo_obligations_milestone CHECK (milestone >= 0),
            CONSTRAINT ck_promo_obligations_instrument CHECK (instrument IN ('passenger_bonus', 'driver_credit')),
            CONSTRAINT ck_promo_obligations_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_promo_obligations_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_promo_obligations_status CHECK (status IN ('promised', 'granted', 'released')),
            CONSTRAINT ck_promo_obligations_decided CHECK ((status = 'promised') = (decided_at IS NULL)),
            CONSTRAINT ck_promo_obligations_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_obligations_campaign_status ON promo_obligations (campaign_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_obligations_beneficiary ON promo_obligations (beneficiary_user_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_lots (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            obligation_id BIGINT NOT NULL,
            campaign_id BIGINT NOT NULL,
            owner_user_id BIGINT NOT NULL,
            instrument VARCHAR(16) NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            amount_minor BIGINT NOT NULL,
            reserved_minor BIGINT NOT NULL DEFAULT 0,
            consumed_minor BIGINT NOT NULL DEFAULT 0,
            expired_minor BIGINT NOT NULL DEFAULT 0,
            reversed_minor BIGINT NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'pending_review',
            expires_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_lots_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_lots_obligation UNIQUE (obligation_id),
            CONSTRAINT fk_promo_lots_obligation FOREIGN KEY (obligation_id) REFERENCES promo_obligations (id),
            CONSTRAINT fk_promo_lots_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_lots_owner FOREIGN KEY (owner_user_id) REFERENCES users (id),
            CONSTRAINT ck_promo_lots_instrument CHECK (instrument IN ('passenger_bonus', 'driver_credit')),
            CONSTRAINT ck_promo_lots_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_promo_lots_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_promo_lots_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_promo_lots_buckets CHECK (
                reserved_minor >= 0 AND consumed_minor >= 0 AND expired_minor >= 0 AND reversed_minor >= 0
                AND reserved_minor + consumed_minor + expired_minor + reversed_minor <= amount_minor
            ),
            CONSTRAINT ck_promo_lots_status CHECK (
                status IN ('pending_review', 'available', 'exhausted', 'expired', 'reversed')
            ),
            CONSTRAINT ck_promo_lots_exhausted CHECK (status <> 'exhausted' OR consumed_minor = amount_minor),
            CONSTRAINT ck_promo_lots_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_promo_lots_owner_status ON promo_lots (owner_user_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_promo_lots_status_expires ON promo_lots (status, expires_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_redemptions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            lot_id BIGINT NOT NULL,
            booking_id BIGINT NOT NULL,
            amount_minor BIGINT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'reserved',
            release_fault VARCHAR(16),
            settled_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_redemptions_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_redemptions_lot_booking UNIQUE (lot_id, booking_id),
            CONSTRAINT fk_promo_redemptions_lot FOREIGN KEY (lot_id) REFERENCES promo_lots (id),
            CONSTRAINT fk_promo_redemptions_booking FOREIGN KEY (booking_id) REFERENCES bookings (id),
            CONSTRAINT ck_promo_redemptions_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_promo_redemptions_status CHECK (status IN ('reserved', 'consumed', 'released')),
            CONSTRAINT ck_promo_redemptions_fault CHECK (
                (status = 'released') = (release_fault IS NOT NULL)
                AND (release_fault IS NULL OR release_fault IN ('client', 'driver', 'platform'))
            ),
            CONSTRAINT ck_promo_redemptions_settled CHECK ((status = 'reserved') = (settled_at IS NULL)),
            CONSTRAINT ck_promo_redemptions_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_promo_redemptions_booking ON promo_redemptions (booking_id)")

    # --- the immutable promo ledger ------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS promo_ledger_transactions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            campaign_id BIGINT NOT NULL,
            kind VARCHAR(24) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            reference_key VARCHAR(200) NOT NULL,
            reversal_of_id BIGINT,
            obligation_id BIGINT,
            lot_id BIGINT,
            redemption_id BIGINT,
            budget_request_id BIGINT,
            actor_user_id BIGINT,
            reason TEXT,
            budget_seq BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_ledger_transactions_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_ledger_transactions_reference_key UNIQUE (reference_key),
            CONSTRAINT fk_promo_ledger_transactions_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_ledger_transactions_reversal FOREIGN KEY (reversal_of_id)
                REFERENCES promo_ledger_transactions (id),
            CONSTRAINT fk_promo_ledger_transactions_obligation FOREIGN KEY (obligation_id) REFERENCES promo_obligations (id),
            CONSTRAINT fk_promo_ledger_transactions_lot FOREIGN KEY (lot_id) REFERENCES promo_lots (id),
            CONSTRAINT fk_promo_ledger_transactions_redemption FOREIGN KEY (redemption_id) REFERENCES promo_redemptions (id),
            CONSTRAINT fk_promo_ledger_transactions_request FOREIGN KEY (budget_request_id)
                REFERENCES promo_budget_requests (id),
            CONSTRAINT fk_promo_ledger_transactions_actor FOREIGN KEY (actor_user_id) REFERENCES users (id),
            CONSTRAINT ck_promo_ledger_transactions_kind CHECK (kind IN ({_sql_list(_LEDGER_KINDS)})),
            CONSTRAINT ck_promo_ledger_transactions_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_promo_ledger_transactions_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_promo_ledger_transactions_links CHECK (
                (kind NOT IN ('promise', 'release_promise', 'grant') OR obligation_id IS NOT NULL)
                AND (kind NOT IN ('grant', 'consume', 'release_granted', 'reinstate') OR lot_id IS NOT NULL)
                AND (kind <> 'consume' OR redemption_id IS NOT NULL)
                AND (kind NOT IN ('allocate', 'reduce_allocation')
                     OR (actor_user_id IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0))
                AND (reversal_of_id IS NULL OR kind = 'reduce_allocation')
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_ledger_promise_obligation "
        "ON promo_ledger_transactions (obligation_id) WHERE kind = 'promise'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_ledger_grant_lot "
        "ON promo_ledger_transactions (lot_id) WHERE kind = 'grant'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_ledger_consume_redemption "
        "ON promo_ledger_transactions (redemption_id) WHERE kind = 'consume'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_ledger_transactions_campaign ON promo_ledger_transactions (campaign_id, id)"
    )
    _add_constraint(
        "promo_budget_requests",
        "fk_promo_budget_requests_ledger_transaction",
        "FOREIGN KEY (ledger_transaction_id) REFERENCES promo_ledger_transactions (id)",
    )
    _append_only("promo_ledger_transactions")

    # --- helpers ----------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_is_finance_approver(p_user_id BIGINT) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
            -- Q69 rule reused: an active finance or super_admin (primary role or active user_roles row).
            SELECT EXISTS (
                SELECT 1 FROM public.users u WHERE u.id = p_user_id AND u.status = 'active'
                AND (u.role IN ('finance', 'super_admin')
                     OR EXISTS (SELECT 1 FROM public.user_roles r WHERE r.user_id = u.id AND r.status = 'active'
                                AND r.role IN ('finance', 'super_admin')))
            )
        $$
        """
    )

    # budget cache: written only from inside the ledger trigger (depth >= 2)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_budgets_writer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'promo_budgets is maintained by the promo ledger trigger only (%)', TG_OP
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_writer_refused';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    _trigger("trg_promo_budgets_writer_guard", "promo_budgets",
             "TRIGGER trg_promo_budgets_writer_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_budgets "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_budgets_writer_guard()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_budgets_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'promo_budgets cannot be truncated'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_writer_refused';
        END;
        $$
        """
    )
    _trigger("trg_promo_budgets_no_truncate", "promo_budgets",
             "TRIGGER trg_promo_budgets_no_truncate BEFORE TRUNCATE ON promo_budgets "
             "FOR EACH STATEMENT EXECUTE FUNCTION public.promo_budgets_no_truncate()")

    # the ledger posting trigger: apply the movement to the budget row under its row lock, then check
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_ledger_apply() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            d_alloc BIGINT := 0; d_prom BIGINT := 0; d_grant BIGINT := 0; d_cons BIGINT := 0; d_rel BIGINT := 0;
            b public.promo_budgets%ROWTYPE;
            req public.promo_budget_requests%ROWTYPE;
            camp_currency CHAR(3);
        BEGIN
            IF NEW.budget_seq IS NOT NULL THEN
                RAISE EXCEPTION 'promo_ledger_transactions.budget_seq is assigned by the database'
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT currency INTO camp_currency FROM public.promo_campaigns WHERE id = NEW.campaign_id;
            IF camp_currency IS DISTINCT FROM NEW.currency THEN
                RAISE EXCEPTION 'promo ledger currency differs from the campaign currency' USING ERRCODE = 'check_violation';
            END IF;
            CASE NEW.kind
                WHEN 'allocate' THEN d_alloc := NEW.amount_minor;
                WHEN 'reduce_allocation' THEN d_alloc := -NEW.amount_minor;
                WHEN 'promise' THEN d_prom := NEW.amount_minor;
                WHEN 'release_promise' THEN d_prom := -NEW.amount_minor; d_rel := NEW.amount_minor;
                WHEN 'grant' THEN d_prom := -NEW.amount_minor; d_grant := NEW.amount_minor;
                WHEN 'consume' THEN d_grant := -NEW.amount_minor; d_cons := NEW.amount_minor;
                WHEN 'release_granted' THEN d_grant := -NEW.amount_minor; d_rel := NEW.amount_minor;
                WHEN 'reinstate' THEN d_grant := NEW.amount_minor;
            END CASE;
            IF NEW.kind IN ('allocate', 'reduce_allocation') THEN
                -- Q105/Q69: budget changes only by an active finance or super_admin member of staff.
                IF NOT public.promo_is_finance_approver(NEW.actor_user_id) THEN
                    RAISE EXCEPTION 'promo budget change by a user who is not active finance staff'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
                END IF;
                IF NEW.amount_minor > {TWO_PERSON_THRESHOLD_MINOR} THEN
                    SELECT * INTO req FROM public.promo_budget_requests WHERE id = NEW.budget_request_id;
                    IF req.id IS NULL OR req.campaign_id <> NEW.campaign_id OR req.kind <> NEW.kind
                       OR req.amount_minor <> NEW.amount_minor OR req.status <> 'pending'
                       OR req.approved_by IS NULL OR req.approved_by = req.requested_by
                       OR NOT public.promo_is_finance_approver(req.approved_by)
                       OR NEW.actor_user_id <> req.approved_by THEN
                        RAISE EXCEPTION 'promo budget change above the two-person threshold needs a different approver'
                            USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_second_approver_required';
                    END IF;
                END IF;
            END IF;
            IF NEW.kind = 'allocate' THEN
                INSERT INTO public.promo_budgets AS pb (campaign_id, currency, allocated_minor, last_ledger_seq)
                VALUES (NEW.campaign_id, NEW.currency, d_alloc, 1)
                ON CONFLICT (campaign_id) DO UPDATE
                    SET allocated_minor = pb.allocated_minor + EXCLUDED.allocated_minor,
                        last_ledger_seq = pb.last_ledger_seq + 1,
                        updated_at = now()
                RETURNING pb.* INTO b;
            ELSE
                UPDATE public.promo_budgets AS pb
                   SET allocated_minor = pb.allocated_minor + d_alloc,
                       promised_minor = pb.promised_minor + d_prom,
                       granted_minor = pb.granted_minor + d_grant,
                       consumed_minor = pb.consumed_minor + d_cons,
                       released_minor = pb.released_minor + d_rel,
                       last_ledger_seq = pb.last_ledger_seq + 1,
                       updated_at = now()
                 WHERE pb.campaign_id = NEW.campaign_id
                RETURNING pb.* INTO b;
                IF b.id IS NULL THEN
                    RAISE EXCEPTION 'promo budget has no allocation'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_exhausted';
                END IF;
            END IF;
            -- The row lock taken by the UPDATE serialises concurrent postings; this check sees the latest row.
            IF NEW.kind IN ('promise', 'reinstate')
               AND b.promised_minor + b.granted_minor + b.consumed_minor > b.allocated_minor THEN
                RAISE EXCEPTION 'promo budget exhausted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_exhausted';
            END IF;
            NEW.budget_seq := b.last_ledger_seq;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_ledger_apply", "promo_ledger_transactions",
             "TRIGGER trg_promo_ledger_apply BEFORE INSERT ON promo_ledger_transactions "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_ledger_apply()")

    # deferred: the cached budget row equals the ledger (detects a forged cache even if the guard were bypassed)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_budget_cache_check() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            s RECORD;
            b public.promo_budgets%ROWTYPE;
        BEGIN
            SELECT
                COALESCE(SUM(CASE kind WHEN 'allocate' THEN amount_minor WHEN 'reduce_allocation' THEN -amount_minor ELSE 0 END), 0) AS alloc,
                COALESCE(SUM(CASE kind WHEN 'promise' THEN amount_minor WHEN 'release_promise' THEN -amount_minor
                                      WHEN 'grant' THEN -amount_minor ELSE 0 END), 0) AS prom,
                COALESCE(SUM(CASE kind WHEN 'grant' THEN amount_minor WHEN 'reinstate' THEN amount_minor
                                      WHEN 'consume' THEN -amount_minor WHEN 'release_granted' THEN -amount_minor ELSE 0 END), 0) AS grnt,
                COALESCE(SUM(CASE kind WHEN 'consume' THEN amount_minor ELSE 0 END), 0) AS cons,
                COALESCE(SUM(CASE kind WHEN 'release_promise' THEN amount_minor WHEN 'release_granted' THEN amount_minor ELSE 0 END), 0) AS rel
            INTO s FROM public.promo_ledger_transactions WHERE campaign_id = NEW.campaign_id;
            SELECT * INTO b FROM public.promo_budgets WHERE campaign_id = NEW.campaign_id;
            IF b.id IS NULL OR b.allocated_minor <> s.alloc OR b.promised_minor <> s.prom OR b.granted_minor <> s.grnt
               OR b.consumed_minor <> s.cons OR b.released_minor <> s.rel THEN
                RAISE EXCEPTION 'promo_budgets cache differs from the promo ledger (campaign %)', NEW.campaign_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_cache_mismatch';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_promo_budget_cache_check ON promo_ledger_transactions")
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_promo_budget_cache_check AFTER INSERT ON promo_ledger_transactions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.promo_budget_cache_check()"
    )

    # campaigns: identity columns frozen, state machine, activation completeness (Q105, Q111)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_campaigns_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            v public.promo_campaign_versions%ROWTYPE;
            allocated BIGINT;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_campaigns rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'draft' OR NEW.active_version_id IS NOT NULL THEN
                    RAISE EXCEPTION 'promo_campaigns are created as drafts'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.kind <> OLD.kind OR NEW.family <> OLD.family OR NEW.service_type <> OLD.service_type
               OR NEW.currency <> OLD.currency OR NEW.created_by <> OLD.created_by OR NEW.public_id <> OLD.public_id THEN
                RAISE EXCEPTION 'promo_campaigns identity columns are immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                (OLD.status, NEW.status) IN (('draft', 'active'), ('draft', 'closed'), ('active', 'paused'),
                                             ('paused', 'active'), ('active', 'closed'), ('paused', 'closed'))
            ) THEN
                RAISE EXCEPTION 'promo_campaigns: % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status = 'active' AND (OLD.status <> 'active' OR NEW.active_version_id IS DISTINCT FROM OLD.active_version_id) THEN
                SELECT * INTO v FROM public.promo_campaign_versions WHERE id = NEW.active_version_id AND campaign_id = NEW.id;
                IF v.id IS NULL
                   OR v.referrer_reward_minor IS NULL OR v.referee_reward_minor IS NULL
                   OR v.referrer_instrument IS NULL OR v.referee_instrument IS NULL
                   OR v.milestone_thresholds IS NULL OR v.enrollment_limit IS NULL
                   OR v.qualification_window_s IS NULL OR v.reward_validity_s IS NULL
                   OR v.review_sla_s IS NULL OR v.restoration_grace_s IS NULL
                   OR v.max_discount_share_bps IS NULL OR v.max_discount_per_booking_minor IS NULL
                   OR v.passenger_bonus_max_per_booking_minor IS NULL OR v.driver_credit_max_per_booking_minor IS NULL
                   OR v.variable_cost_fixed_minor IS NULL OR v.variable_cost_bps IS NULL
                   OR v.min_margin_minor IS NULL OR v.min_margin_minor <= 0
                   OR v.approval_reference IS NULL OR btrim(v.approval_reference) = ''
                   OR (v.referrer_reward_minor = 0 AND v.referee_reward_minor = 0)
                   OR (NEW.kind = 'referral_driver_driver' AND v.min_distinct_clients IS NULL)
                   OR NEW.kind NOT IN ('referral_client_client', 'referral_driver_driver', 'referral_driver_client') THEN
                    RAISE EXCEPTION 'promo_campaigns: activation needs every parameter of the version set'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_activation_incomplete';
                END IF;
                SELECT allocated_minor INTO allocated FROM public.promo_budgets WHERE campaign_id = NEW.id;
                IF COALESCE(allocated, 0) <= 0 THEN
                    RAISE EXCEPTION 'promo_campaigns: activation needs an allocated budget'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_activation_incomplete';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_campaigns_guard", "promo_campaigns",
             "TRIGGER trg_promo_campaigns_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_campaigns "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_campaigns_guard()")

    # obligations: amounts and identity frozen, promised -> granted | released only
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_obligations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_obligations rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'promised' THEN
                    RAISE EXCEPTION 'promo_obligations are created as promised'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.campaign_id, NEW.campaign_version_id, NEW.beneficiary_user_id, NEW.side, NEW.milestone,
                NEW.instrument, NEW.service_type, NEW.amount_minor, NEW.reward_key, NEW.source_type, NEW.source_id,
                NEW.public_id)
               IS DISTINCT FROM
               (OLD.campaign_id, OLD.campaign_version_id, OLD.beneficiary_user_id, OLD.side, OLD.milestone,
                OLD.instrument, OLD.service_type, OLD.amount_minor, OLD.reward_key, OLD.source_type, OLD.source_id,
                OLD.public_id) THEN
                RAISE EXCEPTION 'promo_obligations terms are immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF NEW.status <> OLD.status AND NOT (OLD.status = 'promised' AND NEW.status IN ('granted', 'released')) THEN
                RAISE EXCEPTION 'promo_obligations: % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_obligations_guard", "promo_obligations",
             "TRIGGER trg_promo_obligations_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_obligations "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_obligations_guard()")

    # lots: identity frozen, owner/instrument/service equal the obligation; buckets only grow except reserved
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_lots_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            o public.promo_obligations%ROWTYPE;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_lots rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                SELECT * INTO o FROM public.promo_obligations WHERE id = NEW.obligation_id;
                IF o.id IS NULL OR o.beneficiary_user_id <> NEW.owner_user_id OR o.instrument <> NEW.instrument
                   OR o.service_type <> NEW.service_type OR o.campaign_id <> NEW.campaign_id
                   OR NEW.amount_minor > o.amount_minor THEN
                    RAISE EXCEPTION 'promo_lots must match their obligation (owner, instrument, service, <= amount)'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                IF NEW.reserved_minor + NEW.consumed_minor + NEW.expired_minor + NEW.reversed_minor <> 0 THEN
                    RAISE EXCEPTION 'promo_lots start with empty buckets'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.obligation_id, NEW.campaign_id, NEW.owner_user_id, NEW.instrument, NEW.service_type,
                NEW.currency, NEW.amount_minor, NEW.public_id)
               IS DISTINCT FROM
               (OLD.obligation_id, OLD.campaign_id, OLD.owner_user_id, OLD.instrument, OLD.service_type,
                OLD.currency, OLD.amount_minor, OLD.public_id) THEN
                RAISE EXCEPTION 'promo_lots identity and amount are immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            -- consumed and reversed value never comes back (task §13).
            IF NEW.consumed_minor < OLD.consumed_minor OR NEW.reversed_minor < OLD.reversed_minor THEN
                RAISE EXCEPTION 'promo_lots: consumed or reversed value cannot be returned'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF OLD.status IN ('exhausted', 'reversed') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'promo_lots: % is terminal', OLD.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_lots_guard", "promo_lots",
             "TRIGGER trg_promo_lots_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_lots "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_lots_guard()")

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
            IF (NEW.lot_id, NEW.booking_id, NEW.amount_minor, NEW.public_id)
               IS DISTINCT FROM (OLD.lot_id, OLD.booking_id, OLD.amount_minor, OLD.public_id) THEN
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
    _trigger("trg_promo_redemptions_guard", "promo_redemptions",
             "TRIGGER trg_promo_redemptions_guard BEFORE INSERT OR UPDATE OR DELETE ON promo_redemptions "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_redemptions_guard()")

    # deferred: a lot's reserved/consumed buckets equal its redemptions, and its consumed value equals the
    # consume postings - one bonus can never be spent twice, even through a direct SQL write.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_lot_balance_check() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            target BIGINT;
            l public.promo_lots%ROWTYPE;
            r_reserved BIGINT;
            r_consumed BIGINT;
            posted BIGINT;
        BEGIN
            -- one function for two tables: read the key through jsonb so each table's record type resolves
            target := CASE WHEN TG_TABLE_NAME = 'promo_lots' THEN (to_jsonb(NEW) ->> 'id')::bigint
                           ELSE (to_jsonb(NEW) ->> 'lot_id')::bigint END;
            SELECT * INTO l FROM public.promo_lots WHERE id = target;
            SELECT COALESCE(SUM(amount_minor) FILTER (WHERE status = 'reserved'), 0),
                   COALESCE(SUM(amount_minor) FILTER (WHERE status = 'consumed'), 0)
              INTO r_reserved, r_consumed FROM public.promo_redemptions WHERE lot_id = target;
            SELECT COALESCE(SUM(amount_minor), 0) INTO posted
              FROM public.promo_ledger_transactions WHERE lot_id = target AND kind = 'consume';
            IF l.reserved_minor <> r_reserved OR l.consumed_minor <> r_consumed OR l.consumed_minor <> posted THEN
                RAISE EXCEPTION 'promo lot % buckets differ from its redemptions / consume postings', target
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_lot_balance_mismatch';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for table in ("promo_lots", "promo_redemptions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_balance_check ON {table}")
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_balance_check AFTER INSERT OR UPDATE ON {table} "
            f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.promo_lot_balance_check()"
        )

    # read-only reconciliation (Q115, QA #24): every obligation's stages add up exactly once.
    op.execute(
        """
        CREATE OR REPLACE VIEW promo_obligation_reconciliation AS
        SELECT o.id AS obligation_id, o.campaign_id, o.status, o.amount_minor,
               COALESCE(SUM(t.amount_minor) FILTER (WHERE t.kind = 'promise'), 0) AS promised_minor,
               COALESCE(SUM(t.amount_minor) FILTER (WHERE t.kind = 'grant'), 0) AS granted_minor,
               COALESCE(SUM(t.amount_minor) FILTER (WHERE t.kind = 'release_promise'), 0) AS released_promise_minor,
               CASE
                   WHEN COALESCE(SUM(t.amount_minor) FILTER (WHERE t.kind = 'promise'), 0) <> o.amount_minor THEN 'promise_mismatch'
                   WHEN o.status = 'promised'
                        AND COALESCE(SUM(t.amount_minor) FILTER (WHERE t.kind IN ('grant', 'release_promise')), 0) <> 0
                        THEN 'settled_while_promised'
                   WHEN o.status <> 'promised'
                        AND COALESCE(SUM(t.amount_minor) FILTER (WHERE t.kind IN ('grant', 'release_promise')), 0) <> o.amount_minor
                        THEN 'settlement_mismatch'
                   WHEN o.status = 'granted' AND NOT EXISTS (SELECT 1 FROM promo_lots l WHERE l.obligation_id = o.id)
                        THEN 'granted_without_lot'
                   WHEN o.status = 'released' AND EXISTS (SELECT 1 FROM promo_lots l WHERE l.obligation_id = o.id)
                        THEN 'released_with_lot'
                   ELSE NULL
               END AS issue
          FROM promo_obligations o
          LEFT JOIN promo_ledger_transactions t ON t.obligation_id = o.id
         GROUP BY o.id
        """
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016). Never a production rollback."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP VIEW IF EXISTS promo_obligation_reconciliation")
    op.execute("ALTER TABLE IF EXISTS promo_budget_requests DROP CONSTRAINT IF EXISTS fk_promo_budget_requests_ledger_transaction")
    op.execute("ALTER TABLE IF EXISTS promo_campaigns DROP CONSTRAINT IF EXISTS fk_promo_campaigns_active_version")
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for function in (
        "promo_lot_balance_check", "promo_redemptions_guard", "promo_lots_guard", "promo_obligations_guard",
        "promo_campaigns_guard", "promo_budget_cache_check", "promo_ledger_apply", "promo_budgets_no_truncate",
        "promo_budgets_writer_guard", "promo_is_finance_approver", "promo_ledger_transactions_append_only",
        "promo_campaign_versions_append_only",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS public.{function} CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_feature_flag_values_promotions_guard ON feature_flag_values")
    op.execute("DROP FUNCTION IF EXISTS public.promo_feature_flag_guard()")
    op.execute("DELETE FROM feature_flag_values WHERE flag_key = 'promotions_enabled'")
    op.execute("ALTER TABLE feature_flag_values DROP CONSTRAINT IF EXISTS ck_feature_flag_values_flag_key")
    op.execute(
        f"ALTER TABLE feature_flag_values ADD CONSTRAINT ck_feature_flag_values_flag_key "
        f"CHECK (flag_key IN ({_sql_list(_OLD_FLAG_KEYS)}))"
    )
