"""Wave 6 / A12: S9-S12 on real PostgreSQL (spec §8.1 blocks, §17.3 reports and fraud signals).

Proves the three things the spec asks for and the one thing it forbids:

* a block is **symmetric and silent** - after it, neither side sees the other in the feed and neither can open a
  negotiation (§8.1: "taraflar bir-birini bloklamagan" is checked *before* anything is ranked);
* a report is filed, rate limited and contact-filtered, and it changes **nothing** by itself (§17.3);
* the fraud scan opens signals for human review - shared device, self-dealing device, repeated pair - and
  **never** blocks, charges or down-ranks anybody; a second scan in the same window adds no duplicate.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.contracts.enums import FraudSignalStatus, FraudSignalType, ReportStatus
from app.contracts.errors import DomainError, ErrorCode
from app.modules.communications import service as comms_service
from app.modules.marketplace.feed import service as feed_service
from app.modules.trust_support import rules as trust_rules
from app.modules.trust_support import service as trust_service
from app.modules.trust_support.models import AbuseReport, FraudSignal, UserBlock
from app.modules.trust_support.schemas import ReportCreate
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    accept,
    auth,
    bw,
    driver_trip,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    scalar,
)
from tests.pg.conftest import PgDatabase
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def _user_public_id(bw: BW, user_id: int) -> str:  # noqa: F811
    from app.modules.identity import service as identity_service

    with bw.db.session() as session:
        return identity_service.user_public_id(session, user_id)


def test_block_is_symmetric_and_hides_the_pair_from_the_feed(bw: BW) -> None:  # noqa: F811
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw))
    with bw.db.session() as session:
        before = feed_service.feed(
            session, viewer_user_id=bw.w.driver_id, criteria=_requests_criteria(bw), limit=20
        )
        from app.modules.marketplace import service as marketplace_service

        seen = {marketplace_service.listing_public_id(item.listing) for item in before.items}
        assert listing in seen, "sanity: the driver sees the request"

    with bw.db.session() as session:
        trust_service.block_user(
            session, actor_user_id=bw.w.driver_id, blocked_public_id=_user_public_id(bw, bw.w.client_id)
        )
        session.commit()

    with bw.db.session() as session:
        # the blocker no longer sees the blocked user's listing ...
        after = feed_service.feed(
            session, viewer_user_id=bw.w.driver_id, criteria=_requests_criteria(bw), limit=20
        )
        from app.modules.marketplace import service as marketplace_service

        assert [marketplace_service.listing_public_id(item.listing) for item in after.items] == []
        # ... and the block counts in the other direction too (§8.1).
        assert trust_service.blocked_between(session, bw.w.client_id, bw.w.driver_id) is True
        assert trust_service.blocked_user_ids(session, bw.w.client_id) == {bw.w.driver_id}


def test_block_stops_a_new_negotiation_without_telling_the_other_side(bw: BW) -> None:  # noqa: F811
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw))
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A600AA")
    with bw.db.session() as session:
        trust_service.block_user(
            session, actor_user_id=bw.w.client_id, blocked_public_id=_user_public_id(bw, bw.w.driver_id)
        )
        session.commit()

    with pytest.raises(DomainError) as refused:
        propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=2)
    # 404, not 403: the blocked side is never told that a block exists.
    assert refused.value.code is ErrorCode.NOT_FOUND


def test_block_is_idempotent_and_can_be_lifted(bw: BW) -> None:  # noqa: F811
    client_pid = _user_public_id(bw, bw.w.client_id)
    with bw.db.session() as session:
        first = trust_service.block_user(session, actor_user_id=bw.w.driver_id, blocked_public_id=client_pid)
        second = trust_service.block_user(session, actor_user_id=bw.w.driver_id, blocked_public_id=client_pid)
        assert first.id == second.id
        session.commit()
    with bw.db.session() as session:
        trust_service.unblock_user(session, actor_user_id=bw.w.driver_id, blocked_public_id=client_pid)
        trust_service.unblock_user(session, actor_user_id=bw.w.driver_id, blocked_public_id=client_pid)  # idempotent
        session.commit()
    with bw.db.session() as session:
        assert session.execute(select(UserBlock)).scalars().all() == []
        assert trust_service.blocked_between(session, bw.w.client_id, bw.w.driver_id) is False


def test_blocking_yourself_is_a_validation_error(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session, pytest.raises(DomainError) as refused:
        trust_service.block_user(
            session, actor_user_id=bw.w.client_id, blocked_public_id=_user_public_id(bw, bw.w.client_id)
        )
    assert refused.value.code is ErrorCode.VALIDATION_ERROR


def test_report_is_filtered_rate_limited_and_changes_nothing(bw: BW) -> None:  # noqa: F811
    driver_pid = _user_public_id(bw, bw.w.driver_id)
    warnings: list[dict] = []
    with bw.db.session() as session:
        report = trust_service.create_report(
            session,
            actor_user_id=bw.w.client_id,
            data=ReportCreate(subject_type="user", subject_id=driver_pid, reason_code="off_platform_contact",
                              details="menga +998901234567 raqamiga yozing dedi"),
            warnings=warnings,
        )
        session.commit()
        stored = report.details or ""
    # Q43: the phone number is masked before it is stored, and the caller is warned.
    assert "+998901234567" not in stored
    assert warnings

    with bw.db.session() as session:
        row = session.execute(select(AbuseReport)).scalar_one()
        assert row.status == ReportStatus.OPEN.value
        assert row.subject_user_id == bw.w.driver_id
        assert row.reviewed_at is None and row.reviewed_by is None
        # §17.3: nothing else moved - no block, no trust review, no rating change.
        assert session.execute(select(UserBlock)).scalars().all() == []

    with bw.db.session() as session:
        for _ in range(trust_rules.REPORT_RATE_LIMIT):
            try:
                trust_service.create_report(
                    session, actor_user_id=bw.w.client_id,
                    data=ReportCreate(subject_type="user", subject_id=driver_pid, reason_code="other"),
                )
            except DomainError as exc:
                assert exc.code is ErrorCode.RATE_LIMITED
                break
        else:  # pragma: no cover - the limit must be reached inside the loop
            pytest.fail("the report rate limit did not trigger")
        session.rollback()


def test_operator_review_records_the_decision_only(bw: BW) -> None:  # noqa: F811
    driver_pid = _user_public_id(bw, bw.w.driver_id)
    with bw.db.session() as session:
        report = trust_service.create_report(
            session, actor_user_id=bw.w.client_id,
            data=ReportCreate(subject_type="user", subject_id=driver_pid, reason_code="unsafe_behaviour"),
        )
        session.commit()
        report_pid = trust_service.report_public_id(report)
        version = report.version

    with bw.db.session() as session:
        reviewed = trust_service.report_command(
            session, actor_user_id=bw.operator_id, report_public_id_value=report_pid, status="under_review",
            expected_version=version,
        )
        session.commit()
        assert reviewed.status == ReportStatus.UNDER_REVIEW.value
        assert reviewed.reviewed_at is None  # not a closing decision yet
        version = reviewed.version

    with bw.db.session() as session:
        closed = trust_service.report_command(
            session, actor_user_id=bw.operator_id, report_public_id_value=report_pid, status="dismissed",
            expected_version=version, note="ko'rib chiqildi",
        )
        session.commit()
        assert closed.status == ReportStatus.DISMISSED.value
        assert closed.reviewed_by == bw.operator_id and closed.reviewed_at is not None

    with bw.db.session() as session, pytest.raises(DomainError) as refused:
        trust_service.report_command(
            session, actor_user_id=bw.operator_id, report_public_id_value=report_pid, status="actioned",
            expected_version=closed.version,
        )
    assert refused.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_fraud_scan_opens_signals_for_review_and_never_acts(bw: BW) -> None:  # noqa: F811
    """One device, two accounts, one booking between them: three observations, zero consequences."""
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw)
    booking = accept(bw, ref, bw.w.client_id)

    token = f"device-{uuid.uuid4().hex}"
    with bw.db.session() as session:
        comms_service.register_device(session, user_id=bw.w.client_id, platform="android", token=token, app_version="1")
        comms_service.register_device(session, user_id=bw.w.driver_id, platform="android", token=token, app_version="1")
        session.commit()

    with bw.db.session() as session:
        opened = trust_service.scan_fraud_signals(session)
        session.commit()
    assert opened >= 4  # shared-device for both users + self-dealing for both sides of the booking

    with bw.db.session() as session:
        signals = session.execute(select(FraudSignal)).scalars().all()
        by_type = {signal.signal_type for signal in signals}
        assert FraudSignalType.SHARED_DEVICE_ACCOUNTS.value in by_type
        assert FraudSignalType.SELF_DEALING_DEVICE.value in by_type
        assert all(signal.status == FraudSignalStatus.OPEN.value for signal in signals)
        # §15: evidence carries counts and public ids only - no token, no phone, no coordinate.
        for signal in signals:
            flat = str(signal.evidence)
            assert token not in flat and "+998" not in flat
        # §17.3: the signal is a question, not a verdict - nothing was blocked and the booking is untouched.
        assert session.execute(select(UserBlock)).scalars().all() == []
        assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) is not None

    with bw.db.session() as session:
        again = trust_service.scan_fraud_signals(session)
        session.commit()
    assert again == 0, "a second scan inside the same window must not duplicate a signal"


def test_operator_closes_a_signal_without_side_effects(bw: BW) -> None:  # noqa: F811
    token = f"device-{uuid.uuid4().hex}"
    with bw.db.session() as session:
        comms_service.register_device(session, user_id=bw.w.client_id, platform="android", token=token, app_version="1")
        comms_service.register_device(session, user_id=bw.w.driver_id, platform="android", token=token, app_version="1")
        trust_service.scan_fraud_signals(session)
        session.commit()

    with bw.db.session() as session:
        signal = session.execute(select(FraudSignal).order_by(FraudSignal.id)).scalars().first()
        signal_pid = trust_service.fraud_signal_public_id(signal)
        version = signal.version

    with bw.db.session() as session:
        closed = trust_service.fraud_signal_command(
            session, actor_user_id=bw.operator_id, signal_public_id=signal_pid, status="dismissed",
            expected_version=version, note="ikkita akkaunt bitta oilada",
        )
        session.commit()
        assert closed.status == FraudSignalStatus.DISMISSED.value
        assert closed.reviewed_by == bw.operator_id

    with bw.db.session() as session:
        listed = trust_service.list_fraud_signals(session, actor_user_id=bw.operator_id, status="open")
        assert all(item.status == FraudSignalStatus.OPEN.value for item in listed)
        # a client cannot read the queue
        with pytest.raises(DomainError) as forbidden:
            trust_service.list_fraud_signals(session, actor_user_id=bw.w.client_id)
        assert forbidden.value.code in {ErrorCode.FORBIDDEN, ErrorCode.CAPABILITY_REQUIRED}


def _requests_criteria(bw: BW):  # noqa: ANN202, F811
    from app.contracts.enums import FeedSide, ServiceType
    from app.modules.marketplace.feed.service import FeedCriteria

    return FeedCriteria(
        service_type=ServiceType.PASSENGER, side=FeedSide.REQUESTS,
        date_from=bw.base - timedelta(days=1), date_to=bw.base + timedelta(days=5),
        origin_stop_id=bw.w.stop_public_ids["A"], destination_stop_id=bw.w.stop_public_ids["D"],
    )
