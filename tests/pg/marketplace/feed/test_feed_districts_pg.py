"""Wave 10: choosing a direction by district, and the requests of the districts along the way.

The scenario the user described on 17.09.2026: a driver picks **Toshkent -> Qarshi**; the requests of the
districts the road passes (Chiroqchi, Kitob, ...) must reach that driver as recommendations.

What these tests pin down is *why* such a request shows up. It is never "the district belongs to the same
region" - the spec forbids exactly that shortcut (§6.1, §6.5). It is the order of the confirmed route: the
pickup sits after the driver's origin and the dropoff before the driver's destination, so serving it does not
leave the road the driver agreed to. A district end is only a way to say "anywhere in this district" instead
of naming one place (ADR-0028 / Q160: there are no stops; the district's centre places it on the road).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.enums import FeedSide, MatchReason, MatchType, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.feed import service as feed_service
from app.modules.marketplace.feed.schemas import SavedSearchCreate
from app.modules.marketplace.schemas import ListingCreate
from tests.pg.identity.a1_world import World, passenger_request

pytestmark = pytest.mark.pg

@pytest.fixture
def districts(world: World) -> dict[str, str]:
    """``{place: district public id}`` - the a1 world puts each place in its own district (centre = the place)."""
    return dict(world.district_public_ids)


def publish(world: World, owner_id: int, origin: str, destination: str) -> str:
    body = passenger_request(world, start=world.base_time, seats=1).model_dump(mode="json")
    body["origin_point"] = world.point(origin)
    body["destination_point"] = world.point(destination)
    data = ListingCreate.model_validate(body)
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=owner_id, data=data)
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(s, listing_public_id=public_id, actor_user_id=owner_id, expected_version=1)
        s.commit()
    return public_id


def driver_feed(world: World, **ends: str):  # noqa: ANN201
    criteria = feed_service.FeedCriteria(
        service_type=ServiceType.PASSENGER,
        side=FeedSide.REQUESTS,
        date_from=world.base_time - timedelta(hours=1),
        date_to=world.base_time + timedelta(hours=3),
        **ends,
    )
    with world.db.session() as s:
        page = feed_service.feed(s, viewer_user_id=world.driver_id, criteria=criteria)
        return [
            (marketplace_service.listing_public_id(item.listing), item.match_type, item.reasons) for item in page.items
        ]


def test_a_request_from_a_district_along_the_way_reaches_the_driver(world: World, districts: dict[str, str]) -> None:
    """Toshkent -> Qarshi driver, Chiroqchi -> Qarshi client: recommended, and labelled as an intermediate leg."""
    on_the_way = publish(world, world.client_id, "C", "D")
    items = driver_feed(world, origin_district_id=districts["A"], destination_district_id=districts["D"])
    found = {listing_id: (match, reasons) for listing_id, match, reasons in items}
    assert on_the_way in found, "a district on the confirmed route must be recommended, not filtered out"
    match, reasons = found[on_the_way]
    assert match is MatchType.ON_ROUTE
    assert MatchReason.INTERMEDIATE_SEGMENT in reasons


def test_the_driver_can_ask_for_one_district(world: World, districts: dict[str, str]) -> None:
    listing_id = publish(world, world.client_id, "C", "D")
    by_district = driver_feed(world, origin_district_id=districts["C"], destination_district_id=districts["D"])
    assert [row[0] for row in by_district] == [listing_id]
    assert by_district[0][1] is MatchType.EXACT  # both places lie in the asked districts


def test_the_opposite_direction_is_still_refused(world: World, districts: dict[str, str]) -> None:
    """AC16 with districts: Qarshi -> Chiroqchi is not "on the way" of Toshkent -> Qarshi."""
    with pytest.raises(DomainError) as info:  # ADR-0028: against the road it is not a request at all
        publish(world, world.client_id, "D", "C")
    assert info.value.code is ErrorCode.ROUTE_MISMATCH
    items = driver_feed(
        world, origin_district_id=districts["A"], destination_district_id=districts["D"]
    )
    assert items == []


def test_a_district_off_the_confirmed_route_recommends_nothing(world: World, districts: dict[str, str]) -> None:
    """A district may exist in the same region and still not be on the road (spec §6.1)."""
    with world.db.session() as s:
        far = s.execute(
            text(
                "INSERT INTO geo_districts (public_id, region_id, name_uz) "
                "SELECT gen_random_uuid(), id, 'Uzoq tuman' FROM regions WHERE code = 'UZ-QA' RETURNING public_id"
            )
        ).scalar_one()
        s.commit()
    publish(world, world.client_id, "C", "D")
    items = driver_feed(
        world,
        origin_district_id=format_public_id(PublicIdPrefix.DISTRICT, far),
        destination_district_id=districts["D"],
    )
    assert items == [], "a district with no known centre on the road is placed nowhere, so it matches nothing"


def test_one_end_carries_exactly_one_kind_of_reference(world: World, districts: dict[str, str]) -> None:
    with pytest.raises(DomainError) as both:
        driver_feed(
            world,
            origin_region_id=world.region_public_ids["UZ-TK"],
            origin_district_id=districts["A"],
            destination_district_id=districts["D"],
        )
    assert both.value.code is ErrorCode.VALIDATION_ERROR
    with pytest.raises(DomainError):
        driver_feed(world, destination_district_id=districts["D"])


def test_a_saved_search_remembers_the_district(world: World, districts: dict[str, str]) -> None:
    body = SavedSearchCreate.model_validate(
        {
            "service_type": "passenger",
            "side": "requests",  # ADR-0026: a driver's search of client requests
            "origin_district_id": districts["C"],
            "destination_district_id": districts["D"],
            "time_window_start": world.base_time.isoformat(),
            "time_window_end": (world.base_time + timedelta(hours=5)).isoformat(),
            "quantity": 1,
        }
    )
    with world.db.session() as s:
        row = feed_service.create_saved_search(s, user_id=world.driver_id, data=body)
        s.commit()
        assert row.origin_district_id is not None and row.origin_region_id is None
        stored = s.execute(
            text(
                "SELECT num_nonnulls(origin_stop_id, origin_region_id, origin_district_id) AS origin_refs, "
                "num_nonnulls(destination_stop_id, destination_region_id, destination_district_id) AS dest_refs "
                "FROM saved_searches WHERE id = :i"
            ),
            {"i": row.id},
        ).one()
    assert (stored.origin_refs, stored.dest_refs) == (1, 1)


def test_a_saved_search_with_two_references_on_one_end_is_refused(world: World, districts: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="exactly one of origin_district_id"):
        SavedSearchCreate.model_validate(
            {
                "service_type": "passenger",
                "side": "offers",
                "origin_district_id": districts["C"],
                "origin_region_id": "reg_00000000000000000000000000",
                "destination_district_id": districts["D"],
                "time_window_start": world.base_time.isoformat(),
                "time_window_end": (world.base_time + timedelta(hours=5)).isoformat(),
            }
        )
