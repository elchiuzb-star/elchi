"""trust blocks reports fraud signals

Owner: A12 (wave 6) - spec §8.1 ("taraflar bir-birini bloklamagan"), §17.3 (takror akkaunt va soxta safar),
API_V2_CONTRACT §11 S9-S12. These three tables were listed for wave 4 (U6) and stayed unimplemented, so the
ranking pre-filter of §8.1 had nothing to read and §17.3 had no signal store at all.

  * ``user_blocks`` - a user hides themselves from another user in **both** directions (§8.1). No reason text and
    no notification to the blocked side: a block is a quiet filter, not an accusation.
  * ``abuse_reports`` - what a user reports about a user, listing, booking or chat message (§17.3). The free text
    goes through the contact filter before it is stored (Q43), so a report cannot be used to pass a phone number.
  * ``fraud_signals`` - what the platform *noticed*, never a verdict: "two accounts share one device", "the
    client and the driver of one booking share a device", "the same pair keeps booking each other". Every row is
    opened for human review (§17.3: "avtomatik hukm o'rniga tekshiruv"); nothing is blocked automatically.

Evidence columns hold counts and public ids only - never a phone, a name, a token or a coordinate (§15).

FK / object dependencies: 0032 (users), 0039 (listings), 0048 (bookings), 0059 (chat_messages - referenced by
public id only, no FK, like the rest of A12's evidence).

Rules: idempotent (IF NOT EXISTS); do not change the revision id, file name or down_revision; single head.
downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0068
Revises: 20260916_0067
Create Date: 2026-09-17 09:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0068"
down_revision: str = "20260916_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# app.contracts.enums
REPORT_SUBJECT_TYPES = ("user", "listing", "booking", "chat_message")
REPORT_REASON_CODES = (
    "off_platform_contact", "fraud_suspicion", "unsafe_behaviour", "no_show", "price_pressure",
    "prohibited_item", "harassment", "other",
)
REPORT_STATUSES = ("open", "under_review", "dismissed", "actioned")
FRAUD_SIGNAL_TYPES = ("shared_device_accounts", "self_dealing_device", "repeated_pair_bookings")
FRAUD_SIGNAL_STATUSES = ("open", "under_review", "dismissed", "confirmed")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- S9/S10 blocks (§8.1) ---------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.user_blocks (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id       UUID NOT NULL,
            blocker_user_id INTEGER NOT NULL REFERENCES public.users(id),
            blocked_user_id INTEGER NOT NULL REFERENCES public.users(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_blocks_public_id UNIQUE (public_id),
            CONSTRAINT uq_user_blocks_pair UNIQUE (blocker_user_id, blocked_user_id),
            CONSTRAINT ck_user_blocks_not_self CHECK (blocker_user_id <> blocked_user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_blocks_blocked ON public.user_blocks (blocked_user_id)")
    op.execute(
        "COMMENT ON TABLE public.user_blocks IS "
        "'§8.1: a block hides both users from each other in feed, proposals and accept. Symmetric on read, "
        "directional as a row; the blocked side is never told.'"
    )

    # --- S11/S12 reports (§17.3) ------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.abuse_reports (
            id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id         UUID NOT NULL,
            reporter_user_id  INTEGER NOT NULL REFERENCES public.users(id),
            subject_type      VARCHAR(16) NOT NULL,
            subject_ref       VARCHAR(64) NOT NULL,
            subject_user_id   INTEGER REFERENCES public.users(id),
            reason_code       VARCHAR(32) NOT NULL,
            details           TEXT,
            status            VARCHAR(16) NOT NULL DEFAULT 'open',
            review_note       TEXT,
            reviewed_by       INTEGER REFERENCES public.users(id),
            reviewed_at       TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            version           INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_abuse_reports_public_id UNIQUE (public_id),
            CONSTRAINT ck_abuse_reports_subject_type CHECK (subject_type IN {_in(REPORT_SUBJECT_TYPES)}),
            CONSTRAINT ck_abuse_reports_reason CHECK (reason_code IN {_in(REPORT_REASON_CODES)}),
            CONSTRAINT ck_abuse_reports_status CHECK (status IN {_in(REPORT_STATUSES)}),
            CONSTRAINT ck_abuse_reports_review CHECK (
                (status IN ('open', 'under_review') AND reviewed_at IS NULL AND reviewed_by IS NULL)
                OR (status IN ('dismissed', 'actioned') AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_abuse_reports_status ON public.abuse_reports (status, id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abuse_reports_reporter_created "
        "ON public.abuse_reports (reporter_user_id, created_at)"
    )
    op.execute(
        "COMMENT ON TABLE public.abuse_reports IS "
        "'§17.3: a user report. details passes the contact filter before it is stored (Q43); a report never "
        "changes a booking, a rating or an account by itself - an operator reviews it.'"
    )

    # --- device -> account links (A7 table, created here because §17.3's signal needs the history) -------------
    # ``device_tokens`` re-binds a token to the newest account and keeps no history, so "several accounts on one
    # device" was unobservable. This append-only link table records the pairing; it holds no raw token (the
    # device_tokens hash is referenced) and nothing about the push payload.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.device_account_links (
            id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            platform      VARCHAR(16) NOT NULL,
            token_hash    CHAR(64) NOT NULL,
            user_id       INTEGER NOT NULL REFERENCES public.users(id),
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_device_account_links UNIQUE (platform, token_hash, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_device_account_links_user ON public.device_account_links (user_id, last_seen_at)"
    )
    op.execute(
        "COMMENT ON TABLE public.device_account_links IS "
        "'§17.3: which accounts a push device has belonged to. Append-only history behind the shared-device "
        "signal; no raw token, no payload, no location.'"
    )

    # --- S12 fraud signals (§17.3) ----------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.fraud_signals (
            id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id        UUID NOT NULL,
            signal_type      VARCHAR(32) NOT NULL,
            subject_user_id  INTEGER NOT NULL REFERENCES public.users(id),
            window_key       VARCHAR(64) NOT NULL,
            evidence         JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            status           VARCHAR(16) NOT NULL DEFAULT 'open',
            review_note      TEXT,
            reviewed_by      INTEGER REFERENCES public.users(id),
            reviewed_at      TIMESTAMPTZ,
            detected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            version          INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_fraud_signals_public_id UNIQUE (public_id),
            CONSTRAINT uq_fraud_signals_window UNIQUE (signal_type, subject_user_id, window_key),
            CONSTRAINT ck_fraud_signals_type CHECK (signal_type IN {_in(FRAUD_SIGNAL_TYPES)}),
            CONSTRAINT ck_fraud_signals_status CHECK (status IN {_in(FRAUD_SIGNAL_STATUSES)}),
            CONSTRAINT ck_fraud_signals_review CHECK (
                (status IN ('open', 'under_review') AND reviewed_at IS NULL AND reviewed_by IS NULL)
                OR (status IN ('dismissed', 'confirmed') AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_fraud_signals_status ON public.fraud_signals (status, id)")
    op.execute(
        "COMMENT ON TABLE public.fraud_signals IS "
        "'§17.3: what the platform noticed, never a verdict. window_key deduplicates one finding per window; "
        "evidence holds counts and public ids only (§15). No automatic block, rating change or payout follows.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("fraud_signals", "abuse_reports", "user_blocks", "device_account_links"):
        op.execute(f"DROP TABLE IF EXISTS public.{table}")
