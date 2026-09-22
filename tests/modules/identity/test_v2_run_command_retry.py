"""Unit tests (N9): ``run_command`` retries deadlock/serialization failures like ``run_versioned``, then 503."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DBAPIError

import app.api.v2.web as web
import app.modules.platform.service as platform_service
from app.contracts.errors import DomainError, ErrorCode
from app.modules.platform.service import IdempotentResponse


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def fake_request() -> SimpleNamespace:
    return SimpleNamespace(method="POST", scope={}, url=SimpleNamespace(path="/api/v2/probe"), path_params={})


def deadlock() -> DBAPIError:
    return DBAPIError("UPDATE ...", {}, Exception("deadlock detected"))


@pytest.fixture
def retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_service, "is_retryable_db_error", lambda exc: isinstance(exc, DBAPIError))


def _call(session: FakeSession):  # noqa: ANN202
    return web.run_command(
        fake_request(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
        actor_user_id=1,
        idempotency_key="probe-key-0001",
        body=None,
        handler=lambda: None,  # type: ignore[arg-type,return-value]
    )


def test_run_command_retries_then_succeeds(retryable: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run_idempotent(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append(1)
        if len(calls) < 3:
            raise deadlock()
        return IdempotentResponse(status_code=201, body={"success": True}, replayed=False)

    monkeypatch.setattr(web, "run_idempotent", fake_run_idempotent)
    session = FakeSession()
    response = _call(session)
    assert response.status_code == 201
    assert (len(calls), session.commits) == (3, 1) and session.rollbacks >= 2


def test_run_command_retries_are_bounded(retryable: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def always_deadlock(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append(1)
        raise deadlock()

    monkeypatch.setattr(web, "run_idempotent", always_deadlock)
    session = FakeSession()
    with pytest.raises(DomainError) as info:
        _call(session)
    assert info.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert len(calls) == 3 and session.commits == 0


def test_run_command_does_not_retry_domain_errors(retryable: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def reused(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append(1)
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REUSED)

    monkeypatch.setattr(web, "run_idempotent", reused)
    session = FakeSession()
    with pytest.raises(DomainError):
        _call(session)
    assert len(calls) == 1 and session.rollbacks >= 1
