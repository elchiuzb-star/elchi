"""Wave 1.6 on PostgreSQL: N1 terms_version vs version, N5 detour seconds, R1 open auction, R2 DTOs."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

import app.modules.geo.service as geo_service
from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingPatch, ProposalCounter
from app.modules.marketplace.views import listing_offer_dtos, listing_public_dto, thread_dto
from app.modules.trips import service as trips_service
from app.modules.trips.schemas import TripPatch
from app.modules.trips.views import trip_dto, trip_public_dto
from tests.pg.identity.a1_world import World, make_trip, make_vehicle
from tests.pg.marketplace.test_marketplace_pg import driver_trip, open_thread, proposal, published_request

pytestmark = pytest.mark.pg

IDENTITY_KEYS = {"name", "display_name", "full_name", "phone", "plate", "plate_masked", "plate_number", "make_model", "color", "photo", "driver_id", "trip_id", "user_id"}


def identity_keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        found = {k for k, v in value.items() if k in IDENTITY_KEYS and v is not None}
        for v in value.values():
            found |= identity_keys_in(v)
        return found
    if isinstance(value, list):
        return set().union(*(identity_keys_in(v) for v in value)) if value else set()
    return set()


# --- N1 ---------------------------------------------------------------------------------------------


def test_n1_non_material_edit_bumps_version_only(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        listing = marketplace_service.patch_listing(
            s, listing_public_id=listing_id, actor_user_id=world.client_id, data=ListingPatch(expected_version=2, comment="bekatda kutaman")
        )
        assert (listing.version, listing.terms_version) == (3, 1)
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        assert thread.state == "open"
        assert marketplace_service.current_version(s, thread).listing_terms_version == listing.terms_version
        s.commit()


@pytest.mark.parametrize(
    "patch_body",
    [
        {"passenger": {"seat_count": 2, "adults": 2, "baggage": {"pieces": 2, "total_weight_g": 30_000, "total_volume_ml": 90_000}}},
        {"passenger": {"seat_count": 3, "adults": 3}},
    ],
)
def test_n1_demand_edits_expire_proposals_and_bump_terms_version(world: World, patch_body: dict) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        listing = marketplace_service.patch_listing(
            s, listing_public_id=listing_id, actor_user_id=world.client_id, data=ListingPatch.model_validate({"expected_version": 2, **patch_body})
        )
        assert (listing.version, listing.terms_version) == (3, 2)
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        assert (thread.state, marketplace_service.current_version(s, thread).status_reason) == ("closed", "listing_changed")
        s.commit()


def test_n1_amenities_edit_is_not_material(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    body = {
        "expected_version": 2,
        "passenger": {"seat_count": 2, "adults": 2, "amenities": ["air_conditioning"], "special_assistance": "yordam",
                      "baggage": {"pieces": 1, "total_weight_g": 15_000, "total_volume_ml": 40_000}},
    }
    with world.db.session() as s:
        listing = marketplace_service.patch_listing(s, listing_public_id=listing_id, actor_user_id=world.client_id, data=ListingPatch.model_validate(body))
        assert listing.terms_version == 1
        assert marketplace_service.get_thread_by_public_id(s, thread_public_id).state == "open"


# --- N5 ---------------------------------------------------------------------------------------------


def test_n5_detour_seconds_and_route_public_id_reach_route_matching(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    listing_id = published_request(world)
    trip_id, trip_public_id = driver_trip(world)
    with world.db.session() as s:
        s.execute(text("UPDATE trips SET detour_used_s = 125 WHERE id = :t"), {"t": trip_id})
        s.commit()
    seen = []
    original = geo_service.evaluate_route_match

    def spy(context, request, **kwargs):  # noqa: ANN001, ANN202
        seen.append(context)
        return original(context, request, **kwargs)

    monkeypatch.setattr(geo_service, "evaluate_route_match", spy)
    with world.db.session() as s:
        marketplace_service.submit_proposal(s, listing_public_id=listing_id, actor_user_id=world.driver_id, data=proposal(world, trip_public_id))
        dto = trip_dto(s, trips_service.get_trip(s, trip_id))
        assert (dto.detour_used_s, dto.detour_used_minutes) == (125, 3)
        with pytest.raises(DomainError) as info:
            trips_service.patch_trip(
                s, trip_public_id_value=trip_public_id, actor_user_id=world.driver_id, data=TripPatch(expected_version=1, max_detour_minutes=2)
            )
        assert info.value.code is ErrorCode.VALIDATION_ERROR
    assert seen and seen[0].detour_used_s == 125 and seen[0].route_version_public_id == world.route_public_id


def test_n5_migration_constraint_on_detour_seconds(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01L100LL")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    from sqlalchemy.exc import IntegrityError

    with world.db.session() as s, pytest.raises(IntegrityError, match="ck_trips_detour_used_s"):
        s.execute(text("UPDATE trips SET detour_used_s = max_detour_minutes * 60 + 1 WHERE id = :t"), {"t": trip_id})


# --- R1 ---------------------------------------------------------------------------------------------


def _second_driver_offer(world: World, listing_id: str) -> str:
    vehicle = make_vehicle(world, world.driver2_id, "01M200MM", seats=7)
    _, trip_public_id = make_trip(world, world.driver2_id, vehicle, start=world.base_time, seats=6)
    with world.db.session() as s:
        thread = marketplace_service.submit_proposal(
            s, listing_public_id=listing_id, actor_user_id=world.driver2_id, data=proposal(world, trip_public_id, unit_price_minor=18_000_000)
        )
        s.commit()
        return marketplace_service.thread_public_id(thread)


def _offers(world: World, listing_id: str, viewer: int) -> list[dict]:
    with world.db.session() as s:
        return [
            dto.model_dump(mode="json")
            for dto in listing_offer_dtos(s, marketplace_service.list_listing_offers(s, listing_public_id=listing_id, viewer_user_id=viewer))
        ]


def test_r1_drivers_see_anonymized_offers_with_stable_labels(world: World) -> None:
    listing_id, first_thread, _ = open_thread(world)  # driver 1, 19 000 000 per seat
    _second_driver_offer(world, listing_id)
    for_driver2 = _offers(world, listing_id, world.driver2_id)
    assert [(o["label"], o["is_mine"], o["unit_price_minor"]) for o in for_driver2] == [
        ("Haydovchi #1", False, 19_000_000),
        ("Haydovchi #2", True, 18_000_000),
    ]
    assert for_driver2[1]["vehicle_class"] == "minivan" and for_driver2[1]["seat_capacity"] == 6
    assert not identity_keys_in(for_driver2)
    assert _offers(world, listing_id, world.driver2_id) == for_driver2  # stable across calls
    assert [o["is_mine"] for o in _offers(world, listing_id, world.driver_id)] == [True, False]
    del first_thread


def test_r1_labels_differ_between_listings(world: World) -> None:
    first_listing, _, _ = open_thread(world)  # driver 1 is "#1" here
    second_listing = published_request(world, origin="B", destination="D")
    _second_driver_offer(world, second_listing)  # driver 2 is "#1" on the second listing
    labels_first = {o["is_mine"]: o["label"] for o in _offers(world, first_listing, world.driver_id)}
    labels_second = {o["is_mine"]: o["label"] for o in _offers(world, second_listing, world.driver_id)}
    assert labels_first == {True: "Haydovchi #1"}
    assert labels_second == {False: "Haydovchi #1"}


def test_r1_client_counter_stays_private(world: World) -> None:
    listing_id, thread_public_id, _ = open_thread(world)
    with world.db.session() as s:
        marketplace_service.counter_proposal(
            s, thread_public_id_value=thread_public_id, actor_user_id=world.client_id, data=ProposalCounter(expected_revision=1, unit_price_minor=12_000_000)
        )
        s.commit()
    offers = _offers(world, listing_id, world.driver2_id)
    assert [(o["revision"], o["unit_price_minor"]) for o in offers] == [(1, 19_000_000)]


@pytest.mark.parametrize("viewer", ["client", "owner", "blocked_driver"])
def test_r1_offers_hidden_from_non_eligible_viewers(world: World, viewer: str) -> None:
    listing_id, _, _ = open_thread(world)
    viewer_id = {"client": world.client2_id, "owner": world.client_id, "blocked_driver": world.driver2_id}[viewer]
    if viewer == "blocked_driver":
        with world.db.session() as s:
            identity_service.block_driver_eligibility(s, driver_user_id=world.driver2_id, actor_user_id=world.admin_id, expected_version=1, reason="docs")
            s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        marketplace_service.list_listing_offers(s, listing_public_id=listing_id, viewer_user_id=viewer_id)
    assert info.value.code is ErrorCode.NOT_FOUND


# --- R2 ---------------------------------------------------------------------------------------------


def test_r2_pre_accept_dtos_carry_no_identity(world: World) -> None:
    listing_id, thread_public_id, trip_id = open_thread(world)
    with world.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_id)
        public = listing_public_dto(s, listing).model_dump(mode="json")
        assert "owner_display_name" not in public and not identity_keys_in({k: v for k, v in public.items() if k != "trip_id"})
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        for viewer in (world.client_id, world.driver_id):
            parties = thread_dto(s, thread, viewer_user_id=viewer, include_versions=True).model_dump(mode="json")
            assert not identity_keys_in({"client": parties["client"], "driver": parties["driver"], "versions": parties["versions"]})
        trip_public = trip_public_dto(s, trips_service.get_trip(s, trip_id)).model_dump(mode="json")
        assert trip_public["vehicle"] == {"vehicle_class": "car", "seat_capacity": 4}


# --- U6 rating bucket (user decision 17.09.2026, option A) ------------------------------------------


def _rate(world: World, driver_user_id: int, stars: list[int]) -> None:
    """Write a reputation snapshot straight to the table: this test is about the DTO, not about A12's writer."""
    with world.db.session() as s:
        s.execute(
            text(
                "INSERT INTO reputation_snapshots (user_id, service_type, rating_count, rating_sum, "
                "completed_bookings, completed_trips, eligible_resolved, on_time_count, computed_at) "
                "VALUES (:u, 'passenger', :n, :total, :n, :n, :n, :n, now()) "
                "ON CONFLICT (user_id, service_type) DO UPDATE SET rating_count = EXCLUDED.rating_count, "
                "rating_sum = EXCLUDED.rating_sum, completed_bookings = EXCLUDED.completed_bookings"
            ),
            {"u": driver_user_id, "n": len(stars), "total": sum(stars)},
        )
        s.commit()


def test_u6_offer_card_carries_the_bucket_and_its_count_but_no_identity(world: World) -> None:
    listing_id, _thread, _ = open_thread(world)
    _second_driver_offer(world, listing_id)
    _rate(world, world.driver_id, [5, 5, 4, 5])       # average 4.75 over 4 ratings -> good
    _rate(world, world.driver2_id, [5])               # a single five-star rating -> still "new"

    cards = {o["label"]: o for o in _offers(world, listing_id, world.driver2_id)}
    first, second = cards["Haydovchi #1"], cards["Haydovchi #2"]

    assert (first["rating_bucket"], first["rating_count"]) == ("good", 4)
    assert (second["rating_bucket"], second["rating_count"]) == ("new_verified", 1), (
        "§8.2: one rating must not look like a track record"
    )
    assert not identity_keys_in(list(cards.values())), "the bucket must not drag a name or phone in with it"
    assert "adjusted_rating" not in first and "average_rating" not in first, "internal ranking value stays internal"


def test_u6_a_driver_nobody_rated_yet_gets_no_score(world: World) -> None:
    listing_id, _thread, _ = open_thread(world)
    card = _offers(world, listing_id, world.driver_id)[0]
    assert card["rating_bucket"] == "new_verified"
    assert card["rating_count"] == 0, "zero ratings is reported as zero ratings, not as a zero rating"
