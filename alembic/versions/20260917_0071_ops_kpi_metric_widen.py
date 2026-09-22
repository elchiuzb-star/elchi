"""ops kpi metric widen (seat-km and net commission)

Owner: A13 (wave 7) - spec §20.4. The last two metrics that were reported as "this system does not measure it"
become measurable from data the platform already stores, so the CHECK of 0064/0069 needs room for them:

  * ``booked_seat_km_ratio`` - booked seat-metres / offered seat-metres, computed from
    ``route_version_stops.cumulative_distance_m`` (the distance a human confirmed with the route version), never
    from a straight line and never from a live routing call;
  * ``seat_km_route_coverage`` - the honest companion of the one above: how many eligible trips actually had a
    usable distance. Without it a ratio computed over half the trips would look like a fact about all of them;
  * ``net_commission_per_corridor`` - captured commission minus reversals on the ``commission_revenue`` ledger
    account, per corridor. Holds, top-ups and the legacy calculated fee never touch that account, so they cannot
    leak into it. It is **not** profit: no operating cost is subtracted, and the DTO reports it as an amount with
    the number of bookings behind it, never as a ratio.

Rules: idempotent (DROP + NOT VALID + VALIDATE, no table rewrite); do not change the revision id, file name or
down_revision; single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0071
Revises: 20260917_0070
Create Date: 2026-09-17 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0071"
down_revision: str = "20260917_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METRICS = (
    "listings_published",
    "listing_to_booking",
    "offer_within_target",
    "booking_completion",
    "driver_fault_cancel",
    "repeat_client",
    "search_with_match_rate",
    "time_to_first_valid_offer",
    "booked_seat_km_ratio",
    "seat_km_route_coverage",
    "net_commission_per_corridor",
)
PREVIOUS_METRICS = METRICS[:8]


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.kpi_daily DROP CONSTRAINT IF EXISTS ck_kpi_daily_metric")
    op.execute(
        f"ALTER TABLE public.kpi_daily ADD CONSTRAINT ck_kpi_daily_metric CHECK (metric IN {_in(METRICS)}) NOT VALID"
    )
    op.execute("ALTER TABLE public.kpi_daily VALIDATE CONSTRAINT ck_kpi_daily_metric")


def downgrade() -> None:
    """Dev/test only: back to the wave 6 metric set (rows of the new metrics must be deleted first)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DELETE FROM public.kpi_daily WHERE metric NOT IN {_in(PREVIOUS_METRICS)}")
    op.execute("ALTER TABLE public.kpi_daily DROP CONSTRAINT IF EXISTS ck_kpi_daily_metric")
    op.execute(
        "ALTER TABLE public.kpi_daily ADD CONSTRAINT ck_kpi_daily_metric CHECK (metric IN "
        f"{_in(PREVIOUS_METRICS)}) NOT VALID"
    )
    op.execute("ALTER TABLE public.kpi_daily VALIDATE CONSTRAINT ck_kpi_daily_metric")
