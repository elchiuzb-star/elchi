"""geo: a region carries the point a map should open on

Owner: A0a/A2 (wave 17). Companion to 0079.

0079 gave every district a viewport hint. One region has no districts in the v2 catalogue at all - Tashkent
city, where the user decision (wave 10) is that the city *is* the direction unit, so `requires_district` is
false and no district rows were imported. Without a centre of its own that region falls all the way back to
the country view, which is exactly the case the complaint was about: choose "Toshkent shahri", get a map of
Uzbekistan.

Same contract as 0079: **a camera position, nothing more.** §2 of the specification rejects deciding a route
by administrative unit and Q88 projects a marked point onto a confirmed route instead. Matching, capacity and
pricing do not read these columns, and `tests/pg/geo/test_district_map_centre_pg.py` guards that over the
source.

Backfill is *derived*, not invented: the average of the centres of the legacy districts that belong to the
region, through `legacy_city_mappings` where one exists and through the same `cities.region = regions.name_uz`
name match the import script uses to propose mappings otherwise. For Tashkent city that is the mean of its
twelve districts, which lands on the city.

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260919_0080
Revises: 20260919_0079
Create Date: 2026-09-19 21:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0080"
down_revision: str = "20260919_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.regions ADD COLUMN IF NOT EXISTS center_lat NUMERIC(10, 7)")
    op.execute("ALTER TABLE public.regions ADD COLUMN IF NOT EXISTS center_lng NUMERIC(10, 7)")
    op.execute(
        "COMMENT ON COLUMN public.regions.center_lat IS "
        "'Advisory map viewport hint (wave 17): where a picker opens for this region when no district centre "
        "applies. Never a matching, capacity or pricing input (spec section 2, Q88).'"
    )
    op.execute("COMMENT ON COLUMN public.regions.center_lng IS 'See center_lat.'")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_regions_centre_pair') THEN
                ALTER TABLE public.regions ADD CONSTRAINT ck_regions_centre_pair CHECK (
                    (center_lat IS NULL) = (center_lng IS NULL)
                    AND (center_lat IS NULL OR (center_lat BETWEEN 37.0 AND 46.0))
                    AND (center_lng IS NULL OR (center_lng BETWEEN 55.0 AND 74.0))
                );
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        WITH legacy AS (
            SELECT r.id AS region_id, d.center_lat, d.center_lng
              FROM public.regions r
              JOIN public.legacy_city_mappings m ON m.region_id = r.id
              JOIN public.districts d ON d.city_id = m.legacy_city_id
             WHERE d.center_lat IS NOT NULL AND d.center_lng IS NOT NULL
            UNION ALL
            -- Regions the import deliberately skipped (Tashkent city): matched by the same name the script
            -- itself proposes mappings on.
            SELECT r.id, d.center_lat, d.center_lng
              FROM public.regions r
              JOIN public.cities c ON c.region = r.name_uz
              JOIN public.districts d ON d.city_id = c.id
             WHERE d.center_lat IS NOT NULL AND d.center_lng IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM public.legacy_city_mappings m WHERE m.region_id = r.id)
        ), centres AS (
            SELECT region_id,
                   round(avg(center_lat)::numeric, 7) AS lat,
                   round(avg(center_lng)::numeric, 7) AS lng
              FROM legacy GROUP BY region_id
        )
        UPDATE public.regions AS r
           SET center_lat = centres.lat,
               center_lng = centres.lng,
               updated_at = now()
          FROM centres
         WHERE centres.region_id = r.id
           AND r.center_lat IS NULL
           AND centres.lat BETWEEN 37.0 AND 46.0
           AND centres.lng BETWEEN 55.0 AND 74.0
        """
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): the picker falls back to opening on the country."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.regions DROP CONSTRAINT IF EXISTS ck_regions_centre_pair")
    op.execute("ALTER TABLE public.regions DROP COLUMN IF EXISTS center_lat")
    op.execute("ALTER TABLE public.regions DROP COLUMN IF EXISTS center_lng")
