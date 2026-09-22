"""Open the country for local testing: a few synthetic corridors along the real national axes.

Why this exists
---------------
Two things stop a developer from testing an order between, say, Kasbi and Namangan:

1. The stage-2 services are per-corridor flags (Q5) and default to off, so before a corridor is
   resolved the client reads the *country* scope, finds `parcel_enabled` false, and says "Pochta
   xizmati bu hududda hali ochilmagan" - which is the honest answer to a closed configuration.
2. Even with the flags on, two marked places must project onto a **confirmed route** of an open
   corridor (Q88), and the dev database ships exactly one corridor: Toshkent - Qashqadaryo.

This script fixes both **as data**: nothing in the product is taught to pretend a service exists.

Why several corridors and not one
---------------------------------
The first version seeded a single line through all 14 region centres. It resolved everything, and it
gave visibly wrong numbers: Toshkent -> Kasbi came back as 1 008 km, because the only path between
them ran down through Surxondaryo. A leg is measured **along the line it is projected onto**, so the
line has to resemble the road or the distance shown above a price field is nonsense. These corridors
follow the axes that actually exist, and the resolver picks whichever one both places sit closest to.

What it is not
--------------
A **test fixture, not geography**. The routes are straight hops between region centres drawn by the
deterministic fake router, the stops are region centres rather than verified meeting points, and
places away from an axis only resolve because of a development-only radius override. So:

* it refuses to run against a production marker, twice (here, and again inside the flag helper);
* every corridor and stop is named "dev sinov" wherever a person can see it;
* `ELCHI_GEO_ROUTING_PROVIDER` must be `fake` - the real router is off in production (Q24/Q46).

Idempotent: a corridor that already exists is left alone, and a flag already on is not touched (no
version bump, no audit row). `--drop` retires them by closing them - see `drop` for why deleting a
confirmed route is neither possible nor right.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from app.contracts.enums import Capability, FeatureFlagKey, FlagScopeType  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.modules.geo import service as geo_service  # noqa: E402
from app.modules.geo.config import build_routing_provider, get_geo_settings  # noqa: E402
from app.modules.geo.flags import COUNTRY_SCOPE_REF  # noqa: E402
from app.modules.geo.models import GeoDistrict, Region, ServiceCorridor  # noqa: E402
from app.modules.geo.types import LatLng  # noqa: E402
from app.modules.platform import service as platform_service  # noqa: E402

CORRIDOR_PREFIX = "Dev sinov:"

#: The country as the axes that actually carry traffic, each with stops at the region centres it
#: passes, in travel order. A confirmed route is built in both directions, so every ordered pair along
#: an axis has a route that runs the right way.
CORRIDORS: list[tuple[str, list[str]]] = [
    (
        "M39 janub",
        [
            "Toshkent shahri",
            "Toshkent viloyati",
            "Sirdaryo viloyati",
            "Jizzax viloyati",
            "Samarqand viloyati",
            "Qashqadaryo viloyati",
            "Surxondaryo viloyati",
        ],
    ),
    (
        "M37 g'arb",
        [
            "Toshkent shahri",
            "Toshkent viloyati",
            "Sirdaryo viloyati",
            "Jizzax viloyati",
            "Samarqand viloyati",
            "Navoiy viloyati",
            "Buxoro viloyati",
            "Xorazm viloyati",
            "Qoraqalpog'iston Respublikasi",
        ],
    ),
    (
        "Farg'ona vodiysi",
        [
            "Toshkent shahri",
            "Toshkent viloyati",
            "Namangan viloyati",
            "Andijon viloyati",
            "Farg'ona viloyati",
        ],
    ),
    # Qarshi - Buxoro is a road in its own right; without it a south-west pair detours via Samarqand.
    (
        "Qashqadaryo - Buxoro",
        [
            "Surxondaryo viloyati",
            "Qashqadaryo viloyati",
            "Buxoro viloyati",
            "Xorazm viloyati",
        ],
    ),
]

#: The stored columns stay inside their CHECK constraints (search radius <= 50 km, point offset
#: <= 25 km): those caps are a real invariant and this script does not fight them. What makes a place
#: away from an axis reachable is `ELCHI_GEO_DEV_POINT_OFFSET_M`, which widens the radius the
#: *resolver* tolerates, and only outside production - see `corridor_point_offset_m`.
DEV_POINT_OFFSET_M = 25_000
DEV_SEARCH_RADIUS_M = 50_000

SERVICE_FLAGS = (
    FeatureFlagKey.PASSENGER_ENABLED,
    FeatureFlagKey.PARCEL_ENABLED,
    FeatureFlagKey.DRIVER_LISTING_ENABLED,
    FeatureFlagKey.CORRIDOR_MATCHING_ENABLED,
    # Without it the booking's tracking tab explains that tracking is off, which looks like a bug
    # while testing rather than the configuration statement it is.
    FeatureFlagKey.TRACKING_ENABLED,
)

#: Deliberately NOT here: `wallet_required` (Q1 - turning it off in any environment would still
#: compute, snapshot and hold the commission, so switching it is never a shortcut) and
#: `card_payments_enabled` (there is no card flow to test against).


def nearest_district(db, region_id: int, lat: float, lng: float):  # noqa: ANN001, ANN201
    """A stop needs a district; pick the one whose centre is closest to the region centre."""
    rows = db.scalars(
        select(GeoDistrict).where(GeoDistrict.region_id == region_id, GeoDistrict.is_active)
    ).all()
    if not rows:
        return None
    with_centre = [row for row in rows if row.center_lat is not None and row.center_lng is not None]
    if not with_centre:
        return rows[0]
    return min(
        with_centre,
        key=lambda row: (float(row.center_lat) - lat) ** 2 + (float(row.center_lng) - lng) ** 2,
    )


def enable_country_flags(db, *, actor_user_id: int) -> dict[str, str]:  # noqa: ANN001
    """Turn the stage-2 services on at **country** scope, through the service (never an INSERT).

    Going through `set_flag_value` keeps every rollout rule running: the capability check, the
    production locks, the Q48 money gate and the audit row. A flag already on is left completely alone.
    """
    outcome: dict[str, str] = {}
    for flag in SERVICE_FLAGS:
        rows = geo_service.list_flag_values(db, flag_key=flag, scope_type=FlagScopeType.COUNTRY)
        current = next((row for row in rows), None)
        if current is not None and current.enabled:
            outcome[flag.value] = "already on"
            continue
        try:
            geo_service.set_flag_value(
                db,
                actor_user_id=actor_user_id,
                actor_capabilities=[Capability.OPS_FEATURE_FLAG_MANAGE],
                actor_is_super_admin=True,
                flag_key=flag,
                scope_type=FlagScopeType.COUNTRY,
                scope_ref=COUNTRY_SCOPE_REF,
                enabled=True,
                reason="dev: open the whole catalogue for local testing",
                expected_version=current.version if current is not None else None,
            )
            outcome[flag.value] = "switched on"
        except Exception as error:  # noqa: BLE001 - a refused flag is reported, not fatal
            outcome[flag.value] = f"REFUSED by the service ({type(error).__name__}: {error})"
    db.commit()
    return outcome


def drop(db) -> int:  # noqa: ANN001
    """Close the dev corridors rather than delete them.

    Deleting is not available and should not be: a DB trigger protects the stops of a **confirmed**
    route version, because a route somebody may have been matched on is not something an operator gets
    to rewrite. Closing is the real retirement path - `_open_corridor_ids` stops offering a closed
    corridor, so nothing resolves onto it - and it goes through `patch_corridor`, so the rollout state
    machine and the audit row run exactly as they would for an operator.
    """
    corridors = db.scalars(
        select(ServiceCorridor).where(
            ServiceCorridor.name.like(f"{CORRIDOR_PREFIX}%"), ServiceCorridor.rollout_state != "closed"
        )
    ).all()
    if not corridors:
        print("nothing to close")
        return 0
    for corridor in corridors:
        info = geo_service.get_corridor(db, corridor.id)
        geo_service.patch_corridor(
            db,
            actor_user_id=1,
            corridor_api_id=info.api_id,
            expected_version=info.version,
            reason="dev fixture withdrawn",
            changes={"rollout_state": "closed"},
        )
        print(f"closed {corridor.name!r}")
    db.commit()
    return 0


def seed_corridor(db, *, actor_user_id: int, label: str, region_names: list[str], regions: dict) -> bool:  # noqa: ANN001
    """One axis: a corridor, its region-centre stops, and a confirmed route each way."""
    # The provider is part of the name on purpose: a corridor drawn by `fake` and one drawn by `osrm`
    # are different geography, and seeing which is which in the admin list is worth six characters.
    name = f"{CORRIDOR_PREFIX} {label} ({get_geo_settings().routing_provider})"
    if db.scalar(select(ServiceCorridor).where(ServiceCorridor.name == name)) is not None:
        print(f"  {name}: already present, unchanged")
        return False

    first, last = regions[region_names[0]], regions[region_names[-1]]
    corridor = geo_service.create_corridor(
        db,
        actor_user_id=actor_user_id,
        name=name,
        origin_region_api_id=geo_service.region_api_id(first.public_id),
        destination_region_api_id=geo_service.region_api_id(last.public_id),
        search_radius_m=DEV_SEARCH_RADIUS_M,
        default_max_detour_minutes=60,
        default_max_detour_m=50_000,
    )

    stop_api_ids: list[str] = []
    for index, region_name in enumerate(region_names):
        region = regions[region_name]
        lat, lng = float(region.center_lat), float(region.center_lng)
        district = nearest_district(db, region.id, lat, lng)
        if district is None:
            print(f"    {region_name}: no district to hang a stop on - skipped")
            continue
        stop = geo_service.create_stop(
            db,
            actor_user_id=actor_user_id,
            corridor_api_id=corridor.api_id,
            name_uz=f"{region_name} markazi ({label}, dev sinov)",
            name_ru=None,
            district_api_id=geo_service.district_api_id(district.public_id),
            point=LatLng(lat, lng),
            meeting_note="Dev fixture stop - a region centre, not a verified meeting point",
            sequence_hint=index + 1,
            is_active=True,
        )
        stop_api_ids.append(stop.api_id)

    if len(stop_api_ids) < 2:
        print(f"  {name}: fewer than two stops could be created - rolled back")
        db.rollback()
        return False

    db.execute(
        # Not a config field, so not reachable through patch_corridor: set directly, dev only.
        text("UPDATE service_corridors SET max_point_offset_m = :m WHERE id = :c"),
        {"m": DEV_POINT_OFFSET_M, "c": corridor.id},
    )
    db.commit()

    state = corridor
    for target in ("internal", "pilot"):
        state = geo_service.patch_corridor(
            db,
            actor_user_id=actor_user_id,
            corridor_api_id=corridor.api_id,
            expected_version=state.version,
            reason="dev nationwide fixture",
            changes={"rollout_state": target},
        )
    db.commit()

    from tests.fixtures.geo.loader import build_route  # noqa: PLC0415

    # Whatever the environment is configured to use. With `osrm` these stops are joined by the real
    # road; with `fake` they are joined by a straight line and the corridor name says so.
    router = build_routing_provider(production=False)
    build_route(db, router, actor_user_id=actor_user_id, stop_api_ids=stop_api_ids)
    build_route(db, router, actor_user_id=actor_user_id, stop_api_ids=list(reversed(stop_api_ids)))
    print(f"  {name}: {len(stop_api_ids)} stops, 2 confirmed routes")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-user-id", type=int, default=1, help="staff user the audit rows name")
    parser.add_argument("--drop", action="store_true", help="remove the dev corridors again")
    parser.add_argument("--flags-only", action="store_true", help="only switch the country flags on")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

    with SessionLocal() as db:
        if platform_service.is_production(db):
            print("refusing to run against a production marker")
            return 2

        if args.drop:
            return drop(db)

        print("country-scope service flags:")
        for key, outcome in enable_country_flags(db, actor_user_id=args.actor_user_id).items():
            print(f"  {key}: {outcome}")

        if args.flags_only:
            return 0

        regions = {row.name_uz: row for row in db.scalars(select(Region).where(Region.is_active)).all()}
        needed = {name for _, names in CORRIDORS for name in names}
        missing = sorted(name for name in needed if name not in regions)
        if missing:
            print()
            print(f"catalogue is incomplete, these regions are absent: {', '.join(missing)}")
            print("run scripts/import_legacy_districts.py --create-regions --apply first")
            return 2
        without_centre = sorted(name for name in needed if regions[name].center_lat is None)
        if without_centre:
            print()
            print(f"these regions have no centre, so no stop can be placed: {', '.join(without_centre)}")
            return 2

        print()
        print("corridors:")
        for label, region_names in CORRIDORS:
            seed_corridor(
                db,
                actor_user_id=args.actor_user_id,
                label=label,
                region_names=region_names,
                regions=regions,
            )

        print()
        print("Set ELCHI_GEO_DEV_POINT_OFFSET_M in .env (e.g. 250000) so places away from an axis still")
        print("project onto one; without it only places within 25 km of a line resolve. Dev only - the")
        print("resolver ignores the override outside development. These are fixtures, not geography: the")
        print("lines are straight hops between region centres, so a leg is close to the real road, not it.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
