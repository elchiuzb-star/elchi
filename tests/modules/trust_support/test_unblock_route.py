"""S10 ``DELETE /api/v2/blocks/{blocked_user_id}`` without a database.

The route used to hand ``idempotency_key=None`` to ``run_command`` and never declared the header, so every unblock
was ``400 IDEMPOTENCY_KEY_REQUIRED`` and no client could ever lift a block. These tests pin that the header is part
of the published contract and that the key the client sends is the one the idempotency step receives. The
replay/claim itself is PostgreSQL (``tests/pg/trust_support/test_blocks_reports_fraud_pg.py``).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import app.api.v2.web as web
from app.api.v2.web import current_user_id, get_session
from app.main import app
from app.modules.platform.service import IdempotentResponse
from app.modules.trust_support import service as trust_service

ROUTE = "/api/v2/blocks/{blocked_user_id}"


class FakeSession:
    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture
def http() -> Iterator[TestClient]:
    def fake_session() -> Iterator[FakeSession]:
        yield FakeSession()

    app.dependency_overrides[current_user_id] = lambda: 7
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(current_user_id, None)
        app.dependency_overrides.pop(get_session, None)


def test_openapi_declares_the_idempotency_key_header() -> None:
    operation = app.openapi()["paths"][ROUTE]["delete"]
    headers = [p for p in operation.get("parameters", []) if p["in"] == "header"]
    assert [h["name"] for h in headers] == ["Idempotency-Key"]


def test_the_client_key_reaches_the_idempotency_step_and_the_block_is_lifted(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}
    lifted: list[tuple[int, str]] = []

    def fake_run_idempotent(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.update(kwargs)
        result = kwargs["handler"]()
        return IdempotentResponse(status_code=result.status_code, body=result.body, replayed=False)

    monkeypatch.setattr(web, "run_idempotent", fake_run_idempotent)
    monkeypatch.setattr(trust_service, "unblock_user",
                        lambda session, *, actor_user_id, blocked_public_id: lifted.append((actor_user_id, blocked_public_id)))

    response = http.delete("/api/v2/blocks/usr_abc", headers={"Idempotency-Key": "s10-unblock-0001"})

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {}
    assert seen["idempotency_key"] == "s10-unblock-0001"
    assert (seen["method"], seen["route_template"]) == ("DELETE", ROUTE)
    assert lifted == [(7, "usr_abc")]


def test_without_a_key_it_is_the_adr_0005_400_and_nothing_is_lifted(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(trust_service, "unblock_user", lambda *a, **k: pytest.fail("unblocked without a key"))
    response = http.delete("/api/v2/blocks/usr_abc")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
