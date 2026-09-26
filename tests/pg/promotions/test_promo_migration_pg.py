"""Migrations 20260923_0084 / 0085 / 0086 / 0087 / 0088 / 0089 on PostgreSQL (Q119: evidence, not a stamp).

Four separate facts, each its own test:
1. a clean database migrated to head contains every expected promotions object;
2. upgrading step by step from the previous head (0083 -> 0084 -> ... -> 0088 -> 0089) produces exactly the same catalogue;
3. ``upgrade head`` on a database already at head runs nothing and changes nothing;
4. re-running the revision bodies (stamp back + upgrade) creates no duplicate object - this is *idempotency* of the
   upgrade code only and is never used as evidence that the schema is right (1 and 2 are).
Plus the promotions flag guard. SYNTHETIC data only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.ids import new_public_uuid
from tests.pg.conftest import PgDatabase, run_alembic, script_heads
from tests.pg.wallet.conftest import make_user

pytestmark = pytest.mark.pg

PREVIOUS_HEAD = "20260922_0083"
STEPS = ("20260923_0084", "20260923_0085", "20260923_0086", "20260923_0087", "20260923_0088", "20260923_0089",
         "20260924_0090", "20260924_0091")
EXPECTED_TABLES = {
    "promo_campaigns", "promo_campaign_versions", "promo_budgets", "promo_budget_requests", "promo_obligations",
    "promo_lots", "promo_redemptions", "promo_ledger_transactions", "promo_identities", "promo_identity_digests",
    "referral_codes", "referral_attributions", "promo_enrollments",
    "promo_qualification_events", "promo_qualifications", "promo_reviews",
    "promo_client_features", "promo_consents", "promo_booking_terms", "promo_rate_events",
    "promo_campaign_combinations", "promo_party_readiness",
}
EXPECTED_TRIGGERS = {
    "trg_feature_flag_values_promotions_guard", "trg_promo_campaign_versions_append_only",
    "trg_promo_campaign_versions_no_truncate", "trg_promo_ledger_transactions_append_only",
    "trg_promo_ledger_transactions_no_truncate", "trg_promo_budgets_writer_guard", "trg_promo_budgets_no_truncate",
    "trg_promo_ledger_apply", "trg_promo_budget_cache_check", "trg_promo_campaigns_guard", "trg_promo_obligations_guard",
    "trg_promo_lots_guard", "trg_promo_redemptions_guard", "trg_promo_lots_balance_check",
    "trg_promo_redemptions_balance_check", "trg_referral_codes_guard", "trg_referral_attributions_guard",
    "trg_promo_enrollments_guard", "trg_promo_obligations_enrollment_frozen",
    "trg_promo_qualifications_guard", "trg_promo_reviews_guard", "trg_promo_ledger_reinstate_check",
    "trg_promo_consents_guard", "trg_promo_booking_terms_append_only", "trg_promo_booking_terms_no_truncate",
    "trg_promo_booking_terms_promo_terms_verify", "trg_promo_redemptions_promo_terms_verify",
    "trg_promo_campaign_combinations_guard", "trg_promo_party_readiness_guard",
}
EXPECTED_CONSTRAINTS = {
    "ck_promo_campaign_versions_min_margin", "ck_promo_budgets_non_negative", "ck_promo_budget_requests_approver",
    "ck_promo_lots_buckets", "uq_promo_obligations_reward_key", "uq_promo_redemptions_lot_booking_seq",
    "uq_referral_codes_code", "uq_referral_attributions_referee_family", "ck_referral_attributions_not_self",
    "ck_referral_attributions_window", "uq_promo_enrollments_idempotency", "fk_promo_enrollments_version",
    "fk_promo_obligations_enrollment", "ck_feature_flag_values_flag_key",
    "uq_promo_qualification_events_dedup", "uq_promo_qualifications_enrollment_milestone", "uq_promo_reviews_dedup",
    "ck_promo_reviews_decided", "fk_promo_ledger_transactions_reinstates",
    "ck_promo_booking_terms_identities", "ck_promo_booking_terms_margin", "uq_promo_booking_terms_booking_seq",
    "ck_promo_consents_amounts", "ck_promo_consents_subject", "ck_promo_redemptions_terms_seq",
    "ck_promo_campaign_combinations_pair", "ck_promo_booking_terms_campaigns", "ck_promo_redemptions_restored",
    "ck_promo_party_readiness_subject", "fk_promo_consents_passenger_campaign",
    "ck_promo_budget_requests_funding_evidence",
}
EXPECTED_INDEXES = {
    "uq_promo_ledger_promise_obligation", "uq_promo_ledger_grant_lot", "uq_promo_ledger_consume_redemption",
    "uq_referral_codes_one_active_per_owner", "uq_promo_enrollments_identity_family", "uq_promo_enrollments_user_family",
    "uq_promo_ledger_reinstate_once", "ix_promo_qualification_events_pending", "ix_promo_reviews_open",
    "uq_promo_consents_active_version", "uq_promo_consents_active_amendment", "ix_promo_rate_events_window",
    "uq_promo_campaign_combinations_active", "uq_promo_party_readiness_version", "uq_promo_party_readiness_amendment",
}
_PROMO = "(^promo_|^referral_)"


def _catalogue(db: PgDatabase) -> dict[str, frozenset]:
    """Name + definition of every promotions object, so two databases can be compared exactly."""
    with db.engine.connect() as conn:
        def rows(sql: str) -> frozenset:
            return frozenset(tuple(r) for r in conn.execute(text(sql), {"p": _PROMO}))

        return {
            "columns": rows("SELECT table_name, column_name, data_type, is_nullable, column_default FROM "
                            "information_schema.columns WHERE table_schema = 'public' AND table_name ~ :p"),
            "constraints": rows("SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
                                "WHERE conrelid::regclass::text ~ :p OR conname = 'ck_feature_flag_values_flag_key'"),
            "indexes": rows("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename ~ :p"),
            "triggers": rows("SELECT tgname, tgrelid::regclass::text, pg_get_triggerdef(oid) FROM pg_trigger "
                             "WHERE NOT tgisinternal AND (tgrelid::regclass::text ~ :p OR tgname LIKE '%promotions%')"),
            "functions": rows("SELECT proname, md5(prosrc) FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
                              "AND proname ~ '^(promo_|referral_)'"),
            "views": rows("SELECT viewname, md5(definition) FROM pg_views WHERE schemaname = 'public' AND viewname ~ :p"),
        }


def _names(catalogue: dict[str, frozenset], kind: str) -> set[str]:
    return {row[0] for row in catalogue[kind]}


def _upgrade(db: PgDatabase, target: str) -> str:
    result = run_alembic(db.url, "upgrade", target)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def test_referral_revisions_lead_to_the_single_head() -> None:
    # ADR-0026 migration 20260924_0092 follows the referral steps; the head is still a single revision
    assert script_heads() == ["20260925_0095"]


def test_clean_database_has_every_expected_object(pg_empty_db: PgDatabase) -> None:
    _upgrade(pg_empty_db, "head")
    catalogue = _catalogue(pg_empty_db)
    assert EXPECTED_TABLES <= {row[0] for row in catalogue["columns"]}
    assert EXPECTED_TRIGGERS <= _names(catalogue, "triggers")
    assert EXPECTED_CONSTRAINTS <= _names(catalogue, "constraints")
    assert EXPECTED_INDEXES <= _names(catalogue, "indexes")
    assert {"promo_obligation_reconciliation", "promo_booking_finance"} <= _names(catalogue, "views")
    flag_check = next(r[2] for r in catalogue["constraints"] if r[0] == "ck_feature_flag_values_flag_key")
    assert "promotions_enabled" in flag_check


def test_stepwise_upgrade_from_previous_head_equals_a_clean_install(pg_empty_db: PgDatabase, pg_db: PgDatabase) -> None:
    _upgrade(pg_empty_db, PREVIOUS_HEAD)
    assert not EXPECTED_TABLES & {row[0] for row in _catalogue(pg_empty_db)["columns"]}
    for step in STEPS:
        _upgrade(pg_empty_db, step)
        with pg_empty_db.engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == step
    _upgrade(pg_empty_db, "head")  # later steps (0092/0093, ADR-0026) also widen promo CHECKs; they apply on top the same way
    assert _catalogue(pg_empty_db) == _catalogue(pg_db)  # pg_db: the session template, migrated to head in one go


def test_upgrade_at_head_runs_nothing(pg_db: PgDatabase) -> None:
    before = _catalogue(pg_db)
    output = _upgrade(pg_db, "head")
    assert "Running upgrade" not in output
    assert _catalogue(pg_db) == before


def test_rerunning_the_bodies_creates_no_duplicates(pg_db: PgDatabase) -> None:
    """Idempotency of the upgrade code only (stamp back + upgrade) - not evidence of schema correctness."""
    before = _catalogue(pg_db)
    assert run_alembic(pg_db.url, "stamp", PREVIOUS_HEAD).returncode == 0
    output = _upgrade(pg_db, "head")
    assert all(step in output for step in STEPS)
    assert _catalogue(pg_db) == before


# --- promotions flag (Q101) --------------------------------------------------------------------------------------


def test_promotions_flag_defaults_off_and_accepts_the_new_key(pg_db: PgDatabase) -> None:
    from app.contracts.enums import PRODUCTION_FLAG_DEFAULTS, FeatureFlagKey

    with pg_db.session() as s:
        actor = make_user(s, "super_admin")
        s.commit()
    with pg_db.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
            "VALUES (:p, 'promotions_enabled', 'cohort', 'synthetic', true, 'synthetic test', :u)"),
            {"p": new_public_uuid(), "u": actor})
    assert PRODUCTION_FLAG_DEFAULTS[FeatureFlagKey.PROMOTIONS_ENABLED] is False


def test_promotions_flag_cannot_be_enabled_in_production_without_approval_marker_and_gate(pg_db: PgDatabase) -> None:
    with pg_db.session() as s:
        actor = make_user(s, "super_admin")
        s.commit()
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))

    def insert(approval: str | None, marked: bool) -> None:
        with pg_db.engine.begin() as conn:
            if marked:
                conn.execute(text("SELECT set_config('elchi.flag_change_source', 'admin_api', true)"))
            conn.execute(text(
                "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, "
                "approval_reference, updated_by) VALUES (:p, 'promotions_enabled', 'cohort', :r, true, 'synthetic', :a, :u)"),
                {"p": new_public_uuid(), "r": f"c{approval}{marked}", "a": approval, "u": actor})

    for approval, marked, rule in (
        (None, True, "promo_flag_enable_refused"),
        ("LEGAL-SYNTH-1", False, "flag_enable_source_refused"),
        ("LEGAL-SYNTH-1", True, "promo_flag_enable_refused"),  # marker + approval alone are not enough: Q48 gate
    ):
        with pytest.raises(DBAPIError) as info:
            insert(approval, marked)
        assert info.value.orig.diag.constraint_name == rule
    with pg_db.engine.begin() as conn:  # OFF is always allowed
        conn.execute(text(
            "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
            "VALUES (:p, 'promotions_enabled', 'country', 'UZ', false, 'synthetic', :u)"),
            {"p": new_public_uuid(), "u": actor})
