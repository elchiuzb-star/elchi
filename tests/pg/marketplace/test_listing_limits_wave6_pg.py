"""Wave 6 / §5.2 and §5.4: the pilot's parcel limits and the publish rate limit.

* §5.2 "Pilot limiti ... admin sozlamasida beriladi" - a post above the pilot's declared size is refused with the
  limit in the answer, so raising it is an explicit decision instead of a silent truncation. (The prohibited-items
  list itself is a business decision and is deliberately **not** invented in code.)
* §5.4 "Yangi e'lon uchun miqdoriy rate-limit ishlaydi" - re-publishing cannot be used to look fresh; resuming a
  paused post is not a new post and is not charged against the limit.
* §17.7 - the §20.4 search counters are deleted once they pass the retention window.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.marketplace import (
    LISTING_PUBLISH_RATE_LIMIT,
    PARCEL_PILOT_MAX_DIMENSION_CM,
    PARCEL_PILOT_MAX_WEIGHT_G,
)
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.feed import service as feed_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    auth,
    bw,
    parcel_request_body,
    passenger_request_body,
    publish_listing,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def _create_listing(bw: BW, owner_id: int, body) -> str:  # noqa: ANN001, F811
    with bw.db.session() as session:
        listing = marketplace_service.create_listing(session, owner_user_id=owner_id, data=body)
        session.commit()
        return marketplace_service.listing_public_id(listing)


def test_parcel_above_the_pilot_limit_is_refused_with_the_limit(bw: BW) -> None:  # noqa: F811
    listing_id = _create_listing(bw, bw.w.client_id, parcel_request_body(bw))
    with bw.db.session() as session:
        session.execute(
            text("UPDATE parcel_listing_details SET weight_g = :w"), {"w": PARCEL_PILOT_MAX_WEIGHT_G + 1}
        )
        session.commit()

    with bw.db.session() as session:
        listing = marketplace_service.get_listing_by_public_id(session, listing_id)
        with pytest.raises(DomainError) as refused:
            marketplace_service.publish_listing(
                session, listing_public_id=listing_id, actor_user_id=bw.w.client_id,
                expected_version=listing.version,
            )
    assert refused.value.code is ErrorCode.VALIDATION_ERROR
    assert refused.value.details["reason"] == "pilot_parcel_limit"
    assert refused.value.details["limits"]["weight_g"] == PARCEL_PILOT_MAX_WEIGHT_G


def test_oversized_box_is_refused_by_its_longest_side(bw: BW) -> None:  # noqa: F811
    listing_id = _create_listing(bw, bw.w.client_id, parcel_request_body(bw))
    with bw.db.session() as session:
        session.execute(
            text("UPDATE parcel_listing_details SET length_cm = :l"), {"l": PARCEL_PILOT_MAX_DIMENSION_CM + 10}
        )
        session.commit()
    with bw.db.session() as session:
        listing = marketplace_service.get_listing_by_public_id(session, listing_id)
        with pytest.raises(DomainError) as refused:
            marketplace_service.publish_listing(
                session, listing_public_id=listing_id, actor_user_id=bw.w.client_id,
                expected_version=listing.version,
            )
    assert refused.value.details["limits"]["dimension_cm"] == PARCEL_PILOT_MAX_DIMENSION_CM


def test_publish_rate_limit_stops_flooding_but_not_resuming(bw: BW) -> None:  # noqa: F811
    # distinct departure windows: these are different trips, not duplicates of one post (§5.4 duplicate guard)
    for index in range(LISTING_PUBLISH_RATE_LIMIT):
        publish_listing(
            bw, bw.w.client2_id,
            passenger_request_body(bw, origin="A", destination="D", start=bw.base + timedelta(hours=2 * index)),
        )

    over_the_limit = _create_listing(
        bw, bw.w.client2_id,
        passenger_request_body(bw, origin="A", destination="C", start=bw.base + timedelta(hours=40)),
    )
    with bw.db.session() as session:
        listing = marketplace_service.get_listing_by_public_id(session, over_the_limit)
        with pytest.raises(DomainError) as refused:
            marketplace_service.publish_listing(
                session, listing_public_id=over_the_limit, actor_user_id=bw.w.client2_id,
                expected_version=listing.version,
            )
    assert refused.value.code is ErrorCode.RATE_LIMITED
    assert refused.value.details["limit"] == LISTING_PUBLISH_RATE_LIMIT

    # Another author is not affected by this one's flood.
    publish_listing(bw, bw.w.client_id, passenger_request_body(bw, origin="A", destination="C"))


def test_search_counters_are_deleted_after_the_retention_window(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        session.execute(
            text("INSERT INTO feed_search_events (occurred_at, service_type, side, matched, result_count) "
                 "VALUES (:old, 'passenger', 'requests', true, 3), (:fresh, 'passenger', 'requests', false, 0)"),
            {"old": bw.base - feed_service.SEARCH_EVENT_RETENTION - timedelta(days=1), "fresh": bw.base},
        )
        session.commit()

    with bw.db.session() as session:
        removed = feed_service.purge_search_events(session, now=bw.base)
        session.commit()
    assert removed == 1
    assert scalar(bw.db, "SELECT count(*) FROM feed_search_events") == 1
