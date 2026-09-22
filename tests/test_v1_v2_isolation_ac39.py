"""AC39 / ADR-0006 §2, §4: a v1 client can neither see nor mutate a v2 object (A10b, wave 5).

Two halves, both checkable here:

1. **Structural** - v1 code (``app/api/v1/**``, the legacy ``app/services/*.py``) never reaches a v2 table. It may
   call a v2 module's ``service`` function (ADR-0006 §2 exceptions a/b: account deletion checks and the settings
   adapter), but it must not import a v2 model or name a v2 table in SQL. That boundary is what keeps a v2
   booking invisible to the frozen Android client: v1 endpoints read ``orders`` and nothing else.
2. **Runtime** - a v2 identifier handed to a v1 route resolves to nothing: an unknown numeric id is a v1 ``404``
   in the v1 envelope, and a v2 public id (``bkg_...``) is rejected by the path type before any query. No v1
   handler answers with, or edits, a v2 object.

The projection side of the same decision (v2 reading v1 read-only) is proven in
``tests/pg/ops/test_legacy_projection.py`` (AC37).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers the legacy mappers)
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app
from app.models import User

REPO_ROOT = Path(__file__).resolve().parents[1]
V1_SOURCE_DIRS = (REPO_ROOT / "app" / "api" / "v1", REPO_ROOT / "app" / "services")
# ADR-0006 §2: v1 may call these v2 *service* modules (read-only account-deletion checks, settings adapter).
ALLOWED_MODULE_IMPORTS = re.compile(r"app\.modules\.[a-z_]+(\.(service|schemas|adapters))?\b")
FORBIDDEN_MODULE_IMPORTS = re.compile(r"app\.modules\.[a-z_]+\.(models|repository|api)\b")


def _v2_table_names() -> set[str]:
    """Every table of the v2 modules: the legacy metadata minus the tables declared in app/models."""
    from app.modules import import_models

    import_models()
    legacy = {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if mapper.class_.__module__.startswith("app.models")
    }
    return {name for name in Base.metadata.tables if name not in legacy and name != "alembic_version"}


def _v1_sources() -> list[Path]:
    return [path for directory in V1_SOURCE_DIRS for path in sorted(directory.rglob("*.py"))]


def test_ac39_v1_code_never_imports_a_v2_model_or_repository() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _v1_sources():
        hits = FORBIDDEN_MODULE_IMPORTS.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(REPO_ROOT))] = sorted({hit[0] for hit in hits})
    assert offenders == {}, f"v1 code must reach v2 only through service functions (ADR-0006 §2): {offenders}"


def test_ac39_v1_code_never_queries_a_v2_table() -> None:
    """A v2 table name inside a *SQL string* of v1 code would be a direct read/write across the boundary.

    Prose is not code: ADR-0006 §2 expects v1 to *document* which v2 facts it asks the owning service for
    ("active v2 bookings", "wallet_accounts"), so only string literals that look like SQL are inspected.
    """
    v2_tables = _v2_table_names()
    assert {"bookings", "listings", "wallet_accounts"} <= v2_tables, "sanity: v2 tables were not collected"
    sql_reference = re.compile(
        r"\b(?:from|join|into|update|delete\s+from|table)\s+(?:public\.)?\"?([a-z_][a-z0-9_]*)\"?", re.IGNORECASE
    )
    offenders: dict[str, list[str]] = {}
    for path in _v1_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                named.update(name for name in sql_reference.findall(node.value) if name in v2_tables)
        if named:
            offenders[str(path.relative_to(REPO_ROOT))] = sorted(named)
    assert offenders == {}, f"v1 code must not query a v2 table (ADR-0006 §3, AC39): {offenders}"


@pytest.fixture()
def v1_client() -> tuple[TestClient, dict[str, str]]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    user = User(phone="+998930000001", role="client", status="active", is_phone_verified=True)
    session.add(user)
    session.commit()
    token = create_access_token(str(user.id))
    session.close()

    def override() -> object:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override
    client = TestClient(fastapi_app)
    try:
        yield client, {"Authorization": f"Bearer {token}"}
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


def test_ac39_v1_route_does_not_resolve_an_unknown_or_v2_identifier(v1_client) -> None:  # noqa: ANN001
    client, headers = v1_client

    unknown = client.get("/api/v1/client/orders/999999", headers=headers)
    assert unknown.status_code == 404
    body = unknown.json()
    assert body["success"] is False and body["error"]["code"]  # v1 envelope is unchanged

    # A v2 public id never reaches a v1 handler: the path type refuses it before any query, and v1 renders
    # that refusal in its own envelope (400 VALIDATION_ERROR), not as a v2 answer.
    v2_id = client.get("/api/v1/client/orders/bkg_01JQ8Z0000000000000000", headers=headers)
    assert v2_id.status_code == 400
    assert v2_id.json()["success"] is False

    # ... and no v1 mutation route accepts it either.
    cancelled = client.post("/api/v1/client/orders/bkg_01JQ8Z0000000000000000/cancel", headers=headers, json={})
    assert cancelled.status_code == 400
    assert cancelled.json()["success"] is False
