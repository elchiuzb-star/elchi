"""A map centre is a checked coordinate or nothing - never a generated one (0081, wave 17).

0079 imported district centres from the v1 catalogue believing they were surveyed town centres. In the
development database all 176 of them are points on a 5-wide, 0.08-degree lattice that
`scripts/seed_admin_required_data.py::district_center()` lays out around each city. Mo'ynoq's lattice point is
roughly 250 km from Mo'ynoq. A picker that opens there and names the district is not a rough guide, it is a
false statement the person then drops a pin on, which AGENTS.md section 9 forbids.

So the rule these tests hold is narrow and checkable: a centre in the catalogue is either a coordinate
somebody checked by hand or it is NULL. The checks run against the migration's own logic rather than against
whatever a particular database happens to hold, so they keep holding on a fresh one.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from sqlalchemy import text

from app.modules.geo import service as geo_service
from tests.pg.conftest import REPO_ROOT, PgDatabase

pytestmark = pytest.mark.pg

MIGRATION = pathlib.Path(REPO_ROOT) / "alembic" / "versions" / "20260919_0081_geo_verified_map_centres.py"


def _migration():
    spec = importlib.util.spec_from_file_location("wave17_centres", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_checked_table_holds_real_towns_not_lattice_points() -> None:
    """Anchors chosen because the lattice puts them somewhere else entirely.

    Urgut sits east of Samarkand and Mo'ynoq on the old Aral shore; the generator had them at 39.73/67.04 and
    42.45/59.53. If somebody ever regenerates this table from the v1 database these three go back to being
    wrong, and this fails.
    """
    module = _migration()
    assert module._DISTRICT_CENTRES[("UZ-SA", "urgut")] == (39.4022, 67.2431)
    assert module._DISTRICT_CENTRES[("UZ-QR", "moynoq")] == (43.7683, 59.0214)
    assert module._DISTRICT_CENTRES[("UZ-SA", "kattaqorgon")] == (39.8989, 66.2561)


def test_no_checked_centre_is_a_lattice_point() -> None:
    """The whole table, against the generator that produced the values it replaces.

    One cell of the lattice is excluded, and has to be: the generator builds it *around* the city centre, so
    its middle cell is the real capital. Qarshi's checked coordinate and Qarshi's lattice origin are the same
    point because both are Qarshi. Every other cell is an offset of up to 0.16 degrees from a town it has
    nothing to do with, and none of those may appear here.
    """
    module = _migration()
    lattice = set()
    for _code, city_lat, city_lng in module._CITY_CENTRES.values():
        origin = module._lattice_point(city_lat, city_lng, 8)
        for index in range(1, 26):
            point = module._lattice_point(city_lat, city_lng, index)
            if point != origin:
                lattice.add(point)
    offenders = [key for key, value in module._DISTRICT_CENTRES.items() if (round(value[0], 6), round(value[1], 6)) in lattice]
    assert offenders == [], f"generated coordinates in the checked table: {offenders}"


def test_the_two_catalogues_spellings_fold_onto_one_key() -> None:
    """The match is by normalised name, which is the only reason 99 districts could be filled at all."""
    module = _migration()
    assert module._norm("Kattaqo'rg'on") == module._norm("Kattaqorgon") == "kattaqorgon"
    assert module._norm("Nukus shahri") == module._norm("Nukus") == "nukus"
    assert module._norm("Mo'ynoq") == "moynoq"


def test_a_district_the_table_does_not_cover_stays_empty(pg_db: PgDatabase) -> None:
    """65 real districts have no checked coordinate. They answer `null`, and the client falls back to the
    region - the right province, rather than a town that is not theirs."""
    with pg_db.engine.begin() as conn:
        region = conn.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, is_active) "
                "VALUES (gen_random_uuid(), 'UZ-Z1', 'Sinov', true) RETURNING id"
            )
        ).scalar()
        conn.execute(
            text("INSERT INTO geo_districts (public_id, region_id, name_uz) VALUES (gen_random_uuid(), :r, 'Qanlikol')"),
            {"r": region},
        )

    with pg_db.session() as db:
        districts = geo_service.list_districts(db, q="Qanlikol", limit=5)
    row = next(d for d in districts if d.name_uz == "Qanlikol")
    assert (row.center_lat, row.center_lng) == (None, None)


def test_the_correction_runs_twice_without_drift(pg_db: PgDatabase) -> None:
    """Re-running clears the same generated rows and fills the same checked ones (idempotent upgrade)."""
    module = _migration()
    with pg_db.engine.begin() as conn:
        city = conn.execute(
            text(
                "INSERT INTO cities (name, name_uz, region, type, requires_district, display_order, is_active) "
                "VALUES ('Samarqand viloyati', 'Samarqand viloyati', 'Samarqand viloyati', 'region', true, 99, true) "
                "RETURNING id"
            )
        ).scalar()
        # display_order 3 puts the lattice at city centre + (0 - 1) * 0.08 lat, (2 - 2) * 0.08 lng.
        lat, lng = module._lattice_point(39.6542, 66.9597, 3)
        legacy = conn.execute(
            text(
                "INSERT INTO districts (city_id, name_uz, is_active, display_order, center_lat, center_lng) "
                "VALUES (:c, 'Urgut', true, 3, :lat, :lng) RETURNING id"
            ),
            {"c": city, "lat": lat, "lng": lng},
        ).scalar()
        region = conn.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, is_active) "
                "VALUES (gen_random_uuid(), 'UZ-SA', 'Samarqand viloyati', true) "
                "ON CONFLICT (code) DO UPDATE SET name_uz = EXCLUDED.name_uz RETURNING id"
            )
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO geo_districts (public_id, region_id, name_uz, legacy_district_id, center_lat, center_lng) "
                "VALUES (gen_random_uuid(), :r, 'Urgut', :d, :lat, :lng)"
            ),
            {"r": region, "d": legacy, "lat": lat, "lng": lng},
        )

    seen = []
    for _ in range(2):
        with pg_db.engine.begin() as conn:
            _run_upgrade(module, conn)
        with pg_db.engine.begin() as conn:
            seen.append(
                conn.execute(
                    text("SELECT center_lat, center_lng FROM geo_districts WHERE name_uz = 'Urgut' AND legacy_district_id = :d"),
                    {"d": legacy},
                ).one()
            )

    assert seen[0] == seen[1]
    assert (round(float(seen[0][0]), 4), round(float(seen[0][1]), 4)) == (39.4022, 67.2431)


def _run_upgrade(module, conn) -> None:
    """Drive the migration body against one connection, without an alembic context."""

    class _Op:
        @staticmethod
        def get_bind():
            return conn

    original = module.op
    module.op = _Op()
    try:
        module.upgrade()
    finally:
        module.op = original
