"""marketplace: how many *people* have opened a listing

Owner: A0a/A5 (wave 17) - user decision Q98 (22.09.2026).

Both sides of this market publish and then wait. A driver whose trip offer sits untouched and a client whose
request has no proposals currently see the same screen - nothing - and cannot tell "nobody has seen it" from
"people saw it and passed". Those two need opposite actions: the first means the route or the window is wrong,
the second means the price is.

So the count has to be of *people*, not of openings. A per-open counter is a number the owner cannot use: their
own refreshes, a viewer bouncing in and out, and anyone who wants to inflate it all move it. ``listing_views``
therefore has the pair as its primary key, and the denormalised ``listings.view_count`` is only ever bumped on
the insert that actually created a row. The count is the number of rows, by construction.

Who is deliberately not counted, and why:

* the **owner** - otherwise every check of one's own listing reads as interest;
* **staff** - an operator working a queue is not demand;
* **anonymous** openings, including the public share page (§20.2) - with no identity there is nothing to
  deduplicate by, so counting them would mean the number could be raised by reloading. An approximate number
  presented as an exact one is the kind of invented signal §9 forbids, so those are left out entirely.

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260922_0083
Revises: 20260920_0082
Create Date: 2026-09-22 05:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0083"
down_revision: str = "20260920_0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.listing_views (
            listing_id BIGINT NOT NULL REFERENCES public.listings (id) ON DELETE CASCADE,
            viewer_user_id INTEGER NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
            first_viewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_listing_views PRIMARY KEY (listing_id, viewer_user_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE public.listing_views IS "
        "'Q98: one row per (listing, person) - the primary key is what makes the view count a count of people. "
        "Never written for the owner, for staff or for an anonymous reader.'"
    )
    # The pair index is ordered by listing; a lookup by person (account deletion, abuse review) needs its own.
    op.execute("CREATE INDEX IF NOT EXISTS ix_listing_views_viewer ON public.listing_views (viewer_user_id)")
    op.execute(
        "ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS view_count BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "COMMENT ON COLUMN public.listings.view_count IS "
        "'Q98: distinct people who opened this listing. Denormalised from listing_views and bumped only by the "
        "insert that created a row, so it cannot drift above the number of rows.'"
    )
    # Idempotent backfill: re-running must not double anything, so the column is *set* from the table rather
    # than incremented. On a first run both sides are zero and this is a no-op.
    op.execute(
        """
        UPDATE public.listings AS l
        SET view_count = v.total
        FROM (SELECT listing_id, count(*) AS total FROM public.listing_views GROUP BY listing_id) AS v
        WHERE v.listing_id = l.id AND l.view_count <> v.total
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.listings DROP COLUMN IF EXISTS view_count")
    op.execute("DROP TABLE IF EXISTS public.listing_views")
