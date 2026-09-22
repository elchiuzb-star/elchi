"""Wave 10: choosing a direction by district, and the requests of the districts along the way.

The scenario the user described on 17.09.2026: a driver picks **Toshkent -> Qarshi**; the requests of the
districts the road passes (Chiroqchi, Kitob, ...) must reach that driver as recommendations.

What these tests pin down is *why* such a request shows up. It is never "the district belongs to the same
region" - the spec forbids exactly that shortcut (§6.1, §6.5). It is the order of the confirmed route: the
pickup sits after the driver's origin and the dropoff before the driver's destination, so serving it does not
leave the road the driver agreed to. A district end is only a way to say "anywhere in this district" instead
of naming one stop.
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

# The a1 world puts every stop of the Toshkent - Qarshi corridor in one district; a direction chosen by
# district only means something when the stops are spread the way real geography is.
DISTRICT_OF_STOP = {"A": "Toshkent shahri", "B": "Kattaqo'rg'on", "C": "Chiroqchi", "D": "Qarshi"}


@pytest.fixture
def districts(world: World) -> dict[str, str]:
    """Give each stop its own district and return ``{stop name: district public id}``."""
    ids: dict[str, str] = {}
    with world.db.session() as s:
        regions = {
            row.code: row.id
            for row in s.execute(text("SELECT id, code FROM regions WHERE code IN ('UZ-TK', 'UZ-QA')")).all()
        }
        for stop_name, district_name in DISTRICT_OF_STOP.items():
            region_id = regions["UZ-TK"] if stop_name == "A" else regions["UZ-QA"]
            # The world already owns a "Chiroqchi" row; the unique index per region means get-or-create.
            row = s.execute(
                text("SELECT id, public_id FROM geo_districts WHERE region_id = :r AND lower(name_uz) = lower(:n)"),
                {"r": region_id, "n": district_name},
            ).one_or_none()
            if row is None:
                row = s.execute(
                    text(
                        "INSERT INTO geo_districts (public_id, region_id, name_uz) "
                        "VALUES (gen_random_uuid(), :r, :n) RETURNING id, public_id"
                    ),
                    {"r": region_id, "n": district_name},
                ).one()
            s.execute(
                text("UPDATE corridor_stops SET geo_district_id = :d WHERE id = :s"),
                {"d": row.id, "s": world.stop_ids[stop_name]},
            )
            ids[stop_name] = format_public_id(PublicIdPrefix.DISTRICT, row.public_id)
        # The corridor must be publicly visible for its stops to count in the catalogue.
        s.execute(text("UPDATE service_corridors SET rollout_state = 'pilot' WHERE id = :c"), {"c": world.corridor_id})
        s.commit()
    return ids


def publish(world: World, owner_id: int, origin: str, destination: str) -> str:
    body = passenger_request(world, start=world.base_time, seats=1).model_dump(mode="json")
    body["origin_stop_id"] = world.stop_public_ids[origin]
    body["destination_stop_id"] = world.stop_public_ids[destination]
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
    items = driver_feed(
        world, origin_stop_id=world.stop_public_ids["A"], destination_stop_id=world.stop_public_ids["D"]
    )
    found = {listing_id: (match, reasons) for listing_id, match, reasons in items}
    assert on_the_way in found, "a district on the confirmed route must be recommended, not filtered out"
    match, reasons = found[on_the_way]
    assert match is MatchType.ON_ROUTE
    assert MatchReason.INTERMEDIATE_SEGMENT in reasons


def test_the_driver_can_ask_for_one_district_instead_of_one_stop(world: World, districts: dict[str, str]) -> None:
    listing_id = publish(world, world.client_id, "C", "D")
    by_district = driver_feed(world, origin_district_id=districts["C"], destination_district_id=districts["D"])
    assert [row[0] for row in by_district] == [listing_id]
    # Naming the district is the same question as naming its only stop - the answer must not differ.
    by_stop = driver_feed(
        world, origin_stop_id=world.stop_public_ids["C"], destination_stop_id=world.stop_public_ids["D"]
    )
    assert [row[0] for row in by_stop] == [listing_id]
    assert by_district[0][1] is by_stop[0][1]


def test_the_opposite_direction_is_still_refused(world: World, districts: dict[str, str]) -> None:
    """AC16 with districts: Qarshi -> Chiroqchi is not "on the way" of Toshkent -> Qarshi."""
    publish(world, world.client_id, "D", "C")
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
    assert items == [], "a district with no stop on the route resolves to no stops, so it matches nothing"


def test_one_end_carries_exactly_one_kind_of_reference(world: World, districts: dict[str, str]) -> None:
    with pytest.raises(DomainError) as both:
        driver_feed(
            world,
            origin_stop_id=world.stop_public_ids["A"],
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
            "side": "offers",
            "origin_district_id": districts["C"],
            "destination_district_id": districts["D"],
            "time_window_start": world.base_time.isoformat(),
            "time_window_end": (world.base_time + timedelta(hours=5)).isoformat(),
            "quantity": 1,
        }
    )
    with world.db.session() as s:
        row = feed_service.create_saved_search(s, user_id=world.client_id, data=body)
        s.commit()
        assert row.origin_district_id is not None and row.origin_stop_id is None and row.origin_region_id is None
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
    with pytest.raises(ValueError, match="exactly one of origin_stop_id"):
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
