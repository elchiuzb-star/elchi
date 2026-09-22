"""Wave 10: importing the v1 district names into the v2 catalogue (user decision 17.09.2026).

The decision was "copy the legacy list", not "write a list of Uzbek districts". The risk in such an import is
that it quietly invents the part it cannot find - a region for a city it could not match, or a second copy of a
district on the next run. These tests hold it to the opposite behaviour: it skips what it cannot trace, it
leaves Tashkent city alone, and running it twice changes nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase

pytestmark = pytest.mark.pg

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "import_legacy_districts.py"


def load_script():  # noqa: ANN201
    spec = importlib.util.spec_from_file_location("import_legacy_districts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # @dataclass resolves its module through sys.modules; a file loaded outside it cannot build the class.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def seed(pg_db: PgDatabase) -> None:
    with pg_db.session() as db:
        db.execute(
            text(
                "INSERT INTO regions (public_id, code, name_uz, requires_district) VALUES "
                "(gen_random_uuid(), 'UZ-TK', 'Toshkent shahri', false), "
                "(gen_random_uuid(), 'UZ-QA', 'Qashqadaryo viloyati', true), "
                "(gen_random_uuid(), 'UZ-SA', 'Samarqand viloyati', true)"
            )
        )
        cities = {}
        for name, region, requires in (
            ("Toshkent", "Toshkent shahri", False),
            ("Qarshi", "Qashqadaryo", True),
            ("Samarqand", "Samarqand", True),
            ("Nukus", "Qoraqalpogiston", True),  # no v2 region: must be reported, not invented
        ):
            cities[name] = db.execute(
                text(
                    "INSERT INTO cities (name, name_uz, region, type, requires_district, display_order, is_active) "
                    "VALUES (:n, :n, :r, 'region', :q, 1, true) RETURNING id"
                ),
                {"n": name, "r": region, "q": requires},
            ).scalar_one()
        for city, districts in (
            ("Qarshi", ["Chiroqchi", "Kitob", "Koson"]),
            ("Samarqand", ["Urgut", "Bulungur"]),
            ("Toshkent", ["Chilonzor", "Yunusobod"]),
            ("Nukus", ["Xojayli"]),
        ):
            for order, district in enumerate(districts):
                db.execute(
                    text(
                        "INSERT INTO districts (city_id, name_uz, is_active, display_order) "
                        "VALUES (:c, :n, true, :o)"
                    ),
                    {"c": cities[city], "n": district, "o": order},
                )
        db.commit()


def counts(pg_db: PgDatabase) -> tuple[int, int]:
    with pg_db.session() as db:
        return (
            db.execute(text("SELECT count(*) FROM geo_districts")).scalar_one(),
            db.execute(text("SELECT count(*) FROM legacy_city_mappings")).scalar_one(),
        )


def test_a_dry_run_writes_nothing(pg_db: PgDatabase) -> None:
    seed(pg_db)
    module = load_script()
    with pg_db.session() as db:
        regions = [dict(row._mapping) for row in db.execute(text("SELECT id, code, name_uz, requires_district FROM regions")).all()]
        plans = module.build_plan(db, regions=regions)
        db.rollback()
    assert counts(pg_db) == (0, 0)
    planned = {plan.legacy_city_name: plan for plan in plans}
    assert planned["Qarshi"].new_districts == ["Chiroqchi", "Kitob", "Koson"]
    assert planned["Qarshi"].region_name == "Qashqadaryo viloyati"


def test_tashkent_city_is_left_without_districts(pg_db: PgDatabase) -> None:
    seed(pg_db)
    module = load_script()
    with pg_db.session() as db:
        regions = [dict(row._mapping) for row in db.execute(text("SELECT id, code, name_uz, requires_district FROM regions")).all()]
        plans = module.build_plan(db, regions=regions)
        module.apply_plan(db, plans)
        db.commit()
        names = [row[0] for row in db.execute(text("SELECT name_uz FROM geo_districts ORDER BY name_uz")).all()]
    assert "Chilonzor" not in names and "Yunusobod" not in names
    assert {"Chiroqchi", "Kitob", "Koson", "Urgut", "Bulungur"} == set(names)


def test_a_city_without_a_v2_region_is_reported_not_invented(pg_db: PgDatabase) -> None:
    seed(pg_db)
    module = load_script()
    with pg_db.session() as db:
        regions = [dict(row._mapping) for row in db.execute(text("SELECT id, code, name_uz, requires_district FROM regions")).all()]
        plans = module.build_plan(db, regions=regions)
        module.apply_plan(db, plans)
        db.commit()
        region_count = db.execute(text("SELECT count(*) FROM regions")).scalar_one()
    nukus = next(plan for plan in plans if plan.legacy_city_name == "Nukus")
    assert nukus.skip_reason is not None and "region" in nukus.skip_reason
    assert region_count == 3, "the import never creates a region"


def test_every_imported_district_points_back_at_its_source_and_a_rerun_is_a_no_op(pg_db: PgDatabase) -> None:
    seed(pg_db)
    module = load_script()

    def run() -> tuple[int, int]:
        with pg_db.session() as db:
            regions = [dict(row._mapping) for row in db.execute(text("SELECT id, code, name_uz, requires_district FROM regions")).all()]
            result = module.apply_plan(db, module.build_plan(db, regions=regions))
            db.commit()
            return result

    first = run()
    assert first == (2, 5)  # two mappings (Qarshi, Samarqand), five districts
    after_first = counts(pg_db)
    second = run()
    assert second == (0, 0) and counts(pg_db) == after_first

    with pg_db.session() as db:
        orphans = db.execute(text("SELECT count(*) FROM geo_districts WHERE legacy_district_id IS NULL")).scalar_one()
        statuses = {row[0] for row in db.execute(text("SELECT mapping_status FROM legacy_city_mappings")).all()}
    assert orphans == 0, "an imported district always names the legacy row it came from"
    assert statuses == {"unverified"}, "a name match is a proposal; an operator verifies it"

# --- --create-regions (the step that fills the v2 region catalogue) ---------------------------------------


def test_region_names_match_in_both_legacy_spellings() -> None:
    """The legacy catalogue writes "Qashqadaryo" in one seed and "Qashqadaryo viloyati" in another."""
    module = load_script()
    assert module.region_code_for("Qashqadaryo") == module.region_code_for("Qashqadaryo viloyati") == ("UZ-QA", True)
    assert module.region_code_for("Farg'ona viloyati") == ("UZ-FA", True)
    assert module.region_code_for("Qoraqalpog'iston Respublikasi") == ("UZ-QR", True)
    # The city and the region around it never collapse into one row.
    assert module.region_code_for("Toshkent shahri") == ("UZ-TK", False)
    assert module.region_code_for("Toshkent viloyati") == ("UZ-TO", True)
    assert module.region_code_for("Qoraqalpogiston Viloyati Shimoli") is None


def test_create_regions_uses_the_legacy_names_and_leaves_tashkent_city_without_districts(
    pg_db: PgDatabase,
) -> None:
    module = load_script()
    with pg_db.session() as db:
        for name, region in (("Toshkent shahri", "Toshkent shahri"), ("Qarshi", "Qashqadaryo viloyati")):
            db.execute(
                text(
                    "INSERT INTO cities (name, name_uz, region, type, requires_district, display_order, is_active) "
                    "VALUES (:n, :n, :r, 'region', true, 1, true)"
                ),
                {"n": name, "r": region},
            )
        db.commit()

        created, skipped = module.create_regions(db, apply=True)
        db.commit()
        rows = {
            row.code: (row.name_uz, row.requires_district)
            for row in db.execute(text("SELECT code, name_uz, requires_district FROM regions")).all()
        }
    assert skipped == []
    assert {code for code, _ in created} == {"UZ-TK", "UZ-QA"}
    # The name is the legacy text, unchanged; only the code comes from the standard.
    assert rows["UZ-QA"] == ("Qashqadaryo viloyati", True)
    assert rows["UZ-TK"] == ("Toshkent shahri", False)


def test_create_regions_is_a_no_op_on_a_second_run_and_reports_what_it_cannot_code(pg_db: PgDatabase) -> None:
    module = load_script()
    with pg_db.session() as db:
        db.execute(
            text(
                "INSERT INTO cities (name, name_uz, region, type, requires_district, display_order, is_active) "
                "VALUES ('Atlantida', 'Atlantida', 'Atlantida viloyati', 'region', true, 1, true)"
            )
        )
        db.commit()
        created, skipped = module.create_regions(db, apply=True)
        db.commit()
        again, _ = module.create_regions(db, apply=True)
        db.commit()
        count = db.execute(text("SELECT count(*) FROM regions")).scalar_one()
    assert created == [] and again == []
    assert len(skipped) == 1 and "no ISO code" in skipped[0]
    assert count == 0, "an unknown region is reported, never coded by guesswork"
