"""ADR-0026 (Q138) on real PostgreSQL: drivers no longer publish listings; saved trip requests are retired.

* a driver (or anyone) cannot create, publish, edit or answer a ``trip_offer`` - service guard, HTTP and DB trigger;
* a saved trip request (ADR-0025) cannot be created - service, HTTP and DB trigger;
* what the old model left behind (a published driver listing with an open negotiation) cannot become a booking, and
  the ``marketplace.retire_driver_listings`` job closes it with a technical reason - once, without touching bookings,
  money or anybody's record; the old rows stay readable.

The legacy row is built with SQL the way the pre-0092 model would have left it (``session_replication_role =
replica`` only for that setup statement), because no code path can create one any more. SYNTHETIC data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import ErrorCode
from app.modules.marketplace import intents
from app.modules.marketplace import service as marketplace_service
from tests.pg.bookings.conftest import (  # noqa: F401  (bw, client fixtures)
    BW,
    accept,
    auth,
    booked,
    bw,
    client,
    counter,
    domain_error,
    driver_trip,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    scalar,
    seats_used,
    wallet,
)
from tests.pg.identity.a1_world import passenger_offer

pytestmark = pytest.mark.pg


def _legacy_offer_with_open_thread(bw: BW, plate: str) -> tuple[str, int, object]:
    """A published trip_offer with one open negotiation, as the pre-0092 model left it."""
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, plate, seats=3)
    listing = publish_listing(bw, bw.w.client2_id, passenger_request_body(bw, seats=1))
    ref = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=20_000_000)
    with bw.db.engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE listings SET kind = 'trip_offer', owner_user_id = :d, trip_id = :t WHERE public_id = "
                          "(SELECT public_id FROM listings WHERE id = :l)"),
                     {"d": bw.w.driver_id, "t": trip_id, "l": marketplace_service_id(bw, listing)})
    return listing, trip_id, ref


def marketplace_service_id(bw: BW, listing_public_id: str) -> int:
    with bw.db.session() as s:
        return marketplace_service.resolve_listing_id(s, listing_public_id)


def test_nobody_can_create_or_publish_a_driver_listing_by_service_http_or_sql(bw: BW, client) -> None:  # noqa: ANN001, F811
    _, trip_public = driver_trip(bw, bw.w.driver_id, "01R100AA")
    body = passenger_offer(bw.w, trip_public, start=bw.base)
    for owner in (bw.w.driver_id, bw.w.client_id):
        with bw.db.session() as s:
            error = domain_error(lambda: marketplace_service.create_listing(s, owner_user_id=owner, data=body))
        assert error.code is ErrorCode.DRIVER_LISTING_RETIRED and error.http_status == 409
    response = client.post("/api/v2/listings", json=body.model_dump(mode="json"), headers=auth(bw.w.driver_id, "driver", "adr26-create-1"))
    assert response.status_code == 409 and response.json()["error"]["code"] == "DRIVER_LISTING_RETIRED"
    assert scalar(bw.db, "SELECT count(*) FROM listings WHERE kind = 'trip_offer'") == 0

    # the database refuses a new driver listing even if a code path forgot the guard
    request = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1))
    columns = [r.column_name for r in rows(bw.db, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
                                                  "AND table_name = 'listings' AND column_name NOT IN ('id', 'public_id', 'kind', "
                                                  "'trip_id', 'owner_user_id') ORDER BY ordinal_position")]
    listed = ", ".join(columns)
    with pytest.raises(DBAPIError, match="driver_listing_retired|driver listings are retired"), bw.db.engine.begin() as conn:
        conn.execute(text(f"INSERT INTO listings (public_id, kind, trip_id, owner_user_id, {listed}) "
                          f"SELECT gen_random_uuid(), 'trip_offer', (SELECT id FROM trips LIMIT 1), :d, {listed} "
                          f"FROM listings WHERE id = :l"), {"d": bw.w.driver_id, "l": marketplace_service_id(bw, request)})


def test_a_legacy_driver_listing_never_becomes_a_booking_and_the_retire_job_closes_it_once(bw: BW, client) -> None:  # noqa: ANN001, F811
    listing, trip_id, ref = _legacy_offer_with_open_thread(bw, "01R101AA")
    # a normal booking on the same trip, made the new way, must survive everything below untouched
    kept = booked(bw, _trip_public(bw, trip_id), bw.w.client_id)
    hold_before, seats_before = wallet(bw, bw.w.driver_id), seats_used(bw, trip_id)

    accept_error = domain_error(lambda: accept(bw, ref, bw.w.client2_id))
    assert accept_error.code is ErrorCode.DRIVER_LISTING_RETIRED
    assert domain_error(lambda: counter(bw, ref, bw.w.client2_id, unit=18_000_000)).code is ErrorCode.DRIVER_LISTING_RETIRED
    with bw.db.session() as s:
        version = marketplace_service.get_listing_by_public_id(s, listing).version
        paused = domain_error(lambda: marketplace_service.publish_listing(s, listing_public_id=listing, actor_user_id=bw.w.driver_id,
                                                                          expected_version=version))
    assert paused.code in (ErrorCode.DRIVER_LISTING_RETIRED, ErrorCode.INVALID_STATE_TRANSITION)
    assert (wallet(bw, bw.w.driver_id), seats_used(bw, trip_id)) == (hold_before, seats_before)  # nothing reserved or held
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1

    with bw.db.session() as s:
        assert marketplace_service.retire_driver_listings(s) == 1
        s.commit()
    with bw.db.session() as s:
        assert marketplace_service.retire_driver_listings(s) == 0  # idempotent
        s.commit()
    row = rows(bw.db, "SELECT status, cancelled_reason FROM listings WHERE id = :l", l=marketplace_service_id(bw, listing))[0]
    assert (row.status, row.cancelled_reason) == ("cancelled", "driver_listing_retired")
    thread = rows(bw.db, "SELECT t.state, v.status, v.status_reason FROM proposal_threads t JOIN proposal_versions v "
                         "ON v.id = t.current_version_id WHERE t.listing_id = :l", l=marketplace_service_id(bw, listing))[0]
    assert thread.state == "closed" and thread.status != "active"
    # the booking made the new way is untouched; nobody got a fault, strike or charge from the clean-up
    assert rows(bw.db, "SELECT service_status, commission_status FROM bookings WHERE id = :b", b=kept.id) == [("confirmed", "held")]
    assert (wallet(bw, bw.w.driver_id), seats_used(bw, trip_id)) == (hold_before, seats_before)
    # the old listing stays readable to its owner (history kept)
    old = client.get(f"/api/v2/listings/{listing}", headers=auth(bw.w.driver_id, "driver"))
    assert old.status_code == 200 and old.json()["data"]["status"] == "cancelled"


def test_saved_trip_requests_are_retired_by_service_http_and_sql(bw: BW, client) -> None:  # noqa: ANN001, F811
    with bw.db.session() as s:
        error = domain_error(lambda: intents.create_intent(s, owner_user_id=bw.w.client_id, data=None))
    assert error.code is ErrorCode.TRIP_INTENT_RETIRED
    response = client.post("/api/v2/me/trip-intents", json={"service_type": "passenger"},
                           headers=auth(bw.w.client_id, "client", "adr26-intent-1"))
    assert response.status_code in (409, 422)
    with pytest.raises(DBAPIError, match="trip_intent_retired|saved trip requests are retired"), bw.db.engine.begin() as conn:
        conn.execute(text("INSERT INTO trip_intents DEFAULT VALUES"))


def _trip_public(bw: BW, trip_id: int) -> str:
    from app.modules.trips import service as trips_service

    with bw.db.session() as s:
        return trips_service.trip_public_id(trips_service.get_trip(s, trip_id))


def test_one_authorized_admin_manages_the_size_catalog_with_versions_and_audit(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """0094: the size catalog is not the prohibited-items policy - one `platform.policy_manage` admin drafts and activates
    it; versions supersede each other; both steps are audited; a synthetic version never activates in production."""
    from app.modules.marketplace import parcel_catalog
    from app.modules.marketplace.schemas import ParcelCategoryItemInput
    from app.modules.platform import service as platform_service

    item = ParcelCategoryItemInput.model_validate({"code": "box", "name_uz": "Quti (sintetik)", "icon_key": "box_small",
                                                   "max_length_cm": 30, "max_width_cm": 20, "max_height_cm": 20,
                                                   "max_weight_g": 5_000, "max_volume_ml": 12_000})

    def draft(label: str, synthetic: bool) -> tuple[str, int]:
        with bw.db.session() as s:
            version = parcel_catalog.create_version(s, actor_user_id=bw.super_id, label=label, source_note="synthetic test",
                                                    synthetic=synthetic, items=[item])
            s.commit()
            return parcel_catalog.version_public_id(version), version.version

    first, v1 = draft("cat-v1", True)
    with bw.db.session() as s:  # the author activates it - no second approver
        parcel_catalog.confirm_version(s, actor_user_id=bw.super_id, version_public_id_value=first, expected_version=v1)
        s.commit()
    second, v2 = draft("cat-v2", True)
    with bw.db.session() as s:
        operator_refused = domain_error(lambda: parcel_catalog.confirm_version(
            s, actor_user_id=bw.operator_id, version_public_id_value=second, expected_version=v2))
    assert operator_refused.code in (ErrorCode.CAPABILITY_REQUIRED, ErrorCode.FORBIDDEN)
    monkeypatch.setattr(platform_service, "is_production", lambda session=None: True)
    with bw.db.session() as s:
        prod_refused = domain_error(lambda: parcel_catalog.confirm_version(
            s, actor_user_id=bw.super_id, version_public_id_value=second, expected_version=v2))
    assert prod_refused.details["reason"] == "synthetic_catalog_not_for_production"
    monkeypatch.undo()
    with bw.db.session() as s:
        parcel_catalog.confirm_version(s, actor_user_id=bw.super_id, version_public_id_value=second, expected_version=v2)
        s.commit()
    assert [r.status for r in rows(bw.db, "SELECT status FROM parcel_category_versions WHERE label IN ('cat-v1', 'cat-v2') "
                                          "ORDER BY label")] == ["superseded", "active"]
    actions = [r.action for r in rows(bw.db, "SELECT action FROM audit_logs WHERE entity_type = 'parcel_catalog' ORDER BY id")]
    assert actions == ["parcel_catalog_version_created", "parcel_catalog_version_activated",
                       "parcel_catalog_version_created", "parcel_catalog_version_activated"]
    assert scalar(bw.db, "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_parcel_category_versions_two_people'") == 0
