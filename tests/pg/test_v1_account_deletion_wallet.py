"""BR N4 on real PostgreSQL: v1 account deletion consults the v2 wallet (read-only).

The wallet is created through the wallet service so the 0041 triggers (cache consistency,
N1 environment guard) apply exactly as in production.
"""

from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import select

import app.models  # noqa: F401
from app.models import User
from app.modules.wallet.models import TopupRequest, WalletAccount
from app.modules.wallet.service import blocking_state_for_user, get_or_create_wallet
from app.services.account_deletion_service import delete_own_account
from tests.pg.conftest import PgDatabase

pytestmark = pytest.mark.pg


def _driver(db, phone: str) -> User:
    user = User(phone=phone, role="driver", status="active", is_phone_verified=True)
    db.add(user)
    db.flush()
    return user


def test_pending_topup_blocks_v1_deletion_on_postgres(pg_db: PgDatabase) -> None:
    with pg_db.session() as db:
        user = _driver(db, "+998933000001")
        wallet = get_or_create_wallet(db, user.id)
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
        user_id = user.id

    with pg_db.session() as db:
        state = blocking_state_for_user(db, user_id)
        assert state.blocks_deletion and state.pending_topups_count == 1
        user = db.get(User, user_id)
        result = delete_own_account(db, user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 409
        body = json.loads(result.body)
        assert body["error"]["code"] == "WALLET_BALANCE_EXISTS"
        assert body["error"]["details"]["pending_topups_count"] == 1
        db.rollback()

    with pg_db.session() as db:
        assert db.get(User, user_id).status == "active"


def test_empty_wallet_allows_v1_deletion_on_postgres(pg_db: PgDatabase) -> None:
    with pg_db.session() as db:
        user = _driver(db, "+998933000002")
        get_or_create_wallet(db, user.id)
        db.commit()
        user_id = user.id

    with pg_db.session() as db:
        assert not blocking_state_for_user(db, user_id).blocks_deletion
        result = delete_own_account(db, db.get(User, user_id))
        assert isinstance(result, dict) and result["deleted"] is True

    with pg_db.session() as db:
        assert db.get(User, user_id).status == "deleted"
        assert db.execute(select(WalletAccount).where(WalletAccount.driver_user_id == user_id)).scalar_one() is not None
