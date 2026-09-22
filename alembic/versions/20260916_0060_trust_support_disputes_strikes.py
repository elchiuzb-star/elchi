"""trust support disputes strikes (A12, wave 3)

Owner: A12 (wave 3) - module `trust_support`.
Content (DATA_MODEL.md §1.10, WAVE1_CARDS "Wave 3", STATE_MACHINES §8 and §12, spec §9.5, §16, §17.2-§17.3, §17.8;
AC26, AC36; Q7, Q45, Q66/Q74):
  * disputes_v2 - booking disputes; partial UNIQUE index uq_disputes_v2_booking_type_active (booking_id, dispute_type)
    WHERE status IN ('open','under_review') (-> 409 DISPUTE_ALREADY_OPEN); guard trigger: terminal rows frozen
    (CONSTRAINT 'dispute_terminal_frozen'), identity columns immutable and no DELETE ('append_only_violation'),
    only STATE_MACHINES §8 status transitions; escalate_at (48 h) + escalated_at (worker marker).
  * dispute_evidence - append-only ('append_only_violation'); note is contact-filtered, file ids opaque.
  * contact_filter_hits - append-only log of consumed trust.contact_filter.hit events (UNIQUE source_event_id) used
    for the Q45 window count (additive table, not in the DATA_MODEL plan - A12 report).
  * contact_strikes - append-only, UNIQUE(source_event_id): one strike per hit event.
  * trust_review_items - Q45 operator queue; partial UNIQUE (subject_user_id, signal_type) WHERE status IN
    ('open','under_review'); evidence JSONB guard: only trust.TRUST_REVIEW_EVIDENCE_KEYS with id arrays / numbers;
    terminal rows frozen; no DELETE.
  * support_tickets - support / SOS (§16); resolved rows frozen; no DELETE.
  * ratings_v2 - UNIQUE(booking_id, author_user_id, subject_user_id), stars 1..5, author <> subject; content
    immutable, published_at set once, only moderation_status may change; no DELETE. Legacy ratings are not copied (Q4).
  * reputation_snapshots - UNIQUE(user_id, service_type) counters (worker refresh).
  * staff MFA: plan only in wave 3 (no tables).
FK targets only up to 0057: users (0032), bookings (0048), cash_receipts (0051), trips (0038). No FK to other wave 3
modules. cash_receipts.dispute_id -> disputes_v2 FK is NOT added (A4 table, pending integrator decision).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS + CREATE); single head.
downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0060
Revises: 20260916_0059
Create Date: 2026-09-16 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0060"
down_revision: str = "20260916_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app.contracts values (tests/modules/trust_support/test_migration_literals.py compares them).
DISPUTE_TYPES = ("service", "no_show", "payment", "delivery", "commission", "safety", "other")
DISPUTE_STATUSES = ("open", "under_review", "resolved", "rejected")
DISPUTE_RESOLUTION_CODES = (
    "service_confirmed", "service_not_provided", "paid_confirmed", "unpaid_confirmed", "commission_adjusted", "no_action", "other",
)
DISPUTE_OPENER_SIDES = ("client", "driver", "operator")
TRUST_SIGNAL_TYPES = ("contact_filter_strikes", "quick_cancel_after_chat", "repeated_pair_cancellations")
TRUST_REVIEW_STATUSES = ("open", "under_review", "dismissed", "actioned")
TRUST_REVIEW_DECISIONS = ("no_violation", "warning_issued", "escalated_to_admin")
TRUST_REVIEW_EVIDENCE_KEYS = (
    "booking_ids", "chat_thread_ids", "source_event_ids", "hit_count", "strike_count", "cancel_count", "window_days",
)
SUPPORT_TICKET_KINDS = ("support", "sos")
SUPPORT_TICKET_STATUSES = ("open", "acknowledged", "resolved")
SERVICE_TYPES = ("passenger", "parcel")
RATING_SIDES = ("client", "driver")
MODERATION_STATUSES = ("visible", "hidden_by_staff")
STRIKE_REASONS = ("contact_filter",)
DISPUTE_DESCRIPTION_MAX_LENGTH = 2000
SUPPORT_MESSAGE_MAX_LENGTH = 2000
RATING_COMMENT_MAX_LENGTH = 500
DISPUTE_EVIDENCE_MAX_FILES = 10

APPEND_ONLY = "append_only_violation"
TERMINAL_FROZEN = "dispute_terminal_frozen"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE TRIGGER {name} {definition}")


def _append_only(table: str) -> None:
    _trigger(f"trg_{table}_append_only", table,
             f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION trust_support_append_only()")
    _no_truncate(table)


def _no_truncate(table: str) -> None:
    _trigger(f"trg_{table}_no_truncate", table,
             f"BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION trust_support_append_only()")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trust_support_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only (%)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
        END;
        $$
        """
    )

    # --- disputes_v2 ------------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS disputes_v2 (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            booking_id BIGINT NOT NULL CONSTRAINT fk_disputes_v2_booking_id REFERENCES bookings (id),
            dispute_type VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            opened_by_user_id INTEGER NOT NULL CONSTRAINT fk_disputes_v2_opened_by_user_id REFERENCES users (id),
            opened_by_side VARCHAR(16) NOT NULL,
            description TEXT NOT NULL,
            cash_receipt_id BIGINT CONSTRAINT fk_disputes_v2_cash_receipt_id REFERENCES cash_receipts (id),
            assigned_to INTEGER CONSTRAINT fk_disputes_v2_assigned_to REFERENCES users (id),
            resolution_code VARCHAR(32),
            resolution_text TEXT,
            escalate_at TIMESTAMPTZ NOT NULL,
            escalated_at TIMESTAMPTZ,
            decided_by INTEGER CONSTRAINT fk_disputes_v2_decided_by REFERENCES users (id),
            decided_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_disputes_v2_public_id UNIQUE (public_id),
            CONSTRAINT ck_disputes_v2_type CHECK (dispute_type IN {_in(DISPUTE_TYPES)}),
            CONSTRAINT ck_disputes_v2_status CHECK (status IN {_in(DISPUTE_STATUSES)}),
            CONSTRAINT ck_disputes_v2_opened_by_side CHECK (opened_by_side IN {_in(DISPUTE_OPENER_SIDES)}),
            CONSTRAINT ck_disputes_v2_resolution_code CHECK (resolution_code IS NULL OR resolution_code IN {_in(DISPUTE_RESOLUTION_CODES)}),
            CONSTRAINT ck_disputes_v2_resolved_has_code CHECK (status <> 'resolved' OR resolution_code IS NOT NULL),
            CONSTRAINT ck_disputes_v2_decided CHECK ((status IN ('resolved', 'rejected')) = (decided_at IS NOT NULL)),
            CONSTRAINT ck_disputes_v2_description CHECK (char_length(description) BETWEEN 1 AND {DISPUTE_DESCRIPTION_MAX_LENGTH}),
            CONSTRAINT ck_disputes_v2_receipt_payment CHECK (cash_receipt_id IS NULL OR dispute_type = 'payment'),
            CONSTRAINT ck_disputes_v2_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_disputes_v2_booking_type_active ON disputes_v2 (booking_id, dispute_type) "
        "WHERE status IN ('open', 'under_review')"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_disputes_v2_booking ON disputes_v2 (booking_id, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_disputes_v2_status_created ON disputes_v2 (status, created_at, id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_disputes_v2_escalation_due ON disputes_v2 (escalate_at, id) "
        "WHERE status IN ('open', 'under_review') AND escalated_at IS NULL"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trust_disputes_v2_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'disputes_v2 rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            IF OLD.status IN ('resolved', 'rejected') THEN
                RAISE EXCEPTION 'disputes_v2 % is terminal (%)', OLD.id, OLD.status
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{TERMINAL_FROZEN}';
            END IF;
            IF NEW.id <> OLD.id OR NEW.public_id <> OLD.public_id OR NEW.booking_id <> OLD.booking_id
               OR NEW.dispute_type <> OLD.dispute_type OR NEW.opened_by_user_id <> OLD.opened_by_user_id
               OR NEW.opened_by_side <> OLD.opened_by_side OR NEW.description <> OLD.description
               OR NEW.cash_receipt_id IS DISTINCT FROM OLD.cash_receipt_id OR NEW.escalate_at <> OLD.escalate_at
               OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'disputes_v2 identity columns are immutable'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                   (OLD.status = 'open' AND NEW.status IN ('under_review', 'resolved', 'rejected'))
                OR (OLD.status = 'under_review' AND NEW.status IN ('resolved', 'rejected'))) THEN
                RAISE EXCEPTION 'disputes_v2 transition % -> % is not allowed', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_disputes_v2_guard", "disputes_v2",
             "BEFORE UPDATE OR DELETE ON disputes_v2 FOR EACH ROW EXECUTE FUNCTION trust_disputes_v2_guard()")
    _no_truncate("disputes_v2")

    # --- dispute_evidence -------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS dispute_evidence (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            dispute_id BIGINT NOT NULL CONSTRAINT fk_dispute_evidence_dispute_id REFERENCES disputes_v2 (id),
            author_user_id INTEGER NOT NULL CONSTRAINT fk_dispute_evidence_author_user_id REFERENCES users (id),
            author_side VARCHAR(16) NOT NULL,
            note TEXT,
            file_ids TEXT[] NOT NULL DEFAULT '{{}}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_dispute_evidence_author_side CHECK (author_side IN {_in(DISPUTE_OPENER_SIDES)}),
            CONSTRAINT ck_dispute_evidence_content CHECK (note IS NOT NULL OR cardinality(file_ids) > 0),
            CONSTRAINT ck_dispute_evidence_files CHECK (cardinality(file_ids) <= {DISPUTE_EVIDENCE_MAX_FILES})
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_dispute_evidence_dispute ON dispute_evidence (dispute_id, id)")
    _append_only("dispute_evidence")

    # --- contact_filter_hits / contact_strikes (Q45) ----------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_filter_hits (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL CONSTRAINT fk_contact_filter_hits_user_id REFERENCES users (id),
            source_event_id UUID NOT NULL,
            subject_type VARCHAR(32) NOT NULL,
            field VARCHAR(64),
            categories TEXT[] NOT NULL DEFAULT '{}',
            match_count INTEGER NOT NULL DEFAULT 0,
            occurred_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_contact_filter_hits_source_event UNIQUE (source_event_id),
            CONSTRAINT ck_contact_filter_hits_match_count CHECK (match_count >= 0)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contact_filter_hits_user_occurred ON contact_filter_hits (user_id, occurred_at, id)")
    _append_only("contact_filter_hits")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS contact_strikes (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL CONSTRAINT fk_contact_strikes_user_id REFERENCES users (id),
            source_event_id UUID NOT NULL,
            subject_type VARCHAR(32) NOT NULL,
            categories TEXT[] NOT NULL DEFAULT '{{}}',
            reason_code VARCHAR(32) NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_contact_strikes_source_event UNIQUE (source_event_id),
            CONSTRAINT ck_contact_strikes_reason CHECK (reason_code IN {_in(STRIKE_REASONS)})
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contact_strikes_user_occurred ON contact_strikes (user_id, occurred_at, id)")
    _append_only("contact_strikes")

    # --- trust_review_items -----------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS trust_review_items (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            subject_user_id INTEGER NOT NULL CONSTRAINT fk_trust_review_items_subject_user_id REFERENCES users (id),
            signal_type VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            signal_count INTEGER NOT NULL DEFAULT 1,
            last_signal_at TIMESTAMPTZ NOT NULL,
            decision VARCHAR(32),
            note TEXT,
            assigned_to INTEGER CONSTRAINT fk_trust_review_items_assigned_to REFERENCES users (id),
            decided_by INTEGER CONSTRAINT fk_trust_review_items_decided_by REFERENCES users (id),
            decided_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_trust_review_items_public_id UNIQUE (public_id),
            CONSTRAINT ck_trust_review_items_signal CHECK (signal_type IN {_in(TRUST_SIGNAL_TYPES)}),
            CONSTRAINT ck_trust_review_items_status CHECK (status IN {_in(TRUST_REVIEW_STATUSES)}),
            CONSTRAINT ck_trust_review_items_decision CHECK (decision IS NULL OR decision IN {_in(TRUST_REVIEW_DECISIONS)}),
            CONSTRAINT ck_trust_review_items_decided CHECK ((status IN ('dismissed', 'actioned')) = (decided_at IS NOT NULL AND decision IS NOT NULL)),
            CONSTRAINT ck_trust_review_items_counts CHECK (signal_count >= 1 AND version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_trust_review_items_subject_signal_active ON trust_review_items "
        "(subject_user_id, signal_type) WHERE status IN ('open', 'under_review')"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trust_review_items_status_created ON trust_review_items (status, created_at, id)")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trust_review_items_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'trust_review_items rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.status IN ('dismissed', 'actioned') THEN
                    RAISE EXCEPTION 'trust_review_items % is terminal', OLD.id USING ERRCODE = 'restrict_violation';
                END IF;
                IF NEW.subject_user_id <> OLD.subject_user_id OR NEW.signal_type <> OLD.signal_type
                   OR NEW.public_id <> OLD.public_id THEN
                    RAISE EXCEPTION 'trust_review_items identity columns are immutable'
                        USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
                END IF;
            END IF;
            IF jsonb_typeof(NEW.evidence) <> 'object'
               OR EXISTS (SELECT 1 FROM jsonb_each(NEW.evidence) AS e
                          WHERE e.key NOT IN {_in(TRUST_REVIEW_EVIDENCE_KEYS)}
                             OR jsonb_typeof(e.value) NOT IN ('array', 'number')) THEN
                RAISE EXCEPTION 'trust_review_items.evidence carries only ids and counters (Q45)'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_trust_review_items_guard", "trust_review_items",
             "BEFORE INSERT OR UPDATE OR DELETE ON trust_review_items FOR EACH ROW EXECUTE FUNCTION trust_review_items_guard()")
    _no_truncate("trust_review_items")

    # --- support_tickets --------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            kind VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            user_id INTEGER NOT NULL CONSTRAINT fk_support_tickets_user_id REFERENCES users (id),
            booking_id BIGINT CONSTRAINT fk_support_tickets_booking_id REFERENCES bookings (id),
            trip_id BIGINT CONSTRAINT fk_support_tickets_trip_id REFERENCES trips (id),
            message TEXT,
            acknowledged_by INTEGER CONSTRAINT fk_support_tickets_acknowledged_by REFERENCES users (id),
            acknowledged_at TIMESTAMPTZ,
            resolved_by INTEGER CONSTRAINT fk_support_tickets_resolved_by REFERENCES users (id),
            resolved_at TIMESTAMPTZ,
            resolution_note TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_support_tickets_public_id UNIQUE (public_id),
            CONSTRAINT ck_support_tickets_kind CHECK (kind IN {_in(SUPPORT_TICKET_KINDS)}),
            CONSTRAINT ck_support_tickets_status CHECK (status IN {_in(SUPPORT_TICKET_STATUSES)}),
            CONSTRAINT ck_support_tickets_message CHECK (message IS NULL OR char_length(message) <= {SUPPORT_MESSAGE_MAX_LENGTH}),
            CONSTRAINT ck_support_tickets_resolved CHECK ((status = 'resolved') = (resolved_at IS NOT NULL)),
            CONSTRAINT ck_support_tickets_acknowledged CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL),
            CONSTRAINT ck_support_tickets_trip_booking CHECK (trip_id IS NULL OR booking_id IS NOT NULL),
            CONSTRAINT ck_support_tickets_version CHECK (version >= 1)
        )
        """
    )
    # BR M3: SOS repeat presses (added idempotently for databases created from an earlier 0060 draft).
    op.execute("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS press_count INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS last_pressed_at TIMESTAMPTZ")
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_support_tickets_press_count') THEN "
        "ALTER TABLE support_tickets ADD CONSTRAINT ck_support_tickets_press_count CHECK (press_count >= 1); END IF; END $$"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_support_tickets_user_created ON support_tickets (user_id, created_at, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_support_tickets_status_kind ON support_tickets (status, kind, id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_support_tickets_open_sos_user ON support_tickets (user_id) "
        "WHERE kind = 'sos' AND status <> 'resolved'"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trust_support_tickets_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'support_tickets rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            IF OLD.status = 'resolved' THEN
                RAISE EXCEPTION 'support_tickets % is resolved', OLD.id USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.user_id <> OLD.user_id OR NEW.kind <> OLD.kind OR NEW.public_id <> OLD.public_id
               OR NEW.booking_id IS DISTINCT FROM OLD.booking_id OR NEW.message IS DISTINCT FROM OLD.message THEN
                RAISE EXCEPTION 'support_tickets content is immutable'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_support_tickets_guard", "support_tickets",
             "BEFORE UPDATE OR DELETE ON support_tickets FOR EACH ROW EXECUTE FUNCTION trust_support_tickets_guard()")
    _no_truncate("support_tickets")

    # --- ratings_v2 -------------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS ratings_v2 (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            booking_id BIGINT NOT NULL CONSTRAINT fk_ratings_v2_booking_id REFERENCES bookings (id),
            author_user_id INTEGER NOT NULL CONSTRAINT fk_ratings_v2_author_user_id REFERENCES users (id),
            subject_user_id INTEGER NOT NULL CONSTRAINT fk_ratings_v2_subject_user_id REFERENCES users (id),
            author_side VARCHAR(16) NOT NULL,
            subject_side VARCHAR(16) NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            stars SMALLINT NOT NULL,
            comment TEXT,
            moderation_status VARCHAR(16) NOT NULL DEFAULT 'visible',
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ratings_v2_public_id UNIQUE (public_id),
            CONSTRAINT uq_ratings_v2_booking_author_subject UNIQUE (booking_id, author_user_id, subject_user_id),
            CONSTRAINT ck_ratings_v2_stars CHECK (stars BETWEEN 1 AND 5),
            CONSTRAINT ck_ratings_v2_author_subject CHECK (author_user_id <> subject_user_id),
            CONSTRAINT ck_ratings_v2_sides CHECK (author_side IN {_in(RATING_SIDES)} AND subject_side IN {_in(RATING_SIDES)}
                                                  AND author_side <> subject_side),
            CONSTRAINT ck_ratings_v2_service_type CHECK (service_type IN {_in(SERVICE_TYPES)}),
            CONSTRAINT ck_ratings_v2_moderation CHECK (moderation_status IN {_in(MODERATION_STATUSES)}),
            CONSTRAINT ck_ratings_v2_comment CHECK (comment IS NULL OR char_length(comment) <= {RATING_COMMENT_MAX_LENGTH})
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ratings_v2_subject_published ON ratings_v2 (subject_user_id, service_type, published_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ratings_v2_unpublished ON ratings_v2 (booking_id) WHERE published_at IS NULL")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION trust_ratings_v2_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ratings_v2 rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            IF NEW.public_id <> OLD.public_id OR NEW.booking_id <> OLD.booking_id OR NEW.author_user_id <> OLD.author_user_id
               OR NEW.subject_user_id <> OLD.subject_user_id OR NEW.author_side <> OLD.author_side
               OR NEW.subject_side <> OLD.subject_side OR NEW.service_type <> OLD.service_type OR NEW.stars <> OLD.stars
               OR NEW.comment IS DISTINCT FROM OLD.comment OR NEW.created_at <> OLD.created_at
               OR (OLD.published_at IS NOT NULL AND NEW.published_at IS DISTINCT FROM OLD.published_at) THEN
                RAISE EXCEPTION 'ratings_v2 content is immutable (only published_at once and moderation_status)'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_ratings_v2_guard", "ratings_v2",
             "BEFORE UPDATE OR DELETE ON ratings_v2 FOR EACH ROW EXECUTE FUNCTION trust_ratings_v2_guard()")
    _no_truncate("ratings_v2")

    # --- reputation_snapshots ---------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS reputation_snapshots (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL CONSTRAINT fk_reputation_snapshots_user_id REFERENCES users (id),
            service_type VARCHAR(16) NOT NULL,
            rating_count INTEGER NOT NULL DEFAULT 0,
            rating_sum INTEGER NOT NULL DEFAULT 0,
            completed_bookings INTEGER NOT NULL DEFAULT 0,
            completed_trips INTEGER NOT NULL DEFAULT 0,
            eligible_resolved INTEGER NOT NULL DEFAULT 0,
            on_time_count INTEGER NOT NULL DEFAULT 0,
            computed_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_reputation_snapshots_user_service UNIQUE (user_id, service_type),
            CONSTRAINT ck_reputation_snapshots_service_type CHECK (service_type IN {_in(SERVICE_TYPES)}),
            CONSTRAINT ck_reputation_snapshots_counts CHECK (rating_count >= 0 AND rating_sum >= 0 AND completed_bookings >= 0
                AND completed_trips >= 0 AND eligible_resolved >= 0 AND on_time_count >= 0)
        )
        """
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
