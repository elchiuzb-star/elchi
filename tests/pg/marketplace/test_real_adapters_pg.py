"""Default (non-fake) ports over A2 geo.service and A3 wallet.service on the seeded world."""

from __future__ import annotations

import pytest

from app.contracts.enums import FeatureFlagKey, ServiceType
from app.contracts.timeutil import utc_now
from app.modules.marketplace.adapters import FlagServiceAdapter, WalletFeeAdapter
from app.modules.trips.adapters import GeoServiceAdapter
from tests.pg.identity.a1_world import World

pytestmark = pytest.mark.pg


def test_geo_adapter_matches_seeded_catalogue(world: World) -> None:
    geo = GeoServiceAdapter()
    with world.db.session() as s:
        stops = geo.stops_by_public_ids(s, [world.stop_public_ids["A"], "stp_bad"])
        assert set(stops) == {world.stop_public_ids["A"]}
        stop = stops[world.stop_public_ids["A"]]
        assert (stop.id, stop.corridor_id, stop.is_active) == (world.stop_ids["A"], world.corridor_id, True)
        assert geo.stops_by_ids(s, [stop.id])[stop.id].public_id == stop.public_id
        corridor = geo.corridors_by_ids(s, [world.corridor_id])[world.corridor_id]
        assert (corridor.rollout_state, corridor.is_open) == ("pilot", True)
        route = geo.route_version_by_public_id(s, world.route_public_id)
        assert route is not None and route.is_confirmed
        assert [(r.seq, r.stop_id) for r in route.stops] == [(i, world.stop_ids[n]) for i, n in enumerate("ABCD")]
        assert geo.route_versions_by_ids(s, [world.route_id])[world.route_id].public_id == world.route_public_id


def test_wallet_quote_and_flag_adapters(world: World) -> None:
    with world.db.session() as s:
        quote = WalletFeeAdapter().quote(
            s, corridor_id=world.corridor_id, service_type=ServiceType.PASSENGER, total_minor=40_000_000, at=utc_now()
        )
        assert (quote.policy_id, quote.fee_bps, quote.policy_kind) == (world.policy_id, 1500, "standard")
        assert WalletFeeAdapter().policy_refs(s, [world.policy_id])[world.policy_id].public_id == quote.policy_public_id
        # No flag rows: production defaults keep new services off (Q5).
        assert FlagServiceAdapter().is_enabled(s, FeatureFlagKey.PASSENGER_ENABLED, corridor_id=world.corridor_id) is False
