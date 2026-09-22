"""Wave 1.7: Q56 v2 flag gate (service + DB trigger) and F1 Q47 violation detector (service, CLI, repair path)."""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.modules.platform.service as platform_service
from app.contracts.enums import STAFF_ROLE_CAPABILITIES, FeatureFlagKey, FlagScopeType, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import new_public_uuid
from app.core.config import settings
from app.modules.geo import jobs, service
from app.worker import advisory_lock_key
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import REPO_ROOT, PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user, set_q48_gate, set_support_phone

pytestmark = pytest.mark.pg


@pytest.fixture
def geo(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    super_admin = create_user(pg_db, "super_admin")
    with pg_db.session() as db:
        fx = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
    return pg_db, fx, admin, super_admin


def mark_production(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))


def set_flag(db, actor: int, key: FeatureFlagKey, enabled: bool, *, super_admin: bool = False, **kw):  # noqa: ANN001, ANN003, ANN201
    return service.set_flag_value(
        db,
        actor_user_id=actor,
        actor_capabilities=STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN if super_admin else Role.ADMIN],
        actor_is_super_admin=super_admin,
        flag_key=key,
        scope_type=FlagScopeType.COUNTRY,
        scope_ref="UZ",
        enabled=enabled,
        reason=kw.pop("reason", "launch"),
        **kw,
    )


RAW_INSERT = text(
    "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, approval_reference, reason, updated_by) "
    "VALUES (:p, :k, 'cohort', :ref, true, 'LEGAL-9', 'raw', :u)"
)


def raw_enable(pg_db: PgDatabase, key: str, actor: int, ref: str) -> None:
    """Raw SQL enable carrying the Q72 app marker, so the 0053 Q48 trigger is what gets exercised."""
    with pg_db.engine.begin() as conn:
        service.mark_flag_change_source(conn)
        conn.execute(RAW_INSERT, {"p": new_public_uuid(), "k": key, "ref": ref, "u": actor})


def gate_reason(fn) -> str:  # noqa: ANN001
    with pytest.raises(DomainError) as info:
        fn()
    assert info.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED and info.value.http_status == 503
    assert info.value.details["gate"] == "q48"
    return info.value.details["reason"]


def test_v2_service_flags_list() -> None:
    assert {k.value for k in service.V2_SERVICE_FLAGS} == {
        "passenger_enabled", "parcel_enabled", "driver_listing_enabled", "corridor_matching_enabled", "tracking_enabled", "card_payments_enabled",
    }
    assert FeatureFlagKey.WALLET_REQUIRED not in service.V2_SERVICE_FLAGS


def test_non_production_is_not_gated(geo, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = geo
    set_q48_gate(pg_db, monkeypatch, passed=None)  # no gate anywhere
    with pg_db.session() as db:
        assert set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, True).enabled
        db.commit()
    raw_enable(pg_db, "tracking_enabled", admin, "raw-dev")


def test_production_refuses_enable_while_gate_missing_or_failing(geo, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = geo
    with pg_db.session() as db:  # enabled before production: later edits are not "enabling"
        set_flag(db, admin, FeatureFlagKey.DRIVER_LISTING_ENABLED, True)
        db.commit()
    mark_production(pg_db)
    set_q48_gate(pg_db, monkeypatch, passed=None)
    with pg_db.session() as db:
        assert gate_reason(lambda: set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, True)) == "gate_unavailable"
        db.rollback()
        for gate, reason in (
            (lambda _db: False, "gate_failed"),
            (lambda _db: SimpleNamespace(passed=False), "gate_failed"),
            (lambda _db: object(), "gate_failed"),  # truthy but not an explicit pass: fail closed
            (lambda _db: 1, "gate_failed"),
        ):
            monkeypatch.setattr(platform_service, "q48_gate_status", gate, raising=False)
            assert gate_reason(lambda: set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, True)) == reason
            db.rollback()

        def boom(_db):  # noqa: ANN001, ANN202
            raise RuntimeError("gate broken")

        monkeypatch.setattr(platform_service, "q48_gate_status", boom, raising=False)
        assert gate_reason(lambda: set_flag(db, admin, FeatureFlagKey.TRACKING_ENABLED, True)) == "gate_error"
        db.rollback()
        # Disabling and editing an already enabled flag are not blocked.
        set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, False)
        set_flag(db, admin, FeatureFlagKey.DRIVER_LISTING_ENABLED, True, expected_version=1, reason="note")
        db.commit()
        assert service.list_flag_values(db, flag_key=FeatureFlagKey.PARCEL_ENABLED)[0].enabled is False
        monkeypatch.setattr(platform_service, "q48_gate_status", lambda _db: False, raising=False)
        assert gate_reason(lambda: set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, True, expected_version=1)) == "gate_failed"
        db.rollback()

    # Raw SQL (service bypassed): the 0053 trigger refuses with the A3 function missing or returning false.
    for passed in (None, False):
        set_q48_gate(pg_db, passed=passed)
        with pytest.raises(DBAPIError, match="Q48 launch gate"):
            raw_enable(pg_db, "tracking_enabled", admin, f"raw-{passed}")
        with pytest.raises(DBAPIError, match="Q48 launch gate"):
            with pg_db.engine.begin() as conn:
                service.mark_flag_change_source(conn)  # Q72 marker present: the Q48 trigger refuses
                conn.execute(text("UPDATE feature_flag_values SET enabled = true, version = version + 1 WHERE flag_key = 'parcel_enabled'"))
    with pg_db.engine.begin() as conn:  # non-enabling edit of an enabled row passes the trigger
        conn.execute(text("UPDATE feature_flag_values SET reason = 'raw note', version = version + 1 WHERE flag_key = 'driver_listing_enabled'"))


def test_production_allows_enable_when_gate_passes(geo, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, super_admin = geo
    mark_production(pg_db)
    set_q48_gate(pg_db, monkeypatch, passed=True)
    monkeypatch.setattr(platform_service, "q48_gate_status", lambda _db: SimpleNamespace(passed=True), raising=False)
    set_support_phone(monkeypatch)  # Q87 precondition for passenger_enabled
    with pg_db.session() as db:
        assert set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, True).version == 1
        assert set_flag(db, super_admin, FeatureFlagKey.PASSENGER_ENABLED, True, super_admin=True, approval_reference="LEGAL-2").enabled
        db.commit()
    raw_enable(pg_db, "tracking_enabled", admin, "raw-ok")
    with pg_db.session() as db:
        assert service.q48_gate_passed(db) == (True, "passed")


# --- F1: Q47 detector -------------------------------------------------------------------------------------


def run_check(pg_db: PgDatabase) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"ELCHI_DATABASE_URL": pg_db.url_str, "ELCHI_ENVIRONMENT": "test"})
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "app.modules.geo.checks", "q47"], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_q47_detector_cli_and_repair_path(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = geo
    with pg_db.session() as db:
        assert service.find_q47_violations(db) == []
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=fx.corridor.api_id, expected_version=fx.corridor.version, reason="go", changes={"rollout_state": "active"})
        db.commit()
    clean = run_check(pg_db)
    assert clean.returncode == 0 and clean.stdout == "", clean.stderr

    # Legacy/bypassed data: guards off for this transaction only.
    keep = fx.stop_id("qarshi")
    with pg_db.engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE corridor_stops SET is_active = false WHERE corridor_id = :c AND id <> :keep"), {"c": fx.corridor.id, "keep": keep})
        conn.execute(text("UPDATE corridor_stops SET meeting_note = NULL WHERE id = :keep"), {"keep": keep})

    with pg_db.session() as db:
        violations = service.find_q47_violations(db)
        assert len(violations) == 1
        found = violations[0]
        assert (found.api_id, found.rollout_state.value, found.active_stops) == (fx.corridor.api_id, "active", 1)
        assert found.stops_missing_evidence == (fx.stops["qarshi"].api_id,)
        assert found.reasons == ("needs_two_active_stops", "stops_missing_meeting_evidence")
        assert [n["check"] for n in service.production_invariant_notices(db)] == ["geo.q47"]
    dirty = run_check(pg_db)
    assert dirty.returncode == 1 and fx.corridor.api_id in dirty.stdout and '"needs_two_active_stops"' in dirty.stdout

    # Runbook: active -> pilot -> internal (allowed although violating), fix stops, pilot -> active again.
    with pg_db.session() as db:
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version, reason="Q47 repair", changes={"rollout_state": "pilot"})
        db.commit()
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version, reason="Q47 repair", changes={"rollout_state": "internal"})
        db.commit()
        qarshi = service.get_stop(db, keep)
        service.patch_stop(db, actor_user_id=admin, stop_api_id=qarshi.api_id, expected_version=qarshi.version, changes={"meeting_note": "Avtovokzal kirishi"})
        samarqand = fx.stops["samarqand"]
        service.patch_stop(db, actor_user_id=admin, stop_api_id=samarqand.api_id, expected_version=samarqand.version, changes={"is_active": True})
        db.commit()
        with pytest.raises(DomainError):  # activate is still checked (pilot -> active)
            service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version, reason="x", changes={"rollout_state": "active"})
        db.rollback()
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version, reason="repaired", changes={"rollout_state": "pilot"})
        db.commit()
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version, reason="repaired", changes={"rollout_state": "active"})
        db.commit()
        assert corridor.rollout_state.value == "active" and service.find_q47_violations(db) == []
    assert run_check(pg_db).returncode == 0


# --- readiness notices (Q57 style) and the geo invariant scan job (A10a wiring) -----------------------------


def use_routing_provider(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    from app.modules.geo import config as geo_config

    configured = geo_config.GeoSettings(routing_provider=provider)
    monkeypatch.setattr(geo_config, "get_geo_settings", lambda: configured)


def break_q47(pg_db: PgDatabase, fx, admin: int) -> None:  # noqa: ANN001
    with pg_db.session() as db:
        service.patch_corridor(db, actor_user_id=admin, corridor_api_id=fx.corridor.api_id, expected_version=fx.corridor.version, reason="go", changes={"rollout_state": "active"})
        db.commit()
    keep = fx.stop_id("qarshi")
    with pg_db.engine.begin() as conn:  # legacy/bypassed data, guards off for this transaction only
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE corridor_stops SET is_active = false WHERE corridor_id = :c AND id <> :keep"), {"c": fx.corridor.id, "keep": keep})


def test_readiness_notices_are_names_only(geo, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = geo
    use_routing_provider(monkeypatch, "fake")
    with pg_db.session() as db:
        assert service.readiness_notices(db) == []
    use_routing_provider(monkeypatch, "disabled")
    with pg_db.session() as db:
        assert service.readiness_notices(db) == ["routing_provider_disabled"]

    use_routing_provider(monkeypatch, "fake")
    break_q47(pg_db, fx, admin)
    with pg_db.session() as db:
        assert service.readiness_notices(db) == ["q47_violations_present"]

    with pg_db.session() as db:  # enabled before production without an approval reference (Q5 row)
        set_flag(db, admin, FeatureFlagKey.PASSENGER_ENABLED, True)
        db.commit()
    monkeypatch.setattr(settings, "environment", "production")  # production: no routing provider (Q46)
    with pg_db.session() as db:
        assert service.readiness_notices(db) == ["q47_violations_present", "production_flag_violations_present", "routing_provider_disabled"]


def test_readiness_notices_survive_a_failing_check(geo, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, _, _, _ = geo
    use_routing_provider(monkeypatch, "disabled")

    def broken(db):  # noqa: ANN001, ANN202
        db.execute(text("SELECT * FROM geo_no_such_table"))

    monkeypatch.setattr(service, "find_q47_violations", broken)
    with pg_db.session() as db:
        assert service.readiness_notices(db) == ["geo_readiness_check_error", "routing_provider_disabled"]
        assert db.scalar(text("SELECT 1")) == 1  # the caller's transaction is still usable


def test_geo_invariant_scan_job(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = geo
    assert jobs.run_geo_invariant_scan(engine=pg_db.engine) == 0
    break_q47(pg_db, fx, admin)
    assert jobs.geo_invariant_scan_task(engine=pg_db.engine) == 1
    with pg_db.engine.connect() as conn:  # another replica holds the lock: skipped, not queued
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": advisory_lock_key(jobs.GEO_INVARIANT_SCAN_LOCK_KEY)})
        try:
            assert jobs.geo_invariant_scan_task(engine=pg_db.engine) == 0
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": advisory_lock_key(jobs.GEO_INVARIANT_SCAN_LOCK_KEY)})


def test_db_still_blocks_entering_pilot_while_violating(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = geo
    with pg_db.session() as db:
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=fx.corridor.api_id, expected_version=fx.corridor.version, reason="x", changes={"rollout_state": "internal"})
        db.commit()
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE corridor_stops SET meeting_note = NULL WHERE id = :id"), {"id": fx.stop_id("qarshi")})  # internal: allowed
    with pytest.raises(DBAPIError, match="meeting note or photo"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE service_corridors SET rollout_state = 'pilot', version = version + 1 WHERE id = :id"), {"id": corridor.id})
