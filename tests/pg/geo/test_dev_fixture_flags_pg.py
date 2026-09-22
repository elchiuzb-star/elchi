"""The dev corridor has the whole two-sided marketplace switched on - and only the dev corridor does.

Why this exists: `driver_listing_enabled` defaults to `false` everywhere (`PRODUCTION_FLAG_DEFAULTS`), and the
geo fixture used to seed a corridor without a row for it. A corridor with no row falls back to that default, so
a developer's stack had a working *demand* side and a silently closed *supply* side: the driver's
"publish a trip offer" screen answered `FEATURE_DISABLED`, which reads like a bug in the marketplace rather
than a missing fixture row. Q92 says both sides need a way in; in dev, they now have one.

What must stay true, and is asserted here:

* the production default is untouched - a corridor nobody configured still refuses a trip offer;
* seeding twice changes nothing: no new version, no history row, no audit entry (config drift in a seed script
  is how two developers end up on different configurations and blame the code);
* the flags go through `set_flag_value`, so the capability check, the Q72 write marker, the version trigger and
  the audit row all still run - the fixture is not a back door into the flag table.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.contracts.enums import FeatureFlagKey, FlagScopeType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.geo import service as geo_service
from tests.fixtures.geo.loader import DEV_CORRIDOR_SERVICE_FLAGS, enable_dev_service_flags, load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user

pytestmark = pytest.mark.pg


@pytest.fixture
def seeded(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fixture = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
    return pg_db, fixture, admin


def flag_rows(pg_db: PgDatabase) -> dict[str, tuple[bool, int]]:
    with pg_db.engine.connect() as conn:
        rows = conn.execute(text("SELECT flag_key, enabled, version FROM feature_flag_values")).all()
    return {row.flag_key: (row.enabled, row.version) for row in rows}


def counts(pg_db: PgDatabase) -> tuple[int, int]:
    with pg_db.engine.connect() as conn:
        history = conn.scalar(text("SELECT count(*) FROM feature_flag_changes"))
        audit = conn.scalar(text("SELECT count(*) FROM audit_logs WHERE entity_type = 'feature_flag_value'"))
    return history, audit


def test_the_dev_corridor_gets_every_stage_two_service(seeded) -> None:  # noqa: ANN001
    pg_db, fixture, admin = seeded
    with pg_db.session() as db:
        changed = enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)

    assert set(changed) == set(DEV_CORRIDOR_SERVICE_FLAGS)
    assert all(changed.values()), "a fresh corridor has none of them yet"
    rows = flag_rows(pg_db)
    for key in DEV_CORRIDOR_SERVICE_FLAGS:
        assert rows[key] == (True, 1), key


def test_seeding_twice_changes_nothing(seeded) -> None:  # noqa: ANN001
    """Idempotent means *no write at all*, not "writes the same value again"."""
    pg_db, fixture, admin = seeded
    with pg_db.session() as db:
        enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)
    before_rows, before_counts = flag_rows(pg_db), counts(pg_db)

    with pg_db.session() as db:
        changed = enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)

    assert not any(changed.values()), "the second run reports nothing switched on"
    assert flag_rows(pg_db) == before_rows, "no version was bumped"
    assert counts(pg_db) == before_counts, "no history or audit row was appended"


def test_a_flag_someone_turned_off_is_corrected_through_its_version(seeded) -> None:  # noqa: ANN001
    pg_db, fixture, admin = seeded
    with pg_db.session() as db:
        enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)
    with pg_db.session() as db:
        # Turning a flag *off* never needs the Q72 marker, so this is the ordinary operator path.
        geo_service.set_flag_value(
            db,
            actor_user_id=admin,
            actor_capabilities=list(_manage_capability()),
            actor_is_super_admin=True,
            flag_key=FeatureFlagKey.DRIVER_LISTING_ENABLED,
            scope_type=FlagScopeType.CORRIDOR,
            scope_ref=fixture.corridor.api_id,
            enabled=False,
            reason="operator turned it off",
            expected_version=1,
        )
        db.commit()

    with pg_db.session() as db:
        changed = enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)

    assert changed["driver_listing_enabled"] is True
    assert flag_rows(pg_db)["driver_listing_enabled"] == (True, 3), "corrected through the current version"


def test_it_refuses_to_run_under_the_production_marker(seeded) -> None:  # noqa: ANN001
    """The safety net is the point: a dev convenience must not be able to open services in production."""
    pg_db, fixture, admin = seeded
    # One way on purpose (N1): a DB guard refuses downgrading the marker, so this is not restored afterwards -
    # every test gets its own database and it is dropped at the end.
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))
    with pg_db.session() as db, pytest.raises(RuntimeError, match="never be seeded in production"):
        enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)
    assert flag_rows(pg_db) == {}, "nothing was written"


def test_the_production_default_is_untouched(seeded) -> None:  # noqa: ANN001
    """The fixture is scoped to one corridor; everywhere else the safe default still answers."""
    pg_db, fixture, admin = seeded
    with pg_db.session() as db:
        enable_dev_service_flags(db, corridor_api_id=fixture.corridor.api_id, actor_user_id=admin)

    regions = list(fixture.regions.values())
    with pg_db.session() as db:
        other = geo_service.create_corridor(
            db,
            actor_user_id=admin,
            name="Konfiguratsiyasiz koridor (fixture)",
            origin_region_api_id=regions[0].api_id,
            destination_region_api_id=regions[-1].api_id,
            search_radius_m=5_000,
            default_max_detour_minutes=30,
            default_max_detour_m=20_000,
        )
        db.commit()

    from app.modules.marketplace.ports import get_ports

    with pg_db.session() as db:
        port = get_ports().flags
        # A real corridor that nobody configured: resolution finds no row and falls back to the safe default.
        for key in (FeatureFlagKey.DRIVER_LISTING_ENABLED, FeatureFlagKey.PARCEL_ENABLED, FeatureFlagKey.PASSENGER_ENABLED):
            assert port.is_enabled(db, key, corridor_id=other.id) is False, key
        # ...while the corridor the fixture configured has them on.
        assert port.is_enabled(db, FeatureFlagKey.DRIVER_LISTING_ENABLED, corridor_id=fixture.corridor.id) is True


def _manage_capability():  # noqa: ANN202
    from app.contracts.enums import Capability

    return (Capability.OPS_FEATURE_FLAG_MANAGE,)


def test_domain_error_is_the_contract_for_a_forbidden_flag_write(seeded) -> None:  # noqa: ANN001
    """Without the capability the service refuses - the fixture helper does not bypass authorization."""
    pg_db, fixture, admin = seeded
    with pg_db.session() as db, pytest.raises(DomainError) as refused:
        geo_service.set_flag_value(
            db,
            actor_user_id=admin,
            actor_capabilities=[],
            actor_is_super_admin=False,
            flag_key=FeatureFlagKey.DRIVER_LISTING_ENABLED,
            scope_type=FlagScopeType.CORRIDOR,
            scope_ref=fixture.corridor.api_id,
            enabled=True,
            reason="no capability",
        )
    assert refused.value.code is ErrorCode.FORBIDDEN
