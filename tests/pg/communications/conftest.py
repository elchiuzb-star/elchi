"""PostgreSQL fixtures for A7 communications tests, built on A4's ``bw`` world (real A1/A2/A3/A4 services)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.modules.communications.models  # noqa: F401  (registers the communications tables)
from app.contracts.dto import ChatMessageCreate
from app.contracts.enums import EventType, QuickReplyCode
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.timeutil import utc_now
from app.db.session import get_db
from app.modules.bookings import service as bookings_service
from app.modules.communications import dispatch as dispatch_registry
from app.modules.communications import service as comms
from app.modules.communications.providers import set_push_provider
from app.modules.identity import service as identity_service
from app.modules.platform.service import enqueue_event
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
)
from tests.pg.conftest import PgDatabase
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

FAKE_CONSUMERS = "tests.pg.communications.fake_consumers"


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    from tests.pg.communications import fake_consumers

    dispatch_registry.reset_registry()
    set_push_provider(None)
    fake_consumers.STATE.update({"fail": False, "relevant": True})
    yield
    dispatch_registry.reset_registry()
    set_push_provider(None)


@pytest.fixture
def fake_consumers(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from tests.pg.communications import fake_consumers as module

    monkeypatch.setattr(dispatch_registry, "CONSUMER_MODULES", (FAKE_CONSUMERS, "app.modules.not_delivered_yet.consumers"))
    dispatch_registry.reset_registry()
    return module


@dataclass(frozen=True)
class Deal:
    listing_id: str
    trip_id: int
    ref: ThreadRef
    booking_id: int
    booking_public_id: str


def accepted_deal(bw: BW, **kwargs: object) -> Deal:
    listing, trip_id, _trip_public, ref = request_with_driver_proposal(bw, **kwargs)
    booking = accept(bw, ref, kwargs.get("client_id") or bw.w.client_id)
    return Deal(listing, trip_id, ref, booking.id, bookings_service.booking_public_id(booking))


def open_thread(bw: BW) -> ThreadRef:
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw)
    return ref


def post(
    db: PgDatabase, kind: str, parent: str, actor: int, *, text: str | None = None, quick: QuickReplyCode | None = None,
    now: datetime | None = None, attachment: str | None = None,
) -> tuple[comms.PostedMessage, list[dict]]:
    warnings: list[dict] = []
    with db.session() as s:
        posted = comms.post_message(
            s, kind=kind, parent_public_id=parent, actor_user_id=actor,
            data=ChatMessageCreate(text=text, quick_reply_code=quick, attachment_file_id=attachment), now=now, warnings=warnings,
        )
        s.commit()
        return posted, warnings


def domain_error(fn) -> DomainError:  # noqa: ANN001
    with pytest.raises(DomainError) as info:
        fn()
    return info.value


def dispatch_all(db: PgDatabase, *, now: datetime | None = None, limit: int = 100) -> int:
    total = 0
    for _ in range(100):
        with db.session() as s:
            handled = comms.dispatch_outbox(s, now=now, limit=limit)
            s.commit()
        total += handled
        if handled == 0:
            break
    return total


def enqueue_user_event(db: PgDatabase, user_id: int, *, signal: str = "contact_sharing") -> uuid.UUID:
    with db.session() as s:
        public_id = identity_service.user_public_id(s, user_id)
        row = enqueue_event(
            s,
            EventEnvelope(EventType.TRUST_WARNING_ISSUED, "user", public_id, 1, utc_now(),
                          {"review_id": f"trv_{uuid.uuid4().hex[:8]}", "signal_type": signal}),
            aggregate_id=user_id,
        )
        event_id = row.event_id
        s.commit()
    return event_id


@pytest.fixture
def comms_client(bw: BW) -> Iterator[TestClient]:
    from sqlalchemy.exc import DBAPIError

    from app.api.v2.web import db_error_handler, domain_error_handler
    from app.modules.bookings.api import router as bookings_router
    from app.modules.communications.api import router as communications_router
    from app.modules.marketplace.api import router as marketplace_router

    app = FastAPI()
    for router in (marketplace_router, bookings_router, communications_router):
        app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    async def server_error(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": ErrorCode.SERVER_ERROR.value, "message": "server error"}})

    app.add_exception_handler(Exception, server_error)

    def override_db() -> Iterator[Session]:
        session = bw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
