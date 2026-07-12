from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, City, RouteTariff, User


@pytest.fixture()
def api_client() -> tuple[TestClient, dict[str, str]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    users = {
        "admin": User(phone="+998900000001", role="admin", is_phone_verified=True),
        "operator": User(phone="+998900000002", role="operator", is_phone_verified=True),
        "client": User(phone="+998900000003", role="client", is_phone_verified=True),
    }
    db.add_all(users.values())
    db.commit()
    for user in users.values():
        db.refresh(user)
    tokens = {role: create_access_token(str(user.id)) for role, user in users.items()}
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), tokens
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_city(client: TestClient, token: str, name_uz: str, is_active: bool = True) -> dict:
    response = client.post(
        "/api/v1/admin/cities",
        headers=headers(token),
        json={"name_uz": name_uz, "name_ru": f"{name_uz} RU", "region": "Test"},
    )
    assert response.status_code == 200
    city = response.json()["data"]
    if not is_active:
        patch = client.patch(
            f"/api/v1/admin/cities/{city['id']}",
            headers=headers(token),
            json={"is_active": False},
        )
        assert patch.status_code == 200
        city = patch.json()["data"]
    return city


def test_get_cities_returns_active_cities(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    create_city(client, tokens["admin"], "Toshkent")
    create_city(client, tokens["admin"], "Inactive City", is_active=False)

    response = client.get("/api/v1/cities")

    assert response.status_code == 200
    body = response.json()
    names = [city["name_uz"] for city in body["data"]["items"]]
    assert names == ["Toshkent"]
    assert body["data"]["pagination"] == {"page": 1, "limit": 20, "total": 1, "total_pages": 1}


def test_get_cities_supports_search(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    create_city(client, tokens["admin"], "Toshkent")
    create_city(client, tokens["admin"], "Samarqand")

    response = client.get("/api/v1/cities?search=samar")

    assert response.status_code == 200
    assert [city["name_uz"] for city in response.json()["data"]["items"]] == ["Samarqand"]


def test_city_search_trims_and_matches_region(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    client.post(
        "/api/v1/admin/cities",
        headers=headers(tokens["admin"]),
        json={"name_uz": "  Qo'qon  ", "name_ru": "Коканд", "region": "  Farg'ona   vodiysi "},
    )

    response = client.get("/api/v1/cities?search=  farg'ona   ")

    assert response.status_code == 200
    city = response.json()["data"]["items"][0]
    assert city["name_uz"] == "Qo'qon"
    assert city["region"] == "Farg'ona vodiysi"


def test_admin_can_create_city_and_operator_cannot(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client

    admin_response = client.post(
        "/api/v1/admin/cities",
        headers=headers(tokens["admin"]),
        json={"name_uz": "Buxoro"},
    )
    operator_response = client.post(
        "/api/v1/admin/cities",
        headers=headers(tokens["operator"]),
        json={"name_uz": "Navoiy"},
    )

    assert admin_response.status_code == 200
    assert admin_response.json()["data"]["is_active"] is True
    assert operator_response.status_code == 403


def test_operator_can_view_admin_city_detail(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    city = create_city(client, tokens["admin"], "Buxoro")

    response = client.get(f"/api/v1/admin/cities/{city['id']}", headers=headers(tokens["operator"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == city["id"]
    assert data["name_uz"] == "Buxoro"


def test_duplicate_city_is_rejected(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    create_city(client, tokens["admin"], "Andijon")

    response = client.post(
        "/api/v1/admin/cities",
        headers=headers(tokens["admin"]),
        json={"name_uz": "andijon"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CITY_ALREADY_EXISTS"


def test_duplicate_city_with_collapsed_whitespace_is_rejected(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    create_city(client, tokens["admin"], "Yangi  Toshkent")

    response = client.post(
        "/api/v1/admin/cities",
        headers=headers(tokens["admin"]),
        json={"name_uz": " yangi toshkent "},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CITY_ALREADY_EXISTS"


def test_admin_can_update_city_and_audit_log_is_written(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    city = create_city(client, tokens["admin"], "Namangan")

    response = client.patch(
        f"/api/v1/admin/cities/{city['id']}",
        headers=headers(tokens["admin"]),
        json={"region": "New Region"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["region"] == "New Region"

    with next(app.dependency_overrides[get_db]()) as db:
        actions = set(db.scalars(select(AuditLog.action)))
        assert "city_created" in actions
        assert "city_updated" in actions


def test_admin_can_create_route_tariff(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Toshkent")
    to_city = create_city(client, tokens["admin"], "Samarqand")

    response = client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={
            "from_city_id": from_city["id"],
            "to_city_id": to_city["id"],
            "suggested_price": 60000,
            "min_price": 50000,
            "max_price": 80000,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["from_city"]["name_uz"] == "Toshkent"
    assert response.json()["data"]["suggested_price"] == 60000
    assert response.json()["data"]["currency"] == "UZS"
    assert response.json()["data"]["is_active"] is True


def test_operator_can_view_admin_route_tariff_detail(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Toshkent")
    to_city = create_city(client, tokens["admin"], "Samarqand")
    create_response = client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={
            "from_city_id": from_city["id"],
            "to_city_id": to_city["id"],
            "suggested_price": 60000,
            "min_price": 50000,
            "max_price": 80000,
        },
    )
    tariff_id = create_response.json()["data"]["id"]

    response = client.get(f"/api/v1/admin/route-tariffs/{tariff_id}", headers=headers(tokens["operator"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == tariff_id
    assert data["from_city"]["name_uz"] == "Toshkent"
    assert data["to_city"]["name_uz"] == "Samarqand"


@pytest.mark.parametrize(
    ("payload_extra", "expected_message"),
    [
        ({"suggested_price": -1}, "Invalid input"),
        ({"suggested_price": 60000, "min_price": 70000}, "Invalid input"),
        ({"suggested_price": 90000, "max_price": 80000}, "Invalid input"),
    ],
)
def test_route_tariff_price_validation(
    api_client: tuple[TestClient, dict[str, str]],
    payload_extra: dict,
    expected_message: str,
) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Qarshi")
    to_city = create_city(client, tokens["admin"], "Jizzax")
    payload = {
        "from_city_id": from_city["id"],
        "to_city_id": to_city["id"],
        "suggested_price": 60000,
    }
    payload.update(payload_extra)

    response = client.post("/api/v1/admin/route-tariffs", headers=headers(tokens["admin"]), json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PRICE_RANGE"


def test_same_city_route_tariff_is_rejected(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    city = create_city(client, tokens["admin"], "Termiz")

    response = client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={"from_city_id": city["id"], "to_city_id": city["id"], "suggested_price": 60000},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SAME_CITY_ROUTE"


def test_duplicate_active_tariff_is_rejected(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Urganch")
    to_city = create_city(client, tokens["admin"], "Nukus")
    payload = {"from_city_id": from_city["id"], "to_city_id": to_city["id"], "suggested_price": 60000}

    assert client.post("/api/v1/admin/route-tariffs", headers=headers(tokens["admin"]), json=payload).status_code == 200
    response = client.post("/api/v1/admin/route-tariffs", headers=headers(tokens["admin"]), json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROUTE_TARIFF_ALREADY_EXISTS"


def test_route_tariff_patch_rejects_city_changes(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Bekobod")
    to_city = create_city(client, tokens["admin"], "Angren")
    other_city = create_city(client, tokens["admin"], "Ohangaron")
    create_response = client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={"from_city_id": from_city["id"], "to_city_id": to_city["id"], "suggested_price": 30000},
    )
    assert create_response.status_code == 200

    response = client.patch(
        f"/api/v1/admin/route-tariffs/{create_response.json()['data']['id']}",
        headers=headers(tokens["admin"]),
        json={"to_city_id": other_city["id"]},
    )

    assert response.status_code == 400


def test_inactive_tariff_allows_new_active_tariff_for_same_direction(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Olmaliq")
    to_city = create_city(client, tokens["admin"], "Chirchiq")
    payload = {"from_city_id": from_city["id"], "to_city_id": to_city["id"], "suggested_price": 30000}

    create_response = client.post("/api/v1/admin/route-tariffs", headers=headers(tokens["admin"]), json=payload)
    assert create_response.status_code == 200
    tariff_id = create_response.json()["data"]["id"]
    inactive_response = client.patch(
        f"/api/v1/admin/route-tariffs/{tariff_id}",
        headers=headers(tokens["admin"]),
        json={"is_active": False},
    )
    assert inactive_response.status_code == 200

    new_response = client.post("/api/v1/admin/route-tariffs", headers=headers(tokens["admin"]), json=payload)

    assert new_response.status_code == 200
    assert new_response.json()["data"]["id"] != tariff_id


def test_authenticated_user_can_get_suggested_price(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Guliston")
    to_city = create_city(client, tokens["admin"], "Fargona")
    client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={"from_city_id": from_city["id"], "to_city_id": to_city["id"], "suggested_price": 60000},
    )

    response = client.get(
        f"/api/v1/route-tariffs/suggested-price?from_city_id={from_city['id']}&to_city_id={to_city['id']}",
        headers=headers(tokens["client"]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert Decimal(str(data["suggested_price"])) == Decimal("60000")
    assert data["from_city"]["name_uz"] == "Guliston"
    assert data["currency"] == "UZS"


def test_anonymous_user_cannot_get_suggested_price(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, _tokens = api_client

    response = client.get("/api/v1/route-tariffs/suggested-price?from_city_id=1&to_city_id=2")

    assert response.status_code == 401


def test_missing_tariff_returns_null_suggested_price(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Qo'qon")
    to_city = create_city(client, tokens["admin"], "Navoiy")

    response = client.get(
        f"/api/v1/route-tariffs/suggested-price?from_city_id={from_city['id']}&to_city_id={to_city['id']}",
        headers=headers(tokens["client"]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["suggested_price"] is None
    assert response.json()["data"]["is_active"] is False
    assert response.json()["data"]["currency"] == "UZS"
    assert response.json()["message"] == "No active tariff found for this route"


def test_reverse_route_without_tariff_returns_null_price(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "Denov")
    to_city = create_city(client, tokens["admin"], "Shahrisabz")
    client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={"from_city_id": from_city["id"], "to_city_id": to_city["id"], "suggested_price": 60000},
    )

    response = client.get(
        f"/api/v1/route-tariffs/suggested-price?from_city_id={to_city['id']}&to_city_id={from_city['id']}",
        headers=headers(tokens["client"]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["suggested_price"] is None


def test_operator_can_view_tariffs_but_cannot_update(api_client: tuple[TestClient, dict[str, str]]) -> None:
    client, tokens = api_client
    from_city = create_city(client, tokens["admin"], "City A")
    to_city = create_city(client, tokens["admin"], "City B")
    create_response = client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={"from_city_id": from_city["id"], "to_city_id": to_city["id"], "suggested_price": 60000},
    )
    tariff_id = create_response.json()["data"]["id"]

    view_response = client.get("/api/v1/admin/route-tariffs", headers=headers(tokens["operator"]))
    update_response = client.patch(
        f"/api/v1/admin/route-tariffs/{tariff_id}",
        headers=headers(tokens["operator"]),
        json={"suggested_price": 65000},
    )

    assert view_response.status_code == 200
    assert view_response.json()["data"]["pagination"]["total"] == 1
    assert update_response.status_code == 403

    with next(app.dependency_overrides[get_db]()) as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "route_tariff_created")) is not None
