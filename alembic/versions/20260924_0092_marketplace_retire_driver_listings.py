"""retire driver listings, parcel category catalog, booking-bound operator chat (ADR-0026, Q138-Q142)

Owner: A0a (integrator). A product change decided by the user on 24.09.2026 (ADR-0026). Additive only: nothing that
was applied is rewritten, no history is deleted.

1. **Parcel category catalog (Q140).** The client no longer types length/width/height/weight; they pick a category.
   ``parcel_category_versions`` is versioned and confirmed by a *second* super_admin, exactly like the parcel policy
   (0070): at most one ``active`` version, a ``draft`` is staff-only. ``parcel_category_items`` are immutable rows of
   one version (name, icon key, max dimensions, max weight, max volume) - an agreement points at the item row, so a
   later catalog edit (a new version) can never change an existing agreement. ``synthetic`` marks demo/test catalogs:
   they are never confirmable in production (service guard) and no approved real limits are invented here.
   ``parcel_listing_details``, ``proposal_versions`` and ``bookings`` get ``parcel_category_item_id``; on a booking it
   is frozen after insert (trigger).
2. **Operator chat instead of user-facing disputes (Q141).** ``support_threads`` - one thread per (booking, requester)
   while open (partial unique index: a repeated tap or a network retry returns the same thread), requester side client
   or driver (never both in one thread: the two parties' conversations with staff are private), status open/closed,
   assignee. ``support_messages`` are append-only (client/driver/operator/system authors). Opening or closing a thread
   moves no money, grants nothing and judges nobody - those stay separate authorised finance/ops commands.
   ``disputes_v2`` is kept as a staff-only internal record (its commission/promo/evidence effects are unchanged).
3. **Driver listings retired (Q138).** A trigger refuses any *new* ``kind='trip_offer'`` listing and any transition
   of an existing one *into* ``published``; ``trip_intents`` (ADR-0025, built to answer driver listings) refuse new
   rows. Existing rows stay readable; the ``marketplace.retire_driver_listings`` worker job closes what is still open
   with a technical reason (no penalty, no strike) and never touches a booking.
4. **History carried over (Q141).** Every dispute a client or driver opened becomes an operator thread with its
   description, evidence notes (file ids kept) and the staff decision as messages. Idempotent through
   ``source_dispute_id`` / ``source_evidence_id`` / ``source_kind`` unique keys; the ``disputes_v2`` rows themselves are
   not modified.

FK / object dependencies: 0032 (users), 0039 (listings, parcel_listing_details), 0044 (proposal_versions),
0048 (bookings), 0060 (disputes_v2, dispute_evidence, trust_support_append_only()), 0091 (trip_intents).

Rules: idempotent (IF NOT EXISTS / ON CONFLICT DO NOTHING); single head; downgrade() is dev/test only (ADR-0016).

Revision ID: 20260924_0092
Revises: 20260924_0091
Create Date: 2026-09-24 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260924_0092"
down_revision: str = "20260924_0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATALOG_STATUSES = ("draft", "active", "superseded")
THREAD_STATUSES = ("open", "closed")
REQUESTER_SIDES = ("client", "driver")
AUTHOR_SIDES = ("client", "driver", "operator", "system")
MESSAGE_MAX_LENGTH = 4000


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE TRIGGER {name} {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _parcel_categories()
    _support_threads()
    _retire_driver_listings()
    _carry_over_disputes()


# --- 1. parcel category catalog ----------------------------------------------------------------------------------------


def _parcel_categories() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.parcel_category_versions (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id      UUID NOT NULL,
            label          VARCHAR(64) NOT NULL,
            status         VARCHAR(16) NOT NULL DEFAULT 'draft',
            synthetic      BOOLEAN NOT NULL DEFAULT false,
            source_note    TEXT,
            created_by     INTEGER NOT NULL REFERENCES public.users(id),
            confirmed_by   INTEGER REFERENCES public.users(id),
            confirmed_at   TIMESTAMPTZ,
            effective_from TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            version        INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_parcel_category_versions_public_id UNIQUE (public_id),
            CONSTRAINT uq_parcel_category_versions_label UNIQUE (label),
            CONSTRAINT ck_parcel_category_versions_status CHECK (status IN {_in(CATALOG_STATUSES)}),
            CONSTRAINT ck_parcel_category_versions_confirm CHECK (
                (status = 'draft' AND confirmed_by IS NULL AND confirmed_at IS NULL AND effective_from IS NULL)
                OR (status IN ('active', 'superseded')
                    AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL AND effective_from IS NOT NULL)
            ),
            CONSTRAINT ck_parcel_category_versions_two_people CHECK (confirmed_by IS NULL OR confirmed_by <> created_by)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_parcel_category_versions_active "
        "ON public.parcel_category_versions (status) WHERE status = 'active'"
    )
    op.execute(
        "COMMENT ON TABLE public.parcel_category_versions IS "
        "'Q140: the parcel size catalog the client picks from (no typed dimensions). Draft is staff-only; active "
        "needs a second super_admin. `synthetic` = demo/test values, never confirmable in production.'"
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.parcel_category_items (
            id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id          UUID NOT NULL,
            catalog_version_id BIGINT NOT NULL REFERENCES public.parcel_category_versions(id) ON DELETE RESTRICT,
            code               VARCHAR(32) NOT NULL,
            name_uz            VARCHAR(80) NOT NULL,
            name_ru            VARCHAR(80),
            icon_key           VARCHAR(32) NOT NULL,
            max_length_cm      INTEGER NOT NULL,
            max_width_cm       INTEGER NOT NULL,
            max_height_cm      INTEGER NOT NULL,
            max_weight_g       INTEGER NOT NULL,
            max_volume_ml      INTEGER NOT NULL,
            display_order      INTEGER NOT NULL DEFAULT 100,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_parcel_category_items_public_id UNIQUE (public_id),
            CONSTRAINT uq_parcel_category_items_code UNIQUE (catalog_version_id, code),
            CONSTRAINT ck_parcel_category_items_positive CHECK (
                max_length_cm > 0 AND max_width_cm > 0 AND max_height_cm > 0 AND max_weight_g > 0 AND max_volume_ml > 0
            ),
            CONSTRAINT ck_parcel_category_items_volume CHECK (
                max_volume_ml::bigint <= max_length_cm::bigint * max_width_cm::bigint * max_height_cm::bigint
            ),
            CONSTRAINT ck_parcel_category_items_code CHECK (code ~ '^[a-z][a-z0-9_]{{1,31}}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_parcel_category_items_version "
        "ON public.parcel_category_items (catalog_version_id, display_order, id)"
    )
    # An item is the thing an agreement points at: it never changes and never disappears (a new version supersedes it).
    _trigger("trg_parcel_category_items_append_only", "parcel_category_items",
             "BEFORE UPDATE OR DELETE ON public.parcel_category_items FOR EACH ROW "
             "EXECUTE FUNCTION trust_support_append_only()")
    for table in ("parcel_listing_details", "proposal_versions", "bookings"):
        op.execute(f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS parcel_category_item_id BIGINT")
        op.execute(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_{table}_parcel_category_item') THEN
                    ALTER TABLE public.{table} ADD CONSTRAINT fk_{table}_parcel_category_item
                        FOREIGN KEY (parcel_category_item_id) REFERENCES public.parcel_category_items(id);
                END IF;
            END $$
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.bookings_parcel_category_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.parcel_category_item_id IS DISTINCT FROM OLD.parcel_category_item_id THEN
                RAISE EXCEPTION 'bookings.parcel_category_item_id is frozen after the booking is created'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'booking_parcel_category_frozen';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_bookings_parcel_category_frozen", "bookings",
             "BEFORE UPDATE OF parcel_category_item_id ON public.bookings FOR EACH ROW "
             "EXECUTE FUNCTION public.bookings_parcel_category_frozen()")


# --- 2. operator chat ---------------------------------------------------------------------------------------------------


def _support_threads() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.support_threads (
            id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id         UUID NOT NULL,
            booking_id        BIGINT NOT NULL REFERENCES public.bookings(id),
            requester_user_id INTEGER NOT NULL REFERENCES public.users(id),
            requester_side    VARCHAR(16) NOT NULL,
            status            VARCHAR(16) NOT NULL DEFAULT 'open',
            assigned_to       INTEGER REFERENCES public.users(id),
            assigned_at       TIMESTAMPTZ,
            closed_by         INTEGER REFERENCES public.users(id),
            closed_at         TIMESTAMPTZ,
            close_note        TEXT,
            message_count     INTEGER NOT NULL DEFAULT 0,
            last_message_at   TIMESTAMPTZ,
            last_staff_message_at TIMESTAMPTZ,
            source_dispute_id BIGINT REFERENCES public.disputes_v2(id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            version           INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_support_threads_public_id UNIQUE (public_id),
            CONSTRAINT uq_support_threads_source_dispute UNIQUE (source_dispute_id),
            CONSTRAINT ck_support_threads_side CHECK (requester_side IN {_in(REQUESTER_SIDES)}),
            CONSTRAINT ck_support_threads_status CHECK (status IN {_in(THREAD_STATUSES)}),
            CONSTRAINT ck_support_threads_closed CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
            CONSTRAINT ck_support_threads_counts CHECK (message_count >= 0 AND version >= 1)
        )
        """
    )
    # Q141: one open thread per booking and requester - a repeated tap or retry lands in the same conversation.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_support_threads_open ON public.support_threads (booking_id, requester_user_id) "
        "WHERE status = 'open'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_support_threads_queue ON public.support_threads (status, assigned_to, last_message_at, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_support_threads_requester ON public.support_threads (requester_user_id, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.support_threads_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'support_threads rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF NEW.public_id <> OLD.public_id OR NEW.booking_id <> OLD.booking_id
               OR NEW.requester_user_id <> OLD.requester_user_id OR NEW.requester_side <> OLD.requester_side
               OR NEW.source_dispute_id IS DISTINCT FROM OLD.source_dispute_id OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'support_threads identity columns are immutable'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF OLD.status = 'closed' AND NEW.status <> 'closed' THEN
                RAISE EXCEPTION 'a closed support thread stays closed (a new request opens a new thread)'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'support_thread_closed';
            END IF;
            IF NEW.message_count < OLD.message_count THEN
                RAISE EXCEPTION 'support_threads.message_count never decreases' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_support_threads_guard", "support_threads",
             "BEFORE UPDATE OR DELETE ON public.support_threads FOR EACH ROW EXECUTE FUNCTION public.support_threads_guard()")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.support_messages (
            id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id          UUID NOT NULL,
            thread_id          BIGINT NOT NULL REFERENCES public.support_threads(id),
            author_user_id     INTEGER REFERENCES public.users(id),
            author_side        VARCHAR(16) NOT NULL,
            text               TEXT NOT NULL,
            file_ids           TEXT[] NOT NULL DEFAULT '{{}}',
            filtered           BOOLEAN NOT NULL DEFAULT false,
            source_kind        VARCHAR(32),
            source_ref         BIGINT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_support_messages_public_id UNIQUE (public_id),
            CONSTRAINT uq_support_messages_source UNIQUE (source_kind, source_ref),
            CONSTRAINT ck_support_messages_side CHECK (author_side IN {_in(AUTHOR_SIDES)}),
            CONSTRAINT ck_support_messages_author CHECK ((author_side = 'system') = (author_user_id IS NULL)),
            CONSTRAINT ck_support_messages_text CHECK (char_length(text) BETWEEN 1 AND {MESSAGE_MAX_LENGTH})
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_support_messages_thread ON public.support_messages (thread_id, id)")
    _trigger("trg_support_messages_append_only", "support_messages",
             "BEFORE UPDATE OR DELETE ON public.support_messages FOR EACH ROW EXECUTE FUNCTION trust_support_append_only()")


# --- 3. driver listings and trip intents: no new ones --------------------------------------------------------------------


def _retire_driver_listings() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.listings_driver_offer_retired() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.kind = 'trip_offer' AND (
                   TG_OP = 'INSERT'
                OR (NEW.status IN ('published', 'paused') AND OLD.status IS DISTINCT FROM NEW.status
                    AND OLD.status NOT IN ('published', 'paused'))
                OR (NEW.status = 'published' AND OLD.status = 'paused')) THEN
                RAISE EXCEPTION 'driver listings are retired (ADR-0026, Q138)'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'driver_listing_retired';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_listings_driver_offer_retired", "listings",
             "BEFORE INSERT OR UPDATE OF status ON public.listings FOR EACH ROW "
             "EXECUTE FUNCTION public.listings_driver_offer_retired()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.trip_intents_retired() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'saved trip requests are retired (ADR-0026, Q138)'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'trip_intent_retired';
        END;
        $$
        """
    )
    _trigger("trg_trip_intents_retired", "trip_intents",
             "BEFORE INSERT ON public.trip_intents FOR EACH ROW EXECUTE FUNCTION public.trip_intents_retired()")


# --- 4. disputes opened by a client or driver -> operator threads, history kept --------------------------------------------


def _carry_over_disputes() -> None:
    # The newest still-open dispute of a (booking, opener) pair becomes the open thread; any other one is carried over as a
    # closed thread (the unique index allows one open thread per pair). The disputes_v2 rows are not touched.
    op.execute(
        """
        INSERT INTO public.support_threads (public_id, booking_id, requester_user_id, requester_side, status,
                                            closed_at, close_note, source_dispute_id, created_at, updated_at)
        SELECT gen_random_uuid(), d.booking_id, d.opened_by_user_id, d.opened_by_side,
               CASE WHEN d.keep_open THEN 'open' ELSE 'closed' END,
               CASE WHEN d.keep_open THEN NULL ELSE COALESCE(d.decided_at, now()) END,
               CASE WHEN d.keep_open THEN NULL ELSE 'carried over from dispute ' || d.public_id::text END,
               d.id, d.created_at, now()
          FROM (SELECT d.*,
                       d.status IN ('open', 'under_review')
                       AND row_number() OVER (PARTITION BY d.booking_id, d.opened_by_user_id,
                                                           d.status IN ('open', 'under_review')
                                              ORDER BY d.created_at DESC, d.id DESC) = 1
                       -- a pair that already has an open thread keeps it; the dispute is carried over closed
                       AND NOT EXISTS (SELECT 1 FROM public.support_threads t
                                        WHERE t.booking_id = d.booking_id AND t.requester_user_id = d.opened_by_user_id
                                          AND t.status = 'open') AS keep_open
                  FROM public.disputes_v2 d
                 WHERE d.opened_by_side IN ('client', 'driver')) d
        ON CONFLICT (source_dispute_id) DO NOTHING
        """
    )
    # the complaint itself, in the requester's words
    op.execute(
        """
        INSERT INTO public.support_messages (public_id, thread_id, author_user_id, author_side, text, source_kind,
                                             source_ref, created_at)
        SELECT gen_random_uuid(), t.id, d.opened_by_user_id, d.opened_by_side, d.description, 'dispute', d.id, d.created_at
          FROM public.support_threads t JOIN public.disputes_v2 d ON d.id = t.source_dispute_id
        ON CONFLICT (source_kind, source_ref) DO NOTHING
        """
    )
    # every piece of evidence, with its file ids (nothing is lost)
    op.execute(
        f"""
        INSERT INTO public.support_messages (public_id, thread_id, author_user_id, author_side, text, file_ids,
                                             source_kind, source_ref, created_at)
        SELECT gen_random_uuid(), t.id, e.author_user_id,
               CASE WHEN e.author_side IN ('client', 'driver') THEN e.author_side ELSE 'operator' END,
               left(COALESCE(NULLIF(btrim(e.note), ''), '[dalil fayllari]'), {MESSAGE_MAX_LENGTH}), e.file_ids,
               'dispute_evidence', e.id, e.created_at
          FROM public.support_threads t JOIN public.dispute_evidence e ON e.dispute_id = t.source_dispute_id
        ON CONFLICT (source_kind, source_ref) DO NOTHING
        """
    )
    # the staff decision, as a system line (it happened; it is not re-decided here)
    op.execute(
        f"""
        INSERT INTO public.support_messages (public_id, thread_id, author_user_id, author_side, text, source_kind,
                                             source_ref, created_at)
        SELECT gen_random_uuid(), t.id, NULL, 'system',
               left('Operator qarori: ' || d.status || COALESCE(' (' || d.resolution_code || ')', '')
                    || COALESCE(' - ' || d.resolution_text, ''), {MESSAGE_MAX_LENGTH}),
               'dispute_decision', d.id, d.decided_at
          FROM public.support_threads t JOIN public.disputes_v2 d ON d.id = t.source_dispute_id
         WHERE d.decided_at IS NOT NULL
        ON CONFLICT (source_kind, source_ref) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE public.support_threads t
           SET message_count = m.n, last_message_at = m.last_at, updated_at = now()
          FROM (SELECT thread_id, count(*) AS n, max(created_at) AS last_at FROM public.support_messages GROUP BY thread_id) m
         WHERE m.thread_id = t.id AND t.source_dispute_id IS NOT NULL AND t.message_count < m.n
        """
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_trip_intents_retired ON public.trip_intents")
    op.execute("DROP TRIGGER IF EXISTS trg_listings_driver_offer_retired ON public.listings")
    op.execute("DROP TABLE IF EXISTS public.support_messages")
    op.execute("DROP TABLE IF EXISTS public.support_threads")
    op.execute("DROP TRIGGER IF EXISTS trg_bookings_parcel_category_frozen ON public.bookings")
    for table in ("bookings", "proposal_versions", "parcel_listing_details"):
        op.execute(f"ALTER TABLE public.{table} DROP COLUMN IF EXISTS parcel_category_item_id")
    op.execute("DROP TABLE IF EXISTS public.parcel_category_items")
    op.execute("DROP TABLE IF EXISTS public.parcel_category_versions")
