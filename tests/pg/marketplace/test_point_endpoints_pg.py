"""Map-point direction ends: the invariants Q88 bought the flexibility with (wave 13).

Letting a client mark a place on the map instead of picking a verified stop is a deliberate step away from
spec §6.1/§6.2, and it is only safe because of the bounds recorded with the decision. Each of those bounds is
asserted here against a real PostGIS route, because every one of them is the difference between "a pickup the
driver can actually make" and "a pin somewhere in the country":

* an end is a stop **or** a point, never both and never neither;
* a point must project onto the corridor's confirmed road, within the radius *that corridor* configures;
* the pickup must come before the dropoff along the road;
* capacity is still counted per route segment, so a point booking consumes the same allocations a stop one
  would;
* a point end is never called an ``exact`` match - the person did not pick the driver's stop;
* the district travels as metadata and is never used to decide whether the ride is possible;
* what was agreed is snapshotted onto the booking rather than recomputed from the listing;
* and stop-ended listings keep working exactly as before.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ProposalCreate
from tests.pg.bookings.conftest import (  # noqa: F401  (bw/world are fixtures)
    BW,
    accept,
    bw,
    driver_trip,
    domain_error,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    scalar,
    world,
)

pytestmark = pytest.mark.pg

#: The world's route is LINESTRING(69.24 41.30, 67.90 40.10, 66.60 39.20, 65.80 38.86) with stops A..D on its
#: vertices. These are "just off" the second and fourth vertex - a kerb, not another district.
NEAR_B = (40.105, 67.90)
NEAR_D = (38.86, 65.80)
FAR_AWAY = (42.45, 59.60)  # Nukus: nowhere near this corridor


def district_public_id(bw: BW) -> str:
    value = scalar(bw.db, "SELECT public_id FROM geo_districts ORDER BY id LIMIT 1")
    return format_public_id(PublicIdPrefix.DISTRICT, value)


def point_body(bw: BW, *, origin=NEAR_B, destination=NEAR_D, **overrides) -> dict:
    district = district_public_id(bw)
    body = passenger_request_body(bw, seats=1).model_dump(mode="json")
    body.pop("origin_stop_id", None)
    body.pop("destination_stop_id", None)
    body["origin_point"] = {"lat": origin[0], "lng": origin[1], "district_id": district, "address": "A ko'chasi 1"}
    body["destination_point"] = {"lat": destination[0], "lng": destination[1], "district_id": district, "address": "B ko'chasi 2"}
    # A place between two stops is reached *between* their arrival times, so the window has to span the
    # segment - the one-hour window of the stop fixtures is deliberately tight for stop-to-stop matching.
    body["departure_window_end"] = (bw.base + timedelta(hours=3)).isoformat()
    body.update(overrides)
    return body


def create_point_listing(bw: BW, **overrides):  # noqa: ANN201
    with bw.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw, **overrides))
        )
        s.commit()
        return listing.id


# --------------------------------------------------------------------------------------- the XOR


def test_an_end_is_a_stop_or_a_point_never_both_and_never_neither(bw: BW) -> None:
    both = point_body(bw)
    both["origin_stop_id"] = bw.w.stop_public_ids["A"]
    with pytest.raises(ValueError, match="exactly one"):
        ListingCreate.model_validate(both)

    neither = point_body(bw)
    neither.pop("origin_point")
    with pytest.raises(ValueError, match="exactly one"):
        ListingCreate.model_validate(neither)


def test_the_database_refuses_a_row_that_means_two_things(bw: BW) -> None:
    """The CHECK is the last line: even a direct UPDATE cannot leave a row with a stop *and* a point."""
    listing_id = create_point_listing(bw)
    with bw.db.engine.begin() as conn:
        with pytest.raises(Exception) as info:
            conn.execute(
                text("UPDATE listings SET origin_stop_id = :s WHERE id = :i"),
                {"s": bw.w.stop_ids["A"], "i": listing_id},
            )
    assert "ck_listings_origin_end_one" in str(info.value)


# ------------------------------------------------------------------------------ the route bound


def test_a_place_off_the_road_is_refused(bw: BW) -> None:
    with bw.db.session() as s:
        failure = domain_error(
            lambda: marketplace_service.create_listing(
                s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw, origin=FAR_AWAY))
            )
        )
    assert failure.code is ErrorCode.ROUTE_MISMATCH
    assert failure.details["reason"] == "no_confirmed_route_serves_both_points"


def test_the_radius_is_the_corridors_own_configuration(bw: BW) -> None:
    """Q88 follow-up: 3 km is a pilot default, not a law. A corridor may widen it, and then the same place fits."""
    off_road = (40.20, 67.90)  # ~10 km north of the road: refused at the default radius
    with bw.db.session() as s:
        refused = domain_error(
            lambda: marketplace_service.create_listing(
                s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw, origin=off_road))
            )
        )
    assert refused.code is ErrorCode.ROUTE_MISMATCH

    with bw.db.engine.begin() as conn:
        conn.execute(
            text("UPDATE service_corridors SET max_point_offset_m = 20000 WHERE id = :c"), {"c": bw.w.corridor_id}
        )
    with bw.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw, origin=off_road))
        )
        s.commit()
    assert listing.origin_route_offset_m > 3_000, "the same place, accepted because the corridor says so"


def test_the_pickup_must_come_before_the_dropoff_along_the_road(bw: BW) -> None:
    with bw.db.session() as s:
        failure = domain_error(
            lambda: marketplace_service.create_listing(
                s,
                owner_user_id=bw.w.client_id,
                data=ListingCreate.model_validate(point_body(bw, origin=NEAR_D, destination=NEAR_B)),
            )
        )
    assert failure.code is ErrorCode.ROUTE_MISMATCH


# ----------------------------------------------------------------------------- what gets stored


def test_the_stored_reference_is_a_point_a_district_and_an_offset(bw: BW) -> None:
    listing_id = create_point_listing(bw)
    row = rows(
        bw.db,
        "SELECT origin_stop_id, ST_AsText(origin_point) AS point, origin_address, origin_route_offset_m, "
        "origin_district_id FROM listings WHERE id = :i",
        i=listing_id,
    )[0]
    assert row.origin_stop_id is None
    assert row.point.startswith("POINT(")
    assert row.origin_address == "A ko'chasi 1"
    assert 0 <= row.origin_route_offset_m <= 3_000
    assert row.origin_district_id is not None, "advisory, but always recorded"


def test_the_district_is_advisory_and_no_boundary_is_consulted(bw: BW) -> None:
    """No district in the catalogue has a boundary, so containment is never checked - and must not be.

    The place is accepted because it projects onto the road, not because it sits inside the administrative
    unit the person tapped. If that ever changes it is a product decision, not a silent tightening.
    """
    assert scalar(bw.db, "SELECT count(*) FROM geo_districts WHERE boundary IS NOT NULL") == 0
    listing_id = create_point_listing(bw)
    assert scalar(bw.db, "SELECT origin_district_id FROM listings WHERE id = :i", i=listing_id) is not None


# ------------------------------------------------------------------ proposal, booking, capacity


def full_chain(bw: BW):  # noqa: ANN201
    """A point listing carried all the way to a booking, the way the app does it."""
    with bw.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw))
        )
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(
            s, listing_public_id=public_id, actor_user_id=bw.w.client_id, expected_version=listing.version
        )
        s.commit()
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A777AA")
    window = (bw.base - timedelta(hours=1), bw.base + timedelta(hours=8))
    with bw.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s,
            listing_public_id=public_id,
            actor_user_id=bw.w.driver_id,
            data=ProposalCreate.model_validate(
                {
                    "trip_id": trip_public,
                    "pickup_window_start": window[0].isoformat(),
                    "pickup_window_end": window[1].isoformat(),
                    "quantity": 1,
                    "price_basis": "per_seat",
                    "unit_price_minor": 20_000_000,
                }
            ),
        )
        ref = marketplace_service.current_version(s, thread)
        thread_public = marketplace_service.thread_public_id(thread)
        version_public = marketplace_service.version_public_id(ref)
        s.commit()
    from tests.pg.bookings.conftest import ThreadRef

    booking = accept(bw, ThreadRef(public_id, thread_public, version_public, ref.revision), bw.w.client_id)
    return public_id, booking


def test_a_driver_cannot_move_the_place_the_client_marked(bw: BW) -> None:
    with bw.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw))
        )
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(
            s, listing_public_id=public_id, actor_user_id=bw.w.client_id, expected_version=listing.version
        )
        s.commit()
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A778AA")
    with bw.db.session() as s:
        failure = domain_error(
            lambda: marketplace_service.submit_proposal(
                s,
                listing_public_id=public_id,
                actor_user_id=bw.w.driver_id,
                data=ProposalCreate.model_validate(
                    {
                        "trip_id": trip_public,
                        "pickup_stop_id": bw.w.stop_public_ids["A"],
                        "dropoff_stop_id": bw.w.stop_public_ids["D"],
                        "pickup_window_start": (bw.base - timedelta(hours=1)).isoformat(),
                        "pickup_window_end": (bw.base + timedelta(hours=8)).isoformat(),
                        "quantity": 1,
                        "price_basis": "per_seat",
                        "unit_price_minor": 20_000_000,
                    }
                ),
            )
        )
    assert failure.code is ErrorCode.VALIDATION_ERROR
    assert failure.details["reason"] == "listing_ends_are_points"


def test_the_booking_snapshots_what_was_agreed_and_still_pays_per_segment(bw: BW) -> None:
    _listing, booking = full_chain(bw)
    version = rows(
        bw.db,
        "SELECT ST_AsText(pv.pickup_point) AS point, pv.pickup_address, pv.pickup_route_offset_m, pv.total_minor "
        "FROM proposal_versions pv JOIN bookings b ON b.accepted_proposal_version_id = pv.id WHERE b.id = :i",
        i=booking.id,
    )[0]
    stored = rows(
        bw.db,
        "SELECT ST_AsText(pickup_point) AS point, pickup_address, pickup_route_offset_m, total_minor, "
        "pickup_occurrence_seq, dropoff_occurrence_seq FROM bookings WHERE id = :i",
        i=booking.id,
    )[0]
    assert (stored.point, stored.pickup_address, stored.pickup_route_offset_m) == (
        version.point,
        version.pickup_address,
        version.pickup_route_offset_m,
    ), "the agreed place is copied, not re-derived"
    assert stored.total_minor == version.total_minor, "accept never silently recomputes the money"

    segments = [
        row.segment_from_seq
        for row in rows(
            bw.db,
            "SELECT segment_from_seq FROM booking_allocations WHERE booking_id = :i AND active ORDER BY 1",
            i=booking.id,
        )
    ]
    assert segments == list(range(stored.pickup_occurrence_seq, stored.dropoff_occurrence_seq)), (
        "capacity is still one allocation per route segment (AC12)"
    )


def test_a_marked_place_is_never_called_an_exact_match(bw: BW) -> None:
    """Q88: the person did not pick the driver's stop, so "aniq mos" would be a lie to both sides.

    The feed still has to *find* the listing - a point end that nobody can see is worse than no feature - so
    the match is made through the district's verified stops and capped at ``on_route``.
    """
    from app.contracts.enums import MatchType
    from app.modules.marketplace.feed import service as feed_service

    with bw.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw))
        )
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(
            s, listing_public_id=public_id, actor_user_id=bw.w.client_id, expected_version=listing.version
        )
        s.commit()

    with bw.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, public_id)
        reads = feed_service._Reads(s, bw.base)
        orders = reads.route_orders(listing.corridor_id)
        match = feed_service._point_listing_match(
            reads, listing, orders, frozenset({bw.w.stop_ids["A"]}), frozenset({bw.w.stop_ids["D"]})
        )
    assert match is MatchType.ON_ROUTE, "found, but never sold as an exact match"


# ------------------------------------------------------------------------- the stop path is intact


def test_a_stop_ended_listing_still_works_exactly_as_before(bw: BW) -> None:
    listing_id = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=2))
    row = rows(
        bw.db,
        "SELECT origin_stop_id, origin_point, origin_district_id FROM listings WHERE public_id = "
        "(SELECT public_id FROM listings ORDER BY id DESC LIMIT 1)",
    )[0]
    assert listing_id
    assert row.origin_stop_id is not None
    assert row.origin_point is None and row.origin_district_id is None
