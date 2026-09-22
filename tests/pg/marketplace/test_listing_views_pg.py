"""The view count is a count of people (Q98), on PostgreSQL.

`tests/modules/marketplace/test_listing_views.py` pins who is refused before the database is touched. What
needs a real database is the other half: that the count and the rows cannot drift apart. The counter is
denormalised onto `listings.view_count` so a feed page does not turn into one aggregate per card, and a
denormalised counter is exactly the thing that quietly goes wrong - a second open that increments again, or two
first opens at the same instant that increment once between them.

Both are decided by `ON CONFLICT DO NOTHING ... RETURNING`, which is why they are asserted here and not in a
unit test: SQLite has no such conflict semantics and would prove nothing about what production does.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import ListingView
from app.modules.marketplace.views import listing_public_dto
from tests.pg.identity.a1_world import World, add_user, run_in_thread
from tests.pg.marketplace.test_marketplace_pg import published_request

pytestmark = pytest.mark.pg


def view(world: World, listing_public_id: str, viewer_id: int | None) -> bool:
    with world.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_public_id)
        first = marketplace_service.record_listing_view(s, listing, viewer_user_id=viewer_id)
        s.commit()
        return first


def count_of(world: World, listing_public_id: str) -> tuple[int, int]:
    """``(denormalised counter, rows)`` - the test is that these never disagree."""
    with world.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_public_id)
        rows = s.execute(select(ListingView).where(ListingView.listing_id == listing.id)).scalars().all()
        return listing.view_count, len(rows)


def test_one_person_is_one_view_however_often_they_open_it(world: World) -> None:
    listing = published_request(world)

    assert view(world, listing, world.client2_id) is True
    for _ in range(4):
        assert view(world, listing, world.client2_id) is False

    assert count_of(world, listing) == (1, 1)


def test_a_second_person_is_a_second_view(world: World) -> None:
    listing = published_request(world)
    with world.db.session() as s:
        third = add_user(s, "+998900000404", "client", full_name="Dilnoza Rashidova")
        s.commit()

    view(world, listing, world.client2_id)
    view(world, listing, third)

    assert count_of(world, listing) == (2, 2)


def test_the_owner_and_anonymous_readers_leave_no_row(world: World) -> None:
    listing = published_request(world)

    assert view(world, listing, world.client_id) is False  # the owner
    assert view(world, listing, None) is False  # the public share page has no identity to count

    assert count_of(world, listing) == (0, 0)


def test_two_first_opens_at_once_count_twice_and_only_twice(world: World) -> None:
    """The counter is read-modify-written inside one UPDATE, so concurrent increments queue instead of racing."""
    listing = published_request(world)
    with world.db.session() as s:
        third = add_user(s, "+998900000405", "client", full_name="Bekzod Yo'ldoshev")
        s.commit()

    threads = [run_in_thread(lambda viewer=viewer: view(world, listing, viewer)) for viewer in (world.client2_id, third)]
    for thread, outcome in threads:
        thread.join(timeout=30)
        assert "error" not in outcome, outcome.get("error")
        assert outcome["value"] is True

    assert count_of(world, listing) == (2, 2)


def test_the_same_person_twice_at_once_still_counts_once(world: World) -> None:
    """The unique insert is the whole guarantee: one of the two sessions loses the conflict and adds nothing."""
    listing = published_request(world)
    threads = [run_in_thread(lambda: view(world, listing, world.client2_id)) for _ in range(2)]
    results = []
    for thread, outcome in threads:
        thread.join(timeout=30)
        assert "error" not in outcome, outcome.get("error")
        results.append(outcome["value"])

    assert sorted(results) == [False, True], "exactly one of the two opens may be the first one"
    assert count_of(world, listing) == (1, 1)


def test_reading_a_listing_never_moves_its_version(world: World) -> None:
    """Q54: `version`/`terms_version` decide whether an open proposal is still valid.

    If a view bumped either, a listing would lose every offer on it because somebody looked at it.
    """
    listing = published_request(world)
    with world.db.session() as s:
        before = marketplace_service.get_listing_by_public_id(s, listing)
        versions = (before.version, before.terms_version, before.updated_at)

    view(world, listing, world.client2_id)

    with world.db.session() as s:
        after = marketplace_service.get_listing_by_public_id(s, listing)
        assert (after.version, after.terms_version, after.updated_at) == versions
        assert after.view_count == 1


def test_the_count_is_on_the_public_dto(world: World) -> None:
    """Both sides see it: the owner to decide whether the price or the route is wrong, everyone else as
    ordinary market information. It carries no identity - a number cannot say who looked."""
    listing = published_request(world)
    view(world, listing, world.client2_id)
    with world.db.session() as s:
        dto = listing_public_dto(s, marketplace_service.get_listing_by_public_id(s, listing))
        assert dto.view_count == 1


def test_the_backfill_is_idempotent(world: World) -> None:
    """Migration 0083 re-runs on every deploy of that revision; a second run must not double the counter."""
    listing = published_request(world)
    view(world, listing, world.client2_id)

    backfill = text(
        """
        UPDATE public.listings AS l
        SET view_count = v.total
        FROM (SELECT listing_id, count(*) AS total FROM public.listing_views GROUP BY listing_id) AS v
        WHERE v.listing_id = l.id AND l.view_count <> v.total
        """
    )
    with world.db.session() as s:
        s.execute(backfill)
        s.execute(backfill)
        s.commit()

    assert count_of(world, listing) == (1, 1)


def test_deleting_the_listing_takes_its_views_with_it(world: World) -> None:
    """ON DELETE CASCADE, so a removed listing cannot leave rows pointing at nothing."""
    listing = published_request(world)
    view(world, listing, world.client2_id)
    with world.db.session() as s:
        row = marketplace_service.get_listing_by_public_id(s, listing)
        listing_id = row.id
        s.execute(text("DELETE FROM listings WHERE id = :id"), {"id": listing_id})
        s.commit()
    with world.db.session() as s:
        assert s.execute(select(ListingView).where(ListingView.listing_id == listing_id)).first() is None
