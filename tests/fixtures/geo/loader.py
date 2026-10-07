"""Loads ``corridor_fixture.json`` (synthetic dev/test geography) through the geo service.

Used by tests/pg/geo and scripts/seed_geo_fixtures.py. Roads are built with the deterministic fake router through the
fixture's town centres and confirmed, following the real transaction pattern: read -> end transaction -> router ->
write -> commit. ADR-0028 / Q160: the town centres are only where the line is drawn through - nothing is stored for
them; a road is its geometry from A to B. Each district gets its town centre as its map centre.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.ids import new_public_uuid
from app.modules.geo import service
from app.modules.geo.models import GeoDistrict, Region
from app.modules.geo.routing import FakeRoutingProvider, RoutingProvider
from app.modules.geo.types import LatLng

FIXTURE_PATH = Path(__file__).with_name("corridor_fixture.json")


@dataclass
class GeoFixture:
    corridor: service.CorridorInfo
    regions: dict[str, service.RegionInfo] = field(default_factory=dict)
    district_api_ids: dict[str, str] = field(default_factory=dict)
    places: dict[str, LatLng] = field(default_factory=dict)
    routes: dict[str, service.RouteVersionInfo] = field(default_factory=dict)

    def point(self, key: str) -> dict:
        """A fixture place as ``PointEndInput`` JSON, in its district."""
        place = self.places[key]
        district = next(item["district"] for item in load_json()["places"] if item["key"] == key)
        return {"lat": place.lat, "lng": place.lng, "district_id": self.district_api_ids[district]}


def load_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_route(
    db: Session,
    provider: RoutingProvider,
    *,
    actor_user_id: int,
    corridor: service.CorridorInfo,
    through: list[LatLng],
    confirm: bool = True,
) -> service.RouteVersionInfo:
    """A confirmed road drawn by ``provider`` through ``through`` (first = A, last = B). Only the geometry is stored."""
    departure = datetime.now(timezone.utc) + timedelta(days=1)
    try:
        plan = service.prepare_road_preview(
            db, provider, corridor_api_id=corridor.api_id, origin=through[0], destination=through[-1], departure_at=departure
        )
        waypoints = tuple(through)
        plan = replace(plan, waypoints=waypoints, request_hash=service.routing_request_hash(provider.name, provider.version, waypoints))
    finally:
        db.rollback()
    result, from_cache = service.fetch_route_outside_transaction(db, provider, plan)
    route = service.store_route_preview(db, plan, result, actor_user_id=actor_user_id, from_cache=from_cache, cache_ttl_s=3600, source="fixture")
    if confirm:
        route = service.confirm_route_version(db, actor_user_id=actor_user_id, route_version_api_id=route.api_id)
    db.commit()
    return route


def load_geo_fixture(db: Session, *, actor_user_id: int, provider: RoutingProvider | None = None, with_routes: bool = True) -> GeoFixture:
    data = load_json()
    router = provider or FakeRoutingProvider()

    regions: dict[str, service.RegionInfo] = {}
    for item in data["regions"]:
        row = db.scalar(select(Region).where(Region.code == item["code"]))
        if row is None:
            row = Region(
                public_id=new_public_uuid(),
                code=item["code"],
                name_uz=item["name_uz"],
                name_ru=item["name_ru"],
                # Wave 10: the direction picker asks for a district everywhere except Tashkent city. The rule
                # travels with the catalogue row, so a fresh database carries it without a data fix-up.
                requires_district=bool(item.get("requires_district", True)),
            )
            db.add(row)
            db.flush()
        regions[item["key"]] = service.RegionInfo(
            row.id, row.public_id, row.code, row.name_uz, row.name_ru, bool(row.requires_district)
        )

    # The fixture uses the *real* catalogue districts wherever the catalogue has them (a duplicate "Qarshi (fixture)"
    # beside the real "Qarshi" confused testers). One row still has to be invented: Tashkent city is itself the
    # direction unit (wave 10), so it has no districts at all; it is never shown - a region with
    # `requires_district = false` sends the client straight to the map.
    centres = {item["district"]: (item["lat"], item["lng"]) for item in data["places"]}
    district_ids: dict[str, str] = {}
    for item in data["districts"]:
        region = regions[item["region"]]
        row = db.scalar(
            select(GeoDistrict).where(
                GeoDistrict.region_id == region.id, func.lower(GeoDistrict.name_uz) == item["name_uz"].lower()
            )
        )
        if row is None:
            row = GeoDistrict(public_id=new_public_uuid(), region_id=region.id, name_uz=item["name_uz"])
            db.add(row)
            db.flush()
        if row.center_lat is None and item["key"] in centres:  # the map opens on the town (advisory, never a match input)
            row.center_lat, row.center_lng = centres[item["key"]]
            db.flush()
        district_ids[item["key"]] = service.district_api_id(row.public_id)

    spec = data["corridor"]
    corridor = service.create_corridor(
        db,
        actor_user_id=actor_user_id,
        name=spec["name"],
        origin_region_api_id=regions[spec["origin"]].api_id,
        destination_region_api_id=regions[spec["destination"]].api_id,
        search_radius_m=spec["search_radius_m"],
        default_max_detour_minutes=spec["default_max_detour_minutes"],
        default_max_detour_m=spec["default_max_detour_m"],
    )
    fixture = GeoFixture(corridor=corridor, regions=regions, district_api_ids=district_ids)
    for item in data["places"]:
        fixture.places[item["key"]] = LatLng(item["lat"], item["lng"])
    fixture.corridor = service.patch_corridor(
        db,
        actor_user_id=actor_user_id,
        corridor_api_id=corridor.api_id,
        expected_version=corridor.version,
        reason="fixture rollout",
        changes={"rollout_state": "internal"},
    )
    db.commit()

    # ADR-0028 (0099): a pilot corridor needs a confirmed road, so the roads are confirmed while it is internal. Without
    # ``with_routes`` the first road alone is built - the one a public corridor cannot be without.
    routes = list(data["routes"].items()) if with_routes else list(data["routes"].items())[:1]
    for name, keys in routes:
        fixture.routes[name] = build_route(
            db, router, actor_user_id=actor_user_id, corridor=fixture.corridor, through=[fixture.places[k] for k in keys]
        )
    if spec["rollout_state"] == "pilot":
        current = service.get_corridor_by_api_id(db, corridor.api_id)
        fixture.corridor = service.patch_corridor(
            db,
            actor_user_id=actor_user_id,
            corridor_api_id=corridor.api_id,
            expected_version=current.version,
            reason="fixture rollout",
            changes={"rollout_state": "pilot"},
        )
        db.commit()
    return fixture


#: The stage-2 services the synthetic corridor runs with in dev and test.
#:
#: Production defaults stay `false` for all of them (`PRODUCTION_FLAG_DEFAULTS`) - that is the safe value and
#: nothing here changes it. What a developer needs is a corridor where the *whole* marketplace is reachable,
#: including `driver_listing_enabled` (kept for the retired driver listing switch, Q138).
DEV_CORRIDOR_SERVICE_FLAGS: tuple[str, ...] = (
    "passenger_enabled",
    "parcel_enabled",
    "driver_listing_enabled",
    "corridor_matching_enabled",
)


def enable_dev_service_flags(
    db: Session, *, corridor_api_id: str, actor_user_id: int, flags: tuple[str, ...] = DEV_CORRIDOR_SERVICE_FLAGS
) -> dict[str, bool]:
    """Switch the stage-2 services on for one corridor - **dev and test only**.

    Written through :func:`app.modules.geo.service.set_flag_value`, not with an INSERT, so every rule that
    protects a real rollout still runs: the capability check, the production locks (Q1/Q5), the Q48 money gate
    (Q56), the Q87 support-phone check for `passenger_enabled`, the version trigger and the audit row. That also
    means this helper *cannot* quietly enable anything in production - the service refuses first, and the caller
    below refuses even earlier.

    Idempotent in the way that matters: a flag already at the wanted value is left completely alone (no new
    version, no history row, no audit entry), so re-seeding does not drift the configuration or fill the audit
    log with no-op changes. A flag that exists with the *other* value is corrected through its current version.

    Returns `{flag_key: changed}` so a caller can report what it actually did.
    """
    from app.contracts.enums import Capability, FeatureFlagKey, FlagScopeType
    from app.modules.platform import service as platform_service

    if platform_service.is_production(db):
        raise RuntimeError("dev service flags must never be seeded in production")

    changed: dict[str, bool] = {}
    for key in flags:
        flag = FeatureFlagKey(key)
        rows = service.list_flag_values(db, flag_key=flag, scope_type=FlagScopeType.CORRIDOR)
        current = next((row for row in rows if row.scope_ref == corridor_api_id), None)
        if current is not None and current.enabled:
            changed[key] = False
            continue
        service.set_flag_value(
            db,
            actor_user_id=actor_user_id,
            actor_capabilities=[Capability.OPS_FEATURE_FLAG_MANAGE],
            actor_is_super_admin=True,
            flag_key=flag,
            scope_type=FlagScopeType.CORRIDOR,
            scope_ref=corridor_api_id,
            enabled=True,
            reason="dev fixture: stage-2 services on for the synthetic corridor",
            expected_version=current.version if current is not None else None,
        )
        changed[key] = True
    db.commit()
    return changed
