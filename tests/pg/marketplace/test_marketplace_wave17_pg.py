"""Wave 1.7 BR fixes on PostgreSQL: R1-a/b, R2-a/b, N3, N7, Q53, Q54."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.contracts.enums import FeatureFlagKey
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ProposalCounter, ProposalCreate
from app.modules.marketplace.views import listing_dto
from tests.pg.identity.a1_world import World, passenger_request
from tests.pg.marketplace.test_a1_api_pg import auth, client  # noqa: F401  (fixture)
from tests.pg.marketplace.test_marketplace_pg import driver_trip, open_thread, proposal, published_request
from tests.pg.marketplace.test_marketplace_wave15_pg import client_proposal, published_offer

pytestmark = pytest.mark.pg


def _offers(world: World, listing_id: str, viewer: int, **kwargs: object) -> list:
    with world.db.session() as s:
        return marketplace_service.list_listing_offers(s, listing_public_id=listing_id, viewer_user_id=viewer, **kwargs)


# --- R1 ---------------------------------------------------------------------------------------------


def test_r1a_offers_hidden_when_service_flag_is_off(world: World) -> None:
    listing_id, _, _ = open_thread(world)
    assert len(_offers(world, listing_id, world.driver2_id)) == 1
    world.flags.disabled.add(FeatureFlagKey.PASSENGER_ENABLED)
    with pytest.raises(DomainError) as info:
        _offers(world, listing_id, world.driver2_id)
    assert info.value.code is ErrorCode.NOT_FOUND


def test_r1b_response_pending_and_expired_threads_skipped(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=ProposalCounter(expected_revision=1, unit_price_minor=17_000_000)
        )
        s.commit()
    offers = _offers(world, listing_id, world.driver2_id)
    assert [(o.version.revision, o.version.unit_price_minor, o.response_pending) for o in offers] == [(1, 19_000_000, True)]
    assert _offers(world, listing_id, world.driver2_id, now=utc_now() + timedelta(hours=3)) == []


# --- R2 ---------------------------------------------------------------------------------------------


def test_r2a_enum_fields_are_strict_instead_of_filtered(world: World) -> None:
    """Q68 supersedes R2-a for amenities and parcel types: free text is rejected by the schema (400
    VALIDATION_ERROR through the v2 handler) and never stored, masked or not. Special assistance stays filtered."""
    body = passenger_request(world, start=world.base_time).model_dump(mode="json")
    with pytest.raises(ValidationError):
        ListingCreate.model_validate({**body, "passenger": {**body["passenger"], "amenities": ["konditsioner", "tel 90 123 45 67"]}})
    listing_body = ListingCreate.model_validate(
        {**body, "passenger": {**body["passenger"], "amenities": ["air_conditioning"], "special_assistance": "tel 90 123 45 67"}}
    )
    warnings: list[dict] = []
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=listing_body, warnings=warnings)
        details = marketplace_service.get_passenger_details(s, listing.id)
        assert details.amenities == ["air_conditioning"] and "123" not in details.special_assistance
        s.commit()
    assert [w["field"] for w in warnings] == ["passenger.special_assistance"]

    parcel = {"parcel_type": "box @kuryer_uz", "weight_g": 1_000, "length_cm": 10, "width_cm": 10, "height_cm": 10}
    with pytest.raises(ValidationError):
        ProposalCreate.model_validate(
            {**client_proposal(world, pickup="A", hour=0, price_basis="total", unit_price_minor=4_000_000).model_dump(mode="json"), "parcel": parcel}
        )


def test_r2b_filter_hit_survives_a_failed_command(client, world: World) -> None:  # noqa: F811
    listing_id = published_request(world)  # 2 seats
    _, trip_public_id = driver_trip(world)
    body = proposal(world, trip_public_id, quantity=1).model_dump(mode="json")  # D9 mismatch -> 409
    body["message"] = "menga yozing +998 90 765 43 21"
    response = client.post(
        f"/api/v2/listings/{listing_id}/proposals", json=body, headers=auth(world.driver_id, "driver", "r2b-key-0001")
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "QUANTITY_MISMATCH"
    with world.db.session() as s:
        audit = s.execute(text("SELECT details FROM audit_logs WHERE action = 'contact_filter_hit'")).scalars().all()
        events = s.execute(text("SELECT payload FROM outbox_events WHERE event_type = 'trust.contact_filter.hit'")).scalars().all()
        assert s.execute(text("SELECT count(*) FROM proposal_threads")).scalar_one() == 0
    assert len(audit) == 1 and audit[0]["field"] == "message" and audit[0]["categories"] == {"phone": 1}
    assert len(events) == 1 and events[0]["subject_type"] == "proposal"
    assert "765 43 21" not in str(audit) + str(events)

    ok = proposal(world, trip_public_id, quantity=2).model_dump(mode="json")
    ok["message"] = "telegram @dilshod_driver"
    created = client.post(f"/api/v2/listings/{listing_id}/proposals", json=ok, headers=auth(world.driver_id, "driver", "r2b-key-0002"))
    assert created.status_code == 201
    assert created.json()["warnings"][0]["code"] == "CONTACT_INFO_MASKED"
    with world.db.session() as s:
        assert s.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'contact_filter_hit'")).scalar_one() == 2


# --- N3, N7 -----------------------------------------------------------------------------------------


def test_n3_request_proposal_window_must_meet_its_own_pickup_window(world: World) -> None:
    listing_id = published_request(world)  # request window base .. base+1h
    _, trip_public_id = driver_trip(world)
    late = ProposalCreate.model_validate(
        {
            **proposal(world, trip_public_id).model_dump(mode="json"),
            "pickup_window_start": (world.base_time + timedelta(hours=2)).isoformat(),
            "pickup_window_end": (world.base_time + timedelta(hours=2, minutes=30)).isoformat(),
        }
    )
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=late)
    assert info.value.code is ErrorCode.TIME_WINDOW_CONFLICT


def test_n7_untyped_parcel_rejected_when_offer_restricts_types(world: World) -> None:
    listing_id, _, _ = published_offer(world, parcel=True)  # accepted_parcel_types = ["box"]
    body = ProposalCreate.model_validate(
        {
            **client_proposal(world, pickup="A", hour=0, price_basis="total", unit_price_minor=4_000_000).model_dump(mode="json"),
            "parcel": {"weight_g": 1_000, "length_cm": 10, "width_cm": 10, "height_cm": 10},
        }
    )
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.client_id, data=body)
    assert info.value.code is ErrorCode.VALIDATION_ERROR and info.value.details == {"field": "parcel.parcel_type"}


# --- Q53, Q54 ---------------------------------------------------------------------------------------


def test_q53_unchanged_price_counter_skips_band_and_details_shape(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)  # driver offered 19 000 000 per seat
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
    window = {
        "pickup_window_start": (world.base_time - timedelta(minutes=10)).isoformat(),
        "pickup_window_end": (world.base_time + timedelta(minutes=20)).isoformat(),
    }
    with world.db.session() as s:  # client changes only the window: no band check
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=ProposalCounter.model_validate({"expected_revision": 1, **window})
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.driver_id, data=ProposalCounter(expected_revision=2, unit_price_minor=18_000_000)
        )
    assert info.value.code is ErrorCode.PRICE_OUT_OF_BAND
    assert {"floor_minor", "ceiling_minor", "currency", "price_basis"} <= set(info.value.details)
    assert info.value.details["ceiling_minor"] == 8_000_000


def test_q54_listing_dto_exposes_terms_version(world: World) -> None:
    listing_id = published_request(world)
    with world.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_id)
        dto = listing_dto(s, listing)
        assert (dto.version, dto.terms_version) == (listing.version, listing.terms_version) == (2, 1)
