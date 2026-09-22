"""communications chat notifications

Owner: A7 (wave 3) - module `communications` (+ outbox dispatch primitives in app/modules/platform/outbox_dispatch.py).
Content (DATA_MODEL.md §1.9 and §5, WAVE1_CARDS "Wave 3", spec §15, §16, ADR-0012, ADR-0020, Q43-Q45, Q65):
  * chat_threads (public_id cht_, kind (enums.ChatThreadKind), proposal_thread_id FK proposal_threads | booking_id
    FK bookings; CHECK exactly one and matching kind; UNIQUE per parent; message_count/last_message_at counters)
  * chat_messages (public_id msg_, thread_id, author_user_id, author_side, text (masked text only - contact_filter.scan
    with mask_proof_codes=True), quick_reply_code (enums.QuickReplyCode), attachment_file_id (always NULL in wave 3,
    CHECK), contact_filter_categories (category counts only), moderation_status (enums.ChatModerationStatus),
    created_at); content immutable and no DELETE (guard CONSTRAINT = 'chat_message_immutable'; only
    moderation_status/moderated_by/moderated_at change)
  * device_tokens (public_id dev_, user_id, platform (enums.ClientPlatform), token_hash CHAR(64),
    UNIQUE(platform, token_hash), revoked_at) - no raw token/subscription until the U3 decision
  * notification_deliveries (public_id ntf_, event_id UUID, user_id, audience (events.EventAudience), channel
    (enums.NotificationChannel), status (enums.NotificationDeliveryStatus), audience payload copy, attempts,
    next_attempt_at, lease_until, read_at, last_error; UNIQUE(event_id, user_id, channel)) - also the v2 in-app inbox
  * notification_dedup (user_id, dedup_key, window_start; UNIQUE)
  * dispatch columns of outbox_events / consumer_receipts already exist (0031) - no change
FK / object dependencies: 0040 (proposal_threads), 0048 (bookings), users. No FK to other wave 3 modules.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0059
Revises: 20260916_0058
Create Date: 2026-09-16 00:59:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0059"
down_revision: str = "20260916_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literals frozen at the time of this migration (enums.ChatThreadKind, ActorSide client/driver, QuickReplyCode,
# ChatModerationStatus, ClientPlatform, events.EventAudience, NotificationChannel, NotificationDeliveryStatus).
THREAD_KINDS = ("proposal", "booking")
AUTHOR_SIDES = ("client", "driver")
QUICK_REPLIES = ("price_agreed", "clarify_stop", "arriving_in_5_min", "at_stop")
MODERATION_STATUSES = ("visible", "hidden_by_staff")
PLATFORMS = ("android", "ios", "web")
AUDIENCES = ("client", "driver", "staff", "competing_driver")
CHANNELS = ("in_app", "web_push", "fcm")
DELIVERY_STATUSES = ("pending", "sent", "failed", "dead", "skipped")
CHAT_TEXT_MAX_LENGTH = 1000
IMMUTABLE_RULE = "chat_message_immutable"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chat_threads (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            kind VARCHAR(16) NOT NULL,
            proposal_thread_id BIGINT CONSTRAINT fk_chat_threads_proposal_thread_id REFERENCES proposal_threads (id),
            booking_id BIGINT CONSTRAINT fk_chat_threads_booking_id REFERENCES bookings (id),
            message_count INTEGER NOT NULL DEFAULT 0,
            last_message_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_chat_threads_public_id UNIQUE (public_id),
            CONSTRAINT uq_chat_threads_proposal_thread_id UNIQUE (proposal_thread_id),
            CONSTRAINT uq_chat_threads_booking_id UNIQUE (booking_id),
            CONSTRAINT ck_chat_threads_kind CHECK (kind IN {_in(THREAD_KINDS)}),
            CONSTRAINT ck_chat_threads_parent CHECK (
                (kind = 'proposal' AND proposal_thread_id IS NOT NULL AND booking_id IS NULL)
                OR (kind = 'booking' AND booking_id IS NOT NULL AND proposal_thread_id IS NULL)
            ),
            CONSTRAINT ck_chat_threads_message_count CHECK (message_count >= 0)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            thread_id BIGINT NOT NULL CONSTRAINT fk_chat_messages_thread_id REFERENCES chat_threads (id),
            author_user_id INTEGER NOT NULL CONSTRAINT fk_chat_messages_author_user_id REFERENCES users (id),
            author_side VARCHAR(16) NOT NULL,
            text TEXT,
            quick_reply_code VARCHAR(32),
            attachment_file_id BIGINT,
            contact_filter_categories JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            contact_filter_version VARCHAR(32),
            moderation_status VARCHAR(24) NOT NULL DEFAULT 'visible',
            moderated_by INTEGER CONSTRAINT fk_chat_messages_moderated_by REFERENCES users (id),
            moderated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_chat_messages_public_id UNIQUE (public_id),
            CONSTRAINT ck_chat_messages_author_side CHECK (author_side IN {_in(AUTHOR_SIDES)}),
            CONSTRAINT ck_chat_messages_quick_reply CHECK (quick_reply_code IS NULL OR quick_reply_code IN {_in(QUICK_REPLIES)}),
            CONSTRAINT ck_chat_messages_content CHECK (
                (text IS NOT NULL AND length(text) BETWEEN 1 AND {CHAT_TEXT_MAX_LENGTH}) OR (text IS NULL AND quick_reply_code IS NOT NULL)
            ),
            CONSTRAINT ck_chat_messages_no_attachment CHECK (attachment_file_id IS NULL),
            CONSTRAINT ck_chat_messages_categories CHECK (jsonb_typeof(contact_filter_categories) = 'object'),
            CONSTRAINT ck_chat_messages_moderation CHECK (moderation_status IN {_in(MODERATION_STATUSES)})
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_thread_id ON chat_messages (thread_id, id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_messages_author_thread_created ON chat_messages (author_user_id, thread_id, created_at)"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION chat_messages_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'chat messages cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{IMMUTABLE_RULE}';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.public_id IS DISTINCT FROM OLD.public_id
               OR NEW.thread_id IS DISTINCT FROM OLD.thread_id
               OR NEW.author_user_id IS DISTINCT FROM OLD.author_user_id
               OR NEW.author_side IS DISTINCT FROM OLD.author_side
               OR NEW.text IS DISTINCT FROM OLD.text
               OR NEW.quick_reply_code IS DISTINCT FROM OLD.quick_reply_code
               OR NEW.attachment_file_id IS DISTINCT FROM OLD.attachment_file_id
               OR NEW.contact_filter_categories IS DISTINCT FROM OLD.contact_filter_categories
               OR NEW.contact_filter_version IS DISTINCT FROM OLD.contact_filter_version
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'chat message content is immutable'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{IMMUTABLE_RULE}';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS chat_messages_guard ON chat_messages")
    op.execute(
        "CREATE TRIGGER chat_messages_guard BEFORE UPDATE OR DELETE ON chat_messages "
        "FOR EACH ROW EXECUTE FUNCTION chat_messages_guard()"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS device_tokens (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            user_id INTEGER NOT NULL CONSTRAINT fk_device_tokens_user_id REFERENCES users (id),
            platform VARCHAR(16) NOT NULL,
            token_hash CHAR(64) NOT NULL,
            app_version VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ,
            CONSTRAINT uq_device_tokens_public_id UNIQUE (public_id),
            CONSTRAINT uq_device_tokens_platform_token_hash UNIQUE (platform, token_hash),
            CONSTRAINT ck_device_tokens_platform CHECK (platform IN {_in(PLATFORMS)}),
            CONSTRAINT ck_device_tokens_token_hash CHECK (token_hash ~ '^[0-9a-f]{{64}}$')
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_device_tokens_user_id ON device_tokens (user_id, id)")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS notification_deliveries (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            event_id UUID NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            aggregate_type VARCHAR(64) NOT NULL,
            aggregate_public_id VARCHAR(64) NOT NULL,
            aggregate_version INTEGER NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            user_id INTEGER NOT NULL CONSTRAINT fk_notification_deliveries_user_id REFERENCES users (id),
            audience VARCHAR(24) NOT NULL,
            channel VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            link VARCHAR(255),
            skip_reason VARCHAR(64),
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_until TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            read_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_notification_deliveries_public_id UNIQUE (public_id),
            CONSTRAINT uq_notification_deliveries_event_user_channel UNIQUE (event_id, user_id, channel),
            CONSTRAINT ck_notification_deliveries_audience CHECK (audience IN {_in(AUDIENCES)}),
            CONSTRAINT ck_notification_deliveries_channel CHECK (channel IN {_in(CHANNELS)}),
            CONSTRAINT ck_notification_deliveries_status CHECK (status IN {_in(DELIVERY_STATUSES)}),
            CONSTRAINT ck_notification_deliveries_payload CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT ck_notification_deliveries_attempts CHECK (attempts >= 0),
            CONSTRAINT ck_notification_deliveries_in_app_no_lease CHECK (channel <> 'in_app' OR lease_until IS NULL),
            CONSTRAINT ck_notification_deliveries_read_in_app CHECK (read_at IS NULL OR channel = 'in_app')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_inbox ON notification_deliveries (user_id, id) "
        "WHERE channel = 'in_app' AND status = 'sent'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_push_due ON notification_deliveries (next_attempt_at) "
        "WHERE channel <> 'in_app' AND status IN ('pending', 'failed')"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_dedup (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL CONSTRAINT fk_notification_dedup_user_id REFERENCES users (id),
            dedup_key VARCHAR(255) NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            event_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_notification_dedup_user_key_window UNIQUE (user_id, dedup_key, window_start)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_dedup_window_start ON notification_dedup (window_start)")


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
