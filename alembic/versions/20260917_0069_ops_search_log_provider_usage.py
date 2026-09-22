"""ops search log and provider usage

Owner: A5 / A2 / A13 (wave 6) - spec §20.4 (`search_with_match_rate`, `time_to_first_valid_offer`) and §10.8
(map/routing quota accounting).

Two facts the platform measured nowhere, so two KPIs had to be reported as "not measured at all":

  * ``feed_search_events`` - one append-only row per feed search: when, which service and side, which corridor and
    **whether the search found anything**. It deliberately carries **no user id, no stop ids and no filters** -
    the KPI needs "how many searches had a match", not a personal search history (§17.7 data minimisation).
    Rows older than the retention window are deleted by the worker.
  * ``provider_usage_daily`` - per day and provider, how many calls and estimated credits the map/routing adapter
    spent (§10.8). Without it the "70 % warn / 85 % restrict" rule had nothing to read. Counting is local: it is
    Elchi's own tally, not the provider's invoice, and the answer says so.

``time_to_first_valid_offer`` needs no table: it is computed from ``listings.published_at`` and the first
proposal thread of that listing (both already stored) and lands in ``kpi_daily``. Its ``numerator`` is a **sum of
seconds** and its ``denominator`` the number of listings that got an offer, so the reader's division is a mean,
not a ratio - the DTO says so.

``kpi_daily``'s metric CHECK of 0064 listed six metric names; this migration widens it to the eight the code now
computes (DROP + NOT VALID + VALIDATE, so the table is not rewritten and re-running is a no-op).

Rules: idempotent (IF NOT EXISTS); do not change the revision id, file name or down_revision; single head.
downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0069
Revises: 20260917_0068
Create Date: 2026-09-17 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0069"
down_revision: str = "20260917_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.feed_search_events (
            id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            service_type VARCHAR(16) NOT NULL,
            side         VARCHAR(16) NOT NULL,
            corridor_id  BIGINT REFERENCES public.service_corridors(id),
            matched      BOOLEAN NOT NULL,
            result_count INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT ck_feed_search_events_result_count CHECK (result_count >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_feed_search_events_day ON public.feed_search_events (occurred_at, corridor_id)"
    )
    op.execute(
        "COMMENT ON TABLE public.feed_search_events IS "
        "'§20.4 search_with_match_rate. Append-only counter rows: no user id, no stop ids, no filter values - "
        "only service, side, corridor and whether the search found something.'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.provider_usage_daily (
            id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            day          DATE NOT NULL,
            provider     VARCHAR(32) NOT NULL,
            operation    VARCHAR(32) NOT NULL,
            calls        INTEGER NOT NULL DEFAULT 0,
            credits      NUMERIC(12, 2) NOT NULL DEFAULT 0,
            failures     INTEGER NOT NULL DEFAULT 0,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_provider_usage_daily UNIQUE (day, provider, operation),
            CONSTRAINT ck_provider_usage_daily_counts CHECK (calls >= 0 AND failures >= 0 AND credits >= 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE public.provider_usage_daily IS "
        "'§10.8 map/routing quota accounting. Elchi''s own tally of adapter calls and estimated credits - never "
        "the provider invoice; the operator answer says the number is an estimate.'"
    )


    # §20.4: 0064's CHECK froze the six metrics of wave 4; the two measurable ones added in wave 6 need room.
    op.execute("ALTER TABLE public.kpi_daily DROP CONSTRAINT IF EXISTS ck_kpi_daily_metric")
    op.execute(
        """
        ALTER TABLE public.kpi_daily ADD CONSTRAINT ck_kpi_daily_metric CHECK (
            metric IN ('listings_published', 'listing_to_booking', 'offer_within_target', 'booking_completion',
                       'driver_fault_cancel', 'repeat_client', 'search_with_match_rate', 'time_to_first_valid_offer')
        ) NOT VALID
        """
    )
    op.execute("ALTER TABLE public.kpi_daily VALIDATE CONSTRAINT ck_kpi_daily_metric")


def downgrade() -> None:
    """Dev/test only (ADR-0016): both tables are counters, not business state."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS public.feed_search_events")
    op.execute("DROP TABLE IF EXISTS public.provider_usage_daily")
