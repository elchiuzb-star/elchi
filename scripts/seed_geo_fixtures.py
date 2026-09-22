"""Seed the SYNTHETIC geo fixture (dev/test only).

Loads tests/fixtures/geo/corridor_fixture.json: 3 regions, 6 districts, 1 corridor,
6 stops and 2 confirmed straight-line routes from the fake router. The coordinates
are approximate and unverified; this is not production geography.

Also switches the corridor's stage-2 service flags on (passenger, parcel, driver listing, matching) so the
whole two-sided marketplace is reachable in dev. Production defaults are untouched: they stay `false`, and
the same service call that a real rollout goes through refuses to run here under a production marker.

Refuses to run when production is detected (``platform.service.is_production``: settings OR
the DB marker) or when the DB environment marker is missing (fail closed). Safe to re-run:
does nothing when the fixture corridor already exists. Migration 0043 additionally rejects
fixture route versions under the production marker.

Usage:
    ELCHI_DATABASE_URL=postgresql+psycopg://... py scripts/seed_geo_fixtures.py --actor-user-id 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--actor-user-id", type=int, required=True, help="existing staff user id recorded as creator/verifier")
    parser.add_argument("--no-routes", action="store_true", help="only catalogue, corridor and stops")
    parser.add_argument(
        "--no-flags",
        action="store_true",
        help="leave the corridor's stage-2 service flags alone (they are switched on by default in dev)",
    )
    args = parser.parse_args(argv)

    from sqlalchemy import func, select

    from app.contracts.ids import PublicIdPrefix, format_public_id
    from app.db.session import SessionLocal
    from app.modules.geo.models import ServiceCorridor
    from app.modules.platform import service as platform_service
    from tests.fixtures.geo.loader import enable_dev_service_flags, load_geo_fixture, load_json

    name = load_json()["corridor"]["name"]
    with SessionLocal() as db:
        if platform_service.is_production(db):
            print("refusing: synthetic geo fixtures must never be seeded in production", file=sys.stderr)
            return 2
        if platform_service.get_db_environment(db) is None:
            print("refusing: database environment marker is missing (fail closed)", file=sys.stderr)
            return 2
        db.rollback()
        existing = db.scalar(select(ServiceCorridor).where(func.lower(ServiceCorridor.name) == name.lower()))
        if existing is not None:
            corridor_api_id = format_public_id(PublicIdPrefix.CORRIDOR, existing.public_id)
            print(f"fixture corridor {name!r} already present; catalogue unchanged")
        else:
            fixture = load_geo_fixture(db, actor_user_id=args.actor_user_id, with_routes=not args.no_routes)
            corridor_api_id = fixture.corridor.api_id
            print(f"seeded corridor {corridor_api_id} with {len(fixture.stops)} stops and {len(fixture.routes)} confirmed routes")

        # The flags are ensured on every run, not only on the first: a corridor with no
        # `driver_listing_enabled` row falls back to the production default (false), and a driver then cannot
        # publish a trip offer at all - half of the two-sided auction closed for a configuration reason.
        if not args.no_flags:
            changed = enable_dev_service_flags(db, corridor_api_id=corridor_api_id, actor_user_id=args.actor_user_id)
            turned_on = sorted(key for key, did in changed.items() if did)
            print(
                f"dev service flags: {len(turned_on)} switched on"
                + (f" ({', '.join(turned_on)})" if turned_on else "")
                + f", {len(changed) - len(turned_on)} already on"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
