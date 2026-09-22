"""geo: fold the synthetic fixture districts into the real catalogue rows

Owner: A0a/A2 (wave 19).

The dev/test corridor fixture used to create its own districts - "Qarshi (fixture)" next to the real "Qarshi",
"Chiroqchi (fixture)" next to "Chiroqchi" - because it predates the catalogue import. Both then appeared in
the direction picker, one carrying the corridor's stops and the other not, with nothing on screen to say which
was which. `tests/fixtures/geo/loader.py` now hangs its stops on the real district; this does the same for
databases that already have the duplicates.

**It moves the wiring and retires the row - it never rewrites a record.** Ten columns point at
`geo_districts`, and two of those tables are frozen snapshots: `bookings` and `proposal_versions` record the
district a deal was actually struck on, and the booking snapshot is trigger-protected (Q60). Repointing those
would be editing history to tidy a list. So:

1. `corridor_stops` moves to the real district - that is the wiring the fixture got wrong, and the reason the
   duplicate existed at all;
2. any fixture row still referenced by anything is **deactivated**, which takes it out of the picker
   (`list_districts` filters `is_active`) while every foreign key stays exactly where it points;
3. a fixture row nothing references at all is deleted.

Only rows whose name ends in "(fixture)" are considered, and only when a real counterpart exists in the same
region - so production, which has no such rows, is untouched, and a fixture row with nothing to fold into is
left alone rather than orphaned.

Rules: idempotent, single head. downgrade() is dev/test only (ADR-0016) and does not recreate anything - the
fixture loader does that on its next run.

Revision ID: 20260920_0082
Revises: 20260919_0081
Create Date: 2026-09-20 00:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0082"
down_revision: str = "20260919_0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: A fixture district and the real row of the same name in the same region.
_PAIRED = """
    SELECT fixture.id AS fixture_id, real.id AS real_id
      FROM geo_districts AS fixture
      JOIN geo_districts AS real
        ON real.region_id = fixture.region_id
       AND real.id <> fixture.id
       AND lower(real.name_uz) = lower(btrim(regexp_replace(fixture.name_uz, '\\s*\\(fixture\\)$', '')))
     WHERE fixture.name_uz ILIKE '%(fixture)'
"""

#: Every column that points at `geo_districts`, so "still referenced" is asked of all of them.
_REFERRERS = (
    ("bookings", "pickup_district_id"),
    ("bookings", "dropoff_district_id"),
    ("corridor_stops", "geo_district_id"),
    ("listings", "origin_district_id"),
    ("listings", "destination_district_id"),
    ("proposal_versions", "pickup_district_id"),
    ("proposal_versions", "dropoff_district_id"),
    ("saved_searches", "origin_district_id"),
    ("saved_searches", "destination_district_id"),
    ("settlements", "district_id"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. The stops move onto the real district.
    op.execute(
        f"""
        UPDATE corridor_stops AS s
           SET geo_district_id = paired.real_id,
               updated_at = now()
          FROM ({_PAIRED}) AS paired
         WHERE s.geo_district_id = paired.fixture_id
        """
    )

    referenced = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} t WHERE t.{column} = g.id)" for table, column in _REFERRERS
    )

    # 2. Anything still referenced is retired rather than removed, so no foreign key is disturbed.
    op.execute(
        f"""
        UPDATE geo_districts AS g
           SET is_active = false,
               updated_at = now()
          FROM ({_PAIRED}) AS paired
         WHERE g.id = paired.fixture_id
           AND g.is_active
           AND ({referenced})
        """
    )

    # 3. What nothing points at can go.
    op.execute(
        f"""
        DELETE FROM geo_districts AS g
         USING ({_PAIRED}) AS paired
         WHERE g.id = paired.fixture_id
           AND NOT ({referenced})
        """
    )

    # 4. The one row that legitimately survives is Tashkent city's: the region has no districts at all
    #    (wave 10 made the city itself the direction unit), so there is nothing to fold into and a stop cannot
    #    exist without a district. Give it the name the loader now uses, so a database that was migrated and a
    #    database created from scratch hold the same row.
    op.execute(
        """
        UPDATE geo_districts AS g
           SET name_uz = 'Toshkent shahri',
               updated_at = now()
          FROM regions r
         WHERE r.id = g.region_id
           AND r.code = 'UZ-TK'
           AND g.name_uz ILIKE '%(fixture)'
           AND NOT EXISTS (
                 SELECT 1 FROM geo_districts other
                  WHERE other.region_id = g.region_id AND lower(other.name_uz) = 'toshkent shahri'
               )
        """
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016). The fixture loader recreates what it needs on its next run."""
    return
