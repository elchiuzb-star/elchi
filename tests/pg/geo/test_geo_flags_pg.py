"""Feature flags on PostgreSQL: uniqueness, history trigger, append-only, Q1/Q5 rules, concurrency (ADR-0008, AC38 core).

Production is detected only through ``platform.service.is_production`` (settings OR DB marker, BR #5):
tests flip the DB marker or ``settings.environment``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.contracts.enums import STAFF_ROLE_CAPABILITIES, FeatureFlagKey, FlagScopeType, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import new_public_uuid
from app.core.config import settings
from app.modules.geo import service
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user, set_q48_gate, set_support_phone
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg

ADMIN_CAPS = STAFF_ROLE_CAPABILITIES[Role.ADMIN]
SUPER_CAPS = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]


@pytest.fixture
def env(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    super_admin = create_user(pg_db, "super_admin")
    with pg_db.session() as db:
        fixture = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
    return pg_db, fixture, admin, super_admin


def mark_production(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))


def set_flag(db, actor: int, key: FeatureFlagKey, scope: FlagScopeType, ref: str, enabled: bool, *, super_admin: bool = False, **kw):  # noqa: ANN001, ANN003, ANN201
    return service.set_flag_value(
        db,
        actor_user_id=actor,
        actor_capabilities=SUPER_CAPS if super_admin else ADMIN_CAPS,
        actor_is_super_admin=super_admin,
        flag_key=key,
        scope_type=scope,
        scope_ref=ref,
        enabled=enabled,
        reason=kw.pop("reason", "test"),
        **kw,
    )


def test_flag_scope_is_unique(env) -> None:  # noqa: ANN001
    pg_db, _, admin, _ = env
    insert = text(
        "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
        "VALUES (:p, 'parcel_enabled', 'country', 'UZ', true, 'r', :u)"
    )
    with pg_db.engine.begin() as conn:
        service.mark_flag_change_source(conn)  # Q72: raw enable of a v2 flag needs the app marker
        conn.execute(insert, {"p": new_public_uuid(), "u": admin})
    with pytest.raises(IntegrityError, match="uq_feature_flag_values_key_scope"):
        with pg_db.engine.begin() as conn:
            service.mark_flag_change_source(conn)
            conn.execute(insert, {"p": new_public_uuid(), "u": admin})
    for bad in (
        "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) VALUES (:p, 'legacy_writes_enabled', 'country', 'UZ', true, 'r', :u)",
        "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) VALUES (:p, 'parcel_enabled', 'country', 'KZ', true, 'r', :u)",
    ):
        with pytest.raises(IntegrityError, match="ck_feature_flag_values"):
            with pg_db.engine.begin() as conn:
                service.mark_flag_change_source(conn)
                conn.execute(text(bad), {"p": new_public_uuid(), "u": admin})


def test_history_trigger_records_every_write_with_actor_and_reason(env) -> None:  # noqa: ANN001
    pg_db, fx, admin, super_admin = env
    with pg_db.session() as db:
        first = set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, FlagScopeType.CORRIDOR, fx.corridor.api_id, True, reason="pilot start")
        second = set_flag(db, super_admin, FeatureFlagKey.PARCEL_ENABLED, FlagScopeType.CORRIDOR, fx.corridor.api_id, False, super_admin=True, expected_version=1, reason="incident", approval_reference="INC-9")
        db.commit()
    assert (first.version, second.version) == (1, 2)
    with pg_db.engine.begin() as conn:
        service.mark_flag_change_source(conn)  # Q72
        conn.execute(
            text("UPDATE feature_flag_values SET enabled = true, reason = 'sql fix', approval_reference = NULL, updated_by = :u, version = version + 1 WHERE id = :id"),
            {"u": admin, "id": first.id},
        )
        rows = conn.execute(
            text("SELECT value_version, old_enabled, new_enabled, actor_user_id, reason, approval_reference FROM feature_flag_changes WHERE flag_value_id = :id ORDER BY value_version"),
            {"id": first.id},
        ).all()
        audit = conn.scalar(text("SELECT count(*) FROM audit_logs WHERE entity_type = 'feature_flag_value' AND entity_id = :id"), {"id": first.id})
    assert rows == [
        (1, None, True, admin, "pilot start", None),
        (2, True, False, super_admin, "incident", "INC-9"),
        (3, False, True, admin, "sql fix", None),
    ]
    assert audit == 2
    with pytest.raises(DBAPIError, match="exactly 1"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE feature_flag_values SET enabled = false WHERE id = :id"), {"id": first.id})
    with pytest.raises(DBAPIError, match="immutable"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE feature_flag_values SET scope_ref = 'UZ', version = version + 1 WHERE id = :id"), {"id": first.id})


def test_history_is_append_only_and_values_are_not_deleted(env) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = env
    with pg_db.session() as db:
        value = set_flag(db, admin, FeatureFlagKey.TRACKING_ENABLED, FlagScopeType.COUNTRY, "UZ", False)
        db.commit()
    for statement, message in (
        ("UPDATE feature_flag_changes SET reason = 'rewritten' WHERE flag_value_id = :id", "append-only"),
        ("DELETE FROM feature_flag_changes WHERE flag_value_id = :id", "append-only"),
        ("TRUNCATE feature_flag_changes CASCADE", "append-only"),
        ("DELETE FROM feature_flag_values WHERE id = :id", "cannot be deleted"),
    ):
        with pytest.raises(DBAPIError, match=message):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": value.id})


def test_q5_passenger_enable_in_production_needs_super_admin_and_approval_reference(env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, super_admin = env
    corridor = fx.corridor.api_id
    mark_production(pg_db)  # DB marker only; settings stay "development" (fail closed: either counts)
    set_q48_gate(pg_db, monkeypatch, passed=True)  # Q56 gate open; this test is about Q5
    set_support_phone(monkeypatch)  # Q87 precondition (its own refusal is covered in test_push_support_hardening_pg)
    with pg_db.session() as db:
        with pytest.raises(DomainError) as by_admin:
            set_flag(db, admin, FeatureFlagKey.PASSENGER_ENABLED, FlagScopeType.CORRIDOR, corridor, True, approval_reference="LEGAL-1")
        assert by_admin.value.code is ErrorCode.FORBIDDEN
        with pytest.raises(DomainError) as no_ref:
            set_flag(db, super_admin, FeatureFlagKey.PASSENGER_ENABLED, FlagScopeType.CORRIDOR, corridor, True, super_admin=True)
        assert no_ref.value.code is ErrorCode.APPROVAL_REFERENCE_REQUIRED
        db.rollback()
        assert service.list_flag_values(db, flag_key=FeatureFlagKey.PASSENGER_ENABLED) == []
        assert service.is_flag_enabled(db, FeatureFlagKey.PASSENGER_ENABLED, corridor_id=fx.corridor.id) is False

        enabled = set_flag(db, super_admin, FeatureFlagKey.PASSENGER_ENABLED, FlagScopeType.CORRIDOR, corridor, True, super_admin=True, approval_reference="LEGAL-1")
        db.commit()
        assert enabled.approval_reference == "LEGAL-1"
        assert service.is_flag_enabled(db, FeatureFlagKey.PASSENGER_ENABLED, corridor_id=fx.corridor.id) is True
        set_flag(db, admin, FeatureFlagKey.PASSENGER_ENABLED, FlagScopeType.CORRIDOR, corridor, False, expected_version=1)
        db.commit()
        assert service.is_flag_enabled(db, FeatureFlagKey.PASSENGER_ENABLED, corridor_id=fx.corridor.id) is False


def test_q1_wallet_required_locked_in_production(env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, super_admin = env
    with pg_db.session() as db:
        set_flag(db, admin, FeatureFlagKey.WALLET_REQUIRED, FlagScopeType.CORRIDOR, fx.corridor.api_id, False)
        db.commit()
        assert service.is_flag_enabled(db, FeatureFlagKey.WALLET_REQUIRED, corridor_id=fx.corridor.id) is False
        assert service.production_flag_violations(db) == []
    # The DB refuses to become production while such a row exists (A3 marker guard).
    with pytest.raises(DBAPIError, match="wallet_required"):
        mark_production(pg_db)

    monkeypatch.setattr(settings, "environment", "production")  # settings side of the fail-closed check
    with pg_db.session() as db:
        assert service.is_flag_enabled(db, FeatureFlagKey.WALLET_REQUIRED, corridor_id=fx.corridor.id) is True
        assert service.snapshot_flags(db, corridor_id=fx.corridor.id)["wallet_required"] is True
        assert service.production_flag_violations(db) == [
            {"flag_key": "wallet_required", "scope_type": "corridor", "scope_ref": fx.corridor.api_id, "enabled": False, "rule": "locked_value"}
        ]
        with pytest.raises(DomainError) as locked:
            set_flag(db, super_admin, FeatureFlagKey.WALLET_REQUIRED, FlagScopeType.COUNTRY, "UZ", False, super_admin=True, approval_reference="X")
        assert locked.value.code is ErrorCode.FLAG_LOCKED_IN_ENVIRONMENT


def test_approval_violation_is_reported_when_row_predates_production(env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = env
    with pg_db.session() as db:
        set_flag(db, admin, FeatureFlagKey.PASSENGER_ENABLED, FlagScopeType.COUNTRY, "UZ", True)
        db.commit()
    monkeypatch.setattr(settings, "environment", "production")
    with pg_db.session() as db:
        assert service.production_flag_violations(db) == [
            {"flag_key": "passenger_enabled", "scope_type": "country", "scope_ref": "UZ", "enabled": True, "rule": "approval_reference_required"}
        ]


def test_scope_precedence_with_database_rows(env) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = env
    key = FeatureFlagKey.DRIVER_LISTING_ENABLED
    with pg_db.session() as db:
        def value(**kw) -> bool:  # noqa: ANN003
            return service.is_flag_enabled(db, key, corridor_id=fx.corridor.id, **kw)

        assert value() is False
        set_flag(db, admin, key, FlagScopeType.COUNTRY, "UZ", True)
        assert value() is True
        set_flag(db, admin, key, FlagScopeType.REGION, "UZ-QA", False)
        assert value() is False
        set_flag(db, admin, key, FlagScopeType.CORRIDOR, fx.corridor.api_id, True)
        assert value() is True
        set_flag(db, admin, key, FlagScopeType.COHORT, "internal-testers", False)
        assert value(cohorts=["internal-testers"]) is False and value() is True
        assert service.is_flag_enabled(db, key) is True
        # Decision 26: conflicting rows on one level resolve to off.
        set_flag(db, admin, key, FlagScopeType.REGION, "UZ-TK", True)
        set_flag(db, admin, key, FlagScopeType.CORRIDOR, fx.corridor.api_id, False, expected_version=1)
        assert service.is_flag_enabled(db, key, region_codes=["UZ-TK", "UZ-QA"]) is False
        db.commit()


def test_version_conflicts(env) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = env
    key, scope, ref = FeatureFlagKey.TRACKING_ENABLED, FlagScopeType.REGION, "UZ-TK"
    with pg_db.session() as db:
        with pytest.raises(DomainError) as new_with_version:
            set_flag(db, admin, key, scope, ref, True, expected_version=1)
        assert new_with_version.value.code is ErrorCode.VERSION_CONFLICT
        db.rollback()
        set_flag(db, admin, key, scope, ref, True)
        db.commit()
        for expected in (None, 2):
            with pytest.raises(DomainError) as stale:
                set_flag(db, admin, key, scope, ref, False, expected_version=expected)
            assert stale.value.code is ErrorCode.VERSION_CONFLICT and stale.value.details["current_version"] == 1
            db.rollback()
        with pytest.raises(DomainError) as unknown_region:
            set_flag(db, admin, key, scope, "UZ-XX", True)
        assert unknown_region.value.code is ErrorCode.NOT_FOUND


def test_concurrent_first_write_creates_exactly_one_value(env) -> None:  # noqa: ANN001
    pg_db, fx, admin, _ = env

    def write(worker: int, session) -> int:  # noqa: ANN001
        info = set_flag(session, admin, FeatureFlagKey.PARCEL_ENABLED, FlagScopeType.COHORT, "drivers-wave-1", worker % 2 == 0, reason=f"worker {worker}")
        session.commit()
        return info.id

    report = run_concurrently(12, write, engine=pg_db.engine)
    assert len(report.successes) == 1
    conflicts = report.errors_of(DomainError)
    assert len(conflicts) == 11 and all(r.error.code is ErrorCode.VERSION_CONFLICT for r in conflicts)
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM feature_flag_values WHERE scope_ref = 'drivers-wave-1'")) == 1
        assert conn.scalar(text("SELECT count(*) FROM feature_flag_changes WHERE scope_ref = 'drivers-wave-1'")) == 1


# --- Q72: enabling a v2 service flag only through the application/admin API path (0057) ---------------------

RAW_FLAG_INSERT = text(
    "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
    "VALUES (:p, :k, :s, :ref, :e, 'psql', :u)"
)


def assert_source_refused(fn) -> None:  # noqa: ANN001
    with pytest.raises(DBAPIError) as info:
        fn()
    assert info.value.orig.sqlstate == "42501"
    assert info.value.orig.diag.constraint_name == "flag_enable_source_refused"


def raw_insert(pg_db: PgDatabase, key: str, ref: str, enabled: bool, actor: int, *, marked: bool = False, scope: str = "cohort") -> None:
    with pg_db.engine.begin() as conn:
        if marked:
            service.mark_flag_change_source(conn)
        conn.execute(RAW_FLAG_INSERT, {"p": new_public_uuid(), "k": key, "s": scope, "ref": ref, "e": enabled, "u": actor})


def test_q72_raw_sql_enable_needs_the_app_marker(env) -> None:  # noqa: ANN001
    pg_db, _, admin, _ = env
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_feature_flag_values_enable_source' AND NOT tgisinternal")) == 1
    for key in sorted(k.value for k in service.V2_SERVICE_FLAGS):
        assert_source_refused(lambda key=key: raw_insert(pg_db, key, "q72-raw", True, admin))
    raw_insert(pg_db, "parcel_enabled", "q72-off", False, admin)  # inserting OFF needs no marker
    raw_insert(pg_db, "wallet_required", "UZ", True, admin, scope="country")  # not a v2 service flag

    update_on = text("UPDATE feature_flag_values SET enabled = true, version = version + 1 WHERE flag_key = 'parcel_enabled' AND scope_ref = 'q72-off'")
    update_off = text("UPDATE feature_flag_values SET enabled = false, version = version + 1 WHERE flag_key = 'parcel_enabled' AND scope_ref = 'q72-off'")

    def psql_update_on() -> None:
        with pg_db.engine.begin() as conn:
            conn.execute(update_on)

    assert_source_refused(psql_update_on)
    with pg_db.engine.begin() as conn:  # a marker set in a rolled-back savepoint is gone
        nested = conn.begin_nested()
        service.mark_flag_change_source(conn)
        nested.rollback()
        with pytest.raises(DBAPIError, match="flag_enable_source_refused|application flag API"):
            with conn.begin_nested():
                conn.execute(update_on)
    with pg_db.engine.begin() as conn:
        service.mark_flag_change_source(conn)
        conn.execute(update_on)
    assert_source_refused(lambda: raw_insert(pg_db, "tracking_enabled", "q72-next-tx", True, admin))  # marker is transaction-local
    with pg_db.engine.begin() as conn:  # turning OFF is always possible
        conn.execute(update_off)
    raw_insert(pg_db, "tracking_enabled", "q72-marked", True, admin, marked=True)


def test_q72_set_flag_value_marks_only_its_own_write(env) -> None:  # noqa: ANN001
    pg_db, _, admin, _ = env
    with pg_db.session() as db:
        assert set_flag(db, admin, FeatureFlagKey.TRACKING_ENABLED, FlagScopeType.COHORT, "q72-svc", True).enabled
        with pytest.raises(DBAPIError, match="application flag API"):  # a later raw enable in the same transaction
            db.execute(RAW_FLAG_INSERT, {"p": new_public_uuid(), "k": "parcel_enabled", "s": "cohort", "ref": "q72-svc", "e": True, "u": admin})
        db.rollback()
        assert service.list_flag_values(db, flag_key=FeatureFlagKey.TRACKING_ENABLED) == []

        service.mark_flag_change_source(db)  # a caller that marked first keeps its marker
        set_flag(db, admin, FeatureFlagKey.TRACKING_ENABLED, FlagScopeType.COHORT, "q72-svc", True)
        db.execute(RAW_FLAG_INSERT, {"p": new_public_uuid(), "k": "parcel_enabled", "s": "cohort", "ref": "q72-svc", "e": True, "u": admin})
        db.commit()
        assert service.is_flag_enabled(db, FeatureFlagKey.PARCEL_ENABLED, cohorts=["q72-svc"]) is True


def test_q72_marker_not_left_behind_after_caught_version_conflict(env) -> None:  # noqa: ANN001
    """BR L1: a VERSION_CONFLICT caught in the same transaction (no savepoint) leaves no marker behind."""
    pg_db, _, admin, _ = env
    with pg_db.session() as db:
        set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, FlagScopeType.COHORT, "q72-l1", False)
        db.commit()
    raw = {"p": new_public_uuid(), "k": "tracking_enabled", "s": "cohort", "ref": "q72-l1", "e": True, "u": admin}
    with pg_db.session() as db:
        for kwargs in ({}, {"expected_version": 7}):  # existing row: missing and stale version
            with pytest.raises(DomainError) as conflict:
                set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, FlagScopeType.COHORT, "q72-l1", True, **kwargs)
            assert conflict.value.code is ErrorCode.VERSION_CONFLICT
        with pytest.raises(DomainError) as new_row_conflict:  # no row yet but a version was sent
            set_flag(db, admin, FeatureFlagKey.CARD_PAYMENTS_ENABLED, FlagScopeType.COHORT, "q72-l1", True, expected_version=1)
        assert new_row_conflict.value.code is ErrorCode.VERSION_CONFLICT
        assert db.scalar(text("SELECT coalesce(current_setting('elchi.flag_change_source', true), '')")) == ""
        with pytest.raises(DBAPIError, match="application flag API"):
            db.execute(RAW_FLAG_INSERT, raw)
        db.rollback()


def test_flag_writes_touch_only_flag_tables_and_audit(env) -> None:  # noqa: ANN001
    """Flags never rewrite other rows (frozen booking terms live in A4 snapshots, AC38)."""
    pg_db, fx, admin, _ = env
    allowed = {"feature_flag_values", "feature_flag_changes", "audit_logs"}

    def checksums() -> dict[str, str]:
        with pg_db.engine.connect() as conn:
            tables = [name for (name,) in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys' ORDER BY 1"))]
            return {name: conn.scalar(text(f'SELECT md5(coalesce(string_agg(t::text, \'|\' ORDER BY t::text), \'\')) FROM "{name}" t')) for name in tables}

    before = checksums()
    with pg_db.session() as db:
        set_flag(db, admin, FeatureFlagKey.PARCEL_ENABLED, FlagScopeType.COUNTRY, "UZ", True)
        db.commit()
    after = checksums()
    touched = {name for name in before if before[name] != after.get(name)}
    assert touched and touched <= allowed, touched
