"""Outbound ports from ``marketplace`` to geo (A2) and wallet (A3).

INTEGRATION POINTS (not yet published by their owners as ``service.py``):

* geo: stop lookups, corridor rollout state            -> :class:`MarketplaceGeoPort`
* geo: ``is_flag_enabled`` for a corridor (Q5, AC38)    -> :class:`FlagPort`
* wallet: ``quote_fee`` / policy public ids (AC43)       -> :class:`FeePort`

Idempotency and outbox use ``app.modules.platform.service`` directly (A3, ready).
The integrator registers real adapters with :func:`configure_ports`; tests register
narrow fakes. Unconfigured ports raise :class:`MarketplaceIntegrationNotReady` so a
missing wiring can never silently enable a feature or invent a fee.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.contracts.enums import FeatureFlagKey, ServiceType
from app.modules.trips.ports import StopRef

# Corridor rollout states in which listings may be published (draft/closed may not).
OPEN_CORRIDOR_ROLLOUT_STATES: frozenset[str] = frozenset({"internal", "pilot", "active"})

__all__ = [
    "CorridorRef",
    "FeePort",
    "FeeQuote",
    "FlagPort",
    "MarketplaceGeoPort",
    "MarketplaceIntegrationNotReady",
    "MarketplacePorts",
    "OPEN_CORRIDOR_ROLLOUT_STATES",
    "PolicyRef",
    "StopRef",
    "configure_ports",
    "get_ports",
]


class MarketplaceIntegrationNotReady(RuntimeError):
    """A geo/flag/fee adapter is not registered."""


@dataclass(frozen=True, slots=True)
class CorridorRef:
    id: int
    public_id: str  # cor_...
    rollout_state: str

    @property
    def is_open(self) -> bool:
        return self.rollout_state in OPEN_CORRIDOR_ROLLOUT_STATES


@dataclass(frozen=True, slots=True)
class FeeQuote:
    """Resolved commission policy at quote time; the commission itself is computed with
    ``app.contracts.money.commission_minor`` by the caller (single formula)."""

    policy_id: int
    policy_public_id: str  # cmp_...
    policy_kind: str
    fee_bps: int


@dataclass(frozen=True, slots=True)
class PolicyRef:
    public_id: str
    kind: str


class MarketplaceGeoPort(Protocol):
    def stops_by_public_ids(self, session: Session, public_ids: Sequence[str]) -> dict[str, StopRef]: ...

    def stops_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, StopRef]: ...

    def corridors_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, CorridorRef]: ...


class FlagPort(Protocol):
    def is_enabled(self, session: Session, key: FeatureFlagKey, *, corridor_id: int) -> bool: ...


class FeePort(Protocol):
    def quote(
        self, session: Session, *, corridor_id: int, service_type: ServiceType, total_minor: int, at: datetime
    ) -> FeeQuote: ...

    def policy_refs(self, session: Session, policy_ids: Sequence[int]) -> dict[int, PolicyRef]: ...


@dataclass(frozen=True, slots=True)
class MarketplacePorts:
    geo: MarketplaceGeoPort
    flags: FlagPort
    fees: FeePort


_ports: MarketplacePorts | None = None


def configure_ports(ports: MarketplacePorts | None) -> None:
    global _ports
    _ports = ports


def get_ports() -> MarketplacePorts:
    if _ports is None:
        try:
            from app.modules.marketplace.adapters import default_marketplace_ports
        except ImportError as exc:  # pragma: no cover - geo/wallet module absent
            raise MarketplaceIntegrationNotReady("geo/wallet services are not available") from exc
        return default_marketplace_ports()
    return _ports
