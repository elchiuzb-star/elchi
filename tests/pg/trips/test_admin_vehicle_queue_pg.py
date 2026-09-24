"""T3a on PostgreSQL: the staff vehicle queue filters by status, pages by (created_at, id) and is capability-gated.

The HTTP contract (cursor binding, DTO shape) is in ``tests/modules/trips/test_admin_vehicle_queue.py``.
"""

from __future__ import annotations

import pytest

from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.trips import service as trips_service
from app.modules.trips.views import admin_vehicle_dtos
from tests.pg.identity.a1_world import World, make_vehicle

pytestmark = pytest.mark.pg


def _ids(rows) -> list[str]:  # noqa: ANN001
    return [trips_service.vehicle_public_id(row) for row in rows]


def test_pending_queue_is_oldest_first_and_pages_without_gaps(world: World) -> None:
    pending = [make_vehicle(world, world.driver_id, f"01Q{n}00QQ", approve=False) for n in range(3)]
    approved = make_vehicle(world, world.driver2_id, "01Q900QQ")
    with world.db.session() as s:
        first = trips_service.list_vehicles_for_review(s, actor_user_id=world.admin_id, statuses=["pending"], limit=2)
        assert _ids(first) == pending[:2]
        after = (first[-1].created_at, first[-1].id)
        rest = trips_service.list_vehicles_for_review(
            s, actor_user_id=world.admin_id, statuses=["pending"], after=after, limit=2
        )
        assert _ids(rest) == pending[2:]
        only_approved = trips_service.list_vehicles_for_review(s, actor_user_id=world.admin_id, statuses=["approved"])
        assert _ids(only_approved) == [approved]
        everything = trips_service.list_vehicles_for_review(s, actor_user_id=world.admin_id)
        assert set(_ids(everything)) == set(pending) | {approved}


def test_a_decision_moves_the_vehicle_out_of_the_pending_queue(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01Q300QQ", approve=False)
    with world.db.session() as s:
        trips_service.verify_vehicle(
            s, vehicle_public_id=vehicle, actor_user_id=world.admin_id, expected_version=1, decision="approve", reason=None
        )
        s.commit()
    with world.db.session() as s:
        assert trips_service.list_vehicles_for_review(s, actor_user_id=world.admin_id, statuses=["pending"]) == []


def test_marketplace_accounts_cannot_read_the_queue(world: World) -> None:
    make_vehicle(world, world.driver_id, "01Q400QQ", approve=False)
    with world.db.session() as s:
        for user_id in (world.client_id, world.driver_id):
            with pytest.raises(DomainError) as info:
                trips_service.list_vehicles_for_review(s, actor_user_id=user_id)
            assert info.value.code is ErrorCode.CAPABILITY_REQUIRED


def test_owner_block_reflects_an_eligibility_block_and_its_version(world: World) -> None:
    make_vehicle(world, world.driver_id, "01Q500QQ", approve=False)
    with world.db.session() as s:
        before = admin_vehicle_dtos(s, trips_service.list_vehicles_for_review(s, actor_user_id=world.admin_id))[0].owner
        assert before.is_driver and before.blocked_reason is None
        identity_service.set_driver_eligibility(
            s,
            driver_user_id=world.driver_id,
            actor_user_id=world.admin_id,
            action="block",
            expected_version=before.eligibility_version,
            reason="Hujjat tekshirilmoqda",
        )
        s.commit()
    with world.db.session() as s:
        after = admin_vehicle_dtos(s, trips_service.list_vehicles_for_review(s, actor_user_id=world.admin_id))[0].owner
        assert after.eligible is False and after.blocked_reason == "Hujjat tekshirilmoqda"
        assert "eligibility_blocked" in after.reasons
        assert after.eligibility_version == (before.eligibility_version or 0) + 1
