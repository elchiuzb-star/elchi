"""ADR-0028 (Q159): A->B positions along the road and interval capacity claims.

Phase 1 (0097) added them, phase 2 (0098) made them the decision, phase 4 (0101, Q160) froze the stop model. What is
proved:

* every proposal version and booking carries its two places as metres along the trip's road;
* accept / release / amendment take and give back the booking's road claim - and only that (no legacy allocation);
* the claims fit the trip at every point of the road (half-open: a seat freed at B is free for a pickup at B), so two
  riders one after the other between two places can share one seat;
* claims are immutable history, positions are written once, a claimed trip's road span is locked (Q63 successor);
* the stop freeze migration is idempotent and leaves positions and claims as they were.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.bookings import service as bookings_service
from tests.pg.bookings.conftest import (
    BW,
    accept,
    booked,
    domain_error,
    driver_trip,
    legacy_offer_booking,
    place_position,
    publish_listing,
    request_with_driver_proposal,
    rows,
    scalar,
)
from tests.pg.conftest import run_alembic
from tests.pg.marketplace.test_point_endpoints_pg import NEAR_B, NEAR_D, full_chain

pytestmark = pytest.mark.pg


def point_position(bw: BW, lat_lng: tuple[float, float]) -> int:
    return int(scalar(
        bw.db,
        "SELECT round(ST_LineLocatePoint(geometry, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)) * distance_m)::int "
        "FROM route_versions WHERE id = :r",
        r=bw.w.route_id, lat=lat_lng[0], lng=lat_lng[1],
    ))


def claims(bw: BW, booking_id: int) -> list[tuple]:
    return [tuple(row) for row in rows(
        bw.db,
        "SELECT from_m, to_m, seats, baggage_ml, cargo_weight_g, cargo_volume_ml, active FROM trip_capacity_claims "
        "WHERE booking_id = :b ORDER BY id",
        b=booking_id,
    )]


def booking_demand(bw: BW, booking_id: int) -> tuple:
    row = rows(bw.db, "SELECT seats, baggage_ml, cargo_weight_g, cargo_volume_ml FROM bookings WHERE id = :b", b=booking_id)[0]
    return tuple(row)


def booking_positions(bw: BW, booking_id: int) -> tuple[int, int]:
    row = rows(bw.db, "SELECT pickup_position_m, dropoff_position_m FROM bookings WHERE id = :b", b=booking_id)[0]
    return row.pickup_position_m, row.dropoff_position_m


def db_error(bw: BW, *statements: tuple[str, dict]) -> str:
    """Run the statements in one transaction and return the database's refusal (the transaction rolls back)."""
    with pytest.raises(DBAPIError) as info, bw.db.engine.begin() as conn:
        for sql, params in statements:
            conn.execute(text(sql), params)
    diag = getattr(getattr(info.value, "orig", None), "diag", None)
    return f"{info.value} constraint={getattr(diag, 'constraint_name', None)}"


# --- dual write ------------------------------------------------------------------------------------------------------


def test_accept_writes_the_places_as_road_positions_and_one_claim(bw: BW) -> None:
    _listing, trip_id, _trip_public, ref = request_with_driver_proposal(bw, plate="01P100AA")
    a, d = place_position(bw, "A"), place_position(bw, "D")
    version = rows(bw.db, "SELECT pickup_position_m, dropoff_position_m FROM proposal_versions ORDER BY id DESC LIMIT 1")[0]
    assert (version.pickup_position_m, version.dropoff_position_m) == (a, d)
    assert rows(bw.db, "SELECT route_start_m, route_end_m FROM trips WHERE id = :t", t=trip_id)[0] == (a, d)

    booking = accept(bw, ref, bw.w.client_id)
    assert booking_positions(bw, booking.id) == (a, d)
    assert claims(bw, booking.id) == [(a, d, *booking_demand(bw, booking.id), True)]
    assert scalar(bw.db, "SELECT count(*) FROM booking_allocations WHERE booking_id = :b", b=booking.id) == 0


def test_a_marked_place_is_projected_onto_the_road(bw: BW) -> None:
    _listing, booking = full_chain(bw)
    b, d = point_position(bw, NEAR_B), point_position(bw, NEAR_D)
    assert 0 < b < d
    assert booking_positions(bw, booking.id) == (b, d)
    assert claims(bw, booking.id)[0][:2] == (b, d)


def test_cancel_releases_the_claim(bw: BW) -> None:
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw, plate="01P101AA")
    booking = accept(bw, ref, bw.w.client_id)
    with bw.db.session() as s:
        bookings_service.cancel_booking(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=1, reason_code="plans_changed",
        )
        s.commit()
    assert [claim[-1] for claim in claims(bw, booking.id)] == [False]
    assert scalar(bw.db, "SELECT released_at IS NOT NULL FROM trip_capacity_claims WHERE booking_id = :b", b=booking.id)
    from app.modules.trips import service as trips_service

    with bw.db.session() as s:  # the release contract: a second release finds nothing to release
        assert trips_service.release_claim(s, booking_id=booking.id, now=bw.base) is False


def test_an_amendment_moves_the_claim(bw: BW) -> None:
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P102AA", seats=3)
    booking = legacy_offer_booking(bw, trip_public, bw.w.client_id)
    with bw.db.session() as s:
        amendment = bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=booking.version, changes={"quantity": 2}, reason="friend joins",
        )
        s.commit()
        amendment_public = format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id)
    with bw.db.session() as s:
        bookings_service.accept_amendment(s, amendment_public_id=amendment_public, actor_user_id=bw.w.driver_id, expected_version=1)
        s.commit()
    history = claims(bw, booking.id)
    assert [(claim[2], claim[-1]) for claim in history] == [(1, False), (2, True)]
    assert history[0][:2] == history[1][:2]  # the places did not move, only the seats


# --- the database proofs -----------------------------------------------------------------------------------------------


def test_claims_are_half_open_and_fit_the_trip_at_every_point(bw: BW) -> None:
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P103AA", seats=1)
    first = booked(bw, trip_public, bw.w.client_id, pickup="A", dropoff="B")
    second = booked(bw, trip_public, bw.w.client2_id, pickup="B", dropoff="D")  # the seat freed at B is taken at B
    a, b, d = place_position(bw, "A"), place_position(bw, "B"), place_position(bw, "D")
    assert claims(bw, first.id)[0][:2] == (a, b) and claims(bw, second.id)[0][:2] == (b, d)

    refused = db_error(
        bw,
        ("UPDATE trip_capacity_claims SET active = false, released_at = now() WHERE booking_id = :b", {"b": second.id}),
        ("INSERT INTO trip_capacity_claims (trip_id, booking_id, from_m, to_m, seats) VALUES (:t, :b, :f, :to, 1)",
         {"t": second.trip_id, "b": second.id, "f": b - 1, "to": d}),
    )
    assert "trip_capacity_claims_exceeded" in refused  # one metre before B the single seat is still taken


def test_two_riders_between_two_places_share_one_seat(bw: BW) -> None:
    """The decision phase 2 exists for: between A and B the first rider leaves at P2 and the second boards there - one
    seat, handed over on the road (the old segment model gave A-B's single seat once)."""
    from app.modules.marketplace import service as marketplace_service
    from app.modules.marketplace.schemas import ListingCreate, ProposalCreate
    from tests.pg.bookings.conftest import ThreadRef
    from tests.pg.marketplace.test_point_endpoints_pg import point_body

    p1, p2, p3 = (41.00, 68.905), (40.70, 68.57), (40.40, 68.235)  # a quarter, half and three quarters of A -> B
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P104AA", seats=1)
    made = []
    for client_id, (origin, destination) in ((bw.w.client_id, (p1, p2)), (bw.w.client2_id, (p2, p3))):
        listing = publish_listing(bw, client_id, ListingCreate.model_validate(point_body(bw, origin=origin, destination=destination)))
        with bw.db.session() as s:
            thread = marketplace_service.submit_proposal(s, listing_public_id=listing, actor_user_id=bw.w.driver_id, data=ProposalCreate(
                trip_id=trip_public, pickup_window_start=bw.base - timedelta(hours=1), pickup_window_end=bw.base + timedelta(hours=8),
                quantity=1, price_basis="per_seat", unit_price_minor=9_000_000,
            ))
            version = marketplace_service.current_version(s, thread)
            ref = ThreadRef(listing, marketplace_service.thread_public_id(thread), marketplace_service.version_public_id(version),
                            version.revision)
            s.commit()
        made.append(accept(bw, ref, client_id))
    first, second = (claims(bw, b.id)[0] for b in made)
    assert first[1] == second[0] and first[2] == second[2] == 1  # the seat is handed over at P2


def test_claims_are_immutable_history(bw: BW) -> None:
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw, plate="01P105AA")
    booking = accept(bw, ref, bw.w.client_id)
    params = {"b": booking.id}
    assert "immutable" in db_error(bw, ("UPDATE trip_capacity_claims SET from_m = from_m + 1 WHERE booking_id = :b", params))
    assert "cannot be deleted" in db_error(bw, ("DELETE FROM trip_capacity_claims WHERE booking_id = :b", params))
    with bw.db.session() as s:
        bookings_service.cancel_booking(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=1, reason_code="plans_changed",
        )
        s.commit()
    assert "re-activated" in db_error(
        bw, ("UPDATE trip_capacity_claims SET active = true, released_at = NULL WHERE booking_id = :b", params)
    )


def test_positions_are_written_once_and_a_claimed_road_span_is_locked(bw: BW) -> None:
    _listing, trip_id, _trip_public, ref = request_with_driver_proposal(bw, plate="01P106AA")
    assert scalar(bw.db, "SELECT count(*) FROM trip_capacity_claims WHERE trip_id = :t", t=trip_id) == 0
    with bw.db.engine.begin() as conn:  # no claim yet: the span is still the trip's own plan
        conn.execute(text("UPDATE trips SET route_end_m = route_end_m - 1 WHERE id = :t"), {"t": trip_id})
        conn.execute(text("UPDATE trips SET route_end_m = route_end_m + 1 WHERE id = :t"), {"t": trip_id})
    booking = accept(bw, ref, bw.w.client_id)
    assert "booking_positions_set_once" in db_error(
        bw, ("UPDATE bookings SET pickup_position_m = pickup_position_m + 1 WHERE id = :b", {"b": booking.id})
    )
    assert "trip_stops_locked" in db_error(
        bw, ("UPDATE trips SET route_start_m = route_start_m + 1 WHERE id = :t", {"t": trip_id})
    )


def test_the_service_refuses_a_claim_the_trip_has_no_room_for(bw: BW) -> None:
    from app.modules.trips import service as trips_service
    from app.modules.trips.rules import ResourceDemand

    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P107AA", seats=1)
    first = booked(bw, trip_public, bw.w.client_id, pickup="A", dropoff="C")
    with bw.db.session() as s:
        error = domain_error(lambda: trips_service.claim(
            s, trip_id=first.trip_id, booking_id=first.id, from_m=place_position(bw, "B"), to_m=place_position(bw, "D"),
            demand=ResourceDemand(seats=1),
        ))
        s.rollback()
    assert error.code is ErrorCode.CAPACITY_UNAVAILABLE
    assert error.details["positions"] == [{"at_m": place_position(bw, "B"), "resource": "seats", "remaining": 0, "requested": 1}]


# --- migration ---------------------------------------------------------------------------------------------------


def test_the_stop_freeze_migration_is_idempotent_and_keeps_positions_and_claims(bw: BW) -> None:
    _listing, point_booking = full_chain(bw)
    _trip_id, trip_public = driver_trip(bw, bw.w.driver2_id, "01P108AA", seats=2)
    other = booked(bw, trip_public, bw.w.client_id, pickup="A", dropoff="C", driver_id=bw.w.driver2_id)
    before = {b.id: (booking_positions(bw, b.id), claims(bw, b.id)) for b in (point_booking, other)}
    spans = rows(bw.db, "SELECT id, route_start_m, route_end_m FROM trips ORDER BY id")

    for command, target in (("downgrade", "20261007_0100"), ("upgrade", "head"), ("upgrade", "head")):
        result = run_alembic(bw.db.url, command, target)
        assert result.returncode == 0, result.stdout + result.stderr

    assert rows(bw.db, "SELECT id, route_start_m, route_end_m FROM trips ORDER BY id") == spans
    assert {b_id: (booking_positions(bw, b_id), claims(bw, b_id)) for b_id in before} == before
    assert "frozen history" in db_error(bw, ("INSERT INTO corridor_stops DEFAULT VALUES", {}))
