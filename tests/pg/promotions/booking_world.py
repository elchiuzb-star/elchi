"""Helpers for referral stage-4 PostgreSQL tests: promo bookings through the real bookings orchestrator (ADR-0023 §18).

Everything goes through the owning services - ``accept_proposal`` (with consent and client features), proofs, cash
receipts, ``finalize_fee`` - so the promo reservation, the C_net hold and the capture are the production code paths.
SYNTHETIC people, amounts and campaign parameters only; none is an approved value.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import text

from app.contracts.enums import PromoCampaignKind, PromoInstrument
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.promotions import booking as promo_booking
from app.modules.promotions import service as promo_service
from tests.pg.bookings.conftest import BW, act, codes_for, listing_version, operator, passenger_request_body, propose, \
    publish_listing, run_trip_action
from tests.pg.promotions.lifecycle import passenger_trip
from tests.pg.promotions.referral_world import Ref

CAP = frozenset({"promo_cash_v1"})  # a client that renders F_cash (Q110) - a rendering capability, not an authority
OLD = frozenset()  # an old client: the header is absent
FARE = 20_000_000  # F = 200 000 so'm (synthetic)
P_LOT = 500_000  # P = 5 000 so'm
H_LOT = 300_000  # H = 3 000 so'm
BPS = 1_000  # C = 10 % of F = 20 000 so'm


def use_policy(bw: BW, bps: int) -> None:
    """A synthetic campaign commission policy for the test corridor; the fee port quotes it from now on."""
    with bw.db.engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO commission_policies (public_id, kind, scope_corridor_id, fee_bps, effective_from, effective_to, "
            "campaign_name, reason, created_by) VALUES (gen_random_uuid(), 'campaign', :c, :b, now(), "
            "now() + interval '30 days', 'synthetic', 'synthetic stage-4 test policy', :a) RETURNING id, public_id"),
            {"c": bw.w.corridor_id, "b": bps, "a": bw.w.admin_id}).one()
    bw.w.fees.policy_id = row.id
    bw.w.fees.policy_public_id = format_public_id(PublicIdPrefix.COMMISSION_POLICY, row.public_id)
    bw.w.fees.policy_kind = "campaign"
    bw.w.fees.fee_bps = bps


@dataclass
class PW:
    bw: BW
    ref: Ref
    _sids: dict[int, str] = field(default_factory=dict)

    @property
    def db(self):  # noqa: ANN201
        return self.bw.db

    def lot(self, owner: int, instrument: PromoInstrument, amount: int, *, campaign: int | None = None) -> int:
        """A granted, available lot of ``amount`` for ``owner`` (passenger service)."""
        if campaign is None:
            kind = (PromoCampaignKind.REFERRAL_DRIVER_CLIENT if instrument is PromoInstrument.DRIVER_CREDIT
                    else PromoCampaignKind.REFERRAL_CLIENT_CLIENT)
            campaign = self.ref.campaign(kind=kind)
        spec = promo_service.RewardSpec(owner, "referee", instrument, amount, f"t4:{uuid.uuid4().hex}")
        obligation = self.ref.promo.promise(campaign, [spec])[0]
        with self.db.session() as s:
            lot = promo_service.grant_obligation(s, obligation_id=obligation)
            s.commit()
            return lot.id

    def sid(self, user_id: int) -> str:
        """A live login session of ``user_id`` (a real ``refresh_sessions`` row) - what ``sid`` names (Q126)."""
        if user_id not in self._sids:
            from app.models import RefreshSession

            with self.db.session() as s:
                jti = uuid.uuid4().hex
                s.add(RefreshSession(user_id=user_id, jti=jti, token_hash="synthetic-" + jti,
                                     expires_at=utc_now() + timedelta(days=30)))
                s.commit()
            self._sids[user_id] = jti
        return self._sids[user_id]

    def end_session(self, user_id: int, reason: str = "logout") -> None:
        with self.db.engine.begin() as conn:
            conn.execute(text("UPDATE refresh_sessions SET is_revoked = true, revoked_at = now(), revoked_reason = :r "
                              "WHERE jti = :j"), {"r": reason, "j": self.sid(user_id)})

    def declare(self, user_id: int, features: frozenset[str] = CAP, *, sid: str | None = None) -> None:
        """The user's app declares on a command (the change detector of Q126), from its session."""
        with self.db.session() as s:
            promo_booking.note_client_features(s, user_id=user_id, features=features,
                                               session_ref=sid or self.sid(user_id))
            s.commit()

    def ready(self, ref, user_id: int, features: frozenset[str] = CAP) -> None:  # noqa: ANN001
        """What the HTTP offer/counter records for its author: readiness for *this* version, then the declaration."""
        from app.modules.marketplace import service as marketplace_service

        with self.db.session() as s:
            thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
            promo_booking.note_version_readiness(s, thread=thread, actor_user_id=user_id, features=features,
                                                 session_ref=self.sid(user_id))
            promo_booking.note_client_features(s, user_id=user_id, features=features, session_ref=self.sid(user_id))
            s.commit()

    def combine(self, lot_a: int, lot_b: int, basis: str = "shared") -> None:
        """Q123: approve the two lots' campaigns to meet on one booking (super_admin, synthetic reason)."""
        from tests.pg.promotions.conftest import SUPER_CAPS

        a, b = (self.scalar("SELECT campaign_id FROM promo_lots WHERE id = :l", l=lot) for lot in (lot_a, lot_b))
        with self.db.session() as s:
            promo_service.approve_combination(s, actor_user_id=self.ref.promo.super_id, actor_capabilities=SUPER_CAPS,
                                              campaign_a=a, campaign_b=b, cost_basis=basis, reason="synthetic pairing")
            s.commit()

    def consent_on(self, version_public_id: str, client_id: int, p: int, cash: int) -> None:
        """The client's consent as recorded by an HTTP counter: bound to its session, then its declaration."""
        from app.modules.marketplace import service as marketplace_service

        with self.db.session() as s:
            version = marketplace_service.get_version_by_public_id(s, version_public_id)
            promo_booking.record_consent(
                s, client_user_id=client_id, proposal_version_id=version.id, service_type="passenger",
                parcel_payer=None, fare_minor=version.total_minor, fee_bps=version.fee_bps,
                expires_at=version.expires_at, client_features=CAP, consent=promo_booking.ConsentInput(p, cash),
                flags={"promotions_enabled": True}, session_ref=self.sid(client_id))
            promo_booking.note_client_features(s, user_id=client_id, features=CAP, session_ref=self.sid(client_id))
            s.commit()

    def offer(self, client_id: int, driver_id: int, *, unit: int = FARE, dropoff: str = "D",  # noqa: ANN201
              driver_features: frozenset[str] | None = CAP):
        """(trip, ThreadRef): a driver's offer on the client's request, sent from a capable app (its readiness for
        this version is recorded, Q126) unless ``driver_features`` says otherwise. A second request of the same
        client needs another ``dropoff`` (the marketplace refuses a near-duplicate listing, spec §5.4)."""
        trip = passenger_trip(self.bw, driver_id)
        listing = publish_listing(self.bw, client_id, passenger_request_body(self.bw, seats=1, unit=unit, destination=dropoff))
        ref = propose(self.bw, listing, driver_id, trip_public_id=trip[1], quantity=1, unit=unit, dropoff=dropoff)
        if driver_features is not None:
            self.ready(ref, driver_id, driver_features)
        return trip, ref

    def accept(self, ref, actor_id: int, *, features: frozenset[str] | None = CAP,  # noqa: ANN001
               consent: tuple[int, int] | None = None, session=None) -> Booking:  # noqa: ANN001
        own = session is None
        s = session or self.db.session()
        try:
            booking = bookings_service.accept_proposal(
                s, thread_public_id=ref.thread_id, actor_user_id=actor_id, proposal_version_public_id=ref.version_id,
                expected_listing_version=listing_version(self.bw, ref.listing_id), client_features=features,
                promo_consent=None if consent is None else promo_booking.ConsentInput(*consent),
                client_session=None if features is None else self.sid(actor_id),
            )
            s.commit()
            return booking
        except BaseException:
            s.rollback()
            raise
        finally:
            if own:
                s.close()

    def hold(self, booking_id: int) -> tuple[int, str, int]:
        row = self.rows("SELECT amount_minor, status, captured_minor FROM wallet_holds WHERE booking_id = :b", b=booking_id)
        return tuple(row[0]) if row else None  # type: ignore[return-value]

    def wallet(self, driver_id: int) -> tuple[int, int]:
        row = self.rows("SELECT posted_balance_minor, held_minor FROM wallet_accounts WHERE driver_user_id = :d", d=driver_id)
        return tuple(row[0])  # type: ignore[return-value]

    def lot_row(self, lot_id: int) -> dict:
        return dict(self.rows("SELECT * FROM promo_lots WHERE id = :l", l=lot_id, mapping=True)[0])

    def redemptions(self, booking_id: int) -> list[tuple[int, int, str, int]]:
        return [tuple(r) for r in self.rows(
            "SELECT lot_id, amount_minor, status, terms_seq FROM promo_redemptions WHERE booking_id = :b ORDER BY id",
            b=booking_id)]

    def terms(self, booking_id: int) -> list[dict]:
        return [dict(r) for r in self.rows("SELECT * FROM promo_booking_terms WHERE booking_id = :b ORDER BY seq",
                                           b=booking_id, mapping=True)]

    def wait_until_expired(self, *lot_ids: int, deadline_s: float = 30.0) -> None:
        """Returns once the database clock has passed every lot's ``expires_at`` - a condition, not a guessed delay
        (``clock_timestamp()``: ``now()`` is frozen for a whole transaction)."""
        import time

        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            if self.scalar("SELECT bool_and(expires_at <= clock_timestamp()) FROM promo_lots WHERE id = ANY(:ids)",
                           ids=list(lot_ids)):
                return
            time.sleep(0.05)
        raise AssertionError(f"lots {lot_ids} did not reach their end")

    def scalar(self, sql: str, **params):  # noqa: ANN003, ANN201
        with self.db.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def rows(self, sql: str, *, mapping: bool = False, **params) -> list:  # noqa: ANN003
        with self.db.engine.connect() as conn:
            result = conn.execute(text(sql), params)
            return list(result.mappings() if mapping else result)

    # --- service -------------------------------------------------------------------------------------------------

    def board_and_depart(self, trip_id: int, driver_id: int, bookings: list[tuple[int, int]]) -> None:
        bw = self.bw
        run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
        for booking_id, client_id in bookings:
            act(bw, booking_id, driver_id, "board", code=codes_for(bw, booking_id, client_id)["boarding_code"],
                now=bw.base + timedelta(minutes=5))
        run_trip_action(bw, trip_id, driver_id, "depart", now=bw.base + timedelta(minutes=12))

    def report_cash(self, booking_id: int, driver_id: int, amount: int, *, note: str | None = None,
                    features: frozenset[str] | None = CAP):  # noqa: ANN201 - receipt public id
        with self.db.session() as s:
            booking = s.get(Booking, booking_id)
            _, receipt = bookings_service.report_cash_receipt(
                s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=driver_id,
                expected_version=booking.version, amount_minor=amount, reported_at=self.bw.base + timedelta(hours=3),
                note=note, now=self.bw.base + timedelta(hours=3), client_features=features,
                client_session=self.sid(driver_id))
            s.commit()
            return format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id), receipt.version

    def acknowledge_cash(self, booking_id: int, client_id: int, receipt: tuple[str, int], *,
                         features: frozenset[str] | None = CAP) -> None:
        with self.db.session() as s:
            booking = s.get(Booking, booking_id)
            bookings_service.acknowledge_cash_receipt(
                s, booking_public_id_value=bookings_service.booking_public_id(booking), receipt_public_id=receipt[0],
                actor_user_id=client_id, expected_version=receipt[1], now=self.bw.base + timedelta(hours=3, minutes=1),
                client_features=features, client_session=self.sid(client_id))
            s.commit()

    def finish(self, trip_id: int, driver_id: int, booking_id: int, client_id: int, *, capture: bool = True) -> None:
        """Drop off, complete (commission stays held: no dispute probe -> Q74 finance review), finance capture."""
        bw = self.bw
        act(bw, booking_id, driver_id, "drop_off", now=bw.base + timedelta(hours=3))
        act(bw, booking_id, client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
        if capture:
            self.finalize(booking_id, "capture")
        run_trip_action(bw, trip_id, driver_id, "complete", now=bw.base + timedelta(hours=4))

    def finalize(self, booking_id: int, mode: str, *, actor: int | None = None) -> None:
        operator(self.bw, booking_id, actor or self.bw.finance_id, "finalize_fee", fee_mode=mode,
                 reason="synthetic finance decision")
