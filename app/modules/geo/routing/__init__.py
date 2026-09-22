"""Routing adapters: protocol, deterministic fake (dev/test), our own OSRM, one hosted (Geoapify)."""

from app.modules.geo.routing.base import (
    DisabledRoutingProvider,
    RouteLeg,
    RouteResult,
    RoutingProvider,
    RoutingUnavailable,
    assert_outside_transaction,
    route_outside_transaction,
)
from app.modules.geo.routing.fake import FakeRoutingProvider
from app.modules.geo.routing.geoapify import GeoapifyRoutingProvider
from app.modules.geo.routing.osrm import OsrmRoutingProvider

__all__ = [
    "DisabledRoutingProvider",
    "FakeRoutingProvider",
    "GeoapifyRoutingProvider",
    "OsrmRoutingProvider",
    "RouteLeg",
    "RouteResult",
    "RoutingProvider",
    "RoutingUnavailable",
    "assert_outside_transaction",
    "route_outside_transaction",
]
