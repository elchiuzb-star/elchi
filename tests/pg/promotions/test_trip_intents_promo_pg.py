"""Saved requests (ADR-0025) with promotions on PostgreSQL: every driver's offer has its own promo terms, only the
accepted one reserves anything, and a parallel loser leaves no lot reservation and no hold. SYNTHETIC values only."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.contracts.enums import PromoInstrument
from app.contracts.errors import DomainError, ErrorCode
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from tests.pg.bookings.conftest import BW, bw, listing_version  # noqa: F401  (fixtures)
from tests.pg.marketplace.test_trip_intents_pg import (
    UNIT,
    _create,
    _offer,
    _proposal,
    _propose,
    _staged,
)
from tests.pg.promotions.booking_world import BPS, CAP, H_LOT, P_LOT, PW, use_policy
from tests.pg.promotions.referral_world import Ref, enable_promotions

pytestmark = pytest.mark.pg

FARE = 3 * UNIT  # 3 people x 190 000 so'm = 570 000 so'm
C = FARE * BPS // 10_000


@pytest.fixture
def pw(bw: BW, promo) -> PW:  # noqa: ANN001, F811
    enable_promotions(promo.pg_db)
    use_policy(bw, BPS)
    return PW(bw, Ref(promo))


def _driver_accept(pw: PW, ref, driver: int):  # noqa: ANN001, ANN202
    def run(session: Session) -> Booking:
        return bookings_service.accept_proposal(
            session, thread_public_id=ref.thread_id, actor_user_id=driver, proposal_version_public_id=ref.version_id,
            expected_listing_version=listing_version(pw.bw, ref.listing_id), client_features=CAP,
            client_session=pw.sid(driver))
    return run


def test_parallel_accepts_from_one_request_reserve_promo_only_for_the_booking(pw: PW) -> None:
    bw = pw.bw
    h1 = pw.lot(bw.w.driver_id, PromoInstrument.DRIVER_CREDIT, H_LOT)
    h2 = pw.lot(bw.w.driver2_id, PromoInstrument.DRIVER_CREDIT, H_LOT)
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing1, _ = _offer(bw, bw.w.driver_id, "01P100PA")
    listing2, _ = _offer(bw, bw.w.driver2_id, "01P101PA")
    ref1 = _propose(bw, listing1, bw.w.client_id, _proposal(bw, intent_id, version_no))
    ref2 = _propose(bw, listing2, bw.w.client_id, _proposal(bw, intent_id, version_no))
    for driver, ref in ((bw.w.driver_id, ref1), (bw.w.driver2_id, ref2)):
        pw.ready(ref, driver)  # each driver's own app declared it can render its credit (Q126)

    won, lost = _staged(bw, _driver_accept(pw, ref1, bw.w.driver_id), _driver_accept(pw, ref2, bw.w.driver2_id))
    assert isinstance(won, Booking)
    assert isinstance(lost, DomainError) and lost.code in (ErrorCode.TRIP_INTENT_BOOKED, ErrorCode.PROPOSAL_CHANGED)
    [terms] = pw.terms(won.id)
    assert (terms["driver_credit_minor"], terms["net_commission_minor"]) == (H_LOT, C - H_LOT)  # the winner's own H
    assert pw.lot_row(h1)["reserved_minor"] == H_LOT
    assert pw.lot_row(h2)["reserved_minor"] == 0  # the loser's credit was never touched
    assert pw.scalar("SELECT count(*) FROM wallet_holds") == 1 and pw.hold(won.id)[:2] == (C - H_LOT, "active")
    assert pw.scalar("SELECT count(*) FROM promo_booking_terms") == 1
    assert pw.ref.promo.issues() == []


def test_a_bonus_consent_belongs_to_one_drivers_offer_and_is_never_carried_to_another(pw: PW) -> None:
    bw = pw.bw
    client = bw.w.client_id
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    intent_id, version_no = _create(bw, client)
    listing1, _ = _offer(bw, bw.w.driver_id, "01P110PA")
    listing2, _ = _offer(bw, bw.w.driver2_id, "01P111PA")
    ref1 = _propose(bw, listing1, client, _proposal(bw, intent_id, version_no))
    ref2 = _propose(bw, listing2, client, _proposal(bw, intent_id, version_no))
    pw.consent_on(ref1.version_id, client, P_LOT, FARE - P_LOT)  # shown and agreed on driver 1's offer only
    for driver, ref in ((bw.w.driver_id, ref1), (bw.w.driver2_id, ref2)):
        pw.ready(ref, driver)
    booking = _driver_accept(pw, ref2, bw.w.driver2_id)
    with pw.db.session() as s:
        booked = booking(s)
        s.commit()
    assert pw.terms(booked.id) == [] or pw.terms(booked.id)[0]["passenger_bonus_minor"] == 0  # no consent here
    assert pw.hold(booked.id)[:2] == (C, "active")
    assert pw.scalar("SELECT count(*) FROM promo_consents WHERE status = 'active'") <= 1  # driver 1's stays unused
    assert pw.scalar("SELECT coalesce(sum(reserved_minor), 0) FROM promo_lots WHERE owner_user_id = :c", c=client) == 0
    assert pw.ref.promo.issues() == []
