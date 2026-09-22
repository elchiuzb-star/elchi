from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, City, DriverDocument, DriverProfile, DriverRoute, User
from app.utils.file_access import normalize_storage_key


def upload_document_file(client: TestClient, token: str, document_type: str, filename: str = "doc.jpg") -> str:
    response = client.post(
        "/api/v1/files/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"type": document_type},
        files={"file": (filename, b"\xff\xd8\xff\xe0fake-document-bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    return response.json()["data"]["file_url"]


@pytest.fixture()
def driver_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, str], sessionmaker]:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "public_upload_base_url", "/uploads")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    driver = User(phone="+998910000001", role="driver", status="active", is_phone_verified=True)
    other_driver = User(phone="+998910000002", role="driver", status="active", is_phone_verified=True)
    client_user = User(phone="+998910000003", role="client", status="active", is_phone_verified=True)
    blocked_driver = User(phone="+998910000004", role="driver", status="blocked", is_phone_verified=True)
    db.add_all([driver, other_driver, client_user, blocked_driver])
    db.commit()
    for user in [driver, other_driver, client_user, blocked_driver]:
        db.refresh(user)
    tokens = {
        "driver": create_access_token(str(driver.id)),
        "other_driver": create_access_token(str(other_driver.id)),
        "client": create_access_token(str(client_user.id)),
        "blocked_driver": create_access_token(str(blocked_driver.id)),
    }
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), tokens, TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def set_driver_status(session_factory: sessionmaker, phone: str, verification_status: str) -> DriverProfile:
    db = session_factory()
    user = db.scalar(select(User).where(User.phone == phone))
    profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
    if profile is None:
        profile = DriverProfile(user_id=user.id, verification_status=verification_status)
        db.add(profile)
    profile.verification_status = verification_status
    db.commit()
    db.refresh(profile)
    db.close()
    return profile


def create_city_pair(session_factory: sessionmaker, inactive_to_city: bool = False) -> tuple[int, int]:
    db = session_factory()
    suffix = db.query(City).count() + 1
    from_city = City(
        name=f"Toshkent {suffix}",
        name_uz=f"Toshkent {suffix}",
        name_ru=f"Tashkent {suffix}",
        region="Toshkent",
        requires_district=False,
        is_active=True,
    )
    to_city = City(
        name=f"Samarqand {suffix}",
        name_uz=f"Samarqand {suffix}",
        name_ru=f"Samarkand {suffix}",
        region="Samarqand",
        requires_district=False,
        is_active=not inactive_to_city,
    )
    db.add_all([from_city, to_city])
    db.commit()
    from_id, to_id = from_city.id, to_city.id
    db.close()
    return from_id, to_id


def test_driver_can_get_profile_and_profile_auto_created(driver_client) -> None:
    client, tokens, session_factory = driver_client

    response = client.get("/api/v1/driver/profile", headers=headers(tokens["driver"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verification_status"] == "new"
    assert data["rating"] == 0
    assert data["total_orders"] == 0
    assert data["is_available"] is False

    db = session_factory()
    assert db.scalar(select(DriverProfile)) is not None
    db.close()


def test_driver_can_update_own_profile_but_not_protected_fields(driver_client) -> None:
    client, tokens, _session_factory = driver_client

    response = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={
            "full_name": "Ali Valiyev",
            "car_model": "Cobalt",
            "plate_number": "01 a 123 bc",
            "car_color": "Oq",
            "verification_status": "approved",
            "rating": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["full_name"] == "Ali Valiyev"
    assert data["plate_number"] == "01 a 123 bc"
    assert data["plate_number_normalized"] == "01A123BC"
    assert data["verification_status"] == "new"
    assert "rating" not in data


def test_approved_driver_cannot_change_vehicle_but_can_change_name(driver_client) -> None:
    client, tokens, session_factory = driver_client

    # Set up vehicle details while still unapproved.
    setup = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={"full_name": "Ali Valiyev", "car_model": "Cobalt", "plate_number": "01 a 123 bc", "car_color": "Oq"},
    )
    assert setup.status_code == 200

    set_driver_status(session_factory, "+998910000001", "approved")

    # Changing a vehicle field is rejected for approved drivers.
    blocked = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={"car_model": "Malibu"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "DRIVER_VEHICLE_LOCKED"
    assert "car_model" in blocked.json()["error"]["details"]["locked_fields"]

    # Plate change is rejected too.
    blocked_plate = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={"plate_number": "02 b 456 cd"},
    )
    assert blocked_plate.status_code == 403
    assert blocked_plate.json()["error"]["code"] == "DRIVER_VEHICLE_LOCKED"

    # Name change is allowed.
    ok = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={"full_name": "Ali Karimov"},
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["full_name"] == "Ali Karimov"
    assert ok.json()["data"]["car_model"] == "Cobalt"

    # Resending unchanged vehicle values alongside a name change does not trip the lock.
    ok_same = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={"full_name": "Ali Boboev", "car_model": "Cobalt", "plate_number": "01 a 123 bc", "car_color": "Oq"},
    )
    assert ok_same.status_code == 200
    assert ok_same.json()["data"]["full_name"] == "Ali Boboev"


def test_duplicate_plate_number_normalized_is_rejected(driver_client) -> None:
    client, tokens, session_factory = driver_client
    client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["other_driver"]),
        json={"plate_number": "01-A-123-BC"},
    )

    response = client.patch(
        "/api/v1/driver/profile",
        headers=headers(tokens["driver"]),
        json={"plate_number": "01 a 123 bc"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLATE_NUMBER_ALREADY_EXISTS"
    db = session_factory()
    assert db.scalar(select(DriverProfile).where(DriverProfile.plate_number_normalized == "01A123BC")) is not None
    db.close()


def test_non_driver_and_anonymous_cannot_access_driver_profile(driver_client) -> None:
    client, tokens, _session_factory = driver_client

    anonymous = client.get("/api/v1/driver/profile")
    non_driver = client.get("/api/v1/driver/profile", headers=headers(tokens["client"]))

    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == {"code": "UNAUTHORIZED", "message": "Authentication required"}
    assert non_driver.status_code == 403
    assert non_driver.json()["error"] == {"code": "FORBIDDEN", "message": "Driver role required"}


def test_driver_can_submit_document_and_status_becomes_pending(driver_client) -> None:
    client, tokens, session_factory = driver_client

    file_url = upload_document_file(client, tokens["driver"], "passport")
    response = client.post(
        "/api/v1/driver/documents",
        headers=headers(tokens["driver"]),
        json={"document_type": "passport", "file_url": file_url},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"

    db = session_factory()
    user = db.scalar(select(User).where(User.phone == "+998910000001"))
    profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
    assert profile.verification_status == "pending"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "driver_document_uploaded")) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "driver_submitted_for_review")) is not None
    db.close()


def test_uploading_same_document_type_replaces_existing_record(driver_client) -> None:
    client, tokens, session_factory = driver_client

    old_url = upload_document_file(client, tokens["driver"], "license", "old.jpg")
    new_url = upload_document_file(client, tokens["driver"], "license", "new.jpg")
    first = client.post(
        "/api/v1/driver/documents",
        headers=headers(tokens["driver"]),
        json={"document_type": "license", "file_url": old_url},
    )
    second = client.post(
        "/api/v1/driver/documents",
        headers=headers(tokens["driver"]),
        json={"document_type": "license", "file_url": new_url},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["document_id"] == second.json()["data"]["document_id"]
    db = session_factory()
    docs = list(db.scalars(select(DriverDocument).where(DriverDocument.document_type == "license")))
    assert len(docs) == 1
    assert docs[0].file_url == "/uploads/" + normalize_storage_key(new_url)
    db.close()


def test_invalid_document_type_is_rejected(driver_client) -> None:
    client, tokens, _session_factory = driver_client

    response = client.post(
        "/api/v1/driver/documents",
        headers=headers(tokens["driver"]),
        json={"document_type": "pickup_proof", "file_url": "/uploads/passport/2026/06/doc.jpg"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DRIVER_DOCUMENT_INVALID_TYPE"


def test_invalid_document_mime_and_size_are_rejected(driver_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, tokens, _session_factory = driver_client

    invalid_type = client.post(
        "/api/v1/driver/documents",
        headers=headers(tokens["driver"]),
        json={
            "document_type": "passport",
            "file_url": "/uploads/passport/2026/06/doc.gif",
            "mime_type": "image/gif",
        },
    )
    too_large = client.post(
        "/api/v1/driver/documents",
        headers=headers(tokens["driver"]),
        json={
            "document_type": "passport",
            "file_url": "/uploads/passport/2026/06/doc.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 11 * 1024 * 1024,
        },
    )

    assert invalid_type.status_code == 400
    assert invalid_type.json()["error"]["code"] == "DRIVER_DOCUMENT_INVALID_TYPE"
    assert too_large.status_code == 400
    assert too_large.json()["error"]["code"] == "DRIVER_DOCUMENT_TOO_LARGE"


def test_driver_availability_requires_approval(driver_client) -> None:
    client, tokens, session_factory = driver_client

    new_response = client.patch("/api/v1/driver/availability", headers=headers(tokens["driver"]), json={"is_available": True})
    assert new_response.status_code == 400
    assert new_response.json()["error"]["code"] == "DRIVER_NOT_APPROVED"

    set_driver_status(session_factory, "+998910000001", "approved")
    approved_response = client.patch("/api/v1/driver/availability", headers=headers(tokens["driver"]), json={"is_available": True})
    assert approved_response.status_code == 200
    assert approved_response.json()["data"]["is_available"] is True

    set_driver_status(session_factory, "+998910000001", "rejected")
    rejected_response = client.patch("/api/v1/driver/availability", headers=headers(tokens["driver"]), json={"is_available": True})
    assert rejected_response.status_code == 400

    blocked_response = client.patch(
        "/api/v1/driver/availability",
        headers=headers(tokens["blocked_driver"]),
        json={"is_available": True},
    )
    assert blocked_response.status_code == 403
    assert blocked_response.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}


def test_approved_driver_can_create_route_and_unapproved_cannot(driver_client) -> None:
    client, tokens, session_factory = driver_client
    from_city_id, to_city_id = create_city_pair(session_factory)

    unapproved = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": from_city_id, "to_city_id": to_city_id},
    )
    assert unapproved.status_code == 400
    assert unapproved.json()["error"]["code"] == "DRIVER_NOT_APPROVED"

    set_driver_status(session_factory, "+998910000001", "approved")
    approved = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": from_city_id, "to_city_id": to_city_id},
    )
    assert approved.status_code == 200
    data = approved.json()["data"]
    assert data["status"] == "available"
    assert data["from_city"]["name_uz"].startswith("Toshkent")
    assert "departure_time" not in data
    assert "capacity" not in data


def test_route_validation_same_city_inactive_city_and_duplicate(driver_client) -> None:
    client, tokens, session_factory = driver_client
    set_driver_status(session_factory, "+998910000001", "approved")
    from_city_id, to_city_id = create_city_pair(session_factory)

    same_city = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": from_city_id, "to_city_id": from_city_id},
    )
    assert same_city.status_code == 400

    inactive_from, inactive_to = create_city_pair(session_factory, inactive_to_city=True)
    inactive = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": inactive_from, "to_city_id": inactive_to},
    )
    assert inactive.status_code == 400
    assert inactive.json()["error"]["code"] == "CITY_INACTIVE"

    first = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": from_city_id, "to_city_id": to_city_id},
    )
    duplicate = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": from_city_id, "to_city_id": to_city_id},
    )
    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ROUTE_ALREADY_EXISTS"


def test_driver_can_list_update_and_disable_own_routes(driver_client) -> None:
    client, tokens, session_factory = driver_client
    set_driver_status(session_factory, "+998910000001", "approved")
    from_city_id, to_city_id = create_city_pair(session_factory)
    create_response = client.post(
        "/api/v1/driver/routes",
        headers=headers(tokens["driver"]),
        json={"from_city_id": from_city_id, "to_city_id": to_city_id},
    )
    route_id = create_response.json()["data"]["id"]

    list_response = client.get("/api/v1/driver/routes", headers=headers(tokens["driver"]))
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["id"] == route_id

    invalid_status = client.patch(
        f"/api/v1/driver/routes/{route_id}/status",
        headers=headers(tokens["driver"]),
        json={"status": "deleted"},
    )
    assert invalid_status.status_code == 400

    update_response = client.patch(
        f"/api/v1/driver/routes/{route_id}/status",
        headers=headers(tokens["driver"]),
        json={"status": "busy"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"] == {"route_id": route_id, "status": "busy"}

    delete_response = client.delete(f"/api/v1/driver/routes/{route_id}", headers=headers(tokens["driver"]))
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"route_id": route_id, "status": "deleted"}

    list_after_delete = client.get("/api/v1/driver/routes", headers=headers(tokens["driver"]))
    assert all(route["id"] != route_id for route in list_after_delete.json()["data"])


def test_driver_cannot_update_another_drivers_route(driver_client) -> None:
    client, tokens, session_factory = driver_client
    set_driver_status(session_factory, "+998910000001", "approved")
    other_profile = set_driver_status(session_factory, "+998910000002", "approved")
    from_city_id, to_city_id = create_city_pair(session_factory)

    db = session_factory()
    route = DriverRoute(driver_id=other_profile.id, from_city_id=from_city_id, to_city_id=to_city_id, status="available")
    db.add(route)
    db.commit()
    route_id = route.id
    db.close()

    response = client.patch(
        f"/api/v1/driver/routes/{route_id}/status",
        headers=headers(tokens["driver"]),
        json={"status": "busy"},
    )

    assert response.status_code == 404
