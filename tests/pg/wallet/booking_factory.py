"""Real ``bookings`` rows for wallet PG tests (A3, wave 2.1; FKs from 0055).

Built on A1's shared ``world`` fixture and the same service path as ``tests/pg/bookings/conftest.py``
(publish a passenger request, a driver proposal on a real trip). The booking row itself is inserted from that
proposal version with SQL instead of A4's ``accept_proposal``: accept would hold the fee on its own, while wallet
tests drive ``hold_fee``/``capture_fee`` directly. Nothing here funds a wallet or writes ``feature_flag_values``
(Q72 not involved). Proposals do not reserve seats (§5.3), so one trip serves any number of bookings.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ProposalCreate
from tests.pg.identity.a1_world import World, add_user, make_trip, make_vehicle, world  # noqa: F401  (shared A1 fixture)

_INSERT_BOOKING = text(
    "INSERT INTO bookings (public_id, service_type, service_status, commission_status, client_user_id, driver_user_id, "
    "trip_id, corridor_id, request_listing_id, proposal_thread_id, accepted_proposal_version_id, route_version_id, "
    "trip_version, pickup_stop_id, dropoff_stop_id, pickup_occurrence_seq, dropoff_occurrence_seq, pickup_window_start, "
    "pickup_window_end, quantity, seats, price_basis, unit_price_minor, total_minor, fee_policy_id, fee_bps, "
    "commission_minor, listing_version, listing_terms_version, terms_snapshot) "
    "SELECT gen_random_uuid(), 'passenger', 'confirmed', CASE WHEN v.fee_bps = 0 THEN 'exempt' ELSE 'held' END, "
    "t.client_user_id, :driver, t.trip_id, l.corridor_id, l.id, t.id, v.id, :route, tr.version, v.pickup_stop_id, "
    "v.dropoff_stop_id, COALESCE(v.pickup_occurrence_seq, 1), COALESCE(v.dropoff_occurrence_seq, 4), "
    "v.pickup_window_start, v.pickup_window_end, v.quantity, v.quantity, v.price_basis, v.unit_price_minor, "
    "v.total_minor, v.fee_policy_id, v.fee_bps, v.commission_minor, v.listing_version, l.terms_version, "
    "'{\"source\": \"wallet_test_factory\"}'::jsonb "
    "FROM proposal_versions v JOIN proposal_threads t ON t.id = v.thread_id JOIN listings l ON l.id = t.listing_id "
    "JOIN trips tr ON tr.id = t.trip_id WHERE v.id = :version RETURNING id"
)


class BookingFactory:
    """``new(driver_user_id=...)`` -> internal booking id; ``ids(n, ...)`` for several (create before threads start)."""

    def __init__(self, world: World) -> None:  # noqa: F811
        self.world = world
        self._trip_public_id: str | None = None
        self._count = 0

    def _trip(self) -> str:
        if self._trip_public_id is None:
            vehicle = make_vehicle(self.world, self.world.driver_id, "01A555WT", seats=4)
            _, self._trip_public_id = make_trip(self.world, self.world.driver_id, vehicle, start=self.world.base_time)
        return self._trip_public_id

    def new(self, *, driver_user_id: int, unit_price_minor: int = 20_000_000) -> int:
        w = self.world
        trip_public_id = self._trip()
        self._count += 1
        start = w.base_time
        # A separate request per booking keeps uq_bookings_request_listing_binding (AC06) satisfied.
        listing_body = ListingCreate.model_validate({
            "kind": "request",
            "service_type": "passenger",
            "origin_stop_id": w.stop_public_ids["A"],
            "destination_stop_id": w.stop_public_ids["D"],
            "departure_window_start": start.isoformat(),
            "departure_window_end": (start + timedelta(hours=1)).isoformat(),
            "price_basis": "per_seat",
            "unit_price_minor": unit_price_minor,
            "passenger": {"seat_count": 1, "adults": 1,
                          "baggage": {"pieces": 1, "total_weight_g": 10_000, "total_volume_ml": 40_000}},
        })
        proposal_body = ProposalCreate.model_validate({
            "trip_id": trip_public_id,
            "pickup_stop_id": w.stop_public_ids["A"],
            "dropoff_stop_id": w.stop_public_ids["D"],
            "pickup_window_start": start.isoformat(),
            "pickup_window_end": (start + timedelta(minutes=30)).isoformat(),
            "quantity": 1,
            "price_basis": "per_seat",
            "unit_price_minor": unit_price_minor,
        })
        with w.db.session() as s:
            # One client per booking: identical requests of one owner are refused as duplicates (spec §5.4).
            client_id = add_user(s, f"+99891{uuid.uuid4().int % 10_000_000:07d}", "client")
            listing = marketplace_service.create_listing(s, owner_user_id=client_id, data=listing_body)
            listing_public_id = marketplace_service.listing_public_id(listing)
            marketplace_service.publish_listing(s, listing_public_id=listing_public_id, actor_user_id=client_id,
                                                expected_version=listing.version)
            thread = marketplace_service.submit_proposal(s, listing_public_id=listing_public_id,
                                                         actor_user_id=w.driver_id, data=proposal_body)
            version = marketplace_service.current_version(s, thread)
            booking_id = s.execute(_INSERT_BOOKING, {"driver": driver_user_id, "route": w.route_id,
                                                     "version": version.id}).scalar_one()
            s.commit()
        return int(booking_id)

    def ids(self, n: int, *, driver_user_id: int) -> list[int]:
        return [self.new(driver_user_id=driver_user_id) for _ in range(n)]


@pytest.fixture
def bookings(world: World) -> BookingFactory:  # noqa: F811
    return BookingFactory(world)
