"""PostgreSQL fixtures for A4 booking tests (built on A1's shared world, real A2 flags and A3 wallet).

* ``bw`` - A1 world + staff users (super_admin, operator, finance) + country flags enabled + both drivers' commission
  wallets funded through the real top-up path (1 000 000 so'm each).
* helpers to publish listings, open/counter proposals and accept through the A4 orchestrator.
* ``client`` - test-local FastAPI app with identity/trips/marketplace/bookings routers (the integrator wires /api/v2).
* ``lock_clock`` - forced-overlap evidence (same technique as tests/pg/test_v1_order_races.py).
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.contracts.enums import STAFF_ROLE_CAPABILITIES, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ProposalCounter, ProposalCreate
from app.modules.wallet import service as wallet_service
from tests.pg.conftest import PgDatabase
from tests.pg.identity.a1_world import (  # noqa: F401  (shared A1 fixture)
    World,
    add_user,
    make_trip,
    make_vehicle,
    passenger_offer,
    world,
)

SUPER_CAPS = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
FUNDED_MINOR = 100_000_000  # 1 000 000 so'm


@dataclass
class BW:
    w: World
    super_id: int
    operator_id: int
    finance_id: int

    @property
    def db(self) -> PgDatabase:
        return self.w.db

    @property
    def base(self) -> datetime:
        return self.w.base_time


def _mark_flag_change_source(conn) -> None:  # noqa: ANN001
    """Q72 (A2 0057): v2 flags are enabled only in a transaction marked as the admin API source."""
    from app.modules.geo.service import mark_flag_change_source

    mark_flag_change_source(conn)


def enable_flags(db: PgDatabase, admin_id: int, keys: tuple[str, ...] = ("passenger_enabled", "parcel_enabled", "driver_listing_enabled")) -> None:
    with db.engine.begin() as conn:
        _mark_flag_change_source(conn)
        for key in keys:
            conn.execute(
                text(
                    "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
                    "VALUES (:p, :k, 'country', 'UZ', true, 'A4 test', :u)"
                ),
                {"p": uuid.uuid4(), "k": key, "u": admin_id},
            )


def set_flag(db: PgDatabase, key: str, enabled: bool) -> None:
    with db.engine.begin() as conn:
        _mark_flag_change_source(conn)
        conn.execute(
            text("UPDATE feature_flag_values SET enabled = :e, version = version + 1 WHERE flag_key = :k AND scope_type = 'country'"),
            {"e": enabled, "k": key},
        )


def fund(bw_or_db, driver_id: int, amount_minor: int, approver_id: int) -> None:  # noqa: ANN001
    db = bw_or_db.db if isinstance(bw_or_db, BW) else bw_or_db
    with db.session() as s:
        topup = wallet_service.create_topup(s, driver_user_id=driver_id, amount_minor=amount_minor, method="bank_transfer")
        wallet_service.approve_topup(
            s, actor_user_id=approver_id, actor_capabilities=SUPER_CAPS, topup_id=topup.id, expected_version=topup.version,
            source_type="bank_statement", source_reference=f"BANK-{uuid.uuid4().hex}", received_amount_minor=amount_minor,
            received_at=utc_now() - timedelta(minutes=5),
        )
        s.commit()


def _reset_booking_hooks() -> None:
    """A12 hooks are process-global (``app.main`` start-up registers them); each booking test starts and ends without them
    (Q74 fallback) unless the test registers them itself."""
    bookings_service.set_blocking_dispute_probe(None)
    bookings_service.set_payment_dispute_opener(None)


@pytest.fixture
def bw(world: World) -> Iterator[BW]:
    _reset_booking_hooks()
    with world.db.session() as s:
        super_id = add_user(s, "+998900000400", "super_admin", full_name="Super Admin")
        operator_id = add_user(s, "+998900000401", "operator", full_name="Olim Operator")
        finance_id = add_user(s, "+998900000402", "finance", full_name="Farida Finance")
        s.commit()
    enable_flags(world.db, world.admin_id)
    built = BW(world, super_id, operator_id, finance_id)
    fund(built, world.driver_id, FUNDED_MINOR, super_id)
    fund(built, world.driver2_id, FUNDED_MINOR, super_id)
    try:
        yield built
    finally:
        _reset_booking_hooks()


# --- builders ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadRef:
    listing_id: str
    thread_id: str
    version_id: str
    revision: int


def passenger_request_body(bw: BW, *, seats: int = 2, unit: int = 20_000_000, origin: str = "A", destination: str = "D",
                           baggage_ml: int = 40_000, start: datetime | None = None) -> ListingCreate:
    start = start or bw.base
    return ListingCreate.model_validate(
        {
            "kind": "request",
            "service_type": "passenger",
            "origin_stop_id": bw.w.stop_public_ids[origin],
            "destination_stop_id": bw.w.stop_public_ids[destination],
            "departure_window_start": start.isoformat(),
            "departure_window_end": (start + timedelta(hours=1)).isoformat(),
            "price_basis": "per_seat",
            "unit_price_minor": unit,
            "passenger": {"seat_count": seats, "adults": seats, "baggage": {"pieces": 1, "total_weight_g": 10_000, "total_volume_ml": baggage_ml}},
        }
    )


def parcel_request_body(bw: BW, *, origin: str = "A", destination: str = "C", unit: int = 7_000_000, payer: str = "sender") -> ListingCreate:
    start = bw.base
    return ListingCreate.model_validate(
        {
            "kind": "request",
            "service_type": "parcel",
            "origin_stop_id": bw.w.stop_public_ids[origin],
            "destination_stop_id": bw.w.stop_public_ids[destination],
            "departure_window_start": start.isoformat(),
            "departure_window_end": (start + timedelta(hours=2)).isoformat(),
            "price_basis": "total",
            "unit_price_minor": unit,
            "parcel": {
                "parcel_type": "documents", "weight_g": 2_000, "length_cm": 20, "width_cm": 20, "height_cm": 20, "fragile": False,
                "payer": payer, "sender": {"name": "Aziza Karimova", "phone": "+998900000201"},
                "receiver": {"name": "Nodira Qosimova", "phone": "+998977777777"},
            },
        }
    )


def publish_listing(bw: BW, owner_id: int, body: ListingCreate) -> str:
    with bw.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=owner_id, data=body)
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(s, listing_public_id=public_id, actor_user_id=owner_id, expected_version=listing.version)
        s.commit()
        return public_id


def driver_trip(bw: BW, driver_id: int, plate: str, *, seats: int = 4, baggage_ml: int = 200_000, cargo_g: int = 50_000,
                cargo_ml: int = 300_000) -> tuple[int, str]:
    vehicle = make_vehicle(bw.w, driver_id, plate, seats=max(seats, 1))
    return make_trip(bw.w, driver_id, vehicle, start=bw.base, seats=seats, baggage_ml=baggage_ml, cargo_g=cargo_g, cargo_ml=cargo_ml)


def _ref(session: Session, listing_public_id: str, thread) -> ThreadRef:  # noqa: ANN001
    version = marketplace_service.current_version(session, thread)
    return ThreadRef(listing_public_id, marketplace_service.thread_public_id(thread), marketplace_service.version_public_id(version), version.revision)


def occurrence_window(bw: BW, stop: str) -> tuple[datetime, datetime]:
    offset = {"A": 0, "B": 1, "C": 2, "D": 3}[stop]
    start = bw.base + timedelta(hours=offset)
    return start, start + timedelta(minutes=30)


def propose(bw: BW, listing_public_id: str, actor_id: int, *, trip_public_id: str | None, quantity: int = 2, unit: int = 19_000_000,
            pickup: str = "A", dropoff: str = "D", price_basis: str = "per_seat", parcel: dict | None = None) -> ThreadRef:
    window = occurrence_window(bw, pickup)
    payload = {
        "trip_id": trip_public_id,
        "pickup_stop_id": bw.w.stop_public_ids[pickup],
        "dropoff_stop_id": bw.w.stop_public_ids[dropoff],
        "pickup_window_start": window[0].isoformat(),
        "pickup_window_end": window[1].isoformat(),
        "quantity": quantity,
        "price_basis": price_basis,
        "unit_price_minor": unit,
    }
    if parcel is not None:
        payload["parcel"] = parcel
    with bw.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s, listing_public_id=listing_public_id, actor_user_id=actor_id, data=ProposalCreate.model_validate(payload)
        )
        ref = _ref(s, listing_public_id, thread)
        s.commit()
        return ref


def counter(bw: BW, ref: ThreadRef, actor_id: int, *, unit: int) -> ThreadRef:
    with bw.db.session() as s:
        thread = marketplace_service.counter_proposal(
            s, thread_public_id_value=ref.thread_id, actor_user_id=actor_id,
            data=ProposalCounter(expected_revision=ref.revision, unit_price_minor=unit),
        )
        new = _ref(s, ref.listing_id, thread)
        s.commit()
        return new


def listing_version(bw: BW, listing_public_id: str) -> int:
    """Q54: what the accepting party sends as ``expected_listing_version`` is the listing's terms_version."""
    with bw.db.session() as s:
        return marketplace_service.get_listing_by_public_id(s, listing_public_id).terms_version


def accept(bw: BW, ref: ThreadRef, actor_id: int, *, session: Session | None = None, now: datetime | None = None,
           expected_listing_version: int | None = None, commit: bool = True) -> Booking:
    own = session is None
    s = session or bw.db.session()
    try:
        booking = bookings_service.accept_proposal(
            s, thread_public_id=ref.thread_id, actor_user_id=actor_id, proposal_version_public_id=ref.version_id,
            expected_listing_version=expected_listing_version if expected_listing_version is not None else listing_version(bw, ref.listing_id),
            now=now,
        )
        if commit:
            s.commit()
        return booking
    except BaseException:
        s.rollback()
        raise
    finally:
        if own:
            s.close()


def seats_used(bw: BW, trip_id: int) -> list[int]:
    from app.modules.trips import service as trips_service

    with bw.db.session() as s:
        return [load.seats_used for load in trips_service.get_segment_loads(s, trip_id)]


def wallet(bw: BW, driver_id: int) -> tuple[int, int]:
    row = rows(bw.db, "SELECT posted_balance_minor, held_minor FROM wallet_accounts WHERE driver_user_id = :d", d=driver_id)[0]
    return row.posted_balance_minor, row.held_minor


def request_with_driver_proposal(bw: BW, *, seats: int = 2, trip_seats: int = 4, plate: str = "01A100AA", client_id: int | None = None,
                                 driver_id: int | None = None):  # noqa: ANN201
    driver_id = driver_id or bw.w.driver_id
    listing = publish_listing(bw, client_id or bw.w.client_id, passenger_request_body(bw, seats=seats))
    trip_id, trip_public = driver_trip(bw, driver_id, plate, seats=trip_seats)
    ref = propose(bw, listing, driver_id, trip_public_id=trip_public, quantity=seats)
    return listing, trip_id, trip_public, ref


def trip_version(bw: BW, trip_id: int) -> int:
    return int(scalar(bw.db, "SELECT version FROM trips WHERE id = :t", t=trip_id))


def booking_version(bw: BW, booking_id: int) -> int:
    return int(scalar(bw.db, "SELECT version FROM bookings WHERE id = :b", b=booking_id))


def run_trip_action(bw: BW, trip_id: int, actor_id: int, action: str, *, now: datetime, reason: str | None = None):  # noqa: ANN201
    from app.modules.trips import service as trips_service

    with bw.db.session() as s:
        trip = trips_service.get_trip(s, trip_id)
        result = bookings_service.trip_action(
            s, trip_public_id_value=trips_service.trip_public_id(trip), actor_user_id=actor_id, action=action,
            expected_version=trip.version, reason=reason, now=now,
        )
        s.commit()
        return result.status


def act(bw: BW, booking_id: int, actor_id: int, action: str, *, now: datetime | None = None, code: str | None = None,
        failures: list | None = None, **extra: object) -> Booking:
    with bw.db.session() as s:
        booking = s.get(Booking, booking_id)
        result = bookings_service.perform_action(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=actor_id, action=action,
            data=bookings_service.ActionInput(expected_version=booking.version, code=code, **extra), now=now, proof_failures=failures,
        )
        s.commit()
        return result


def operator(bw: BW, booking_id: int, actor_id: int, command: str, *, now: datetime | None = None, fee_mode: str | None = None,
             reason: str = "operator decision") -> Booking:
    with bw.db.session() as s:
        booking = s.get(Booking, booking_id)
        result = bookings_service.operator_command(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=actor_id, command=command,
            expected_version=booking.version, reason=reason, fee_mode=fee_mode, now=now,
        )
        s.commit()
        return result


def codes_for(bw: BW, booking_id: int, viewer_id: int) -> dict[str, str]:
    with bw.db.session() as s:
        booking = s.get(Booking, booking_id)
        return {kind.value: code for kind, code in bookings_service.booking_codes(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), viewer_user_id=viewer_id)}


def view(bw: BW, booking_id: int, role: str, *, now: datetime | None = None) -> dict:
    from app.modules.bookings.views import booking_view

    with bw.db.session() as s:
        return booking_view(s, s.get(Booking, booking_id), viewer_role=role, now=now).model_dump(mode="json")


def domain_error(fn: Callable[[], object]) -> DomainError:
    with pytest.raises(DomainError) as info:
        fn()
    return info.value


def scalar(db: PgDatabase, sql: str, **params: object):  # noqa: ANN201
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(db: PgDatabase, sql: str, **params: object) -> list:
    with db.engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


# --- HTTP ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(bw: BW) -> Iterator[TestClient]:
    from app.modules.bookings.api import router as bookings_router
    from app.modules.identity.api import router as identity_router
    from app.modules.identity.web import domain_error_handler
    from app.modules.marketplace.api import router as marketplace_router
    from app.modules.trips.api import router as trips_router

    app = FastAPI()
    for router in (identity_router, trips_router, marketplace_router, bookings_router):
        app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    from sqlalchemy.exc import DBAPIError

    from app.api.v2.web import db_error_handler

    app.add_exception_handler(DBAPIError, db_error_handler)  # wave 2.1: app.main maps /api/v2 DB errors the same way

    async def server_error(request, exc):  # noqa: ANN001, ANN202 - mirrors app.main's generic 500 envelope
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


def auth(user_id: int, role: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_access_token(str(user_id), extra_claims={'role': role})}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


# --- forced overlap -------------------------------------------------------------------------------------------------------

HOLD_S = 0.4
STAGGER_S = 0.12
USERS_LOCK = re.compile(r"\bFROM users\b.*\bFOR (NO KEY UPDATE|UPDATE)", re.S)
TRIPS_LOCK = re.compile(r"\bFROM trips\b.*\bFOR (NO KEY UPDATE|UPDATE)", re.S)


class LockClock:
    """Per worker: when its first matching lock statement was sent/returned and when it committed."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self._local = threading.local()
        self._mutex = threading.Lock()
        self.started: dict[int, float] = {}
        self.acquired: dict[int, float] = {}
        self.commit_started: dict[int, float] = {}

    def reset(self) -> None:
        with self._mutex:
            self.started.clear()
            self.acquired.clear()
            self.commit_started.clear()

    def bind(self, index: int) -> None:
        self._local.index = index

    def before_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        index = getattr(self._local, "index", None)
        if index is not None and self.pattern.search(statement):
            with self._mutex:
                self.started.setdefault(index, time.perf_counter())

    def after_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        index = getattr(self._local, "index", None)
        if index is not None and self.pattern.search(statement):
            with self._mutex:
                self.acquired.setdefault(index, time.perf_counter())

    def on_commit(self, conn) -> None:  # noqa: ANN001
        index = getattr(self._local, "index", None)
        if index is not None:
            with self._mutex:
                self.commit_started.setdefault(index, time.perf_counter())

    def assert_waited(self, early: int, late: int) -> None:
        state = (self.started, self.acquired, self.commit_started)
        assert late in self.started and late in self.acquired and early in self.commit_started, state
        assert self.started[late] < self.commit_started[early] <= self.acquired[late], state


@pytest.fixture
def lock_clock(pg_db: PgDatabase):  # noqa: ANN201
    registered: list[tuple[str, object]] = []

    def make(pattern: re.Pattern[str]) -> LockClock:
        clock = LockClock(pattern)
        for name, fn in (("before_cursor_execute", clock.before_execute), ("after_cursor_execute", clock.after_execute), ("commit", clock.on_commit)):
            event.listen(pg_db.engine, name, fn)
            registered.append((name, fn))
        return clock

    yield make
    for name, fn in registered:
        event.remove(pg_db.engine, name, fn)


def hold_inside(monkeypatch: pytest.MonkeyPatch, module, name: str, seconds: float = HOLD_S, *, only_thread: Callable[[], bool] | None = None) -> None:  # noqa: ANN001
    original = getattr(module, name)

    def delayed(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if only_thread is None or only_thread():
            time.sleep(seconds)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, delayed)
