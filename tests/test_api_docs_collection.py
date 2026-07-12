import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"
API_GUIDE = ROOT / "docs" / "API_GUIDE.md"
POSTMAN_COLLECTION = ROOT / "docs" / "postman" / "intercity_mvp_api.postman_collection.json"
POSTMAN_ENVIRONMENT = ROOT / "docs" / "postman" / "intercity_mvp_local.postman_environment.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def top_level_folder_names(collection: dict) -> set[str]:
    return {item["name"] for item in collection["item"]}


def test_swagger_and_openapi_are_available() -> None:
    client = TestClient(app)

    docs = client.get("/docs")
    openapi = client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200
    data = openapi.json()
    assert data["info"]["title"] == "Intercity Parcel Delivery Marketplace API"
    assert data["info"]["version"] == "1.0.0-mvp"
    assert "cash only" in data["info"]["description"].lower()


def test_openapi_has_required_tags_and_no_removed_feature_tags() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    tags = {item["name"] for item in schema["tags"]}

    required_tags = {
        "Health",
        "Auth",
        "Files",
        "Cities",
        "Route Tariffs",
        "Client Orders",
        "Driver Profile",
        "Driver Orders",
        "Driver Bids",
        "Order Status",
        "Disputes",
        "Notifications",
        "Admin Orders",
        "Admin Drivers",
        "Admin Disputes",
        "Audit Logs",
    }
    removed_tags = {"Payments", "Escrow", "OTP", "QR", "Tracking", "Chat", "Maps", "Capacity", "Cargo Weight", "Cargo Size"}

    assert required_tags.issubset(tags)
    assert removed_tags.isdisjoint(tags)


def test_readme_env_example_and_api_guide_exist_with_mvp_docs() -> None:
    assert README.exists()
    assert ENV_EXAMPLE.exists()
    assert API_GUIDE.exists()

    readme_text = README.read_text(encoding="utf-8").lower()
    guide_text = API_GUIDE.read_text(encoding="utf-8").lower()
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "cash only" in readme_text
    assert "no `weight` or `size`" in readme_text
    assert "otp" in readme_text and "qr" in readme_text and "proof" in readme_text
    assert "driver route has no `departure_time` and no `capacity`" in readme_text
    assert "postman collection" in readme_text
    assert "elchi_database_url" in env_text.lower()
    assert "docs/postman/intercity_mvp_api.postman_collection.json" in guide_text
    assert "online payment" in guide_text
    assert "cargo weight" in guide_text


def test_postman_collection_and_environment_are_valid() -> None:
    collection = load_json(POSTMAN_COLLECTION)
    environment = load_json(POSTMAN_ENVIRONMENT)

    assert collection["info"]["name"] == "Intercity Parcel Delivery Marketplace API - MVP"
    assert collection["info"]["schema"].endswith("collection/v2.1.0/collection.json")
    assert environment["name"] == "Intercity MVP Local"
    assert any(item["key"] == "base_url" and item["value"] == "http://localhost:8000" for item in environment["values"])
    assert any(item["key"] == "client_access_token" for item in environment["values"])
    assert any(item["key"] == "driver_access_token" for item in environment["values"])
    assert any(item["key"] == "admin_access_token" for item in environment["values"])


def test_postman_collection_has_required_folders_and_no_removed_feature_folders() -> None:
    collection = load_json(POSTMAN_COLLECTION)
    folders = top_level_folder_names(collection)

    required_folders = {
        "01 Health",
        "02 Auth",
        "03 Files",
        "04 Cities and Tariffs",
        "05 Client Orders",
        "06 Driver Profile and Routes",
        "07 Driver Feed and Bids",
        "08 Select Driver",
        "09 Driver Order Status",
        "10 Client Confirm and Rating",
        "11 Disputes",
        "12 Notifications",
        "13 Admin Orders",
        "14 Admin Drivers",
        "15 Audit Logs",
    }
    removed_folders = {"Online Payments", "OTP Proof", "QR Proof", "GPS Tracking", "Chat", "Cargo Weight/Size", "Capacity"}

    assert required_folders == folders
    assert removed_folders.isdisjoint(folders)


def test_collection_order_payload_omits_removed_cargo_and_time_fields() -> None:
    collection_text = POSTMAN_COLLECTION.read_text(encoding="utf-8")
    forbidden_payload_fields = [
        '"cargo_weight"',
        '"cargo_size"',
        '"weight"',
        '"size"',
        '"pickup_time"',
        '"delivery_time"',
        '"departure_time"',
        '"capacity"',
    ]

    for field in forbidden_payload_fields:
        assert field not in collection_text
