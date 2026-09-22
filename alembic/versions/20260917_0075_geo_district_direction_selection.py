"""geo + feed: the district as a direction unit

Owner: A2/A5 (wave 10) - user decision 17.09.2026: a direction is chosen as *region -> district* everywhere
except Tashkent city, and a driver who chose Toshkent -> Qarshi must also be recommended the listings of the
districts that lie along the way.

Two additive pieces:

  * ``regions.requires_district`` - the product rule as data, not as a hard-coded name check. It is ``true``
    for every region and ``false`` for Tashkent city (ISO code ``UZ-TK``), where the city itself is the unit.
    Operators can change it per region later without a deploy; the client reads it and hides or shows the
    district step accordingly. Only set by this migration when the column is created, so an operator's later
    correction is never silently reverted by a re-run.
  * ``saved_searches.origin_district_id`` / ``destination_district_id`` - a saved search can now name a
    district end, exactly like a stop or a region. The "exactly one reference per end" CHECKs are rebuilt to
    count all three, so a row can still never mean two things at once.

What this migration deliberately does **not** do: invent districts. ``geo_districts`` stays operator data;
``scripts/import_legacy_districts.py`` copies the verified names from the legacy v1 ``districts`` table
(mapped through ``legacy_city_mappings``), and nothing here claims that a district is "on the way" - that
stays a question for the confirmed route (spec 6.1, 6.5).

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0075
Revises: 20260917_0074
Create Date: 2026-09-17 20:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0075"
down_revision: str = "20260917_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ISO 3166-2:UZ code of Tashkent *city* (UZ-TO is the surrounding region and keeps its districts).
TASHKENT_CITY_CODE = "UZ-TK"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    bind = op.get_bind()

    fresh_column = not bool(
        bind.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'regions' AND column_name = 'requires_district'"
        ).scalar()
    )
    op.execute("ALTER TABLE public.regions ADD COLUMN IF NOT EXISTS requires_district BOOLEAN NOT NULL DEFAULT true")
    if fresh_column:
        # Only on creation: a later operator correction must survive a re-run of this migration.
        op.execute(f"UPDATE public.regions SET requires_district = false WHERE code = '{TASHKENT_CITY_CODE}'")
    op.execute(
        "COMMENT ON COLUMN public.regions.requires_district IS "
        "'Direction selection asks for a district in this region (user decision 17.09.2026). False for "
        "Tashkent city, where the city itself is the unit. Data, not code: operators may change it.'"
    )

    for end in ("origin", "destination"):
        op.execute(f"ALTER TABLE public.saved_searches ADD COLUMN IF NOT EXISTS {end}_district_id BIGINT")
        op.execute(
            f"ALTER TABLE public.saved_searches DROP CONSTRAINT IF EXISTS fk_saved_searches_{end}_district_id"
        )
        op.execute(
            f"ALTER TABLE public.saved_searches ADD CONSTRAINT fk_saved_searches_{end}_district_id "
            f"FOREIGN KEY ({end}_district_id) REFERENCES public.geo_districts (id)"
        )
        op.execute(f"ALTER TABLE public.saved_searches DROP CONSTRAINT IF EXISTS ck_saved_searches_{end}_one")
        op.execute(
            f"ALTER TABLE public.saved_searches ADD CONSTRAINT ck_saved_searches_{end}_one CHECK ("
            f"num_nonnulls({end}_stop_id, {end}_region_id, {end}_district_id) = 1)"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_origin_district ON public.saved_searches (origin_district_id) "
        "WHERE origin_district_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_destination_district "
        "ON public.saved_searches (destination_district_id) WHERE destination_district_id IS NOT NULL"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): dropping the columns loses district-scoped saved searches."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_saved_searches_destination_district")
    op.execute("DROP INDEX IF EXISTS ix_saved_searches_origin_district")
    for end in ("origin", "destination"):
        op.execute(f"ALTER TABLE public.saved_searches DROP CONSTRAINT IF EXISTS ck_saved_searches_{end}_one")
        op.execute(f"ALTER TABLE public.saved_searches DROP COLUMN IF EXISTS {end}_district_id")
        op.execute(
            f"ALTER TABLE public.saved_searches ADD CONSTRAINT ck_saved_searches_{end}_one CHECK ("
            f"num_nonnulls({end}_stop_id, {end}_region_id) = 1)"
        )
    op.execute("ALTER TABLE public.regions DROP COLUMN IF EXISTS requires_district")
