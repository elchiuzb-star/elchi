"""Promotions inside the real booking flow on PostgreSQL (referral stage 4, ADR-0023 §18; Q104, Q110, Q116, Q120-Q122).

Every flow goes through ``bookings.service`` - accept (consent, lot reservation, C_net hold, immutable terms),
cash receipts (F_cash), ``finalize_fee`` (capture of the held C_net + consume), cancel (release), amendments
(reservation swap) - and the database's deferred ``promo_booking_terms_verify`` check. SYNTHETIC amounts only.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import STAFF_ROLE_CAPABILITIES, PromoInstrument, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.promotions import booking as promo_booking
from app.modules.promotions import qualification, referral
from app.modules.promotions import service as promo_service
from app.modules.wallet import service as wallet_service
from tests.pg.bookings.conftest import BW, bw, counter, domain_error, listing_version, view  # noqa: F401
from tests.pg.harness import run_concurrently
from tests.pg.promotions.booking_world import BPS, CAP, FARE, H_LOT, OLD, P_LOT, PW, use_policy
from tests.pg.promotions.referral_world import Ref, enable_promotions

pytestmark = pytest.mark.pg

FINANCE_CAPS = STAFF_ROLE_CAPABILITIES[Role.FINANCE]
ADMIN_CAPS = STAFF_ROLE_CAPABILITIES[Role.ADMIN]
SUPER_CAPS = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]


@pytest.fixture
def pw(bw: BW, promo) -> PW:  # noqa: ANN001, F811
    enable_promotions(promo.pg_db)
    use_policy(bw, BPS)
    return PW(bw, Ref(promo))


def _code(exc: pytest.ExceptionInfo) -> ErrorCode:
    return exc.value.code


def _promo_deal(pw: PW, *, client: int | None = None, driver: int | None = None, p: int = P_LOT, h: int = H_LOT):
    """Client with a P lot, driver with an H lot and a capable app, a driver offer for F. The two lots come from two
    campaigns approved to meet on one booking with a shared cost basis (Q123)."""
    client = client or pw.ref.client()
    driver = driver or pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, p) if p else None
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, h) if h else None
    if p_lot and h_lot:
        pw.combine(p_lot, h_lot)
    trip, ref = pw.offer(client, driver)
    return client, driver, p_lot, h_lot, trip, ref


# --- the synthetic example end to end (task stage 4) ----------------------------------------------------------------


def test_synthetic_example_runs_through_the_real_flow(pw: PW) -> None:
    """F = 200 000, C = 20 000, P = 5 000, H = 3 000 -> client pays 195 000 cash, driver charged 12 000, keeps 183 000."""
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    posted_before, held_before = pw.wallet(driver)
    booking = pw.accept(ref, client, consent=(500_000, 19_500_000))

    [terms] = pw.terms(booking.id)
    assert (terms["fare_minor"], terms["base_commission_minor"], terms["passenger_bonus_minor"],
            terms["driver_credit_minor"], terms["cash_due_minor"], terms["net_commission_minor"]) == (
        20_000_000, 2_000_000, 500_000, 300_000, 19_500_000, 1_200_000)
    assert pw.hold(booking.id)[:2] == (1_200_000, "active")  # only C_net is held - never C and a fake refund
    assert pw.wallet(driver) == (posted_before, held_before + 1_200_000)
    assert sorted(pw.redemptions(booking.id)) == sorted([(p_lot, 500_000, "reserved", 1), (h_lot, 300_000, "reserved", 1)])
    assert pw.scalar("SELECT terms_snapshot->'promo'->>'applied' FROM bookings WHERE id = :b", b=booking.id) == "true"
    assert pw.scalar("SELECT status FROM promo_consents WHERE booking_id = :b", b=booking.id) == "used"

    client_dto = view(pw.bw, booking.id, "client")
    assert client_dto["promo"] == {"view": "client", "fare_minor": 20_000_000, "passenger_discount_minor": 500_000,
                                   "cash_due_minor": 19_500_000, "currency": "UZS"}
    assert "commission" not in str(client_dto) and "driver_credit" not in str(client_dto)  # Q16/Q103
    driver_dto = view(pw.bw, booking.id, "driver")
    assert driver_dto["promo"] == {
        "view": "driver", "fare_minor": 20_000_000, "passenger_discount_minor": 500_000, "cash_to_collect_minor": 19_500_000,
        "base_commission_minor": 2_000_000, "passenger_discount_covered_minor": 500_000, "driver_credit_minor": 300_000,
        "commission_charged_minor": 1_200_000, "driver_keeps_minor": 18_300_000, "currency": "UZS"}
    assert driver_dto["fee"]["net_minor"] == 18_300_000

    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    with pytest.raises(DomainError) as exc:  # the receipt is checked against F_cash, not F
        pw.report_cash(booking.id, driver, 20_000_000)
    assert _code(exc) is ErrorCode.VALIDATION_ERROR
    receipt = pw.report_cash(booking.id, driver, 19_500_000)
    pw.acknowledge_cash(booking.id, client, receipt)
    pw.finish(trip[0], driver, booking.id, client)

    assert pw.hold(booking.id) == (1_200_000, "captured", 1_200_000)
    assert pw.wallet(driver) == (posted_before - 1_200_000, held_before)  # 12 000 so'm charged from the real balance
    assert sorted(pw.redemptions(booking.id)) == sorted([(p_lot, 500_000, "consumed", 1), (h_lot, 300_000, "consumed", 1)])
    assert pw.scalar("SELECT sum(amount_minor) FROM promo_ledger_transactions WHERE kind = 'consume' AND lot_id IN (:p, :h)",
                     p=p_lot, h=h_lot) == 800_000
    report = pw.rows("SELECT * FROM promo_booking_finance WHERE booking_id = :b", b=booking.id, mapping=True)[0]
    assert (report["fare_minor"], report["base_commission_minor"], report["passenger_bonus_minor"],
            report["driver_credit_minor"], report["cash_due_minor"], report["net_commission_minor"],
            report["captured_minor"], report["consumed_passenger_bonus_minor"], report["consumed_driver_credit_minor"]) == (
        20_000_000, 2_000_000, 500_000, 300_000, 19_500_000, 1_200_000, 1_200_000, 500_000, 300_000)
    # C = C_net + P + H: the discount is taken out of the platform's commission exactly once
    assert report["base_commission_minor"] == report["captured_minor"] + report["consumed_passenger_bonus_minor"] \
        + report["consumed_driver_credit_minor"]

    # a repeated finalize_fee charges nothing more (the capture is not recomputed from any newer rate)
    pw.bw.w.fees.fee_bps = 2_000  # a newer rate at the quote port changes nothing already held
    with pytest.raises(DomainError) as exc:
        pw.finalize(booking.id, "capture")
    assert _code(exc) is ErrorCode.INVALID_STATE_TRANSITION
    assert pw.scalar("SELECT count(*) FROM ledger_transactions WHERE booking_id = :b AND reference_kind = 'commission_capture'",
                     b=booking.id) == 1
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'consume' AND lot_id IN (:p, :h)",
                     p=p_lot, h=h_lot) == 2


# --- plain and 0 % bookings (QA #12, #23) -----------------------------------------------------------------------------


def test_plain_booking_is_unchanged_and_marked_plain(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    trip, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client)
    assert pw.terms(booking.id) == [] and pw.redemptions(booking.id) == []
    assert pw.hold(booking.id)[:2] == (2_000_000, "active")  # C
    assert pw.scalar("SELECT terms_snapshot->'promo'->>'applied' FROM bookings WHERE id = :b", b=booking.id) == "false"
    assert view(pw.bw, booking.id, "client")["promo"] is None
    assert view(pw.bw, booking.id, "driver")["fee"]["net_minor"] == FARE - 2_000_000


def test_zero_percent_booking_takes_no_discount_and_a_consent_on_it_is_stale(pw: PW) -> None:
    pw.bw.w.fees.fee_bps = 0  # an approved 0 % campaign (synthetic): C = 0, nothing to fund a discount from
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.declare(driver)
    trip, ref = pw.offer(client, driver)
    with pytest.raises(DomainError) as exc:  # consented P cannot apply: refused, never a higher cash amount
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert exc.value.details["scope"] == "accept_attempt"
    booking = pw.accept(ref, client)  # without consent: an ordinary exempt booking, the bonus stays with its owner
    assert booking.commission_status == "exempt" and pw.hold(booking.id) is None
    assert pw.terms(booking.id) == [] and pw.redemptions(booking.id) == []
    assert pw.lot_row(p_lot)["reserved_minor"] == 0


def test_legacy_booking_reads_as_plain_but_a_broken_marker_is_an_error(pw: PW) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    trip, ref = pw.offer(client, driver)
    booking_id = pw.accept(ref, client).id
    with pw.db.session() as s:
        booking = s.get(Booking, booking_id)
        legacy = dict(booking.terms_snapshot)
        legacy.pop("promo")
        booking.terms_snapshot = legacy  # in-memory only: how a booking accepted before stage 4 reads
        quote = promo_booking.terms_for_booking(s, booking)
        assert (quote.passenger_bonus_minor, quote.driver_credit_minor, quote.net_commission_minor) == (0, 0, 2_000_000)
        booking.terms_snapshot = {**legacy, "promo": {"applied": "yes"}}  # malformed new marker: never "no promo"
        with pytest.raises(DomainError) as exc:
            promo_booking.terms_for_booking(s, booking)
        assert _code(exc) is ErrorCode.INTEGRITY_CONFLICT
        booking.terms_snapshot = {**legacy, "promo": {"contract_version": 1, "applied": True}}  # applied, no terms row
        with pytest.raises(DomainError) as exc:
            promo_booking.terms_for_booking(s, booking)
        assert _code(exc) is ErrorCode.INTEGRITY_CONFLICT
        s.rollback()


def test_database_refuses_money_that_disagrees_with_the_terms(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    for statements, rule in (
        # the bonus quietly handed back while the booking still holds only C_net (lot buckets kept consistent)
        (["UPDATE promo_redemptions SET status = 'released', settled_at = now(), release_fault = 'client' "
          "WHERE booking_id = :b AND lot_id = :p",
          "UPDATE promo_lots SET reserved_minor = reserved_minor - 500000 WHERE id = :p"], "promo_booking_terms_mismatch"),
        (["UPDATE promo_booking_terms SET passenger_bonus_minor = 0 WHERE booking_id = :b"], "append_only_violation"),
    ):
        with pytest.raises(DBAPIError) as exc, pw.db.engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql), {"b": booking.id, "p": p_lot})
        assert exc.value.orig.diag.constraint_name == rule
    plain_client = pw.ref.client()
    trip2, ref2 = pw.offer(plain_client, pw.bw.w.driver2_id)
    plain = pw.accept(ref2, plain_client)
    with pytest.raises(DBAPIError) as exc, pw.db.engine.begin() as conn:  # a plain booking cannot carry promo terms
        conn.execute(text(
            "INSERT INTO promo_booking_terms (booking_id, seq, contract_version, fare_minor, fee_bps, base_commission_minor, "
            "passenger_bonus_minor, driver_credit_minor, cash_due_minor, net_commission_minor, variable_cost_minor, "
            "min_margin_minor, quote_fingerprint, driver_campaign_id) VALUES (:b, 1, 1, 20000000, 1000, 2000000, 0, "
            "300000, 20000000, 1700000, 100000, 100000, repeat('0', 64), "
            "(SELECT campaign_id FROM promo_lots WHERE id = :h))"), {"b": plain.id, "h": h_lot})
    assert exc.value.orig.diag.constraint_name == "promo_booking_terms_mismatch"
    with pytest.raises(DBAPIError) as exc, pw.db.engine.begin() as conn:  # Q123: a credit must name its one campaign
        conn.execute(text(
            "INSERT INTO promo_booking_terms (booking_id, seq, contract_version, fare_minor, fee_bps, base_commission_minor, "
            "passenger_bonus_minor, driver_credit_minor, cash_due_minor, net_commission_minor, variable_cost_minor, "
            "min_margin_minor, quote_fingerprint) VALUES (:b, 1, 1, 20000000, 1000, 2000000, 0, 300000, 20000000, "
            "1700000, 100000, 100000, repeat('0', 64))"), {"b": plain.id})
    assert exc.value.orig.diag.constraint_name == "ck_promo_booking_terms_campaigns"


# --- consent, capability, staleness (Q104, Q110, Q119) -----------------------------------------------------------------


def test_consent_needs_a_capable_client_and_its_exact_numbers(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    with pytest.raises(DomainError) as exc:  # old client app: it would show F, not F_cash
        pw.accept(ref, client, features=OLD, consent=(P_LOT, FARE - P_LOT))
    assert _code(exc) is ErrorCode.CLIENT_UPGRADE_REQUIRED
    with pytest.raises(DomainError) as exc:  # numbers the server did not show: never used as amounts
        pw.accept(ref, client, consent=(P_LOT + 1, FARE - P_LOT - 1))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert pw.lot_row(p_lot)["reserved_minor"] == 0 and pw.scalar("SELECT count(*) FROM bookings") == 0
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert pw.terms(booking.id)[0]["passenger_bonus_minor"] == P_LOT


def test_counterparty_with_an_old_app_makes_a_consented_discount_stale(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    pw.declare(driver, OLD)  # the driver's app would show "collect F"
    with pytest.raises(DomainError) as exc:
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert exc.value.details["reasons"] == ["counterparty_client_outdated"]
    booking = pw.accept(ref, client)  # no consent: plain for the client; the old driver app gets no credit either
    assert pw.terms(booking.id) == [] and pw.hold(booking.id)[0] == 2_000_000


def test_driver_credit_alone_never_changes_what_the_client_pays(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw, p=0)
    booking = pw.accept(ref, client, features=OLD)  # an old client app is fine: F_cash = F
    [terms] = pw.terms(booking.id)
    assert (terms["passenger_bonus_minor"], terms["driver_credit_minor"], terms["cash_due_minor"],
            terms["net_commission_minor"]) == (0, H_LOT, FARE, 2_000_000 - H_LOT)


def test_driver_accept_applies_exactly_the_recorded_consent_or_refuses(pw: PW) -> None:
    """Q104: the client consented when countering; the driver accepts without the client present."""
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    countered = counter(pw.bw, ref, client, unit=FARE)
    pw.consent_on(countered.version_id, client, P_LOT, FARE - P_LOT)
    # the bonus is spent elsewhere meanwhile (another booking of the same client)
    other_trip, other = pw.offer(client, pw.bw.w.driver2_id, dropoff="C")
    pw.declare(pw.bw.w.driver2_id)
    pw.accept(other, client, consent=(P_LOT, FARE - P_LOT))
    with pytest.raises(DomainError) as exc:  # never "just drop the promo" and collect the full fare
        pw.accept(countered, driver)
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE and exc.value.details["action"] == "requote"
    assert pw.scalar("SELECT count(*) FROM bookings WHERE proposal_thread_id = (SELECT id FROM proposal_threads "
                     "WHERE listing_id = (SELECT id FROM listings WHERE public_id::text = split_part(:l, '_', 2)))",
                     l=countered.listing_id) in (0, None)


def test_driver_accept_with_consent_in_place(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    countered = counter(pw.bw, ref, client, unit=FARE)
    pw.consent_on(countered.version_id, client, P_LOT, FARE - P_LOT)
    booking = pw.accept(countered, driver)
    [terms] = pw.terms(booking.id)
    assert (terms["passenger_bonus_minor"], terms["cash_due_minor"], terms["net_commission_minor"]) == (
        P_LOT, FARE - P_LOT, 2_000_000 - P_LOT - H_LOT)


def test_promotions_switched_off_makes_a_consent_stale(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    with pw.db.engine.begin() as conn:
        from tests.pg.bookings.conftest import _mark_flag_change_source

        _mark_flag_change_source(conn)
        conn.execute(text("UPDATE feature_flag_values SET enabled = false, version = version + 1 "
                          "WHERE flag_key = 'promotions_enabled'"))
    with pytest.raises(DomainError) as exc:
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert exc.value.details["reasons"] == ["promotions_disabled"]
    booking = pw.accept(ref, client)
    assert pw.terms(booking.id) == []  # flag off: exactly today's booking flow (QA #23)


# --- concurrency ----------------------------------------------------------------------------------------------------


def test_two_parallel_accepts_cannot_spend_one_bonus(pw: PW) -> None:
    client = pw.ref.client()
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    drivers = [pw.bw.w.driver_id, pw.bw.w.driver2_id]
    refs = []
    for driver, dropoff in zip(drivers, ("D", "C")):
        pw.declare(driver)
        refs.append(pw.offer(client, driver, dropoff=dropoff)[1])

    report = run_concurrently(2, lambda i, s: pw.accept(refs[i], client, consent=(P_LOT, FARE - P_LOT), session=s).id,
                              engine=pw.db.engine)
    ok = [r for r in report.results if r.error is None]
    failed = [r for r in report.results if r.error is not None]
    assert len(ok) == 1 and len(failed) == 1
    assert isinstance(failed[0].error, DomainError) and failed[0].error.code is ErrorCode.PROMO_QUOTE_STALE
    lot = pw.lot_row(p_lot)
    assert (lot["reserved_minor"], lot["consumed_minor"]) == (P_LOT, 0)
    assert pw.scalar("SELECT count(*) FROM promo_redemptions WHERE lot_id = :l", l=p_lot) == 1
    assert pw.ref.promo.issues() == []


def test_bonus_enough_but_driver_real_balance_short_rolls_back_everything(pw: PW) -> None:
    from tests.pg.identity.a1_world import add_user

    with pw.db.session() as s:
        poor = add_user(s, f"+99891{uuid.uuid4().int % 10_000_000:07d}", "driver", full_name="Synthetic Poor",
                        driver_status="approved")
        s.commit()
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw, driver=poor)
    with pytest.raises(DomainError) as exc:
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert _code(exc) is ErrorCode.INSUFFICIENT_COMMISSION_BALANCE
    assert pw.scalar("SELECT count(*) FROM bookings") == 0
    assert pw.scalar("SELECT count(*) FROM promo_redemptions") == 0
    assert pw.lot_row(p_lot)["reserved_minor"] == 0 and pw.lot_row(h_lot)["reserved_minor"] == 0
    assert pw.scalar("SELECT count(*) FROM promo_consents") == 0  # the consent of the refused attempt is gone too


def test_repeated_accept_and_cancel_create_one_booking_and_one_money_result(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    with pytest.raises(DomainError):
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert pw.scalar("SELECT count(*) FROM bookings") == 1
    assert pw.scalar("SELECT count(*) FROM wallet_holds") == 1 and len(pw.terms(booking.id)) == 1

    def cancel() -> None:
        with pw.db.session() as s:
            b = s.get(Booking, booking.id)
            bookings_service.cancel_booking(s, booking_public_id_value=bookings_service.booking_public_id(b),
                                            actor_user_id=driver, expected_version=b.version, reason_code="driver_sick")
            s.commit()

    cancel()
    with pytest.raises(DomainError):
        cancel()
    assert pw.hold(booking.id)[1] == "released" and pw.wallet(driver)[1] == 0
    assert sorted(r[2] for r in pw.redemptions(booking.id)) == ["released", "released"]
    assert pw.lot_row(p_lot)["reserved_minor"] == 0 and pw.lot_row(h_lot)["reserved_minor"] == 0
    assert pw.ref.promo.issues() == []


def test_release_versus_capture_race_settles_the_money_once(pw: PW) -> None:
    """Two finance decisions race on a completed promo booking still held (Q74): exactly one wins, and the promo
    reservations follow it (all consumed with the capture, or all back with the release)."""
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking.id, client, capture=False)
    modes = ["capture", "release"]

    def decide(index: int, session) -> str:  # noqa: ANN001
        b = session.get(Booking, booking.id)
        bookings_service.operator_command(
            session, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=pw.bw.finance_id,
            command="finalize_fee", expected_version=b.version, reason="synthetic race", fee_mode=modes[index])
        session.commit()
        return modes[index]

    report = run_concurrently(2, decide, engine=pw.db.engine)
    winners = [r.value for r in report.results if r.error is None]
    assert len(winners) == 1
    statuses = sorted(r[2] for r in pw.redemptions(booking.id))
    if winners == ["capture"]:
        assert pw.hold(booking.id)[1:] == ("captured", 1_200_000) and statuses == ["consumed", "consumed"]
    else:
        assert pw.hold(booking.id)[1] == "released" and statuses == ["released", "released"]
    assert pw.ref.promo.issues() == []


def test_accept_racing_lot_expiry(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    with pw.db.engine.begin() as conn:  # the bonus reaches its end right now
        conn.execute(text("UPDATE promo_lots SET expires_at = now() + interval '2 seconds' WHERE id = :l"), {"l": p_lot})
    pw.wait_until_expired(p_lot)
    with pw.db.session() as s:
        promo_service.expire_due_lots(s)
        s.commit()
    with pytest.raises(DomainError) as exc:  # expired first: only this attempt is refused
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE

    # reserved first, expires while reserved: the reservation stays with its booking and is consumed normally
    client2, _, p2, _, trip2, ref2 = _promo_deal(pw, driver=pw.bw.w.driver2_id, h=0)
    booking = pw.accept(ref2, client2, consent=(P_LOT, FARE - P_LOT))
    with pw.db.engine.begin() as conn:
        conn.execute(text("UPDATE promo_lots SET expires_at = now() + interval '1 second' WHERE id = :l"), {"l": p2})
    pw.wait_until_expired(p2)
    with pw.db.session() as s:
        promo_service.expire_due_lots(s)
        s.commit()
    assert pw.lot_row(p2)["reserved_minor"] == P_LOT
    pw.board_and_depart(trip2[0], pw.bw.w.driver2_id, [(booking.id, client2)])
    pw.acknowledge_cash(booking.id, client2, pw.report_cash(booking.id, pw.bw.w.driver2_id, FARE - P_LOT))
    pw.finish(trip2[0], pw.bw.w.driver2_id, booking.id, client2)
    assert pw.lot_row(p2)["consumed_minor"] == P_LOT
    assert pw.ref.promo.issues() == []


def test_post_grant_review_stops_new_spending_but_keeps_confirmed_discounts(pw: PW) -> None:
    """Q122: a lot under review cannot be reserved; a reservation made before it settles with its booking."""
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw, h=0)
    booking = pw.accept(ref, client, consent=(200_000, FARE - 200_000))  # part of the lot, confirmed
    with pw.db.session() as s:
        promo_service.flag_lot_for_review(s, lot_id=p_lot, reason="post_grant_recheck")
        s.commit()
    trip2, ref2 = pw.offer(client, pw.bw.w.driver2_id, dropoff="C")
    pw.declare(pw.bw.w.driver2_id)
    with pytest.raises(DomainError) as exc:  # the unreserved rest is suspended
        pw.accept(ref2, client, consent=(300_000, FARE - 300_000))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert pw.terms(booking.id)[0]["passenger_bonus_minor"] == 200_000  # the confirmed discount is untouched
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - 200_000))
    pw.finish(trip[0], driver, booking.id, client)
    lot = pw.lot_row(p_lot)
    assert (lot["status"], lot["consumed_minor"], lot["reserved_minor"]) == ("pending_review", 200_000, 0)


# --- amendments (Q116) ---------------------------------------------------------------------------------------------


def _amend(pw: PW, booking_id: int, actor: int, unit: int, *, consent=None, ack=None):  # noqa: ANN001, ANN202
    with pw.db.session() as s:
        b = s.get(Booking, booking_id)
        amendment = bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=actor,
            expected_version=b.version, changes={"unit_price_minor": unit}, reason="synthetic change",
            client_features=CAP, promo_consent=None if consent is None else promo_booking.ConsentInput(*consent),
            promo_driver_ack=None if ack is None else promo_booking.DriverAck(*ack), client_session=pw.sid(actor))
        s.commit()
        return format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id), amendment.version


def _accept_amendment(pw: PW, amendment: tuple[str, int], actor: int, *, consent=None, ack=None) -> None:  # noqa: ANN001
    with pw.db.session() as s:
        bookings_service.accept_amendment(
            s, amendment_public_id=amendment[0], actor_user_id=actor, expected_version=amendment[1],
            client_features=CAP, promo_consent=None if consent is None else promo_booking.ConsentInput(*consent),
            promo_driver_ack=None if ack is None else promo_booking.DriverAck(*ack), client_session=pw.sid(actor))
        s.commit()


def test_amendment_recomputes_terms_needs_the_clients_confirmation_and_keeps_the_old_agreement_on_failure(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    with pytest.raises(DomainError) as exc:  # Q125: the driver's cash and commission change - it confirms them first
        _amend(pw, booking.id, driver, 8_000_000)
    assert _code(exc) is ErrorCode.PROMO_CONSENT_REQUIRED
    assert exc.value.details == {"cash_to_collect_minor": 7_600_000, "commission_charged_minor": 400_000,
                                 "driver_credit_minor": 0, "fare_minor": 8_000_000, "party": "driver"}
    amendment = _amend(pw, booking.id, driver, 8_000_000, ack=(7_600_000, 400_000))  # F 200 000 -> 80 000
    before = (pw.terms(booking.id), pw.redemptions(booking.id), pw.hold(booking.id), pw.wallet(driver))

    with pytest.raises(DomainError) as exc:  # F, P and F_cash change: the client must confirm the new cash
        _accept_amendment(pw, amendment, client)
    assert _code(exc) is ErrorCode.PROMO_CONSENT_REQUIRED
    assert exc.value.details == {"passenger_discount_minor": 400_000, "cash_due_minor": 7_600_000,
                                 "fare_minor": 8_000_000}
    with pytest.raises(DomainError) as exc:  # the old P "assumed" by the client is not what applies
        _accept_amendment(pw, amendment, client, consent=(P_LOT, 8_000_000 - P_LOT))
    assert _code(exc) is ErrorCode.PROMO_QUOTE_STALE
    assert (pw.terms(booking.id), pw.redemptions(booking.id), pw.hold(booking.id), pw.wallet(driver)) == before

    _accept_amendment(pw, amendment, client, consent=(400_000, 7_600_000))
    terms = pw.terms(booking.id)
    assert [t["seq"] for t in terms] == [1, 2]
    new = terms[1]
    # F down -> P down (cap) -> F_cash = 76 000 is MORE than F - old P (75 000): that is why the client confirms
    assert (new["fare_minor"], new["passenger_bonus_minor"], new["driver_credit_minor"], new["cash_due_minor"],
            new["net_commission_minor"]) == (8_000_000, 400_000, 0, 7_600_000, 400_000)
    assert pw.hold(booking.id)[:2] == (400_000, "active")
    live = [r for r in pw.redemptions(booking.id) if r[2] == "reserved"]
    assert live == [(p_lot, 400_000, "reserved", 2)]
    assert pw.lot_row(p_lot)["reserved_minor"] == 400_000 and pw.lot_row(h_lot)["reserved_minor"] == 0
    assert terms[0]["passenger_bonus_minor"] == P_LOT  # history is never rewritten
    assert pw.ref.promo.issues() == []


def test_client_authored_amendment_carries_its_consent_to_the_drivers_accept(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    with pytest.raises(DomainError) as exc:
        _amend(pw, booking.id, client, 8_000_000)
    assert _code(exc) is ErrorCode.PROMO_CONSENT_REQUIRED
    amendment = _amend(pw, booking.id, client, 8_000_000, consent=(400_000, 7_600_000))
    with pytest.raises(DomainError) as exc:  # Q125: the driver accepts only numbers it has seen
        _accept_amendment(pw, amendment, driver)
    assert _code(exc) is ErrorCode.PROMO_CONSENT_REQUIRED and exc.value.details["party"] == "driver"
    _accept_amendment(pw, amendment, driver, ack=(7_600_000, 400_000))
    assert pw.terms(booking.id)[1]["cash_due_minor"] == 7_600_000
    assert pw.scalar("SELECT status FROM promo_consents WHERE amendment_id IS NOT NULL") == "used"


def test_old_client_cannot_run_cash_commands_on_a_promo_booking_and_the_discount_stays(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    with pytest.raises(DomainError) as exc:
        pw.report_cash(booking.id, driver, FARE, features=OLD)
    assert _code(exc) is ErrorCode.CLIENT_UPGRADE_REQUIRED
    receipt = pw.report_cash(booking.id, driver, FARE - P_LOT)
    with pytest.raises(DomainError) as exc:
        pw.acknowledge_cash(booking.id, client, receipt, features=OLD)
    assert _code(exc) is ErrorCode.CLIENT_UPGRADE_REQUIRED
    assert pw.terms(booking.id)[0]["cash_due_minor"] == FARE - P_LOT  # never zeroed to suit the old app


# --- refunds are separate events (ADR-0023 §7) ----------------------------------------------------------------------


def test_partial_and_repeated_commission_reversal_never_touches_the_bonus_or_creates_debt(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking.id, client)
    posted = pw.wallet(driver)[0]

    def reverse(amount: int) -> None:
        with pw.db.session() as s:
            wallet_service.reverse_fee(s, booking_id=booking.id, amount_minor=amount, actor_user_id=pw.bw.finance_id,
                                       actor_capabilities=FINANCE_CAPS, reason="synthetic refund")
            s.commit()

    reverse(500_000)
    reverse(700_000)  # cumulative = C_net: the most that was ever really charged
    with pytest.raises(DomainError) as exc:
        reverse(1)
    assert _code(exc) is ErrorCode.REVERSAL_EXCEEDS_CAPTURED
    assert pw.wallet(driver)[0] == posted + 1_200_000  # never more than C_net back, never a debt
    assert sorted(r[2] for r in pw.redemptions(booking.id)) == ["consumed", "consumed"]  # no automatic bonus return
    assert pw.lot_row(p_lot)["consumed_minor"] == P_LOT
    assert view(pw.bw, booking.id, "client")["promo"]["cash_due_minor"] == FARE - P_LOT  # no "refund to client"


# --- qualification with the real flow (Q120) ----------------------------------------------------------------------


def _enrolled_client(pw: PW) -> tuple[int, int, int]:
    campaign = pw.ref.campaign()
    referee = pw.ref.client()
    attribution = pw.ref.attribute(referee, pw.ref.code(pw.ref.client()))
    return referee, pw.ref.enroll(referee, attribution, campaign), campaign


def _lots_of(pw: PW, enrollment: int) -> list[dict]:
    return pw.rows("SELECT l.* FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id "
                   "WHERE o.enrollment_id = :e ORDER BY l.id", e=enrollment, mapping=True)


def test_late_capture_after_an_in_time_service_waits_and_grants_once_captured(pw: PW) -> None:
    referee, enrollment, campaign = _enrolled_client(pw)
    driver = pw.bw.w.driver_id
    trip, ref = pw.offer(referee, driver)
    booking = pw.accept(ref, referee)
    pw.board_and_depart(trip[0], driver, [(booking.id, referee)])
    pw.acknowledge_cash(booking.id, referee, pw.report_cash(booking.id, driver, FARE))
    pw.finish(trip[0], driver, booking.id, referee, capture=False)  # served and paid in time; finance review holds C
    assert pw.scalar("SELECT count(*) FROM promo_qualification_events WHERE booking_id = :b", b=booking.id) >= 2

    deadline = pw.scalar("SELECT qualification_deadline FROM promo_enrollments WHERE id = :e", e=enrollment)
    after_deadline = deadline + timedelta(days=5)
    with pw.db.session() as s:
        assert qualification.process_enrollment(s, enrollment_id=enrollment, now=after_deadline) == "waiting"
        s.commit()
    with pw.db.session() as s:  # the deadline job must not take the reserve away while only the platform is late
        qualification.expire_enrollments(s, now=after_deadline)
        s.commit()
    assert pw.scalar("SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment) == "promised"
    assert _lots_of(pw, enrollment) == []  # no grant without a real positive C_net capture

    pw.finalize(booking.id, "capture")  # the platform captures late
    with pw.db.session() as s:
        evidence = qualification.read_evidence(s, booking.id)
    ready = max(evidence.completed_at, evidence.cash_confirmed_at, evidence.captured_at) + timedelta(hours=48)
    with pw.db.session() as s:
        assert qualification.process_enrollment(s, enrollment_id=enrollment, now=max(ready, after_deadline)) == "granted"
        s.commit()
    assert len(_lots_of(pw, enrollment)) == 2


def test_event_and_sweep_together_grant_once(pw: PW) -> None:
    referee, enrollment, campaign = _enrolled_client(pw)
    driver = pw.bw.w.driver_id
    trip, ref = pw.offer(referee, driver)
    booking = pw.accept(ref, referee)
    pw.board_and_depart(trip[0], driver, [(booking.id, referee)])
    pw.acknowledge_cash(booking.id, referee, pw.report_cash(booking.id, driver, FARE))
    pw.finish(trip[0], driver, booking.id, referee)
    kinds = {r[0] for r in pw.rows("SELECT kind FROM promo_qualification_events WHERE booking_id = :b", b=booking.id)}
    assert {"booking_completed", "cash_acknowledged", "commission_captured"} <= kinds  # written by the booking flow
    with pw.db.session() as s:
        evidence = qualification.read_evidence(s, booking.id)
    ready = evidence.conditions_met_at + timedelta(hours=48)

    def worker(index: int, session) -> None:  # noqa: ANN001
        if index == 0:
            qualification.process_qualification_events(session, now=ready)
        else:
            qualification.process_enrollment(session, enrollment_id=enrollment, now=ready)
        session.commit()

    run_concurrently(2, worker, engine=pw.db.engine)
    for _ in range(2):
        with pw.db.session() as s:
            qualification.process_qualification_events(s, now=ready)
            s.commit()
    assert len(_lots_of(pw, enrollment)) == 2
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'grant' AND campaign_id = :c",
                     c=campaign) == 2


def _await_lock_waiter(pw: PW, *, deadline_s: float = 30.0) -> None:
    """Returns once another backend is *waiting* on a lock - a condition, not a delay. The short poll interval only
    paces the check; the order of the two transactions never depends on it."""
    end = time.monotonic() + deadline_s
    with pw.db.engine.connect() as conn:
        while time.monotonic() < end:
            if conn.execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted")).scalar():
                return
            time.sleep(0.01)
    raise AssertionError("the second transaction never waited on the first one's lock: they did not serialise")


def test_attribution_races_the_real_first_accept(pw: PW) -> None:
    """A4.12: attribution and the referee's first real accept serialise on the users row; one consistent outcome.

    Deterministic: the first transaction does its work and keeps its locks; the second starts only then, and the
    first commits only after the database shows the second *waiting* on it. No sleep decides the order."""
    for attribute_first in (True, False):
        referee = pw.ref.client()
        code = pw.ref.code(pw.ref.client())
        driver = pw.bw.w.driver_id if attribute_first else pw.bw.w.driver2_id
        trip, ref = pw.offer(referee, driver)
        pw.sid(referee)  # the login session exists before the race (its insert is not part of it)
        first_holds_locks = threading.Event()

        def worker(index: int, session, first=attribute_first, referee=referee, code=code, ref=ref,  # noqa: ANN001, ANN202
                   gate=first_holds_locks):
            is_first = (index == 0) == first  # worker 0 attributes, worker 1 accepts
            if not is_first:
                assert gate.wait(timeout=30), "the first transaction never reached its locked point"
            if index == 0:
                result = referral.attribute(session, referee_user_id=referee, raw_code=code, audience_role="client",
                                            idempotency_key=uuid.uuid4().hex).id
            else:
                result = bookings_service.accept_proposal(
                    session, thread_public_id=ref.thread_id, actor_user_id=referee,
                    proposal_version_public_id=ref.version_id, expected_listing_version=listing_version(pw.bw, ref.listing_id),
                    client_features=CAP, promo_consent=None, client_session=pw.sid(referee)).id
            if is_first:
                gate.set()
                _await_lock_waiter(pw)  # the other transaction is now blocked on our users row
            session.commit()
            return result

        report = run_concurrently(2, worker, engine=pw.db.engine)
        attribution, booking = report.results
        assert booking.error is None, booking.error
        if attribute_first:
            assert attribution.error is None
        else:
            assert isinstance(attribution.error, DomainError)
            assert attribution.error.code is ErrorCode.REFERRAL_WINDOW_CLOSED
        assert pw.ref.count("referral_attributions", "referee_user_id = :u", u=referee) == (1 if attribute_first else 0)


def test_a_retried_accept_after_a_real_serialization_failure_keeps_one_reservation_and_one_hold(
        pw: PW, monkeypatch: pytest.MonkeyPatch) -> None:
    """The promo accept runs inside ``run_with_db_retry`` (the HTTP command runner's retry). The first attempt fails
    with a genuine PostgreSQL 40001 *after* the promo reservation was written and before the hold: the whole
    transaction rolls back, the retry does it again - exactly one booking, one reservation per lot, one C_net hold."""
    from app.modules.platform.service import run_with_db_retry

    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    real_hold, attempts = wallet_service.hold_fee, []

    def failing_once(session, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        attempts.append(1)
        if len(attempts) == 1:  # a real server-side serialization failure, raised inside this transaction
            session.execute(text("DO $$ BEGIN RAISE EXCEPTION 'synthetic serialization failure' "
                                 "USING ERRCODE = '40001'; END $$"))
        return real_hold(session, *args, **kwargs)

    monkeypatch.setattr(wallet_service, "hold_fee", failing_once)
    with pw.db.session() as s:
        booking_id = run_with_db_retry(s, lambda: pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT), session=s).id)
    assert len(attempts) == 2  # failed once, retried once
    assert pw.scalar("SELECT count(*) FROM bookings WHERE id >= :b", b=booking_id) == 1
    assert sorted((r[0], r[1], r[2]) for r in pw.redemptions(booking_id)) == sorted(
        [(p_lot, P_LOT, "reserved"), (h_lot, H_LOT, "reserved")])
    assert (pw.lot_row(p_lot)["reserved_minor"], pw.lot_row(h_lot)["reserved_minor"]) == (P_LOT, H_LOT)
    assert pw.scalar("SELECT count(*) FROM wallet_holds WHERE booking_id = :b", b=booking_id) == 1
    assert pw.hold(booking_id)[:2] == (2_000_000 - P_LOT - H_LOT, "active")
    assert pw.scalar("SELECT count(*) FROM promo_booking_terms WHERE booking_id = :b", b=booking_id) == 1
    assert pw.ref.promo.issues() == []


def test_a_client_who_becomes_a_driver_keeps_an_open_driver_window(pw: PW) -> None:
    from app.models import DriverProfile

    person = pw.ref.client()
    trip, ref = pw.offer(person, pw.bw.w.driver_id)
    pw.accept(ref, person)  # a real accepted client booking: closes the *client* attribution window only
    with pw.db.session() as s:
        s.execute(text("INSERT INTO user_roles (user_id, role, status) VALUES (:u, 'driver', 'active')"), {"u": person})
        s.add(DriverProfile(user_id=person, verification_status="approved"))
        s.commit()
    with pytest.raises(DomainError) as exc:
        pw.ref.attribute(person, pw.ref.code(pw.ref.client()))
    assert _code(exc) is ErrorCode.REFERRAL_WINDOW_CLOSED
    assert pw.ref.attribute(person, pw.ref.code(pw.ref.driver()), audience="driver")


# --- T3 / Q122: autonomous review, reinstate, suspension ---------------------------------------------------------------


def test_autonomous_review_neither_commits_nor_waits_for_the_callers_work(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw, h=0)
    campaign = pw.scalar("SELECT campaign_id FROM promo_lots WHERE id = :l", l=p_lot)
    with pw.db.session() as caller:
        # the caller holds the promo locks (FOR NO KEY UPDATE) and has uncommitted work on the lot
        promo_service._lock_campaign(caller, campaign)
        promo_service.flag_lot_for_review(caller, lot_id=p_lot, reason="uncommitted caller work")
        started = time.perf_counter()
        review_id = qualification.open_review_autonomously(
            caller, kind="qualification_risk", dedup_key=f"t3:{uuid.uuid4().hex}", reasons=["synthetic"],
            evidence=[{"table": "promo_lots", "id": p_lot}], now=utc_now(), campaign_id=campaign)
        assert time.perf_counter() - started < 5  # FK checks take KEY SHARE: no wait on the caller's locks
        caller.rollback()
    assert pw.scalar("SELECT count(*) FROM promo_reviews WHERE id = :r", r=review_id) == 1  # survived the rollback
    assert pw.lot_row(p_lot)["status"] == "available"  # ... and did not commit the caller's work
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))  # nothing left locked or half-done
    assert pw.terms(booking.id)[0]["passenger_bonus_minor"] == P_LOT


def test_reinstate_is_never_partial_and_an_unfulfilled_one_stays_escalated(pw: PW) -> None:
    client = pw.ref.client()
    campaign = pw.ref.campaign(allocate_minor=P_LOT)
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT, campaign=campaign)
    with pw.db.engine.begin() as conn:
        conn.execute(text("UPDATE promo_lots SET expires_at = now() + interval '1 second' WHERE id = :l"), {"l": p_lot})
    pw.wait_until_expired(p_lot)
    with pw.db.session() as s:
        promo_service.expire_due_lots(s)
        s.commit()
    release = pw.scalar("SELECT id FROM promo_ledger_transactions WHERE lot_id = :l AND kind = 'release_granted'", l=p_lot)
    pw.lot(pw.ref.client(), PromoInstrument.PASSENGER_BONUS, P_LOT, campaign=campaign)  # the freed budget is used again
    with pw.db.session() as s, pytest.raises(DomainError) as exc:
        qualification.reinstate_expired_release(s, release_transaction_id=release, actor_user_id=pw.ref.promo.admin_id,
                                                actor_capabilities=ADMIN_CAPS, reason="synthetic approved reinstatement")
    assert _code(exc) is ErrorCode.PROMO_BUDGET_EXHAUSTED
    assert pw.lot_row(p_lot)["expired_minor"] == P_LOT  # nothing partial
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'reinstate'") == 0
    review = pw.rows("SELECT kind, status, due_at FROM promo_reviews WHERE dedup_key = :k",
                     k=f"reinstate_unfulfilled:{release}", mapping=True)
    assert review and review[0]["kind"] == "reinstate_unfulfilled" and review[0]["status"] == "open"
    with pw.db.session() as s:
        assert qualification.escalate_overdue_reviews(s, now=utc_now() + timedelta(seconds=5)) >= 1
        s.commit()


def test_processing_suspension_changes_no_booking_price_and_charges_once(pw: PW) -> None:
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw, h=0)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    campaign = pw.scalar("SELECT campaign_id FROM promo_lots WHERE id = :l", l=p_lot)
    with pw.db.session() as s:
        qualification.suspend_processing(s, campaign_id=campaign, actor_user_id=pw.ref.promo.super_id,
                                         actor_capabilities=SUPER_CAPS, reason="synthetic operational stop")
        s.commit()
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking.id, client)
    assert pw.terms(booking.id)[0]["cash_due_minor"] == FARE - P_LOT
    assert pw.hold(booking.id) == (2_000_000 - P_LOT, "captured", 2_000_000 - P_LOT)
    assert pw.scalar("SELECT count(*) FROM ledger_transactions WHERE booking_id = :b AND reference_kind = 'commission_capture'",
                     b=booking.id) == 1


# --- preview before agreeing (task stage 4: the driver sees F_cash, C_net and H first) -----------------------------


def test_both_sides_see_the_money_terms_before_agreeing(pw: PW) -> None:
    from app.modules.marketplace import service as marketplace_service
    from app.modules.marketplace.views import thread_dto

    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    with pw.db.session() as s:  # the client, looking at the driver's offer: what its bonus gives on this fare
        client_view = thread_dto(s, marketplace_service.get_thread_by_public_id(s, ref.thread_id),
                                 viewer_user_id=client).current_version.promo_quote
    assert (client_view.fare_minor, client_view.passenger_discount_minor, client_view.cash_due_minor) == (
        FARE, P_LOT, FARE - P_LOT)
    # the client's object has no commission, credit or keeps key at all - not even as null (Q16, Q103)
    assert set(client_view.model_dump()) == {"view", "fare_minor", "passenger_discount_minor", "cash_due_minor", "currency"}

    countered = counter(pw.bw, ref, client, unit=FARE)
    pw.consent_on(countered.version_id, client, P_LOT, FARE - P_LOT)
    with pw.db.session() as s:  # the driver, before accepting: cash to collect, credit used, commission charged
        driver_view = thread_dto(s, marketplace_service.get_thread_by_public_id(s, countered.thread_id),
                                 viewer_user_id=driver).current_version.promo_quote
    assert (driver_view.cash_to_collect_minor, driver_view.driver_credit_minor, driver_view.commission_charged_minor,
            driver_view.driver_keeps_minor) == (19_500_000, 300_000, 1_200_000, 18_300_000)
    assert pw.scalar("SELECT count(*) FROM promo_redemptions") == 0  # a preview reserves nothing


# --- gaps closed during the stage-4 reconciliation (A4.4, A4.7, A4.10) ----------------------------------------------


def _cancel(pw: PW, booking_id: int, actor: int, reason: str) -> None:
    with pw.db.session() as s:
        b = s.get(Booking, booking_id)
        bookings_service.cancel_booking(s, booking_public_id_value=bookings_service.booking_public_id(b),
                                        actor_user_id=actor, expected_version=b.version, reason_code=reason)
        s.commit()


def test_cancel_after_expiry_restores_by_fault_in_the_real_flow(pw: PW) -> None:
    """A4.4 / ADR-0023 §7: a driver-fault cancel gives an expired bonus the campaign's grace; a client-fault cancel
    lets the returned value expire (back to the budget, reinstatable later)."""
    results = {}
    for side in ("driver", "client"):
        driver = pw.bw.w.driver_id if side == "driver" else pw.bw.w.driver2_id
        client, _, p_lot, _, trip, ref = _promo_deal(pw, driver=driver, h=0)
        booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
        with pw.db.engine.begin() as conn:  # the bonus reaches its end while reserved for this booking
            conn.execute(text("UPDATE promo_lots SET expires_at = now() + interval '1 second' WHERE id = :l"), {"l": p_lot})
        pw.wait_until_expired(p_lot)
        _cancel(pw, booking.id, driver if side == "driver" else client, f"{side}_cancel")
        results[side] = pw.lot_row(p_lot)
        assert pw.redemptions(booking.id)[0][2] == "released" and pw.hold(booking.id)[1] == "released"
    restored, expired = results["driver"], results["client"]
    assert restored["status"] == "available" and restored["expired_minor"] == 0
    assert restored["expires_at"] > utc_now() + timedelta(days=6)  # synthetic grace (7 days) from the release
    assert expired["status"] == "expired" and expired["expired_minor"] == P_LOT
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE lot_id = :l AND reference_key LIKE "
                     "'release_granted:expiry-redemption:%'", l=expired["id"]) == 1
    assert pw.ref.promo.issues() == []


def test_a_cash_amount_other_than_f_cash_needs_a_note_and_goes_to_the_contested_path(pw: PW) -> None:
    """A4.7: F_cash is the expected amount; another amount is accepted only with a note and can be contested."""
    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    receipt = pw.report_cash(booking.id, driver, FARE, note="client paid the full fare in cash")
    with pw.db.session() as s:
        b = s.get(Booking, booking.id)
        _, row = bookings_service.contest_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(b), receipt_public_id=receipt[0],
            actor_user_id=client, expected_version=receipt[1], comment="I paid 195 000 as agreed",
            client_features=CAP)
        s.commit()
        assert row.status == "contested"
    assert pw.scalar("SELECT cash_status FROM bookings WHERE id = :b", b=booking.id) == "contested"
    assert pw.terms(booking.id)[0]["cash_due_minor"] == FARE - P_LOT  # the agreed F_cash is not rewritten


def test_client_copies_of_booking_events_carry_no_commission_or_credit(pw: PW) -> None:
    """A4.10 / Q16 / Q103: every outbox event of a promo booking, filtered for the client audience."""
    from app.contracts.enums import EventType
    from app.contracts.events import EventAudience, payload_for_audience

    client, driver, p_lot, h_lot, trip, ref = _promo_deal(pw)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking.id, client)
    with pw.db.session() as s:
        public = bookings_service.booking_public_id(s.get(Booking, booking.id))
    events = pw.rows("SELECT event_type, payload FROM outbox_events WHERE aggregate_public_id = :p "
                     "OR payload->>'booking_id' = :p", p=public)
    assert events, "the booking flow wrote no events"
    forbidden = ("commission", "fee", "credit", "net_", "variable_cost", "margin", "bps")
    seen = 0
    for event_type, payload in events:
        try:
            kind = EventType(event_type)
        except ValueError:
            continue
        copy = payload_for_audience(kind, payload, EventAudience.CLIENT)
        if copy is None:
            continue
        seen += 1
        assert not [key for key in copy if any(word in key for word in forbidden)], (event_type, copy)
    assert seen >= 1
