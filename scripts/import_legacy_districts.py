"""Copy the district names of the legacy v1 catalogue into the v2 ``geo_districts`` catalogue.

User decision 17.09.2026: a direction is chosen as *region -> district* everywhere except Tashkent city, and
the district names come from the list the platform already uses in v1 rather than from a list written from
memory. This script is that copy. It writes nothing that it cannot trace to an existing row:

* a legacy city becomes a v2 region only through ``legacy_city_mappings``. When no mapping exists the script
  proposes one by matching ``cities.region`` against ``regions.name_uz`` / ``regions.code``, and records it as
  ``unverified`` - an operator confirms it later. An ambiguous or missing match is **reported and skipped**,
  never guessed;
* a legacy district becomes ``geo_districts`` row with ``legacy_district_id`` pointing back at its source, so
  a re-run updates nothing and inserts nothing twice;
* regions with ``requires_district = false`` (Tashkent city) are skipped: there the city itself is the unit;
* ``--create-regions`` fills the v2 region catalogue from the same legacy rows before importing: one region per
  distinct ``cities.region``, named exactly as the legacy catalogue names it, coded with its ISO 3166-2:UZ
  code from the table below. A region name that is not in that table is **reported and skipped**, never coded
  by guesswork. Tashkent city is created with ``requires_district = false``;
* nothing here creates a stop or a route. A district in the catalogue is a *name you can search by*, not a
  promise that a verified stop serves it - that stays operator work (Q27).

The script is read-only until ``--apply`` is passed, and it refuses to run when the database carries no
environment marker (fail closed, same rule as the other catalogue scripts).

Usage::

    ELCHI_DATABASE_URL=postgresql+psycopg://... py scripts/import_legacy_districts.py                  # dry run
    ELCHI_DATABASE_URL=postgresql+psycopg://... py scripts/import_legacy_districts.py --create-regions --apply
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


#: ISO 3166-2:UZ codes for the region names the legacy catalogue uses. The *names* come from the database;
#: only the code comes from the standard, and a name that is missing here is skipped rather than coded blindly.
#: ``UZ-TK`` is Tashkent city (the direction unit is the city itself); ``UZ-TO`` is the surrounding region.
REGION_CODES: dict[str, tuple[str, bool]] = {
    "toshkent shahri": ("UZ-TK", False),
    "toshkent viloyati": ("UZ-TO", True),
    "andijon": ("UZ-AN", True),
    "buxoro": ("UZ-BU", True),
    "fargona": ("UZ-FA", True),
    "jizzax": ("UZ-JI", True),
    "namangan": ("UZ-NG", True),
    "navoiy": ("UZ-NW", True),
    "qashqadaryo": ("UZ-QA", True),
    "qoraqalpogiston": ("UZ-QR", True),
    "samarqand": ("UZ-SA", True),
    "sirdaryo": ("UZ-SI", True),
    "surxondaryo": ("UZ-SU", True),
    "xorazm": ("UZ-XO", True),
}


#: The legacy catalogue writes a region either bare ("Qashqadaryo") or with its type ("Qashqadaryo viloyati",
#: "Qoraqalpog'iston Respublikasi"), and with any of three apostrophes. Both forms mean the same region, so the
#: lookup normalises before it matches - but "Toshkent shahri" and "Toshkent viloyati" stay two different rows.
_TYPE_SUFFIXES = (" respublikasi", " viloyati")


def normalise_region_name(value: str) -> list[str]:
    """Candidate keys for ``REGION_CODES``, most specific first."""
    text = value.strip().casefold()
    for apostrophe in ("ʻ", "ʼ", "‘", "’", "'", "`"):
        text = text.replace(apostrophe, "")
    text = " ".join(text.split())
    keys = [text]
    for suffix in _TYPE_SUFFIXES:
        if text.endswith(suffix):
            keys.append(text[: -len(suffix)].strip())
    return keys


def region_code_for(name: str) -> tuple[str, bool] | None:
    for key in normalise_region_name(name):
        known = REGION_CODES.get(key)
        if known is not None:
            return known
    return None


def create_regions(session, *, apply: bool) -> tuple[list[tuple[str, str]], list[str]]:  # noqa: ANN001 - Session
    """Create one v2 region per distinct legacy ``cities.region``. Returns ``(created, skipped)``."""
    from sqlalchemy import text

    from app.contracts.ids import new_public_uuid

    names = [
        row[0]
        for row in session.execute(
            text("SELECT DISTINCT region FROM cities WHERE is_active AND region IS NOT NULL ORDER BY region")
        ).all()
    ]
    created: list[tuple[str, str]] = []
    skipped: list[str] = []
    for name in names:
        known = region_code_for(name)
        if known is None:
            skipped.append(f"{name}: no ISO code in REGION_CODES (add it, or create the region by hand)")
            continue
        code, requires_district = known
        exists = session.execute(
            text("SELECT 1 FROM regions WHERE code = :c OR lower(name_uz) = lower(:n)"), {"c": code, "n": name}
        ).first()
        if exists:
            continue
        created.append((code, name))
        if apply:
            session.execute(
                text(
                    "INSERT INTO regions (public_id, code, name_uz, requires_district, is_active) "
                    "VALUES (:u, :c, :n, :q, true)"
                ),
                {"u": new_public_uuid(), "c": code, "n": name, "q": requires_district},
            )
    return created, skipped


@dataclass
class CityPlan:
    legacy_city_id: int
    legacy_city_name: str
    legacy_region_name: str | None
    region_id: int | None = None
    region_name: str | None = None
    mapping_exists: bool = False
    skip_reason: str | None = None
    new_districts: list[str] = field(default_factory=list)
    existing_districts: int = 0


def _match_region(regions: list[dict], legacy_region_name: str | None, legacy_city_name: str) -> list[dict]:
    """Regions whose name or code matches the legacy text. Several matches = ambiguous, and we stop.

    Both sides are normalised the same way ("Qashqadaryo" and "Qashqadaryo viloyati" are one region), except
    that Tashkent city and Tashkent region never collapse into each other.
    """
    for value in (legacy_region_name, legacy_city_name):
        if not value:
            continue
        needles = set(normalise_region_name(value))
        hits = [
            region
            for region in regions
            if needles & set(normalise_region_name(region["name_uz"]))
            or value.strip().casefold() == (region["code"] or "").strip().casefold()
        ]
        if hits:
            return hits
    return []


def build_plan(session, *, regions: list[dict]) -> list[CityPlan]:  # noqa: ANN001 - Session
    from sqlalchemy import text

    cities = session.execute(
        text(
            "SELECT id, name_uz, region, requires_district, is_active FROM cities "
            "WHERE is_active ORDER BY display_order, id"
        )
    ).all()
    plans: list[CityPlan] = []
    for city in cities:
        plan = CityPlan(
            legacy_city_id=city.id, legacy_city_name=city.name_uz, legacy_region_name=city.region
        )
        if not city.requires_district:
            # Tashkent city in the legacy catalogue: the city itself is the direction unit.
            plan.skip_reason = "legacy city does not use districts"
            plans.append(plan)
            continue

        mapped = session.execute(
            text("SELECT region_id FROM legacy_city_mappings WHERE legacy_city_id = :c"), {"c": city.id}
        ).scalar_one_or_none()
        if mapped is not None:
            region = next((r for r in regions if r["id"] == int(mapped)), None)
            plan.mapping_exists = True
        else:
            hits = _match_region(regions, city.region, city.name_uz)
            if len(hits) > 1:
                plan.skip_reason = f"ambiguous region match ({', '.join(h['name_uz'] for h in hits)})"
                plans.append(plan)
                continue
            region = hits[0] if hits else None
        if region is None:
            plan.skip_reason = "no v2 region for this legacy city (create the region first)"
            plans.append(plan)
            continue
        if not region["requires_district"]:
            plan.skip_reason = f"{region['name_uz']} does not use districts"
            plans.append(plan)
            continue

        plan.region_id, plan.region_name = region["id"], region["name_uz"]
        rows = session.execute(
            text(
                "SELECT id, name_uz, name_ru FROM districts WHERE city_id = :c AND is_active "
                "ORDER BY display_order, id"
            ),
            {"c": city.id},
        ).all()
        for district in rows:
            taken = session.execute(
                text(
                    "SELECT 1 FROM geo_districts WHERE legacy_district_id = :d "
                    "OR (region_id = :r AND lower(name_uz) = lower(:n))"
                ),
                {"d": district.id, "r": region["id"], "n": district.name_uz},
            ).first()
            if taken:
                plan.existing_districts += 1
            else:
                plan.new_districts.append(district.name_uz)
        plans.append(plan)
    return plans


def apply_plan(session, plans: list[CityPlan]) -> tuple[int, int]:  # noqa: ANN001 - Session
    from sqlalchemy import text

    from app.contracts.ids import new_public_uuid

    mappings = districts = 0
    for plan in plans:
        if plan.skip_reason is not None or plan.region_id is None:
            continue
        if not plan.mapping_exists:
            session.execute(
                text(
                    "INSERT INTO legacy_city_mappings (legacy_city_id, region_id, mapping_status, note) "
                    "VALUES (:c, :r, 'unverified', :note) ON CONFLICT (legacy_city_id) DO NOTHING"
                ),
                {
                    "c": plan.legacy_city_id,
                    "r": plan.region_id,
                    "note": "scripts/import_legacy_districts.py: matched by name; an operator verifies it",
                },
            )
            mappings += 1
        for name in plan.new_districts:
            legacy = session.execute(
                text(
                    "SELECT id, name_ru FROM districts WHERE city_id = :c AND name_uz = :n AND is_active "
                    "ORDER BY id LIMIT 1"
                ),
                {"c": plan.legacy_city_id, "n": name},
            ).one_or_none()
            session.execute(
                text(
                    "INSERT INTO geo_districts (public_id, region_id, name_uz, name_ru, legacy_district_id, is_active) "
                    "VALUES (:u, :r, :n, :ru, :l, true) ON CONFLICT DO NOTHING"
                ),
                {
                    "u": new_public_uuid(),
                    "r": plan.region_id,
                    "n": name,
                    "ru": legacy.name_ru if legacy else None,
                    "l": legacy.id if legacy else None,
                },
            )
            districts += 1
    return mappings, districts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the plan (without it the script only reports)")
    parser.add_argument(
        "--create-regions",
        action="store_true",
        help="also create the v2 regions from the distinct legacy cities.region values (ISO codes)",
    )
    args = parser.parse_args(argv)

    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.modules.platform import service as platform_service

    with SessionLocal() as session:
        environment = platform_service.get_db_environment(session)
        if environment is None:
            print("refusing: database environment marker is missing (fail closed)", file=sys.stderr)
            return 2
        session.rollback()
        print(f"environment: {environment}")

        if args.create_regions:
            created, skipped = create_regions(session, apply=args.apply)
            for code, name in created:
                print(f"  {'REGION' if args.apply else 'region'} {code:<6} {name}")
            for reason in skipped:
                print(f"  SKIP   region  {reason}")
            if args.apply:
                session.flush()
            elif created:
                print(f"  ({len(created)} regions would be created)")

        regions = [
            dict(row._mapping)
            for row in session.execute(
                text("SELECT id, code, name_uz, requires_district FROM regions WHERE is_active ORDER BY name_uz")
            ).all()
        ]
        if args.create_regions and not args.apply:
            # A dry run must still be able to show the districts. The proposed regions get placeholder ids;
            # nothing is written, and apply_plan is never reached on this path.
            regions += [
                {"id": -index, "code": code, "name_uz": name, "requires_district": REGION_CODES[key][1]}
                for index, (code, name) in enumerate(created, start=1)
                for key in [next(k for k in normalise_region_name(name) if k in REGION_CODES)]
            ]
        if not regions:
            print(
                "refusing: no v2 regions yet - run with --create-regions, or create the region catalogue first",
                file=sys.stderr,
            )
            return 2
        plans = build_plan(session, regions=regions)

        planned_districts = 0
        for plan in plans:
            if plan.skip_reason is not None:
                print(f"  SKIP  {plan.legacy_city_name:<16} {plan.skip_reason}")
                continue
            planned_districts += len(plan.new_districts)
            names = ", ".join(plan.new_districts) if plan.new_districts else "-"
            print(
                f"  {'MAP ' if not plan.mapping_exists else '    '} {plan.legacy_city_name:<16} "
                f"-> {plan.region_name} | new {len(plan.new_districts):>3}, already present "
                f"{plan.existing_districts:>3} | {names}"
            )
        if not args.apply:
            print(f"\ndry run: {planned_districts} districts would be created. Re-run with --apply to write.")
            return 0
        mappings, districts = apply_plan(session, plans)
        session.commit()
        print(f"\ncreated {districts} districts and {mappings} unverified city->region mappings.")
        print("Next: an operator verifies the mappings and attaches verified stops (Q27) to the districts.")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
