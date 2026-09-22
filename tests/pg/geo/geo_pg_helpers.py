"""Shared helpers for geo PG tests (not a conftest, to keep tests/pg/conftest.py A0b-owned)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.pg.conftest import PgDatabase


def create_user(db: PgDatabase | Session, role: str = "admin") -> int:
    phone = "+99890" + str(uuid.uuid4().int)[:7]
    statement = text(
        "INSERT INTO users (phone, role, status, is_phone_verified) VALUES (:phone, :role, 'active', true) RETURNING id"
    )
    if isinstance(db, Session):
        return db.scalar(statement, {"phone": phone, "role": role})
    with db.engine.begin() as conn:
        return conn.scalar(statement, {"phone": phone, "role": role})


def set_q48_gate(pg_db: PgDatabase, monkeypatch=None, *, passed: bool | None = True) -> None:  # noqa: ANN001
    """Stand-in for A3's Q48 gate (not delivered yet) in one test database.

    ``passed=None`` removes it (the geo checks then fail closed). ``monkeypatch`` also sets the Python side
    (``platform.service.q48_gate_status``); without it only the SQL function used by the 0053 trigger is set.
    """
    if monkeypatch is not None:
        import app.modules.platform.service as platform_service

        if passed is None:
            monkeypatch.delattr(platform_service, "q48_gate_status", raising=False)
        else:
            monkeypatch.setattr(platform_service, "q48_gate_status", lambda db: passed, raising=False)
    with pg_db.engine.begin() as conn:
        if passed is None:
            conn.execute(text("DROP FUNCTION IF EXISTS platform_q48_gate_passed()"))
        else:
            conn.execute(
                text(f"CREATE OR REPLACE FUNCTION platform_q48_gate_passed() RETURNS boolean LANGUAGE sql AS $$ SELECT {'true' if passed else 'false'} $$")
            )


def set_support_phone(monkeypatch, phone: str = "+998711234567") -> None:  # noqa: ANN001
    """Q87 (wave 7): production cannot switch ``passenger_enabled`` on without a reachable support phone.

    Tests that are about Q5/Q48 rather than about Q87 declare the precondition explicitly with this helper.
    The number is synthetic; the real one is a pending user decision and stays unset in the repository.
    """
    from app.modules.trust_support import config as support_config

    monkeypatch.setattr(support_config, "support_contacts", lambda settings=None: (True, phone, None))
