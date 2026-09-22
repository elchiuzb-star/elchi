"""Shared helpers for wallet/platform PostgreSQL tests (A3)."""

from __future__ import annotations

import itertools
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.contracts.enums import FLAG_CHANGE_SOURCE_ADMIN_API, FLAG_CHANGE_SOURCE_SETTING, STAFF_ROLE_CAPABILITIES, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from tests.pg.wallet.booking_factory import BookingFactory, bookings, world  # noqa: F401  (fixtures, 0055 FKs)

SUPER_CAPS = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
FINANCE_CAPS = STAFF_ROLE_CAPABILITIES[Role.FINANCE]
ADMIN_CAPS = STAFF_ROLE_CAPABILITIES[Role.ADMIN]
OPERATOR_CAPS = STAFF_ROLE_CAPABILITIES[Role.OPERATOR]

_phones = itertools.count(1)


def make_user(session: Session, role: str) -> int:
    phone = f"+99890{uuid.uuid4().int % 10_000_000:07d}"
    return session.execute(
        text(
            "INSERT INTO users (phone, role, status, is_phone_verified) "
            "VALUES (:phone, :role, 'active', true) RETURNING id"
        ),
        {"phone": phone, "role": role},
    ).scalar_one()


def fund_wallet(session: Session, driver_id: int, amount_minor: int, approver_id: int) -> None:
    """Real money path: pending top-up + approval with a unique bank reference."""
    from app.modules.wallet import service

    topup = service.create_topup(session, driver_user_id=driver_id, amount_minor=amount_minor, method="bank_transfer")
    service.approve_topup(
        session,
        actor_user_id=approver_id,
        actor_capabilities=SUPER_CAPS,
        topup_id=topup.id,
        expected_version=topup.version,
        source_type="bank_statement",
        source_reference=f"BANK-{uuid.uuid4().hex}",
        received_amount_minor=amount_minor,
        received_at=utc_now() - timedelta(minutes=5),
    )


def wallet_row(session: Session, driver_id: int) -> dict:
    return dict(
        session.execute(
            text("SELECT id, posted_balance_minor, held_minor, test_overdraft_allowed FROM wallet_accounts WHERE driver_user_id = :d"),
            {"d": driver_id},
        ).mappings().one()
    )


def error_code(result) -> ErrorCode | None:
    error = result.error
    return error.code if isinstance(error, DomainError) else None


@pytest.fixture
def app_role(pg_db):
    """A NOSUPERUSER app role like A10a's (Q36): full DML except balance writes. Cluster role, dropped after."""
    role = f"elchi_app_t{uuid.uuid4().hex[:8]}"
    with pg_db.engine.begin() as conn:
        conn.execute(text(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS'))
        conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
        conn.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
        conn.execute(text(f'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ledger_account_balances FROM "{role}"'))
    try:
        yield role
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def mark_flag_change_source(session_or_conn) -> None:
    """Q72 (A2, 0057): a transaction that switches a v2 service flag ON needs the admin-API source marker.

    Uses ``geo.service.mark_flag_change_source`` when A2 has published it, otherwise the same ``SET LOCAL``.
    """
    try:
        from app.modules.geo.service import mark_flag_change_source as helper
    except ImportError:
        helper = None
    if helper is not None:
        helper(session_or_conn)
        return
    session_or_conn.execute(text("SELECT set_config(:k, :v, true)"),
                            {"k": FLAG_CHANGE_SOURCE_SETTING, "v": FLAG_CHANGE_SOURCE_ADMIN_API})


def as_role(session_or_conn, role: str) -> None:
    """Run the rest of the current transaction as ``role`` (call again after each commit/rollback)."""
    session_or_conn.execute(text(f'SET LOCAL ROLE "{role}"'))


@pytest.fixture
def people(pg_db):
    with pg_db.session() as session:
        ids = {
            "driver": make_user(session, "driver"),
            "driver2": make_user(session, "driver"),
            "super": make_user(session, "super_admin"),
            "super2": make_user(session, "super_admin"),
            "finance": make_user(session, "finance"),
            "admin": make_user(session, "admin"),
        }
        session.commit()
    return ids
