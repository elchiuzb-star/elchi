"""Envelope.warnings through the real v2 command runner on PostgreSQL, including idempotent replay (Q43)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.api.v2.web import run_command
from app.contracts.contact_filter import CONTACT_FILTER_VERSION, scan
from app.contracts.dto import ContractModel
from app.contracts.errors import WARNING_CATALOGUE, WarningCode
from app.contracts.idempotency import IDEMPOTENT_REPLAY_HEADER
from app.models import User
from tests.pg.conftest import PgDatabase

pytestmark = pytest.mark.pg


class _EchoBody(ContractModel):
    text: str


class _EchoDTO(ContractModel):
    id: str
    text: str


@pytest.fixture
def echo_client(pg_db: PgDatabase):  # noqa: ANN201
    with pg_db.session() as db:
        user = User(phone="+998934000077", role="client", status="active", is_phone_verified=True)
        db.add(user)
        db.commit()
        user_id = user.id
    calls: list[str] = []
    local = FastAPI()

    @local.post("/api/v2/echo/{kind}")
    def echo(kind: str, body: _EchoBody, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):  # noqa: ANN202
        session = pg_db.session()
        try:

            def handler():  # noqa: ANN202
                calls.append(kind)
                result = scan(body.text)
                dto = _EchoDTO(id="ech_1", text=result.masked_text)
                if kind == "plain":
                    return dto
                warnings = (
                    [{"code": WarningCode.CONTACT_INFO_MASKED.value, "field": "text", **result.warning_details()}]
                    if result.has_contact
                    else []
                )
                return dto, warnings

            return run_command(
                request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                handler=handler, success_status=201, resource_type="echo",
            )
        finally:
            session.close()

    return TestClient(local), calls


def test_warnings_are_in_envelope_and_replayed(echo_client) -> None:  # noqa: ANN001
    client, calls = echo_client
    headers = {"Idempotency-Key": "warn-replay-0001"}
    first = client.post("/api/v2/echo/filtered", json={"text": "tel 90 123 45 67"}, headers=headers)
    assert first.status_code == 201, first.text
    payload = first.json()
    assert payload["success"] is True and "90 123" not in payload["data"]["text"]
    assert payload["warnings"] == [
        {
            "code": "CONTACT_INFO_MASKED",
            "message": WARNING_CATALOGUE[WarningCode.CONTACT_INFO_MASKED],
            "field": "text",
            "details": {"categories": ["phone"], "match_count": 1, "filter_version": CONTACT_FILTER_VERSION},
        }
    ]

    replay = client.post("/api/v2/echo/filtered", json={"text": "tel 90 123 45 67"}, headers=headers)
    assert replay.status_code == 201
    assert replay.headers.get(IDEMPOTENT_REPLAY_HEADER) == "true"
    assert replay.json() == payload
    assert calls == ["filtered"]  # replay did not run the handler again


def test_plain_dto_and_clean_text_have_no_warnings_key(echo_client) -> None:  # noqa: ANN001
    client, _calls = echo_client
    plain = client.post("/api/v2/echo/plain", json={"text": "90 123 45 67"}, headers={"Idempotency-Key": "warn-plain-0001"})
    clean = client.post("/api/v2/echo/filtered", json={"text": "200 000 so'm"}, headers={"Idempotency-Key": "warn-clean-0001"})
    assert plain.status_code == clean.status_code == 201
    assert "warnings" not in plain.json() and "warnings" not in clean.json()
