"""Shared fixtures for promotions PostgreSQL tests (referral stage 1, ADR-0023).

Every amount is SYNTHETIC. Nothing here is a reward size, a budget or an O/M value that anyone approved.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.contracts.enums import (
    STAFF_ROLE_CAPABILITIES,
    PromoCampaignKind,
    PromoInstrument,
    PromoLedgerKind,
    Role,
    ServiceType,
)
from app.contracts.promo import PromoMarginPolicy
from app.modules.promotions import service
from tests.pg.wallet.booking_factory import BookingFactory, bookings, world  # noqa: F401  (fixtures)
from tests.pg.wallet.conftest import make_user

SUPER_CAPS = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
FINANCE_CAPS = STAFF_ROLE_CAPABILITIES[Role.FINANCE]
ADMIN_CAPS = STAFF_ROLE_CAPABILITIES[Role.ADMIN]
OPERATOR_CAPS = STAFF_ROLE_CAPABILITIES[Role.OPERATOR]

SYNTH_POLICY = PromoMarginPolicy(
    max_discount_share_bps=5_000,
    max_discount_per_booking_minor=1_500_000,
    passenger_bonus_max_per_booking_minor=1_000_000,
    driver_credit_max_per_booking_minor=1_000_000,
    variable_cost_fixed_minor=100_000,
    variable_cost_bps=0,
    min_margin_minor=100_000,
)
REFERRER_REWARD = 300_000  # synthetic: 3 000 so'm
REFEREE_REWARD = 200_000  # synthetic: 2 000 so'm
COMMITMENT = REFERRER_REWARD + REFEREE_REWARD

_keys = itertools.count(1)


def synthetic_terms(**overrides) -> service.VersionTerms:  # noqa: ANN003
    base = dict(
        referrer_reward_minor=REFERRER_REWARD,
        referee_reward_minor=REFEREE_REWARD,
        referrer_instrument=PromoInstrument.PASSENGER_BONUS,
        referee_instrument=PromoInstrument.PASSENGER_BONUS,
        milestone_thresholds=(),
        enrollment_limit=1_000,
        qualification_window=timedelta(days=30),
        reward_validity=timedelta(days=60),
        review_sla=timedelta(hours=72),
        restoration_grace=timedelta(days=7),
        margin_policy=SYNTH_POLICY,
        approval_reference="SYNTHETIC-TEST-ONLY",
    )
    base.update(overrides)
    return service.VersionTerms(**base)


@dataclass
class Promo:
    pg_db: object
    super_id: int
    super2_id: int
    finance_id: int
    finance2_id: int
    admin_id: int
    operator_id: int
    client_ids: list[int]

    def session(self) -> Session:
        return self.pg_db.session()

    def campaign(self, *, allocate_minor: int = COMMITMENT * 10, activate: bool = True,
                 kind: PromoCampaignKind = PromoCampaignKind.REFERRAL_CLIENT_CLIENT,
                 terms: service.VersionTerms | None = None) -> int:
        with self.session() as s:
            campaign = service.create_campaign(s, actor_user_id=self.super_id, actor_capabilities=SUPER_CAPS,
                                               kind=kind, service_type=ServiceType.PASSENGER, name="Synthetic test")
            version = service.add_campaign_version(s, actor_user_id=self.super_id, actor_capabilities=SUPER_CAPS,
                                                   campaign_id=campaign.id, terms=terms or synthetic_terms())
            if allocate_minor:
                service.request_budget_change(s, actor_user_id=self.finance_id, actor_capabilities=FINANCE_CAPS,
                                              campaign_id=campaign.id, kind=PromoLedgerKind.ALLOCATE,
                                              amount_minor=allocate_minor, reason="synthetic allocation")
            if activate:
                service.activate_campaign(s, actor_user_id=self.super_id, actor_capabilities=SUPER_CAPS,
                                          campaign_id=campaign.id, version_id=version.id,
                                          expected_version=campaign.version, reason="synthetic test")
            s.commit()
            return campaign.id

    def specs(self, *, referrer: int | None = None, referee: int | None = None, key: str | None = None,
              referrer_amount: int = REFERRER_REWARD, referee_amount: int = REFEREE_REWARD) -> list[service.RewardSpec]:
        key = key or f"k{next(_keys)}-{uuid.uuid4().hex[:6]}"
        return [
            service.RewardSpec(referrer if referrer is not None else self.client_ids[0], "referrer",
                               PromoInstrument.PASSENGER_BONUS, referrer_amount, f"{key}:referrer"),
            service.RewardSpec(referee if referee is not None else self.client_ids[1], "referee",
                               PromoInstrument.PASSENGER_BONUS, referee_amount, f"{key}:referee"),
        ]

    def promise(self, campaign_id: int, specs: list[service.RewardSpec] | None = None) -> list[int]:
        with self.session() as s:
            rows = service.promise_rewards(s, campaign_id=campaign_id, rewards=specs or self.specs(),
                                           source_type="synthetic_test", source_id=1)
            s.commit()
            return [row.id for row in rows]

    def granted_lot(self, campaign_id: int) -> int:
        """A granted, available referee lot of REFEREE_REWARD."""
        obligation_ids = self.promise(campaign_id)
        with self.session() as s:
            lot = service.grant_obligation(s, obligation_id=obligation_ids[1])
            s.commit()
            return lot.id

    def budget(self, campaign_id: int):  # noqa: ANN201
        with self.session() as s:
            return service.budget_position(s, campaign_id)

    def issues(self, campaign_id: int | None = None) -> list[dict]:
        with self.session() as s:
            return service.reconciliation_issues(s, campaign_id)

    def ledger_count(self, campaign_id: int, kind: str | None = None) -> int:
        with self.pg_db.engine.connect() as conn:
            query = "SELECT count(*) FROM promo_ledger_transactions WHERE campaign_id = :c"
            params = {"c": campaign_id}
            if kind:
                query += " AND kind = :k"
                params["k"] = kind
            return conn.execute(text(query), params).scalar_one()


@pytest.fixture
def promo(pg_db) -> Promo:  # noqa: ANN001
    with pg_db.session() as s:
        ids = {
            "super": make_user(s, "super_admin"),
            "super2": make_user(s, "super_admin"),
            "finance": make_user(s, "finance"),
            "finance2": make_user(s, "finance"),
            "admin": make_user(s, "admin"),
            "operator": make_user(s, "operator"),
        }
        clients = [make_user(s, "client") for _ in range(4)]
        s.commit()
    return Promo(pg_db, ids["super"], ids["super2"], ids["finance"], ids["finance2"], ids["admin"],
                 ids["operator"], clients)
