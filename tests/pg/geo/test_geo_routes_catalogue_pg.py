"""G18: reading the confirmed routes of a corridor (QA finding F-01, 17.09.2026).

The gap this closes: ``POST /trips`` requires a ``route_version_id``, and the only way to obtain one was
``POST /routes/preview`` - which needs the routing provider. The provider is deliberately off until the
legal/data-flow review (Q24/Q46), which is the configuration production runs in. So a verified driver could
not publish a trip at all, and with no trips there are no ``trip_offer`` listings and no proposals carrying a
trip: the whole supply side of the marketplace was unreachable.

The test that matters is the last one: with the provider refusing, the catalogue still hands the driver a
usable road.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_current_user
from app.api.v2.web import domain_error_handler
from app.contracts.errors import DomainError
from app.db.session import get_db
from app.models import User
from app.modules.geo import api as geo_api
from app.modules.geo.routing import DisabledRoutingProvider
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
    return pg_db, fixture, admin


@pytest.fixture
def client(world) -> Iterator[TestClient]:  # noqa: ANN001
    pg_db, _, _ = world
    app = FastAPI()
    app.include_router(geo_api.router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)

    def override_db() -> Iterator:
        session = pg_db.session()
        try:
            yield session
        finally:
            session.close()

    def user_override(authorization: str | None = Header(default=None)) -> User:
        if not authorization:
            raise HTTPException(status_code=401)
        with pg_db.session() as session:
            user = session.get(User, int(authorization.split()[1]))
            if user is None:
                raise HTTPException(status_code=401)
            return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = user_override
    with TestClient(app) as test_client:
        yield test_client


def ok(response, status: int = 200):  # noqa: ANN001, ANN201
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


def test_the_catalogue_lists_the_confirmed_roads_of_the_corridor(client: TestClient, world) -> None:  # noqa: ANN001
    _, fixture, _ = world
    routes = ok(client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/routes"))
    assert len(routes) == 2, "the fixture confirms two roads"
    for route in routes:
        assert route["id"].startswith("rtv_") and route["status"] == "confirmed"
        assert route["distance_m"] > 0 and route["duration_s"] > 0
        assert len(route["stops"]) >= 2 and route["attribution"], "a road without stops cannot carry a trip"
        seqs = [stop["seq"] for stop in route["stops"]]
        assert seqs == sorted(seqs), "the stop order is the travel order"


def test_a_draft_route_is_not_offered_as_a_road(client: TestClient, world) -> None:  # noqa: ANN001
    """A confirmed route is immutable (DB trigger), so the draft is a new row rather than a downgrade."""
    pg_db, fixture, admin = world
    with pg_db.session() as db:
        db.execute(
            text(
                "INSERT INTO route_versions (public_id, corridor_id, created_by_user_id, source, provider, "
                "provider_version, request_hash, geometry, distance_m, duration_s, is_estimate, status) "
                "SELECT gen_random_uuid(), corridor_id, :a, source, provider, provider_version, "
                "md5(random()::text) || md5(random()::text), geometry, distance_m, duration_s, is_estimate, "
                "'draft' FROM route_versions ORDER BY id LIMIT 1"
            ),
            {"a": admin},
        )
        db.commit()
    routes = ok(client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/routes"))
    assert len(routes) == 2, "the draft is not a road a trip may be planned on"
    assert all(route["status"] == "confirmed" for route in routes)


def test_a_corridor_that_is_not_public_has_no_catalogue(client: TestClient, world) -> None:  # noqa: ANN001
    pg_db, fixture, _ = world
    with pg_db.session() as db:
        db.execute(text("UPDATE service_corridors SET rollout_state = 'internal' WHERE id = :c"),
                   {"c": fixture.corridor.id})
        db.commit()
    assert client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/routes").status_code == 404


def test_a_driver_can_plan_a_trip_while_the_routing_provider_refuses(client: TestClient, world) -> None:  # noqa: ANN001
    """The regression: provider off (Q24/Q46) must not mean "no supply side"."""
    pg_db, fixture, admin = world
    client.app.dependency_overrides[geo_api.get_routing_provider] = DisabledRoutingProvider

    preview = client.post(
        "/api/v2/routes/preview",
        json={
            "stop_ids": [fixture.stops["toshkent"].api_id, fixture.stops["qarshi"].api_id],
            "departure_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
        headers={"Authorization": f"Bearer {admin}", "Idempotency-Key": "qa-f01"},
    )
    assert preview.status_code in (403, 503), preview.text  # no provider -> no new road (AC35)

    routes = ok(client.get(f"/api/v2/corridors/{fixture.corridor.api_id}/routes"))
    assert routes, "with the provider off the driver must still find a confirmed road to plan a trip on"
    assert routes[0]["id"].startswith("rtv_")
