"""Wave 6 / §16: the three operator lists the spec names that had no queue yet.

"Operator paneli: koridor bo'yicha ochiq talab, **javobsiz e'lonlar**, **jo'nashga yaqin tasdiqlanmagan
haydovchilar**, **GPS eskirishi**, nizolar, top-up tekshiruvi, ..." - disputes, tickets, finance and the outbox
retry queue existed; these three did not, so an operator had no list to work from.

Each queue is a *read-only view* of rows the owning module already has: no new table, no new writer, and the
summary is operational language - "no GPS point for over 2 minutes", never "the driver is lying" (§9, §10.5).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.enums import OpsQueue
from app.modules.operations import service as operations_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    auth,
    bw,
    driver_trip,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def test_unanswered_listing_queue_lists_only_posts_without_an_offer(bw: BW) -> None:  # noqa: F811
    answered = publish_listing(bw, bw.w.client_id, passenger_request_body(bw))
    unanswered = publish_listing(bw, bw.w.client2_id, passenger_request_body(bw, origin="A", destination="C"))
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A620AA")
    propose(bw, answered, bw.w.driver_id, trip_public_id=trip_public, quantity=2)

    with bw.db.session() as session:
        # the listing departs inside the queue horizon
        session.execute(
            text("UPDATE listings SET departure_window_start = :start, departure_window_end = :end"),
            {"start": bw.base + timedelta(hours=3), "end": bw.base + timedelta(hours=4)},
        )
        session.commit()

    with bw.db.session() as session:
        items = operations_service.ops_queue(
            session, actor_user_id=bw.operator_id, queue=OpsQueue.UNANSWERED_LISTING.value, now=bw.base, limit=20
        )
    ids = {item.item_id for item in items}
    assert unanswered in ids
    assert answered not in ids, "a listing that already has an offer is not an operator task"
    assert all(item.item_type == "listing" for item in items)
    assert all("without an offer" in item.summary for item in items)


def test_stale_tracking_queue_speaks_about_the_signal_not_the_driver(bw: BW) -> None:  # noqa: F811
    trip_id, _trip_public = driver_trip(bw, bw.w.driver_id, "01A621AA")
    with bw.db.session() as session:
        session.execute(text("UPDATE trips SET status = 'in_progress' WHERE id = :t"), {"t": trip_id})
        session.execute(
            text(
                # a session that started an hour ago and has not delivered a single point since
                "INSERT INTO tracking_sessions (public_id, trip_id, driver_user_id, device_id, platform, status, "
                "app_version, started_at, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :t, :d, 'test-device', 'android', 'active', '1.0', :started, "
                ":started, :started)"
            ),
            {"t": trip_id, "d": bw.w.driver_id, "started": bw.base - timedelta(hours=1)},
        )
        session.commit()

    with bw.db.session() as session:
        items = operations_service.ops_queue(
            session, actor_user_id=bw.operator_id, queue=OpsQueue.STALE_TRACKING.value, now=bw.base, limit=20
        )
    assert len(items) == 1
    item = items[0]
    assert item.item_type == "trip"
    assert "no GPS point" in item.summary and "connection" in item.summary
    assert item.age_minutes >= 59


def test_ineligible_driver_queue_asks_identity_instead_of_keeping_a_copy(bw: BW) -> None:  # noqa: F811
    trip_id, _trip_public = driver_trip(bw, bw.w.driver_id, "01A622AA")
    with bw.db.session() as session:
        session.execute(
            text("UPDATE trips SET planned_start_at = :start WHERE id = :t"),
            {"start": bw.base + timedelta(hours=2), "t": trip_id},
        )
        session.commit()

    with bw.db.session() as session:
        before = operations_service.ops_queue(
            session, actor_user_id=bw.operator_id, queue=OpsQueue.INELIGIBLE_DRIVER_TRIP.value, now=bw.base, limit=20
        )
        assert before == [], "an eligible driver is not a task"

    from app.modules.identity import service as identity_service

    with bw.db.session() as session:
        version = identity_service.eligibility_version(session, bw.w.driver_id)
        identity_service.block_driver_eligibility(
            session, actor_user_id=bw.super_id, driver_user_id=bw.w.driver_id,
            expected_version=version, reason="documents_expired",
        )
        session.commit()

    with bw.db.session() as session:
        after = operations_service.ops_queue(
            session, actor_user_id=bw.operator_id, queue=OpsQueue.INELIGIBLE_DRIVER_TRIP.value, now=bw.base, limit=20
        )
    assert [item.item_type for item in after] == ["trip"]
    assert "not eligible" in after[0].summary


def test_queues_need_ops_view(bw: BW) -> None:  # noqa: F811
    from app.contracts.errors import DomainError, ErrorCode

    with bw.db.session() as session:
        for queue in (OpsQueue.UNANSWERED_LISTING, OpsQueue.STALE_TRACKING, OpsQueue.INELIGIBLE_DRIVER_TRIP):
            with pytest.raises(DomainError) as refused:
                operations_service.ops_queue(
                    session, actor_user_id=bw.w.client_id, queue=queue.value, now=bw.base, limit=5
                )
            assert refused.value.code in {ErrorCode.FORBIDDEN, ErrorCode.CAPABILITY_REQUIRED}
