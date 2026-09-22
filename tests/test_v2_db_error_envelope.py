"""Wave 2.1 (integrator): DB-raised errors on /api/v2 render the v2 ErrorEnvelope; v1 behaviour is unchanged."""

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.v2.web import db_error_to_domain_error
from app.contracts.errors import ErrorCode


class _Diag:
    def __init__(self, constraint_name: str | None, message_primary: str | None) -> None:
        self.constraint_name = constraint_name
        self.message_primary = message_primary


class _Orig(Exception):
    def __init__(self, sqlstate: str | None, constraint: str | None = None, message: str | None = None) -> None:
        super().__init__(message or "db error")
        self.sqlstate = sqlstate
        self.diag = _Diag(constraint, message)


def _integrity(sqlstate: str, constraint: str | None = None, message: str | None = None) -> IntegrityError:
    return IntegrityError("UPDATE x", {}, _Orig(sqlstate, constraint, message))


def test_constraint_rule_wins() -> None:
    error = db_error_to_domain_error(_integrity("23001", "trip_stops_locked", "trip 7 stops are locked"))
    assert error.code is ErrorCode.TRIP_STOPS_LOCKED
    assert error.details == {"reason": "trip_stops_locked"}


def test_legacy_trigger_message_and_no_leak() -> None:
    error = db_error_to_domain_error(_integrity("23001", None, "booking agreement snapshot is immutable"))
    assert error.code is ErrorCode.INTEGRITY_CONFLICT
    assert "immutable" not in str(error.details)


def test_connection_error_is_503() -> None:
    exc = OperationalError("SELECT 1", {}, _Orig(None), connection_invalidated=True)
    assert db_error_to_domain_error(exc).code is ErrorCode.SERVICE_UNAVAILABLE


def test_handler_applies_to_v2_paths_only() -> None:
    from app.main import create_app

    app = create_app()

    @app.get("/api/v2/__wave21_db_error")
    def _v2_route() -> None:
        raise _integrity("23505", "uq_demo", "duplicate key value")

    @app.get("/api/v1/__wave21_db_error")
    def _v1_route() -> None:
        raise _integrity("23505", "uq_demo", "duplicate key value")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v2/__wave21_db_error")
    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTEGRITY_CONFLICT"
    assert body["error"]["details"] == {"reason": "unique_violation"}
    assert "duplicate" not in response.text

    v1 = client.get("/api/v1/__wave21_db_error")
    assert v1.status_code == 500
    assert "INTEGRITY_CONFLICT" not in v1.text
