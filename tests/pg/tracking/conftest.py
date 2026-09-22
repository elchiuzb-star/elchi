"""PostgreSQL fixtures for A6 tracking tests, built on A4's booking world (``bw``) with the real A1-A4 services.

* ``tw`` - ``bw`` + country ``tracking_enabled`` flag on.
* builders: running passenger/parcel trips with a booking, sessions and point batches through the tracking service
  (``now`` is passed explicitly: the world's trips start two days ahead).
* ``client`` - test-local FastAPI app with the tracking router (the integrator mounts it under /api/v2).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.dto import PointsBatchAck, PointsBatchIn, TrackingPointIn
from app.contracts.errors import DomainError, ErrorCode
from app.db.session import get_db
from app.modules.bookings.models import Booking
from app.modules.tracking import models as tracking_models  # noqa: F401  (registers tracking tables)
from app.modules.tracking import service as tracking_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared fixtures and helpers)
    BW,
    accept,
    act,
    auth,
    bw,
    codes_for,
    domain_error,
    enable_flags,
    parcel_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    run_trip_action,
    scalar,
    set_flag,
    world,
)

LAT, LNG = 41.30, 69.24


@pytest.fixture
def tw(bw: BW) -> BW:
    enable_flags(bw.db, bw.w.admin_id, ("tracking_enabled",))
    return bw


def point(seq: int, at: datetime, *, lat: float = LAT, lng: float = LNG, acc: int = 10, mock: bool = False) -> TrackingPointIn:
    return TrackingPointIn(seq=seq, captured_at=at, lat=lat, lng=lng, accuracy_m=acc, is_mock=mock, battery_pct=80)


def passenger_booking(bw: BW, plate: str, *, boarding: bool = True, client_id: int | None = None,
                      driver_id: int | None = None) -> tuple[int, str, Booking]:
    driver_id = driver_id or bw.w.driver_id
    _, trip_id, trip_public, ref = request_with_driver_proposal(bw, plate=plate, client_id=client_id, driver_id=driver_id)
    booking = accept(bw, ref, client_id or bw.w.client_id)
    if boarding:
        run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    return trip_id, trip_public, booking


def parcel_booking(bw: BW, plate: str) -> tuple[int, str, Booking]:
    from tests.pg.bookings.conftest import driver_trip

    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, plate)
    ref = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000, dropoff="C", price_basis="total")
    booking = accept(bw, ref, bw.w.client_id)
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    return trip_id, trip_public, booking


def start_session(bw: BW, trip_public: str, *, driver_id: int | None = None, now: datetime | None = None, device: str = "dev-1") -> str:
    with bw.db.session() as s:
        row = tracking_service.create_session(
            s, actor_user_id=driver_id or bw.w.driver_id, trip_public_id=trip_public, device_id=device, platform="android",
            app_version="2.0.0", now=now or bw.base - timedelta(minutes=20),
        )
        public = tracking_service.session_public_id(row)
        s.commit()
        return public


def send(bw: BW, session_public: str, points: list[TrackingPointIn], *, now: datetime, driver_id: int | None = None) -> PointsBatchAck:
    with bw.db.session() as s:
        try:
            ack = tracking_service.ingest_points(
                s, actor_user_id=driver_id or bw.w.driver_id, session_public_id_value=session_public,
                batch=PointsBatchIn.model_construct(points=points), now=now,
            )
            s.commit()
            return ack
        except BaseException:
            s.rollback()
            raise


def db_constraint(exc: DBAPIError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


@pytest.fixture
def client(tw: BW) -> Iterator[TestClient]:
    from app.api.v2.web import db_error_handler, domain_error_handler
    from app.modules.tracking.api import router
    from app.modules.tracking.ws import get_session_factory

    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    async def server_error(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": ErrorCode.SERVER_ERROR.value, "message": "server error"}})

    app.add_exception_handler(Exception, server_error)

    def override_db() -> Iterator[Session]:
        session = tw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_factory] = lambda: tw.db.session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
