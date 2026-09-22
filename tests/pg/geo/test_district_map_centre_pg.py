"""A district carries the point a map should open on - and nothing decides a route by it (0079, wave 17).

The v1 catalogue has always had `districts.center_lat/center_lng` filled, and the v1 picker opened the map
there. The v2 catalogue dropped the column, so every picker opened over Tashkent: somebody in Urgut had to drag
the map across the country before they could drop a pin. The coordinate came back for exactly that reason.

The line this file defends is the one it would be easy to cross. §2 of the specification lists two rejected
approaches by name - matching by equal city/district, and a geo check measured from the district centre - and
Q88 replaced both with projection onto a confirmed route. So a centre here is a *camera position*: the tests
below assert it is filled, that it is inside the country, and that the code that decides routes never reads it.

What a *checked* centre is, and why the v1 values could not simply be trusted, is 0081 and
`test_verified_map_centres_pg.py`.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from sqlalchemy import text

from app.modules.geo import service as geo_service
from tests.pg.conftest import REPO_ROOT, PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user

pytestmark = pytest.mark.pg


def test_the_column_exists_with_both_halves_or_neither(pg_db: PgDatabase) -> None:
    admin = create_user(pg_db, "admin")
    with pg_db.engine.begin() as conn:
        region = conn.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, is_active) "
                "VALUES (gen_random_uuid(), 'UZ-ZZ', 'Sinov viloyati', true) RETURNING id"
            )
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO geo_districts (public_id, region_id, name_uz, center_lat, center_lng) "
                "VALUES (gen_random_uuid(), :r, 'Markazli', 39.7342, 67.0397)"
            ),
            {"r": region},
        )
    assert admin

    with pg_db.engine.begin() as conn:
        # Half a coordinate points the camera nowhere; the CHECK refuses it.
        with pytest.raises(Exception, match="ck_geo_districts_centre_pair"):
            conn.execute(
                text(
                    "INSERT INTO geo_districts (public_id, region_id, name_uz, center_lat) "
                    "VALUES (gen_random_uuid(), :r, 'Yarim', 39.7342)"
                ),
                {"r": region},
            )

    with pg_db.engine.begin() as conn:
        # Somewhere in the Atlantic is not a district of Uzbekistan.
        with pytest.raises(Exception, match="ck_geo_districts_centre_pair"):
            conn.execute(
                text(
                    "INSERT INTO geo_districts (public_id, region_id, name_uz, center_lat, center_lng) "
                    "VALUES (gen_random_uuid(), :r, 'Okean', 0.0, 0.0)"
                ),
                {"r": region},
            )


def test_the_catalogue_carries_it_through_to_the_dto(pg_db: PgDatabase) -> None:
    """What the client reads is what the picker opens on."""
    with pg_db.engine.begin() as conn:
        region = conn.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, is_active) "
                "VALUES (gen_random_uuid(), 'UZ-ZY', 'Samarqand sinov', true) RETURNING id"
            )
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO geo_districts (public_id, region_id, name_uz, center_lat, center_lng) "
                "VALUES (gen_random_uuid(), :r, 'Urgut', 39.4022, 67.2431)"
            ),
            {"r": region},
        )

    with pg_db.session() as db:
        districts = geo_service.list_districts(db, q="Urgut", limit=5)
    urgut = next(d for d in districts if d.name_uz == "Urgut")
    assert (round(urgut.center_lat or 0, 4), round(urgut.center_lng or 0, 4)) == (39.4022, 67.2431)


def test_a_district_without_a_centre_is_answered_honestly(pg_db: PgDatabase) -> None:
    """`None`, not a guess: the client then opens on the country rather than on the wrong town."""
    with pg_db.engine.begin() as conn:
        region = conn.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, is_active) "
                "VALUES (gen_random_uuid(), 'UZ-ZX', 'Joylashmagan', true) RETURNING id"
            )
        ).scalar()
        conn.execute(
            text("INSERT INTO geo_districts (public_id, region_id, name_uz) VALUES (gen_random_uuid(), :r, 'Nomalum')"),
            {"r": region},
        )

    with pg_db.session() as db:
        districts = geo_service.list_districts(db, q="Nomalum", limit=5)
    unknown = next(d for d in districts if d.name_uz == "Nomalum")
    assert unknown.center_lat is None and unknown.center_lng is None


def test_nothing_that_decides_a_route_reads_the_centre() -> None:
    """The guard on §2: matching, capacity and pricing must not learn about district centres.

    Asserted over the source because that is where the mistake would be made - somebody reaching for a
    coordinate that is finally there and using it to answer "is this on the way", which is exactly the
    approach the specification rejected and Q88 replaced.
    """
    watched = [
        "app/modules/marketplace/feed/service.py",
        "app/modules/marketplace/feed/rules.py",
        "app/modules/marketplace/service.py",
        "app/modules/geo/matching.py",
        "app/modules/geo/pricing.py",
        "app/modules/trips/service.py",
        "app/modules/bookings/service.py",
    ]
    offenders = []
    for relative in watched:
        path = pathlib.Path(REPO_ROOT) / relative
        if not path.is_file():
            continue
        if re.search(r"\bcenter_l(at|ng)\b", path.read_text(encoding="utf-8")):
            offenders.append(relative)
    assert offenders == [], (
        "a district centre is a map viewport hint, never a matching input (spec §2, Q88): " + ", ".join(offenders)
    )


def test_a_region_carries_a_centre_for_the_case_with_no_districts(pg_db: PgDatabase) -> None:
    """Tashkent city is the direction unit itself (wave 10), so the region has to answer for it (0080)."""
    with pg_db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, is_active, requires_district, center_lat, center_lng) "
                "VALUES (gen_random_uuid(), 'UZ-TW', 'Shahar sinov', true, false, 41.3111, 69.2797)"
            )
        )
    with pg_db.session() as db:
        regions = geo_service.list_regions(db)
    city = next(r for r in regions if r.code == "UZ-TW")
    assert city.requires_district is False
    assert (round(city.center_lat or 0, 4), round(city.center_lng or 0, 4)) == (41.3111, 69.2797)


def test_a_region_centre_obeys_the_same_bounds(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        with pytest.raises(Exception, match="ck_regions_centre_pair"):
            conn.execute(
                text(
                    "INSERT INTO regions (public_id, code, name_uz, is_active, center_lat, center_lng) "
                    "VALUES (gen_random_uuid(), 'UZ-ZW', 'Okean viloyati', true, 0.0, 0.0)"
                )
            )
