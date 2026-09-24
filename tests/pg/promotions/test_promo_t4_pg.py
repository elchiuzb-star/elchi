"""T4 decisions in the real booking flow on PostgreSQL (referral stage 5, ADR-0023 §18.1, Q123-Q129).

Every flow goes through ``bookings.service`` and the promotions services; the database's deferred money check and the
0089 constraints are part of what is tested. SYNTHETIC amounts, campaigns and people only - no value here is approved.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import STAFF_ROLE_CAPABILITIES, PromoCampaignKind, PromoInstrument, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.promotions import booking as promo_booking
from app.modules.promotions import qualification
from app.modules.promotions import service as promo_service
from app.modules.wallet import service as wallet_service
from tests.pg.bookings.conftest import BW, act, bw, counter, run_trip_action, view  # noqa: F401
from tests.pg.harness import run_concurrently
from tests.pg.promotions.booking_world import BPS, CAP, FARE, H_LOT, OLD, P_LOT, PW, use_policy
from tests.pg.promotions.conftest import SYNTH_POLICY, synthetic_terms
from tests.pg.promotions.referral_world import Ref, enable_promotions

pytestmark = pytest.mark.pg

ADMIN_CAPS = STAFF_ROLE_CAPABILITIES[Role.ADMIN]
FINANCE_CAPS = STAFF_ROLE_CAPABILITIES[Role.FINANCE]
DRIVER_CLIENT = PromoCampaignKind.REFERRAL_DRIVER_CLIENT


@pytest.fixture
def pw(bw: BW, promo) -> PW:  # noqa: ANN001, F811
    enable_promotions(promo.pg_db)
    use_policy(bw, BPS)
    return PW(bw, Ref(promo))


def _code(exc: pytest.ExceptionInfo) -> ErrorCode:
    return exc.value.code


def _campaign_of(pw: PW, lot_id: int) -> int:
    return pw.scalar("SELECT campaign_id FROM promo_lots WHERE id = :l", l=lot_id)


def _h_campaign(pw: PW, **policy) -> int:  # noqa: ANN003
    return pw.ref.campaign(kind=DRIVER_CLIENT, margin_policy=replace(SYNTH_POLICY, **policy))


def _expire_now(pw: PW, *lot_ids: int) -> None:
    """The lots reach their end while reserved for a booking (synthetic clock move)."""
    with pw.db.engine.begin() as conn:
        for lot_id in lot_ids:
            conn.execute(text("UPDATE promo_lots SET expires_at = now() + interval '1 second' WHERE id = :l"), {"l": lot_id})
    pw.wait_until_expired(*lot_ids)


def _operator_cancel(pw: PW, booking_id: int, fault: str | None) -> None:
    with pw.db.session() as s:
        b = s.get(Booking, booking_id)
        bookings_service.operator_command(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=pw.bw.super_id,
            command="cancel", expected_version=b.version, reason="synthetic operator cancel", cancel_fault_side=fault)
        s.commit()


# --- Q123: one campaign per instrument, explicit combinations ----------------------------------------------------------


def test_q123_an_unapproved_pair_applies_p_only_and_an_approved_pair_records_both_campaigns(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    trip, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))  # no approved pairing: H is simply not applied
    [terms] = pw.terms(booking.id)
    assert (terms["passenger_bonus_minor"], terms["driver_credit_minor"], terms["passenger_campaign_id"],
            terms["driver_campaign_id"], terms["combination_cost_basis"]) == (
        P_LOT, 0, _campaign_of(pw, p_lot), None, None)
    assert pw.lot_row(h_lot)["reserved_minor"] == 0

    client2, driver2 = pw.ref.client(), pw.bw.w.driver2_id
    p2 = pw.lot(client2, PromoInstrument.PASSENGER_BONUS, P_LOT, campaign=_campaign_of(pw, p_lot))
    h2 = pw.lot(driver2, PromoInstrument.DRIVER_CREDIT, H_LOT, campaign=_campaign_of(pw, h_lot))
    pw.combine(p2, h2, "shared")  # the super_admin approves this pair of campaigns
    _, ref2 = pw.offer(client2, driver2, dropoff="C")
    booking2 = pw.accept(ref2, client2, consent=(P_LOT, FARE - P_LOT))
    [terms2] = pw.terms(booking2.id)
    assert (terms2["passenger_bonus_minor"], terms2["driver_credit_minor"], terms2["passenger_campaign_id"],
            terms2["driver_campaign_id"], terms2["combination_cost_basis"]) == (
        P_LOT, H_LOT, _campaign_of(pw, p_lot), _campaign_of(pw, h_lot), "shared")
    assert pw.ref.promo.issues() == []


def test_q123_shared_takes_the_larger_cost_and_additive_counts_both(pw: PW) -> None:
    """Synthetic: the H campaign carries O = 12 000 so'm of its own. shared -> O = 12 000 (room for H: 2 000),
    additive -> O = 13 000 (room for H: 1 000). max(O) never silently drops a cost the pairing says is separate."""
    results = {}
    for basis, driver in (("shared", pw.bw.w.driver_id), ("additive", pw.bw.w.driver2_id)):
        client = pw.ref.client()
        p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
        h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT,
                       campaign=_h_campaign(pw, variable_cost_fixed_minor=1_200_000))
        pw.combine(p_lot, h_lot, basis)
        _, ref = pw.offer(client, driver, dropoff="D" if basis == "shared" else "C")
        results[basis] = pw.terms(pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT)).id)[0]
    shared, additive = results["shared"], results["additive"]
    assert (shared["passenger_bonus_minor"], shared["driver_credit_minor"], shared["variable_cost_minor"]) == (
        P_LOT, 200_000, 1_200_000)
    assert (additive["passenger_bonus_minor"], additive["driver_credit_minor"], additive["variable_cost_minor"]) == (
        P_LOT, 100_000, 1_300_000)
    for row in (shared, additive):  # the floor holds on the combined cost
        assert row["net_commission_minor"] - row["variable_cost_minor"] >= row["min_margin_minor"]


def test_q123_p_comes_from_one_campaign_and_the_database_refuses_a_mixed_booking(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    first = pw.lot(client, PromoInstrument.PASSENGER_BONUS, 600_000)
    other = pw.lot(client, PromoInstrument.PASSENGER_BONUS, 600_000)  # the same amount in another campaign
    _, ref = pw.offer(client, driver)
    with pytest.raises(DomainError) as exc:  # 12 000 would need two campaigns: never offered, never applied
        pw.accept(ref, client, consent=(1_200_000, FARE - 1_200_000))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE and exc.value.details["reasons"] == ["passenger_bonus_changed"]
    booking = pw.accept(ref, client, consent=(600_000, FARE - 600_000))
    assert [r[0] for r in pw.redemptions(booking.id)] == [first]  # one campaign: the soonest-expiring of equals
    assert pw.lot_row(other)["reserved_minor"] == 0
    # the same P forced in from the other campaign by SQL: the sums still match, the campaign does not
    with pytest.raises(DBAPIError) as db_exc, pw.db.engine.begin() as conn:
        conn.execute(text("UPDATE promo_redemptions SET status = 'released', settled_at = now(), release_fault = 'none' "
                          "WHERE booking_id = :b"), {"b": booking.id})
        conn.execute(text("UPDATE promo_lots SET reserved_minor = 0 WHERE id = :l"), {"l": first})
        conn.execute(text("INSERT INTO promo_redemptions (public_id, lot_id, booking_id, amount_minor, terms_seq, status) "
                          "VALUES (gen_random_uuid(), :l, :b, 600000, 1, 'reserved')"), {"l": other, "b": booking.id})
        conn.execute(text("UPDATE promo_lots SET reserved_minor = 600000 WHERE id = :l"), {"l": other})
    assert db_exc.value.orig.diag.constraint_name == "promo_booking_terms_mismatch"


def test_q123_adding_h_never_lowers_the_consented_p(pw: PW) -> None:
    """The H campaign caps the whole discount at 4 000 so'm: combining it would shrink the client's agreed 5 000.
    P is kept exactly and H is not applied - no hidden reduction of P (a smaller P needs a new consent)."""
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT,
                   campaign=_h_campaign(pw, max_discount_per_booking_minor=400_000))
    pw.combine(p_lot, h_lot, "shared")
    _, ref = pw.offer(client, driver)
    [terms] = pw.terms(pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT)).id)
    assert (terms["passenger_bonus_minor"], terms["driver_credit_minor"], terms["cash_due_minor"]) == (
        P_LOT, 0, FARE - P_LOT)


def test_q123_a_revoked_pairing_stops_new_bookings_but_not_the_agreed_one(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.combine(p_lot, h_lot, "shared")
    _, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    combination = pw.scalar("SELECT id FROM promo_campaign_combinations WHERE status = 'active'")
    from tests.pg.promotions.conftest import SUPER_CAPS

    with pw.db.session() as s:
        promo_service.revoke_combination(s, actor_user_id=pw.ref.promo.super_id, actor_capabilities=SUPER_CAPS,
                                         combination_id=combination, expected_version=1, reason="synthetic stop")
        s.commit()
    with pytest.raises(DBAPIError) as exc, pw.db.engine.begin() as conn:  # revoked is final; rows are never deleted
        conn.execute(text("DELETE FROM promo_campaign_combinations WHERE id = :c"), {"c": combination})
    assert exc.value.orig.diag.constraint_name == "append_only_violation"
    assert pw.terms(booking.id)[0]["combination_cost_basis"] == "shared"  # the agreement keeps what it was made under
    client2, driver2 = pw.ref.client(), pw.bw.w.driver2_id
    pw.lot(client2, PromoInstrument.PASSENGER_BONUS, P_LOT, campaign=_campaign_of(pw, p_lot))
    pw.lot(driver2, PromoInstrument.DRIVER_CREDIT, H_LOT, campaign=_campaign_of(pw, h_lot))
    _, ref2 = pw.offer(client2, driver2, dropoff="C")
    assert pw.terms(pw.accept(ref2, client2, consent=(P_LOT, FARE - P_LOT)).id)[0]["driver_credit_minor"] == 0


# --- Q124: driver credit alone ------------------------------------------------------------------------------------------


def test_q124_a_driver_credit_only_booking_keeps_the_old_client_semantics(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    trip, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, features=OLD)  # an old client app: nothing about the discount is asked of it
    [terms] = pw.terms(booking.id)
    assert (terms["passenger_bonus_minor"], terms["driver_credit_minor"], terms["cash_due_minor"]) == (0, H_LOT, FARE)
    assert view(pw.bw, booking.id, "client")["promo"] is None  # exactly what a plain booking shows the client
    assert view(pw.bw, booking.id, "driver")["promo"]["commission_charged_minor"] == 2_000_000 - H_LOT
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    receipt = pw.report_cash(booking.id, driver, FARE)  # the receipt is F, as without promotions
    pw.acknowledge_cash(booking.id, client, receipt, features=OLD)  # the old client app may confirm it
    with pytest.raises(DomainError) as exc:  # the driver's app still has to show H and C_net
        pw.report_cash(booking.id, driver, FARE, features=OLD)
    assert _code(exc) in (ErrorCode.CLIENT_UPGRADE_REQUIRED, ErrorCode.INVALID_STATE_TRANSITION)
    assert pw.lot_row(h_lot)["reserved_minor"] == H_LOT


def test_q124_the_exception_never_lets_a_passenger_bonus_in_later(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    _, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, features=OLD)
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)  # the client receives a bonus afterwards
    with pw.db.session() as s:  # an old client app proposes a cheaper fare: no consent is asked (P stays 0) ...
        b = s.get(Booking, booking.id)
        amendment = bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=client,
            expected_version=b.version, changes={"unit_price_minor": 15_000_000}, reason="synthetic change",
            client_features=OLD)
        s.commit()
        public = format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id)
    new_c_net = 1_500_000 - H_LOT
    with pw.db.session() as s:  # ... the driver confirms its new commission, and no bonus appears
        bookings_service.accept_amendment(s, amendment_public_id=public, actor_user_id=driver, expected_version=1,
                                          client_features=CAP, client_session=pw.sid(driver),
                                          promo_driver_ack=promo_booking.DriverAck(15_000_000, new_c_net))
        s.commit()
    latest = pw.terms(booking.id)[-1]
    assert (latest["passenger_bonus_minor"], latest["cash_due_minor"], latest["driver_credit_minor"]) == (
        0, 15_000_000, H_LOT)


# --- Q125: amendments -------------------------------------------------------------------------------------------------


def test_q125_an_amendment_takes_no_new_lot_and_never_grows_the_discount(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    first = pw.lot(client, PromoInstrument.PASSENGER_BONUS, 200_000)
    _, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=(200_000, FARE - 200_000))
    later = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT, campaign=_campaign_of(pw, first))
    with pw.db.session() as s:  # the client asks for a higher fare: its discount stays 2 000, the new lot untouched
        b = s.get(Booking, booking.id)
        amendment = bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=client,
            expected_version=b.version, changes={"unit_price_minor": 25_000_000}, reason="synthetic change",
            client_features=CAP, client_session=pw.sid(client),
            promo_consent=promo_booking.ConsentInput(200_000, 24_800_000))
        s.commit()
        public = format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id)
    before = (pw.terms(booking.id), pw.redemptions(booking.id), pw.hold(booking.id))
    with pw.db.session() as s, pytest.raises(DomainError) as exc:  # the driver's own numbers must be confirmed
        bookings_service.accept_amendment(s, amendment_public_id=public, actor_user_id=driver, expected_version=1,
                                          client_features=CAP, client_session=pw.sid(driver),
                                          promo_driver_ack=promo_booking.DriverAck(24_800_000, 1))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert (pw.terms(booking.id), pw.redemptions(booking.id), pw.hold(booking.id)) == before  # old agreement kept
    with pw.db.session() as s:
        bookings_service.accept_amendment(s, amendment_public_id=public, actor_user_id=driver, expected_version=1,
                                          client_features=CAP, client_session=pw.sid(driver),
                                          promo_driver_ack=promo_booking.DriverAck(24_800_000, 2_300_000))
        s.commit()
    latest = pw.terms(booking.id)[-1]
    assert (latest["fare_minor"], latest["passenger_bonus_minor"], latest["cash_due_minor"]) == (
        25_000_000, 200_000, 24_800_000)
    assert pw.lot_row(later)["reserved_minor"] == 0
    assert [r for r in pw.redemptions(booking.id) if r[2] == "reserved"] == [(first, 200_000, "reserved", 2)]


# --- Q126: readiness bound to version, session and expiry ------------------------------------------------------------------


def _p_only_offer(pw: PW) -> tuple[int, int, object]:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    _, ref = pw.offer(client, driver)
    return client, driver, ref


def test_q126_the_passive_drivers_readiness_ends_with_its_session_and_is_renewed_by_a_new_confirmation(pw: PW) -> None:
    client, driver, ref = _p_only_offer(pw)
    pw.end_session(driver)  # the driver logged out after sending the offer
    with pytest.raises(DomainError) as exc:
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert exc.value.details["reasons"] == ["counterparty_client_outdated"]
    with pw.db.session() as s:
        from app.modules.marketplace import service as marketplace_service

        thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
        version = marketplace_service.current_version(s, thread)
        assert promo_booking.version_confirmation_state(s, version=version, viewer_user_id=driver) == "stale"
    pw._sids.pop(driver)  # the driver logs in again: a new session
    with pw.db.session() as s:
        from app.modules.marketplace import service as marketplace_service

        thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
        promo_booking.confirm_current_version(
            s, thread=thread, actor_user_id=driver, proposal_version_id=marketplace_service.current_version(s, thread).id,
            client_features=CAP, session_ref=pw.sid(driver), consent=None)
        promo_booking.note_client_features(s, user_id=driver, features=CAP, session_ref=pw.sid(driver))
        s.commit()
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))  # same offer, same price
    assert pw.terms(booking.id)[0]["passenger_bonus_minor"] == P_LOT


def test_q126_another_live_login_or_a_downgrade_invalidates_but_a_refresh_rotation_does_not(pw: PW) -> None:
    client, driver, ref = _p_only_offer(pw)
    pw.declare(driver, sid="another-live-login")  # a later declaration from a different session
    with pytest.raises(DomainError) as exc:
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert exc.value.details["reasons"] == ["counterparty_client_outdated"]

    client2, driver2 = pw.ref.client(), pw.bw.w.driver2_id
    pw.lot(client2, PromoInstrument.PASSENGER_BONUS, P_LOT)
    _, ref2 = pw.offer(client2, driver2, dropoff="C")
    pw.end_session(driver2, reason="rotated")  # an ordinary token refresh replaced the session
    pw.declare(driver2, sid="rotated-successor")
    booking = pw.accept(ref2, client2, consent=(P_LOT, FARE - P_LOT))
    assert pw.terms(booking.id)[0]["passenger_bonus_minor"] == P_LOT


def test_q126_a_stale_client_consent_is_renewed_without_changing_the_offer(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    _, ref = pw.offer(client, driver)
    countered = counter(pw.bw, ref, client, unit=FARE)
    pw.consent_on(countered.version_id, client, P_LOT, FARE - P_LOT)
    pw.declare(client, OLD)  # the client's app is later seen without the capability
    with pytest.raises(DomainError) as exc:
        pw.accept(countered, driver)
    assert exc.value.details["reasons"] == ["counterparty_confirmation_stale"]
    assert pw.scalar("SELECT count(*) FROM bookings") == 0
    with pw.db.session() as s:
        from app.modules.marketplace import service as marketplace_service

        thread = marketplace_service.get_thread_by_public_id(s, countered.thread_id)
        promo_booking.confirm_current_version(
            s, thread=thread, actor_user_id=client, proposal_version_id=marketplace_service.current_version(s, thread).id,
            client_features=CAP, session_ref=pw.sid(client), consent=promo_booking.ConsentInput(P_LOT, FARE - P_LOT))
        promo_booking.note_client_features(s, user_id=client, features=CAP, session_ref=pw.sid(client))
        s.commit()
    booking = pw.accept(countered, driver)
    assert pw.terms(booking.id)[0]["cash_due_minor"] == FARE - P_LOT


# --- Q127: reversal and refund are their own operations ------------------------------------------------------------------


def test_q127_a_reversal_shows_spent_value_to_a_person_per_holder_and_moves_nothing(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.combine(p_lot, h_lot)
    trip, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking.id, client)
    with pw.db.session() as s:
        wallet_service.reverse_fee(s, booking_id=booking.id, amount_minor=500_000, actor_user_id=pw.bw.finance_id,
                                   actor_capabilities=FINANCE_CAPS, reason="synthetic refund")
        s.commit()
    reviews = pw.rows("SELECT kind, reason_codes FROM promo_reviews WHERE booking_id = :b ORDER BY id", b=booking.id)
    assert sorted((k, sorted(r)) for k, r in reviews) == [
        ("restoration_uncovered", ["commission_reversed", "holder_client"]),
        ("restoration_uncovered", ["commission_reversed", "holder_driver"])]
    assert (pw.lot_row(p_lot)["consumed_minor"], pw.lot_row(h_lot)["consumed_minor"]) == (P_LOT, H_LOT)
    review_id = pw.scalar("SELECT id FROM promo_reviews WHERE booking_id = :b ORDER BY id LIMIT 1", b=booking.id)
    with pw.db.session() as s:  # an admin records a judgement; nothing is granted or taken by it
        qualification.decide_review(s, review_id=review_id, decision="approve", actor_user_id=pw.ref.promo.admin_id,
                                    actor_capabilities=ADMIN_CAPS, note="synthetic judgement", expected_version=1)
        s.commit()
    assert (pw.lot_row(p_lot)["consumed_minor"], pw.lot_row(p_lot)["amount_minor"]) == (P_LOT, P_LOT)
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE kind IN ('grant', 'reinstate') "
                     "AND lot_id IN (:p, :h)", p=p_lot, h=h_lot) == 2  # only the two original grants
    assert pw.ref.promo.issues() == []


# --- Q128: release, expiry and reinstatement racing ----------------------------------------------------------------------


def test_q128_release_and_expiry_racing_expire_each_amount_once_and_reinstate_once(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    _, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    _expire_now(pw, p_lot)

    def worker(index: int, session) -> str:  # noqa: ANN001
        if index == 0:
            b = session.get(Booking, booking.id)
            bookings_service.cancel_booking(session, booking_public_id_value=bookings_service.booking_public_id(b),
                                            actor_user_id=client, expected_version=b.version, reason_code="client_cancel")
        else:
            promo_service.expire_due_lots(session)
        session.commit()
        return "ok"

    report = run_concurrently(2, worker, engine=pw.db.engine)
    assert [r.error for r in report.results] == [None, None]
    lot = pw.lot_row(p_lot)
    assert (lot["status"], lot["expired_minor"], lot["reserved_minor"]) == ("expired", P_LOT, 0)  # client's own cause
    releases = pw.rows("SELECT id, amount_minor FROM promo_ledger_transactions WHERE lot_id = :l "
                       "AND kind = 'release_granted'", l=p_lot)
    assert sum(r[1] for r in releases) == P_LOT  # released to the budget exactly once

    def reinstate(index: int, session) -> None:  # noqa: ANN001, ARG001
        qualification.reinstate_expired_release(session, release_transaction_id=releases[0][0],
                                                actor_user_id=pw.ref.promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                                reason="synthetic approved reinstatement")
        session.commit()

    run_concurrently(2, reinstate, engine=pw.db.engine)
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'reinstate' AND lot_id = :l",
                     l=p_lot) == 1
    lot = pw.lot_row(p_lot)
    assert (lot["status"], lot["expired_minor"]) == ("available", 0)
    assert pw.ref.promo.issues() == []


# --- Q129: the cause, not the actor; each holder on its own ------------------------------------------------------------------


def _both_instruments(pw: PW, driver: int, dropoff: str = "D") -> tuple[int, int, int, object, int]:
    client = pw.ref.client()
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.combine(p_lot, h_lot)
    trip, ref = pw.offer(client, driver, dropoff=dropoff)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    return client, p_lot, h_lot, trip, booking.id


def test_q129_an_operator_cancel_without_a_decided_cause_keeps_rights_and_opens_a_review_per_holder(pw: PW) -> None:
    driver = pw.bw.w.driver_id
    _, p_lot, h_lot, _, booking_id = _both_instruments(pw, driver)
    _expire_now(pw, p_lot, h_lot)
    _operator_cancel(pw, booking_id, None)
    assert pw.scalar("SELECT fault_side FROM bookings WHERE id = :b", b=booking_id) == "none"  # nothing recorded as decided
    faults = {row[0] for row in pw.rows("SELECT release_fault FROM promo_redemptions WHERE booking_id = :b", b=booking_id)}
    assert faults == {"undetermined"}  # never "platform" just because an operator pressed the button
    for lot_id in (p_lot, h_lot):  # uncertainty takes no right away: both get the grace
        assert pw.lot_row(lot_id)["status"] == "available"
    reviews = pw.rows("SELECT id, reason_codes FROM promo_reviews WHERE kind = 'cancel_fault' AND booking_id = :b "
                      "ORDER BY id", b=booking_id)
    assert sorted(sorted(r[1]) for r in reviews) == [["fault_undetermined", "holder_client"],
                                                    ["fault_undetermined", "holder_driver"]]
    client_review = next(r[0] for r in reviews if "holder_client" in r[1])
    with pw.db.session() as s:  # an admin decides: it was the client's own cause - only the unspent extension goes
        qualification.decide_review(s, review_id=client_review, decision="reject", actor_user_id=pw.ref.promo.admin_id,
                                    actor_capabilities=ADMIN_CAPS, note="synthetic: client cancelled by phone",
                                    expected_version=1)
        s.commit()
    assert (pw.lot_row(p_lot)["status"], pw.lot_row(p_lot)["expired_minor"]) == ("expired", P_LOT)
    assert pw.lot_row(h_lot)["status"] == "available"  # the driver's credit is judged on its own
    assert pw.ref.promo.issues() == []


def test_q129_a_decided_cause_judges_each_holder_separately(pw: PW) -> None:
    driver = pw.bw.w.driver_id
    _, p_lot, h_lot, _, booking_id = _both_instruments(pw, driver)
    _expire_now(pw, p_lot, h_lot)
    _operator_cancel(pw, booking_id, "client")  # decided with the reason: the client's cause
    assert pw.scalar("SELECT fault_side FROM bookings WHERE id = :b", b=booking_id) == "client"
    assert pw.lot_row(p_lot)["status"] == "expired"  # the client's own cause: no extension of its bonus
    assert pw.lot_row(h_lot)["status"] == "available"  # the driver did nothing wrong: its credit gets the grace
    assert pw.scalar("SELECT count(*) FROM promo_reviews WHERE kind = 'cancel_fault'") == 0
    assert pw.hold(booking_id)[1] == "released"  # the real-money outcome is the same release as before


def test_q129_only_a_confirmed_client_no_show_is_the_clients_cause(pw: PW) -> None:
    driver = pw.bw.w.driver_id
    client, p_lot, h_lot, trip, booking_id = _both_instruments(pw, driver)
    bw = pw.bw
    run_trip_action(bw, trip[0], driver, "start_boarding", now=bw.base - timedelta(minutes=30))
    act(bw, booking_id, driver, "arrive_at_pickup", now=bw.base, observed_at=bw.base)
    act(bw, booking_id, driver, "report_no_show", now=bw.base + timedelta(minutes=11),
        contact_attempts=({"at": bw.base.isoformat(), "channel": "chat"},))
    _expire_now(pw, p_lot, h_lot)
    from tests.pg.bookings.conftest import operator

    operator(bw, booking_id, bw.operator_id, "confirm_no_show", now=bw.base + timedelta(minutes=20))
    assert pw.lot_row(p_lot)["status"] == "expired"  # the client's confirmed no-show: its own cause
    assert pw.lot_row(h_lot)["status"] == "available"  # the driver showed up: its credit keeps the grace


def test_q129_the_operator_cause_is_validated(pw: PW) -> None:
    driver = pw.bw.w.driver_id
    _, _, _, _, booking_id = _both_instruments(pw, driver)
    with pw.db.session() as s, pytest.raises(DomainError) as exc:  # a participant cannot name the cause
        b = s.get(Booking, booking_id)
        bookings_service.cancel_booking(s, booking_public_id_value=bookings_service.booking_public_id(b),
                                        actor_user_id=driver, expected_version=b.version, reason_code="x",
                                        fault_side="client")
    assert _code(exc) is ErrorCode.VALIDATION_ERROR
    with pw.db.session() as s, pytest.raises(DomainError) as exc:  # the cause belongs to a cancel only
        b = s.get(Booking, booking_id)
        bookings_service.operator_command(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=pw.bw.super_id,
            command="drop_off", expected_version=b.version, reason="x", cancel_fault_side="client")
    assert _code(exc) is ErrorCode.VALIDATION_ERROR


def test_q129_no_discount_reason_is_a_plain_category(pw: PW) -> None:
    client = pw.ref.client()
    with pw.db.session() as s:
        flags = {"promotions_enabled": True}
        ask = lambda **kw: promo_booking.no_discount_reason(  # noqa: E731
            s, flags=flags, user_id=client, instrument="passenger_bonus", service_type="passenger",
            parcel_payer=None, client_features=CAP, **kw)
        assert ask() == "no_campaign"
        assert promo_booking.no_discount_reason(s, flags={}, user_id=client, instrument="passenger_bonus",
                                                service_type="passenger", parcel_payer=None,
                                                client_features=CAP) == "no_campaign"
        assert promo_booking.no_discount_reason(s, flags=flags, user_id=client, instrument="passenger_bonus",
                                                service_type="passenger", parcel_payer=None,
                                                client_features=OLD) == "client_update_required"
    lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    with pw.db.session() as s:
        assert promo_booking.no_discount_reason(s, flags=flags, user_id=client, instrument="passenger_bonus",
                                                service_type="parcel", parcel_payer="receiver",
                                                client_features=CAP) == "service_not_eligible"
        assert promo_booking.no_discount_reason(s, flags=flags, user_id=client, instrument="passenger_bonus",
                                                service_type="passenger", parcel_payer=None,
                                                client_features=CAP) == "trip_terms"
    _expire_now(pw, lot)
    with pw.db.session() as s:
        assert promo_booking.no_discount_reason(s, flags=flags, user_id=client, instrument="passenger_bonus",
                                                service_type="passenger", parcel_payer=None,
                                                client_features=CAP) == "bonus_expired"
    assert utc_now()  # the reasons carry no rate, limit, formula or risk signal (Q103): they are the fixed list
    assert set(promo_booking.NO_DISCOUNT_REASONS) == {
        "service_not_eligible", "bonus_expired", "bonus_reserved", "bonus_on_hold", "no_campaign",
        "client_update_required", "trip_terms"}


# --- Q123 clarified (24.09.2026): partial H vs pairs that never meet; a confirmed H is never removed silently ---------


def test_q123_clarified_h_takes_only_the_room_left_after_p_partial_not_all_or_nothing(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, 900_000,
                   campaign=_h_campaign(pw, max_discount_per_booking_minor=700_000))
    pw.combine(p_lot, h_lot, "shared")
    _, ref = pw.offer(client, driver)
    with pw.db.session() as s:  # the plan itself names the outcome (internal; never shown to the client)
        from app.modules.marketplace import service as marketplace_service

        thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
        version = marketplace_service.current_version(s, thread)
        plan = promo_booking.prepare_accept(
            s, flags={"promotions_enabled": True}, service_type="passenger", parcel_payer=None, fare_minor=FARE,
            fee_bps=BPS, proposal_version_id=version.id, version_expires_at=version.expires_at, client_user_id=client,
            driver_user_id=driver, actor_side=__import__("app.contracts.enums", fromlist=["x"]).ActorSide.CLIENT,
            actor_features=CAP, consent_input=promo_booking.ConsentInput(P_LOT, FARE - P_LOT),
            actor_session_ref=pw.sid(client))
        s.rollback()
    assert plan.h_outcome.value == "partial"
    [terms] = pw.terms(pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT)).id)
    assert (terms["passenger_bonus_minor"], terms["driver_credit_minor"]) == (P_LOT, 200_000)  # P kept, H = what is left
    assert pw.lot_row(h_lot)["reserved_minor"] == 200_000


def _driver_accept(pw: PW, ref, driver: int, ack: tuple[int, int] | None):  # noqa: ANN001, ANN202
    from tests.pg.bookings.conftest import listing_version

    with pw.db.session() as s:
        booking = bookings_service.accept_proposal(
            s, thread_public_id=ref.thread_id, actor_user_id=driver, proposal_version_public_id=ref.version_id,
            expected_listing_version=listing_version(pw.bw, ref.listing_id), client_features=CAP,
            client_session=pw.sid(driver), promo_driver_ack=None if ack is None else promo_booking.DriverAck(*ack))
        s.commit()
        return booking


def test_q123_clarified_a_credit_the_driver_saw_is_never_removed_behind_its_back(pw: PW) -> None:
    """The driver accepts the client's counter after seeing cash 195 000 / charged 12 000 (H = 3 000). Its credit
    expires meanwhile: the server's result now charges 15 000. The accept is refused with the new numbers - no
    booking, no higher C_net - and goes through only when the driver confirms them."""
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.combine(p_lot, h_lot)
    _, ref = pw.offer(client, driver)
    countered = counter(pw.bw, ref, client, unit=FARE)
    pw.consent_on(countered.version_id, client, P_LOT, FARE - P_LOT)
    seen = (FARE - P_LOT, 2_000_000 - P_LOT - H_LOT)  # what the driver's pre-accept card showed
    with pw.db.engine.begin() as conn:
        conn.execute(text("UPDATE promo_lots SET expires_at = now() - interval '1 minute' WHERE id = :l"), {"l": h_lot})
    with pytest.raises(DomainError) as exc:
        _driver_accept(pw, countered, driver, seen)
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert exc.value.details["reasons"] == ["driver_terms_changed"]
    assert (exc.value.details["commission_charged_minor"], exc.value.details["driver_credit_minor"]) == (
        2_000_000 - P_LOT, 0)
    assert pw.scalar("SELECT count(*) FROM bookings") == 0  # nothing charged at the higher C_net
    booking = _driver_accept(pw, countered, driver, (FARE - P_LOT, 2_000_000 - P_LOT))  # confirmed again
    [terms] = pw.terms(booking.id)
    assert (terms["passenger_bonus_minor"], terms["driver_credit_minor"], terms["net_commission_minor"]) == (
        P_LOT, 0, 2_000_000 - P_LOT)
