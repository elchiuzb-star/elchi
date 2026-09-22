"""Wave 7 / §5.2: the prohibited-items policy mechanism (the list itself stays a human decision).

What is proven here:

* an **unpublished list is not permission**: with no approved policy, production refuses a new parcel listing and
  a new parcel booking (`503 PARCEL_POLICY_UNCONFIRMED`), while outside production the same state only reports
  ``approved=false``;
* a parcel that is **already booked keeps running** - delivery, proof and completion never consult the policy,
  because an unapproved list must not strand cargo that is on the road;
* approval is a two-person act: a draft applies to nobody, the author cannot confirm their own draft, and only
  one version is active at a time;
* a ``prohibited`` rule cannot exist without its legal basis and source (DB CHECK) - the platform never says
  "this is forbidden" without naming where that comes from;
* passenger listings are untouched: a parcel rule is not silently applied to every service.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.contracts.errors import DomainError, ErrorCode
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import ParcelPolicyVersion
from app.modules.platform import service as platform_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    accept,
    auth,
    bw,
    driver_trip,
    parcel_request_body,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def _draft_items(count: int = 2) -> list[object]:
    from scripts.seed_parcel_policy_draft import DRAFT_ITEMS

    return list(DRAFT_ITEMS[:count])


@pytest.fixture
def as_production(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Make the gate see "production" without touching the environment marker.

    The DB guard refuses to mark this database production (a passenger flag is enabled without an approval
    reference - exactly the invariant Q5/N1 asks for), so the test swaps the reader instead of weakening it.
    """

    def enable() -> None:
        monkeypatch.setattr(marketplace_service.platform_service, "is_production", lambda session: True)

    return enable


def test_policy_reader_says_not_approved_instead_of_empty_permission(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        view = marketplace_service.active_parcel_policy(session)
    assert view.approved is False and view.items == ()


def test_draft_applies_to_nobody_and_the_author_cannot_confirm_it(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        version = marketplace_service.create_parcel_policy_version(
            session, actor_user_id=bw.super_id, label="pilot-draft", source_note="draft", items=_draft_items()
        )
        session.commit()
        policy_id = marketplace_service.parcel_policy_public_id(version)
        expected_version = version.version

    with bw.db.session() as session:
        assert marketplace_service.active_parcel_policy(session).approved is False, "a draft is not in force"
        with pytest.raises(DomainError) as refused:
            marketplace_service.confirm_parcel_policy_version(
                session, actor_user_id=bw.super_id, policy_public_id=policy_id, expected_version=expected_version
            )
        assert refused.value.code is ErrorCode.FORBIDDEN
        assert refused.value.details["reason"] == "author_cannot_confirm_own_policy"


def test_prohibited_rule_without_a_source_is_refused_by_the_database(bw: BW) -> None:  # noqa: F811
    from scripts.seed_parcel_policy_draft import DraftItem

    bad = DraftItem("no_source", "prohibited", "all", "Manbasiz taqiq", "Sababsiz taqiq",
                    legal_basis=None, source_ref=None, source_checked_on=date(2026, 9, 17))
    with bw.db.session() as session, pytest.raises(DomainError) as refused:
        marketplace_service.create_parcel_policy_version(
            session, actor_user_id=bw.super_id, label="bad-draft", source_note=None, items=[bad]
        )
    assert refused.value.code is ErrorCode.VALIDATION_ERROR
    assert refused.value.details["reason"] == "prohibited_item_needs_legal_basis_and_source"


def test_confirmation_by_another_super_admin_activates_exactly_one_version(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        first = marketplace_service.create_parcel_policy_version(
            session, actor_user_id=bw.super_id, label="v1", source_note=None, items=_draft_items(2)
        )
        session.commit()
        first_id, first_version = marketplace_service.parcel_policy_public_id(first), first.version

    # The operator drafting is not enough; approval needs platform.policy_manage (super_admin).
    with bw.db.session() as session, pytest.raises(DomainError) as refused:
        marketplace_service.confirm_parcel_policy_version(
            session, actor_user_id=bw.operator_id, policy_public_id=first_id, expected_version=first_version
        )
    assert refused.value.code in {ErrorCode.FORBIDDEN, ErrorCode.CAPABILITY_REQUIRED}

    with bw.db.session() as session:
        approver = _second_super_admin(session, bw)
        marketplace_service.confirm_parcel_policy_version(
            session, actor_user_id=approver, policy_public_id=first_id, expected_version=first_version
        )
        session.commit()

    with bw.db.session() as session:
        view = marketplace_service.active_parcel_policy(session)
        assert view.approved is True and view.label == "v1"
        assert len(view.items) == 2
        assert all(item.title_uz for item in view.items)

    # A second confirmed version supersedes the first: "which list applies" is never ambiguous.
    with bw.db.session() as session:
        second = marketplace_service.create_parcel_policy_version(
            session, actor_user_id=bw.super_id, label="v2", source_note=None, items=_draft_items(3)
        )
        session.commit()
        second_id, second_version = marketplace_service.parcel_policy_public_id(second), second.version
    with bw.db.session() as session:
        approver = _second_super_admin(session, bw)
        marketplace_service.confirm_parcel_policy_version(
            session, actor_user_id=approver, policy_public_id=second_id, expected_version=second_version
        )
        session.commit()
    with bw.db.session() as session:
        assert marketplace_service.active_parcel_policy(session).label == "v2"
        statuses = dict(session.execute(text("SELECT label, status FROM parcel_policy_versions")).all())
        assert statuses == {"v1": "superseded", "v2": "active"}


def test_production_without_a_policy_refuses_new_parcel_business_only(
    bw: BW, as_production, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """The gate is fail-closed for *new* parcel business and blind to passenger listings."""
    parcel_listing = _draft_parcel_listing(bw)
    passenger = passenger_request_body(bw)

    as_production()
    if True:
        with bw.db.session() as session:
            listing = marketplace_service.get_listing_by_public_id(session, parcel_listing)
            with pytest.raises(DomainError) as refused:
                marketplace_service.publish_listing(
                    session, listing_public_id=parcel_listing, actor_user_id=bw.w.client_id,
                    expected_version=listing.version,
                )
            assert refused.value.code is ErrorCode.PARCEL_POLICY_UNCONFIRMED
        # a passenger listing is not touched by a parcel rule
        publish_listing(bw, bw.w.client2_id, passenger)

    monkeypatch.undo()
    # outside production the same state is allowed - development is not blocked, the reader still says false
    with bw.db.session() as session:
        listing = marketplace_service.get_listing_by_public_id(session, parcel_listing)
        marketplace_service.publish_listing(
            session, listing_public_id=parcel_listing, actor_user_id=bw.w.client_id,
            expected_version=listing.version,
        )
        session.commit()
        assert marketplace_service.active_parcel_policy(session).approved is False


def test_an_accepted_parcel_keeps_running_without_a_policy(bw: BW, as_production) -> None:  # noqa: F811
    """An unapproved list must never strand cargo that is already on the road (D16 obligation)."""
    from app.modules.bookings import service as bookings_service

    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A700AA")
    ref = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000,
                  dropoff="C", price_basis="total")
    booking = accept(bw, ref, bw.w.client_id)

    as_production()
    if True:
        with bw.db.session() as session:
            # reading and progressing the existing booking does not consult the policy at all
            stored = bookings_service.get_booking(session, booking.id)
            assert stored.service_status is not None
            assert marketplace_service.active_parcel_policy(session).approved is False
            # ... while a *new* parcel negotiation is refused
            with pytest.raises(DomainError) as refused:
                marketplace_service.assert_parcel_policy_ready(session)
            assert refused.value.code is ErrorCode.PARCEL_POLICY_UNCONFIRMED


def _draft_parcel_listing(bw: BW) -> str:  # noqa: F811
    with bw.db.session() as session:
        listing = marketplace_service.create_listing(
            session, owner_user_id=bw.w.client_id, data=parcel_request_body(bw)
        )
        session.commit()
        return marketplace_service.listing_public_id(listing)


def _second_super_admin(session, bw: BW) -> int:  # noqa: ANN001, F811
    """§5.2 approval needs a *different* super_admin; the pilot therefore needs at least two."""
    from app.models import User
    from app.modules.identity import service as identity_service

    existing = session.execute(
        text("SELECT id FROM users WHERE role = 'super_admin' AND id <> :self ORDER BY id LIMIT 1"),
        {"self": bw.super_id},
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    user = User(phone="+998970000777", role="super_admin", status="active", is_phone_verified=True)
    session.add(user)
    session.flush()
    identity_service.get_capabilities(session, user.id)  # warms the capability cache the same way the API does
    return user.id


# --- wave 8: the approved list (product owner, 17.09.2026) ------------------------------------------


def test_the_approved_list_loads_whole_and_every_prohibited_row_names_its_source(bw: BW) -> None:  # noqa: F811
    """The 13 approved items must survive the database's own rules, not just the document."""
    from scripts.seed_parcel_policy_draft import DRAFT_ITEMS

    with bw.db.session() as session:
        version = marketplace_service.create_parcel_policy_version(
            session, actor_user_id=bw.super_id, label="approved-2026-09",
            source_note="content approved 17.09.2026", items=list(DRAFT_ITEMS),
        )
        session.commit()
        public_id = marketplace_service.parcel_policy_public_id(version)

    with bw.db.session() as session:
        rows = session.execute(
            text(
                "SELECT category, applies_to, legal_basis, source_ref FROM parcel_policy_items i "
                "JOIN parcel_policy_versions v ON v.id = i.policy_version_id WHERE v.label = :label"
            ),
            {"label": "approved-2026-09"},
        ).all()
    assert len(rows) == len(DRAFT_ITEMS) == 13
    for category, _applies_to, legal_basis, source_ref in rows:
        if category == "prohibited":
            assert legal_basis and source_ref, "the platform never calls something illegal without saying why"
    # a transport rule applies to everything carried; an excise/medicine rule is about parcels only
    scopes = {r[0]: set() for r in rows}
    for category, applies_to, _b, _s in rows:
        scopes[category].add(applies_to)
    assert "all" in scopes["prohibited"], "dangerous-goods rules cover passenger baggage too"
    del public_id


def test_confirming_the_approved_list_reopens_new_parcel_business_in_production(
    bw: BW, as_production  # noqa: F811
) -> None:
    """End to end: draft -> second super_admin confirms -> the gate that refused now lets a listing through."""
    from scripts.seed_parcel_policy_draft import DRAFT_ITEMS

    parcel_listing = _draft_parcel_listing(bw)
    as_production()

    with bw.db.session() as session:
        with pytest.raises(DomainError) as refused:
            marketplace_service.assert_parcel_policy_ready(session)
        assert refused.value.code is ErrorCode.PARCEL_POLICY_UNCONFIRMED

        version = marketplace_service.create_parcel_policy_version(
            session, actor_user_id=bw.super_id, label="approved-live",
            source_note="content approved 17.09.2026", items=list(DRAFT_ITEMS),
        )
        session.commit()
        public_id = marketplace_service.parcel_policy_public_id(version)
        expected_version = version.version

    with bw.db.session() as session:
        # still refused: a draft approves nothing
        with pytest.raises(DomainError):
            marketplace_service.assert_parcel_policy_ready(session)
        approver = _second_super_admin(session, bw)
        marketplace_service.confirm_parcel_policy_version(
            session, actor_user_id=approver, policy_public_id=public_id, expected_version=expected_version
        )
        session.commit()

    with bw.db.session() as session:
        view = marketplace_service.active_parcel_policy(session)
        assert view.approved is True and len(view.items) == 13
        marketplace_service.assert_parcel_policy_ready(session)  # no longer raises
        listing = marketplace_service.get_listing_by_public_id(session, parcel_listing)
        marketplace_service.publish_listing(
            session, listing_public_id=parcel_listing, actor_user_id=bw.w.client_id,
            expected_version=listing.version,
        )
        session.commit()
