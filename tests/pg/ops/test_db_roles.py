"""Decision 36: separate owner/migration and app roles on real PostgreSQL + PostGIS.

Proves: the whole migration chain runs as the non-superuser owner; the app role gets DML
(also on tables created later, via default privileges) but cannot bypass DB-level
invariants (DISABLE TRIGGER, session_replication_role, COPY PROGRAM, TRUNCATE, DDL,
alembic_version / platform_environment writes). Re-running the bootstrap is a no-op.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import errors, sql
from sqlalchemy.engine import URL

from tests.pg.conftest import PgDatabase, PgServer, _libpq_dsn, run_alembic, script_heads

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_db_roles():
    import sys

    spec = importlib.util.spec_from_file_location("elchi_db_roles", REPO_ROOT / "scripts" / "db_roles.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve the defining module through sys.modules
    spec.loader.exec_module(module)
    return module


db_roles = _load_db_roles()


@dataclass(frozen=True)
class Roles:
    owner: str
    owner_password: str
    app: str
    app_password: str


@pytest.fixture
def roles(pg_server: PgServer) -> Iterator[Roles]:
    """Requested BEFORE the database fixture so its teardown runs after the DB is dropped."""
    suffix = uuid.uuid4().hex[:10]
    value = Roles(f"elchi_pgtest_owner_{suffix}", uuid.uuid4().hex, f"elchi_pgtest_app_{suffix}", uuid.uuid4().hex)
    yield value
    with pg_server.admin_connect() as conn:
        for role in (value.app, value.owner):
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def _plan(db: PgDatabase, roles: Roles) -> object:
    return db_roles.RolePlan(
        database=db.name, owner=roles.owner, owner_password=roles.owner_password,
        app=roles.app, app_password=roles.app_password,
    )


def _as(db: PgDatabase, user: str, password: str) -> URL:
    return db.url.set(username=user, password=password)


def _connect(url: URL) -> psycopg.Connection:
    return psycopg.connect(_libpq_dsn(url), autocommit=True)


def test_owner_migrates_whole_chain_and_app_role_cannot_bypass_invariants(roles: Roles, pg_empty_db: PgDatabase) -> None:
    admin_dsn = _libpq_dsn(pg_empty_db.url)
    db_roles.bootstrap(admin_dsn, _plan(pg_empty_db, roles))

    # 1. Migrations as the non-superuser owner (0030/0038 find the extensions pre-created).
    owner_url = _as(pg_empty_db, roles.owner, roles.owner_password)
    result = run_alembic(owner_url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    with _connect(owner_url) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == script_heads()[0]
        assert conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone() == (False, False)
        owners = conn.execute(
            "SELECT DISTINCT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND c.relname <> 'spatial_ref_sys'"
        ).fetchall()
        assert owners == [(roles.owner,)]

    # 2. Bootstrap again after migrations: converges, no errors, nothing left to reassign.
    assert db_roles.bootstrap(admin_dsn, _plan(pg_empty_db, roles)) == []

    app_url = _as(pg_empty_db, roles.app, roles.app_password)
    with _connect(app_url) as conn:
        assert conn.execute("SELECT rolsuper, rolbypassrls, rolinherit FROM pg_roles WHERE rolname = current_user").fetchone() == (
            False, False, False,
        )
        # DML works, including an identity sequence and a v2 table.
        conn.execute("INSERT INTO audit_logs (entity_type, action) VALUES ('roles-test', 'created')")
        assert conn.execute("SELECT count(*) FROM audit_logs WHERE entity_type = 'roles-test'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM platform_environment").fetchone()[0] >= 0
        # Immutable audit log: the app role is refused by privilege (append-only class) before the trigger.
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("UPDATE audit_logs SET action = 'tampered' WHERE entity_type = 'roles-test'")

        forbidden = {
            "disable trigger": "ALTER TABLE audit_logs DISABLE TRIGGER ALL",
            "session_replication_role": "SET session_replication_role = replica",
            "copy program": "COPY (SELECT 1) TO PROGRAM 'true'",
            "truncate": "TRUNCATE audit_logs",
            "ddl in public": "CREATE TABLE app_role_probe (id int)",
            "alembic_version write": "UPDATE alembic_version SET version_num = version_num",
            "platform_environment write": "DELETE FROM platform_environment",
            "create role": "CREATE ROLE app_role_escalation",
            "grant to self": f"GRANT {roles.owner} TO {roles.app}",
        }
        refused = {}
        for label, statement in forbidden.items():
            try:
                conn.execute(statement)
                refused[label] = "EXECUTED"
            except (errors.InsufficientPrivilege, errors.WrongObjectType) as exc:
                refused[label] = type(exc).__name__
        assert "EXECUTED" not in refused.values(), refused

    # 3. A table created by a later migration (as owner) is usable by the app via default privileges.
    with _connect(owner_url) as conn:
        conn.execute("CREATE TABLE future_feature (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text)")
    with _connect(app_url) as conn:
        conn.execute("INSERT INTO future_feature (note) VALUES ('ok')")
        assert conn.execute("SELECT count(*) FROM future_feature").fetchone()[0] == 1
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("TRUNCATE future_feature")


def _migrated_with_roles(db: PgDatabase, roles: Roles) -> tuple[URL, URL]:
    db_roles.bootstrap(_libpq_dsn(db.url), _plan(db, roles))
    owner_url = _as(db, roles.owner, roles.owner_password)
    result = run_alembic(owner_url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    db_roles.bootstrap(_libpq_dsn(db.url), _plan(db, roles))  # post-migration run, as deploy.sh does
    return owner_url, _as(db, roles.app, roles.app_password)


def test_session_guard_cannot_be_flipped_by_the_app_role(roles: Roles, pg_empty_db: PgDatabase) -> None:
    """BR wave 1.6 N1: `SET elchi.ledger_balance_writer = 'on'` must not let the app role write balances."""
    _, app_url = _migrated_with_roles(pg_empty_db, roles)
    with _connect(app_url) as conn:
        conn.execute("SET elchi.ledger_balance_writer = 'on'")
        assert conn.execute("SELECT current_setting('elchi.ledger_balance_writer')").fetchone()[0] == "on"
        for statement in (
            "UPDATE ledger_account_balances SET balance_minor = balance_minor + 1000000",
            "INSERT INTO ledger_account_balances (account_id, balance_minor) VALUES (1, 1000000)",
            "DELETE FROM ledger_account_balances",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(statement)


def test_every_session_or_depth_guarded_table_is_read_only_for_the_app_role(roles: Roles, pg_empty_db: PgDatabase) -> None:
    owner_url, app_url = _migrated_with_roles(pg_empty_db, roles)
    with _connect(owner_url) as conn:
        guarded = db_roles.guarded_tables(conn)
    assert "ledger_account_balances" in guarded, guarded
    app_marker = set(db_roles.RolePlan("d", "o", "p", "a", "p").app_marker_tables)
    assert app_marker == {"bookings", "booking_amendments", "feature_flag_values"}, app_marker
    read_only = [table for table in guarded if table not in app_marker]
    with _connect(app_url) as conn:
        # Wave 2.1: app-marker guards (0056 Q60, 0057 Q72) keep the app role as the legitimate writer.
        for table in sorted(app_marker & set(guarded)):
            assert conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT'), has_table_privilege(current_user, %s, 'UPDATE')",
                (table, table),
            ).fetchone() == (True, True), table
        for table in read_only:
            privileges = conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT'), has_table_privilege(current_user, %s, 'UPDATE'),"
                " has_table_privilege(current_user, %s, 'DELETE'), has_table_privilege(current_user, %s, 'SELECT')",
                (table, table, table, table),
            ).fetchone()
            assert privileges == (False, False, False, True), (table, privileges)
            conn.execute("SELECT set_config('elchi.ledger_balance_writer', 'on', false)")
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        # Append-only and no-delete classes (mirror of A3's 0042 list).
        for table in db_roles.DEFAULT_APPEND_ONLY_TABLES:
            assert conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT'), has_table_privilege(current_user, %s, 'UPDATE'),"
                " has_table_privilege(current_user, %s, 'DELETE')", (table, table, table),
            ).fetchone() == (True, False, False), table
        for table in db_roles.DEFAULT_NO_DELETE_TABLES:
            assert conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'UPDATE'), has_table_privilege(current_user, %s, 'DELETE')",
                (table, table),
            ).fetchone() == (True, False), table
        for table in ("platform_environment", "platform_environment_history", "alembic_version"):
            assert conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT') OR has_table_privilege(current_user, %s, 'UPDATE')"
                " OR has_table_privilege(current_user, %s, 'DELETE')", (table, table, table),
            ).fetchone()[0] is False, table


def test_wave3_grant_classes_partitions_and_function_execute(roles: Roles, pg_empty_db: PgDatabase) -> None:
    """Wave 3.1 (A10a follow-up): append-only / no-update / no-delete classes of the wave 2.1 and wave 3 tables,
    the partitions of tracking_points and EXECUTE on A6's SECURITY DEFINER partition functions."""
    _, app_url = _migrated_with_roles(pg_empty_db, roles)
    plan = db_roles.RolePlan("d", "o", "p", "a", "q")
    assert {"booking_status_history", "dispute_evidence", "contact_strikes", "contact_filter_hits",
            "tracking_points"} <= set(plan.append_only_tables)
    assert plan.no_update_tables == ("tracking_point_receipts",)
    assert {"chat_messages", "disputes_v2", "tracking_sessions"} <= set(plan.no_delete_tables)

    with _connect(app_url) as conn:
        def privileges(table: str) -> tuple[bool, bool, bool]:
            return conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT'), has_table_privilege(current_user, %s, 'UPDATE'),"
                " has_table_privilege(current_user, %s, 'DELETE')", (table, table, table),
            ).fetchone()

        # the retention job deletes receipts, so DELETE stays; nothing updates them
        assert privileges("tracking_point_receipts") == (True, False, True)
        # chat moderation updates a message, nothing deletes one (0059 guard verified, wave 3.1)
        assert privileges("chat_messages") == (True, True, False)
        # every existing partition of an append-only partitioned table is revoked with its parent
        for partition in ("tracking_points_default", *(
            row[0] for row in conn.execute(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                "WHERE i.inhparent = 'public.tracking_points'::regclass"
            ).fetchall()
        )):
            assert privileges(partition) == (True, False, False), partition
        # A6's SECURITY DEFINER functions: revoked from PUBLIC by 0058, granted to the app role by db_roles
        for signature in db_roles.DEFAULT_APP_EXECUTE_FUNCTIONS:
            assert conn.execute("SELECT has_function_privilege(current_user, %s, 'EXECUTE')", (signature,)).fetchone()[0] is True
        assert conn.execute(
            "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
            ("public.tracking_points_apply_parent_acl(TEXT)",),
        ).fetchone()[0] is False, "0063 helper is owner-only"

    # A partition created afterwards by the SECURITY DEFINER function inherits the revoked parent ACL (0063).
    with _connect(app_url) as conn:
        conn.execute("SELECT public.tracking_ensure_point_partition((now() AT TIME ZONE 'UTC')::date + 7)")
        fresh = conn.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = 'public.tracking_points'::regclass ORDER BY c.relname DESC LIMIT 1"
        ).fetchone()[0]
        assert conn.execute(
            "SELECT has_table_privilege(current_user, %s, 'INSERT'), has_table_privilege(current_user, %s, 'UPDATE'),"
            " has_table_privilege(current_user, %s, 'DELETE')", (fresh, fresh, fresh),
        ).fetchone() == (True, False, False), fresh


def test_balance_writer_chain_runs_with_owner_privileges(roles: Roles, pg_empty_db: PgDatabase) -> None:
    """The app role cannot write ledger_account_balances itself; the ledger trigger chain that does is
    SECURITY DEFINER and owned by the owner role, so it keeps working for app-role postings.

    A full app-role posting is not built here: since 0047/0052 a ledger transaction needs a valid
    source link (top-up/booking/adjustment rows), which A3's wallet PG suite exercises end to end.
    """
    owner_url, app_url = _migrated_with_roles(pg_empty_db, roles)
    with _connect(owner_url) as conn:
        writers = conn.execute(
            "SELECT DISTINCT p.proname, p.prosecdef, pg_get_userbyid(p.proowner) FROM pg_trigger t"
            " JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_class c ON c.oid = t.tgrelid"
            " WHERE c.relname = 'ledger_entries' AND NOT t.tgisinternal"
            " AND pg_get_functiondef(p.oid) ~* '(insert\\s+into|update)\\s+(public\\.)?ledger_account_balances'"
        ).fetchall()
    assert writers, "no trigger on ledger_entries writes ledger_account_balances"
    for name, secdef, owner in writers:
        assert secdef is True, (name, "must be SECURITY DEFINER")
        assert owner == roles.owner, (name, owner)
    with _connect(app_url) as conn:
        assert conn.execute("SELECT has_table_privilege(current_user, 'ledger_entries', 'INSERT')").fetchone()[0] is True
        assert conn.execute(
            "SELECT has_table_privilege(current_user, 'ledger_account_balances', 'UPDATE')"
        ).fetchone()[0] is False


def test_detected_guarded_tables_match_the_committed_expected_list(roles: Roles, pg_empty_db: PgDatabase) -> None:
    """NEW-5: the migrated schema's guarded tables equal scripts/db_roles.expected-guarded-tables.txt."""
    owner_url, _ = _migrated_with_roles(pg_empty_db, roles)
    expected = db_roles.read_expected_guarded(str(REPO_ROOT / "scripts" / "db_roles.expected-guarded-tables.txt"))
    with _connect(owner_url) as conn:
        detected = db_roles.guarded_tables(conn)
    assert db_roles.compare_guarded(detected, expected) is None, (detected, expected)
    problem = db_roles.compare_guarded([*detected, "wallet_accounts"], expected)
    assert problem is not None and "unexpected ['wallet_accounts']" in problem
    assert "'ledger_account_balances'" in (db_roles.compare_guarded([], expected) or "")
    classes = db_roles.read_guard_classes(REPO_ROOT / "scripts" / "db_roles.expected-guarded-tables.txt")
    assert classes == {
        "ledger_account_balances": "read-only",
        "bookings": "app-marker",
        "booking_amendments": "app-marker",
        "feature_flag_values": "app-marker",
    }
    # 0054/0055 guards read no session state: correctly not detected (not bypassable by SET).
    assert not {"trip_stop_occurrences", "trip_segment_resources", "topup_requests", "ledger_adjustment_requests"} & set(detected)


def test_detector_follows_a_session_check_moved_into_a_helper(roles: Roles, pg_empty_db: PgDatabase) -> None:
    """Wave 3.1 closes follow-up (c): a guard whose current_setting() sits in a helper is detected as well, and a
    function name that only appears inside a string literal is not mistaken for a call."""
    owner_url, _ = _migrated_with_roles(pg_empty_db, roles)
    with _connect(owner_url) as conn:
        conn.execute("CREATE TABLE hidden_guard_probe (id int)")
        conn.execute(
            "CREATE FUNCTION hidden_guard_helper() RETURNS boolean LANGUAGE plpgsql AS "
            "$$ BEGIN RETURN current_setting('elchi.probe', true) = 'on'; END; $$"
        )
        conn.execute(
            "CREATE FUNCTION hidden_guard_trigger() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN IF NOT hidden_guard_helper() THEN RAISE EXCEPTION 'no'; END IF; RETURN NEW; END; $$"
        )
        conn.execute("CREATE TRIGGER trg_hidden_guard BEFORE UPDATE ON hidden_guard_probe "
                     "FOR EACH ROW EXECUTE FUNCTION hidden_guard_trigger()")
        # only names the helper in a string literal: not a call, so this table stays unguarded
        conn.execute("CREATE TABLE literal_mention_probe (id int)")
        conn.execute(
            "CREATE FUNCTION literal_mention_trigger() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN PERFORM 1 FROM pg_proc WHERE proname = 'hidden_guard_helper'; RETURN NEW; END; $$"
        )
        conn.execute("CREATE TRIGGER trg_literal_mention BEFORE UPDATE ON literal_mention_probe "
                     "FOR EACH ROW EXECUTE FUNCTION literal_mention_trigger()")
        detected = db_roles.guarded_tables(conn)
    assert "hidden_guard_probe" in detected
    assert "literal_mention_probe" not in detected


def test_guard_classes_file_format(tmp_path: Path) -> None:
    good = tmp_path / "ok.txt"
    good.write_text("# c\nledger_account_balances\nbookings app-marker  # why\n\nx read-only\n", encoding="utf-8")
    assert db_roles.read_guard_classes(good) == {"ledger_account_balances": "read-only", "bookings": "app-marker", "x": "read-only"}
    assert db_roles.read_expected_guarded(str(good)) == ["ledger_account_balances", "bookings", "x"]
    bad = tmp_path / "bad.txt"
    bad.write_text("bookings writable\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        db_roles.read_guard_classes(bad)


def test_bootstrap_takes_over_objects_of_a_restored_superuser_owned_database(roles: Roles, pg_db: PgDatabase) -> None:
    """A restored v1 dump is owned by POSTGRES_USER (superuser): ownership moves to the owner role."""
    admin_dsn = _libpq_dsn(pg_db.url)
    changed = db_roles.bootstrap(admin_dsn, _plan(pg_db, roles))
    assert any(statement.startswith("ALTER TABLE public.users OWNER TO") for statement in changed), changed[:5]
    assert db_roles.bootstrap(admin_dsn, _plan(pg_db, roles)) == []
    with _connect(_as(pg_db, roles.app, roles.app_password)) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] >= 0
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("ALTER TABLE users DISABLE TRIGGER ALL")


def test_non_superuser_admin_is_refused(roles: Roles, pg_db: PgDatabase) -> None:
    db_roles.bootstrap(_libpq_dsn(pg_db.url), _plan(pg_db, roles))
    with pytest.raises(SystemExit, match="superuser"):
        db_roles.bootstrap(_libpq_dsn(_as(pg_db, roles.owner, roles.owner_password)), _plan(pg_db, roles))
