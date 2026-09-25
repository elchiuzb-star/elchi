"""Migration 20260924_0091 (ADR-0025, saved trip/parcel requests) on PostgreSQL - evidence, not a stamp (Q119).

1. a clean database migrated to head has every trip-intent object;
2. 0090 -> 0091 step by step gives exactly the same catalogue as a clean install;
3. ``upgrade head`` at head runs nothing;
4. re-running the body (stamp back + upgrade) creates no duplicate (idempotency of the upgrade code only).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase, run_alembic

pytestmark = pytest.mark.pg

PREVIOUS = "20260924_0090"
REVISION = "20260924_0091"
EXPECTED_TABLES = {"trip_intents", "trip_intent_versions"}
EXPECTED_COLUMNS = {("proposal_threads", "trip_intent_id"), ("proposal_threads", "trip_intent_terms_version"),
                    ("bookings", "trip_intent_id")}
EXPECTED_TRIGGERS = {"trg_trip_intents_guard", "trg_trip_intent_versions_append_only",
                     "trg_proposal_threads_trip_intent_frozen", "trg_bookings_trip_intent_guard"}
EXPECTED_CONSTRAINTS = {
    "uq_trip_intents_public_id", "fk_trip_intents_owner", "fk_trip_intents_booking", "ck_trip_intents_service",
    "ck_trip_intents_status", "ck_trip_intents_booked", "ck_trip_intents_counters", "uq_trip_intent_versions_no",
    "ck_trip_intent_versions_ends", "ck_trip_intent_versions_window", "ck_trip_intent_versions_quantity",
    "ck_trip_intent_versions_price", "ck_trip_intent_versions_parcel", "fk_proposal_threads_trip_intent",
    "ck_proposal_threads_trip_intent_pair", "fk_bookings_trip_intent",
}
EXPECTED_INDEXES = {"ix_trip_intents_owner_status", "ix_proposal_threads_trip_intent", "uq_bookings_trip_intent_binding"}
_TABLES = "^(trip_intents|trip_intent_versions|proposal_threads|bookings)$"


def _catalogue(db: PgDatabase) -> dict[str, frozenset]:
    with db.engine.connect() as conn:
        def rows(sql: str) -> frozenset:
            return frozenset(tuple(r) for r in conn.execute(text(sql), {"p": _TABLES}))

        return {
            "columns": rows("SELECT table_name, column_name, data_type, is_nullable, column_default FROM "
                            "information_schema.columns WHERE table_schema = 'public' AND table_name ~ :p"),
            "constraints": rows("SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
                                "WHERE conrelid::regclass::text ~ :p"),
            "indexes": rows("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename ~ :p"),
            "triggers": rows("SELECT tgname, tgrelid::regclass::text, pg_get_triggerdef(oid) FROM pg_trigger "
                             "WHERE NOT tgisinternal AND tgrelid::regclass::text ~ :p"),
            "functions": rows("SELECT proname, md5(prosrc) FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
                              "AND proname ~ 'trip_intent'"),
        }


def _names(catalogue: dict[str, frozenset], kind: str) -> set[str]:
    return {row[0] for row in catalogue[kind]}


def _upgrade(db: PgDatabase, target: str) -> str:
    result = run_alembic(db.url, "upgrade", target)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def test_clean_database_has_every_trip_intent_object(pg_empty_db: PgDatabase) -> None:
    _upgrade(pg_empty_db, "head")
    catalogue = _catalogue(pg_empty_db)
    assert EXPECTED_TABLES <= {row[0] for row in catalogue["columns"]}
    assert EXPECTED_COLUMNS <= {(row[0], row[1]) for row in catalogue["columns"]}
    assert EXPECTED_TRIGGERS <= _names(catalogue, "triggers")
    assert EXPECTED_CONSTRAINTS <= _names(catalogue, "constraints")
    assert EXPECTED_INDEXES <= _names(catalogue, "indexes")
    binding = next(r[1] for r in catalogue["indexes"] if r[0] == "uq_bookings_trip_intent_binding")
    assert "UNIQUE" in binding and "cancelled" in binding  # a cancelled booking frees the request, nothing else does


def test_step_from_the_previous_head_equals_a_clean_install(pg_empty_db: PgDatabase, pg_db: PgDatabase) -> None:
    _upgrade(pg_empty_db, PREVIOUS)
    assert not EXPECTED_TABLES & {row[0] for row in _catalogue(pg_empty_db)["columns"]}
    _upgrade(pg_empty_db, REVISION)
    with pg_empty_db.engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
    _upgrade(pg_empty_db, "head")  # later revisions (0092, ADR-0026 retirement triggers) apply on top the same way
    assert _catalogue(pg_empty_db) == _catalogue(pg_db)


def test_upgrade_at_head_runs_nothing(pg_db: PgDatabase) -> None:
    before = _catalogue(pg_db)
    assert "Running upgrade" not in _upgrade(pg_db, "head")
    assert _catalogue(pg_db) == before


def test_rerunning_the_body_creates_no_duplicates(pg_db: PgDatabase) -> None:
    """Idempotency of the upgrade code only (stamp back + upgrade) - not evidence of schema correctness."""
    before = _catalogue(pg_db)
    assert run_alembic(pg_db.url, "stamp", PREVIOUS).returncode == 0
    assert REVISION in _upgrade(pg_db, "head")
    assert _catalogue(pg_db) == before
