"""Wave 1.6 on PostgreSQL: R2 contact filter on free text (Q43-Q44) and Q42 price bands."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.errors import DomainError, ErrorCode
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate, ListingPatch, ProposalCounter, ProposalCreate
from tests.pg.identity.a1_world import World, passenger_request
from tests.pg.marketplace.test_marketplace_pg import driver_trip, open_thread, proposal, published_request

pytestmark = pytest.mark.pg

PHONES = [
    "+998 90 123 45 67",
    "998901234567",
    "90-123-45-67",
    "(90) 123 45 67",
    "to'qson bir ikki uch to'rt besh olti yetti sakkiz",
]


def raw_text_stored(world: World, needle: str) -> bool:
    with world.db.session() as s:
        haystacks = (
            s.execute(text("SELECT string_agg(coalesce(comment, '') || ' ' || coalesce(cancel_comment, ''), ' ') FROM listings")).scalar(),
            s.execute(text("SELECT string_agg(coalesce(message, ''), ' ') FROM proposal_versions")).scalar(),
            s.execute(text("SELECT string_agg(coalesce(special_assistance, ''), ' ') FROM passenger_listing_details")).scalar(),
            s.execute(text("SELECT string_agg(details::text, ' ') FROM audit_logs")).scalar(),
            s.execute(text("SELECT string_agg(payload::text, ' ') FROM outbox_events")).scalar(),
        )
    return any(needle in (h or "") for h in haystacks)


@pytest.mark.parametrize("phone", PHONES)
def test_r2_listing_comment_is_masked_and_raw_never_stored(world: World, phone: str) -> None:
    body = passenger_request(world, start=world.base_time).model_copy(update={"comment": f"Menga yozing {phone} tez"})
    warnings: list[dict] = []
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body, warnings=warnings)
        assert phone not in (listing.comment or "") and "•••" in listing.comment
        s.commit()
    assert warnings and warnings[0]["code"] == "CONTACT_INFO_MASKED" and warnings[0]["field"] == "comment"
    assert "phone" in warnings[0]["categories"]
    assert not raw_text_stored(world, phone)
    with world.db.session() as s:
        audit = s.execute(text("SELECT details FROM audit_logs WHERE action = 'contact_filter_hit'")).scalar_one()
        assert audit["field"] == "comment" and audit["categories"].get("phone", 0) >= 1


def test_r2_prices_and_times_are_not_masked(world: World) -> None:
    comment = "Narx 200 000 so'm, 13:00 da jo'naymiz, 2 kishi, 15 kg yuk"
    body = passenger_request(world, start=world.base_time).model_copy(update={"comment": comment})
    warnings: list[dict] = []
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body, warnings=warnings)
        assert listing.comment == comment and warnings == []


def test_r2_special_assistance_patch_and_proposal_message_are_masked(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    warnings: list[dict] = []
    patch = ListingPatch.model_validate(
        {
            "expected_version": 2,
            "comment": "telegram: @aziza_uz",
            "passenger": {"seat_count": 2, "adults": 2, "special_assistance": "qo'ng'iroq qiling 901234567",
                          "baggage": {"pieces": 1, "total_weight_g": 15_000, "total_volume_ml": 40_000}},
        }
    )
    with world.db.session() as s:
        listing = marketplace_service.patch_listing(s, listing_public_id=listing_id, actor_user_id=world.client_id, data=patch, warnings=warnings)
        assert "@aziza_uz" not in listing.comment
        assert "901234567" not in marketplace_service.get_passenger_details(s, listing.id).special_assistance
        s.commit()
    assert {w["field"] for w in warnings} == {"comment", "passenger.special_assistance"}

    warnings = []
    with world.db.session() as s:
        thread = marketplace_service.counter_proposal(
            s,
            thread_public_id_value=thread_public_id,
            actor_user_id=world.client_id,
            data=ProposalCounter(expected_revision=1, unit_price_minor=18_000_000, message="WhatsApp +998 97 765 43 21"),
            warnings=warnings,
        )
        version = marketplace_service.current_version(s, thread)
        assert "765" not in version.message and warnings[0]["field"] == "message"
        s.commit()
    assert not raw_text_stored(world, "97 765 43 21") and not raw_text_stored(world, "aziza_uz")


def _band(
    world: World,
    *,
    floor: int,
    ceiling: int,
    origin: str | None = None,
    destination: str | None = None,
    enforced: bool = True,
) -> None:
    """Q90: ``enforced`` defaults to true *here* because these tests exist to prove the precedence and
    the moment of the check, and only an enforced band still refuses observably. The advisory default
    (a warning, never a refusal) is covered in ``test_price_is_negotiated_pg.py``."""
    with world.db.session() as s:
        s.execute(
            text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, origin_stop_id, "
                "destination_stop_id, floor_minor, ceiling_minor, enforced, reason, updated_by) VALUES "
                "(gen_random_uuid(), :c, 'passenger', 'per_seat', :o, :d, :f, :ce, :en, 'test band', :a)"
            ),
            {
                "c": world.corridor_id,
                "o": world.stop_ids[origin] if origin else None,
                "d": world.stop_ids[destination] if destination else None,
                "f": floor,
                "ce": ceiling,
                "en": enforced,
                "a": world.admin_id,
            },
        )
        s.commit()


def test_q42_price_band_on_submit_and_counter(world: World) -> None:
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    _band(world, floor=15_000_000, ceiling=25_000_000)  # corridor-wide, per seat
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, unit_price_minor=30_000_000)
        )
    assert info.value.code is ErrorCode.PRICE_OUT_OF_BAND
    assert info.value.details["ceiling_minor"] == 25_000_000
    with world.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, unit_price_minor=20_000_000)
        )
        thread_public_id = marketplace_service.thread_public_id(thread)
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=ProposalCounter(expected_revision=1, unit_price_minor=10_000_000)
        )
    assert info.value.code is ErrorCode.PRICE_OUT_OF_BAND


def test_q42_segment_band_wins_and_missing_band_allows(world: World) -> None:
    listing_id = published_request(world)
    _, trip_public_id = driver_trip(world)
    with world.db.session() as s:  # no band configured -> any price allowed
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, unit_price_minor=99_000_000)
        )
        s.rollback()
    _band(world, floor=1_000_000, ceiling=50_000_000)
    _band(world, floor=5_000_000, ceiling=8_000_000, origin="A", destination="D")
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id, unit_price_minor=20_000_000)
        )
    assert info.value.code is ErrorCode.PRICE_OUT_OF_BAND and info.value.details["ceiling_minor"] == 8_000_000
