"""Wave 2.1 marketplace on PostgreSQL: Q59 public commands, Q67 band, Q68 enums + 0054 data step, BR blocker 7,
trip-offer parcel receiver (Q43/Q44)."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.contracts.enums import EventType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import ProposalThread, ProposalVersion
from app.modules.marketplace.schemas import ListingCreate, ParcelDetails, ProposalCounter
from tests.pg.identity.a1_world import World, passenger_request
from tests.pg.marketplace.test_marketplace_pg import open_thread
from tests.pg.marketplace.catalog_world import synthetic_category

pytestmark = pytest.mark.pg

MIGRATION_0054 = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260915_0054_marketplace_trips_hardening.py"


def _parcel_request_pk(world: World) -> int:
    body = ListingCreate.model_validate({
        "kind": "request", "service_type": "parcel",
        "origin_stop_id": world.stop_public_ids["A"], "destination_stop_id": world.stop_public_ids["C"],
        "departure_window_start": world.base_time.isoformat(),
        "departure_window_end": (world.base_time + timedelta(hours=2)).isoformat(),
        "price_basis": "total", "unit_price_minor": 7_000_000,
        "parcel": {"parcel_type": "box", "category_id": synthetic_category(world.db), "payer": "sender",
                   "sender": {"name": "Aziza", "phone": "+998900000201"}, "receiver": {"name": "Olim", "phone": "+998900000999"}},
    })
    with world.db.session() as s:
        pk = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body).id
        s.commit()
    return pk


def _count(world: World, sql: str, **params: object) -> int:
    with world.db.engine.connect() as conn:
        return int(conn.execute(text(sql), params).scalar_one())


# --- Q59 ----------------------------------------------------------------------------------------------


def test_q59_accept_fulfil_reopen_cancel_follow_the_state_machines(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    now = utc_now()
    with world.db.session() as s:
        listing = marketplace_service.lock_listing(s, marketplace_service.resolve_listing_id(s, listing_id))
        thread = marketplace_service.lock_thread(s, marketplace_service.get_thread_by_public_id(s, thread_public_id).id)
        version = marketplace_service.current_version(s, thread, for_update=True)
        thread_v, listing_v = thread.version, listing.version

        marketplace_service.accept_version(s, listing=listing, thread=thread, version=version, now=now)
        assert (version.status, version.closed_at is not None, thread.state, thread.version) == ("accepted", True, "accepted", thread_v + 1)
        with pytest.raises(DomainError) as info:
            marketplace_service.accept_version(s, listing=listing, thread=thread, version=version, now=now)
        assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION

        marketplace_service.fulfil_listing(s, listing=listing, now=now)
        assert (listing.status, listing.version) == ("fulfilled", listing_v + 1)
        with pytest.raises(DomainError) as info:
            marketplace_service.fulfil_listing(s, listing=listing, now=now)
        assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION

        marketplace_service.reopen_listing(s, listing=listing, now=now)
        assert (listing.status, listing.version) == ("published", listing_v + 2)
        marketplace_service.cancel_listing_for_booking(
            s, listing=listing, actor_user_id=None, reason_code="trip_cancelled_by_driver", now=now
        )
        assert (listing.status, listing.cancelled_reason, listing.version) == ("cancelled", "trip_cancelled_by_driver", listing_v + 3)
        with pytest.raises(DomainError):
            marketplace_service.reopen_listing(s, listing=listing, now=now)
        s.commit()
    published = _count(world, "SELECT count(*) FROM outbox_events WHERE event_type = :e", e=EventType.LISTING_PUBLISHED.value)
    cancelled = _count(world, "SELECT count(*) FROM outbox_events WHERE event_type = :e", e=EventType.LISTING_CANCELLED.value)
    assert (published, cancelled) == (2, 1)  # publish + reopen (Q19), then cancel


def test_q59_close_open_threads_returns_the_number_closed(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        listing = marketplace_service.lock_listing(s, marketplace_service.resolve_listing_id(s, listing_id))
        assert marketplace_service.close_open_threads(s, listing=listing, reason="demand_fulfilled", now=utc_now()) == 1
        assert marketplace_service.close_open_threads(s, listing=listing, reason="demand_fulfilled", now=utc_now()) == 0
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        version = marketplace_service.current_version(s, thread)
        assert (thread.state, thread.closed_reason, version.status, version.status_reason) == (
            "closed", "demand_fulfilled", "expired", "demand_fulfilled"
        )
        s.commit()


# --- Q67 ----------------------------------------------------------------------------------------------


def test_q67_counter_rechecks_the_band_when_a_stop_changes(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)  # driver: 19 000 000 per seat, A -> D
    with world.db.session() as s:  # no band yet: the client moves the dropoff to C, price unchanged
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id,
            data=ProposalCounter(expected_revision=1, dropoff_stop_id=world.stop_public_ids["C"]),
        )
        s.commit()
    with world.db.session() as s:
        s.execute(
            text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, floor_minor, ceiling_minor, "
                "enforced, reason, updated_by) VALUES (gen_random_uuid(), :c, 'passenger', 'per_seat', 5000000, 8000000, "
                "true, 'band (enforced: Q90 leaves only this kind able to refuse)', :a)"
            ),
            {"c": world.corridor_id, "a": world.admin_id},
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:  # same price, dropoff back to D -> band re-checked
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id,
            data=ProposalCounter(expected_revision=2, dropoff_stop_id=world.stop_public_ids["D"]),
        )
    assert info.value.code is ErrorCode.PRICE_OUT_OF_BAND
    window = {
        "pickup_window_start": (world.base_time - timedelta(minutes=10)).isoformat(),
        "pickup_window_end": (world.base_time + timedelta(minutes=20)).isoformat(),
    }
    with world.db.session() as s:  # window-only change: price and stops unchanged -> no band check (Q53)
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id,
            data=ProposalCounter.model_validate({"expected_revision": 2, **window}),
        )
        s.commit()


# --- Q68 ----------------------------------------------------------------------------------------------


def test_q68_strict_enums_in_schema_and_db_checks(world: World) -> None:
    body = passenger_request(world, start=world.base_time).model_dump(mode="json")
    for bad in (
        lambda: ListingCreate.model_validate({**body, "passenger": {**body["passenger"], "amenities": ["konditsioner"]}}),
        lambda: ParcelDetails.model_validate({"parcel_type": "furniture"}),
        lambda: ParcelDetails.model_validate({"accepted_parcel_types": ["box", "tel 90 123 45 67"]}),
    ):
        with pytest.raises(ValidationError):
            bad()
    ok = ListingCreate.model_validate({**body, "passenger": {**body["passenger"], "amenities": ["air_conditioning", "wifi", "wifi"]}})
    warnings: list[dict] = []
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=ok, warnings=warnings)
        assert marketplace_service.get_passenger_details(s, listing.id).amenities == ["air_conditioning", "wifi"]
        passenger_pk = listing.id
        s.commit()
    assert warnings == []
    parcel_pk = _parcel_request_pk(world)  # ADR-0026: a client's parcel request carries the same details row
    for statement, pk, constraint in (
        ("UPDATE passenger_listing_details SET amenities = ARRAY['konditsioner'] WHERE listing_id = :l", passenger_pk, "ck_passenger_listing_details_amenities"),
        ("UPDATE parcel_listing_details SET parcel_type = 'furniture' WHERE listing_id = :l", parcel_pk, "ck_parcel_listing_details_parcel_type"),
        ("UPDATE parcel_listing_details SET accepted_parcel_types = ARRAY['box', 'sofa'] WHERE listing_id = :l", parcel_pk, "ck_parcel_listing_details_accepted_parcel_types"),
    ):
        with world.db.session() as s, pytest.raises(IntegrityError, match=constraint):
            s.execute(text(statement), {"l": pk})


def _run_0054_upgrade(world: World) -> None:
    spec = importlib.util.spec_from_file_location("migration_0054_pg", MIGRATION_0054)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    with world.db.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()


def test_0054_data_step_cleans_free_text_and_upgrade_is_idempotent(world: World) -> None:
    body = passenger_request(world, start=world.base_time)
    with world.db.session() as s:
        passenger_pk = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body).id
        s.commit()
    parcel_pk = _parcel_request_pk(world)  # ADR-0026: a client's parcel request carries the same details row
    with world.db.engine.begin() as conn:  # pre-Q68 state: no CHECKs, free text rows
        for table, name in (
            ("passenger_listing_details", "ck_passenger_listing_details_amenities"),
            ("parcel_listing_details", "ck_parcel_listing_details_parcel_type"),
            ("parcel_listing_details", "ck_parcel_listing_details_accepted_parcel_types"),
        ):
            conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
        conn.execute(
            text("UPDATE passenger_listing_details SET amenities = ARRAY['konditsioner', ' WiFi ', 'wifi', 'tel 90 123 45 67'] WHERE listing_id = :l"),
            {"l": passenger_pk},
        )
        conn.execute(
            text("UPDATE parcel_listing_details SET parcel_type = 'Mebel', accepted_parcel_types = ARRAY['BOX', 'sofa', 'divan', 'box'] WHERE listing_id = :l"),
            {"l": parcel_pk},
        )
    _run_0054_upgrade(world)
    _run_0054_upgrade(world)  # second run is a no-op (idempotent)
    with world.db.engine.connect() as conn:
        amenities = conn.execute(text("SELECT amenities FROM passenger_listing_details WHERE listing_id = :l"), {"l": passenger_pk}).scalar_one()
        parcel = conn.execute(
            text("SELECT parcel_type, accepted_parcel_types FROM parcel_listing_details WHERE listing_id = :l"), {"l": parcel_pk}
        ).one()
        validated = conn.execute(
            text(
                "SELECT count(*) FROM pg_constraint WHERE convalidated AND conname IN ('ck_passenger_listing_details_amenities', "
                "'ck_parcel_listing_details_parcel_type', 'ck_parcel_listing_details_accepted_parcel_types', 'ck_proposal_versions_receiver')"
            )
        ).scalar_one()
        triggers = conn.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_trip_stop_occurrences_stops_locked', "
                 "'trg_trip_segment_resources_stops_locked', 'trg_trip_segment_resources_counters_match_allocations')")
        ).scalar_one()
    assert amenities == ["wifi"]
    assert (parcel.parcel_type, parcel.accepted_parcel_types) == ("other", ["box", "other"])
    assert (validated, triggers) == (4, 3)


# --- BR blocker 7 --------------------------------------------------------------------------------------


def test_br7_offer_pages_are_filled_past_expired_threads(world: World) -> None:
    listing_id, thread_public_id, trip_id = open_thread(world)
    thread_columns = [
        c.name for c in ProposalThread.__table__.columns if c.name not in ("id", "public_id", "trip_id", "current_version_id")
    ]
    version_columns = [
        c.name for c in ProposalVersion.__table__.columns if c.name not in ("id", "public_id", "thread_id", "expires_at")
    ]
    with world.db.session() as s:
        source = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        for index in range(34):  # ids after the original: 30 open threads whose version expired, then 4 live ones
            clone_trip = s.execute(
                text(
                    "INSERT INTO trips (public_id, driver_user_id, vehicle_id, route_version_id, status, planned_start_at, planned_end_at, "
                    "blocked_period, booking_cutoff_at, seat_capacity, max_detour_minutes, max_detour_m, cancel_reason) "
                    "SELECT gen_random_uuid(), driver_user_id, vehicle_id, route_version_id, 'cancelled', planned_start_at, planned_end_at, "
                    "blocked_period, booking_cutoff_at, seat_capacity, max_detour_minutes, max_detour_m, 'fixture' FROM trips WHERE id = :t "
                    "RETURNING id"
                ),
                {"t": trip_id},
            ).scalar_one()
            new_thread = s.execute(
                text(
                    f"INSERT INTO proposal_threads (public_id, trip_id, {', '.join(thread_columns)}) "
                    f"SELECT gen_random_uuid(), :trip, {', '.join(thread_columns)} FROM proposal_threads WHERE id = :id RETURNING id"
                ),
                {"trip": clone_trip, "id": source.id},
            ).scalar_one()
            expires = "now() - interval '1 minute'" if index < 30 else "expires_at"
            new_version = s.execute(
                text(
                    f"INSERT INTO proposal_versions (public_id, thread_id, expires_at, {', '.join(version_columns)}) "
                    f"SELECT gen_random_uuid(), :thread, {expires}, {', '.join(version_columns)} FROM proposal_versions WHERE id = :v "
                    "RETURNING id"
                ),
                {"thread": new_thread, "v": source.current_version_id},
            ).scalar_one()
            s.execute(text("UPDATE proposal_threads SET current_version_id = :v WHERE id = :t"), {"v": new_version, "t": new_thread})
        s.commit()

    def offers(**kwargs: object) -> list:
        with world.db.session() as s:
            return marketplace_service.list_listing_offers(s, listing_public_id=listing_id, viewer_user_id=world.driver2_id, **kwargs)

    assert len(offers(limit=6)) == 5  # the API asks limit + 1: 5 live offers, none hidden by the 30 expired ones
    first = offers(limit=3)
    rest = offers(limit=3, after_thread_id=first[-1].thread_id)
    assert (len(first), len(rest)) == (3, 2)
    assert len({o.thread_id for o in first + rest}) == 5


# --- receiver contact on trip-offer parcel proposals (card item 7) -----------------------------------------


