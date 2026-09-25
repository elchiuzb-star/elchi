"""Real booking lifecycles for stage-3 qualification tests (referral stage 3, ADR-0023).

Everything here goes through the owning services - ``accept_proposal`` (real commission hold), participant actions
with real proof codes, ``report_cash_receipt`` / ``acknowledge_cash_receipt`` and the finance ``finalize_fee``
(real ``commission_capture`` ledger posting). What is *not* real yet is the promotions hook inside that flow
(stage 4): tests call ``qualification.process_enrollment`` / the jobs themselves. SYNTHETIC people and amounts.
"""

from __future__ import annotations

from tests.pg.marketplace.catalog_world import synthetic_category

import itertools
import uuid
from datetime import timedelta

from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.promo import normalize_phone
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.marketplace.schemas import ListingCreate
from tests.pg.bookings.conftest import (
    BW,
    accept,
    act,
    booking_version,
    codes_for,
    driver_trip,
    operator,
    passenger_request_body,
    propose,
    publish_listing,
    run_trip_action,
)

_plates = itertools.count(100)


def plate() -> str:
    return f"01P{next(_plates):03d}PR"


def report_and_acknowledge_cash(bw: BW, booking_id: int, driver_id: int, client_id: int, *, at) -> None:  # noqa: ANN001
    with bw.db.session() as s:
        booking = s.get(Booking, booking_id)
        public = bookings_service.booking_public_id(booking)
        _, receipt = bookings_service.report_cash_receipt(
            s, booking_public_id_value=public, actor_user_id=driver_id, expected_version=booking.version,
            amount_minor=booking.total_minor, reported_at=at, now=at)
        s.commit()
        receipt_public = format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id)
    with bw.db.session() as s:
        bookings_service.acknowledge_cash_receipt(
            s, booking_public_id_value=public, receipt_public_id=receipt_public, actor_user_id=client_id,
            expected_version=receipt.version, now=at)
        s.commit()


def finalize_capture(bw: BW, booking_id: int) -> None:
    operator(bw, booking_id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="synthetic test capture")


def passenger_trip(bw: BW, driver_id: int, *, seats: int = 4) -> tuple[int, str]:
    return driver_trip(bw, driver_id, plate(), seats=seats)


def accepted_passenger(bw: BW, client_id: int, trip: tuple[int, str], driver_id: int, *, unit: int = 20_000_000) -> int:
    listing = publish_listing(bw, client_id, passenger_request_body(bw, seats=1, unit=unit))
    ref = propose(bw, listing, driver_id, trip_public_id=trip[1], quantity=1, unit=unit)
    return accept(bw, ref, client_id).id


def complete_passengers(bw: BW, trip_id: int, driver_id: int, bookings: list[tuple[int, int]], *,
                        cash_after: timedelta = timedelta(hours=3, minutes=5), capture: bool = True) -> None:
    """``bookings``: (booking_id, client_id). Board, pay cash, drop off, complete, capture - all on one trip."""
    run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    for booking_id, client_id in bookings:
        code = codes_for(bw, booking_id, client_id)["boarding_code"]
        act(bw, booking_id, driver_id, "board", code=code, now=bw.base + timedelta(minutes=5))
    run_trip_action(bw, trip_id, driver_id, "depart", now=bw.base + timedelta(minutes=12))
    for booking_id, client_id in bookings:
        report_and_acknowledge_cash(bw, booking_id, driver_id, client_id, at=bw.base + cash_after)
        act(bw, booking_id, driver_id, "drop_off", now=bw.base + timedelta(hours=3))
        act(bw, booking_id, client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
        if capture:
            finalize_capture(bw, booking_id)
    run_trip_action(bw, trip_id, driver_id, "complete", now=bw.base + timedelta(hours=4))  # frees the driver's time slot


def completed_passenger(bw: BW, client_id: int, driver_id: int | None = None, **kw) -> int:  # noqa: ANN003
    driver_id = driver_id or bw.w.driver_id
    trip = passenger_trip(bw, driver_id)
    booking_id = accepted_passenger(bw, client_id, trip, driver_id)
    complete_passengers(bw, trip[0], driver_id, [(booking_id, client_id)], **kw)
    return booking_id


def parcel_body(bw: BW, *, receiver_phone: str, unit: int, destination: str = "C") -> ListingCreate:
    start = bw.base
    return ListingCreate.model_validate({
        "kind": "request", "service_type": "parcel",
        "origin_stop_id": bw.w.stop_public_ids["A"], "destination_stop_id": bw.w.stop_public_ids[destination],
        "departure_window_start": start.isoformat(), "departure_window_end": (start + timedelta(hours=2)).isoformat(),
        "price_basis": "total", "unit_price_minor": unit,
        "parcel": {"parcel_type": "documents", "category_id": synthetic_category(bw.db),
                   "fragile": False, "payer": "sender", "sender": {"name": "Synthetic Sender", "phone": "+998900000299"},
                   "receiver": {"name": "Synthetic Receiver", "phone": receiver_phone}},
    })


def completed_parcels_on_one_trip(bw: BW, sender_id: int, receivers: list[str], *, destination: str = "C") -> list[int]:
    """Real parcel bookings of one sender on one trip, finished the only way left (ADR-0026, Q139/Q143): the trip
    departs (in transit), staff record ``mark_delivered`` and ``complete_with_evidence``, finance captures. No codes,
    no in-app cash - so there is no handover/delivery proof and no confirmed cash either."""
    driver_id = bw.w.driver_id
    trip_id, trip_public = driver_trip(bw, driver_id, plate())
    booking_ids = []
    for index, receiver in enumerate(receivers):
        listing = publish_listing(bw, sender_id, parcel_body(bw, receiver_phone=receiver, unit=7_000_000 + index * 10_000,
                                                             destination=destination))
        ref = propose(bw, listing, driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000 + index * 10_000,
                      dropoff=destination, price_basis="total")
        booking_ids.append(accept(bw, ref, sender_id).id)
    run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    run_trip_action(bw, trip_id, driver_id, "depart", now=bw.base + timedelta(minutes=12))
    for booking_id in booking_ids:
        operator(bw, booking_id, bw.operator_id, "mark_delivered", now=bw.base + timedelta(hours=2), reason="synthetic delivery")
        operator(bw, booking_id, bw.operator_id, "complete_with_evidence", now=bw.base + timedelta(hours=2, minutes=10),
                 reason="synthetic completion")
        finalize_capture(bw, booking_id)
    run_trip_action(bw, trip_id, driver_id, "complete", now=bw.base + timedelta(hours=4))
    return booking_ids


def new_receiver() -> str:
    phone = f"+99897{uuid.uuid4().int % 10_000_000:07d}"
    assert normalize_phone(phone) == phone
    return phone


__all__ = ["booking_version"]
