"""Default marketplace ports over A2 (``geo.service``) and A3 (``wallet.service``)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.enums import FeatureFlagKey, ServiceType
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.marketplace.ports import FeeQuote, MarketplacePorts, PolicyRef
from app.modules.trips.adapters import GeoServiceAdapter


class FlagServiceAdapter:
    def is_enabled(self, session: Session, key: FeatureFlagKey, *, corridor_id: int) -> bool:
        from app.modules.geo import service as geo_service

        return geo_service.is_flag_enabled(session, key, corridor_id=corridor_id)


class WalletFeeAdapter:
    def quote(
        self, session: Session, *, corridor_id: int, service_type: ServiceType, total_minor: int, at: datetime
    ) -> FeeQuote:
        from app.modules.wallet import service as wallet_service

        quote = wallet_service.quote_fee(
            session, corridor_id=corridor_id, service_type=service_type, total_minor=total_minor, at=at
        )
        return FeeQuote(
            policy_id=quote.policy_id,
            policy_public_id=quote.policy_public_id,
            policy_kind=str(getattr(quote.policy_kind, "value", quote.policy_kind)),
            fee_bps=quote.fee_bps,
        )

    def policy_refs(self, session: Session, policy_ids: Sequence[int]) -> dict[int, PolicyRef]:
        # Read-only lookup of immutable policy identity; wallet.service has no by-id getter yet.
        from app.modules.wallet.models import CommissionPolicy

        rows = session.execute(
            select(CommissionPolicy.id, CommissionPolicy.public_id, CommissionPolicy.kind).where(
                CommissionPolicy.id.in_(sorted(set(policy_ids)))
            )
        )
        return {
            row.id: PolicyRef(format_public_id(PublicIdPrefix.COMMISSION_POLICY, row.public_id), row.kind) for row in rows
        }


def default_marketplace_ports() -> MarketplacePorts:
    return MarketplacePorts(geo=GeoServiceAdapter(), flags=FlagServiceAdapter(), fees=WalletFeeAdapter())
