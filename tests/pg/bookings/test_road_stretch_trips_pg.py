"""ADR-0028 (Q159/Q160): A->B end to end with no intermediate point anywhere.

* a road is built from two places - nothing stored in between;
* a trip is a stretch of that road (``route_start_m``/``route_end_m``);
* a request marked on the map is proposed and booked on it: the booking has road positions, its ETA and the driver's
  manifest come from the positions, and the claim holds the seats;
* the DB refuses a booking that would say neither where it rides;
* a trip the system plans from a driver direction is such a stretch too.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.bookings import service as bookings_service
from app.modules.bookings.views import manifest_dto
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ProposalCreate
from app.modules.trips import service as trips_service
from app.modules.trips.schemas import TripCreate
from tests.pg.bookings.conftest import BW, ThreadRef, accept, claims_of, publish_listing, rows, scalar, view
from tests.pg.identity.a1_world import make_vehicle
from tests.pg.marketplace.test_point_endpoints_pg import NEAR_B, NEAR_D, point_body

pytestmark = pytest.mark.pg


def a_b_road(bw: BW) -> tuple[int, str]:
    """The world's road again, confirmed with its two ends only (what ``prepare_road_preview`` stores)."""
    with bw.db.engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO route_versions (public_id, corridor_id, created_by_user_id, source, provider, provider_version, "
                "request_hash, geometry, distance_m, duration_s, is_estimate, status, confirmed_at) "
                "SELECT gen_random_uuid(), corridor_id, created_by_user_id, 'fixture', provider, provider_version, :h, geometry, "
                "distance_m, duration_s, true, 'confirmed', now() FROM route_versions WHERE id = :r RETURNING id, public_id"
            ),
            {"r": bw.w.route_id, "h": uuid.uuid4().hex * 2},
        ).one()
    return row.id, format_public_id(PublicIdPrefix.ROUTE_VERSION, row.public_id)


def stretch_trip(bw: BW, route_public_id: str, *, seats: int = 2) -> tuple[int, str]:
    vehicle = make_vehicle(bw.w, bw.w.driver_id, "01S300SS", seats=seats)
    data = TripCreate.model_validate({
        "vehicle_id": vehicle, "route_version_id": route_public_id,
        "planned_start_at": bw.base.isoformat(), "planned_end_at": (bw.base + timedelta(hours=3)).isoformat(),
        "seat_capacity": seats, "baggage_capacity_ml": 200_000, "max_detour_minutes": 15, "max_detour_m": 5000,
    })
    with bw.db.session() as s:
        trip = trips_service.create_trip(s, driver_user_id=bw.w.driver_id, data=data)
        s.commit()
        return trip.id, trips_service.trip_public_id(trip)


def point_proposal(bw: BW, listing: str, trip_public: str) -> ThreadRef:
    with bw.db.session() as s:
        thread = marketplace_service.submit_proposal(s, listing_public_id=listing, actor_user_id=bw.w.driver_id, data=ProposalCreate(
            trip_id=trip_public, pickup_window_start=bw.base - timedelta(hours=1), pickup_window_end=bw.base + timedelta(hours=8),
            quantity=1, price_basis="per_seat", unit_price_minor=20_000_000,
        ))
        version = marketplace_service.current_version(s, thread)
        ref = ThreadRef(listing, marketplace_service.thread_public_id(thread), marketplace_service.version_public_id(version),
                        version.revision)
        s.commit()
        return ref


def test_a_road_built_from_its_two_ends_has_no_stop(pg_db) -> None:  # noqa: ANN001
    from app.modules.geo import service as geo_service
    from app.modules.geo.routing import FakeRoutingProvider
    from app.modules.geo.types import LatLng
    from tests.fixtures.geo.loader import load_geo_fixture
    from tests.pg.geo.geo_pg_helpers import create_user

    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fx = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
        provider = FakeRoutingProvider()
        plan = geo_service.prepare_road_preview(
            db, provider, corridor_api_id=fx.corridor.api_id, origin=LatLng(41.3111, 69.2797), destination=LatLng(38.8606, 65.7890),
            departure_at=fx.corridor.updated_at + timedelta(days=1),
        )
        db.rollback()
        result, cached = geo_service.fetch_route_outside_transaction(db, provider, plan)
        draft = geo_service.store_route_preview(db, plan, result, actor_user_id=admin, from_cache=cached, cache_ttl_s=0, source="fixture")
        road = geo_service.confirm_route_version(db, actor_user_id=admin, route_version_api_id=draft.api_id)
        db.commit()
    assert road.status == "confirmed"
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM route_version_stops WHERE route_version_id = :r"), {"r": road.id}) == 0


def test_a_request_is_booked_on_a_stretch_of_road_with_no_stop(bw: BW) -> None:
    _route_id, route_public = a_b_road(bw)
    trip_id, trip_public = stretch_trip(bw, route_public)
    trip_row = rows(bw.db, "SELECT route_start_m, route_end_m FROM trips WHERE id = :t", t=trip_id)[0]
    assert (trip_row.route_start_m, trip_row.route_end_m) == (0, 520_000)  # the whole road
    assert scalar(bw.db, "SELECT count(*) FROM trip_stop_occurrences WHERE trip_id = :t", t=trip_id) == 0

    listing = publish_listing(bw, bw.w.client_id, ListingCreate.model_validate(point_body(bw, origin=NEAR_B, destination=NEAR_D)))
    ref = point_proposal(bw, listing, trip_public)
    version = rows(bw.db, "SELECT pickup_occurrence_seq, pickup_position_m, dropoff_position_m FROM proposal_versions "
                          "ORDER BY id DESC LIMIT 1")[0]
    assert version.pickup_occurrence_seq is None and 0 < version.pickup_position_m < version.dropoff_position_m

    booking = accept(bw, ref, bw.w.client_id)
    assert (booking.pickup_occurrence_seq, booking.dropoff_occurrence_seq) == (None, None)
    assert claims_of(bw, booking.id) == [(version.pickup_position_m, version.dropoff_position_m, 1, True)]

    dto = view(bw, booking.id, "client")
    with bw.db.session() as s:
        expected_eta = trips_service.trip_eta_at(trips_service.get_trip(s, trip_id), version.pickup_position_m)
    assert "occurrence_seq" not in dto["pickup"] and "stop" not in dto["pickup"]
    assert dto["pickup"]["planned_arrival_at"] == expected_eta.isoformat().replace("+00:00", "Z")

    with bw.db.session() as s:
        trip, entries = bookings_service.trip_manifest(s, trip_public_id_value=trip_public, viewer_user_id=bw.w.driver_id)
        manifest = manifest_dto(s, trip, entries)
    assert [(row.seq, len(row.pickups), len(row.dropoffs)) for row in manifest.places] == [(1, 1, 0), (2, 0, 1)]
    assert manifest.places[0].point is not None


def test_a_booking_says_where_it_rides(bw: BW) -> None:
    _route_id, route_public = a_b_road(bw)
    _trip_id, trip_public = stretch_trip(bw, route_public)
    listing = publish_listing(bw, bw.w.client_id, ListingCreate.model_validate(point_body(bw, origin=NEAR_B, destination=NEAR_D)))
    booking = accept(bw, point_proposal(bw, listing, trip_public), bw.w.client_id)
    with pytest.raises(DBAPIError, match="ck_bookings_place_known"), bw.db.engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))  # the position columns are set-once otherwise
        conn.execute(text("UPDATE bookings SET pickup_position_m = NULL WHERE id = :b"), {"b": booking.id})


def test_a_trip_planned_from_a_direction_is_a_stretch_of_road() -> None:
    """Covered end to end in test_driver_directions_pg (every offer there plans or re-times such a trip); this pins the
    planner's own output: no stop, a span, a driving time."""
    from app.modules.trips.directions import plan_trip_create

    class _Route:
        api_id = "rtv_x"
        distance_m = 520_000
        duration_s = 25_200

    class _Direction:
        seat_capacity, cargo_capacity_weight_g, cargo_capacity_volume_ml = 4, 0, 0

    from datetime import UTC, datetime

    start = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)
    plan = plan_trip_create(_Direction(), _Route(), vehicle_public_id="veh_x", start_m=173_333, end_m=520_000, departure=start)
    assert (plan.route_start_m, plan.route_end_m) == (173_333, 520_000)
    assert plan.planned_end_at == start + timedelta(seconds=16_800)  # two thirds of the road's 7 h
