"""Helpers for referral stage-2 PostgreSQL tests (ADR-0023). SYNTHETIC people, codes and amounts only."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.contracts.enums import PromoCampaignKind, PromoInstrument, ServiceType
from app.contracts.ids import new_public_uuid
from app.modules.marketplace import service as marketplace_service
from app.modules.promotions import identity as identity_service
from app.modules.promotions import referral
from tests.pg.identity.a1_world import add_user
from tests.pg.promotions.conftest import Promo, synthetic_terms
from tests.pg.wallet.booking_factory import _INSERT_BOOKING, BookingFactory

SYNTH_SECRET = "synthetic-test-secret-" + "x" * 40  # a test-only master secret; never a real key
KEYS = identity_service.keys_from_secret(SYNTH_SECRET)
_phones = itertools.count(1)


def new_phone() -> str:
    return f"+99893{uuid.uuid4().int % 10_000_000:07d}"


def enable_promotions(pg_db) -> None:  # noqa: ANN001
    """Non-production synthetic environment: switch the promotions flag on country-wide (Q101: prod stays off)."""
    with pg_db.session() as s:
        actor = add_user(s, new_phone(), "super_admin")
        s.execute(text(
            "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
            "VALUES (:p, 'promotions_enabled', 'country', 'UZ', true, 'synthetic referral tests', :u)"),
            {"p": new_public_uuid(), "u": actor})
        s.commit()


@dataclass
class Ref:
    promo: Promo

    @property
    def pg_db(self):  # noqa: ANN201
        return self.promo.pg_db

    def client(self, *, hours_ago: float = 1.0, verified: bool = True) -> int:
        with self.pg_db.session() as s:
            user_id = add_user(s, new_phone(), "client")
            s.execute(text("UPDATE users SET created_at = now() - make_interval(secs => :s), is_phone_verified = :v "
                           "WHERE id = :u"), {"s": hours_ago * 3600, "v": verified, "u": user_id})
            s.commit()
            return user_id

    def driver(self, *, approved: bool = True) -> int:
        with self.pg_db.session() as s:
            user_id = add_user(s, new_phone(), "driver", full_name="Synthetic Driver",
                               driver_status="approved" if approved else "pending")
            s.commit()
            return user_id

    def code(self, owner_id: int) -> str:
        with self.pg_db.session() as s:
            code = referral.issue_referral_code(s, owner_user_id=owner_id)
            s.commit()
            return code.code

    def attribute(self, referee_id: int, code: str, *, audience: str = "client", key: str | None = None):  # noqa: ANN201
        with self.pg_db.session() as s:
            row = referral.attribute(s, referee_user_id=referee_id, raw_code=code, audience_role=audience,
                                     idempotency_key=key or uuid.uuid4().hex)
            s.commit()
            return row.id

    def campaign(self, *, kind=PromoCampaignKind.REFERRAL_CLIENT_CLIENT, service_type=ServiceType.PASSENGER,  # noqa: ANN001
                 allocate_minor: int = 5_000_000, **terms) -> int:  # noqa: ANN003
        if kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER:
            terms = {"milestone_thresholds": (5, 10), "min_distinct_clients": 3,
                     "referrer_instrument": PromoInstrument.DRIVER_CREDIT,
                     "referee_instrument": PromoInstrument.DRIVER_CREDIT, **terms}
        elif kind is PromoCampaignKind.REFERRAL_DRIVER_CLIENT:
            terms = {"referrer_instrument": PromoInstrument.DRIVER_CREDIT, **terms}
        campaign_id = self.promo.campaign(kind=kind, allocate_minor=allocate_minor, terms=synthetic_terms(**terms))
        if service_type is not ServiceType.PASSENGER:
            raise NotImplementedError  # the conftest factory creates passenger campaigns; parcel uses parcel_campaign
        return campaign_id

    def parcel_campaign(self, *, allocate_minor: int = 5_000_000) -> int:
        from app.contracts.enums import PromoLedgerKind
        from app.modules.promotions import service
        from tests.pg.promotions.conftest import FINANCE_CAPS, SUPER_CAPS

        with self.pg_db.session() as s:
            campaign = service.create_campaign(s, actor_user_id=self.promo.super_id, actor_capabilities=SUPER_CAPS,
                                               kind=PromoCampaignKind.REFERRAL_CLIENT_CLIENT,
                                               service_type=ServiceType.PARCEL, name="Synthetic parcel")
            version = service.add_campaign_version(s, actor_user_id=self.promo.super_id, actor_capabilities=SUPER_CAPS,
                                                   campaign_id=campaign.id, terms=synthetic_terms())
            service.request_budget_change(s, actor_user_id=self.promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                          campaign_id=campaign.id, kind=PromoLedgerKind.ALLOCATE,
                                          amount_minor=allocate_minor, reason="synthetic")
            service.activate_campaign(s, actor_user_id=self.promo.super_id, actor_capabilities=SUPER_CAPS,
                                      campaign_id=campaign.id, version_id=version.id, expected_version=1, reason="t")
            s.commit()
            return campaign.id

    def offer(self, campaign_id: int) -> referral.EnrollmentOffer:
        with self.pg_db.session() as s:
            return referral.enrollment_offer(s, campaign_id=campaign_id)

    def enroll(self, referee_id: int, attribution_id: int, campaign_id: int, *, key: str | None = None,
               offer: referral.EnrollmentOffer | None = None, keys=KEYS):  # noqa: ANN001, ANN201
        offer = offer or self.offer(campaign_id)
        with self.pg_db.session() as s:
            row = referral.enroll(s, referee_user_id=referee_id, attribution_id=attribution_id, campaign_id=campaign_id,
                                  accepted_campaign_version_id=offer.campaign_version_id,
                                  accepted_terms_fingerprint=offer.terms_fingerprint,
                                  idempotency_key=key or uuid.uuid4().hex, keys=keys)
            s.commit()
            return row.id

    def count(self, table: str, where: str = "true", **params) -> int:  # noqa: ANN003
        with self.pg_db.engine.connect() as conn:
            return conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params).scalar_one()


def open_booking_for(bookings: BookingFactory, session: Session, client_id: int) -> int:
    """Stand-in for the stage-4 accept: inside ``session`` (not committed) give ``client_id`` a real v2 booking.

    Locks the client's ``users`` row first, exactly as ``bookings.accept_proposal`` does (ADR-0017).
    """
    from app.modules.marketplace.schemas import ListingCreate, ProposalCreate

    w = bookings.world
    session.execute(text("SELECT id FROM users WHERE id = :u FOR NO KEY UPDATE"), {"u": client_id})
    trip_public_id = bookings._trip()
    start = w.base_time
    listing = marketplace_service.create_listing(session, owner_user_id=client_id, data=ListingCreate.model_validate({
        "kind": "request", "service_type": "passenger", "origin_stop_id": w.stop_public_ids["A"],
        "destination_stop_id": w.stop_public_ids["D"], "departure_window_start": start.isoformat(),
        "departure_window_end": (start + timedelta(hours=1)).isoformat(), "price_basis": "per_seat",
        "unit_price_minor": 20_000_000,
        "passenger": {"seat_count": 1, "adults": 1, "baggage": {"pieces": 1, "total_weight_g": 10_000, "total_volume_ml": 40_000}},
    }))
    public_id = marketplace_service.listing_public_id(listing)
    marketplace_service.publish_listing(session, listing_public_id=public_id, actor_user_id=client_id,
                                        expected_version=listing.version)
    thread = marketplace_service.submit_proposal(session, listing_public_id=public_id, actor_user_id=w.driver_id,
                                                 data=ProposalCreate.model_validate({
                                                     "trip_id": trip_public_id, "pickup_stop_id": w.stop_public_ids["A"],
                                                     "dropoff_stop_id": w.stop_public_ids["D"],
                                                     "pickup_window_start": start.isoformat(),
                                                     "pickup_window_end": (start + timedelta(minutes=30)).isoformat(),
                                                     "quantity": 1, "price_basis": "per_seat",
                                                     "unit_price_minor": 20_000_000}))
    version = marketplace_service.current_version(session, thread)
    return int(session.execute(_INSERT_BOOKING, {"driver": w.driver_id, "route": w.route_id, "version": version.id}).scalar_one())
