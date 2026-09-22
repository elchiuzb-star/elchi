"""v1 order/bid/driver/account race invariants on real PostgreSQL 16 (H1).

Service functions are called directly, each worker with its own Session and
connection (tests/pg/harness.py); every worker commits or rolls back on its own,
exactly like concurrent API requests.

Invariants (card letters from WAVE1_CARDS H1):
- (a) client cancel vs select-driver: one of the two serial outcomes;
- (b) update_bid vs select-driver: the accepted bid's price equals final_price;
      update_bid never revives a closed/accepted/rejected bid;
- (c) bid create/update vs client cancel: no active bid on a cancelled order;
- (d) parallel publish: published exactly once;
- (e) block_driver vs select-driver: a driver blocked first is never assigned;
- F4 create_bid vs block_driver: no new bid from a driver blocked first;
- F1 FK key-share: block_driver vs token refresh, account deletion vs admin
  cancel / rating: no deadlock and a consistent final state.

Forced overlap: test hooks (monkeypatched module functions that run *inside*
the locked section) sleep, and one worker starts STAGGER_S later. LockClock
records when each worker's contended lock statement returned and when each
worker committed; the tests assert the late worker got its lock only after the
early worker committed (it really waited on the row lock).

Negative controls (bottom) swap the lock helpers for plain reads (or restore the
old FOR UPDATE users lock) and show the same scenarios then break the invariant
(or deadlock): the tests detect a missing or wrong lock. They are deterministic
because the hooks hold the first worker inside its critical section while the
second reads stale state; they assert "at least once" to stay robust.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers mappers)
from app.api.v1 import admin_clients
from app.api.v1.admin_clients import block_admin_client
from app.core.security import create_refresh_token, verify_token
from app.models import AuditLog, Bid, City, DriverDocument, DriverProfile, DriverRoute, Order, OrderOffer, Rating, RefreshSession, StatusHistory, User
from app.schemas.admin_driver import AdminDriverBlock, AdminDriverVehicleUpdate
from app.schemas.driver import DriverDocumentCreate, DriverRouteStatusUpdate
from app.schemas.admin_order import AdminOrderCancel
from app.schemas.bid import BidCreate, BidUpdate
from app.schemas.order import ClientOrderCancel, ClientOrderRatingCreate, SelectDriverRequest
from app.services import account_deletion_service, admin_driver_service, admin_order_service, auth_service, driver_order_service, driver_service, order_service
from app.services.account_deletion_service import delete_own_account
from app.services.admin_driver_service import block_driver, update_driver_vehicle
from app.services.driver_locks import lock_user_key_share, lock_user_row
from app.services.driver_service import normalize_plate_number_key, submit_driver_document, update_route_status
from app.services.admin_order_service import cancel_order_manually
from app.services.auth_service import create_refresh_session, refresh_tokens
from app.services.driver_order_service import create_bid, update_bid
from app.services.order_service import cancel_order, create_order_rating, publish_order, select_driver_for_order
from tests.pg.conftest import PgDatabase
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg

WORKERS = 20
HOLD_S = 0.3  # sleep inside the locked section (test hook)
STAGGER_S = 0.1  # the late worker starts this much later

ORDERS_LOCK = re.compile(r"\bFROM orders\b.*\bFOR (NO KEY )?UPDATE", re.S)
USERS_LOCK = re.compile(r"\bFROM users\b.*\bFOR (NO KEY UPDATE|UPDATE)", re.S)
# Any users row lock (deletion FOR UPDATE vs self-service FOR KEY SHARE).
USERS_ANY_LOCK = re.compile(r"\bFROM users\b.*\bFOR (NO KEY UPDATE|UPDATE|SHARE|KEY SHARE)\b", re.S)
# block_driver (NO KEY UPDATE) vs refresh (FOR SHARE); logout's FOR KEY SHARE does not match.
USERS_WRITE_OR_SHARE_LOCK = re.compile(r"\bFROM users\b.*\bFOR (NO KEY UPDATE|UPDATE|SHARE)\b", re.S)
PROFILE_LOCK = re.compile(r"\bFROM driver_profiles\b.*\bFOR (NO KEY UPDATE|UPDATE)\b", re.S)


# ── fixtures and helpers ─────────────────────────────────────────────────────


@dataclass
class World:
    client_id: int
    admin_id: int
    driver_user_ids: list[int]
    profile_ids: list[int]
    from_city_id: int
    to_city_id: int


def seed_world(db: PgDatabase, drivers: int) -> World:
    with db.session() as s:
        client = User(phone="+998970000001", role="client", status="active", is_phone_verified=True)
        admin = User(phone="+998970000002", role="admin", status="active", is_phone_verified=True)
        from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
        to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
        s.add_all([client, admin, from_city, to_city])
        s.flush()
        user_ids, profile_ids = [], []
        for i in range(drivers):
            user = User(phone=f"+99897100{i:04d}", role="driver", status="active", is_phone_verified=True)
            s.add(user)
            s.flush()
            profile = DriverProfile(user_id=user.id, full_name=f"Driver {i}", verification_status="approved", is_available=True, plate_number=f"01A{i:03d}AA")
            s.add(profile)
            s.flush()
            s.add(DriverRoute(driver_id=profile.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
            user_ids.append(user.id)
            profile_ids.append(profile.id)
        s.commit()
        return World(client.id, admin.id, user_ids, profile_ids, from_city.id, to_city.id)


def seed_client(db: PgDatabase, n: int) -> int:
    with db.session() as s:
        user = User(phone=f"+99897200{n:04d}", role="client", status="active", is_phone_verified=True)
        s.add(user)
        s.commit()
        return user.id


def seed_order(
    db: PgDatabase,
    world: World,
    *,
    status: str,
    number: str,
    client_id: int | None = None,
    driver_slot: int | None = None,
) -> int:
    with db.session() as s:
        order = Order(
            order_number=number,
            client_id=client_id or world.client_id,
            from_city_id=world.from_city_id,
            to_city_id=world.to_city_id,
            pickup_address="Toshkent, Chilonzor",
            dropoff_address="Samarqand, Registon",
            sender_phone="+998901234567",
            receiver_phone="+998911112233",
            status=status,
            assigned_driver_id=world.profile_ids[driver_slot] if driver_slot is not None else None,
            final_price=Decimal("50000") if driver_slot is not None else None,
        )
        s.add(order)
        s.commit()
        return order.id


def seed_bids(db: PgDatabase, order_id: int, profile_ids: list[int], *, status: str = "active") -> list[int]:
    with db.session() as s:
        bids = [Bid(order_id=order_id, driver_id=pid, price=Decimal(50000 + i * 1000), status=status) for i, pid in enumerate(profile_ids)]
        s.add_all(bids)
        s.commit()
        return [bid.id for bid in bids]


def outcome(result) -> str:
    """'ok' for a success, the v1 error code for a refusal."""
    if isinstance(result, JSONResponse):
        return json.loads(result.body)["error"]["code"]
    return "ok"


def assert_no_worker_crashed(report) -> None:
    assert report.failures == [], [f"worker {r.index}: {r.error!r}" for r in report.failures]


def is_deadlock(error: BaseException | None) -> bool:
    return isinstance(error, OperationalError) and isinstance(error.orig, pg_errors.DeadlockDetected)


def statuses(db: PgDatabase, order_id: int) -> dict[int, str]:
    with db.session() as s:
        return dict(s.execute(select(Bid.id, Bid.status).where(Bid.order_id == order_id)).all())


def hold_inside(monkeypatch: pytest.MonkeyPatch, module, name: str, seconds: float = HOLD_S, *, after: bool = False) -> None:
    """Test hook: make `module.name` sleep before (or after) running; it runs inside the locks."""
    original = getattr(module, name)

    def delayed(*args, **kwargs):
        if not after:
            time.sleep(seconds)
        result = original(*args, **kwargs)
        if after:
            time.sleep(seconds)
        return result

    monkeypatch.setattr(module, name, delayed)


class LockClock:
    """Per worker: when its first matching lock statement was sent (`started`) and
    returned (`acquired`), and when it sent COMMIT (`commit_started`, the engine
    "commit" event fires before the DBAPI commit, i.e. before locks are released).

    `assert_waited(early, late)` proves real overlap and real waiting:
        started[late] < commit_started[early] <= acquired[late]
    the late worker asked for the lock while the early one still held it, and
    only got it after the early worker began committing.
    """

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

    def _index(self) -> int | None:
        return getattr(self._local, "index", None)

    def before_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        index = self._index()
        if index is not None and self.pattern.search(statement):
            with self._mutex:
                self.started.setdefault(index, time.perf_counter())

    def after_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        index = self._index()
        if index is not None and self.pattern.search(statement):
            with self._mutex:
                self.acquired.setdefault(index, time.perf_counter())

    def on_commit(self, conn) -> None:
        index = self._index()
        if index is not None:
            with self._mutex:
                self.commit_started.setdefault(index, time.perf_counter())

    def bind(self, index: int, session: Session) -> None:
        self._local.index = index

    def assert_waited(self, early: int, late: int) -> None:
        state = (self.started, self.acquired, self.commit_started)
        assert late in self.started and late in self.acquired and early in self.commit_started, state
        assert self.started[late] < self.commit_started[early] <= self.acquired[late], (
            f"late worker {late}: asked {self.started[late]:.4f}, got {self.acquired[late]:.4f}; "
            f"early worker {early} began commit {self.commit_started[early]:.4f}"
        )


@pytest.fixture
def lock_clock(pg_db: PgDatabase):
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


def staggered(index: int, early_index: int) -> None:
    if index != early_index:
        time.sleep(STAGGER_S)


# ── (c) cancel vs bid create/update ──────────────────────────────────────────


def run_cancel_vs_creates(pg_db: PgDatabase, world: World, round_no: int, *, updaters: int, creators: int):
    order_id = seed_order(pg_db, world, status="bidding", number=f"ORD-RACE-A-{round_no}")
    updater_slots = list(range(updaters))
    creator_slots = list(range(updaters, updaters + creators))
    bid_ids = seed_bids(pg_db, order_id, [world.profile_ids[i] for i in updater_slots])

    def work(index: int, session: Session) -> str:
        if index == 0:
            time.sleep(STAGGER_S)  # creators read the order first
            client = session.get(User, world.client_id)
            return outcome(cancel_order(session, client, order_id, ClientOrderCancel(reason="race")))
        if index <= updaters:
            slot = updater_slots[index - 1]
            user = session.get(User, world.driver_user_ids[slot])
            profile = session.get(DriverProfile, world.profile_ids[slot])
            return outcome(update_bid(session, user, profile, bid_ids[index - 1], BidUpdate(price=Decimal("77000"))))
        slot = creator_slots[index - 1 - updaters]
        user = session.get(User, world.driver_user_ids[slot])
        profile = session.get(DriverProfile, world.profile_ids[slot])
        return outcome(create_bid(session, user, profile, order_id, BidCreate(price=Decimal("66000"))))

    report = run_concurrently(1 + updaters + creators, work, engine=pg_db.engine)
    return order_id, report


def test_cancel_vs_concurrent_bid_create_and_update_leaves_no_active_bid(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """1 cancel + 10 updates + 9 creates = 20 workers; creates sleep inside the order lock."""
    hold_inside(monkeypatch, driver_order_service, "ensure_order_visible", 0.05)
    world = seed_world(pg_db, drivers=WORKERS - 1)
    for round_no in range(3):
        order_id, report = run_cancel_vs_creates(pg_db, world, round_no, updaters=10, creators=9)

        assert_no_worker_crashed(report)
        results = {r.index: r.value for r in report.results}
        assert results[0] == "ok", results
        assert set(results.values()) <= {"ok", "ORDER_INVALID_STATUS"}, results
        with pg_db.session() as s:
            assert s.get(Order, order_id).status == "cancelled"
            assert s.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id, Bid.status == "active")) == 0, statuses(pg_db, order_id)
            assert set(statuses(pg_db, order_id).values()) == {"closed"}
            created_ok = sum(1 for i in range(11, WORKERS) if results[i] == "ok")
            assert s.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id)) == 10 + created_ok
            assert len(s.scalars(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "cancelled")).all()) == 1


# ── (a) cancel vs select-driver ──────────────────────────────────────────────


def run_cancel_vs_select(pg_db: PgDatabase, world: World, round_no: int, *, select_first: bool, clock: LockClock | None = None):
    order_id = seed_order(pg_db, world, status="bidding", number=f"ORD-RACE-B-{round_no}")
    bid_ids = seed_bids(pg_db, order_id, world.profile_ids)
    early = 1 if select_first else 0

    def work(index: int, session: Session) -> str:
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        client = session.get(User, world.client_id)
        if index == 0:
            return outcome(cancel_order(session, client, order_id, ClientOrderCancel(reason="race")))
        return outcome(select_driver_for_order(session, client, order_id, SelectDriverRequest(bid_id=bid_ids[0])))

    return order_id, bid_ids, early, run_concurrently(2, work, engine=pg_db.engine)


def cancel_select_history(pg_db: PgDatabase, order_id: int) -> list[tuple[str | None, str]]:
    with pg_db.session() as s:
        return [(h.old_status, h.new_status) for h in s.scalars(select(StatusHistory).where(StatusHistory.order_id == order_id).order_by(StatusHistory.id))]


def test_cancel_vs_select_driver_is_serializable(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    hold_inside(monkeypatch, order_service, "write_status_history")  # inside both transactions' locks
    clock = lock_clock(ORDERS_LOCK)
    world = seed_world(pg_db, drivers=3)
    seen: set[str] = set()
    for round_no in range(4):
        clock.reset()
        order_id, bid_ids, early, report = run_cancel_vs_select(pg_db, world, round_no, select_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        cancel_value, select_value = report.results[0].value, report.results[1].value
        chosen = bid_ids[0]
        history = cancel_select_history(pg_db, order_id)
        bids = statuses(pg_db, order_id)
        with pg_db.session() as s:
            order = s.get(Order, order_id)
            assert "active" not in bids.values(), bids
            if select_value == "ok":
                seen.add("select_then_cancel")
                assert cancel_value == "ok"  # v1 lets a client cancel an accepted order
                assert history == [("bidding", "accepted"), ("accepted", "cancelled")], history
                assert order.status == "cancelled"
                assert bids[chosen] == "accepted" and all(bids[b] == "closed" for b in bid_ids[1:])
                assert order.assigned_driver_id == world.profile_ids[0] and order.accepted_bid_id == chosen
                assert order.final_price == Decimal("50000")
                assert order.system_fee is not None and order.system_fee + order.driver_income == order.final_price
            else:
                seen.add("cancel_first")
                assert cancel_value == "ok" and select_value == "ORDER_INVALID_STATUS"
                assert history == [("bidding", "cancelled")], history
                assert order.status == "cancelled" and set(bids.values()) == {"closed"}
                assert order.assigned_driver_id is None and order.accepted_bid_id is None
                assert order.final_price is None and order.system_fee is None
    assert seen == {"select_then_cancel", "cancel_first"}


def test_select_driver_is_exclusive(pg_db: PgDatabase) -> None:
    world = seed_world(pg_db, drivers=2)
    order_id = seed_order(pg_db, world, status="bidding", number="ORD-RACE-B2")
    bid_ids = seed_bids(pg_db, order_id, world.profile_ids)

    def work(index: int, session: Session) -> str:
        client = session.get(User, world.client_id)
        return outcome(select_driver_for_order(session, client, order_id, SelectDriverRequest(bid_id=bid_ids[index % 2])))

    report = run_concurrently(10, work, engine=pg_db.engine)

    assert_no_worker_crashed(report)
    values = report.values()
    assert values.count("ok") == 1, values
    assert set(values) - {"ok"} <= {"ORDER_INVALID_STATUS"}
    with pg_db.session() as s:
        order = s.get(Order, order_id)
        bids = statuses(pg_db, order_id)
        assert order.status == "accepted"
        assert list(bids.values()).count("accepted") == 1
        assert bids[order.accepted_bid_id] == "accepted"
        assert s.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "accepted")) == 1


# ── (b) update_bid vs select-driver ──────────────────────────────────────────


def run_update_vs_select(pg_db: PgDatabase, world: World, round_no: int, *, update_first: bool, clock: LockClock | None = None):
    order_id = seed_order(pg_db, world, status="bidding", number=f"ORD-RACE-C2-{round_no}")
    bid_ids = seed_bids(pg_db, order_id, world.profile_ids)
    early = 0 if update_first else 1

    def work(index: int, session: Session) -> str:
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            user = session.get(User, world.driver_user_ids[0])
            profile = session.get(DriverProfile, world.profile_ids[0])
            return outcome(update_bid(session, user, profile, bid_ids[0], BidUpdate(price=Decimal("88000"))))
        client = session.get(User, world.client_id)
        return outcome(select_driver_for_order(session, client, order_id, SelectDriverRequest(bid_id=bid_ids[0])))

    return order_id, bid_ids, early, run_concurrently(2, work, engine=pg_db.engine)


def accepted_price_matches_final(pg_db: PgDatabase, order_id: int) -> bool:
    with pg_db.session() as s:
        order = s.get(Order, order_id)
        accepted = s.get(Bid, order.accepted_bid_id) if order.accepted_bid_id else None
        return accepted is not None and accepted.status == "accepted" and accepted.price == order.final_price


def test_update_bid_vs_select_driver_forced_overlap(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    hold_inside(monkeypatch, driver_order_service, "review_pairing_allowed")  # update: after all checks, inside locks
    hold_inside(monkeypatch, order_service, "apply_order_commission")  # select: inside order/bid/driver locks
    clock = lock_clock(ORDERS_LOCK)
    world = seed_world(pg_db, drivers=2)
    seen: set[str] = set()
    for round_no in range(4):
        clock.reset()
        order_id, bid_ids, early, report = run_update_vs_select(pg_db, world, round_no, update_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        update_value, select_value = report.results[0].value, report.results[1].value
        assert select_value == "ok"
        assert accepted_price_matches_final(pg_db, order_id)
        with pg_db.session() as s:
            order = s.get(Order, order_id)
            bid = s.get(Bid, bid_ids[0])
            assert order.status == "accepted" and bid.status == "accepted"
            if update_value == "ok":
                seen.add("update_then_select")
                assert bid.price == Decimal("88000") and order.final_price == Decimal("88000")
            else:
                seen.add("select_first")
                assert update_value == "ORDER_INVALID_STATUS"
                assert bid.price == Decimal("50000") and bid.price_update_count == 0
    assert seen == {"update_then_select", "select_first"}


def test_update_bid_never_revives_closed_bid_under_concurrency(pg_db: PgDatabase) -> None:
    world = seed_world(pg_db, drivers=WORKERS - 1)
    for round_no in range(3):
        order_id = seed_order(pg_db, world, status="bidding", number=f"ORD-RACE-C-{round_no}")
        bid_ids = seed_bids(pg_db, order_id, world.profile_ids)
        chosen_slot = round_no * 7 % len(bid_ids)

        def work(index: int, session: Session) -> str:
            if index == 0:
                client = session.get(User, world.client_id)
                return outcome(select_driver_for_order(session, client, order_id, SelectDriverRequest(bid_id=bid_ids[chosen_slot])))
            slot = index - 1
            user = session.get(User, world.driver_user_ids[slot])
            profile = session.get(DriverProfile, world.profile_ids[slot])
            return outcome(update_bid(session, user, profile, bid_ids[slot], BidUpdate(price=Decimal("88000"))))

        report = run_concurrently(WORKERS, work, engine=pg_db.engine)

        assert_no_worker_crashed(report)
        results = {r.index: r.value for r in report.results}
        assert results[0] == "ok", results
        assert set(results.values()) <= {"ok", "ORDER_INVALID_STATUS"}, results
        with pg_db.session() as s:
            order = s.get(Order, order_id)
            bids = {b.id: b for b in s.scalars(select(Bid).where(Bid.order_id == order_id))}
            assert order.status == "accepted"
            assert [b.status for b in bids.values()].count("active") == 0
            assert [b.status for b in bids.values()].count("accepted") == 1
            assert order.final_price == bids[bid_ids[chosen_slot]].price
            for slot, bid_id in enumerate(bid_ids):
                if slot == chosen_slot:
                    continue
                assert bids[bid_id].status == "closed"
                if results[slot + 1] != "ok":
                    assert bids[bid_id].price == Decimal(50000 + slot * 1000)


def test_concurrent_updates_of_rejected_bid_all_refused(pg_db: PgDatabase) -> None:
    world = seed_world(pg_db, drivers=2)
    order_id = seed_order(pg_db, world, status="bidding", number="ORD-RACE-D")
    rejected_bid, _other = seed_bids(pg_db, order_id, world.profile_ids)
    with pg_db.session() as s:
        s.get(Bid, rejected_bid).status = "rejected"
        s.commit()

    def work(index: int, session: Session) -> str:
        user = session.get(User, world.driver_user_ids[0])
        profile = session.get(DriverProfile, world.profile_ids[0])
        return outcome(update_bid(session, user, profile, rejected_bid, BidUpdate(price=Decimal(60000 + index))))

    report = run_concurrently(WORKERS, work, engine=pg_db.engine)

    assert_no_worker_crashed(report)
    assert report.values() == ["BID_NOT_ACTIVE"] * WORKERS
    with pg_db.session() as s:
        bid = s.get(Bid, rejected_bid)
        assert bid.status == "rejected" and bid.price == Decimal("50000") and bid.price_update_count == 0
        assert s.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "driver_bid_updated")) == 0


# ── (d) parallel publish ─────────────────────────────────────────────────────


def run_publishes(pg_db: PgDatabase, world: World, number: str, workers: int = 10):
    order_id = seed_order(pg_db, world, status="draft", number=number)

    def work(index: int, session: Session) -> str:
        client = session.get(User, world.client_id)
        return outcome(publish_order(session, client, order_id))

    return order_id, run_concurrently(workers, work, engine=pg_db.engine)


def published_count(pg_db: PgDatabase, order_id: int) -> int:
    with pg_db.session() as s:
        return s.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "published"))


def test_concurrent_publish_publishes_once(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    hold_inside(monkeypatch, order_service, "validate_order_complete", 0.2)  # after the status check, inside the lock
    world = seed_world(pg_db, drivers=3)
    order_id, report = run_publishes(pg_db, world, "ORD-RACE-E")

    assert_no_worker_crashed(report)
    values = report.values()
    assert values.count("ok") == 1, values
    assert values.count("ORDER_INVALID_STATUS") == 9
    assert published_count(pg_db, order_id) == 1
    with pg_db.session() as s:
        assert s.get(Order, order_id).status == "published"
        assert s.scalar(select(func.count(OrderOffer.id)).where(OrderOffer.order_id == order_id)) == 3


# ── (e) block_driver vs select-driver ────────────────────────────────────────


def run_block_vs_select(pg_db: PgDatabase, world: World, round_no: int, *, select_first: bool, clock: LockClock | None = None):
    slot = round_no
    order_id = seed_order(pg_db, world, status="bidding", number=f"ORD-RACE-F-{round_no}")
    (bid_id,) = seed_bids(pg_db, order_id, [world.profile_ids[slot]])
    early = 1 if select_first else 0

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            admin = session.get(User, world.admin_id)
            return block_driver(session, admin, world.profile_ids[slot], AdminDriverBlock(reason="fraud"))
        client = session.get(User, world.client_id)
        return select_driver_for_order(session, client, order_id, SelectDriverRequest(bid_id=bid_id))

    return order_id, slot, early, run_concurrently(2, work, engine=pg_db.engine)


def blocked_driver_newly_assigned(pg_db: PgDatabase, order_id: int, block_value, select_value) -> bool:
    """The assignment committed although the block committed first (block saw no active order)."""
    if outcome(select_value) != "ok" or outcome(block_value) != "ok":
        return False
    with pg_db.session() as s:
        assigned = s.get(Order, order_id).assigned_driver_id is not None
    return assigned and block_value["active_orders_count"] == 0


def test_block_driver_vs_select_driver_never_assigns_blocked_driver(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    hold_inside(monkeypatch, order_service, "apply_order_commission")  # select: inside order/bid/user/profile locks
    hold_inside(monkeypatch, admin_driver_service, "write_audit_log")  # block: inside user/profile locks
    clock = lock_clock(USERS_LOCK)
    rounds = 6
    world = seed_world(pg_db, drivers=rounds)
    seen: set[str] = set()
    for round_no in range(rounds):
        clock.reset()
        order_id, slot, early, report = run_block_vs_select(pg_db, world, round_no, select_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)  # also proves no deadlock between the two lock paths
        clock.assert_waited(early=early, late=1 - early)
        block_value, select_value = report.results[0].value, report.results[1].value
        assert outcome(block_value) == "ok"
        assert not blocked_driver_newly_assigned(pg_db, order_id, block_value, select_value)
        with pg_db.session() as s:
            order = s.get(Order, order_id)
            assert s.get(User, world.driver_user_ids[slot]).status == "blocked"
            assert s.get(DriverProfile, world.profile_ids[slot]).verification_status == "blocked"
            if outcome(select_value) == "ok":
                seen.add("select_then_block")
                assert order.status == "accepted" and order.assigned_driver_id == world.profile_ids[slot]
                assert block_value["active_orders_count"] == 1 and block_value["warning"] is not None
            else:
                seen.add("block_first")
                assert outcome(select_value) == "DRIVER_NOT_APPROVED"
                assert order.status == "bidding" and order.assigned_driver_id is None
                assert s.scalar(select(Bid.status).where(Bid.order_id == order_id)) == "active"
    assert seen == {"select_then_block", "block_first"}


# ── F4: create_bid vs block_driver ───────────────────────────────────────────


def run_create_vs_block(pg_db: PgDatabase, world: World, round_no: int, *, create_first: bool, clock: LockClock | None = None):
    slot = round_no
    order_id = seed_order(pg_db, world, status="bidding", number=f"ORD-RACE-G-{round_no}")
    early = 0 if create_first else 1

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            user = session.get(User, world.driver_user_ids[slot])
            profile = session.get(DriverProfile, world.profile_ids[slot])
            return create_bid(session, user, profile, order_id, BidCreate(price=Decimal("61000")))
        admin = session.get(User, world.admin_id)
        return block_driver(session, admin, world.profile_ids[slot], AdminDriverBlock(reason="fraud"))

    return order_id, slot, early, run_concurrently(2, work, engine=pg_db.engine)


def test_create_bid_vs_block_driver_rechecks_eligibility_inside_locks(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    # create: stall after every check (locked re-check, visibility/route), right before the bid insert
    hold_inside(monkeypatch, driver_order_service, "ensure_order_visible", after=True)
    hold_inside(monkeypatch, admin_driver_service, "write_audit_log")  # block: inside user/profile locks
    clock = lock_clock(USERS_LOCK)
    rounds = 4
    world = seed_world(pg_db, drivers=rounds)
    seen: set[str] = set()
    for round_no in range(rounds):
        clock.reset()
        order_id, slot, early, report = run_create_vs_block(pg_db, world, round_no, create_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        create_value, block_value = report.results[0].value, report.results[1].value
        assert outcome(block_value) == "ok"
        with pg_db.session() as s:
            bids = list(s.scalars(select(Bid).where(Bid.order_id == order_id)))
            if outcome(create_value) == "ok":
                seen.add("create_then_block")
                assert [b.driver_id for b in bids] == [world.profile_ids[slot]]
                assert clock.commit_started[0] <= clock.acquired[1]  # the bid committed before block got the user lock
            else:
                seen.add("block_first")
                assert json.loads(create_value.body) == {"success": False, "error": {"code": "FORBIDDEN", "message": "Driver account must be active"}}
                assert bids == []
    assert seen == {"create_then_block", "block_first"}


# ── F1: FK key-share — no deadlock with inserts that reference the locked user ──


def seed_refresh_session(pg_db: PgDatabase, user_id: int) -> str:
    token = create_refresh_token(str(user_id))
    with pg_db.session() as s:
        create_refresh_session(s, s.get(User, user_id), token, verify_token(token))
        s.commit()
    return token


def run_refresh_vs_block(pg_db: PgDatabase, world: World, round_no: int, *, refresh_first: bool, clock: LockClock | None = None):
    slot = round_no
    token = seed_refresh_session(pg_db, world.driver_user_ids[slot])
    early = 1 if refresh_first else 0

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            admin = session.get(User, world.admin_id)
            return block_driver(session, admin, world.profile_ids[slot], AdminDriverBlock(reason="fraud"))
        return refresh_tokens(session, token)

    return slot, early, run_concurrently(2, work, engine=pg_db.engine)


def live_sessions(pg_db: PgDatabase, user_id: int) -> int:
    with pg_db.session() as s:
        return s.scalar(
            select(func.count(RefreshSession.id)).where(RefreshSession.user_id == user_id, RefreshSession.is_revoked == False)  # noqa: E712
        )


def test_token_refresh_vs_block_driver_serializes_and_leaves_no_live_session(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    """N-B/N-D (also F1 (a): no deadlock). Refresh takes users FOR SHARE, block_driver
    FOR NO KEY UPDATE: they serialize, so a blocked driver never keeps a live session."""
    hold_inside(monkeypatch, auth_service, "write_audit_log")  # refresh: after the users/session locks
    hold_inside(monkeypatch, admin_driver_service, "write_audit_log")  # block: after revoking sessions
    clock = lock_clock(USERS_WRITE_OR_SHARE_LOCK)
    rounds = 4
    world = seed_world(pg_db, drivers=rounds)
    seen: set[str] = set()
    for round_no in range(rounds):
        clock.reset()
        slot, early, report = run_refresh_vs_block(pg_db, world, round_no, refresh_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        block_value, refresh_value = report.results[0].value, report.results[1].value
        assert outcome(block_value) == "ok"
        assert live_sessions(pg_db, world.driver_user_ids[slot]) == 0
        with pg_db.session() as s:
            assert s.get(User, world.driver_user_ids[slot]).status == "blocked"
        if outcome(refresh_value) == "ok":
            seen.add("refresh_then_block")
            assert block_value["revoked_refresh_sessions_count"] == 1  # the session this refresh created
        else:
            seen.add("block_first")
            assert json.loads(refresh_value.body) == {"success": False, "error": {"code": "USER_BLOCKED", "message": "User account is blocked"}}
    assert seen == {"refresh_then_block", "block_first"}


def run_deletion_vs(pg_db: PgDatabase, world: World, round_no: int, other: str, *, deletion_first: bool, clock: LockClock | None = None):
    client_id = seed_client(pg_db, round_no)
    order_id = seed_order(pg_db, world, status="confirmed", number=f"ORD-RACE-H-{other}-{round_no}", client_id=client_id, driver_slot=0)
    early = 0 if deletion_first else 1

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            return delete_own_account(session, session.get(User, client_id))
        if other == "cancel":
            admin = session.get(User, world.admin_id)
            return cancel_order_manually(session, admin, order_id, AdminOrderCancel(reason="Refund agreed"))
        return create_order_rating(session, session.get(User, client_id), order_id, ClientOrderRatingCreate(rating=5, comment=None))

    return client_id, order_id, early, run_concurrently(2, work, engine=pg_db.engine)


def assert_deleted_client(pg_db: PgDatabase, client_id: int, order_id: int) -> None:
    with pg_db.session() as s:
        user = s.get(User, client_id)
        order = s.get(Order, order_id)
        assert user.status == "deleted" and user.phone == f"deleted-{client_id}"
        assert order.sender_phone == "" and order.receiver_phone == ""


def test_account_deletion_vs_admin_cancel_no_deadlock(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    """(b) deletion rewrites the client's orders; admin cancel holds the order and
    inserts notifications referencing the client."""
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")  # deletion: inside order/user locks
    hold_inside(monkeypatch, admin_order_service, "active_dispute_error")  # cancel: inside the order lock
    clock = lock_clock(ORDERS_LOCK)
    world = seed_world(pg_db, drivers=1)
    for round_no in range(4):
        clock.reset()
        client_id, order_id, early, report = run_deletion_vs(pg_db, world, round_no, "cancel", deletion_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        deletion_value, cancel_value = report.results[0].value, report.results[1].value
        assert deletion_value["deleted"] is True
        assert outcome(cancel_value) == "ok"
        assert_deleted_client(pg_db, client_id, order_id)
        with pg_db.session() as s:
            assert s.get(Order, order_id).status == "cancelled"


def test_account_deletion_vs_rating_no_deadlock(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")
    hold_inside(monkeypatch, order_service, "recalculate_driver_rating")  # rating: after the rating insert, inside the order lock
    clock = lock_clock(ORDERS_LOCK)
    world = seed_world(pg_db, drivers=1)
    for round_no in range(4):
        clock.reset()
        client_id, order_id, early, report = run_deletion_vs(pg_db, world, round_no, "rating", deletion_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        deletion_value, rating_value = report.results[0].value, report.results[1].value
        assert deletion_value["deleted"] is True
        assert outcome(rating_value) == "ok"
        assert_deleted_client(pg_db, client_id, order_id)
        with pg_db.session() as s:
            assert s.scalar(select(func.count(Rating.id)).where(Rating.order_id == order_id)) == 1


# ── negative controls: the same scenarios without the locks must fail ───────


def plain_order(db, order_id):
    return db.get(Order, order_id)


def plain_order_bids(db, order_id, *, active_only=False):
    stmt = select(Bid).where(Bid.order_id == order_id)
    if active_only:
        stmt = stmt.where(Bid.status == "active")
    return list(db.scalars(stmt.order_by(Bid.id)))


def plain_bid(db, bid_id):
    return db.get(Bid, bid_id)


def plain_driver(db, profile_id):
    profile = db.get(DriverProfile, profile_id)
    return profile, db.get(User, profile.user_id) if profile else None


def for_update_driver(db, profile_id):
    """The pre-F1 lock: plain FOR UPDATE on users and driver_profiles."""
    profile = db.get(DriverProfile, profile_id)
    user = db.scalar(select(User).where(User.id == profile.user_id).with_for_update().execution_options(populate_existing=True))
    profile = db.scalar(select(DriverProfile).where(DriverProfile.id == profile_id).with_for_update().execution_options(populate_existing=True))
    return profile, user


def test_negative_control_cancel_without_order_lock_leaves_active_bids(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver_order_service, "lock_order", plain_order)
    monkeypatch.setattr(order_service, "lock_order_row", plain_order)
    hold_inside(monkeypatch, driver_order_service, "ensure_order_visible")  # creators read 'bidding', then stall
    world = seed_world(pg_db, drivers=5)
    violations = 0
    for round_no in range(3):
        order_id, report = run_cancel_vs_creates(pg_db, world, round_no, updaters=0, creators=5)
        assert_no_worker_crashed(report)
        with pg_db.session() as s:
            cancelled = s.get(Order, order_id).status == "cancelled"
            active = s.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id, Bid.status == "active"))
        if cancelled and active:
            violations += 1
    assert violations >= 1, "race test (c) would not detect a missing order lock"


def test_negative_control_cancel_vs_select_without_locks_breaks_serial_history(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order_service, "lock_order_row", plain_order)
    monkeypatch.setattr(order_service, "lock_order_bids", plain_order_bids)
    hold_inside(monkeypatch, order_service, "write_status_history")
    world = seed_world(pg_db, drivers=3)
    serial = ([("bidding", "accepted"), ("accepted", "cancelled")], [("bidding", "cancelled")])
    violations = 0
    for round_no in range(2):
        order_id, _bid_ids, _early, report = run_cancel_vs_select(pg_db, world, round_no, select_first=round_no % 2 == 0)
        if report.failures or cancel_select_history(pg_db, order_id) not in serial:
            violations += 1
    assert violations >= 1, "race test (a) would not detect missing order/bid locks"


def test_negative_control_update_bid_vs_select_without_locks_desyncs_price(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver_order_service, "lock_order", plain_order)
    monkeypatch.setattr(driver_order_service, "lock_bid_row", plain_bid)
    monkeypatch.setattr(driver_order_service, "lock_driver_user_and_profile", plain_driver)
    hold_inside(monkeypatch, driver_order_service, "review_pairing_allowed")  # update checked 'active', then stalls
    world = seed_world(pg_db, drivers=2)
    violations = 0
    for round_no in range(2):
        order_id, _bid_ids, _early, report = run_update_vs_select(pg_db, world, round_no, update_first=True)
        if report.failures or not accepted_price_matches_final(pg_db, order_id):
            violations += 1
    assert violations >= 1, "race test (b) would not detect missing order/bid locks in update_bid"


def test_negative_control_publish_without_order_lock_publishes_twice(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order_service, "lock_order_row", plain_order)
    hold_inside(monkeypatch, order_service, "validate_order_complete", 0.2)  # every worker saw 'draft', then stalls
    world = seed_world(pg_db, drivers=0)  # no drivers: no offer unique-constraint noise
    order_id, report = run_publishes(pg_db, world, "ORD-RACE-E-NEG")
    assert report.values().count("ok") > 1 or published_count(pg_db, order_id) > 1, "race test (d) would not detect a missing order lock"


def test_negative_control_select_without_driver_lock_assigns_blocked_driver(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order_service, "lock_driver_user_and_profile", plain_driver)
    hold_inside(monkeypatch, order_service, "apply_order_commission")  # select checked eligibility, then stalls
    rounds = 3
    world = seed_world(pg_db, drivers=rounds)
    violations = 0
    for round_no in range(rounds):
        order_id, _slot, _early, report = run_block_vs_select(pg_db, world, round_no, select_first=True)
        assert_no_worker_crashed(report)
        if blocked_driver_newly_assigned(pg_db, order_id, report.results[0].value, report.results[1].value):
            violations += 1
    assert violations >= 1, "race test (e) would not detect a missing driver lock"


def test_negative_control_create_bid_without_driver_recheck_accepts_blocked_driver(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    monkeypatch.setattr(driver_order_service, "lock_driver_user_and_profile", plain_driver)
    # create passed eligibility and the route check, then stalls before the insert
    hold_inside(monkeypatch, driver_order_service, "ensure_order_visible", after=True)
    clock = lock_clock(USERS_LOCK)
    rounds = 2
    world = seed_world(pg_db, drivers=rounds)
    violations = 0
    for round_no in range(rounds):
        clock.reset()
        order_id, slot, _early, report = run_create_vs_block(pg_db, world, round_no, create_first=True, clock=clock)
        assert_no_worker_crashed(report)
        create_ok = outcome(report.results[0].value) == "ok"
        # Violation: the bid committed after the block had already committed.
        if create_ok and clock.commit_started[1] < clock.commit_started[0]:
            violations += 1
    assert violations >= 1, "F4 test would not detect a missing locked eligibility re-check"


def test_negative_control_deletion_without_orders_first_deadlocks_vs_cancel(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deletion without the orders-first lock (users FOR UPDATE, then order rewrite)."""
    monkeypatch.setattr(account_deletion_service, "lock_orders_for_account", lambda db, user: [])
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")  # deletion holds the user, cancel arrives
    world = seed_world(pg_db, drivers=1)
    deadlocks = 0
    for round_no in range(2):
        _client_id, _order_id, _early, report = run_deletion_vs(pg_db, world, round_no, "cancel", deletion_first=True)
        deadlocks += sum(1 for r in report.failures if is_deadlock(r.error))
    assert deadlocks >= 1, "F1 test (b) would not detect the users FOR UPDATE deadlock"


def test_negative_control_refresh_with_key_share_leaves_live_session_after_block(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wave-1.5 refresh lock (FOR KEY SHARE) does not serialize with block_driver."""
    monkeypatch.setattr(auth_service, "lock_user_share", lock_user_key_share)
    hold_inside(monkeypatch, auth_service, "write_audit_log")  # refresh passed its checks, then stalls
    rounds = 2
    world = seed_world(pg_db, drivers=rounds)
    violations = 0
    for round_no in range(rounds):
        slot, _early, report = run_refresh_vs_block(pg_db, world, round_no, refresh_first=True)
        assert_no_worker_crashed(report)
        if outcome(report.results[0].value) == "ok" and live_sessions(pg_db, world.driver_user_ids[slot]) > 0:
            violations += 1
    assert violations >= 1, "N-B test would not detect a refresh that does not serialize with block_driver"


# ── N-A: unique-column updates take FOR UPDATE up front; self-service writes lock users first ──


def passport_payload(user_id: int, round_no: int) -> DriverDocumentCreate:
    return DriverDocumentCreate(document_type="passport", file_url=f"/uploads/passport/2026/09/u{user_id}/p{round_no}.jpg")


def hold_in_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hook: document upload's attachment resolver runs inside the self-service locks.
    It returns the reference unchanged; file storage is out of scope for these tests."""

    def resolve(value, **kwargs):
        time.sleep(HOLD_S)
        return value

    monkeypatch.setattr(driver_service, "resolve_attachment", resolve)


def run_vehicle_vs_document(pg_db: PgDatabase, world: World, round_no: int, *, vehicle_first: bool, clock: LockClock | None = None):
    slot = round_no
    with pg_db.session() as s:
        s.get(DriverProfile, world.profile_ids[slot]).verification_status = "rejected"  # upload moves it to pending
        s.commit()
    new_plate = f"01B{round_no:03d}BB"
    early = 0 if vehicle_first else 1

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            admin = session.get(User, world.admin_id)
            return update_driver_vehicle(session, admin, world.profile_ids[slot], AdminDriverVehicleUpdate(plate_number=new_plate))
        user = session.get(User, world.driver_user_ids[slot])
        profile = session.get(DriverProfile, world.profile_ids[slot])
        return submit_driver_document(session, user, profile, passport_payload(user.id, round_no))

    return slot, new_plate, early, run_concurrently(2, work, engine=pg_db.engine)


def test_admin_vehicle_edit_vs_document_upload_no_deadlock(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:
    hold_inside(monkeypatch, admin_driver_service, "normalize_plate_number")  # vehicle: inside users/profile locks
    hold_in_attachment(monkeypatch)
    clock = lock_clock(PROFILE_LOCK)
    rounds = 4
    world = seed_world(pg_db, drivers=rounds)
    for round_no in range(rounds):
        clock.reset()
        slot, new_plate, early, report = run_vehicle_vs_document(pg_db, world, round_no, vehicle_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        assert outcome(report.results[0].value) == "ok"
        assert outcome(report.results[1].value) == "ok"
        with pg_db.session() as s:
            profile = s.get(DriverProfile, world.profile_ids[slot])
            assert profile.plate_number_normalized == normalize_plate_number_key(new_plate)
            assert profile.verification_status == "pending"
            assert s.scalar(select(func.count(DriverDocument.id)).where(DriverDocument.driver_id == profile.id)) == 1


def run_deletion_vs_driver_write(pg_db: PgDatabase, world: World, round_no: int, write: str, *, deletion_first: bool, clock: LockClock | None = None):
    slot = round_no
    with pg_db.session() as s:
        route_id = s.scalar(select(DriverRoute.id).where(DriverRoute.driver_id == world.profile_ids[slot]))
    early = 0 if deletion_first else 1

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        user = session.get(User, world.driver_user_ids[slot])
        if index == 0:
            return delete_own_account(session, user)
        profile = session.get(DriverProfile, world.profile_ids[slot])
        if write == "document":
            return submit_driver_document(session, user, profile, passport_payload(user.id, round_no))
        return update_route_status(session, user, profile, route_id, DriverRouteStatusUpdate(status="unavailable"))

    return slot, early, run_concurrently(2, work, engine=pg_db.engine)


def assert_driver_deleted_cleanly(pg_db: PgDatabase, world: World, slot: int) -> None:
    with pg_db.session() as s:
        profile_id = world.profile_ids[slot]
        assert s.get(User, world.driver_user_ids[slot]).status == "deleted"
        assert s.get(DriverProfile, profile_id).plate_number is None
        assert s.scalar(select(func.count(DriverDocument.id)).where(DriverDocument.driver_id == profile_id)) == 0
        assert s.scalar(select(func.count(DriverRoute.id)).where(DriverRoute.driver_id == profile_id)) == 0


@pytest.mark.parametrize("write", ["document", "route"])
def test_account_deletion_vs_driver_self_service_write_no_deadlock(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock, write: str) -> None:
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")  # deletion: inside orders/users/profile locks
    if write == "document":
        hold_in_attachment(monkeypatch)
    else:
        hold_inside(monkeypatch, driver_service, "write_audit_log")  # route: after the route row update
    clock = lock_clock(USERS_ANY_LOCK)
    rounds = 4
    world = seed_world(pg_db, drivers=rounds)
    seen: set[str] = set()
    for round_no in range(rounds):
        clock.reset()
        slot, early, report = run_deletion_vs_driver_write(pg_db, world, round_no, write, deletion_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        deletion_value, write_value = report.results[0].value, report.results[1].value
        assert deletion_value["deleted"] is True
        assert_driver_deleted_cleanly(pg_db, world, slot)  # a write that won first is purged by the deletion
        if outcome(write_value) == "ok":
            seen.add("write_then_delete")
        else:
            seen.add("delete_first")
            assert json.loads(write_value.body) == {"success": False, "error": {"code": "FORBIDDEN", "message": "User account is not active"}}
    assert seen == {"write_then_delete", "delete_first"}


def test_negative_control_old_lock_modes_deadlock_deletion_vs_route_update(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wave-1.5 modes: deletion locks users FOR NO KEY UPDATE (upgraded to FOR UPDATE by
    the phone tombstone at flush) and the route update takes no users-first lock.
    The route update holds its route row, then inserts an audit row referencing
    the user; deletion holds the upgraded users lock and deletes that route: 40P01."""
    monkeypatch.setattr(account_deletion_service, "lock_user_for_key_change", lock_user_row)
    monkeypatch.setattr(driver_service, "lock_driver_self_service", lambda db, user, profile, **kwargs: None)
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")
    hold_inside(monkeypatch, driver_service, "write_audit_log")
    rounds = 2
    world = seed_world(pg_db, drivers=rounds)
    deadlocks = 0
    for round_no in range(rounds):
        _slot, _early, report = run_deletion_vs_driver_write(pg_db, world, round_no, "route", deletion_first=True)
        deadlocks += sum(1 for r in report.failures if is_deadlock(r.error))
    assert deadlocks >= 1, "N-A test would not detect the lock-upgrade deadlock"


# ── L1: admin block vs account deletion ──────────────────────────────────────


def run_deletion_vs_admin_block(pg_db: PgDatabase, world: World, round_no: int, target: str, *, deletion_first: bool, clock: LockClock | None = None):
    user_id = seed_client(pg_db, 100 + round_no) if target == "client" else world.driver_user_ids[round_no]
    early = 0 if deletion_first else 1

    def work(index: int, session: Session):
        if clock is not None:
            clock.bind(index, session)
        staggered(index, early)
        if index == 0:
            return delete_own_account(session, session.get(User, user_id))
        admin = session.get(User, world.admin_id)
        if target == "client":
            return block_admin_client(user_id, {"reason": "fraud"}, current_user=admin, db=session)
        return block_driver(session, admin, world.profile_ids[round_no], AdminDriverBlock(reason="fraud"))

    return user_id, early, run_concurrently(2, work, engine=pg_db.engine)


@pytest.mark.parametrize("target", ["client", "driver"])
def test_admin_block_vs_account_deletion_never_resurrects_deleted_user(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, lock_clock, target: str) -> None:
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")  # deletion: inside orders/users/profile locks
    hold_inside(monkeypatch, admin_clients if target == "client" else admin_driver_service, "write_audit_log")  # block: inside the users lock
    clock = lock_clock(USERS_ANY_LOCK)
    rounds = 4
    world = seed_world(pg_db, drivers=rounds)
    not_found = {"code": "CLIENT_NOT_FOUND", "message": "Client not found"} if target == "client" else {"code": "NOT_FOUND", "message": "Driver not found"}
    seen: set[str] = set()
    for round_no in range(rounds):
        clock.reset()
        user_id, early, report = run_deletion_vs_admin_block(pg_db, world, round_no, target, deletion_first=round_no % 2 == 0, clock=clock)

        assert_no_worker_crashed(report)
        clock.assert_waited(early=early, late=1 - early)
        deletion_value, block_value = report.results[0].value, report.results[1].value
        assert deletion_value["deleted"] is True
        with pg_db.session() as s:
            assert s.get(User, user_id).status == "deleted"
        if outcome(block_value) == "ok":
            seen.add("block_then_delete")
        else:
            seen.add("delete_first")
            assert json.loads(block_value.body) == {"success": False, "error": not_found}
    assert seen == {"block_then_delete", "delete_first"}


def test_negative_control_client_block_without_users_lock_resurrects_deleted_client(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-L1 block: plain read, then write status over a deletion that committed meanwhile."""
    monkeypatch.setattr(admin_clients, "lock_user_row", lambda db, user_id, mode="no_key_update": db.get(User, user_id))
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")
    hold_inside(monkeypatch, admin_clients, "write_audit_log")  # block read 'active', then stalls
    world = seed_world(pg_db, drivers=0)
    violations = 0
    for round_no in range(2):
        user_id, _early, report = run_deletion_vs_admin_block(pg_db, world, round_no, "client", deletion_first=True)
        assert_no_worker_crashed(report)
        with pg_db.session() as s:
            if s.get(User, user_id).status != "deleted":
                violations += 1
    assert violations >= 1, "L1 test would not detect a block overwriting a deleted client"
