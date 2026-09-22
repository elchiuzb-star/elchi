"""marketplace + bookings: a direction end may be a map point, not only a verified stop

Owner: A0a (wave 13) - user decision 18.09.2026 (Q88), recorded in AGENTS.md with the conflict it carries.

Until now every end of a listing, a proposal version and a booking was a ``corridor_stops`` row. That is what
spec 6.1/6.2 asks for, and it is why matching, ETA and the "arrived" proof all work on ordered stops. In the
catalogue as it actually stands, though, only 6 of 170 districts have an active stop, so a client who is
required to pick one cannot use the product at all. Q88 accepts the trade: the client may mark a point on the
map inside the chosen district.

The trade is bounded rather than open, and the bounds live here as constraints:

  * each end is **exactly one** of a stop or a point (``num_nonnulls`` CHECK), never both and never neither;
  * a point end carries the district it was marked in, so the feed's district questions keep working and an
    operator can always say which administrative unit a booking belongs to;
  * ``bookings.pickup_occurrence_seq`` stays NOT NULL. A point is projected onto the trip's confirmed route and
    the segment it falls in is what carries the seat/cargo allocation, so ``booking_allocations`` is untouched
    and capacity is still counted per segment (AC12);
  * the projection distance is stored (``*_route_offset_m``) so an operator can see how far off the road a
    booking was agreed, and so the pilot radius can be tightened later from data rather than from opinion.

What this migration deliberately does **not** do: drop the stop ends, or relax anything about corridors. A
listing on a verified stop keeps its ``exact`` match; Q47 (>= 2 active stops before a corridor opens) is a
corridor rule and is unaffected.

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260918_0076
Revises: 20260917_0075
Create Date: 2026-09-18 01:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0076"
down_revision: str = "20260917_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: table -> the two end prefixes it uses.
ENDS: dict[str, tuple[str, str]] = {
    "listings": ("origin", "destination"),
    "proposal_versions": ("pickup", "dropoff"),
    "bookings": ("pickup", "dropoff"),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table, ends in ENDS.items():
        for end in ends:
            op.execute(
                f"ALTER TABLE public.{table} "
                f"ADD COLUMN IF NOT EXISTS {end}_point geometry(Point, 4326)"
            )
            op.execute(f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {end}_district_id BIGINT")
            op.execute(f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {end}_address TEXT")
            op.execute(f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {end}_route_offset_m INTEGER")
            op.execute(
                f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS fk_{table}_{end}_district_id"
            )
            op.execute(
                f"ALTER TABLE public.{table} ADD CONSTRAINT fk_{table}_{end}_district_id "
                f"FOREIGN KEY ({end}_district_id) REFERENCES public.geo_districts (id)"
            )
            # The stop id was NOT NULL; a point end leaves it empty, so the column has to allow it.
            op.execute(f"ALTER TABLE public.{table} ALTER COLUMN {end}_stop_id DROP NOT NULL")
            op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS ck_{table}_{end}_end_one")
            op.execute(
                f"ALTER TABLE public.{table} ADD CONSTRAINT ck_{table}_{end}_end_one CHECK ("
                f"num_nonnulls({end}_stop_id, {end}_point) = 1)"
            )
            # A point without its district would be a place nobody can file, report on or search by.
            op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS ck_{table}_{end}_point_district")
            op.execute(
                f"ALTER TABLE public.{table} ADD CONSTRAINT ck_{table}_{end}_point_district CHECK ("
                f"{end}_point IS NULL OR {end}_district_id IS NOT NULL)"
            )
            op.execute(
                f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS ck_{table}_{end}_route_offset_sane"
            )
            op.execute(
                f"ALTER TABLE public.{table} ADD CONSTRAINT ck_{table}_{end}_route_offset_sane CHECK ("
                f"{end}_route_offset_m IS NULL OR {end}_route_offset_m >= 0)"
            )
            op.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_{end}_district "
                f"ON public.{table} ({end}_district_id) WHERE {end}_district_id IS NOT NULL"
            )
            op.execute(
                f"COMMENT ON COLUMN public.{table}.{end}_point IS "
                f"'Q88 (18.09.2026): a place marked on the map instead of a verified stop. Exactly one of "
                f"{end}_stop_id / {end}_point is set. Matching projects it onto the confirmed route.'"
            )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_listings_origin_point_gist "
        "ON public.listings USING gist (origin_point) WHERE origin_point IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_listings_destination_point_gist "
        "ON public.listings USING gist (destination_point) WHERE destination_point IS NOT NULL"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): dropping the columns loses every point-ended listing and booking."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_listings_destination_point_gist")
    op.execute("DROP INDEX IF EXISTS ix_listings_origin_point_gist")
    for table, ends in ENDS.items():
        for end in ends:
            op.execute(f"DROP INDEX IF EXISTS ix_{table}_{end}_district")
            for suffix in ("end_one", "point_district", "route_offset_sane"):
                op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS ck_{table}_{end}_{suffix}")
            op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS fk_{table}_{end}_district_id")
            for column in ("point", "district_id", "address", "route_offset_m"):
                op.execute(f"ALTER TABLE public.{table} DROP COLUMN IF EXISTS {end}_{column}")
            op.execute(
                f"UPDATE public.{table} SET {end}_stop_id = {end}_stop_id WHERE {end}_stop_id IS NULL"
            )
            op.execute(f"ALTER TABLE public.{table} ALTER COLUMN {end}_stop_id SET NOT NULL")
