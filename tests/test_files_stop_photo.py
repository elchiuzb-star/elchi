"""`stop_photo` upload type (wave 1.6 integration, Q27/Q47): staff with ops.corridor_manage only.

Existing upload types keep their v1 behaviour (frozen clients never send `stop_photo`).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User
from app.utils import file_access
from app.utils.file_validation import ALLOWED_UPLOAD_TYPES, IMAGE_ONLY_TYPES

JPEG = b"\xff\xd8\xff\xe0stop-photo"


@pytest.fixture()
def clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, dict[str, tuple[int, str]]]]:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    users: dict[str, tuple[int, str]] = {}
    with session_factory() as db:
        for index, role in enumerate(("admin", "operator", "client", "driver"), start=1):
            user = User(phone=f"+99890000{index:04d}", role=role, status="active", is_phone_verified=True)
            db.add(user)
            db.commit()
            users[role] = (user.id, create_access_token(str(user.id)))

    def override_get_db() -> Iterator:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), users
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _upload(client: TestClient, token: str, upload_type: str, content: bytes = JPEG, filename: str = "stop.jpg"):  # noqa: ANN202
    return client.post(
        "/api/v1/files/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"type": upload_type},
        files={"file": (filename, content, "image/jpeg")},
    )


def test_stop_photo_is_an_image_only_upload_type() -> None:
    assert "stop_photo" in ALLOWED_UPLOAD_TYPES and "stop_photo" in IMAGE_ONLY_TYPES


def test_staff_upload_attaches_as_stop_evidence(clients) -> None:  # noqa: ANN001
    client, users = clients
    admin_id, admin_token = users["admin"]
    response = _upload(client, admin_token, "stop_photo")
    assert response.status_code == 200, response.text
    file_url = response.json()["data"]["file_url"]
    assert response.json()["data"]["type"] == "stop_photo"
    assert file_url.startswith("/api/v1/files/stop_photo/")

    # H0 attach rules with the geo expectation (expected_upload_type="stop_photo").
    stored = file_access.resolve_attachment(file_url, user_id=admin_id, expected_upload_type="stop_photo")
    assert stored is not None and "stop_photo/" in stored
    from app.modules.geo import service as geo_service

    assert geo_service._resolve_meeting_photo(file_url, actor_user_id=admin_id) == stored
    # Someone else cannot attach the admin's photo.
    other_id, _ = users["operator"]
    with pytest.raises(file_access.FileReferenceError):
        file_access.resolve_attachment(file_url, user_id=other_id, expected_upload_type="stop_photo")


def test_stop_photo_rejects_non_images_for_staff(clients) -> None:  # noqa: ANN001
    client, users = clients
    response = _upload(client, users["admin"][1], "stop_photo", content=b"%PDF-1.4 x", filename="stop.pdf")
    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.parametrize("role", ["client", "driver", "operator"])
def test_users_without_corridor_manage_get_v1_403(clients, role: str) -> None:  # noqa: ANN001
    client, users = clients
    response = _upload(client, users[role][1], "stop_photo")
    assert response.status_code == 403
    assert response.json() == {
        "success": False,
        "error": {"code": "FORBIDDEN", "message": "Not allowed to upload this file type"},
    }


def test_existing_upload_types_unchanged_for_non_staff(clients) -> None:  # noqa: ANN001
    client, users = clients
    response = _upload(client, users["client"][1], "cargo_photo")
    assert response.status_code == 200 and response.json()["data"]["type"] == "cargo_photo"
    invalid = _upload(client, users["client"][1], "not_a_type")
    assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"
