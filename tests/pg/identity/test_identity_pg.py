"""Identity on real PostgreSQL 16: user_roles backfill (idempotent), Q3 trigger, eligibility blocks (D16, AC41)."""

from __future__ import annotations

import importlib.util
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import OBLIGATION_CAPABILITIES, Capability, Role, role_combination_allowed
from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from tests.pg.conftest import REPO_ROOT, PgDatabase, run_alembic, script_heads
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import World, add_user, make_trip, make_vehicle, passenger_offer

pytestmark = pytest.mark.pg

MIGRATION_0032 = Path(REPO_ROOT) / "alembic" / "versions" / "20260913_0032_identity_roles_eligibility.py"


def load_migration_0032():  # noqa: ANN201
    spec = importlib.util.spec_from_file_location("a1_migration_0032", MIGRATION_0032)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def role_rows(session: Session, user_id: int) -> list[tuple[str, str]]:
    return session.execute(
        text("SELECT role, status FROM user_roles WHERE user_id = :u ORDER BY role"), {"u": user_id}
    ).all()


# --- migration 0032 ------------------------------------------------------------------------------------


def test_user_roles_backfill_is_idempotent(world: World) -> None:
    backfill = load_migration_0032().BACKFILL_USER_ROLES_SQL
    with world.db.session() as s:
        users = s.execute(text("SELECT id, role FROM users ORDER BY id")).all()
        s.execute(text(backfill))
        s.execute(text(backfill))
        s.commit()
        pairs = s.execute(text("SELECT user_id, role, count(*) FROM user_roles GROUP BY user_id, role ORDER BY user_id")).all()
        assert [(u, r) for u, r, _ in pairs] == [(u.id, u.role) for u in users]
        assert all(count == 1 for _, _, count in pairs)

        s.execute(text("UPDATE user_roles SET status = 'revoked' WHERE user_id = :u"), {"u": world.client_id})
        s.execute(text(backfill))
        s.commit()
        assert role_rows(s, world.client_id) == [("client", "revoked")]  # never revived, never duplicated


def test_users_public_id_backfilled_unique_and_defaulted_for_legacy_inserts(world: World) -> None:
    with world.db.session() as s:
        assert s.execute(text("SELECT count(*) FROM users WHERE public_id IS NULL")).scalar_one() == 0
        assert s.execute(text("SELECT count(DISTINCT public_id) = count(*) FROM users")).scalar_one()
        assert identity_service.user_public_id(s, world.client_id).startswith("usr_")


def test_rerunning_a1_migration_bodies_is_a_noop(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        user_id = conn.execute(
            text("INSERT INTO users (phone, role, status, is_phone_verified) VALUES ('+998901112233', 'driver', 'active', true) RETURNING id")
        ).scalar_one()
        conn.execute(text(load_migration_0032().BACKFILL_USER_ROLES_SQL))
        before = conn.execute(text("SELECT count(*) FROM user_roles")).scalar_one()
    head = script_heads()[0]
    for down, up in (("20260913_0031", "20260913_0032"), ("20260913_0036", "20260913_0040")):
        stamped = run_alembic(pg_db.url, "stamp", down)
        assert stamped.returncode == 0, stamped.stderr
        upgraded = run_alembic(pg_db.url, "upgrade", up)
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    assert run_alembic(pg_db.url, "stamp", head).returncode == 0
    second = run_alembic(pg_db.url, "upgrade", "head")
    assert second.returncode == 0 and "Running upgrade" not in second.stderr
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM user_roles")).scalar_one() == before
        assert conn.execute(text("SELECT role FROM user_roles WHERE user_id = :u"), {"u": user_id}).scalar_one() == "driver"
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == head


# --- Q3 -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("primary", "extra", "allowed"),
    [
        ("client", "operator", False),
        ("admin", "driver", False),
        ("finance", "client", False),
        ("client", "driver", True),
        ("admin", "finance", True),
    ],
)
def test_q3_trigger_on_user_roles(world: World, primary: str, extra: str, allowed: bool) -> None:
    with world.db.session() as s:
        user_id = add_user(s, f"+99890555{len(primary)}{len(extra)}01", primary)
        s.commit()
        statement = text("INSERT INTO user_roles (user_id, role) VALUES (:u, :r)")
        if allowed:
            s.execute(statement, {"u": user_id, "r": extra})
            s.commit()
        else:
            with pytest.raises(IntegrityError, match="ck_user_roles_staff_marketplace_separation|cannot be combined"):
                s.execute(statement, {"u": user_id, "r": extra})


def test_q3_trigger_serialises_concurrent_role_writes(world: World) -> None:
    """Each insert alone is valid for a user whose primary role is neither family; together they are not."""
    with world.db.session() as s:
        user_id = add_user(s, "+998905550099", "applicant")  # legacy users.role has no CHECK
        s.commit()
    roles = ["operator", "client"] * 10

    def insert(worker: int, session: Session) -> str:
        session.execute(
            text("INSERT INTO user_roles (user_id, role) VALUES (:u, :r) ON CONFLICT (user_id, role) DO NOTHING"),
            {"u": user_id, "r": roles[worker]},
        )
        session.commit()
        return roles[worker]

    report = run_concurrently(20, insert, engine=world.db.engine)
    assert report.successes and report.failures
    assert all(isinstance(r.error, IntegrityError) for r in report.failures)
    with world.db.session() as s:
        stored = [role for role, _ in role_rows(s, user_id)]
    assert len(stored) == 1 and role_combination_allowed(stored)


def test_activate_role_service(world: World) -> None:
    with world.db.session() as s:
        caps = identity_service.activate_role(s, world.client_id, "driver", granted_by=world.client_id)
        assert {Role.CLIENT, Role.DRIVER} <= caps.roles
        assert not caps.driver_eligible  # no approved driver profile yet
        again = identity_service.activate_role(s, world.client_id, Role.DRIVER)
        assert again.roles == caps.roles
        s.commit()
        assert role_rows(s, world.client_id) == [("driver", "active")]
        for user_id, role, code in (
            (world.admin_id, "client", ErrorCode.ROLE_COMBINATION_FORBIDDEN),
            (world.client_id, "operator", ErrorCode.VALIDATION_ERROR),
        ):
            with pytest.raises(DomainError) as info:
                identity_service.activate_role(s, user_id, role)
            assert info.value.code is code
            s.rollback()


# --- eligibility blocks (D16, AC41) -----------------------------------------------------------------------


def test_block_removes_new_business_only_and_is_versioned(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01D400DD")
    _, trip_public_id = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with world.db.session() as s:
        assert identity_service.get_driver_eligibility(s, world.driver_id).version == 1
        state = identity_service.block_driver_eligibility(
            s, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="document review"
        )
        assert (state.eligible, state.blocked_reason, state.version) == (False, "document review", 2)
        assert state.active_trip_public_ids == (trip_public_id,)
        caps = identity_service.get_capabilities(s, world.driver_id)
        assert caps.capabilities == OBLIGATION_CAPABILITIES  # trip.operate + tracking.publish stay (D16)
        s.commit()
        assert s.execute(text("SELECT status FROM users WHERE id = :u"), {"u": world.driver_id}).scalar_one() == "active"

    with world.db.session() as s:
        for actor, version, code in (
            (world.admin_id, 1, ErrorCode.VERSION_CONFLICT),
            (world.admin_id, 2, ErrorCode.INVALID_STATE_TRANSITION),
            (world.client_id, 2, ErrorCode.CAPABILITY_REQUIRED),
        ):
            with pytest.raises(DomainError) as info:
                identity_service.block_driver_eligibility(
                    s, driver_user_id=world.driver_id, actor_user_id=actor, expected_version=version, reason="again"
                )
            assert info.value.code is code
            s.rollback()
        state = identity_service.unblock_driver_eligibility(
            s, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=2, reason="documents ok"
        )
        assert (state.eligible, state.version) == (True, 3)
        assert Capability.TRIP_CREATE in identity_service.get_capabilities(s, world.driver_id).capabilities
        s.commit()
        assert s.execute(text("SELECT count(*) FROM audit_logs WHERE entity_type = 'driver_eligibility'")).scalar_one() == 2


def test_blocks_partial_unique_and_immutability(world: World) -> None:
    insert = text("INSERT INTO driver_eligibility_blocks (driver_user_id, reason, blocked_by) VALUES (:d, 'r', :a) RETURNING id")
    with world.db.session() as s:
        block_id = s.execute(insert, {"d": world.driver_id, "a": world.admin_id}).scalar_one()
        s.commit()
        with pytest.raises(IntegrityError, match="uq_driver_eligibility_blocks_active"):
            s.execute(insert, {"d": world.driver_id, "a": world.admin_id})
    for statement in (
        "UPDATE driver_eligibility_blocks SET reason = 'rewritten' WHERE id = :b",
        "DELETE FROM driver_eligibility_blocks WHERE id = :b",
    ):
        with world.db.session() as s, pytest.raises(DBAPIError, match="immutable"):
            s.execute(text(statement), {"b": block_id})
    with world.db.session() as s:
        s.execute(
            text("UPDATE driver_eligibility_blocks SET lifted_at = now(), lifted_by = :a, lift_reason = 'ok' WHERE id = :b"),
            {"a": world.admin_id, "b": block_id},
        )
        s.execute(insert, {"d": world.driver_id, "a": world.admin_id})  # a new active block after lifting
        s.commit()
        with pytest.raises(DBAPIError, match="immutable"):
            s.execute(text("UPDATE driver_eligibility_blocks SET lift_reason = 'x' WHERE id = :b"), {"b": block_id})


def _draft_offers(world: World, count: int) -> list[str]:
    vehicle = make_vehicle(world, world.driver_id, "01E500EE")
    listing_ids = []
    for day in range(count):
        start = world.base_time + timedelta(days=day)
        _, trip_public_id = make_trip(world, world.driver_id, vehicle, start=start)
        with world.db.session() as s:
            listing = marketplace_service.create_listing(
                s, owner_user_id=world.driver_id, data=passenger_offer(world, trip_public_id, start=start)
            )
            listing_ids.append(marketplace_service.listing_public_id(listing))
            s.commit()
    return listing_ids


def _wait_for_lock_waiters(world: World, expected: int, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    with world.db.engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
            ).scalar_one()
            conn.rollback()  # fresh stats snapshot on the next poll
            if waiting >= expected:
                return
            time.sleep(0.05)
    raise AssertionError(f"expected {expected} sessions waiting on a lock")


def _publish_in_thread(world: World, listing_id: str, results: dict[str, object]) -> threading.Thread:
    def run() -> None:
        with world.db.session() as s:
            try:
                marketplace_service.publish_listing(s, listing_public_id=listing_id, actor_user_id=world.driver_id, expected_version=1)
                s.commit()
                results[listing_id] = "published"
            except DomainError as exc:
                s.rollback()
                results[listing_id] = exc.code
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion
                s.rollback()
                results[listing_id] = exc

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_ac41_block_first_then_waiting_publishes_see_it(world: World) -> None:
    listing_ids = _draft_offers(world, 4)
    blocker = world.db.session()
    try:
        identity_service.block_driver_eligibility(
            blocker, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="fraud review"
        )  # holds FOR UPDATE on the driver's users row
        results: dict[str, object] = {}
        threads = [_publish_in_thread(world, listing_id, results) for listing_id in listing_ids]
        _wait_for_lock_waiters(world, len(listing_ids))
        blocker.commit()
    finally:
        blocker.close()
    for thread in threads:
        thread.join(timeout=30)
    assert set(results.values()) == {ErrorCode.DRIVER_NOT_ELIGIBLE}, results
    with world.db.session() as s:
        assert s.execute(text("SELECT count(*) FROM listings WHERE status = 'published'")).scalar_one() == 0


def test_ac41_publish_first_then_block_waits(world: World) -> None:
    first, second = _draft_offers(world, 2)
    publisher = world.db.session()
    outcome: dict[str, object] = {}
    try:
        marketplace_service.publish_listing(publisher, listing_public_id=first, actor_user_id=world.driver_id, expected_version=1)

        def block() -> None:
            with world.db.session() as s:
                identity_service.block_driver_eligibility(
                    s, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="late block"
                )
                s.commit()
                outcome["blocked_at"] = time.monotonic()

        thread = threading.Thread(target=block)
        thread.start()
        _wait_for_lock_waiters(world, 1)
        outcome["published_at"] = time.monotonic()
        publisher.commit()
    finally:
        publisher.close()
    thread.join(timeout=30)
    assert outcome["blocked_at"] > outcome["published_at"]
    with world.db.session() as s:
        assert marketplace_service.get_listing_by_public_id(s, first).status == "published"  # committed before the block
        with pytest.raises(DomainError) as info:
            marketplace_service.publish_listing(s, listing_public_id=second, actor_user_id=world.driver_id, expected_version=1)
        assert info.value.code is ErrorCode.DRIVER_NOT_ELIGIBLE
