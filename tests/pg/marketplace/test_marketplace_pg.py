"""Listings and proposals on real PostgreSQL 16 (AC01, AC04, AC05, AC43, D9, §5.3, §5.4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import FeatureFlagKey
from app.contracts.errors import DomainError, ErrorCode
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.rules import PROPOSAL_MAX_TTL
from app.modules.marketplace.schemas import ListingCreate, ListingPatch, ProposalCounter, ProposalCreate
from app.modules.trips import service as trips_service
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import World, make_trip, make_vehicle, passenger_request

pytestmark = pytest.mark.pg


def publish(world: World, session: Session, listing_public_id: str, owner_id: int, version: int = 1):  # noqa: ANN201
    return marketplace_service.publish_listing(
        session, listing_public_id=listing_public_id, actor_user_id=owner_id, expected_version=version
    )


def published_request(world: World, *, seats: int = 2, **kwargs: object) -> str:
    with world.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=world.client_id, data=passenger_request(world, start=world.base_time, seats=seats, **kwargs)
        )
        public_id = marketplace_service.listing_public_id(listing)
        publish(world, s, public_id, world.client_id)
        s.commit()
        return public_id


def driver_trip(world: World, plate: str = "01B200BB", seats: int = 4) -> tuple[int, str]:
    vehicle = make_vehicle(world, world.driver_id, plate, seats=max(seats, 1))
    return make_trip(world, world.driver_id, vehicle, start=world.base_time, seats=seats)


def proposal(world: World, trip_public_id: str | None, *, quantity: int = 2, unit_price_minor: int = 19_000_000) -> ProposalCreate:
    return ProposalCreate.model_validate(
        {
            "trip_id": trip_public_id,
            "pickup_stop_id": world.stop_public_ids["A"],
            "dropoff_stop_id": world.stop_public_ids["D"],
            "pickup_window_start": world.base_time.isoformat(),
            "pickup_window_end": (world.base_time + timedelta(minutes=30)).isoformat(),
            "quantity": quantity,
            "price_basis": "per_seat",
            "unit_price_minor": unit_price_minor,
        }
    )


def open_thread(world: World) -> tuple[str, str, int]:
    listing_id = published_request(world)
    trip_id, trip_public_id = driver_trip(world)
    with world.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id)
        )
        thread_public_id = marketplace_service.thread_public_id(thread)
        s.commit()
    return listing_id, thread_public_id, trip_id


# --- listings ------------------------------------------------------------------------------------------


def test_ac01_server_total_and_db_check(world: World) -> None:
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=passenger_request(world, start=world.base_time))
        assert (listing.quantity, listing.unit_price_minor, listing.total_minor) == (2, 20_000_000, 40_000_000)
        assert marketplace_service.get_passenger_details(s, listing.id).seat_count == listing.quantity  # D9 at rest
        s.commit()
        with pytest.raises(IntegrityError, match="ck_listings_total_minor"):
            s.execute(text("UPDATE listings SET total_minor = 20000000 WHERE id = :id"), {"id": listing.id})


def test_publish_guards(world: World) -> None:
    listing_id = published_request(world)
    with world.db.session() as s:
        duplicate = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=passenger_request(world, start=world.base_time))
        with pytest.raises(DomainError) as info:
            publish(world, s, marketplace_service.listing_public_id(duplicate), world.client_id)
        assert info.value.code is ErrorCode.DUPLICATE_LISTING
        assert info.value.details == {"existing_listing_id": listing_id}

    world.flags.disabled.add(FeatureFlagKey.PASSENGER_ENABLED)
    with world.db.session() as s:
        other = marketplace_service.create_listing(
            s, owner_user_id=world.client2_id, data=passenger_request(world, start=world.base_time)
        )
        with pytest.raises(DomainError) as info:
            publish(world, s, marketplace_service.listing_public_id(other), world.client2_id)
        assert info.value.code is ErrorCode.FEATURE_DISABLED

    with world.db.session() as s, pytest.raises(DomainError) as info:
        publish(world, s, listing_id, world.client_id, version=1)
    assert info.value.code is ErrorCode.VERSION_CONFLICT


def test_parcel_request_incomplete_cannot_publish(world: World) -> None:
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
            "parcel": {"parcel_type": "documents", "weight_g": 500},
        }
    )
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body)
        assert (listing.quantity, listing.total_minor) == (1, 7_000_000)
        with pytest.raises(DomainError) as info:
            publish(world, s, marketplace_service.listing_public_id(listing), world.client_id)
        assert info.value.code is ErrorCode.LISTING_INCOMPLETE
        assert "parcel.receiver_phone" in info.value.details["missing"]


# --- proposals -----------------------------------------------------------------------------------------


def test_ac05_self_dealing_forbidden(world: World) -> None:
    listing_id = published_request(world)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.client_id, data=proposal(world, None))
    assert info.value.code is ErrorCode.SELF_DEALING_FORBIDDEN
    assert info.value.http_status == 403


def test_d9_request_quantity_must_equal_seat_count(world: World) -> None:
    listing_id = published_request(world, seats=2)
    _, trip_public_id = driver_trip(world)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, quantity=1)
        )
    assert info.value.code is ErrorCode.QUANTITY_MISMATCH


def test_proposal_checks_but_never_reserves_capacity(world: World) -> None:
    listing_id = published_request(world, seats=3)
    trip_id, trip_public_id = driver_trip(world, seats=2)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, quantity=3)
        )
    assert info.value.code is ErrorCode.CAPACITY_UNAVAILABLE

    listing_id2 = published_request(world, seats=2, origin="B", destination="D")
    with world.db.session() as s:
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id2, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, quantity=2)
        )
        s.commit()
        assert [load.seats_used for load in trips_service.get_segment_loads(s, trip_id)] == [0, 0, 0]  # §5.3


def test_submit_snapshot_ttl_and_fee_quote(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        version = marketplace_service.current_version(s, thread)
        assert (version.revision, version.author_side, version.status) == (1, "driver", "active")
        assert (version.total_minor, version.fee_bps, version.commission_minor) == (38_000_000, 1500, 5_700_000)
        assert version.fee_policy_id == world.policy_id
        assert version.expires_at - version.created_at == PROPOSAL_MAX_TTL  # departure is two days away
        assert (version.pickup_occurrence_seq, version.dropoff_occurrence_seq) == (1, 4)
        events = s.execute(text("SELECT event_type FROM outbox_events ORDER BY id")).scalars().all()
        assert events == ["listing.published", "proposal.created"]


def test_ac04_counter_supersedes_and_stale_revision_is_rejected(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    counter = ProposalCounter(expected_revision=1, unit_price_minor=18_000_000)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.counter_proposal(s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id, data=counter)
    assert info.value.code is ErrorCode.NOT_PROPOSAL_RECIPIENT  # the author cannot counter itself

    with world.db.session() as s:
        thread = marketplace_service.counter_proposal(s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=counter)
        versions = marketplace_service.thread_versions(s, thread.id)
        assert [(v.revision, v.status, v.author_side) for v in versions] == [(1, "superseded", "driver"), (2, "active", "client")]
        assert (thread.client_price_revisions, thread.driver_price_revisions) == (1, 0)
        s.commit()

    with world.db.session() as s, pytest.raises(DomainError) as info:  # old revision
        marketplace_service.reject_proposal(s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id, expected_revision=1)
    assert info.value.code is ErrorCode.PROPOSAL_CHANGED


def test_price_revision_limit_is_three_per_side(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    price = 19_000_000
    revision = 1
    actors = [world.client_id, world.driver_id] * 3
    for actor in actors:
        price -= 100_000
        with world.db.session() as s:
            marketplace_service.counter_proposal(
                s,
                thread_public_id_value=thread_public_id,
                actor_user_id=actor,
                data=ProposalCounter(expected_revision=revision, unit_price_minor=price),
            )
            s.commit()
        revision += 1
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread_public_id,
            actor_user_id=world.client_id,
            data=ProposalCounter(expected_revision=revision, unit_price_minor=price - 100_000),
        )
    assert info.value.code is ErrorCode.NEGOTIATION_LIMIT_REACHED


def test_ac43_fee_quote_frozen_per_version(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    world.fees.fee_bps = 1000  # policy changed after revision 1 was quoted
    with world.db.session() as s:
        thread = marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread_public_id,
            actor_user_id=world.client_id,
            data=ProposalCounter(expected_revision=1, unit_price_minor=20_000_000),
        )
        first, second = marketplace_service.thread_versions(s, thread.id)
        assert (first.fee_bps, first.commission_minor) == (1500, 5_700_000)
        assert (second.fee_bps, second.commission_minor) == (1000, 4_000_000)
        s.commit()


def test_withdraw_by_author_and_reject_by_recipient(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.withdraw_proposal(s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, expected_revision=1)
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION
    with world.db.session() as s:
        thread = marketplace_service.withdraw_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id, expected_revision=1, reason_code="changed_plans"
        )
        assert thread.state == "closed"
        assert marketplace_service.current_version(s, thread).status == "withdrawn"
        s.commit()


def test_listing_change_and_cancel_expire_open_negotiations(world: World) -> None:
    """Decision 20: a unit-price edit keeps negotiations open; a window edit expires them."""
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        listing = marketplace_service.patch_listing(
            s, listing_public_id=listing_id, actor_user_id=world.client_id, data=ListingPatch(expected_version=2, unit_price_minor=21_000_000)
        )
        assert (listing.version, listing.total_minor) == (3, 42_000_000)
        assert marketplace_service.get_thread_by_public_id(s, thread_public_id).state == "open"
        s.commit()
    with world.db.session() as s:
        marketplace_service.patch_listing(
            s,
            listing_public_id=listing_id,
            actor_user_id=world.client_id,
            data=ListingPatch(expected_version=3, departure_window_end=world.base_time + timedelta(minutes=50)),
        )
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        assert (thread.state, marketplace_service.current_version(s, thread).status_reason) == ("closed", "listing_changed")
        s.commit()
    with world.db.session() as s:
        listing = marketplace_service.cancel_listing(
            s, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=4, reason_code="found_other_ride"
        )
        assert listing.status == "cancelled"
        s.commit()


def test_parallel_submit_creates_one_open_thread(world: World) -> None:
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    body = proposal(world, trip_public_id)

    def submit(worker: int, session: Session) -> str:
        thread = marketplace_service.submit_proposal(session, listing_public_id=listing_id, actor_user_id=world.driver_id, data=body)
        session.commit()
        return marketplace_service.thread_public_id(thread)

    report = run_concurrently(10, submit, engine=world.db.engine)
    assert len(report.successes) == 1
    assert all(isinstance(r.error, DomainError) and r.error.code is ErrorCode.INVALID_STATE_TRANSITION for r in report.failures)


# --- DB invariants ---------------------------------------------------------------------------------------


def test_open_thread_partial_unique_includes_null_trip(world: World) -> None:
    listing_id = published_request(world)
    with world.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_id)
        insert = text(
            "INSERT INTO proposal_threads (public_id, listing_id, client_user_id, driver_user_id, trip_id, state) "
            "VALUES (gen_random_uuid(), :l, :c, :d, NULL, :state)"
        )
        params = {"l": listing.id, "c": world.client_id, "d": world.driver_id}
        s.execute(insert, {**params, "state": "closed"})
        s.execute(insert, {**params, "state": "closed"})  # closed threads never collide
        s.execute(insert, {**params, "state": "open"})
        s.commit()
        with pytest.raises(IntegrityError, match="uq_proposal_threads_open_context"):
            s.execute(insert, {**params, "state": "open"})


def test_active_version_partial_unique_and_immutability(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        version_id = thread.current_version_id
        with pytest.raises(IntegrityError, match="uq_proposal_versions_active"):
            s.execute(
                text(
                    "INSERT INTO proposal_versions (public_id, thread_id, revision, author_side, author_user_id, pickup_stop_id, "
                    "dropoff_stop_id, pickup_window_start, pickup_window_end, quantity, price_basis, unit_price_minor, total_minor, "
                    "expires_at, listing_version, fee_policy_id, fee_bps, commission_minor) "
                    "SELECT gen_random_uuid(), thread_id, 2, 'client', :c, pickup_stop_id, dropoff_stop_id, pickup_window_start, "
                    "pickup_window_end, quantity, price_basis, unit_price_minor, total_minor, expires_at, listing_version, "
                    "fee_policy_id, fee_bps, commission_minor FROM proposal_versions WHERE id = :v"
                ),
                {"c": world.client_id, "v": version_id},
            )
        s.rollback()

    for statement in (
        "UPDATE proposal_versions SET unit_price_minor = unit_price_minor + 100 WHERE id = :v",
        "UPDATE proposal_versions SET fee_bps = 0, commission_minor = 0 WHERE id = :v",
        "DELETE FROM proposal_versions WHERE id = :v",
    ):
        with world.db.session() as s, pytest.raises(DBAPIError, match="immutable"):
            s.execute(text(statement), {"v": version_id})

    with world.db.session() as s:
        s.execute(
            text("UPDATE proposal_versions SET status = 'rejected', status_reason = 'x', closed_at = now() WHERE id = :v"),
            {"v": version_id},
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DBAPIError, match="immutable"):
        s.execute(text("UPDATE proposal_versions SET status = 'active', closed_at = NULL WHERE id = :v"), {"v": version_id})
