"""A12 PostgreSQL fixtures: A4's booking world (``bw``) plus trust helpers. Hooks are registered per test and
always unregistered in teardown, so other suites keep the Q74 fallback."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.contracts.communications import DispatchedEvent
from app.contracts.enums import EventType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.db.session import get_db
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.trust_support import service as trust_service
from tests.pg.bookings.conftest import (  # noqa: F401  (fixtures bw, world)
    BW,
    accept,
    act,
    bw,
    codes_for,
    request_with_driver_proposal,
    rows,
    run_trip_action,
    scalar,
    world,
)


@pytest.fixture
def hooks() -> Iterator[None]:
    trust_service.register_booking_hooks()
    trust_service.register_booking_hooks()  # idempotent
    try:
        yield
    finally:
        bookings_service.set_blocking_dispute_probe(None)
        bookings_service.set_payment_dispute_opener(None)


def boarding_passenger(bw: BW, plate: str, *, client_id: int | None = None, driver_id: int | None = None):  # noqa: ANN201
    client_id, driver_id = client_id or bw.w.client_id, driver_id or bw.w.driver_id
    listing, trip_id, trip_public, ref = request_with_driver_proposal(bw, plate=plate, client_id=client_id, driver_id=driver_id)
    booking = accept(bw, ref, client_id)
    assert run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30)) == "boarding"
    return trip_id, booking


def arrived_passenger(bw: BW, plate: str, *, client_id: int | None = None, driver_id: int | None = None) -> Booking:
    client_id, driver_id = client_id or bw.w.client_id, driver_id or bw.w.driver_id
    _, booking = boarding_passenger(bw, plate, client_id=client_id, driver_id=driver_id)
    act(bw, booking.id, driver_id, "board", code=codes_for(bw, booking.id, client_id)["boarding_code"], now=bw.base + timedelta(minutes=5))
    act(bw, booking.id, driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    return booking


COMPLETE_AT_OFFSET = timedelta(hours=3, minutes=10)


def complete(bw: BW, booking: Booking, client_id: int | None = None) -> Booking:
    return act(bw, booking.id, client_id or bw.w.client_id, "complete", now=bw.base + COMPLETE_AT_OFFSET)


def captures(bw: BW) -> int:
    return int(scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE reference_kind = 'commission_capture'"))


def open_dispute(bw: BW, booking_id: int, actor_id: int, dispute_type: str = "service", *, session: Session | None = None,
                 description: str = "Haydovchi kelishilgan bekatga kelmadi", warnings: list | None = None):  # noqa: ANN201
    own = session is None
    s = session or bw.db.session()
    try:
        booking = s.get(Booking, booking_id)
        dispute = trust_service.open_dispute(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=actor_id,
            dispute_type=dispute_type, description=description, warnings=warnings,
        )
        public = trust_service.dispute_public_id(dispute)
        s.commit()
        return public
    except BaseException:
        s.rollback()
        raise
    finally:
        if own:
            s.close()


def dispute_command(bw: BW, dispute_public: str, actor_id: int, command: str, **kwargs):  # noqa: ANN003, ANN201
    with bw.db.session() as s:
        version = kwargs.pop("expected_version", None)
        if version is None:
            version = trust_service.get_dispute_for_viewer(s, dispute_public, actor_id)[0].version
        result = trust_service.dispute_command(s, dispute_public_id_value=dispute_public, actor_user_id=actor_id, command=command,
                                               expected_version=version, **kwargs)
        s.commit()
        return result


def domain_error(fn) -> DomainError:  # noqa: ANN001
    with pytest.raises(DomainError) as info:
        fn()
    return info.value


def user_public(bw: BW, user_id: int) -> str:
    return format_public_id(PublicIdPrefix.USER, scalar(bw.db, "SELECT public_id FROM users WHERE id = :u", u=user_id))


def hit_event(bw: BW, user_id: int, occurred_at: datetime, *, event_id: uuid.UUID | None = None,
              categories: tuple[str, ...] = ("phone",)) -> DispatchedEvent:
    return DispatchedEvent(
        event_id=event_id or uuid.uuid4(), event_type=EventType.CONTACT_FILTER_HIT, aggregate_type="user",
        aggregate_public_id=user_public(bw, user_id), aggregate_id=user_id, aggregate_version=1, occurred_at=occurred_at,
        payload={"actor_id": user_public(bw, user_id), "subject_type": "chat_message", "field": "text",
                 "categories": list(categories), "match_count": 1, "filter_version": "test"},
    )


def consume(bw: BW, consumer_fn, event: DispatchedEvent) -> None:  # noqa: ANN001
    with bw.db.session() as s:
        consumer_fn(s, event)
        s.commit()


@pytest.fixture
def trust_client(bw: BW) -> Iterator[TestClient]:
    from sqlalchemy.exc import DBAPIError

    from app.api.v2.web import db_error_handler, domain_error_handler
    from app.modules.trust_support.api import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    async def server_error(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": ErrorCode.SERVER_ERROR.value, "message": str(exc)}})

    app.add_exception_handler(Exception, server_error)

    def override_db() -> Iterator[Session]:
        session = bw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
