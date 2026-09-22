"""PostGIS sanity on the test image: geography distance semantics in meters."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase, PgServer

pytestmark = pytest.mark.pg

# Tashkent centre and a point 0.009 deg of latitude north (~1.0 km).
A = (69.2401, 41.2995)
B = (69.2401, 41.3085)


def test_postgis_extension_installed(pg_db: PgDatabase, pg_server: PgServer) -> None:
    with pg_db.engine.connect() as conn:
        installed = conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'"))
        srid = conn.scalar(text("SELECT count(*) FROM spatial_ref_sys WHERE srid = 4326"))
    assert installed is not None and installed.startswith("3.")
    assert installed == pg_server.postgis_version
    assert srid == 1


@pytest.mark.parametrize(("meters", "expected"), [(1500, True), (1100, True), (900, False), (500, False)])
def test_st_dwithin_geography_meters(pg_db: PgDatabase, meters: int, expected: bool) -> None:
    params = {"ax": A[0], "ay": A[1], "bx": B[0], "by": B[1], "m": meters}
    with pg_db.engine.connect() as conn:
        within = conn.scalar(
            text(
                "SELECT ST_DWithin("
                " ST_SetSRID(ST_MakePoint(:ax, :ay), 4326)::geography,"
                " ST_SetSRID(ST_MakePoint(:bx, :by), 4326)::geography, :m)"
            ),
            params,
        )
    assert within is expected


def test_geography_distance_and_gist_index(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        distance = conn.scalar(
            text(
                "SELECT ST_Distance(ST_SetSRID(ST_MakePoint(:ax, :ay), 4326)::geography,"
                " ST_SetSRID(ST_MakePoint(:bx, :by), 4326)::geography)"
            ),
            {"ax": A[0], "ay": A[1], "bx": B[0], "by": B[1]},
        )
        assert 990 < distance < 1010, distance

        conn.execute(text("CREATE TABLE geo_probe (id serial PRIMARY KEY, pt geography(Point, 4326) NOT NULL)"))
        conn.execute(text("CREATE INDEX geo_probe_pt_gist ON geo_probe USING gist (pt)"))
        conn.execute(
            text(
                "INSERT INTO geo_probe (pt) SELECT ST_SetSRID(ST_MakePoint(69 + random(), 41 + random()), 4326)::geography"
                " FROM generate_series(1, 2000)"
            )
        )
        conn.execute(text("ANALYZE geo_probe"))
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in conn.execute(
                text(
                    "EXPLAIN SELECT id FROM geo_probe"
                    " WHERE ST_DWithin(pt, ST_SetSRID(ST_MakePoint(:ax, :ay), 4326)::geography, 1500)"
                ),
                {"ax": A[0], "ay": A[1]},
            )
        )
    assert "geo_probe_pt_gist" in plan, plan
