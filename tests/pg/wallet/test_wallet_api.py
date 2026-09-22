"""HTTP smoke of the W* router on PostgreSQL: envelopes, idempotency header, capabilities, OpenAPI."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts.timeutil import to_iso_utc, utc_now
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app as main_app
from app.modules.wallet.api import router

pytestmark = pytest.mark.pg


@pytest.fixture
def client(pg_db):
    api = FastAPI()
    # Reuse the real v1 exception handlers so auth errors keep the envelope shape.
    for exc_class, handler in main_app.exception_handlers.items():
        api.add_exception_handler(exc_class, handler)
    api.include_router(router, prefix="/api/v2")

    def override():
        session = pg_db.session()
        try:
            yield session
        finally:
            session.close()

    api.dependency_overrides[get_db] = override
    return TestClient(api)


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


@pytest.fixture
def approved_driver(pg_db, people):
    """A1 grants wallet.* only to an eligible driver (approved profile) or one with active trips."""
    from sqlalchemy import text

    with pg_db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO driver_profiles (user_id, verification_status, is_available, rating_avg, total_orders, "
                "completed_orders, cancelled_orders, dispute_count) VALUES (:u, 'approved', false, 0, 0, 0, 0, 0)"
            ),
            {"u": people["driver"]},
        )
    return people["driver"]


def test_openapi_every_route_has_response_schema(client):
    spec = client.get("/openapi.json").json()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            ok = operation["responses"].get("200") or operation["responses"].get("201")
            assert ok and "schema" in ok["content"]["application/json"], (method, path)
    assert len([p for p in spec["paths"] if p.startswith("/api/v2/")]) == 19


def test_driver_topup_flow_and_idempotent_replay(client, people, approved_driver):
    driver, super_admin = _auth(approved_driver), _auth(people["super"])
    wallet = client.get("/api/v2/wallet", headers=driver)
    assert wallet.status_code == 200 and wallet.json()["data"]["available_minor"] == 0
    assert wallet.json()["data"]["id"].startswith("wal_")

    body = {"amount_minor": 10_000_000, "method": "bank_transfer", "evidence_file_id": "shot-1"}
    missing = client.post("/api/v2/wallet/topups", json=body, headers=driver)
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    headers = {**driver, "Idempotency-Key": "topup-key-000001"}
    first = client.post("/api/v2/wallet/topups", json=body, headers=headers)
    again = client.post("/api/v2/wallet/topups", json=body, headers=headers)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() and again.headers.get("Idempotent-Replayed") == "true"
    reused = client.post("/api/v2/wallet/topups", json={**body, "amount_minor": 1}, headers=headers)
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    topup_id = first.json()["data"]["id"]
    assert client.get("/api/v2/wallet", headers=driver).json()["data"]["posted_balance_minor"] == 0  # AC24

    approve = {"expected_version": 1, "source_type": "bank_statement", "source_reference": "STMT-API-1",
               "received_amount_minor": 10_000_000, "received_at": to_iso_utc(utc_now())}
    forbidden = client.post(f"/api/v2/admin/topups/{topup_id}/approve", json=approve,
                            headers={**driver, "Idempotency-Key": "approve-key-0001"})
    assert forbidden.status_code == 403
    ok = client.post(f"/api/v2/admin/topups/{topup_id}/approve", json=approve,
                     headers={**super_admin, "Idempotency-Key": "approve-key-0002"})
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "approved", ok.json()
    lines = client.get("/api/v2/wallet/transactions", headers=driver).json()
    assert lines["data"][0]["balance_after_minor"] == 10_000_000 and lines["meta"]["next_cursor"] is None
    unknown = client.post("/api/v2/admin/topups/top_aaaaaaaaaaaaaaaaaaaaaaaaaa/approve", json=approve,
                          headers={**super_admin, "Idempotency-Key": "approve-key-0003"})
    assert unknown.status_code == 404


def test_policy_endpoints_q2(client, people):
    now = utc_now()
    body = {"kind": "campaign", "fee_bps": 0, "effective_from": to_iso_utc(now + timedelta(hours=1)),
            "effective_to": to_iso_utc(now + timedelta(hours=2)), "campaign_name": "launch", "reason": "pilot"}
    admin = client.post("/api/v2/admin/commission-policies", json=body,
                        headers={**_auth(people["admin"]), "Idempotency-Key": "policy-key-0001"})
    assert admin.status_code == 403 and admin.json()["error"]["code"] == "FORBIDDEN"
    created = client.post("/api/v2/admin/commission-policies", json=body,
                          headers={**_auth(people["super"]), "Idempotency-Key": "policy-key-0002"})
    assert created.status_code == 201 and created.json()["data"]["fee_percent"] == "0.00"
    listed = client.get("/api/v2/admin/commission-policies", headers=_auth(people["admin"]))
    assert listed.status_code == 200 and len(listed.json()["data"]) == 2
    naive = client.post("/api/v2/admin/commission-policies", json={**body, "effective_from": "2030-01-01T10:00:00"},
                        headers={**_auth(people["super"]), "Idempotency-Key": "policy-key-0003"})
    assert naive.status_code == 400


# --- wave 1.5 ---------------------------------------------------------------------------------------------


def _count(pg_db, sql):
    from sqlalchemy import text

    with pg_db.engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def _funded_wallet_public_id(pg_db, people, amount=10_000_000):
    from app.modules.wallet import service
    from tests.pg.wallet.conftest import fund_wallet

    with pg_db.session() as s:
        fund_wallet(s, people["driver"], amount, people["super"])
        public_id = service.get_wallet(s, people["driver"]).public_id
        s.commit()
    return public_id


def test_br14_forbidden_command_is_not_stored_for_replay(client, people, pg_db):
    now = utc_now()
    body = {"kind": "campaign", "fee_bps": 0, "effective_from": to_iso_utc(now + timedelta(hours=1)),
            "effective_to": to_iso_utc(now + timedelta(hours=2)), "campaign_name": "launch", "reason": "pilot"}
    denied = client.post("/api/v2/admin/commission-policies", json=body,
                         headers={**_auth(people["admin"]), "Idempotency-Key": "shared-key-00001"})
    assert denied.status_code == 403
    assert _count(pg_db, "SELECT count(*) FROM idempotency_records") == 0


def test_br14_database_error_at_commit_is_a_500_envelope(client, people, pg_db, monkeypatch):
    import uuid as uuid_module

    from sqlalchemy import text

    from app.modules.wallet import service

    wallet_id = _funded_wallet_public_id(pg_db, people)
    original = service.request_adjustment

    def unbalanced_then_real(db, **kwargs):
        tx = db.execute(text(
            "INSERT INTO ledger_transactions (public_id, reference_kind, reference_key, description) "
            "VALUES (:p, 'adjustment', 'broken-api', 'x') RETURNING id"), {"p": uuid_module.uuid4()}).scalar()
        db.execute(text("INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor) "
                        "VALUES (:t, 1, 'debit', 5)"), {"t": tx})
        return original(db, **kwargs)

    monkeypatch.setattr(service, "request_adjustment", unbalanced_then_real)
    response = client.post("/api/v2/admin/ledger/adjustments",
                           json={"wallet_id": wallet_id, "amount_minor": 100, "direction": "credit", "reason": "x"},
                           headers={**_auth(people["super"]), "Idempotency-Key": "broken-key-00001"})
    assert response.status_code == 500 and response.json()["error"]["code"] == "SERVER_ERROR"
    assert _count(pg_db, "SELECT count(*) FROM ledger_transactions WHERE reference_key IN ('broken-api')") == 0
    assert _count(pg_db, "SELECT count(*) FROM idempotency_records") == 0


def test_br9_reconciliation_get_reads_stored_runs_only(client, people, pg_db):
    from app.modules.wallet import service

    url = f"/api/v2/admin/finance/reconciliation?date={utc_now().date().isoformat()}"
    missing = client.get(url, headers=_auth(people["finance"]))
    assert missing.status_code == 404
    assert _count(pg_db, "SELECT count(*) FROM reconciliation_runs") == 0
    with pg_db.session() as s:
        service.run_reconciliation(s)
        s.commit()
    stored = client.get(url, headers=_auth(people["finance"]))
    assert stored.status_code == 200 and stored.json()["data"]["mismatches"] == []


def test_br4_adjustment_endpoints_list_get_reject(client, people, pg_db):
    from app.modules.wallet import service

    wallet_id = _funded_wallet_public_id(pg_db, people)
    big = service.TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1
    created = client.post("/api/v2/admin/ledger/adjustments",
                          json={"wallet_id": wallet_id, "amount_minor": big, "direction": "credit", "reason": "bank fix"},
                          headers={**_auth(people["finance"]), "Idempotency-Key": "adj-create-0001"})
    assert created.status_code == 202, created.json()
    adjustment_id = created.json()["data"]["id"]
    assert adjustment_id.startswith("adj_")
    listed = client.get(f"/api/v2/admin/ledger/adjustments?status=pending&wallet_id={wallet_id}",
                        headers=_auth(people["super"]))
    assert [item["id"] for item in listed.json()["data"]] == [adjustment_id]
    assert client.get("/api/v2/admin/ledger/adjustments?status=approved",
                      headers=_auth(people["super"])).json()["data"] == []
    one = client.get(f"/api/v2/admin/ledger/adjustments/{adjustment_id}", headers=_auth(people["super"]))
    assert one.status_code == 200 and one.json()["data"]["status"] == "pending_second_approval"
    rejected = client.post(f"/api/v2/admin/ledger/adjustments/{adjustment_id}/reject",
                           json={"expected_version": 1, "reason": "duplicate"},
                           headers={**_auth(people["super2"]), "Idempotency-Key": "adj-reject-0001"})
    assert rejected.status_code == 200 and rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["data"]["reject_reason"] == "duplicate"
    late = client.post(f"/api/v2/admin/ledger/adjustments/{adjustment_id}/approve", json={"expected_version": 2},
                       headers={**_auth(people["super"]), "Idempotency-Key": "adj-approve-0001"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    signals = client.get(f"/api/v2/admin/finance/signals/split-adjustments?from={utc_now().date()}&to={utc_now().date()}",
                         headers=_auth(people["finance"]))
    assert signals.status_code == 200 and signals.json()["data"] == []


def test_decision28_confirm_seed_policy_endpoint(client, people):
    listed = client.get("/api/v2/admin/commission-policies", headers=_auth(people["admin"])).json()["data"]
    seed = next(item for item in listed if not item["is_confirmed"])
    body = {"expected_version": seed["version"], "reason": "rate reviewed"}
    denied = client.post(f"/api/v2/admin/commission-policies/{seed['id']}/confirm", json=body,
                         headers={**_auth(people["admin"]), "Idempotency-Key": "confirm-key-0001"})
    assert denied.status_code == 403
    confirmed = client.post(f"/api/v2/admin/commission-policies/{seed['id']}/confirm", json=body,
                            headers={**_auth(people["super"]), "Idempotency-Key": "confirm-key-0002"})
    assert confirmed.status_code == 200 and confirmed.json()["data"]["is_confirmed"] is True
