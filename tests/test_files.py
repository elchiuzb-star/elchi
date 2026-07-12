from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User


@pytest.fixture()
def upload_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str, Path]:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    monkeypatch.setattr(settings, "max_image_upload_mb", 5)
    monkeypatch.setattr(settings, "max_document_upload_mb", 10)
    monkeypatch.setattr(settings, "public_upload_base_url", "/uploads")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = User(phone="+998901234567", role="client", is_phone_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), token, upload_dir
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def upload(
    client: TestClient,
    token: str,
    upload_type: str,
    filename: str,
    content: bytes,
    mime_type: str,
):
    return client.post(
        "/api/v1/files/upload",
        headers=auth_headers(token),
        data={"type": upload_type},
        files={"file": (filename, content, mime_type)},
    )


def test_authenticated_user_can_upload_valid_cargo_photo(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, upload_dir = upload_client

    response = upload(client, token, "cargo_photo", "photo.jpg", b"fake-image", "image/jpeg")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "File uploaded successfully"
    assert body["data"]["type"] == "cargo_photo"
    assert body["data"]["mime_type"] == "image/jpeg"
    assert body["data"]["size_bytes"] == len(b"fake-image")
    assert body["data"]["original_filename"] == "photo.jpg"
    assert body["data"]["file_url"].startswith("/uploads/cargo_photo/")
    assert not body["data"]["file_url"].endswith("photo.jpg")

    relative_path = body["data"]["file_url"].removeprefix("/uploads/").replace("/", "\\")
    assert (upload_dir / relative_path).exists()
    assert (upload_dir / "cargo_photo").exists()


def test_anonymous_user_cannot_upload(upload_client: tuple[TestClient, str, Path]) -> None:
    client, _token, _upload_dir = upload_client

    response = client.post(
        "/api/v1/files/upload",
        data={"type": "cargo_photo"},
        files={"file": ("photo.jpg", b"fake-image", "image/jpeg")},
    )

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "error": {"code": "UNAUTHORIZED", "message": "Authentication required"},
    }


def test_invalid_type_is_rejected(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, _upload_dir = upload_client

    response = upload(client, token, "pickup_proof", "photo.jpg", b"fake-image", "image/jpeg")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "allowed_types" in response.json()["error"]["details"]


def test_invalid_extension_is_rejected(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, _upload_dir = upload_client

    response = upload(client, token, "cargo_photo", "photo.gif", b"fake-image", "image/gif")

    assert response.status_code == 400
    assert response.json()["error"]["message"] in {"Invalid file extension", "Invalid MIME type"}


def test_dangerous_extension_is_rejected(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, _upload_dir = upload_client

    response = upload(client, token, "passport", "payload.exe", b"MZ", "application/octet-stream")

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Dangerous file extension is not allowed"


def test_too_large_file_is_rejected(
    upload_client: tuple[TestClient, str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, token, _upload_dir = upload_client
    monkeypatch.setattr(settings, "max_image_upload_mb", 0)

    response = upload(client, token, "cargo_photo", "photo.jpg", b"x", "image/jpeg")

    assert response.status_code == 413
    assert response.json() == {
        "success": False,
        "error": {"code": "FILE_TOO_LARGE", "message": "File size exceeds allowed limit"},
    }


def test_empty_file_is_rejected(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, _upload_dir = upload_client

    response = upload(client, token, "cargo_photo", "photo.jpg", b"", "image/jpeg")

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "File is empty"


def test_passport_accepts_pdf(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, _upload_dir = upload_client

    response = upload(client, token, "passport", "passport.pdf", b"%PDF-1.4", "application/pdf")

    assert response.status_code == 200
    assert response.json()["data"]["file_url"].endswith(".pdf")


def test_cargo_photo_rejects_pdf(upload_client: tuple[TestClient, str, Path]) -> None:
    client, token, _upload_dir = upload_client

    response = upload(client, token, "cargo_photo", "cargo.pdf", b"%PDF-1.4", "application/pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
