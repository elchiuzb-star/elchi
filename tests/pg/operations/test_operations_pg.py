"""A13 (wave 4) on real PostgreSQL: share links and the public page (§20.2), operator queues (§16),
KPI counts (§20.4), the SLO answer (§19.3) and listings created on behalf of an owner.

Business truthfulness under test: the token is stored only as a hash and an unknown/revoked/expired one is a plain
404; the public page carries no identity; a KPI ratio without a denominator stays null and unmeasured metrics are
listed as missing; the SLO answer reports latency from the process's own measurements and stays null while the
sample is too small, instead of inventing a number (wave 6).
"""

from __future__ import annotations

import uuid

from datetime import timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from app.contracts.crypto import secret_token_hash
from app.contracts.enums import KpiMetric, OpsQueue
from app.contracts.errors import ErrorCode
from app.contracts.operations import SHARE_LINK_MAX_ACTIVE_PER_LISTING
from app.contracts.timeutil import utc_now
from app.modules.operations import jobs, service
from tests.pg.operations.conftest import (
    BW,
    domain_error,
    passenger_request_body,
    publish_listing,
    rows,
    scalar,
)

pytestmark = pytest.mark.pg


def _published_listing(bw: BW, *, owner_id: int | None = None, origin: str = "A", destination: str = "D") -> str:
    owner = owner_id or bw.w.client_id
    return publish_listing(bw, owner, passenger_request_body(bw, origin=origin, destination=destination))


def _create_link(bw: BW, listing_public: str, actor_id: int, *, ttl_hours: int = 48):
    with bw.db.session() as s:
        created = service.create_share_link(
            s, listing_public_id_value=listing_public, actor_user_id=actor_id, channel="telegram", ttl_hours=ttl_hours
        )
        result = (service.share_link_public_id(created.row), created.token, created.share_text, created.url)
        s.commit()
        return result


def test_share_link_is_stored_as_a_hash_and_opens_a_page_without_identity(bw: BW) -> None:
    listing = _published_listing(bw)
    public_id, token, share_text, url = _create_link(bw, listing, bw.w.client_id)

    stored = rows(bw.db, "SELECT token_hash, opened_count, channel FROM share_links")[0]
    assert stored.token_hash == secret_token_hash(token) and token not in stored.token_hash
    assert scalar(bw.db, "SELECT count(*) FROM share_links WHERE token_hash = :t", t=token) == 0, "raw token not stored"
    assert stored.opened_count == 0 and stored.channel == "telegram"
    assert url.endswith(token) and token in share_text
    owner_phone = scalar(bw.db, "SELECT phone FROM users WHERE id = :u", u=bw.w.client_id)
    assert owner_phone not in share_text and "+998" not in share_text  # §20.2: route, time, price and the link

    with bw.db.session() as s:
        page = service.open_public_listing(s, token=token)
        s.commit()
    assert page.status_open is True and page.cta == "open_app_to_offer"
    assert page.total_minor > 0 and page.currency == "UZS"
    assert page.origin_stop_name and page.destination_stop_name
    # the page object carries no identity field at all (Q43)
    assert {field for field in page.__slots__} == {
        "kind", "service_type", "origin_stop_name", "destination_stop_name", "departure_window_start",
        "departure_window_end", "timezone", "price_basis", "unit_price_minor", "quantity", "total_minor",
        "currency", "status_open", "cta",
    }
    assert rows(bw.db, "SELECT opened_count, last_opened_at FROM share_links")[0].opened_count == 1

    with bw.db.session() as s:
        assert domain_error(lambda: service.open_public_listing(s, token="not-a-real-token")).code is ErrorCode.NOT_FOUND

    with bw.db.session() as s:
        service.revoke_share_link(s, share_link_public_id_value=public_id, actor_user_id=bw.w.client_id)
        service.revoke_share_link(s, share_link_public_id_value=public_id, actor_user_id=bw.w.client_id)  # idempotent
        s.commit()
    with bw.db.session() as s:
        assert domain_error(lambda: service.open_public_listing(s, token=token)).code is ErrorCode.NOT_FOUND


def test_share_link_ownership_status_and_active_limit(bw: BW) -> None:
    listing = _published_listing(bw)
    with bw.db.session() as s:
        other = domain_error(lambda: service.create_share_link(
            s, listing_public_id_value=listing, actor_user_id=bw.w.client2_id, ttl_hours=24))
        assert other.code is ErrorCode.NOT_FOUND  # somebody else's listing is invisible

    for _ in range(SHARE_LINK_MAX_ACTIVE_PER_LISTING):
        _create_link(bw, listing, bw.w.client_id)
    with bw.db.session() as s:
        too_many = domain_error(lambda: service.create_share_link(
            s, listing_public_id_value=listing, actor_user_id=bw.w.client_id, ttl_hours=24))
        assert too_many.code is ErrorCode.VALIDATION_ERROR and too_many.details["reason"] == "too_many_active"

    # a draft listing is not shareable yet (§20.2: the page would show a listing nobody can answer)
    from app.modules.marketplace import service as marketplace_service

    with bw.db.session() as s:
        draft = marketplace_service.create_listing(
            s, owner_user_id=bw.w.client_id, data=passenger_request_body(bw, origin="A", destination="C")
        )
        draft_public = marketplace_service.listing_public_id(draft)
        s.commit()
    with bw.db.session() as s:
        not_open = domain_error(lambda: service.create_share_link(
            s, listing_public_id_value=draft_public, actor_user_id=bw.w.client_id, ttl_hours=24))
        assert not_open.code is ErrorCode.LISTING_NOT_OPEN and not_open.details["status"] == "draft"


def test_expired_link_is_refused_and_revoked_by_the_worker(bw: BW) -> None:
    listing = _published_listing(bw)
    _, token, _, _ = _create_link(bw, listing, bw.w.client_id, ttl_hours=1)
    later = utc_now() + timedelta(hours=2)
    with bw.db.session() as s:
        assert domain_error(lambda: service.open_public_listing(s, token=token, now=later)).code is ErrorCode.NOT_FOUND
    with bw.db.session() as s:
        assert jobs.expire_share_links(s, now=later) == 1
        assert jobs.expire_share_links(s, now=later) == 0
        s.commit()
    assert scalar(bw.db, "SELECT count(*) FROM share_links WHERE revoked_at IS NOT NULL") == 1


def test_share_links_are_revoked_never_deleted_or_rewritten(bw: BW) -> None:
    listing = _published_listing(bw)
    _create_link(bw, listing, bw.w.client_id)
    for statement, constraint in (
        ("DELETE FROM share_links", "share_link_immutable"),
        ("UPDATE share_links SET token_hash = repeat('a', 64)", "share_link_immutable"),
        ("UPDATE share_links SET opened_count = opened_count - 1", "share_link_immutable"),
    ):
        with pytest.raises(DBAPIError) as info:
            with bw.db.engine.begin() as conn:
                conn.exec_driver_sql(statement)
        assert info.value.orig.diag.constraint_name == constraint, statement


def test_kpi_counts_are_stored_as_pairs_and_missing_metrics_are_named(bw: BW) -> None:
    listing = _published_listing(bw)
    _create_link(bw, listing, bw.w.client_id)  # unrelated write, must not affect KPI
    today = service.rules.local_date(utc_now())

    with bw.db.session() as s:
        written = service.collect_kpi_daily(s, day=today)
        s.commit()
    assert written == len(KpiMetric)

    with bw.db.session() as s:
        report = service.kpi_report(s, actor_user_id=bw.operator_id, date_from=today, date_to=today)
    by_metric = {value.metric: value for value in report.metrics}
    published = by_metric[KpiMetric.LISTINGS_PUBLISHED.value]
    assert published.numerator >= 1 and published.value is None, "a plain count is not shown as a ratio"
    completion = by_metric[KpiMetric.BOOKING_COMPLETION.value]
    assert completion.denominator == 0 and completion.value is None, "no bookings measured -> no percentage"
    assert completion.target == 0.90
    offers = by_metric[KpiMetric.OFFER_WITHIN_TARGET.value]
    assert offers.denominator >= 1 and offers.small_sample is True  # small n is flagged (§20.4)
    # Wave 6 measured the searches and the first-offer time; wave 7 added seat-km and net commission, so the
    # "cannot measure" list is now empty. Empty means every §20.4 metric is computed from stored rows - it does
    # NOT mean every metric has a value: an unmeasurable day still reports denominator 0 and value None.
    assert "search_with_match_rate" not in report.missing_metrics
    assert report.missing_metrics == []
    seat_km = by_metric[KpiMetric.BOOKED_SEAT_KM_RATIO.value]
    assert seat_km.denominator == 0 and seat_km.value is None, "no measurable trip -> no ratio, not a zero"
    commission = by_metric[KpiMetric.NET_COMMISSION_PER_CORRIDOR.value]
    assert commission.value is None, "commission is an amount, never a ratio"
    assert report.computed_at is not None

    # re-running the day updates the same rows (idempotent upsert)
    with bw.db.session() as s:
        service.collect_kpi_daily(s, day=today)
        s.commit()
    assert scalar(bw.db, "SELECT count(*) FROM kpi_daily") == len(KpiMetric)


def test_kpi_and_slo_need_ops_view_and_reject_a_bad_range(bw: BW) -> None:
    today = service.rules.local_date(utc_now())
    with bw.db.session() as s:
        refused = domain_error(lambda: service.kpi_report(s, actor_user_id=bw.w.client_id))
        assert refused.code is ErrorCode.CAPABILITY_REQUIRED
        bad = domain_error(lambda: service.kpi_report(
            s, actor_user_id=bw.operator_id, date_from=today, date_to=today - timedelta(days=1)))
        assert bad.code is ErrorCode.VALIDATION_ERROR and bad.details["reason"] == "after_to"
        assert domain_error(lambda: service.slo_report(s, actor_user_id=bw.w.driver_id)).code is ErrorCode.CAPABILITY_REQUIRED


def test_slo_reports_tracking_freshness_and_marks_latency_unmeasured(bw: BW) -> None:
    with bw.db.session() as s:
        report = service.slo_report(s, actor_user_id=bw.operator_id)
    indicators = {item.name: item for item in report.indicators}
    freshness = indicators["tracking_freshness"]
    assert freshness.measured is True and freshness.target == 0.95
    assert freshness.sample_size == 0 and freshness.value is None, "no points -> no invented percentage"
    # Wave 6 (§19.2/§19.3): latency comes from the process's own measurements. With no traffic in this test the
    # answer is still null - the sample is below the minimum - and the note says exactly why.
    for name in ("feed_p95_seconds", "booking_accept_p95_seconds"):
        assert indicators[name].measured is False and indicators[name].value is None
        assert "worker process" in (indicators[name].note or "")
    assert indicators["server_error_rate"].sample_size == 0
    assert indicators["outbox_oldest_pending_seconds"].measured is True


def test_ops_queue_uses_the_owning_modules_and_needs_ops_view(bw: BW) -> None:
    with bw.db.session() as s:
        refused = domain_error(lambda: service.ops_queue(
            s, actor_user_id=bw.w.client_id, queue=OpsQueue.FINANCE_REVIEW.value))
        assert refused.code is ErrorCode.CAPABILITY_REQUIRED
        assert service.ops_queue(s, actor_user_id=bw.operator_id, queue=OpsQueue.FINANCE_REVIEW.value) == []
        assert service.ops_queue(s, actor_user_id=bw.operator_id, queue=OpsQueue.DISPUTE.value) == []
        assert service.ops_queue(s, actor_user_id=bw.operator_id, queue=OpsQueue.TRUST_REVIEW.value) == []
        unknown = domain_error(lambda: service.ops_queue(
            s, actor_user_id=bw.operator_id, queue=OpsQueue.FINANCE_REVIEW.value, corridor_id="cor_00000000000000000000000000"))
        assert unknown.code is ErrorCode.NOT_FOUND


def test_listing_on_behalf_keeps_the_owner_and_records_consent(bw: BW) -> None:
    from app.modules.identity import service as identity_service

    body = passenger_request_body(bw)
    with bw.db.session() as s:
        owner_public = identity_service.user_public_id(s, bw.w.client_id)
        refused = domain_error(lambda: service.create_listing_on_behalf(
            s, actor_user_id=bw.w.client_id, owner_public_id=owner_public, consent_reference="call-1", data=body))
        assert refused.code is ErrorCode.CAPABILITY_REQUIRED
        no_consent = domain_error(lambda: service.create_listing_on_behalf(
            s, actor_user_id=bw.operator_id, owner_public_id=owner_public, consent_reference="  ", data=body))
        assert no_consent.code is ErrorCode.VALIDATION_ERROR and no_consent.details["field"] == "consent_reference"
    with bw.db.session() as s:
        listing = service.create_listing_on_behalf(
            s, actor_user_id=bw.operator_id, owner_public_id=owner_public, consent_reference="tg-call-2026-09-16",
            data=body,
        )
        listing_id, owner_id, operator_id = listing.id, listing.owner_user_id, listing.created_by_operator_id
        s.commit()
    assert owner_id == bw.w.client_id and operator_id == bw.operator_id
    stored = rows(bw.db, "SELECT consent_reference FROM listings WHERE id = :l", l=listing_id)[0]
    assert stored.consent_reference == "tg-call-2026-09-16"
    audit = rows(bw.db, "SELECT details FROM audit_logs WHERE action = 'listing_created_on_behalf'")
    assert len(audit) == 1 and audit[0].details["consent_reference"] == "tg-call-2026-09-16"


def test_listing_on_behalf_through_http(bw: BW, ops_client) -> None:  # noqa: ANN001
    """O-on-behalf over HTTP, not just through the service.

    The route builds the response with `listing_dto(..., viewer_user_id=...)`. Until wave 13 that keyword did
    not exist on the view, so this endpoint raised a TypeError - invisible to a test that called the service
    directly. A staff surface that answers 500 is worse than one that refuses, so the round trip is asserted.
    """
    from app.modules.identity import service as identity_service
    from tests.pg.operations.conftest import auth

    with bw.db.session() as s:
        owner_public = identity_service.user_public_id(s, bw.w.client_id)

    payload = passenger_request_body(bw).model_dump(mode="json")
    payload["owner_user_id"] = owner_public
    payload["consent_reference"] = "tg-call-http"
    response = ops_client.post(
        "/api/v2/admin/listings/on-behalf",
        json=payload,
        headers={**auth(bw.operator_id, "operator"), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["owner"]["id"] == owner_public


def test_public_page_and_share_link_through_http(bw: BW, ops_client) -> None:  # noqa: ANN001
    from tests.pg.operations.conftest import auth

    listing = _published_listing(bw)
    created = ops_client.post(
        f"/api/v2/listings/{listing}/share-links", json={"channel": "telegram", "ttl_hours": 24},
        headers=auth(bw.w.client_id, "client", "idem-share-1"),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    token = data["url"].rsplit("/", 1)[-1]
    replay = ops_client.post(
        f"/api/v2/listings/{listing}/share-links", json={"channel": "telegram", "ttl_hours": 24},
        headers=auth(bw.w.client_id, "client", "idem-share-1"),
    )
    assert replay.status_code == 201 and replay.json()["data"]["id"] == data["id"], "idempotent replay"
    assert scalar(bw.db, "SELECT count(*) FROM share_links") == 1

    page = ops_client.get(f"/api/v2/public/listings/{token}")  # no Authorization header
    assert page.status_code == 200, page.text
    body = page.json()["data"]
    assert body["status_open"] is True and body["cta"] == "open_app_to_offer"
    assert set(body) == {
        "kind", "service_type", "origin_stop_name", "destination_stop_name", "departure_date",
        "departure_window_start", "departure_window_end", "timezone", "price_basis", "unit_price_minor",
        "quantity", "total_minor", "currency", "status_open", "cta",
    }
    assert ops_client.get("/api/v2/public/listings/unknown-token").status_code == 404

    revoked = ops_client.delete(f"/api/v2/share-links/{data['id']}", headers=auth(bw.w.client_id, "client"))
    assert revoked.status_code == 200
    assert ops_client.get(f"/api/v2/public/listings/{token}").status_code == 404
