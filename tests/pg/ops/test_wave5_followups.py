"""Wave 5 integrator: the wave 4 follow-ups that were backend gaps, on real PostgreSQL.

1. ``BookingDTO.contact.chat_thread_id`` (wave 4d follow-up): A7's read-only lookup is registered in A4 through
   ``communications.service.register_booking_hooks()``. Before any message the field stays ``null`` - opening a
   booking must not create a thread - and once the participants have written, the booking carries the thread id,
   so a client no longer has to guess whether a chat exists.

2. ``booking.amendment_requested`` (wave 4d follow-up): the counter-party used to learn about an open amendment
   only by opening the booking. The command now enqueues the existing outbox event, with the audience rules of
   N2/Q16 (no commission field in the client copy).
"""

from __future__ import annotations

import uuid

import pytest

from app.contracts.enums import EventType
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.communications import service as comms
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    ThreadRef,
    accept,
    auth,
    bw,
    driver_trip,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    scalar,
    view,
)
from tests.pg.conftest import PgDatabase
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
def _wire_chat_lookup() -> None:
    """The integrator wires this at start-up (``configure_v2_ports``); tests/conftest.py clears it afterwards."""
    comms.register_booking_hooks()


def _accepted_booking(bw: BW) -> int:  # noqa: F811
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw)
    booking = accept(bw, ref, bw.w.client_id)
    return booking.id


def test_chat_thread_id_is_null_until_the_first_message_and_then_points_at_the_thread(bw: BW) -> None:  # noqa: F811
    booking_id = _accepted_booking(bw)
    assert view(bw, booking_id, "client")["contact"]["chat_thread_id"] is None

    from app.contracts.dto import ChatMessageCreate
    from app.contracts.ids import PublicIdPrefix, format_public_id

    with bw.db.session() as session:
        parent = bookings_service.booking_public_id(session.get(Booking, booking_id))
        comms.post_message(
            session, kind="booking", parent_public_id=parent, actor_user_id=bw.w.client_id,
            data=ChatMessageCreate(text="Assalomu alaykum, qayerdasiz?"), warnings=[],
        )
        session.commit()

    thread_uuid = scalar(bw.db, "SELECT public_id FROM chat_threads WHERE booking_id = :b", b=booking_id)
    expected = format_public_id(PublicIdPrefix.CHAT_THREAD, uuid.UUID(str(thread_uuid)))
    for role in ("client", "driver"):
        assert view(bw, booking_id, role)["contact"]["chat_thread_id"] == expected


def test_chat_thread_id_stays_null_when_communications_is_not_wired(bw: BW) -> None:  # noqa: F811
    booking_id = _accepted_booking(bw)
    bookings_service.set_chat_thread_lookup(None)
    assert view(bw, booking_id, "client")["contact"]["chat_thread_id"] is None


def test_amendment_request_notifies_the_counter_party(bw: BW) -> None:  # noqa: F811
    """Wave 4d gap: an open amendment raised no event, so the other side only saw it by chance."""
    booking_id = _accepted_booking(bw)
    before = len(rows(bw.db, "SELECT id FROM outbox_events WHERE event_type = :t", t=EventType.BOOKING_AMENDMENT_REQUESTED.value))

    with bw.db.session() as session:
        booking = session.get(Booking, booking_id)
        bookings_service.create_amendment(
            session, booking_public_id_value=bookings_service.booking_public_id(booking),
            actor_user_id=bw.w.driver_id, expected_version=booking.version,
            changes={"unit_price_minor": booking.unit_price_minor + 1_000_000},
            reason="yo'l narxi oshdi",
        )
        session.commit()

    events = rows(
        bw.db,
        "SELECT payload FROM outbox_events WHERE event_type = :t ORDER BY id",
        t=EventType.BOOKING_AMENDMENT_REQUESTED.value,
    )
    assert len(events) == before + 1
    payload = events[-1][0]
    assert payload["amendment_id"].startswith("amd_")
    assert payload["new_quantity"] >= 1
    # Q16: the amendment event says what changed, never the commission.
    assert "commission_minor" not in payload and "fee_delta_minor" not in payload
