"""Wave 1.5 BR fixes on PostgreSQL: deadlock-free user locks, demand snapshot, segment/time checks,
decisions 20/21/23, pause/resume, expiry workers, rejected event, frozen final versions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ListingPatch, ProposalCounter, ProposalCreate
from app.modules.platform.service import sqlstate_of
from app.modules.trips import service as trips_service
from tests.pg.identity.a1_world import (
    World,
    make_trip,
    make_vehicle,
    passenger_offer,
    passenger_request,
    run_in_thread,
    trip_create,
    wait_for_lock_waiters,
)
from tests.pg.marketplace.test_marketplace_pg import driver_trip, open_thread, proposal, published_request

pytestmark = pytest.mark.pg

DEADLOCK = "40P01"


def _publish(world: World, session: Session, listing_public_id: str, owner_id: int, version: int = 1):  # noqa: ANN202
    return marketplace_service.publish_listing(
        session, listing_public_id=listing_public_id, actor_user_id=owner_id, expected_version=version
    )


def published_offer(world: World, *, plate: str = "01F600FF", parcel: bool = False) -> tuple[str, int, str]:
    vehicle = make_vehicle(world, world.driver_id, plate)
    trip_id, trip_public_id = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    body = passenger_offer(world, trip_public_id, start=world.base_time)
    if parcel:
        body = ListingCreate.model_validate(
            {
                **body.model_dump(mode="json"),
                "service_type": "parcel",
                "price_basis": "total",
                "unit_price_minor": 5_000_000,
                "parcel": {"max_weight_g": 20_000, "max_volume_ml": 100_000, "max_dimension_cm": 60, "accepted_parcel_types": ["box"]},
            }
        )
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.driver_id, data=body)
        listing_public_id = marketplace_service.listing_public_id(listing)
        _publish(world, s, listing_public_id, world.driver_id)
        s.commit()
    return listing_public_id, trip_id, trip_public_id


def client_proposal(world: World, *, pickup: str = "B", dropoff: str = "D", hour: int = 1, **extra: object) -> ProposalCreate:
    start = world.base_time + timedelta(hours=hour)
    body = {
        "pickup_stop_id": world.stop_public_ids[pickup],
        "dropoff_stop_id": world.stop_public_ids[dropoff],
        "pickup_window_start": start.isoformat(),
        "pickup_window_end": (start + timedelta(minutes=30)).isoformat(),
        "quantity": 1,
        "price_basis": "per_seat",
        "unit_price_minor": 15_000_000,
    }
    body.update(extra)
    return ProposalCreate.model_validate(body)


# --- deadlock fix: FOR NO KEY UPDATE on users rows ------------------------------------------------------


def _deadlocked(*errors: BaseException | None) -> bool:
    return any(isinstance(error, DBAPIError) and sqlstate_of(error) == DEADLOCK for error in errors)


@pytest.mark.parametrize("holder_lock", ["service", "plain_for_update_control"])
def test_submit_vs_users_row_holder_waiting_for_the_listing(world: World, holder_lock: str) -> None:
    """A4-accept shape: users row locked first, then the listing, while submit holds the listing and inserts a
    thread referencing the same user (FOR KEY SHARE). The plain FOR UPDATE control proves the scenario deadlocks."""
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    with world.db.session() as s:
        listing_pk = marketplace_service.resolve_listing_id(s, listing_id)
    holder, submitter = world.db.session(), world.db.session()
    submit_error = None
    try:
        marketplace_service.lock_listing(submitter, listing_pk)

        def hold() -> None:
            if holder_lock == "service":
                identity_service.lock_user_eligibility(holder, [world.client_id])
            else:
                holder.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": world.client_id})
            marketplace_service.lock_listing(holder, listing_pk)
            holder.commit()

        thread, outcome = run_in_thread(hold)
        wait_for_lock_waiters(world, 1)
        try:
            marketplace_service.submit_proposal(
                submitter, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id)
            )
            submitter.commit()
        except DBAPIError as exc:
            submit_error = exc
            submitter.rollback()
        thread.join(timeout=30)
        assert not thread.is_alive(), "holder thread still blocked"
    finally:
        submitter.close()
        holder.close()
    if holder_lock == "service":
        assert submit_error is None and "error" not in outcome
        with world.db.session() as s:
            assert s.execute(text("SELECT count(*) FROM proposal_threads")).scalar_one() == 1
    else:
        assert _deadlocked(submit_error, outcome.get("error"))


@pytest.mark.parametrize("holder_lock", ["service", "plain_for_update_control"])
def test_owner_cancel_vs_resume_does_not_deadlock(world: World, holder_lock: str) -> None:
    listing_id = published_request(world)
    with world.db.session() as s:
        marketplace_service.pause_listing(s, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=2)
        listing_pk = marketplace_service.resolve_listing_id(s, listing_id)
        s.commit()
    canceller, resumer = world.db.session(), world.db.session()
    cancel_error = None
    try:
        marketplace_service.lock_listing(canceller, listing_pk)

        def resume() -> None:
            if holder_lock == "service":
                marketplace_service.resume_listing(
                    resumer, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=3
                )
            else:
                resumer.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": world.client_id})
                marketplace_service.lock_listing(resumer, listing_pk)
            resumer.commit()

        thread, outcome = run_in_thread(resume)
        wait_for_lock_waiters(world, 1)
        try:
            marketplace_service.cancel_listing(
                canceller, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=3, reason_code="plans_changed"
            )
            canceller.commit()
        except DBAPIError as exc:
            cancel_error = exc
            canceller.rollback()
        thread.join(timeout=30)
        assert not thread.is_alive(), "resume thread still blocked"
    finally:
        canceller.close()
        resumer.close()
    if holder_lock == "service":
        assert cancel_error is None
        assert isinstance(outcome.get("error"), DomainError) and outcome["error"].code is ErrorCode.VERSION_CONFLICT
        with world.db.session() as s:
            assert marketplace_service.get_listing_by_public_id(s, listing_id).status == "cancelled"
    else:
        assert _deadlocked(cancel_error, outcome.get("error"))


def test_submit_waits_for_a_concurrent_block_and_then_fails(world: World) -> None:
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    blocker = world.db.session()
    try:
        identity_service.block_driver_eligibility(
            blocker, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="fraud review"
        )

        def submit() -> None:
            with world.db.session() as s:
                marketplace_service.submit_proposal(
                    s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id)
                )
                s.commit()

        thread, outcome = run_in_thread(submit)
        wait_for_lock_waiters(world, 1)
        blocker.commit()
    finally:
        blocker.close()
    thread.join(timeout=30)
    assert not thread.is_alive(), "submit thread still blocked"
    assert isinstance(outcome.get("error"), DomainError) and outcome["error"].code is ErrorCode.DRIVER_NOT_ELIGIBLE


# --- eligibility on submit/counter (decision 21) --------------------------------------------------------


def test_blocked_driver_cannot_submit_or_counter(world: World) -> None:
    _, thread_public_id, trip_id = open_thread(world)
    with world.db.session() as s:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=ProposalCounter(expected_revision=1, unit_price_minor=18_000_000)
        )
        identity_service.block_driver_eligibility(
            s, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="docs"
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id, data=ProposalCounter(expected_revision=2, unit_price_minor=18_500_000)
        )
    assert info.value.code is ErrorCode.DRIVER_NOT_ELIGIBLE
    other = published_request(world, origin="B", destination="D")
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trip_public_id = trips_service.trip_public_id(trips_service.get_trip(s, trip_id))
        marketplace_service.submit_proposal(
            s, listing_public_id=other, actor_user_id=world.driver_id, data=proposal(world, trip_public_id)
        )
    assert info.value.code is ErrorCode.DRIVER_NOT_ELIGIBLE


def test_decision21_client_cannot_propose_on_blocked_drivers_offer(world: World) -> None:
    listing_id, _, _ = published_offer(world)
    with world.db.session() as s:
        identity_service.block_driver_eligibility(
            s, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="docs"
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.client_id, data=client_proposal(world))
    assert info.value.code is ErrorCode.DRIVER_NOT_ELIGIBLE
    assert info.value.details == {"reason": "trip_driver_not_eligible"}


# --- AC02 side, demand snapshot, segment checks --------------------------------------------------------


def test_ac02_client_proposal_on_trip_offer_with_baggage_snapshot(world: World) -> None:
    listing_id, trip_id, _ = published_offer(world)
    with world.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s,
            listing_public_id=listing_id,
            actor_user_id=world.client_id,
            data=client_proposal(world, baggage={"pieces": 1, "total_weight_g": 12_000, "total_volume_ml": 60_000}),
        )
        version = marketplace_service.current_version(s, thread)
        assert (version.author_side, version.pickup_occurrence_seq, version.dropoff_occurrence_seq) == ("client", 2, 4)
        assert (version.baggage_ml, version.cargo_weight_g, version.trip_version) == (60_000, 0, 1)
        assert marketplace_service.version_demand(version, service_type="passenger").seats == 1
        assert [load.seats_used for load in trips_service.get_segment_loads(s, trip_id)] == [0, 0, 0]
        s.commit()
        thread_public_id = marketplace_service.thread_public_id(thread)

    with world.db.session() as s:  # D9 on counter: offers are not bound to a seat count, requests are
        thread = marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id, data=ProposalCounter(expected_revision=1, quantity=2)
        )
        assert marketplace_service.current_version(s, thread).baggage_ml == 60_000  # carried over
        s.rollback()

    with world.db.session() as s, pytest.raises(DomainError) as info:  # trip baggage capacity 200 000 ml
        marketplace_service.submit_proposal(
            s,
            listing_public_id=listing_id,
            actor_user_id=world.client2_id,
            data=client_proposal(world, baggage={"total_volume_ml": 250_000}),
        )
    assert info.value.code is ErrorCode.CARGO_LIMIT_EXCEEDED


def test_trip_offer_segment_must_lie_inside_the_offer(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01H800HH")
    _, trip_public_id = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    body = passenger_offer(world, trip_public_id, start=world.base_time)
    body = ListingCreate.model_validate({**body.model_dump(mode="json"), "origin_stop_id": world.stop_public_ids["B"]})
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.driver_id, data=body)
        listing_id = marketplace_service.listing_public_id(listing)
        _publish(world, s, listing_id, world.driver_id)
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.client_id, data=client_proposal(world, pickup="A", hour=0)
        )
    assert info.value.code is ErrorCode.ROUTE_MISMATCH and info.value.details == {"reason": "outside_offer_segment"}


def test_route_mismatch_time_window_and_cutoff_at_submit(world: World) -> None:
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    reverse = proposal(world, trip_public_id).model_copy(
        update={"pickup_stop_id": world.stop_public_ids["D"], "dropoff_stop_id": world.stop_public_ids["A"]}
    )
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=reverse)
    assert info.value.code is ErrorCode.ROUTE_MISMATCH

    late = published_request_at(world, hours_after_base=5)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=late, actor_user_id=world.driver_id, data=proposal(world, trip_public_id))
    assert info.value.code is ErrorCode.TIME_WINDOW_CONFLICT

    day = world.base_time + timedelta(days=1)
    with world.db.session() as s:
        next_day_request = marketplace_service.create_listing(
            s, owner_user_id=world.client2_id, data=passenger_request(world, start=day)
        )
        next_day_id = marketplace_service.listing_public_id(next_day_request)
        _publish(world, s, next_day_id, world.client2_id)
        vehicle = make_vehicle(world, world.driver_id, "01J900JJ")
        cutoff_trip = trips_service.create_trip(
            s,
            driver_user_id=world.driver_id,
            data=trip_create(world, vehicle, start=day).model_copy(update={"booking_cutoff_at": day - timedelta(hours=1)}),
        )
        cutoff_trip_id = trips_service.trip_public_id(cutoff_trip)
        s.commit()
    late_proposal = ProposalCreate.model_validate(
        {
            **proposal(world, cutoff_trip_id).model_dump(mode="json"),
            "pickup_window_start": day.isoformat(),
            "pickup_window_end": (day + timedelta(minutes=30)).isoformat(),
        }
    )
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(
            s, listing_public_id=next_day_id, actor_user_id=world.driver_id, data=late_proposal, now=day - timedelta(minutes=30)
        )
    assert info.value.code is ErrorCode.BOOKING_CUTOFF_PASSED


def published_request_at(world: World, *, hours_after_base: int) -> str:
    with world.db.session() as s:
        listing = marketplace_service.create_listing(
            s,
            owner_user_id=world.client2_id,
            data=passenger_request(world, start=world.base_time + timedelta(hours=hours_after_base)),
        )
        public_id = marketplace_service.listing_public_id(listing)
        _publish(world, s, public_id, world.client2_id)
        s.commit()
        return public_id


def test_parcel_offer_proposal_snapshot_and_limits(world: World) -> None:
    listing_id, _, _ = published_offer(world, parcel=True)
    base = client_proposal(world, pickup="A", hour=0, price_basis="total", unit_price_minor=4_000_000)
    # W21-4 (wave 3.1): a trip-offer parcel proposal carries the receiver - nothing is picked up without one.
    parcel = {"parcel_type": "box", "weight_g": 5_000, "length_cm": 30, "width_cm": 20, "height_cm": 10,
              "receiver": {"name": "Olim", "phone": "+998900000999"}}
    with world.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s,
            listing_public_id=listing_id,
            actor_user_id=world.client_id,
            data=ProposalCreate.model_validate({**base.model_dump(mode="json"), "parcel": parcel}),
        )
        version = marketplace_service.current_version(s, thread)
        assert (version.receiver_name, version.receiver_phone) == ("Olim", "+998900000999")
        assert (version.cargo_weight_g, version.cargo_volume_ml) == (5_000, 6_000)
        assert (version.parcel_length_cm, version.parcel_width_cm, version.parcel_height_cm) == (30, 20, 10)
        s.commit()
    for update, code in (
        ({"parcel": {**parcel, "weight_g": 25_000}}, ErrorCode.CARGO_LIMIT_EXCEEDED),
        ({"parcel": {**parcel, "length_cm": 70}}, ErrorCode.CARGO_LIMIT_EXCEEDED),
        ({"parcel": None}, ErrorCode.VALIDATION_ERROR),
        ({"baggage": {"total_volume_ml": 1_000}}, ErrorCode.VALIDATION_ERROR),
        ({"quantity": 2, "parcel": parcel}, ErrorCode.QUANTITY_MISMATCH),
        ({"parcel": {k: v for k, v in parcel.items() if k != "receiver"}}, ErrorCode.VALIDATION_ERROR),  # W21-4
    ):
        body = ProposalCreate.model_validate({**base.model_dump(mode="json"), **update})
        with world.db.session() as s, pytest.raises(DomainError) as info:
            marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.client2_id, data=body)
        assert info.value.code is code, update


def test_parcel_request_proposal_takes_demand_from_the_request(world: World) -> None:
    body = ListingCreate.model_validate(
        {
            "kind": "request",
            "service_type": "parcel",
            "origin_stop_id": world.stop_public_ids["A"],
            "destination_stop_id": world.stop_public_ids["C"],
            "departure_window_start": world.base_time.isoformat(),
            "departure_window_end": (world.base_time + timedelta(hours=2)).isoformat(),
            "price_basis": "total",
            "unit_price_minor": 7_000_000,
            "parcel": {
                "parcel_type": "box", "weight_g": 4_000, "length_cm": 40, "width_cm": 30, "height_cm": 20, "payer": "sender",
                "sender": {"name": "Aziza", "phone": "+998900000201"}, "receiver": {"name": "Olim", "phone": "+998900000999"},
            },
        }
    )
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body)
        listing_id = marketplace_service.listing_public_id(listing)
        _publish(world, s, listing_id, world.client_id)
        s.commit()
    _, trip_public_id = driver_trip(world)
    offer = proposal(world, trip_public_id, quantity=1).model_copy(
        update={"dropoff_stop_id": world.stop_public_ids["C"], "price_basis": "total", "unit_price_minor": 6_500_000}
    )
    with world.db.session() as s:
        version = marketplace_service.current_version(
            s, marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=offer)
        )
        assert (version.cargo_weight_g, version.cargo_volume_ml, version.parcel_height_cm) == (4_000, 24_000, 20)
        s.rollback()
    with_parcel = ProposalCreate.model_validate(
        {**offer.model_dump(mode="json"), "parcel": {"weight_g": 1, "length_cm": 1, "width_cm": 1, "height_cm": 1}}
    )
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=with_parcel)
    assert info.value.code is ErrorCode.VALIDATION_ERROR


def test_d9_on_counter_for_requests(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=ProposalCounter(expected_revision=1, quantity=1)
        )
    assert info.value.code is ErrorCode.QUANTITY_MISMATCH


# --- listings: decisions 20/23, BR #8, pause/resume --------------------------------------------------------


def test_material_edit_reruns_publish_guards(world: World) -> None:
    second = published_request_at(world, hours_after_base=3)  # client2
    first_by_client2 = published_request_at(world, hours_after_base=8)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.patch_listing(
            s,
            listing_public_id=first_by_client2,
            actor_user_id=world.client2_id,
            data=ListingPatch(
                expected_version=2,
                departure_window_start=world.base_time + timedelta(hours=3),
                departure_window_end=world.base_time + timedelta(hours=4),
            ),
        )
    assert info.value.code is ErrorCode.DUPLICATE_LISTING
    assert second in str(info.value.details)


def test_operator_cancel_is_audited_and_cannot_touch_drafts(world: World) -> None:
    listing_id = published_request(world)
    with world.db.session() as s:
        draft = marketplace_service.listing_public_id(
            marketplace_service.create_listing(s, owner_user_id=world.client_id, data=passenger_request(world, start=world.base_time + timedelta(days=1)))
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.cancel_listing(s, listing_public_id=listing_id, actor_user_id=world.client2_id, expected_version=2, reason_code="spam")
    assert info.value.code is ErrorCode.NOT_FOUND
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.cancel_listing(s, listing_public_id=draft, actor_user_id=world.admin_id, expected_version=1, reason_code="spam")
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION
    with world.db.session() as s:
        listing = marketplace_service.cancel_listing(
            s, listing_public_id=listing_id, actor_user_id=world.admin_id, expected_version=2, reason_code="spam", comment="report #7"
        )
        assert (listing.status, listing.cancelled_by_user_id) == ("cancelled", world.admin_id)
        s.commit()
        audit = s.execute(
            text("SELECT actor_id, details FROM audit_logs WHERE action = 'listing_cancel_by_operator'")
        ).one()
        assert audit.actor_id == world.admin_id and audit.details["reason_code"] == "spam"


def test_pause_blocks_new_proposals_and_resume_reopens(world: World) -> None:
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    with world.db.session() as s:
        assert marketplace_service.pause_listing(s, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=2).status == "paused"
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id))
    assert info.value.code is ErrorCode.LISTING_NOT_OPEN
    with world.db.session() as s:
        listing = marketplace_service.resume_listing(s, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=3)
        assert (listing.status, listing.version) == ("published", 4)
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id))
        s.commit()


# --- workers, events, final immutability ------------------------------------------------------------------


def test_expiry_workers_skip_locked_listings_and_leave_commit_to_the_caller(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    later = utc_now() + timedelta(hours=3)
    holder = world.db.session()
    try:
        marketplace_service.lock_listing(holder, marketplace_service.resolve_listing_id(holder, listing_id))
        with world.db.session() as s:
            assert marketplace_service.expire_due_proposals(s, now=later) == 0  # skipped, not blocked
    finally:
        holder.rollback()
        holder.close()
    with world.db.session() as s:  # AGENTS §4: no internal commit - a rollback discards the batch
        assert marketplace_service.expire_due_proposals(s, now=later) == 1
        s.rollback()
    with world.db.session() as s:
        assert marketplace_service.get_thread_by_public_id(s, thread_public_id).state == "open"
    with world.db.session() as s:
        assert marketplace_service.expire_due_proposals(s, now=later) == 1
        s.commit()
    with world.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        assert (thread.state, marketplace_service.current_version(s, thread).status_reason) == ("closed", "ttl_expired")
        assert "proposal.expired" in s.execute(text("SELECT event_type FROM outbox_events")).scalars().all()
    with world.db.session() as s:
        assert marketplace_service.expire_due_listings(s, now=world.base_time + timedelta(hours=2)) >= 1
        s.commit()
    with world.db.session() as s:
        assert marketplace_service.get_listing_by_public_id(s, listing_id).status == "expired"


def test_reject_emits_event_and_final_version_is_frozen(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        thread = marketplace_service.reject_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, expected_revision=1, reason_code="too_expensive"
        )
        version_id = thread.current_version_id
        s.commit()
        assert s.execute(text("SELECT count(*) FROM outbox_events WHERE event_type = 'proposal.rejected'")).scalar_one() == 1
    for statement in (
        "UPDATE proposal_versions SET status_reason = 'rewritten' WHERE id = :v",
        "UPDATE proposal_versions SET closed_at = now() WHERE id = :v",
    ):
        with world.db.session() as s, pytest.raises(DBAPIError, match="immutable"):
            s.execute(text(statement), {"v": version_id})


def test_trip_change_expires_threads_and_rechecks_offers(world: World) -> None:
    _, thread_public_id, trip_id = open_thread(world)
    with world.db.session() as s:
        trip = s.execute(text("SELECT public_id, version FROM trips WHERE id = :t"), {"t": trip_id}).one()
    from app.contracts.ids import PublicIdPrefix, format_public_id
    from app.modules.trips.schemas import TripPatch

    trip_public_id = format_public_id(PublicIdPrefix.TRIP, trip.public_id)
    stops = [
        {"stop_id": world.stop_public_ids[name], "seq": index + 1, "planned_arrival_at": (world.base_time + timedelta(hours=hour)).isoformat()}
        for index, (name, hour) in enumerate((("A", 0), ("B", 1), ("D", 3)))
    ]
    with world.db.session() as s:
        patched = trips_service.patch_trip(
            s, trip_public_id_value=trip_public_id, actor_user_id=world.driver_id, data=TripPatch.model_validate({"expected_version": trip.version, "stops": stops})
        )
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        assert (patched.version, thread.state, marketplace_service.current_version(s, thread).status_reason) == (
            trip.version + 1, "closed", "trip_changed"
        )
        s.commit()

    with world.db.session() as s:
        offer = marketplace_service.create_listing(
            s, owner_user_id=world.driver_id, data=passenger_offer(world, trip_public_id, start=world.base_time)
        )
        s.commit()
    removing_d = [dict(stop) for stop in stops[:2]] + [
        {"stop_id": world.stop_public_ids["C"], "seq": 3, "planned_arrival_at": (world.base_time + timedelta(hours=2)).isoformat()}
    ]
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.patch_trip(
            s, trip_public_id_value=trip_public_id, actor_user_id=world.driver_id, data=TripPatch.model_validate({"expected_version": trip.version + 1, "stops": removing_d})
        )
    assert info.value.code is ErrorCode.ROUTE_MISMATCH
    assert info.value.details["listing_id"] == marketplace_service.listing_public_id(offer)
