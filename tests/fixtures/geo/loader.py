"""Loads ``corridor_fixture.json`` (synthetic dev/test geography) through the geo service.

Used by tests/pg/geo and scripts/seed_geo_fixtures.py. Route versions are built with
the deterministic fake router and confirmed, following the real transaction pattern:
read -> end transaction -> router -> write -> commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    stops: dict[str, service.StopInfo] = field(default_factory=dict)
    routes: dict[str, service.RouteVersionInfo] = field(default_factory=dict)

    def stop_id(self, key: str) -> int:
        return self.stops[key].id


def load_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_route(
    db: Session, provider: RoutingProvider, *, actor_user_id: int, stop_api_ids: list[str], confirm: bool = True
) -> service.RouteVersionInfo:
    departure = datetime.now(timezone.utc) + timedelta(days=1)
    try:
        plan = service.prepare_route_preview(db, provider, stop_api_ids=stop_api_ids, departure_at=departure)
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

    # The fixture hangs its stops on the *real* catalogue districts wherever the catalogue has them.
    #
    # It used to create its own - "Qarshi (fixture)" beside the real "Qarshi" - and in a development database
    # both showed up in the district picker, so a tester had to know which of two identically-named rows was
    # the one the corridor actually used. The stops keep their "(fixture)" names, which is the honest label for
    # synthetic geography; the districts no longer duplicate anything.
    #
    # One row still has to be invented: Tashkent city is itself the direction unit (wave 10), so it has no
    # districts at all, and a stop cannot exist without one. It is never shown - a region with
    # `requires_district = false` sends the client straight to the map.
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
    for item in data["stops"]:
        fixture.stops[item["key"]] = service.create_stop(
            db,
            actor_user_id=actor_user_id,
            corridor_api_id=corridor.api_id,
            name_uz=item["name_uz"],
            name_ru=None,
            district_api_id=district_ids[item["district"]],
            point=LatLng(item["lat"], item["lng"]),
            meeting_note="Fixture stop - not a verified meeting point",
            sequence_hint=item["sequence_hint"],
            is_active=True,
        )
    fixture.corridor = service.patch_corridor(
        db,
        actor_user_id=actor_user_id,
        corridor_api_id=corridor.api_id,
        expected_version=corridor.version,
        reason="fixture rollout",
        changes={"rollout_state": "internal"},
    )
    if spec["rollout_state"] == "pilot":
        fixture.corridor = service.patch_corridor(
            db,
            actor_user_id=actor_user_id,
            corridor_api_id=corridor.api_id,
            expected_version=fixture.corridor.version,
            reason="fixture rollout",
            changes={"rollout_state": "pilot"},
        )
    db.commit()

    if with_routes:
        for name, keys in data["routes"].items():
            fixture.routes[name] = build_route(db, router, actor_user_id=actor_user_id, stop_api_ids=[fixture.stops[k].api_id for k in keys])
    return fixture


#: The stage-2 services the synthetic corridor runs with in dev and test.
#:
#: Production defaults stay `false` for all of them (`PRODUCTION_FLAG_DEFAULTS`) - that is the safe value and
#: nothing here changes it. What a developer needs is a corridor where the *whole* marketplace is reachable,
#: including `driver_listing_enabled`: without it a driver cannot publish a trip offer at all, so half of the
#: two-sided auction (Q92) is closed and the supply side looks broken for a configuration reason.
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
