"""Who the view counter refuses to count, proved without a database (Q98).

The counting itself is a unique insert and belongs in PostgreSQL (`tests/pg/marketplace/test_listing_views_pg.py`).
What can be pinned here is the part that decides *whether* to count at all, and it matters more than it looks:
every exclusion is the difference between a number the owner can act on and a number that moves on its own.

So the session these tests pass in refuses to execute anything. A regression that starts counting the owner,
or an anonymous reader, cannot pass silently - it has to reach the database, and the database is a landmine.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.marketplace import service as marketplace_service

OWNER_ID = 41
LISTING = SimpleNamespace(id=7, owner_user_id=OWNER_ID)


class RefusingSession:
    """Any query at all is the failure this test is looking for."""

    def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("record_listing_view reached the database for a viewer it must not count")


def test_the_owner_is_not_an_audience() -> None:
    """Otherwise every check of one's own listing reads back as interest, and the number means nothing."""
    assert marketplace_service.record_listing_view(RefusingSession(), LISTING, viewer_user_id=OWNER_ID) is False


def test_an_anonymous_reader_is_not_counted() -> None:
    """No identity means nothing to deduplicate by, so the count could be raised by reloading the page.

    That includes the public share link (§20.2), which is the one surface a stranger can open. An approximate
    number shown as an exact one is an invented signal (§9), so it is left out rather than estimated.
    """
    assert marketplace_service.record_listing_view(RefusingSession(), LISTING, viewer_user_id=None) is False


@pytest.mark.parametrize("viewer", [OWNER_ID - 1, OWNER_ID + 1])
def test_anybody_else_is_counted(viewer: int) -> None:
    """The mirror of the two above: a real viewer must get as far as the insert."""
    with pytest.raises(AssertionError, match="reached the database"):
        marketplace_service.record_listing_view(RefusingSession(), LISTING, viewer_user_id=viewer)
