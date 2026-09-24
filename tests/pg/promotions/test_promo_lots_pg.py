"""Bonus lots and redemptions on PostgreSQL (referral stage 1, ADR-0023). SYNTHETIC amounts only.

QA #9 (one bonus, two bookings), #14 (cancel returns the reserve), #15 (partial spend / expiry / return add up),
#16 (spent reward reversal is no debt), #20 (retry / crash) at the promo-ledger level. The booking integration
itself (accept / cancel / capture calling these functions) is stage 4 and is not claimed here.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import PromoFault
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.promotions import service
from tests.pg.harness import run_concurrently
from tests.pg.promotions.conftest import ADMIN_CAPS, OPERATOR_CAPS, REFEREE_REWARD

pytestmark = pytest.mark.pg


def _lot(promo, lot_id: int) -> dict:  # noqa: ANN001
    with promo.pg_db.engine.connect() as conn:
        return dict(conn.execute(text("SELECT * FROM promo_lots WHERE id = :l"), {"l": lot_id}).mappings().one())


def _buckets(lot: dict) -> int:
    return lot["reserved_minor"] + lot["consumed_minor"] + lot["expired_minor"] + lot["reversed_minor"]


def test_one_bonus_cannot_be_reserved_by_two_bookings(promo, bookings) -> None:  # noqa: ANN001
    """QA #9: two bookings race for the whole lot; exactly one gets it."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking_ids = bookings.ids(2, driver_user_id=bookings.world.driver_id)

    def reserve(index: int, session) -> int:  # noqa: ANN001
        redemption = service.reserve_lot(session, lot_id=lot_id, booking_id=booking_ids[index], amount_minor=REFEREE_REWARD)
        session.commit()
        return redemption.id

    report = run_concurrently(2, reserve, engine=promo.pg_db.engine)
    assert len(report.successes) == 1
    assert report.failures[0].error.code is ErrorCode.PROMO_QUOTE_STALE
    assert _lot(promo, lot_id)["reserved_minor"] == REFEREE_REWARD


def test_one_reservation_is_consumed_once(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        redemption_id = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=150_000).id
        s.commit()

    def consume(index: int, session) -> str:  # noqa: ANN001
        row = service.consume_redemption(session, redemption_id=redemption_id)
        session.commit()
        return row.status

    report = run_concurrently(5, consume, engine=promo.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    assert promo.ledger_count(campaign, "consume") == 1
    lot = _lot(promo, lot_id)
    assert (lot["consumed_minor"], lot["reserved_minor"]) == (150_000, 0)
    assert promo.budget(campaign).consumed_minor == 150_000
    assert promo.issues(campaign) == []


def test_database_refuses_a_double_spend_written_directly(promo, bookings) -> None:  # noqa: ANN001
    """Bypassing the service: a lot whose buckets disagree with its redemptions cannot commit."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with pytest.raises(DBAPIError) as info:
        with promo.pg_db.engine.begin() as conn:  # a redemption without moving the lot's reserved bucket
            conn.execute(text("INSERT INTO promo_redemptions (public_id, lot_id, booking_id, amount_minor) "
                              "VALUES (gen_random_uuid(), :l, :b, :a)"), {"l": lot_id, "b": booking, "a": REFEREE_REWARD})
    assert info.value.orig.diag.constraint_name == "promo_lot_balance_mismatch"
    with pytest.raises(DBAPIError) as info:  # over-reserving beyond the lot amount
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE promo_lots SET reserved_minor = amount_minor + 1 WHERE id = :l"), {"l": lot_id})
    assert info.value.orig.diag.constraint_name == "ck_promo_lots_buckets"
    with pytest.raises(DBAPIError) as info:  # consumed value never comes back
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE promo_lots SET consumed_minor = consumed_minor - 1 WHERE id = :l"), {"l": lot_id})
    assert info.value.orig.diag.constraint_name in {"promo_invalid_transition", "ck_promo_lots_buckets"}


def test_cancel_returns_the_reservation_and_partial_spend_adds_up(promo, bookings) -> None:  # noqa: ANN001
    """QA #14/#15."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    b1, b2, b3 = bookings.ids(3, driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        r1 = service.reserve_lot(s, lot_id=lot_id, booking_id=b1, amount_minor=50_000)
        r2 = service.reserve_lot(s, lot_id=lot_id, booking_id=b2, amount_minor=70_000)
        service.consume_redemption(s, redemption_id=r1.id)
        service.release_redemption(s, redemption_id=r2.id, fault=PromoFault.CLIENT)
        r3 = service.reserve_lot(s, lot_id=lot_id, booking_id=b3, amount_minor=150_000)  # the released 70 000 is back
        s.commit()
    lot = _lot(promo, lot_id)
    assert (lot["consumed_minor"], lot["reserved_minor"]) == (50_000, 150_000)
    assert lot["amount_minor"] - _buckets(lot) == 0
    assert r3.status == "reserved"
    assert promo.issues(campaign) == []


def test_failed_transaction_leaves_no_partial_reservation(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=100_000)
        s.rollback()  # e.g. the booking accept failed after reserving (crash / capacity conflict)
    lot = _lot(promo, lot_id)
    assert lot["reserved_minor"] == 0
    with promo.pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM promo_redemptions WHERE lot_id = :l"), {"l": lot_id}).scalar_one() == 0


def test_expiry_returns_only_free_value_and_reserved_value_follows_its_booking(promo, bookings) -> None:  # noqa: ANN001
    """QA #15: expiry never eats a reservation in flight; a later client-fault release expires that part too."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        redemption_id = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=60_000).id
        s.commit()
    later = utc_now() + timedelta(days=61)
    with promo.session() as s:
        assert service.expire_due_lots(s, now=later) == [lot_id]
        s.commit()
    lot = _lot(promo, lot_id)
    assert (lot["status"], lot["expired_minor"], lot["reserved_minor"]) == ("expired", REFEREE_REWARD - 60_000, 60_000)
    with promo.session() as s:
        service.release_redemption(s, redemption_id=redemption_id, fault=PromoFault.CLIENT, now=later)
        s.commit()
    lot = _lot(promo, lot_id)
    assert (lot["expired_minor"], lot["reserved_minor"]) == (REFEREE_REWARD, 0)
    position = promo.budget(campaign)
    assert position.released_minor >= REFEREE_REWARD
    assert promo.issues(campaign) == []


def test_driver_fault_release_restores_an_expired_bonus(promo, bookings) -> None:  # noqa: ANN001
    """Fair restoration (ADR-0023 §7): the client does not lose a bonus because the driver cancelled late."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        redemption_id = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=REFEREE_REWARD).id
        s.commit()
    later = utc_now() + timedelta(days=61)
    with promo.session() as s:
        service.expire_due_lots(s, now=later)
        service.release_redemption(s, redemption_id=redemption_id, fault=PromoFault.DRIVER, now=later)
        s.commit()
    lot = _lot(promo, lot_id)
    assert lot["status"] == "available"
    assert lot["expires_at"] >= later + timedelta(days=7) - timedelta(seconds=1)
    assert lot["amount_minor"] - _buckets(lot) == REFEREE_REWARD
    assert promo.issues(campaign) == []


def test_cancel_consume_and_expiry_racing_keep_the_books_straight(promo, bookings) -> None:  # noqa: ANN001
    """Parallel consume, release and the expiry job on one lot: one outcome per redemption, nothing counted twice."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    b1, b2 = bookings.ids(2, driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        r1 = service.reserve_lot(s, lot_id=lot_id, booking_id=b1, amount_minor=80_000).id
        r2 = service.reserve_lot(s, lot_id=lot_id, booking_id=b2, amount_minor=40_000).id
        s.commit()
    later = utc_now() + timedelta(days=61)

    def work(index: int, session) -> str:  # noqa: ANN001
        if index % 3 == 0:
            service.consume_redemption(session, redemption_id=r1)
        elif index % 3 == 1:
            service.release_redemption(session, redemption_id=r1, fault=PromoFault.CLIENT, now=later)
        else:
            service.expire_due_lots(session, now=later)
            service.consume_redemption(session, redemption_id=r2)
        session.commit()
        return "ok"

    report = run_concurrently(9, work, engine=promo.pg_db.engine)
    for failure in report.failures:  # a loser of consume-vs-release sees the other's terminal state, nothing else
        assert isinstance(failure.error, DomainError) and failure.error.code is ErrorCode.INVALID_STATE_TRANSITION
    lot = _lot(promo, lot_id)
    with promo.pg_db.engine.connect() as conn:
        statuses = dict(conn.execute(text("SELECT id, status FROM promo_redemptions WHERE lot_id = :l"), {"l": lot_id}).all())
    assert statuses[r2] == "consumed" and statuses[r1] in {"consumed", "released"}
    assert lot["reserved_minor"] == 0
    assert lot["amount_minor"] == _buckets(lot)
    assert promo.ledger_count(campaign, "consume") == (2 if statuses[r1] == "consumed" else 1)
    assert promo.issues(campaign) == []


def test_reversal_after_spending_is_risk_cost_not_debt(promo, bookings) -> None:  # noqa: ANN001
    """QA #16: consumed value stays consumed; only free value returns; nothing touches anyone's real balance."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    b1, b2 = bookings.ids(2, driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        r1 = service.reserve_lot(s, lot_id=lot_id, booking_id=b1, amount_minor=50_000)
        service.consume_redemption(s, redemption_id=r1.id)
        r2 = service.reserve_lot(s, lot_id=lot_id, booking_id=b2, amount_minor=30_000)
        s.commit()
        r2_id = r2.id
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.reverse_lot(s, lot_id=lot_id, actor_user_id=promo.operator_id, actor_capabilities=OPERATOR_CAPS,
                                reason="operator may review, not decide")
        assert exc.value.code is ErrorCode.FORBIDDEN
    with promo.session() as s:
        service.reverse_lot(s, lot_id=lot_id, actor_user_id=promo.admin_id, actor_capabilities=ADMIN_CAPS,
                            reason="synthetic confirmed abuse")
        s.commit()
    lot = _lot(promo, lot_id)
    assert (lot["status"], lot["consumed_minor"], lot["reversed_minor"], lot["reserved_minor"]) == (
        "reversed", 50_000, REFEREE_REWARD - 80_000, 30_000)
    with promo.session() as s:  # the in-flight reservation is released later: it is reversed, not restored
        service.release_redemption(s, redemption_id=r2_id, fault=PromoFault.DRIVER)
        s.commit()
    lot = _lot(promo, lot_id)
    assert (lot["reversed_minor"], lot["reserved_minor"]) == (REFEREE_REWARD - 50_000, 0)
    assert promo.budget(campaign).consumed_minor == 50_000
    assert promo.issues(campaign) == []


def test_review_lot_cannot_be_spent_until_released(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    obligations = promo.promise(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        lot = service.grant_obligation(s, obligation_id=obligations[1], hold_for_review=True)
        s.commit()
        lot_id = lot.id
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=1)
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
    with promo.session() as s:
        service.make_lot_available(s, lot_id=lot_id, actor_user_id=promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                   reason="reviewed")
        service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=1)
        s.commit()


def test_a_release_after_the_end_expires_the_free_remainder_too(promo, bookings) -> None:  # noqa: ANN001
    """Stage-4 finding: a release that finds the lot past its end marks it expired; its free remainder expires with
    it (the expiry job no longer visits an expired lot), so the buckets still add up."""
    campaign = promo.campaign()
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        redemption = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=80_000).id
        s.commit()
    with promo.session() as s:
        service.release_redemption(s, redemption_id=redemption, fault=PromoFault.CLIENT, now=utc_now() + timedelta(days=61))
        s.commit()
    lot = _lot(promo, lot_id)
    assert (lot["status"], lot["reserved_minor"], lot["expired_minor"]) == ("expired", 0, REFEREE_REWARD)
    assert lot["amount_minor"] == _buckets(lot)
    assert promo.issues(campaign) == []
