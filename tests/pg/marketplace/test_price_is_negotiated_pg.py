"""The price is the one the two sides agree on, not one the platform computes (Q90, wave 15).

ELCHI is a two-sided auction. The sequence the product is built around is:

    client 300 000 -> driver 350 000 -> client 320 000 -> driver 330 000 -> ACCEPT  =>  booking total 330 000

Every step of that has to be possible, and the number that ends up on the booking has to be the number the two
people said out loud. A corridor band that refused an offer, or any "calculated fare" substituted at accept,
would quietly turn this into a fixed-fare booking - which is the architecture drift this file guards against.

What is asserted:

* an offer outside a configured band is **accepted**, and comes back with a ``PRICE_OUTSIDE_REFERENCE``
  warning rather than a refusal (a warning code is never spelled like an error code, so a client never has
  to guess which register it is in);
* a counteroffer outside the band is equally allowed - the negotiation is never blocked mid-way;
* only a band an admin marked ``enforced`` refuses a price, and it says which band it was;
* a price that is technically invalid (zero, negative) is still refused, band or no band;
* the accepted version's total is what lands on the booking, untouched.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.contracts.errors import ErrorCode, WarningCode
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ProposalCounter, ProposalCreate
from tests.pg.bookings.conftest import (  # noqa: F401  (bw/world are fixtures)
    BW,
    accept,
    bw,
    domain_error,
    driver_trip,
    occurrence_window,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    scalar,
    world,
)

pytestmark = pytest.mark.pg

#: The world's passenger fixtures negotiate around 20 000 000 minor (200 000 so'm) per seat.
FLOOR, CEILING = 15_000_000, 25_000_000
WAY_ABOVE = 40_000_000


def configure_band(bw: BW, *, enforced: bool = False) -> None:
    with bw.db.engine.begin() as conn:
        conn.execute(text("DELETE FROM corridor_price_bands WHERE corridor_id = :c"), {"c": bw.w.corridor_id})
        conn.execute(
            text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, "
                "origin_stop_id, destination_stop_id, floor_minor, ceiling_minor, currency, is_active, "
                "enforced, reason, version, updated_by) VALUES (gen_random_uuid(), :c, 'passenger', "
                "'per_seat', NULL, NULL, :f, :ce, 'UZS', true, :en, 'wave 15 test band', 1, :a)"
            ),
            {"c": bw.w.corridor_id, "f": FLOOR, "ce": CEILING, "en": enforced, "a": bw.w.admin_id},
        )


def open_request(bw: BW) -> tuple[str, str]:
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1, unit=20_000_000))
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A611AA")
    return listing, trip_public


def offer(bw: BW, listing: str, trip_public: str, unit: int, warnings: list | None = None):  # noqa: ANN201
    window = occurrence_window(bw, "A")
    with bw.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s,
            listing_public_id=listing,
            actor_user_id=bw.w.driver_id,
            data=ProposalCreate.model_validate(
                {
                    "trip_id": trip_public,
                    "pickup_stop_id": bw.w.stop_public_ids["A"],
                    "dropoff_stop_id": bw.w.stop_public_ids["D"],
                    "pickup_window_start": window[0].isoformat(),
                    "pickup_window_end": window[1].isoformat(),
                    "quantity": 1,
                    "price_basis": "per_seat",
                    "unit_price_minor": unit,
                }
            ),
            warnings=warnings,
        )
        ref = marketplace_service.current_version(s, thread)
        result = (
            marketplace_service.thread_public_id(thread),
            marketplace_service.version_public_id(ref),
            ref.revision,
            ref.total_minor,
        )
        s.commit()
        return result


def test_an_offer_outside_the_band_is_allowed_and_only_warned_about(bw: BW) -> None:
    configure_band(bw)
    listing, trip_public = open_request(bw)
    warnings: list[dict] = []

    _thread, _version, _revision, total = offer(bw, listing, trip_public, WAY_ABOVE, warnings)

    assert total == WAY_ABOVE, "the driver's own number, not one the platform picked"
    assert [w["code"] for w in warnings] == [WarningCode.PRICE_OUTSIDE_REFERENCE.value], warnings
    assert warnings[0]["details"]["ceiling_minor"] == CEILING, "the warning says what it is comparing against"


def test_a_counteroffer_outside_the_band_is_allowed_too(bw: BW) -> None:
    """The negotiation must not be blocked half way through - that is where a fixed fare creeps back in."""
    configure_band(bw)
    listing, trip_public = open_request(bw)
    thread, _version, revision, _total = offer(bw, listing, trip_public, 22_000_000)

    warnings: list[dict] = []
    with bw.db.session() as s:
        countered = marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread,
            actor_user_id=bw.w.client_id,
            data=ProposalCounter.model_validate({"expected_revision": revision, "unit_price_minor": WAY_ABOVE}),
            warnings=warnings,
        )
        current = marketplace_service.current_version(s, countered)
        total = current.total_minor
        s.commit()

    assert total == WAY_ABOVE
    assert [w["code"] for w in warnings] == [WarningCode.PRICE_OUTSIDE_REFERENCE.value]


def test_only_an_enforced_band_refuses(bw: BW) -> None:
    """An admin-imposed abuse/safety limit is the one case that still says no (Q90)."""
    configure_band(bw, enforced=True)
    listing, trip_public = open_request(bw)

    failure = domain_error(lambda: offer(bw, listing, trip_public, WAY_ABOVE))
    assert failure.code is ErrorCode.PRICE_OUT_OF_BAND
    assert failure.details["ceiling_minor"] == CEILING


def test_a_technically_invalid_price_is_still_refused(bw: BW) -> None:
    """Q90 softens the band, not arithmetic: zero and negative are not prices."""
    configure_band(bw)
    listing, trip_public = open_request(bw)
    for bad in (0, -1):
        with pytest.raises(ValueError):
            offer(bw, listing, trip_public, bad)


def test_the_agreed_number_is_the_one_that_lands_on_the_booking(bw: BW) -> None:
    """300 000 -> 350 000 -> 320 000 -> 330 000 -> accept, and the booking says 330 000."""
    configure_band(bw)
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1, unit=30_000_000))
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A612AA")

    thread, _version, revision, _total = offer(bw, listing, trip_public, 35_000_000)
    with bw.db.session() as s:
        countered = marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread,
            actor_user_id=bw.w.client_id,
            data=ProposalCounter.model_validate({"expected_revision": revision, "unit_price_minor": 32_000_000}),
        )
        revision = marketplace_service.current_version(s, countered).revision
        s.commit()
    with bw.db.session() as s:
        final = marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread,
            actor_user_id=bw.w.driver_id,
            data=ProposalCounter.model_validate({"expected_revision": revision, "unit_price_minor": 33_000_000}),
        )
        version = marketplace_service.current_version(s, final)
        version_public = marketplace_service.version_public_id(version)
        revision = version.revision
        s.commit()

    from tests.pg.bookings.conftest import ThreadRef

    booking = accept(bw, ThreadRef(listing, thread, version_public, revision), bw.w.client_id)
    stored = rows(bw.db, "SELECT total_minor, unit_price_minor FROM bookings WHERE id = :i", i=booking.id)[0]
    assert stored.unit_price_minor == 33_000_000
    assert stored.total_minor == 33_000_000, "the platform never substitutes its own number"
