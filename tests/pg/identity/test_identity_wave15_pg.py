"""Wave 1.5 identity fixes on PostgreSQL: Q3 on users.role (BR #13), lift_reason rules (BR #12),
FOR NO KEY UPDATE user locks coexisting with foreign-key inserts."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.modules.identity import service as identity_service
from tests.pg.identity.a1_world import World, add_user, run_in_thread, wait_for_lock_waiters

pytestmark = pytest.mark.pg


@pytest.mark.parametrize(
    ("old", "new", "allowed"),
    [
        ("operator", "admin", True),
        ("admin", "finance", True),
        ("client", "driver", True),
        ("client", "operator", False),
        ("finance", "driver", False),
    ],
)
def test_users_role_update_enforces_q3(world: World, old: str, new: str, allowed: bool) -> None:
    with world.db.session() as s:
        user_id = add_user(s, f"+99890777{len(old)}{len(new)}0", old)
        s.commit()
        statement = text("UPDATE users SET role = :r WHERE id = :u")
        if allowed:
            s.execute(statement, {"r": new, "u": user_id})
            s.commit()
        else:
            with pytest.raises(IntegrityError, match="ck_users_role_staff_marketplace_separation|cannot be combined"):
                s.execute(statement, {"r": new, "u": user_id})


def test_users_role_trigger_counts_activated_roles(world: World) -> None:
    with world.db.session() as s:
        identity_service.activate_role(s, world.driver_id, "client")
        s.commit()
        s.execute(text("UPDATE users SET role = 'client' WHERE id = :u"), {"u": world.driver_id})  # still marketplace
        s.commit()
        with pytest.raises(IntegrityError, match="cannot be combined"):
            s.execute(text("UPDATE users SET role = 'admin' WHERE id = :u"), {"u": world.driver_id})


def test_lift_reason_only_when_lifting(world: World) -> None:
    insert = text("INSERT INTO driver_eligibility_blocks (driver_user_id, reason, blocked_by) VALUES (:d, 'r', :a) RETURNING id")
    with world.db.session() as s:
        block_id = s.execute(insert, {"d": world.driver_id, "a": world.admin_id}).scalar_one()
        s.commit()
    with world.db.session() as s, pytest.raises(DBAPIError, match="immutable"):
        s.execute(text("UPDATE driver_eligibility_blocks SET lift_reason = 'sneaky' WHERE id = :b"), {"b": block_id})
    with world.db.session() as s, pytest.raises(IntegrityError, match="ck_driver_eligibility_blocks_lift_reason"):
        s.execute(
            text("UPDATE driver_eligibility_blocks SET lifted_at = now(), lifted_by = :a WHERE id = :b"),
            {"a": world.admin_id, "b": block_id},
        )
    with world.db.session() as s:
        s.execute(
            text("UPDATE driver_eligibility_blocks SET lifted_at = now(), lifted_by = :a, lift_reason = 'ok' WHERE id = :b"),
            {"a": world.admin_id, "b": block_id},
        )
        s.commit()


def test_users_lock_does_not_block_foreign_key_inserts(world: World) -> None:
    """FOR NO KEY UPDATE (eligibility lock) is compatible with the FOR KEY SHARE an FK insert takes."""
    holder = world.db.session()
    try:
        identity_service.lock_user_eligibility(holder, [world.client_id])

        def insert_referencing_row() -> int:
            with world.db.session() as s:
                row_id = s.execute(
                    text("INSERT INTO audit_logs (actor_id, entity_type, action) VALUES (:u, 'probe', 'fk') RETURNING id"),
                    {"u": world.client_id},
                ).scalar_one()
                s.commit()
                return row_id

        thread, outcome = run_in_thread(insert_referencing_row)
        thread.join(timeout=10)
        assert not thread.is_alive() and "value" in outcome, outcome  # finished while the lock was held
    finally:
        holder.rollback()
        holder.close()


def test_eligibility_lock_still_excludes_share_readers(world: World) -> None:
    """AC41 serialisation holds: a FOR SHARE reader (proposal submit) waits for the NO KEY UPDATE holder."""
    holder = world.db.session()
    try:
        identity_service.lock_user_eligibility(holder, [world.driver_id])

        def reader() -> list[int]:
            with world.db.session() as s:
                return identity_service.lock_user_eligibility(s, [world.driver_id], mode="share")

        thread, outcome = run_in_thread(reader)
        wait_for_lock_waiters(world, 1)
        assert "value" not in outcome
        holder.commit()
    finally:
        holder.close()
    thread.join(timeout=10)
    assert outcome.get("value") == [world.driver_id]
