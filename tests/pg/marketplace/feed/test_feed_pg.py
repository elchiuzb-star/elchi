"""PostgreSQL tests for the feed, matches and saved searches (A5, wave 3; AC16, AC18, AC36, Q21, §6.6, §8)."""

from __future__ import annotations

import dataclasses
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.api.v2.web import current_user_id, db_error_handler, domain_error_handler, get_session
from app.contracts.communications import DispatchedEvent
from app.contracts.enums import (
    EventType,
    FeedSide,
    FeedSort,
    MatchGroup,
    MatchReason,
    MatchType,
    ReputationLabel,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.feed import RANKING_VERSION, SAVED_SEARCH_MAX_PER_USER
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.contracts.trust import ReputationSummary
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.feed import api as feed_api
from app.modules.marketplace.feed import consumers
from app.modules.marketplace.feed import service as feed_service
from app.modules.marketplace.feed.models import FEED_TABLES, SavedSearch, SavedSearchNotification
from app.modules.marketplace.feed.schemas import SavedSearchCreate
from app.modules.marketplace.schemas import ListingCreate
from app.modules.platform.models import OutboxEvent
from app.modules.platform.service import constraint_name_of
from tests.pg.conftest import PgDatabase
from tests.pg.identity.a1_world import World, add_user, make_trip, make_vehicle, passenger_offer, passenger_request, run_in_thread

pytestmark = pytest.mark.pg

MIGRATION_0061 = Path(__file__).resolve().parents[4] / "alembic" / "versions" / "20260916_0061_marketplace_saved_searches.py"


# --- builders -----------------------------------------------------------------------------------------------------------


def publish_offer(world: World, driver_id: int, plate: str, *, unit_price: int = 20_000_000) -> str:
    vehicle = make_vehicle(world, driver_id, plate)
    _, trip_public_id = make_trip(world, driver_id, vehicle, start=world.base_time)
    with world.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=driver_id, data=passenger_offer(world, trip_public_id, start=world.base_time, unit_price_minor=unit_price)
        )
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(s, listing_public_id=public_id, actor_user_id=driver_id, expected_version=1)
        s.commit()
    return public_id


def publish_offer_at(world: World, driver_id: int, plate: str, *, start) -> str:  # noqa: ANN001 - datetime
    """Like ``publish_offer`` but with the trip at a chosen hour, so a near miss can be built."""
    vehicle = make_vehicle(world, driver_id, plate)
    _, trip_public_id = make_trip(world, driver_id, vehicle, start=start)
    with world.db.session() as s:
        listing = marketplace_service.create_listing(
            s, owner_user_id=driver_id, data=passenger_offer(world, trip_public_id, start=start)
        )
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(s, listing_public_id=public_id, actor_user_id=driver_id, expected_version=1)
        s.commit()
    return public_id


def publish_request(world: World, owner_id: int, body: ListingCreate) -> str:
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=owner_id, data=body)
        public_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(s, listing_public_id=public_id, actor_user_id=owner_id, expected_version=1)
        s.commit()
    return public_id


def total_request(world: World, *, total: int, seats: int = 2) -> ListingCreate:
    body = passenger_request(world, start=world.base_time, seats=seats).model_dump(mode="json")
    return ListingCreate.model_validate({**body, "price_basis": "total", "unit_price_minor": total})


def third_driver(world: World) -> int:
    with world.db.session() as s:
        driver = add_user(s, "+998900000303", "driver", full_name="Sardor Umarov", driver_status="approved")
        s.commit()
    return driver


def offers(world: World, **overrides: object) -> feed_service.FeedCriteria:
    values = {
        "service_type": ServiceType.PASSENGER,
        "side": FeedSide.OFFERS,
        "origin_stop_id": world.stop_public_ids["B"],
        "destination_stop_id": world.stop_public_ids["D"],
        "date_from": world.base_time,
        "date_to": world.base_time + timedelta(hours=4),
        "seats": 1,
    }
    values.update(overrides)
    return feed_service.FeedCriteria(**values)


def requests(world: World, **overrides: object) -> feed_service.FeedCriteria:
    values = {
        "service_type": ServiceType.PASSENGER,
        "side": FeedSide.REQUESTS,
        "origin_stop_id": world.stop_public_ids["A"],
        "destination_stop_id": world.stop_public_ids["D"],
        "date_from": world.base_time - timedelta(hours=1),
        "date_to": world.base_time + timedelta(hours=3),
    }
    values.update(overrides)
    return feed_service.FeedCriteria(**values)


def run_feed(world: World, viewer: int, criteria: feed_service.FeedCriteria, **kwargs: object):  # noqa: ANN201
    with world.db.session() as s:
        page = feed_service.feed(s, viewer_user_id=viewer, criteria=criteria, **kwargs)
        return page, [marketplace_service.listing_public_id(item.listing) for item in page.items]


def search_body(world: World, **overrides: object) -> SavedSearchCreate:
    values = {
        "service_type": "passenger",
        "side": "offers",
        "origin_stop_id": world.stop_public_ids["B"],
        "destination_stop_id": world.stop_public_ids["D"],
        "time_window_start": world.base_time.isoformat(),
        "time_window_end": (world.base_time + timedelta(hours=5)).isoformat(),
        "quantity": 1,
    }
    values.update(overrides)
    return SavedSearchCreate.model_validate(values)


def create_search(world: World, user_id: int, **overrides: object) -> str:
    with world.db.session() as s:
        row = feed_service.create_saved_search(s, user_id=user_id, data=search_body(world, **overrides))
        public_id = feed_service.saved_search_public_id(row)
        s.commit()
    return public_id


def region_public_id(world: World, code: str) -> str:
    with world.db.engine.connect() as conn:
        value = conn.execute(text("SELECT public_id FROM regions WHERE code = :c"), {"c": code}).scalar_one()
    return format_public_id(PublicIdPrefix.REGION, value)


def dispatched(world: World, event_type: EventType, aggregate_public_id: str | None = None) -> list[DispatchedEvent]:
    with world.db.session() as s:
        stmt = select(OutboxEvent).where(OutboxEvent.event_type == event_type.value)
        if aggregate_public_id is not None:
            stmt = stmt.where(OutboxEvent.aggregate_public_id == aggregate_public_id)
        return [
            DispatchedEvent(
                event_id=row.event_id,
                event_type=EventType(row.event_type),
                aggregate_type=row.aggregate_type,
                aggregate_public_id=row.aggregate_public_id,
                aggregate_id=row.aggregate_id,
                aggregate_version=row.aggregate_version,
                occurred_at=row.occurred_at,
                payload=dict(row.payload),
            )
            for row in s.execute(stmt.order_by(OutboxEvent.id)).scalars()
        ]


def fake_reputation(monkeypatch: pytest.MonkeyPatch, table: dict[int, dict[str, int]]) -> None:
    import app.modules.trust_support.service as trust_service

    def summaries(session, user_ids, *, service_type):  # noqa: ANN001, ANN202
        return {uid: ReputationSummary(user_id=uid, service_type=ServiceType(service_type), **table[uid]) for uid in user_ids if uid in table}

    monkeypatch.setattr(trust_service, "reputation_summaries", summaries)


# --- M1 -------------------------------------------------------------------------------------------------------------------


def test_ac18_offline_driver_with_future_trip_stays_in_feed_on_route_only(world: World) -> None:
    listing_id = publish_offer(world, world.driver_id, "01A500AA")
    page, ids = run_feed(world, world.client_id, offers(world))
    assert ids == [listing_id]  # no tracking / online signal needed (AC18)
    item = page.items[0]
    assert item.match_type is MatchType.ON_ROUTE and item.group is MatchGroup.PRIMARY  # B->D inside A->D, no detour (Q46)
    assert item.ready_to_accept and item.comparable_total_minor == 20_000_000
    assert item.reputation.label is ReputationLabel.NEW_VERIFIED and item.reputation.average_rating is None
    assert page.ranking_version == RANKING_VERSION


def test_ac16_reverse_direction_is_not_in_the_feed(world: World) -> None:
    publish_offer(world, world.driver_id, "01A501AA")
    publish_request(world, world.client_id, passenger_request(world, start=world.base_time, origin="B", destination="C"))
    _, reverse_offers = run_feed(world, world.client2_id, offers(world, origin_stop_id=world.stop_public_ids["D"], destination_stop_id=world.stop_public_ids["B"]))
    _, reverse_requests = run_feed(world, world.driver_id, requests(world, origin_stop_id=world.stop_public_ids["D"], destination_stop_id=world.stop_public_ids["A"]))
    _, forward_requests = run_feed(world, world.driver_id, requests(world))
    assert reverse_offers == [] and reverse_requests == []
    assert len(forward_requests) == 1


def test_q21_blocked_driver_offer_is_hidden(world: World) -> None:
    visible = publish_offer(world, world.driver_id, "01A502AA")
    hidden = publish_offer(world, world.driver2_id, "01A503AA")
    _, before = run_feed(world, world.client_id, offers(world))
    assert set(before) == {visible, hidden}
    with world.db.session() as s:
        version = identity_service.eligibility_version(s, world.driver2_id)
        identity_service.block_driver_eligibility(
            s, driver_user_id=world.driver2_id, actor_user_id=world.admin_id, expected_version=version, reason="documents"
        )
        s.commit()
    _, after = run_feed(world, world.client_id, offers(world))
    assert after == [visible]


def test_ac36_many_ratings_rank_above_a_single_five_star(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    single = publish_offer(world, world.driver_id, "01A504AA")
    many = publish_offer(world, world.driver2_id, "01A505AA")
    fake_reputation(monkeypatch, {world.driver_id: {"rating_count": 1, "rating_sum": 5}, world.driver2_id: {"rating_count": 200, "rating_sum": 960}})
    for sort in (FeedSort.RECOMMENDED, FeedSort.RATING):
        page, ids = run_feed(world, world.client_id, offers(world, sort=sort))
        assert ids == [many, single], sort
    assert [item.reputation.rating_count for item in page.items] == [200, 1]  # counts are shown


def test_total_price_comparison_for_the_same_quantity(world: World) -> None:
    per_seat = publish_request(world, world.client_id, passenger_request(world, start=world.base_time, seats=2, unit_price_minor=20_000_000))
    total = publish_request(world, world.client2_id, total_request(world, total=39_000_000))
    page, ids = run_feed(world, world.driver_id, requests(world, sort=FeedSort.CHEAPEST))
    assert ids == [total, per_seat]  # 39 000 000 total < 2 x 20 000 000, although its "unit" is higher
    assert [item.comparable_total_minor for item in page.items] == [39_000_000, 40_000_000]


def test_driver_score_does_not_reward_the_cheaper_request(world: World) -> None:
    expensive = publish_request(world, world.client_id, passenger_request(world, start=world.base_time, unit_price_minor=20_000_000))
    cheap = publish_request(world, world.client2_id, passenger_request(world, start=world.base_time, unit_price_minor=10_000_000))
    page, ids = run_feed(world, world.driver_id, requests(world))
    scores = {marketplace_service.listing_public_id(i.listing): i for i in page.items}
    assert set(ids) == {expensive, cheap}
    assert scores[cheap].score <= scores[expensive].score
    assert scores[cheap].components["Y"] <= scores[expensive].components["Y"]


def test_requests_feed_needs_driver_capability(world: World) -> None:
    with world.db.session() as s, pytest.raises(DomainError) as info:
        feed_service.feed(s, viewer_user_id=world.client_id, criteria=requests(world))
    assert info.value.code in (ErrorCode.CAPABILITY_REQUIRED, ErrorCode.DRIVER_NOT_ELIGIBLE)


def test_cursor_is_stable_and_bound_to_its_query(world: World) -> None:
    driver3 = third_driver(world)
    expected = {
        publish_offer(world, world.driver_id, "01A506AA", unit_price=20_000_000),
        publish_offer(world, world.driver2_id, "01A507AA", unit_price=19_000_000),
        publish_offer(world, driver3, "01A508AA", unit_price=18_000_000),
    }
    first, first_ids = run_feed(world, world.client_id, offers(world, sort=FeedSort.CHEAPEST), limit=2)
    assert len(first_ids) == 2 and first.next_key is not None
    second, second_ids = run_feed(world, world.client_id, offers(world, sort=FeedSort.CHEAPEST), limit=2, after_key=first.next_key)
    assert second.next_key is None and set(first_ids) | set(second_ids) == expected and not set(first_ids) & set(second_ids)

    client = http_client(world, world.client_id)
    params = {
        "service_type": "passenger", "side": "offers", "origin_stop_id": world.stop_public_ids["B"],
        "destination_stop_id": world.stop_public_ids["D"], "date_from": world.base_time.isoformat(),
        "date_to": (world.base_time + timedelta(hours=4)).isoformat(), "sort": "cheapest", "limit": 2,
    }
    response = client.get("/api/v2/feed", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["ranking_version"] == RANKING_VERSION and len(body["data"]) == 2
    assert "owner" not in body["data"][0]["listing"] and body["data"][0]["reputation"]["average_rating"] is None
    cursor = body["meta"]["next_cursor"]
    assert len(client.get("/api/v2/feed", params={**params, "cursor": cursor}).json()["data"]) == 1
    other = client.get("/api/v2/feed", params={**params, "sort": "time", "cursor": cursor})
    assert other.status_code == 400 and other.json()["error"]["code"] == "INVALID_CURSOR"


# --- M2 -------------------------------------------------------------------------------------------------------------------


def test_m2_matches_for_owner_only(world: World) -> None:
    offer = publish_offer(world, world.driver_id, "01A509AA")
    request = publish_request(world, world.client_id, passenger_request(world, start=world.base_time, seats=2))
    with world.db.session() as s:
        page = feed_service.listing_matches(s, listing_public_id=request, viewer_user_id=world.client_id)
        assert [marketplace_service.listing_public_id(i.listing) for i in page.items] == [offer]
        assert page.items[0].availability.min_remaining_seats == 4
        driver_page = feed_service.listing_matches(s, listing_public_id=offer, viewer_user_id=world.driver_id)
        assert [marketplace_service.listing_public_id(i.listing) for i in driver_page.items] == [request]
        with pytest.raises(DomainError) as info:
            feed_service.listing_matches(s, listing_public_id=request, viewer_user_id=world.client2_id)
        assert info.value.code is ErrorCode.NOT_FOUND


# --- the alternative group (§6.4, §8.2) ------------------------------------------------------------------------------------


def test_a_trip_two_hours_late_is_invisible_until_alternatives_are_asked_for(world: World) -> None:
    """The near miss is opt-in, and it is a *separate* answer.

    A driver leaving two hours after the client asked is not a match - offering it as one would put someone at
    a kerb at the wrong time. But it is the only thing on that road that day, so hiding it entirely is how a
    thin pilot market looks empty. The server therefore returns it only when asked, marked `alternative` and
    ranked below every real match, and this is what proves both halves of that.
    """
    late = world.base_time + timedelta(hours=2)
    offer = publish_offer_at(world, world.driver_id, "01A520AA", start=late)
    request = publish_request(world, world.client_id, passenger_request(world, start=world.base_time, seats=2))

    with world.db.session() as s:
        strict = feed_service.listing_matches(s, listing_public_id=request, viewer_user_id=world.client_id)
        assert [marketplace_service.listing_public_id(i.listing) for i in strict.items] == []

        widened = feed_service.listing_matches(
            s, listing_public_id=request, viewer_user_id=world.client_id, include_alternatives=True
        )
        assert [marketplace_service.listing_public_id(i.listing) for i in widened.items] == [offer]
        item = widened.items[0]
        assert item.group is MatchGroup.ALTERNATIVE
        assert item.match_type is MatchType.ALTERNATIVE
        # The reason is what the client renders as "Vaqti boshqa"; without it the badge says nothing.
        assert MatchReason.TIME_DIFFERS in item.reasons


def test_alternatives_never_push_a_real_match_down(world: World) -> None:
    """Asking for suggestions must not cost the driver the results. The primary group always comes first."""
    on_time = publish_offer(world, world.driver_id, "01A521AA")
    late = publish_offer_at(world, third_driver(world), "01A522AA", start=world.base_time + timedelta(hours=2))
    request = publish_request(world, world.client_id, passenger_request(world, start=world.base_time, seats=2))

    with world.db.session() as s:
        page = feed_service.listing_matches(
            s, listing_public_id=request, viewer_user_id=world.client_id, include_alternatives=True
        )
        ids = [marketplace_service.listing_public_id(i.listing) for i in page.items]
        assert ids == [on_time, late], "the alternative must rank after every primary match"
        assert page.items[0].group is MatchGroup.PRIMARY
        assert page.items[1].group is MatchGroup.ALTERNATIVE


# --- M3-M5 ----------------------------------------------------------------------------------------------------------------


def test_parallel_saved_search_creation_never_exceeds_the_limit(world: World) -> None:
    for _ in range(SAVED_SEARCH_MAX_PER_USER - 1):
        create_search(world, world.client_id)

    def attempt() -> str:
        with world.db.session() as s:
            try:
                feed_service.create_saved_search(s, user_id=world.client_id, data=search_body(world))
                s.commit()
                return "created"
            except DomainError as exc:
                s.rollback()
                return exc.code.value

    runs = [run_in_thread(attempt) for _ in range(6)]
    for thread, _ in runs:
        thread.join()
    outcomes = sorted(outcome.get("value", repr(outcome.get("error"))) for _, outcome in runs)
    assert outcomes == ["SAVED_SEARCH_LIMIT_REACHED"] * 5 + ["created"]
    with world.db.session() as s:
        assert s.execute(select(func.count(SavedSearch.id)).where(SavedSearch.user_id == world.client_id)).scalar_one() == SAVED_SEARCH_MAX_PER_USER
        # DB guard alone (service bypassed)
        with pytest.raises(DBAPIError) as info:
            s.execute(
                text(
                    "INSERT INTO saved_searches (public_id, user_id, service_type, side, origin_stop_id, destination_stop_id, "
                    "time_window_start, time_window_end, quantity) VALUES (gen_random_uuid(), :u, 'passenger', 'offers', :o, :d, "
                    "now(), now() + interval '1 day', 1)"
                ),
                {"u": world.client_id, "o": world.stop_ids["B"], "d": world.stop_ids["D"]},
            )
        assert constraint_name_of(info.value) == "saved_search_limit"


def test_saved_search_http_limit_soft_delete_and_foreign_404(world: World) -> None:
    client = http_client(world, world.client_id)
    body = search_body(world).model_dump(mode="json")
    ids = []
    for n in range(SAVED_SEARCH_MAX_PER_USER):
        response = client.post("/api/v2/saved-searches", json=body, headers={"Idempotency-Key": f"svs-key-{n:04d}"})
        assert response.status_code == 201, response.text
        ids.append(response.json()["data"]["id"])
    over = client.post("/api/v2/saved-searches", json=body, headers={"Idempotency-Key": "svs-key-over"})
    assert over.status_code == 409 and over.json()["error"]["code"] == "SAVED_SEARCH_LIMIT_REACHED"
    assert over.json()["error"]["details"] == {"limit": SAVED_SEARCH_MAX_PER_USER}
    too_long = {**body, "time_window_end": (world.base_time + timedelta(days=61)).isoformat()}
    assert http_client(world, world.client2_id).post(
        "/api/v2/saved-searches", json=too_long, headers={"Idempotency-Key": "svs-key-long"}
    ).json()["error"]["code"] == "VALIDATION_ERROR"
    assert http_client(world, world.client2_id).delete(f"/api/v2/saved-searches/{ids[0]}").status_code == 404
    assert client.delete(f"/api/v2/saved-searches/{ids[0]}").status_code == 200
    assert client.delete(f"/api/v2/saved-searches/{ids[0]}").status_code == 404
    listed = client.get("/api/v2/me/saved-searches").json()["data"]
    assert len(listed) == SAVED_SEARCH_MAX_PER_USER - 1 and ids[0] not in {item["id"] for item in listed}


def test_duplicate_listing_published_gives_one_saved_search_matched(world: World) -> None:
    qa = region_public_id(world, "UZ-QA")
    client_stop_search = create_search(world, world.client_id)
    create_search(world, world.client_id, origin_stop_id=None, origin_region_id=qa)  # same user, second match
    client2_region_search = create_search(world, world.client2_id, origin_stop_id=None, origin_region_id=qa)
    create_search(world, world.driver2_id, side="requests")  # other side: no match
    listing_id = publish_offer(world, world.driver_id, "01A510AA")
    event = dispatched(world, EventType.LISTING_PUBLISHED, listing_id)[-1]
    for _ in range(2):  # redelivery
        with world.db.session() as s:
            consumers.saved_search_matcher(s, event)
            s.commit()
    matched = dispatched(world, EventType.SAVED_SEARCH_MATCHED)
    assert sorted(e.payload["saved_search_id"] for e in matched) == sorted([client_stop_search, client2_region_search])
    assert all(e.payload["listing_id"] == listing_id and e.payload["side"] == "offers" for e in matched)
    with world.db.session() as s:
        assert s.execute(select(func.count(SavedSearchNotification.id))).scalar_one() == 2
        assert all(consumers.RELEVANCE_CHECKS[EventType.SAVED_SEARCH_MATCHED](s, e) for e in matched)
        listing = marketplace_service.get_listing_by_public_id(s, listing_id)
        marketplace_service.cancel_listing(
            s, listing_public_id=listing_id, actor_user_id=world.driver_id, expected_version=listing.version, reason_code="plans_changed"
        )
        s.commit()
    with world.db.session() as s:
        assert not any(consumers.RELEVANCE_CHECKS[EventType.SAVED_SEARCH_MATCHED](s, e) for e in matched)


def test_l2_requests_saved_search_needs_driver_capability_at_create_and_notify(world: World) -> None:
    with world.db.session() as s, pytest.raises(DomainError) as info:
        feed_service.create_saved_search(s, user_id=world.client_id, data=search_body(world, side="requests", origin_stop_id=world.stop_public_ids["A"]))
    assert info.value.code in (ErrorCode.CAPABILITY_REQUIRED, ErrorCode.DRIVER_NOT_ELIGIBLE)
    eligible = create_search(world, world.driver_id, side="requests", origin_stop_id=world.stop_public_ids["A"])
    blocked = create_search(world, world.driver2_id, side="requests", origin_stop_id=world.stop_public_ids["A"])
    with world.db.session() as s:
        version = identity_service.eligibility_version(s, world.driver2_id)
        identity_service.block_driver_eligibility(
            s, driver_user_id=world.driver2_id, actor_user_id=world.admin_id, expected_version=version, reason="documents"
        )
        s.commit()
    listing_id = publish_request(world, world.client_id, passenger_request(world, start=world.base_time, seats=1))
    with world.db.session() as s:
        consumers.saved_search_matcher(s, dispatched(world, EventType.LISTING_PUBLISHED, listing_id)[-1])
        s.commit()
    matched = dispatched(world, EventType.SAVED_SEARCH_MATCHED)
    assert [e.payload["saved_search_id"] for e in matched] == [eligible]
    stale = dataclasses.replace(matched[0], payload={**matched[0].payload, "saved_search_id": blocked})
    with world.db.session() as s:
        assert consumers.RELEVANCE_CHECKS[EventType.SAVED_SEARCH_MATCHED](s, matched[0])
        assert not consumers.RELEVANCE_CHECKS[EventType.SAVED_SEARCH_MATCHED](s, stale)  # blocked later -> no push


def test_l9_unapproved_vehicle_offer_is_not_ready_to_accept(world: World) -> None:
    listing_id = publish_offer(world, world.driver_id, "01A511AA")
    with world.db.session() as s:
        listing_pk = marketplace_service.resolve_listing_id(s, listing_id)
    with world.db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE vehicles SET verification_status = 'pending' WHERE id = "
                "(SELECT t.vehicle_id FROM listings l JOIN trips t ON t.id = l.trip_id WHERE l.id = :l)"
            ),
            {"l": listing_pk},
        )
    page, ids = run_feed(world, world.client_id, offers(world))
    assert ids == [listing_id] and page.items[0].ready_to_accept is False


def test_expire_saved_searches_worker(world: World) -> None:
    now = utc_now()
    create_search(world, world.client_id, time_window_start=(now - timedelta(hours=1)).isoformat(), time_window_end=(now + timedelta(minutes=2)).isoformat())
    create_search(world, world.client_id)
    with world.db.session() as s:
        assert feed_service.expire_saved_searches(s, now=now + timedelta(minutes=3)) == 1
        s.commit()
        assert feed_service.expire_saved_searches(s, now=now + timedelta(minutes=3)) == 0
        assert sorted(s.execute(select(SavedSearch.notify)).scalars()) == [False, True]


# --- migration ------------------------------------------------------------------------------------------------------------


def test_0061_upgrade_is_idempotent_and_models_match(pg_db: PgDatabase) -> None:
    from alembic.autogenerate import compare_metadata

    import app.models  # noqa: F401
    import app.modules.marketplace.feed.models  # noqa: F401
    from app.db.base import Base

    spec = importlib.util.spec_from_file_location("migration_0061_pg", MIGRATION_0061)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for _ in range(2):
        with pg_db.engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_saved_searches_limit'")).scalar_one() == 1

        def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
            if type_ == "table" and reflected and compare_to is None:
                return name in Base.metadata.tables
            return True

        diffs = compare_metadata(
            MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True, "compare_server_default": False}),
            Base.metadata,
        )

    def touches_feed(diff: object) -> bool:
        for item in diff if isinstance(diff, list) else [diff]:
            for part in item:
                table = getattr(part, "table", None)
                if (getattr(table, "name", None) or getattr(part, "name", None)) in FEED_TABLES or part in FEED_TABLES:
                    return True
        return False

    feed_diffs = [diff for diff in diffs if touches_feed(diff)]
    assert feed_diffs == [], "\n".join(map(repr, feed_diffs))


# --- http ------------------------------------------------------------------------------------------------------------------


def http_client(world: World, user_id: int) -> TestClient:
    app = FastAPI()
    app.include_router(feed_api.router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    def session_dependency():  # noqa: ANN202
        session = world.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[current_user_id] = lambda: user_id
    return TestClient(app)
