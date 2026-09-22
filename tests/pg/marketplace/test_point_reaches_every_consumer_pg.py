"""A map-point listing has to reach **every** consumer, not just the one it was written for (Q88, wave 15).

Wave 14 proved a point listing can be created, published, proposed on and accepted. What it did not check was
whether the rest of the marketplace can *see* it, and four places could not:

* ``counter_proposal`` looked the version's stop ids up in the catalogue and crashed on ``None`` - so the
  counteroffer, the half that makes this an auction rather than a price list, was impossible on every
  point listing the client app creates;
* ``list_listing_offers`` (Q40) read the corridor off the same absent stops and answered 404;
* ``listing_matches`` (M2) passed ``(None,)`` as the end ids, which matches nothing and reports "no matches";
* a saved search compared the absent stop pair and therefore never fired.

None of those raised anything a test would notice - three of them simply returned "nothing". That is the
marketplace loop breaking silently, which is why each one gets an explicit test here.

The fifth case is the price *reference*: a point listing has no stop pair, so no segment band applies, and it
used to fall through to a neutral score. The corridor-wide band describes the whole direction and is the right
answer - as a reference for ranking and an advisory warning, never as a fare (Q90).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.contracts.enums import FeedSide, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.feed import service as feed_service
from app.modules.marketplace.feed.schemas import SavedSearchCreate
from app.modules.marketplace.schemas import ListingCreate, ProposalCounter, ProposalCreate
from tests.pg.bookings.conftest import (  # noqa: F401  (bw/world are fixtures)
    BW,
    bw,
    domain_error,
    driver_trip,
    occurrence_window,
    publish_listing,
    world,
)
from tests.pg.identity.a1_world import passenger_offer
from tests.pg.marketplace.test_point_endpoints_pg import point_body

pytestmark = pytest.mark.pg


def publish_point_request(bw: BW) -> str:
    """A published passenger request whose two ends are places on the map, as the client app sends them."""
    with bw.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=ListingCreate.model_validate(point_body(bw))
        )
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(
            s, listing_public_id=public_id, actor_user_id=bw.w.client_id, expected_version=listing.version
        )
        s.commit()
        return public_id


def driver_offers_on(bw: BW, listing_public_id: str, plate: str, *, unit: int = 20_000_000):  # noqa: ANN201
    """The driver's first offer on a point listing: no stops are sent, the places are inherited."""
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, plate)
    window = (bw.base - timedelta(hours=1), bw.base + timedelta(hours=8))
    with bw.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s,
            listing_public_id=listing_public_id,
            actor_user_id=bw.w.driver_id,
            data=ProposalCreate.model_validate(
                {
                    "trip_id": trip_public,
                    "pickup_window_start": window[0].isoformat(),
                    "pickup_window_end": window[1].isoformat(),
                    "quantity": 1,
                    "price_basis": "per_seat",
                    "unit_price_minor": unit,
                }
            ),
        )
        thread_public = marketplace_service.thread_public_id(thread)
        revision = marketplace_service.current_version(s, thread).revision
        s.commit()
        return thread_public, revision


# ----------------------------------------------------------------- the counteroffer (the P0 of this wave)


def test_the_client_can_counter_a_driver_offer_on_a_point_listing(bw: BW) -> None:
    """`300k -> 350k -> 320k -> ...` has to be possible on the listings the app actually publishes.

    Before the fix this raised a ``KeyError`` looking up stop ``None``: a 500, on the main client flow.
    """
    listing = publish_point_request(bw)
    thread, revision = driver_offers_on(bw, listing, "01P100AA", unit=35_000_000)

    with bw.db.session() as s:
        thread_row = marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread,
            actor_user_id=bw.w.client_id,
            data=ProposalCounter(expected_revision=revision, unit_price_minor=32_000_000),
        )
        version = marketplace_service.current_version(s, thread_row)
        s.commit()
        assert version.unit_price_minor == 32_000_000, "the counter's price is the one that stands"
        assert version.revision == revision + 1
        assert version.pickup_stop_id is None and version.dropoff_stop_id is None, "still point-ended"
        assert version.pickup_point is not None, "the client's marked place travelled onto the new version"


def test_a_counter_cannot_move_the_place_the_client_marked(bw: BW) -> None:
    """Q88: the ends belong to the listing. A counter negotiates price and time, not where someone lives."""
    listing = publish_point_request(bw)
    thread, revision = driver_offers_on(bw, listing, "01P101AA")

    with bw.db.session() as s:
        failure = domain_error(
            lambda: marketplace_service.counter_proposal(
                s,
                thread_public_id_value=thread,
                actor_user_id=bw.w.client_id,
                data=ProposalCounter.model_validate(
                    {"expected_revision": revision, "pickup_stop_id": bw.w.stop_public_ids["A"]}
                ),
            )
        )
    assert failure.code is ErrorCode.VALIDATION_ERROR
    assert failure.details["reason"] == "listing_ends_are_points"


# ----------------------------------------------------------------- Q40: the competing-offer list


def test_the_competing_offers_list_answers_for_a_point_listing(bw: BW) -> None:
    """R1/Q40 was closed with a 404 on exactly the listings the client app creates."""
    listing = publish_point_request(bw)
    driver_offers_on(bw, listing, "01P102AA", unit=21_000_000)

    with bw.db.session() as s:
        offers = marketplace_service.list_listing_offers(
            s, listing_public_id=listing, viewer_user_id=bw.w.driver_id
        )
    assert len(offers) == 1, "the driver sees the competing offer instead of a 404"
    assert offers[0].version.unit_price_minor == 21_000_000


# ----------------------------------------------------------------- M2: matches, both directions


def test_the_owner_of_a_point_request_is_shown_matching_trip_offers(bw: BW) -> None:
    listing = publish_point_request(bw)
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P103AA")
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    assert offer

    with bw.db.session() as s:
        page = feed_service.listing_matches(
            s, listing_public_id=listing, viewer_user_id=bw.w.client_id, now=bw.base
        )
    assert page.items, "a point-ended request used to report 'no matches' for every trip offer there was"


def test_a_driver_sees_a_point_request_among_the_matches_for_their_trip_offer(bw: BW) -> None:
    point_listing = publish_point_request(bw)
    assert point_listing
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P104AA")
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))

    with bw.db.session() as s:
        page = feed_service.listing_matches(
            s, listing_public_id=offer, viewer_user_id=bw.w.driver_id, now=bw.base
        )
    ids = {marketplace_service.listing_public_id(item.listing) for item in page.items}
    assert point_listing in ids, "the driver whose trip can serve the place could not see the request"


# ----------------------------------------------------------------- saved searches


def test_a_saved_search_fires_for_a_point_listing(bw: BW) -> None:
    """A search saved on the districts a point sits in has to notice that point being published."""
    with bw.db.session() as s:
        feed_service.create_saved_search(
            s,
            user_id=bw.w.driver_id,
            data=SavedSearchCreate.model_validate(
                {
                    "service_type": ServiceType.PASSENGER.value,
                    "side": FeedSide.REQUESTS.value,
                    "origin_stop_id": bw.w.stop_public_ids["A"],
                    "destination_stop_id": bw.w.stop_public_ids["D"],
                    "time_window_start": (bw.base - timedelta(hours=2)).isoformat(),
                    "time_window_end": (bw.base + timedelta(hours=8)).isoformat(),
                    "quantity": 1,
                }
            ),
            now=bw.base,
        )
        s.commit()

    listing = publish_point_request(bw)
    with bw.db.session() as s:
        listing_id = marketplace_service.resolve_listing_id(s, listing)
    with bw.db.session() as s:
        matched = feed_service.match_saved_searches_for_listing(s, listing_id, now=bw.base)
        s.commit()
    assert matched == 1, "the saved search never fired for a point listing before"


# ----------------------------------------------------------------- Q42 as a reference, not a fare


def test_a_point_listing_resolves_the_corridor_reference_not_nothing(bw: BW) -> None:
    """Q42/Q88: no stop pair means no *segment* band - the corridor-wide one still describes the direction."""
    from app.modules.geo.service import resolve_price_band

    with bw.db.session() as s:
        s.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, floor_minor, "
                "ceiling_minor, reason, updated_by) VALUES (gen_random_uuid(), :c, 'passenger', 'per_seat', "
                "15000000, 25000000, 'reference', :a)"
            ),
            {"c": bw.w.corridor_id, "a": bw.w.admin_id},
        )
        s.commit()

    with bw.db.session() as s:
        band = resolve_price_band(
            s,
            corridor_id=bw.w.corridor_id,
            service_type=ServiceType.PASSENGER,
            origin_stop_id=None,
            destination_stop_id=None,
        )
    assert band is not None and band.scope == "corridor"
    assert band.enforced is False, "a reference advises; it is not a fare (Q90)"


def test_an_out_of_reference_price_is_accepted_with_a_warning_on_a_point_listing(bw: BW) -> None:
    """The whole point of Q90, exercised on the listing kind the client app publishes."""
    from sqlalchemy import text

    with bw.db.session() as s:
        s.execute(
            text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, floor_minor, "
                "ceiling_minor, reason, updated_by) VALUES (gen_random_uuid(), :c, 'passenger', 'per_seat', "
                "15000000, 25000000, 'reference', :a)"
            ),
            {"c": bw.w.corridor_id, "a": bw.w.admin_id},
        )
        s.commit()

    listing = publish_point_request(bw)
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P105AA")
    window = (bw.base - timedelta(hours=1), bw.base + timedelta(hours=8))
    warnings: list[dict] = []
    with bw.db.session() as s:
        marketplace_service.submit_proposal(
            s,
            listing_public_id=listing,
            actor_user_id=bw.w.driver_id,
            data=ProposalCreate.model_validate(
                {
                    "trip_id": trip_public,
                    "pickup_window_start": window[0].isoformat(),
                    "pickup_window_end": window[1].isoformat(),
                    "quantity": 1,
                    "price_basis": "per_seat",
                    "unit_price_minor": 40_000_000,  # far above the reference
                }
            ),
            warnings=warnings,
        )
        s.commit()

    codes = {warning["code"] for warning in warnings}
    assert "PRICE_OUTSIDE_REFERENCE" in codes, "the reference has something to say"
    assert "PRICE_OUT_OF_BAND" not in codes, "but it does not refuse - that spelling is the enforced error"


def test_an_enforced_reference_still_refuses_on_a_point_listing(bw: BW) -> None:
    """The one hard limit Q90 keeps, reachable on point listings too."""
    from sqlalchemy import text

    with bw.db.session() as s:
        s.execute(
            text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, floor_minor, "
                "ceiling_minor, enforced, reason, updated_by) VALUES (gen_random_uuid(), :c, 'passenger', "
                "'per_seat', 15000000, 25000000, true, 'abuse limit', :a)"
            ),
            {"c": bw.w.corridor_id, "a": bw.w.admin_id},
        )
        s.commit()

    listing = publish_point_request(bw)
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01P106AA")
    window = (bw.base - timedelta(hours=1), bw.base + timedelta(hours=8))
    with bw.db.session() as s:
        failure = domain_error(
            lambda: marketplace_service.submit_proposal(
                s,
                listing_public_id=listing,
                actor_user_id=bw.w.driver_id,
                data=ProposalCreate.model_validate(
                    {
                        "trip_id": trip_public,
                        "pickup_window_start": window[0].isoformat(),
                        "pickup_window_end": window[1].isoformat(),
                        "quantity": 1,
                        "price_basis": "per_seat",
                        "unit_price_minor": 40_000_000,
                    }
                ),
            )
        )
    assert isinstance(failure, DomainError) and failure.code is ErrorCode.PRICE_OUT_OF_BAND
    assert failure.details["scope"] == "corridor"
