"""Promotions DB guards under the real application role (Q119, Q36 roles from scripts/db_roles.py).

The schema is migrated by the non-superuser owner and the app role gets exactly the grants deploy gives it. Then,
connected *as the app role*, we try every shortcut: writing the budget cache, rewriting or truncating the ledger,
disabling triggers, replication-role tricks, borrowing the owner role, session "context" settings, naming an
operator or an inactive person as the finance actor, self-approving a large change, and a flag marker plus an
approval reference in production.

Protection boundary (ADR-0023 §15): the database checks that the *named* actor is an active finance/super_admin
user and that a large change names two different such people; it cannot authenticate which human is behind an
app-role connection. That is the API layer's job (JWT session, server-computed capabilities, MFA step-up) and every
posting is recorded append-only with its actor. The last test pins this boundary explicitly. SYNTHETIC data only.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.contracts.enums import STAFF_ROLE_CAPABILITIES, PromoCampaignKind, PromoLedgerKind, Role, ServiceType
from app.modules.promotions import service
from tests.pg.conftest import PgDatabase
from tests.pg.ops.test_db_roles import Roles, _connect, _libpq_dsn, _migrated_with_roles, roles  # noqa: F401  (fixture)
from tests.pg.promotions.conftest import synthetic_terms

pytestmark = pytest.mark.pg

SUPER = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
FINANCE = STAFF_ROLE_CAPABILITIES[Role.FINANCE]
THRESHOLD = 100_000_000


def _user(conn: psycopg.Connection, role: str, status: str = "active") -> int:
    phone = f"+99894{uuid.uuid4().int % 10_000_000:07d}"
    return conn.execute("INSERT INTO users (phone, role, status, is_phone_verified) VALUES (%s, %s, %s, true) RETURNING id",
                        (phone, role, status)).fetchone()[0]


@pytest.fixture
def app_setup(roles: Roles, pg_empty_db: PgDatabase):  # noqa: F811, ANN201
    _, app_url = _migrated_with_roles(pg_empty_db, roles)
    conn = _connect(app_url)
    people = {name: _user(conn, role) for name, role in (
        ("super", "super_admin"), ("finance", "finance"), ("finance2", "finance"), ("operator", "operator"))}
    people["gone"] = _user(conn, "finance", status="deleted")
    engine = create_engine(app_url)
    with Session(engine) as s:
        campaign = service.create_campaign(s, actor_user_id=people["super"], actor_capabilities=SUPER,
                                           kind=PromoCampaignKind.REFERRAL_CLIENT_CLIENT,
                                           service_type=ServiceType.PASSENGER, name="Synthetic app-role test")
        service.add_campaign_version(s, actor_user_id=people["super"], actor_capabilities=SUPER,
                                     campaign_id=campaign.id, terms=synthetic_terms())
        service.request_budget_change(s, actor_user_id=people["finance"], actor_capabilities=FINANCE,
                                      campaign_id=campaign.id, kind=PromoLedgerKind.ALLOCATE, amount_minor=1_000_000,
                                      reason="synthetic")
        s.commit()
        campaign_id = campaign.id
    yield conn, campaign_id, people, engine
    conn.close()
    engine.dispose()


@pytest.fixture
def app_world(app_setup):  # noqa: ANN001, ANN201
    conn, campaign_id, people, _ = app_setup
    return conn, campaign_id, people


def _refused(conn: psycopg.Connection, sql: str, params: tuple = ()) -> psycopg.Error:
    with pytest.raises(psycopg.Error) as info:
        with conn.transaction():
            conn.execute(sql, params)
    return info.value


def _allocate_sql() -> str:
    return ("INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, reference_key, "
            "actor_user_id, reason, budget_request_id) VALUES (gen_random_uuid(), %s, 'allocate', %s, %s, %s, 'raw', %s)")


def test_app_role_is_the_real_non_privileged_role(app_world) -> None:  # noqa: ANN001
    conn, _, _ = app_world
    assert conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone() == (False, False)


def test_app_role_cannot_write_the_budget_cache_even_with_session_settings(app_world) -> None:  # noqa: ANN001
    conn, campaign, _ = app_world
    conn.execute("SELECT set_config('elchi.promo_budget_writer', 'on', false)")  # a made-up "context": grants nothing
    for sql in (
        "UPDATE promo_budgets SET allocated_minor = allocated_minor + 1 WHERE campaign_id = %s",
        "DELETE FROM promo_budgets WHERE campaign_id = %s",
        "INSERT INTO promo_budgets (campaign_id, allocated_minor) VALUES (%s, 1)",
    ):
        error = _refused(conn, sql, (campaign,))
        assert error.sqlstate in {"42501", "23514"}  # revoked by db_roles (read-only class) or the writer guard
    assert _refused(conn, "TRUNCATE promo_budgets CASCADE").sqlstate in {"42501", "23514"}


def test_app_role_cannot_rewrite_or_hide_ledger_history(app_world) -> None:  # noqa: ANN001
    conn, campaign, _ = app_world
    for sql in ("UPDATE promo_ledger_transactions SET amount_minor = 1 WHERE campaign_id = %s",
                "DELETE FROM promo_ledger_transactions WHERE campaign_id = %s"):
        assert _refused(conn, sql, (campaign,)).diag.constraint_name == "append_only_violation"
    assert _refused(conn, "TRUNCATE promo_ledger_transactions CASCADE").sqlstate in {"42501", "23514"}


def test_app_role_cannot_switch_the_guards_off(app_world, roles: Roles) -> None:  # noqa: ANN001, F811
    conn, _, _ = app_world
    assert _refused(conn, "SET session_replication_role = replica").sqlstate == "42501"
    assert _refused(conn, "ALTER TABLE promo_ledger_transactions DISABLE TRIGGER ALL").sqlstate == "42501"
    assert _refused(conn, f'SET ROLE "{roles.owner}"').sqlstate == "42501"


def test_named_actor_must_be_active_finance_staff(app_world) -> None:  # noqa: ANN001
    conn, campaign, people = app_world
    for actor in (people["operator"], people["gone"], people["super"] + 10_000):
        error = _refused(conn, _allocate_sql(), (campaign, 1, f"raw-{actor}", actor, None))
        assert error.diag.constraint_name in {"approver_not_finance_staff", "promo_ledger_transactions_actor_fkey",
                                              "fk_promo_ledger_transactions_actor"}


def test_large_change_cannot_be_self_approved_or_approved_by_request_number_alone(app_world) -> None:  # noqa: ANN001
    conn, campaign, people = app_world
    # no request at all
    error = _refused(conn, _allocate_sql(), (campaign, THRESHOLD + 1, "raw-large", people["finance"], None))
    assert error.diag.constraint_name == "promo_second_approver_required"
    # a request "approved" by its own requester
    error = _refused(conn, (
        "INSERT INTO promo_budget_requests (public_id, campaign_id, kind, amount_minor, reason, requested_by, approved_by) "
        "VALUES (gen_random_uuid(), %s, 'allocate', %s, 'raw', %s, %s)"),
        (campaign, THRESHOLD + 1, people["finance"], people["finance"]))
    assert error.diag.constraint_name == "ck_promo_budget_requests_approver"
    # a real pending request id without a second approver
    request_id = conn.execute(
        "INSERT INTO promo_budget_requests (public_id, campaign_id, kind, amount_minor, reason, requested_by) "
        "VALUES (gen_random_uuid(), %s, 'allocate', %s, 'raw', %s) RETURNING id",
        (campaign, THRESHOLD + 1, people["finance"])).fetchone()[0]
    error = _refused(conn, _allocate_sql(), (campaign, THRESHOLD + 1, "raw-large-2", people["finance"], request_id))
    assert error.diag.constraint_name == "promo_second_approver_required"
    # an operator named as the second approver
    conn.execute("UPDATE promo_budget_requests SET approved_by = %s WHERE id = %s", (people["operator"], request_id))
    error = _refused(conn, _allocate_sql(), (campaign, THRESHOLD + 1, "raw-large-3", people["operator"], request_id))
    assert error.diag.constraint_name in {"approver_not_finance_staff", "promo_second_approver_required"}


def test_overspending_is_refused_whoever_writes(app_world) -> None:  # noqa: ANN001
    conn, campaign, people = app_world
    obligation = conn.execute(
        "INSERT INTO promo_obligations (public_id, campaign_id, campaign_version_id, beneficiary_user_id, side, "
        "instrument, service_type, amount_minor, reward_key, source_type, source_id) "
        "SELECT gen_random_uuid(), %s, v.id, %s, 'referee', 'passenger_bonus', 'passenger', %s, 'raw-over', 'raw', 1 "
        "FROM promo_campaign_versions v WHERE v.campaign_id = %s RETURNING id",
        (campaign, people["super"], 1_000_001, campaign)).fetchone()[0]
    error = _refused(conn, "INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, "
                           "reference_key, obligation_id) VALUES (gen_random_uuid(), %s, 'promise', %s, 'raw-p', %s)",
                     (campaign, 1_000_001, obligation))
    assert error.diag.constraint_name == "promo_budget_exhausted"


def test_flag_marker_and_approval_reference_do_not_grant_enablement(app_world, pg_empty_db: PgDatabase) -> None:  # noqa: ANN001
    conn, _, people = app_world
    with psycopg.connect(_libpq_dsn(pg_empty_db.url), autocommit=True) as admin:
        admin.execute("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1")
    with pytest.raises(psycopg.Error) as info:
        with conn.transaction():
            conn.execute("SELECT set_config('elchi.flag_change_source', 'admin_api', true)")
            conn.execute("INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, "
                         "approval_reference, updated_by) VALUES (gen_random_uuid(), 'promotions_enabled', 'country', "
                         "'UZ', true, 'raw', 'LEGAL-SYNTH-1', %s)", (people["super"],))
    assert info.value.diag.constraint_name == "promo_flag_enable_refused"  # the Q48 gate still decides


def test_boundary_the_db_cannot_authenticate_the_human_behind_an_app_connection(app_world) -> None:  # noqa: ANN001
    """Pinned boundary: naming two *different active* finance users is accepted by the DB. Who they really are is
    proven by the API (JWT + capabilities + MFA step-up); the posting stays, append-only, with both names on it."""
    conn, campaign, people = app_world
    request_id = conn.execute(
        "INSERT INTO promo_budget_requests (public_id, campaign_id, kind, amount_minor, reason, requested_by, approved_by) "
        "VALUES (gen_random_uuid(), %s, 'allocate', %s, 'raw', %s, %s) RETURNING id",
        (campaign, THRESHOLD + 1, people["finance"], people["finance2"])).fetchone()[0]
    conn.execute(_allocate_sql(), (campaign, THRESHOLD + 1, "raw-boundary", people["finance2"], request_id))
    row = conn.execute("SELECT actor_user_id, budget_request_id FROM promo_ledger_transactions WHERE reference_key = "
                       "'raw-boundary'").fetchone()
    assert row == (people["finance2"], request_id)
    assert _refused(conn, "DELETE FROM promo_ledger_transactions WHERE reference_key = 'raw-boundary'").diag.constraint_name \
        == "append_only_violation"


def test_promotion_jobs_and_reviews_work_under_the_application_role(app_setup) -> None:  # noqa: ANN001
    """The worker uses the application role: every promotions job runs (advisory lock, SKIP LOCKED claims, batch
    commits) and a review can be opened and decided without extra privileges."""
    from app import worker
    from app.modules.promotions import qualification

    conn, campaign, people, engine = app_setup
    jobs = [job for job in worker.SERVICE_JOBS if job.name.startswith("promotions.")]
    assert len(jobs) == 8  # stage 5 added promotions.purge_rate_events; it too runs under the application role
    for job in jobs:
        ran, _ = worker.run_service_job(job, worker.resolve_service_function(job), engine=engine)
        assert ran, job.name
    with Session(engine) as s:
        review = qualification.open_review(s, kind="qualification_risk", dedup_key="app-role-review", reasons=["x"],
                                           evidence=[{"table": "promo_campaigns", "id": campaign}], campaign_id=campaign)
        s.commit()
        review_id, version = review.id, review.version
    with Session(engine) as s:
        qualification.decide_review(s, review_id=review_id, decision="approve", actor_user_id=people["super"],
                                    actor_capabilities=SUPER, note="checked", expected_version=version)
        s.commit()
    assert conn.execute("SELECT status FROM promo_reviews WHERE id = %s", (review_id,)).fetchone()[0] == "approved"
    error = _refused(conn, "UPDATE promo_reviews SET status = 'rejected' WHERE id = %s", (review_id,))
    assert error.diag.constraint_name == "promo_invalid_transition"  # a decision is final for every role



def test_app_role_cannot_switch_off_the_stage4_money_guards(app_world, roles: Roles) -> None:  # noqa: ANN001, F811
    """Stage 4 (ADR-0023 §18): the booking promo terms stay append-only and the deferred money check stays on for the
    application role too (the row-level refusals themselves are proven on real bookings in test_promo_booking_pg)."""
    conn, _, _ = app_world
    for sql in ("ALTER TABLE promo_booking_terms DISABLE TRIGGER trg_promo_booking_terms_append_only",
                "ALTER TABLE bookings DISABLE TRIGGER trg_bookings_promo_terms_verify",
                "ALTER TABLE wallet_holds DISABLE TRIGGER trg_wallet_holds_promo_terms_verify",
                "ALTER TABLE promo_consents DISABLE TRIGGER trg_promo_consents_guard",
                "DROP FUNCTION public.promo_booking_terms_verify() CASCADE"):
        assert _refused(conn, sql).sqlstate == "42501", sql
    assert _refused(conn, "TRUNCATE promo_booking_terms").sqlstate in {"42501", "23514"}
    guards = {row[0] for row in conn.execute(
        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgenabled <> 'D' AND tgrelid IN "
        "('promo_consents'::regclass, 'promo_booking_terms'::regclass, 'bookings'::regclass, "
        "'wallet_holds'::regclass, 'promo_redemptions'::regclass)")}
    assert {"trg_promo_consents_guard", "trg_promo_booking_terms_append_only", "trg_promo_booking_terms_no_truncate",
            "trg_bookings_promo_terms_verify", "trg_wallet_holds_promo_terms_verify",
            "trg_promo_redemptions_promo_terms_verify", "trg_promo_booking_terms_promo_terms_verify"} <= guards
