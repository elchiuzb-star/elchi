"""Idempotent database role and grant bootstrap (decision 36).

Two login roles, neither superuser:

* **owner** (e.g. ``elchi_owner``): owns schema ``public`` and every application
  object; the one-shot ``migrate`` job connects as this role
  (``ELCHI_MIGRATION_DATABASE_URL``).
* **app** (e.g. ``elchi_app``): NOSUPERUSER NOBYPASSRLS NOINHERIT, only
  SELECT/INSERT/UPDATE/DELETE on tables and USAGE/SELECT on sequences (through
  default privileges also for tables created by future migrations). ``api`` and
  ``worker`` connect as this role (``ELCHI_DATABASE_URL``). Not an owner, so it cannot
  ``ALTER TABLE ... DISABLE TRIGGER``, ``TRUNCATE``, create objects, ``SET
  session_replication_role`` or ``COPY ... PROGRAM``.

Extensions: ``postgis`` is not a trusted extension, so only a superuser can create it.
This script (run as the bootstrap superuser, ``POSTGRES_USER``) creates ``postgis`` and
``btree_gist`` up front; migrations ``0030``/``0038`` then run as the owner and are
no-ops (``CREATE EXTENSION IF NOT EXISTS``). Extension objects stay owned by the
superuser -- PostgreSQL has no supported way to hand an untrusted extension to a
non-superuser.

Table privilege classes for the app role (re-applied on every run, after the blanket DML
grant, so a later run never re-grants them). They mirror A3's list in migration 0042:

* **read-only** (``DEFAULT_READ_ONLY_TABLES``): ``alembic_version``, ``spatial_ref_sys``,
  ``platform_environment``, ``platform_environment_history``, ``ledger_account_balances``.
  Extend with ``--read-only-table``.
* **append-only** (``DEFAULT_APPEND_ONLY_TABLES``, no UPDATE/DELETE): the ledger and audit tables plus, since
  wave 3.1, every table whose DB trigger already refuses both (booking status history and proof attempts/reissues,
  flag and price-band change logs, dispute evidence, contact filter hits and strikes, tracking points). A
  partitioned table in ``PARTITIONED_APPEND_ONLY_TABLES`` is revoked together with its partitions, because a
  session that names a partition directly is checked against the partition's own ACL; partitions created later by
  ``tracking_ensure_point_partition`` copy the parent ACL (migration 0063).
* **read-only views** (``DEFAULT_READ_ONLY_VIEWS``): the wave 5 legacy projection (``legacy_*_v``); the app
  role keeps SELECT and loses INSERT/UPDATE/DELETE (Q4, AC37).
* **no-update** (``DEFAULT_NO_UPDATE_TABLES``): insert-and-expire rows the retention job deletes but nobody
  updates (``tracking_point_receipts``).
* **no-delete** (``DEFAULT_NO_DELETE_TABLES``): commission policies, wallet accounts/holds,
  top-ups, adjustment requests, reconciliation runs; wave 3.1 adds the rows the app updates but must never
  remove (chat messages, tracking sessions/grants, disputes, ratings, support tickets, trust review items).
* **EXECUTE** (``DEFAULT_APP_EXECUTE_FUNCTIONS``): the SECURITY DEFINER tracking-partition functions of 0058,
  which revoked EXECUTE from PUBLIC; the worker calls them as the app role.
* **owner-only** (``DEFAULT_OWNER_ONLY_FUNCTIONS``): SECURITY DEFINER helpers the app role must not call; the
  blanket function grant is taken back for them (0063 partition ACL helper).
* **guarded, detected** (BR wave 1.6 N1): every table with a trigger whose non-SECURITY-DEFINER
  function reads a session setting (``current_setting(...)``) or ``pg_trigger_depth()``. Each detected
  table has a class in ``scripts/db_roles.expected-guarded-tables.txt`` (wave 2.1):

  - ``read-only`` (default, also for a detected table that is not listed -- fail safe): the guard is
    bypassable by any session that can ``SET elchi.<flag> = 'on'`` and the only legitimate writer is a
    SECURITY DEFINER trigger owned by the owner role, so the app role loses INSERT/UPDATE/DELETE
    (``ledger_account_balances``).
  - ``app-marker``: the setting is a transaction marker the APPLICATION itself sets (``SET LOCAL`` /
    ``set_config``), or evidence re-checked against real rows; the app role is the legitimate writer and
    keeps DML (``bookings``/``booking_amendments`` 0056 Q60, ``feature_flag_values`` 0057 Q72). These guards
    stop accidental psql/migration writes, not a deliberate actor holding app-role credentials.

  Wave 3.1: the detector follows calls, so a session check inside a helper the trigger function calls is detected as
  well (matched by function name inside ``prosrc``, recursively). A SECURITY DEFINER *trigger* function is still
  skipped -- it runs with the owner's rights by design.

Superuser connection: pass a local-socket URL (``postgresql://user@/db?host=/var/run/postgresql``);
``docker-compose.prod.yml`` shares only the socket directory with this job and pg_hba rejects
superuser TCP logins.

Extension upgrades (BR N10): ``ALTER EXTENSION postgis UPDATE`` belongs in this superuser step
(``--update-extensions``), never in owner-run migrations, because the owner cannot alter an
extension it does not own.

Usage (secrets only via environment, never argv)::

    ELCHI_DB_ADMIN_URL='postgresql://elchi_admin@/elchi?host=/var/run/postgresql' \\
    ELCHI_DB_OWNER_PASSWORD=... ELCHI_DB_APP_PASSWORD=... \\
    python scripts/db_roles.py --owner elchi_owner --app elchi_app

Re-running is safe: roles are created or altered to the stated attributes, passwords
are reset to the environment values (password rotation), ownership and grants converge.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql

DEFAULT_READ_ONLY_TABLES = (
    "alembic_version",
    # Q50 (0067): the migration graph is written by alembic/env.py as the owner; the app only reads it.
    "alembic_revision_lineage",
    "spatial_ref_sys",
    "platform_environment",
    "platform_environment_history",
    "ledger_account_balances",
)
DEFAULT_APPEND_ONLY_TABLES = (
    "ledger_transactions",
    "ledger_entries",
    "audit_logs",
    # wave 2.1 follow-up (b), completed in wave 3.1: every table whose DB trigger already refuses UPDATE and
    # DELETE loses the privilege as well, so the refusal does not depend on the trigger being present.
    "booking_status_history",  # 0048
    "booking_proof_attempts",  # 0049
    "booking_proof_reissues",  # 0056
    "feature_flag_changes",  # 0033
    "corridor_price_band_changes",  # 0046
    # wave 3 (A12 0060, A6 0058). tracking_points is partitioned: its daily partitions are revoked too
    # (PARTITIONED_APPEND_ONLY_TABLES) and new ones inherit the parent ACL from 0063.
    "dispute_evidence",
    "contact_filter_hits",
    "contact_strikes",
    "tracking_points",
)
# Append-only tables whose partitions must be revoked with them (privileges are checked per partition when a
# session names the partition directly).
PARTITIONED_APPEND_ONLY_TABLES = ("tracking_points",)
# Wave 5 (A10b 0065, Q4): the legacy projection is read-only. A view over a single legacy table would be
# auto-updatable, so the blanket "GRANT ... ON ALL TABLES" (views included) would make it writable; the
# INSTEAD OF triggers of 0065 refuse the write anyway, and this revoke is the second, privilege-level layer.
DEFAULT_READ_ONLY_VIEWS = (
    "legacy_parcel_orders_v",
    "legacy_order_status_history_v",
    "legacy_ratings_v",
    "legacy_disputes_v",
)
# Insert-and-expire tables: the trigger refuses UPDATE, but the A6 retention job (app role) deletes expired rows.
DEFAULT_NO_UPDATE_TABLES = ("tracking_point_receipts",)
DEFAULT_NO_DELETE_TABLES = (
    "commission_policies",
    "wallet_accounts",
    "wallet_holds",
    "topup_requests",
    "ledger_adjustment_requests",
    "reconciliation_runs",
    # wave 3.1: rows the application updates (moderation, status, revocation) but must never delete.
    "chat_messages",  # 0059: content is immutable, moderation columns are not; nothing deletes a message
    "tracking_sessions",  # 0058
    "tracking_grants",  # 0058: a grant is revoked with revoked_at, never removed
    "disputes_v2",  # 0060
    "ratings_v2",  # 0060
    "support_tickets",  # 0060
    "trust_review_items",  # 0060
    "share_links",  # 0064 (wave 4): a link is revoked, never deleted; the open counter only moves forward
)
# SECURITY DEFINER functions the app role (worker) calls: 0058 revokes them from PUBLIC, so the grant is explicit
# here instead of relying on the blanket "GRANT EXECUTE ON ALL FUNCTIONS" (wave 3.1 A10a follow-up).
DEFAULT_APP_EXECUTE_FUNCTIONS = (
    "public.tracking_ensure_point_partition(DATE)",
    "public.tracking_ensure_point_partitions()",
    "public.tracking_drop_expired_point_partitions()",
)
# SECURITY DEFINER helpers only the owner may call: the blanket "GRANT EXECUTE ON ALL FUNCTIONS" above would hand
# them to the app role, so EXECUTE is revoked again (0063 partition ACL helper).
DEFAULT_OWNER_ONLY_FUNCTIONS = ("public.tracking_points_apply_parent_acl(TEXT)",)
EXTENSIONS = ("postgis", "btree_gist")

GUARD_CLASS_READ_ONLY = "read-only"
GUARD_CLASS_APP_MARKER = "app-marker"
GUARD_CLASSES = (GUARD_CLASS_READ_ONLY, GUARD_CLASS_APP_MARKER)
DEFAULT_GUARDED_FILE = Path(__file__).resolve().with_name("db_roles.expected-guarded-tables.txt")


def read_guard_classes(path: str | Path) -> dict[str, str]:
    """``<table> [read-only|app-marker]  # comment`` per line -> {table: class}; class defaults to read-only."""
    classes: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            tokens = raw.split("#", 1)[0].split()
            if not tokens:
                continue
            if len(tokens) > 2 or (len(tokens) == 2 and tokens[1] not in GUARD_CLASSES):
                raise SystemExit(f"db_roles: {path}:{number}: expected '<table> [{'|'.join(GUARD_CLASSES)}]', got {raw.strip()!r}")
            classes[tokens[0]] = tokens[1] if len(tokens) == 2 else GUARD_CLASS_READ_ONLY
    return classes


def _default_app_marker_tables() -> tuple[str, ...]:
    """App-marker tables from the committed list; without the file every detected table stays read-only."""
    if not DEFAULT_GUARDED_FILE.is_file():
        return ()
    return tuple(t for t, cls in read_guard_classes(DEFAULT_GUARDED_FILE).items() if cls == GUARD_CLASS_APP_MARKER)

# Tables whose write guard lives in a non-SECURITY-DEFINER trigger function that trusts a session setting or
# trigger depth: any session could flip the setting, so writes are revoked. Wave 3.1 closes follow-up (c): the
# search now walks function calls, so a session check hidden in a helper the trigger function calls is detected
# too (recursively, by name, within schema public).
GUARDED_TABLES_SQL = r"""
WITH RECURSIVE session_readers AS (
    SELECT p.oid, p.proname
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND (p.prosrc ~* 'current_setting\s*\(' OR p.prosrc ~* 'pg_trigger_depth\s*\(')
    UNION
    SELECT caller.oid, caller.proname
    FROM pg_proc caller
    JOIN pg_namespace n ON n.oid = caller.pronamespace
    JOIN session_readers reader ON caller.oid <> reader.oid
    WHERE n.nspname = 'public'
      AND caller.prosrc ~* ('\m' || reader.proname || '\s*\(')  -- a call, not the name inside a literal
)
SELECT DISTINCT c.relname
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_proc p ON p.oid = t.tgfoid
JOIN session_readers r ON r.oid = p.oid
WHERE n.nspname = 'public'
  AND NOT t.tgisinternal
  AND NOT p.prosecdef
ORDER BY 1
"""


@dataclass(frozen=True)
class RolePlan:
    database: str
    owner: str
    owner_password: str
    app: str
    app_password: str
    read_only_tables: tuple[str, ...] = DEFAULT_READ_ONLY_TABLES
    read_only_views: tuple[str, ...] = DEFAULT_READ_ONLY_VIEWS
    append_only_tables: tuple[str, ...] = DEFAULT_APPEND_ONLY_TABLES
    no_update_tables: tuple[str, ...] = DEFAULT_NO_UPDATE_TABLES
    no_delete_tables: tuple[str, ...] = DEFAULT_NO_DELETE_TABLES
    app_execute_functions: tuple[str, ...] = DEFAULT_APP_EXECUTE_FUNCTIONS
    owner_only_functions: tuple[str, ...] = DEFAULT_OWNER_ONLY_FUNCTIONS
    extensions: tuple[str, ...] = field(default=EXTENSIONS)
    update_extensions: bool = False
    # Detected guarded tables the app role keeps writing (class app-marker in the committed list).
    app_marker_tables: tuple[str, ...] = field(default_factory=_default_app_marker_tables)


def guarded_tables(conn: psycopg.Connection) -> list[str]:
    return [name for (name,) in conn.execute(GUARDED_TABLES_SQL).fetchall()]


def partitions(conn: psycopg.Connection, table: str) -> list[str]:
    """Direct partitions of ``public.<table>`` (privileges are checked per partition when named directly)."""
    if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None:
        return []
    return [
        name
        for (name,) in conn.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE i.inhparent = to_regclass(%s) AND n.nspname = 'public' ORDER BY 1",
            (f"public.{table}",),
        ).fetchall()
    ]


def _ensure_role(cur: psycopg.Cursor, name: str, password: str, attributes: str) -> None:
    exists = cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    cur.execute(
        sql.SQL("{} ROLE {} WITH LOGIN " + attributes + " PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(name), sql.Literal(password)
        )
    )


def apply_cluster(conn: psycopg.Connection, plan: RolePlan) -> None:
    """Roles and database-level privileges (connect to any database of the cluster)."""
    with conn.cursor() as cur:
        _ensure_role(cur, plan.owner, plan.owner_password, "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT")
        _ensure_role(cur, plan.app, plan.app_password, "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT")
        db = sql.Identifier(plan.database)
        cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
        cur.execute(sql.SQL("GRANT CONNECT, TEMPORARY, CREATE ON DATABASE {} TO {}").format(db, sql.Identifier(plan.owner)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, sql.Identifier(plan.app)))


# Literal % is doubled: this string is sent with psycopg parameters.
_REASSIGN_SQL = """
SELECT format('ALTER %%s %%s OWNER TO %%I', kind, ident, %(owner)s)
FROM (
    SELECT CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                          WHEN 'S' THEN 'SEQUENCE' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END AS kind,
           format('%%I.%%I', n.nspname, c.relname) AS ident
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND c.relowner <> (SELECT oid FROM pg_roles WHERE rolname = %(owner)s)
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
      -- sequences owned by a column follow their table
      AND NOT (c.relkind = 'S' AND EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                                           AND d.objid = c.oid AND d.deptype IN ('a', 'i')))
    UNION ALL
    SELECT CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END,
           format('%%I.%%I(%%s)', n.nspname, p.proname, pg_get_function_identity_arguments(p.oid))
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.prokind IN ('f', 'p')
      AND p.proowner <> (SELECT oid FROM pg_roles WHERE rolname = %(owner)s)
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
    UNION ALL
    SELECT 'TYPE', format('%%I.%%I', n.nspname, t.typname)
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd')
      AND t.typowner <> (SELECT oid FROM pg_roles WHERE rolname = %(owner)s)
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
) AS todo
ORDER BY kind DESC, ident
"""


def apply_database(conn: psycopg.Connection, plan: RolePlan) -> list[str]:
    """Extensions, schema, ownership, grants and default privileges (connected to plan.database)."""
    owner, app = sql.Identifier(plan.owner), sql.Identifier(plan.app)
    done: list[str] = []
    with conn.cursor() as cur:
        for extension in plan.extensions:
            cur.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(extension)))
            if plan.update_extensions:
                cur.execute(sql.SQL("ALTER EXTENSION {} UPDATE").format(sql.Identifier(extension)))
                done.append(f"ALTER EXTENSION {extension} UPDATE")
        cur.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(owner))
        cur.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(app))

        for (statement,) in cur.execute(_REASSIGN_SQL, {"owner": plan.owner}).fetchall():
            cur.execute(statement)
            done.append(statement)

        cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(app))
        cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(app))
        cur.execute(sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {}").format(app))
        for privileges, objects in (
            ("SELECT, INSERT, UPDATE, DELETE", "TABLES"),
            ("USAGE, SELECT", "SEQUENCES"),
            ("EXECUTE", "FUNCTIONS"),
        ):
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT " + privileges + " ON " + objects + " TO {}").format(
                    owner, app
                )
            )
        session_guarded = [t for t in guarded_tables(conn) if t not in plan.app_marker_tables]
        read_only = list(dict.fromkeys((*plan.read_only_tables, *session_guarded)))
        append_only = list(plan.append_only_tables)
        for parent in plan.append_only_tables:
            if parent in PARTITIONED_APPEND_ONLY_TABLES:
                append_only.extend(partitions(conn, parent))
        for privileges, tables in (
            ("INSERT, UPDATE, DELETE", plan.read_only_views),
            ("INSERT, UPDATE, DELETE, TRUNCATE", read_only),
            ("UPDATE, DELETE, TRUNCATE", append_only),
            ("UPDATE, TRUNCATE", plan.no_update_tables),
            ("DELETE, TRUNCATE", plan.no_delete_tables),
        ):
            for table in tables:
                if cur.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is not None:
                    cur.execute(
                        sql.SQL("REVOKE " + privileges + " ON TABLE {} FROM {}").format(
                            sql.Identifier("public", table), app
                        )
                    )
        # The worker calls these through the app role; 0058 revoked them from PUBLIC (wave 3.1).
        for signature in plan.app_execute_functions:
            if cur.execute("SELECT to_regprocedure(%s)", (signature,)).fetchone()[0] is not None:
                cur.execute(sql.SQL("GRANT EXECUTE ON FUNCTION " + signature + " TO {}").format(app))
        for signature in plan.owner_only_functions:
            if cur.execute("SELECT to_regprocedure(%s)", (signature,)).fetchone()[0] is not None:
                cur.execute(sql.SQL("REVOKE EXECUTE ON FUNCTION " + signature + " FROM {}").format(app))
    return done


def bootstrap(admin_dsn: str, plan: RolePlan) -> list[str]:
    """Run both phases as a superuser. ``admin_dsn`` may point at any database; the
    database phase reconnects to ``plan.database``."""
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        if not conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
            raise SystemExit("db_roles: the admin connection must be a superuser (POSTGRES_USER)")
        apply_cluster(conn, plan)
        target = psycopg.conninfo.make_conninfo(admin_dsn, dbname=plan.database)
    with psycopg.connect(target, autocommit=True) as conn:
        return apply_database(conn, plan)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or "<" in value:
        raise SystemExit(f"db_roles: {name} is not set")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/db_roles.py")
    parser.add_argument("--database", default=os.environ.get("POSTGRES_DB", "elchi"))
    parser.add_argument("--owner", default=os.environ.get("ELCHI_DB_OWNER_USER", "elchi_owner"))
    parser.add_argument("--app", default=os.environ.get("ELCHI_DB_APP_USER", "elchi_app"))
    parser.add_argument("--read-only-table", action="append", default=[], help="additional app read-only table")
    parser.add_argument("--update-extensions", action="store_true",
                        help="ALTER EXTENSION ... UPDATE for postgis/btree_gist (after a PostGIS image upgrade)")
    parser.add_argument("--expected-guarded", metavar="FILE",
                        help="fail (exit 3) if the detected guarded tables differ from FILE (one name per line)")
    args = parser.parse_args(argv)

    admin = _require_env("ELCHI_DB_ADMIN_URL").replace("postgresql+psycopg://", "postgresql://", 1)
    plan = RolePlan(
        database=args.database,
        owner=args.owner,
        owner_password=_require_env("ELCHI_DB_OWNER_PASSWORD"),
        app=args.app,
        app_password=_require_env("ELCHI_DB_APP_PASSWORD"),
        read_only_tables=tuple(dict.fromkeys((*DEFAULT_READ_ONLY_TABLES, *args.read_only_table))),
        update_extensions=args.update_extensions,
    )
    changed = bootstrap(admin, plan)
    print(f"db_roles: roles {plan.owner} (owner) and {plan.app} (app) converged on {plan.database}; "
          f"{len(changed)} ownership change(s)")
    target = psycopg.conninfo.make_conninfo(admin, dbname=plan.database)
    with psycopg.connect(target, autocommit=True) as conn:
        detected = guarded_tables(conn)
    made_read_only = [t for t in detected if t not in plan.app_marker_tables]
    app_marker = [t for t in detected if t in plan.app_marker_tables]
    print(f"  session-guarded tables made read-only for {plan.app}: {', '.join(made_read_only) or 'none'}")
    print(f"  app-marker guarded tables (app keeps DML; guard stops accidental writes only): {', '.join(app_marker) or 'none'}")
    for statement in changed:
        print(f"  {statement}")
    print(f"GUARDED_TABLES={','.join(detected)}")
    if args.expected_guarded:
        problem = compare_guarded(detected, read_expected_guarded(args.expected_guarded))
        if problem:
            print(f"db_roles: {problem}", file=sys.stderr)
            return 3
        print("  guarded tables match the expected list")
    return 0


def read_expected_guarded(path: str) -> list[str]:
    return list(read_guard_classes(path))


def compare_guarded(detected: Sequence[str], expected: Sequence[str]) -> str | None:
    missing, unexpected = sorted(set(expected) - set(detected)), sorted(set(detected) - set(expected))
    if not missing and not unexpected:
        return None
    return (f"guarded tables differ from the expected list: missing {missing or '[]'}, unexpected {unexpected or '[]'} "
            "(update scripts/db_roles.expected-guarded-tables.txt together with the migration that changed a guard)")


if __name__ == "__main__":
    sys.exit(main())
