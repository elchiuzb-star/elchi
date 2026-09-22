"""geo: a district carries the point a map should open on

Owner: A0a/A2 (wave 17).

The v1 catalogue has kept `districts.center_lat/center_lng` filled for every one of its 176 rows, and the v1
picker opened the map there: choose "Samarqand viloyati / Urgut" and the camera is already over Urgut. The v2
catalogue dropped the column, so `geo_districts` has no coordinate at all (`boundary` exists but is NULL for
every row), and the stage-2 picker opens over Tashkent no matter which district was chosen. Somebody in Urgut
had to drag the map across the country before they could drop a pin.

**This is a viewport hint, not a matching input.** The specification deliberately rejected deciding routes by
district (§2: "shahar va tumanlar aynan teng bo'lishi" and "tuman markazidan 75 km" are both listed as
rejected approaches) and Q88 projects a marked point onto a confirmed route instead. Nothing here changes
that: the columns are advisory, they are read by the client to position a camera, and no matching, capacity or
pricing code may read them. The CHECK keeps them inside Uzbekistan's bounding box so a bad import cannot send
the camera into the ocean.

Backfill: from `districts` through `legacy_district_id`, which 164 of the 170 rows already carry. The six
without it are the synthetic dev fixture districts; they stay NULL and the client falls back to the region.

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260919_0079
Revises: 20260918_0078
Create Date: 2026-09-19 21:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0079"
down_revision: str = "20260918_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.geo_districts ADD COLUMN IF NOT EXISTS center_lat NUMERIC(10, 7)")
    op.execute("ALTER TABLE public.geo_districts ADD COLUMN IF NOT EXISTS center_lng NUMERIC(10, 7)")
    op.execute(
        "COMMENT ON COLUMN public.geo_districts.center_lat IS "
        "'Advisory map viewport hint (wave 17): where a picker opens when this district is chosen. Never a "
        "matching, capacity or pricing input - routes are decided by projection onto a confirmed route (Q88).'"
    )
    op.execute("COMMENT ON COLUMN public.geo_districts.center_lng IS 'See center_lat.'")

    # Both or neither, and inside Uzbekistan: a half-filled or wildly wrong centre would point the camera
    # somewhere the person cannot recognise, which is worse than opening on the default.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_geo_districts_centre_pair'
            ) THEN
                ALTER TABLE public.geo_districts ADD CONSTRAINT ck_geo_districts_centre_pair CHECK (
                    (center_lat IS NULL) = (center_lng IS NULL)
                    AND (center_lat IS NULL OR (center_lat BETWEEN 37.0 AND 46.0))
                    AND (center_lng IS NULL OR (center_lng BETWEEN 55.0 AND 74.0))
                );
            END IF;
        END $$;
        """
    )

    # Backfill from the v1 catalogue. Only rows that are still empty are touched, so a later correction made
    # in v2 is never overwritten by a re-run.
    op.execute(
        """
        UPDATE public.geo_districts AS g
           SET center_lat = d.center_lat,
               center_lng = d.center_lng,
               updated_at = now()
          FROM public.districts AS d
         WHERE g.legacy_district_id = d.id
           AND g.center_lat IS NULL
           AND d.center_lat IS NOT NULL
           AND d.center_lng IS NOT NULL
           AND d.center_lat BETWEEN 37.0 AND 46.0
           AND d.center_lng BETWEEN 55.0 AND 74.0
        """
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): the picker falls back to opening on the country."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.geo_districts DROP CONSTRAINT IF EXISTS ck_geo_districts_centre_pair")
    op.execute("ALTER TABLE public.geo_districts DROP COLUMN IF EXISTS center_lat")
    op.execute("ALTER TABLE public.geo_districts DROP COLUMN IF EXISTS center_lng")
