"""PostgreSQL fixtures for A13 operations tests, built on A4's booking world (``bw``) with the real A1-A4 services."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.db.session import get_db
from app.modules.operations import models as operations_models  # noqa: F401  (registers the wave 4 tables)
from tests.pg.bookings.conftest import (  # noqa: F401  (shared fixtures and helpers)
    BW,
    accept,
    act,
    auth,
    bw,
    domain_error,
    enable_flags,
    parcel_request_body,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    run_trip_action,
    scalar,
    world,
)


@pytest.fixture
def ops_client(bw: BW) -> Iterator[TestClient]:
    """Test-local app with the operations router (the integrator mounts it under /api/v2)."""
    from app.api.v2.web import db_error_handler, domain_error_handler
    from app.modules.operations.api import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    async def server_error(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": ErrorCode.SERVER_ERROR.value,
                                                                                  "message": "server error"}})

    app.add_exception_handler(Exception, server_error)

    def override_db() -> Iterator[Session]:
        session = bw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
