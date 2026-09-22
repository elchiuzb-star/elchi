"""Unit tests: v2 commands retry deadlock/serialization failures, then answer 503 (wave 1.5 BR fix)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import DBAPIError

import app.modules.platform.service as platform_service
from app.api.v2.web import run_versioned
from app.contracts.errors import DomainError, ErrorCode


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def deadlock() -> DBAPIError:
    return DBAPIError("UPDATE ...", {}, Exception("deadlock detected"))


@pytest.fixture
def retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_service, "is_retryable_db_error", lambda exc: isinstance(exc, DBAPIError))


def test_versioned_command_is_retried_after_a_deadlock(retryable: None) -> None:
    session = FakeSession()
    calls = []

    def handler() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise deadlock()
        return "ok"

    assert run_versioned(session, handler) == "ok"  # type: ignore[arg-type]
    assert (len(calls), session.commits) == (3, 1)
    assert session.rollbacks >= 2


def test_retries_are_bounded_then_service_unavailable(retryable: None) -> None:
    session = FakeSession()
    calls = []

    def handler() -> str:
        calls.append(1)
        raise deadlock()

    with pytest.raises(DomainError) as info:
        run_versioned(session, handler)  # type: ignore[arg-type]
    assert info.value.code is ErrorCode.SERVICE_UNAVAILABLE and info.value.http_status == 503
    assert len(calls) == 3 and session.commits == 0


def test_domain_errors_are_not_retried(retryable: None) -> None:
    session = FakeSession()
    calls = []

    def handler() -> str:
        calls.append(1)
        raise DomainError(ErrorCode.VERSION_CONFLICT)

    with pytest.raises(DomainError):
        run_versioned(session, handler)  # type: ignore[arg-type]
    assert len(calls) == 1 and session.rollbacks >= 1
