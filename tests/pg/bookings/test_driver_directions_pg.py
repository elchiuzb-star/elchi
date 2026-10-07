"""ADR-0027 (Q150-Q155): a driver names only a direction; the system plans trips, times offers and books on the way.

The A1 fixture road runs through places A -> B -> C -> D, each in its own district (centre = the place), so a direction
"district of A -> district of D" means exactly what a driver would type in the app.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.contracts.errors import ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.marketplace import directions as market_directions
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ProposalCounter
from app.modules.tracking import service as tracking_service
from app.modules.trips import directions as trip_directions
from app.modules.trips.schemas import DirectionEndInput, DriverDirectionCreate
from tests.pg.bookings.conftest import (
    BW,
    ThreadRef,
    accept,
    domain_error,
    driver_trip,
    publish_listing,
    run_trip_action,
    scalar,
)
from tests.pg.identity.a1_world import make_vehicle
from tests.pg.marketplace.catalog_world import synthetic_category

pytestmark = pytest.mark.pg


@dataclass(frozen=True)
class DW:
    bw: BW
    regions: dict[str, str]  # code -> api id
    districts: dict[str, str]  # place -> district api id


@pytest.fixture
def dw(bw: BW) -> DW:
    """The world's districts (one per place), an approved car for the driver."""
    make_vehicle(bw.w, bw.w.driver_id, "01D777AA", seats=4)
    return DW(bw=bw, regions=dict(bw.w.region_public_ids), districts=dict(bw.w.district_public_ids))


def _end(dw: DW, place: str) -> DirectionEndInput:
    return DirectionEndInput(**dw.bw.w.end(place))


def add_direction(dw: DW, origin: str = "A", destination: str = "D") -> str:
    with dw.bw.db.session() as s:
        direction = trip_directions.create_direction(
            s, driver_user_id=dw.bw.w.driver_id, data=DriverDirectionCreate(origin=_end(dw, origin), destination=_end(dw, destination))
        )
        public_id = trip_directions.direction_public_id(direction)
        s.commit()
        return public_id


def request(dw: DW, owner_id: int, *, origin: str, destination: str, start: datetime, hours: float = 1.0,
            service: str = "passenger", seats: int = 1) -> str:
    body: dict = {
        "kind": "request", "service_type": service,
        "origin_point": dw.bw.w.point(origin), "destination_point": dw.bw.w.point(destination),
        "departure_window_start": start.isoformat(), "departure_window_end": (start + timedelta(hours=hours)).isoformat(),
        "price_basis": "per_seat" if service == "passenger" else "total", "unit_price_minor": 10_000_000,
    }
    if service == "passenger":
        body["passenger"] = {"seat_count": seats, "adults": seats}
    else:
        body["parcel"] = {"parcel_type": "documents", "category_id": synthetic_category(dw.bw.db), "payer": "sender",
                          "sender": {"name": "Aziza", "phone": "+998900000201"}, "receiver": {"name": "Nodira", "phone": "+998977777777"}}
    return publish_listing(dw.bw, owner_id, ListingCreate.model_validate(body))


@dataclass(frozen=True)
class Offer:
    ref: ThreadRef
    trip_public_id: str
    trip_id: int
    created: bool
    retimed: bool
    time_proposal: bool


def offer(dw: DW, direction_id: str, listing_id: str, *, now: datetime, unit: int = 10_000_000, pickup_at: datetime | None = None) -> Offer:
    with dw.bw.db.session() as s:
        result = market_directions.offer_from_direction(
            s, driver_user_id=dw.bw.w.driver_id, direction_public_id_value=direction_id, listing_public_id_value=listing_id,
            unit_price_minor=unit, message=None, pickup_at=pickup_at, now=now,
        )
        version = marketplace_service.current_version(s, result.thread)
        made = Offer(
            ref=ThreadRef(listing_id, marketplace_service.thread_public_id(result.thread),
                          marketplace_service.version_public_id(version), version.revision),
            trip_public_id=format_public_id(PublicIdPrefix.TRIP, result.trip.public_id), trip_id=result.trip.id,
            created=result.trip_created, retimed=result.trip_retimed, time_proposal=result.time_proposal,
        )
        s.commit()
        return made


def feed(dw: DW, direction_id: str, *, now: datetime, service: str = "passenger") -> dict[str, market_directions.DirectionRequest]:
    from app.contracts.enums import ServiceType

    with dw.bw.db.session() as s:
        _d, _t, items = market_directions.direction_requests(
            s, driver_user_id=dw.bw.w.driver_id, direction_public_id_value=direction_id, service_type=ServiceType(service),
            date_from=now - timedelta(days=1), date_to=now + timedelta(days=3), now=now,
        )
        return {marketplace_service.listing_public_id(item.listing): item for item in items}


# --- Q150 -----------------------------------------------------------------------------------------------------------


def test_direction_needs_only_two_ends(dw: DW) -> None:
    direction_id = add_direction(dw)
    with dw.bw.db.session() as s:
        direction = trip_directions.get_owned_direction(s, direction_id, dw.bw.w.driver_id)
        assert direction.corridor_id == dw.bw.w.corridor_id
        assert direction.seat_capacity == 4  # taken from the car
        assert trip_directions.active_trip(s, direction) is None
        routes = trip_directions.direction_routes(s, direction)
        assert [trip_directions.via_district_names(s, r) for r in routes] == [["Jizzax yo'li", "Chiroqchi"]]


def test_duplicate_and_unserved_directions_are_refused(dw: DW) -> None:
    add_direction(dw)
    err = domain_error(lambda: add_direction(dw))
    assert err.code is ErrorCode.VALIDATION_ERROR and err.details["reason"] == "direction_exists"
    backwards = domain_error(lambda: add_direction(dw, origin="D", destination="A"))
    assert backwards.code is ErrorCode.ROUTE_MISMATCH  # the road runs A -> D only


# --- Q151/Q152 -------------------------------------------------------------------------------------------------------


def test_first_offer_plans_the_trip_and_the_next_one_reuses_it(dw: DW) -> None:
    w = dw.bw.w
    direction_id = add_direction(dw)
    now = w.base_time - timedelta(hours=6)
    full = request(dw, w.client_id, origin="A", destination="D", start=w.base_time)
    part = request(dw, w.client2_id, origin="B", destination="C", start=w.base_time + timedelta(hours=1, minutes=30), hours=3)
    items = feed(dw, direction_id, now=now)
    assert items[full].fit == "no_trip" and items[full].match_type.value == "exact"
    assert items[part].match_type.value == "on_route"

    first = offer(dw, direction_id, full, now=now)
    assert first.created and not first.retimed
    assert scalar(dw.bw.db, "SELECT direction_id IS NOT NULL FROM trips WHERE id = :t", t=first.trip_id)
    # ADR-0028: the planned trip is a stretch of road, a span in metres
    assert scalar(dw.bw.db, "SELECT route_start_m < route_end_m FROM trips WHERE id = :t", t=first.trip_id)
    start = scalar(dw.bw.db, "SELECT planned_start_at FROM trips WHERE id = :t", t=first.trip_id)
    assert start == w.base_time  # leaves when the client at A wants to be picked up

    second = offer(dw, direction_id, part, now=now)
    assert second.trip_id == first.trip_id and not second.created
    assert feed(dw, direction_id, now=now)[part].fit == "fits_trip"


def test_an_empty_trip_follows_the_next_client(dw: DW) -> None:
    w = dw.bw.w
    direction_id = add_direction(dw)
    now = w.base_time - timedelta(hours=6)
    early = request(dw, w.client_id, origin="A", destination="D", start=w.base_time)
    first = offer(dw, direction_id, early, now=now)
    with dw.bw.db.session() as s:  # the driver takes the offer back: no booking, no open offer on the trip
        marketplace_service.withdraw_proposal(s, thread_public_id_value=first.ref.thread_id, actor_user_id=w.driver_id,
                                              expected_revision=first.ref.revision, reason_code=None, now=now)
        s.commit()
    later = request(dw, w.client2_id, origin="A", destination="D", start=w.base_time + timedelta(hours=5))
    moved = offer(dw, direction_id, later, now=now)
    assert moved.trip_id == first.trip_id and moved.retimed
    assert scalar(dw.bw.db, "SELECT planned_start_at FROM trips WHERE id = :t", t=moved.trip_id) == w.base_time + timedelta(hours=5)


# --- Q153 time proposal --------------------------------------------------------------------------------------------------


def test_time_proposal_is_booked_only_with_the_clients_consent(dw: DW) -> None:
    w = dw.bw.w
    direction_id = add_direction(dw)
    now = w.base_time - timedelta(hours=6)
    booked = offer(dw, direction_id, request(dw, w.client_id, origin="A", destination="D", start=w.base_time), now=now)
    accept(dw.bw, booked.ref, w.client_id, now=now)  # the trip now has a passenger: its time is fixed

    # the car reaches C about 4 h 45 min after A; the client asks ~2 h later - inside the Q157 "3 h earlier" limit
    late = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=7))
    item = feed(dw, direction_id, now=now)[late]
    assert item.fit == "time_differs" and item.pickup_eta is not None

    plain = domain_error(lambda: offer(dw, direction_id, late, now=now))
    assert plain.code is ErrorCode.TIME_WINDOW_CONFLICT and "eta" in plain.details

    proposal = offer(dw, direction_id, late, now=now, pickup_at=item.pickup_eta)
    assert proposal.time_proposal and proposal.trip_id == booked.trip_id

    # the client cannot move the window outside on their own...
    with dw.bw.db.session() as s:
        current = marketplace_service.current_version(s, marketplace_service.get_thread_by_public_id(s, proposal.ref.thread_id))
        assert current.outside_request_window
        window = (current.pickup_window_start + timedelta(hours=1), current.pickup_window_end + timedelta(hours=1))
    err = domain_error(lambda: _counter(dw, proposal.ref, w.client2_id, now=now, window=window))
    assert err.code is ErrorCode.TIME_WINDOW_CONFLICT
    # ...but a price counter keeps the driver's time - and is the client's consent to it
    countered = _counter(dw, proposal.ref, w.client2_id, now=now, unit=9_000_000)
    booking = accept(dw.bw, countered, w.driver_id, now=now)
    assert booking.terms_snapshot["outside_request_window"] is True
    assert booking.pickup_window_end < w.base_time + timedelta(hours=7)  # the driver's time, not the client's window


def _counter(dw: DW, ref: ThreadRef, actor_id: int, *, now: datetime, unit: int | None = None,
             window: tuple[datetime, datetime] | None = None) -> ThreadRef:
    with dw.bw.db.session() as s:
        thread = marketplace_service.counter_proposal(
            s, thread_public_id_value=ref.thread_id, actor_user_id=actor_id, now=now,
            data=ProposalCounter(
                expected_revision=ref.revision, unit_price_minor=unit,
                pickup_window_start=window[0] if window else None, pickup_window_end=window[1] if window else None,
            ),
        )
        version = marketplace_service.current_version(s, thread)
        made = ThreadRef(ref.listing_id, ref.thread_id, marketplace_service.version_public_id(version), version.revision)
        s.commit()
        return made


# --- Q155 point pickup just before a place on the road ------------------------------------------------------------------------------


def test_a_place_just_before_b_is_bookable(dw: DW) -> None:
    """The 06.10.2026 live finding: submit took the interpolated ETA, accept the ETA of the stop opening the segment."""
    w = dw.bw.w
    trip_id, trip_public = driver_trip(dw.bw, w.driver2_id, "01P155AA")  # A at base, B at base+1h (A1 fixture trip)
    # On the road just before B: the fixture puts B at line fraction 1/3, so 0.32 projects into segment A->B
    with dw.bw.db.engine.connect() as conn:
        lng, lat = conn.execute(text(
            "SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_LineInterpolatePoint(geometry, 0.32) AS p FROM route_versions WHERE id = :r) q"
        ), {"r": w.route_id}).one()
    body = ListingCreate.model_validate({
        "kind": "request", "service_type": "passenger",
        "origin_point": {"lat": lat, "lng": lng, "district_id": dw.districts["B"]},
        "destination_point": {"lat": 38.86, "lng": 65.80, "district_id": dw.districts["D"]},
        "departure_window_start": (w.base_time + timedelta(minutes=40)).isoformat(),
        "departure_window_end": (w.base_time + timedelta(minutes=80)).isoformat(),
        "price_basis": "per_seat", "unit_price_minor": 9_000_000, "passenger": {"seat_count": 1, "adults": 1},
    })
    listing = publish_listing(dw.bw, w.client_id, body)
    with dw.bw.db.session() as s:
        from app.modules.marketplace.schemas import ProposalCreate

        thread = marketplace_service.submit_proposal(s, listing_public_id=listing, actor_user_id=w.driver2_id, data=ProposalCreate(
            trip_id=trip_public, pickup_window_start=w.base_time + timedelta(minutes=40),
            pickup_window_end=w.base_time + timedelta(minutes=80), quantity=1, price_basis="per_seat", unit_price_minor=9_000_000,
        ))
        version = marketplace_service.current_version(s, thread)
        assert version.pickup_position_m is not None  # the place itself, as metres along the road
        ref = ThreadRef(listing, marketplace_service.thread_public_id(thread), marketplace_service.version_public_id(version), version.revision)
        s.commit()
    booking = accept(dw.bw, ref, w.client_id)
    assert booking.trip_id == trip_id


# --- Q154 on the way ---------------------------------------------------------------------------------------------------


def _running_trip(dw: DW) -> tuple[str, Offer]:
    w = dw.bw.w
    direction_id = add_direction(dw)
    first = offer(dw, direction_id, request(dw, w.client_id, origin="A", destination="D", start=w.base_time, seats=2),
                  now=w.base_time - timedelta(hours=6))
    accept(dw.bw, first.ref, w.client_id, now=w.base_time - timedelta(hours=6))
    run_trip_action(dw.bw, first.trip_id, w.driver_id, "start_boarding", now=w.base_time - timedelta(minutes=30))
    with dw.bw.db.session() as s:
        booking_id = s.execute(text("SELECT id FROM bookings WHERE trip_id = :t"), {"t": first.trip_id}).scalar_one()
    from tests.pg.bookings.conftest import act, codes_for

    act(dw.bw, booking_id, w.driver_id, "board", now=w.base_time - timedelta(minutes=20))
    run_trip_action(dw.bw, first.trip_id, w.driver_id, "depart", now=w.base_time + timedelta(minutes=5))
    return direction_id, first


def test_a_moving_trip_takes_a_pickup_still_ahead(dw: DW) -> None:
    w = dw.bw.w
    direction_id, first = _running_trip(dw)
    now = w.base_time + timedelta(hours=1)
    rider = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=4), hours=2)
    assert feed(dw, direction_id, now=now)[rider].fit == "fits_trip"
    made = offer(dw, direction_id, rider, now=now)
    assert made.trip_id == first.trip_id
    booking = accept(dw.bw, made.ref, w.client2_id, now=now)
    assert booking.service_status == "awaiting_pickup"  # the trip already passed start_boarding
    assert booking.terms_snapshot["booked_trip_status"] == "in_progress"

    parcel = request(dw, w.client2_id, origin="B", destination="D", start=w.base_time + timedelta(hours=1), hours=3, service="parcel")
    made = offer(dw, direction_id, parcel, now=now)
    booked_parcel = accept(dw.bw, made.ref, w.client2_id, now=now)
    assert booked_parcel.service_status == "in_transit"  # on the way with the trip (Q139/Q142)


def test_a_pickup_the_car_has_passed_is_refused(dw: DW, monkeypatch: pytest.MonkeyPatch) -> None:
    w = dw.bw.w
    direction_id, _first = _running_trip(dw)
    passed = request(dw, w.client2_id, origin="B", destination="D", start=w.base_time + timedelta(hours=2), hours=3)
    late = w.base_time + timedelta(hours=3)  # the schedule put the car at B about 2 h 20 min after A
    assert passed not in feed(dw, direction_id, now=late)
    err = domain_error(lambda: offer(dw, direction_id, passed, now=late))
    assert err.code is ErrorCode.BOOKING_CUTOFF_PASSED and err.details["reason"] == "pickup_passed"

    # the schedule says C is still ahead, the phone says the car is already at C
    ahead = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=4), hours=2)
    now = w.base_time + timedelta(hours=1)
    at_c = tracking_service.LivePoint(captured_at=now - timedelta(minutes=1), received_at=now, lat=39.20, lng=66.60, accuracy_m=10)
    monkeypatch.setattr(tracking_service, "trip_live_point", lambda session, trip_id: at_c)
    err = domain_error(lambda: offer(dw, direction_id, ahead, now=now))
    assert err.code is ErrorCode.BOOKING_CUTOFF_PASSED and "ahead_m" in err.details


def test_an_interrupted_trip_takes_no_new_business(dw: DW) -> None:
    w = dw.bw.w
    direction_id, first = _running_trip(dw)
    run_trip_action(dw.bw, first.trip_id, w.driver_id, "interrupt", now=w.base_time + timedelta(minutes=30), reason="g'ildirak")
    rider = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=4), hours=2)
    err = domain_error(lambda: offer(dw, direction_id, rider, now=w.base_time + timedelta(hours=1)))
    # interrupted is not an active direction trip any more: the next trip would be planned, but this car is still on it
    assert err.code in (ErrorCode.SCHEDULE_CONFLICT, ErrorCode.BOOKING_CUTOFF_PASSED)


# --- Q157 asymmetric limits ------------------------------------------------------------------------------------------


def _booked_trip(dw: DW) -> str:
    w = dw.bw.w
    direction_id = add_direction(dw)
    now = w.base_time - timedelta(hours=6)
    booked = offer(dw, direction_id, request(dw, w.client_id, origin="A", destination="D", start=w.base_time), now=now)
    accept(dw.bw, booked.ref, w.client_id, now=now)  # the trip's time is fixed from here on
    return direction_id


def test_a_pickup_far_earlier_than_asked_is_not_offered(dw: DW) -> None:
    """Client wants C at base+12h, the car is there at ~base+4h45: 7 h earlier - beyond the 3 h early limit."""
    w = dw.bw.w
    direction_id = _booked_trip(dw)
    now = w.base_time - timedelta(hours=6)
    far = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=12))
    assert far not in feed(dw, direction_id, now=now)  # not even under "vaqti boshqa"
    plain = domain_error(lambda: offer(dw, direction_id, far, now=now))
    assert plain.code is ErrorCode.TIME_WINDOW_CONFLICT and plain.details["time_proposal_possible"] is False
    eta = datetime.fromisoformat(plain.details["eta"])
    too_far = domain_error(lambda: offer(dw, direction_id, far, now=now, pickup_at=eta))
    assert too_far.code is ErrorCode.TIME_WINDOW_CONFLICT and too_far.details["reason"] == "time_proposal_too_far"
    assert (too_far.details["max_early_minutes"], too_far.details["max_late_minutes"]) == (180, 720)


def test_a_later_pickup_within_twelve_hours_may_be_proposed(dw: DW) -> None:
    """Client wants C at base+1h..+2h, the car is there ~2 h 45 min after the window ends: a late proposal is fine."""
    w = dw.bw.w
    direction_id = _booked_trip(dw)
    now = w.base_time - timedelta(hours=6)
    early_client = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=1))
    item = feed(dw, direction_id, now=now)[early_client]
    assert item.fit == "time_differs"
    made = offer(dw, direction_id, early_client, now=now, pickup_at=item.pickup_eta)
    assert made.time_proposal


def test_the_limits_are_configuration(dw: DW, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q157: the values live in settings (env), so a pilot can move them without a release."""
    from app.core.config import settings

    w = dw.bw.w
    direction_id = _booked_trip(dw)
    now = w.base_time - timedelta(hours=6)
    two_hours_early = request(dw, w.client2_id, origin="C", destination="D", start=w.base_time + timedelta(hours=7))
    assert two_hours_early in feed(dw, direction_id, now=now)
    monkeypatch.setattr(settings, "time_proposal_max_early_shift_minutes", 60)
    assert two_hours_early not in feed(dw, direction_id, now=now)
