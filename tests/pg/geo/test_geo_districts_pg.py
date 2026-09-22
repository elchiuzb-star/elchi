"""Wave 10: the district as a direction unit (G16, G17) on PostgreSQL.

The user asked for two things on 17.09.2026: every region except Tashkent city is chosen *with* a district,
and a driver who picked Toshkent -> Qarshi should also be recommended the districts along the way. These tests
guard the honest half of that, which is where such a feature usually goes wrong:

* a district that no verified stop serves must say so (``stops_count = 0``) instead of looking like a place
  you can be picked up from;
* "on the way" is decided by the confirmed route, never by the district belonging to the corridor's region -
  the spec (§6.1, §6.5) says in as many words that not every Toshkent -> Qarshi road passes Chiroqchi.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.contracts.errors import DomainError
from app.db.session import get_db
from app.modules.geo import api as geo_api
from app.modules.geo import service as geo_service
from app.api.v2.web import domain_error_handler
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user

pytestmark = pytest.mark.pg


@pytest.fixture
def world(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fixture = load_geo_fixture(db, actor_user_id=admin)
        db.commit()
    return pg_db, fixture


@pytest.fixture
def client(world) -> Iterator[TestClient]:  # noqa: ANN001
    pg_db, _ = world
    app = FastAPI()
    app.include_router(geo_api.router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)

    def override_db() -> Iterator:
        session = pg_db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def ok(response, status: int = 200):  # noqa: ANN001, ANN201
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


def region_id(pg_db: PgDatabase, code: str) -> str:
    with pg_db.session() as db:
        return geo_service.get_region_by_code(db, code).api_id


def test_only_tashkent_city_is_chosen_without_a_district(client: TestClient) -> None:
    regions = {item["code"]: item for item in ok(client.get("/api/v2/regions"))}
    assert regions["UZ-TK"]["requires_district"] is False
    assert sorted(code for code, item in regions.items() if item["requires_district"]) == ["UZ-QA", "UZ-SA"]


def test_districts_are_listed_per_region_with_their_stop_counts(client: TestClient, world) -> None:  # noqa: ANN001
    pg_db, _ = world
    qashqadaryo = region_id(pg_db, "UZ-QA")
    districts = ok(client.get("/api/v2/districts", params={"region_id": qashqadaryo}))
    names = [item["name_uz"] for item in districts]
    assert names == sorted(names), "the picker gets one ordering, not the insert order"
    assert {"Chiroqchi", "Kitob", "Qarshi"} <= set(names)
    for item in districts:
        assert item["id"].startswith("dst_") and item["region"]["code"] == "UZ-QA"
    # The fixture corridor is `pilot`, so its stops count. The fixture now hangs its stops on the real
    # catalogue districts rather than inventing "Qarshi (fixture)" beside "Qarshi" (wave 19), so the count
    # lands on the row a traveller actually sees.
    assert {item["name_uz"]: item["stops_count"] for item in districts}["Qarshi"] == 1


def test_a_district_without_a_verified_stop_says_zero_instead_of_looking_available(
    client: TestClient, world  # noqa: ANN001
) -> None:
    pg_db, _ = world
    with pg_db.session() as db:
        db.execute(
            text(
                "INSERT INTO geo_districts (public_id, region_id, name_uz) "
                "SELECT gen_random_uuid(), id, 'Yangi tuman (fixture)' FROM regions WHERE code = 'UZ-QA'"
            )
        )
        db.commit()
    districts = {item["name_uz"]: item for item in ok(client.get("/api/v2/districts", params={"region_id": region_id(pg_db, "UZ-QA")}))}
    assert districts["Yangi tuman (fixture)"]["stops_count"] == 0


def test_search_and_unknown_region_behave_like_a_catalogue(client: TestClient, world) -> None:  # noqa: ANN001
    pg_db, _ = world
    found = ok(client.get("/api/v2/districts", params={"q": "chiroq"}))
    assert [item["name_uz"] for item in found] == ["Chiroqchi"]
    assert ok(client.get("/api/v2/districts", params={"region_id": "reg_00000000000000000000000000"})) == []
    assert ok(client.get("/api/v2/districts", params={"q": "x"})) == []


def test_corridor_districts_are_the_confirmed_route_in_travel_order(client: TestClient, world) -> None:  # noqa: ANN001
    _, fixture = world
    items = ok(client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/districts"))
    names = [item["district"]["name_uz"] for item in items]
    assert names[0] == "Toshkent shahri" and names[-1] != "Toshkent shahri"
    assert [item["sequence"] for item in items] == list(range(len(items)))
    on_route = [item["district"]["name_uz"] for item in items if item["on_confirmed_route"]]
    # Both fixture routes start in Tashkent and end in Qarshi; Chiroqchi and Kattaqo'rg'on are on one each.
    assert {"Toshkent shahri", "Qarshi", "Chiroqchi"} <= set(on_route)
    assert on_route[0] == "Toshkent shahri" and on_route[-1] == "Qarshi"
    # Kitob owns a stop of the corridor but no confirmed route calls there: listed, last, and not "on route".
    assert "Kitob" in names and "Kitob" not in on_route
    assert names.index("Kitob") > names.index("Qarshi")


def test_a_district_no_confirmed_route_reaches_is_listed_but_not_called_on_route(
    client: TestClient, world  # noqa: ANN001
) -> None:
    """Spec §6.1: owning a stop on the corridor is not the same as being on the road the driver confirmed."""
    pg_db, fixture = world
    with pg_db.session() as db:
        district = db.execute(
            text(
                "INSERT INTO geo_districts (public_id, region_id, name_uz) "
                "SELECT gen_random_uuid(), id, 'Yo''l tashqarisi (fixture)' FROM regions WHERE code = 'UZ-QA' "
                "RETURNING id"
            )
        ).scalar_one()
        admin = db.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar_one()
        db.execute(
            text(
                "INSERT INTO corridor_stops (public_id, corridor_id, geo_district_id, name_uz, point, is_active, "
                "verified_by, verified_at, meeting_note, sequence_hint) VALUES (gen_random_uuid(), :c, :d, "
                "'Chekka bekat (fixture)', ST_SetSRID(ST_MakePoint(66.0, 39.0), 4326), true, :a, now(), 'Bekat', 99)"
            ),
            {"c": fixture.corridor.id, "d": district, "a": admin},
        )
        db.commit()

    items = ok(client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/districts"))
    entry = next(item for item in items if item["district"]["name_uz"] == "Yo'l tashqarisi (fixture)")
    assert entry["on_confirmed_route"] is False and entry["stops_count"] == 1
    # Everything a confirmed route really covers comes first; the unproven ones follow.
    flags = [item["on_confirmed_route"] for item in items]
    assert flags == sorted(flags, reverse=True)
    assert entry["sequence"] >= flags.index(False)


def test_corridor_districts_hide_a_corridor_that_is_not_public(client: TestClient, world) -> None:  # noqa: ANN001
    pg_db, fixture = world
    with pg_db.session() as db:
        db.execute(
            text("UPDATE service_corridors SET rollout_state = 'internal' WHERE id = :c"), {"c": fixture.corridor.id}
        )
        db.commit()
    response = client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/districts")
    assert response.status_code == 404, response.text
