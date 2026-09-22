"""BR N4: v1 account deletion refuses while the v2 wallet has balance, holds or pending requests.

Behaviour only (SQLite). The same rule on real PostgreSQL with the wallet DB triggers is in
tests/pg/test_v1_account_deletion_wallet.py.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User
from app.modules.wallet.models import LedgerAccount, TopupRequest, WalletAccount


@pytest.fixture()
def env():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    users = {
        "driver_pending_topup": User(phone="+998932000001", role="driver", status="active", is_phone_verified=True),
        "driver_empty_wallet": User(phone="+998932000002", role="driver", status="active", is_phone_verified=True),
        "client_no_wallet": User(phone="+998932000003", role="client", status="active", is_phone_verified=True),
    }
    db.add_all(users.values())
    db.flush()
    for key in ("driver_pending_topup", "driver_empty_wallet"):
        user = users[key]
        account = LedgerAccount(code=f"driver_prepaid:{user.id}", kind="liability", owner_user_id=user.id, currency="UZS")
        db.add(account)
        db.flush()
        wallet = WalletAccount(driver_user_id=user.id, ledger_account_id=account.id, currency="UZS")
        db.add(wallet)
        db.flush()
        if key == "driver_pending_topup":
            db.add(
                TopupRequest(
                    driver_user_id=user.id,
                    wallet_id=wallet.id,
                    amount_minor=5_000_000,
                    currency="UZS",
                    method="bank_transfer",
                    status="pending",
                )
            )
    db.commit()
    ids = {key: user.id for key, user in users.items()}
    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    db.close()

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), tokens, SessionLocal, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_pending_topup_blocks_account_deletion(env) -> None:
    client, tokens, SessionLocal, ids = env
    response = client.delete("/api/v1/auth/me", headers=_auth(tokens["driver_pending_topup"]))
    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "WALLET_BALANCE_EXISTS"
    assert body["error"]["details"]["pending_topups_count"] == 1
    assert body["error"]["details"]["wallet_posted_minor"] == 0
    with SessionLocal() as db:
        assert db.get(User, ids["driver_pending_topup"]).status == "active"


def test_empty_wallet_does_not_block_deletion(env) -> None:
    client, tokens, SessionLocal, ids = env
    response = client.delete("/api/v1/auth/me", headers=_auth(tokens["driver_empty_wallet"]))
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(User, ids["driver_empty_wallet"]).status == "deleted"


def test_user_without_wallet_is_unaffected(env) -> None:
    client, tokens, SessionLocal, ids = env
    response = client.delete("/api/v1/auth/me", headers=_auth(tokens["client_no_wallet"]))
    assert response.status_code == 200, response.text
