"""Private uploads: signed download URLs, attachment ownership, no public mount."""

import json
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import Settings, settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, Bid, City, DriverDocument, DriverProfile, DriverRoute, Order, User
from app.services.account_deletion_service import _remove_upload
from app.utils import file_access
from app.utils.file_access import (
    normalize_storage_key,
    resolve_upload_path,
    sign_file_key,
    signed_file_url,
    verify_file_signature,
)

FILES_PREFIX = "/api/v1/files/"
JPEG_BYTES = b"\xff\xd8\xff\xe0jpeg-bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\npng-bytes"
WEBP_BYTES = b"RIFF\x10\x00\x00\x00WEBPVP8 webp-bytes"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    monkeypatch.setattr(settings, "public_upload_base_url", "/uploads")
    monkeypatch.setattr(settings, "file_url_signing_key", None)
    monkeypatch.setattr(settings, "file_url_ttl_seconds", 900)
    monkeypatch.setattr(settings, "max_image_upload_mb", 5)
    monkeypatch.setattr(settings, "max_document_upload_mb", 10)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = session_factory()
    users = {
        "client": User(phone="+998930000001", role="client", status="active", is_phone_verified=True),
        "other_client": User(phone="+998930000002", role="client", status="active", is_phone_verified=True),
        "driver": User(phone="+998930000003", role="driver", status="active", is_phone_verified=True),
        "admin": User(phone="+998930000004", role="admin", status="active", is_phone_verified=True),
        "operator": User(phone="+998930000005", role="operator", status="active", is_phone_verified=True),
    }
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    db.add_all([*users.values(), from_city, to_city])
    db.commit()
    profile = DriverProfile(user_id=users["driver"].id, verification_status="new")
    db.add(profile)
    db.commit()
    ids = {name: user.id for name, user in users.items()}
    ids.update({"driver_profile": profile.id, "from_city": from_city.id, "to_city": to_city.id})
    tokens = {name: create_access_token(str(user.id)) for name, user in users.items()}
    db.close()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield SimpleNamespace(
            client=TestClient(app),
            tokens=tokens,
            ids=ids,
            session_factory=session_factory,
            upload_dir=upload_dir,
            tmp_path=tmp_path,
        )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_stored_file(upload_dir: Path, key: str, content: bytes = b"stored-bytes") -> Path:
    path = upload_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def legacy_key(upload_type: str = "passport", ext: str = "jpg") -> str:
    return f"{upload_type}/2026/06/{uuid4().hex}.{ext}"


def upload(env, token_name: str, upload_type: str = "cargo_photo", content: bytes = JPEG_BYTES,
           filename: str = "photo.jpg", mime: str = "image/jpeg") -> str:
    response = env.client.post(
        "/api/v1/files/upload",
        headers=auth(env.tokens[token_name]),
        data={"type": upload_type},
        files={"file": (filename, content, mime)},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["file_url"]


def collect_file_urls(value) -> list[str]:
    if isinstance(value, dict):
        return [url for item in value.values() for url in collect_file_urls(item)]
    if isinstance(value, list):
        return [url for item in value for url in collect_file_urls(item)]
    if isinstance(value, str) and value.startswith(FILES_PREFIX):
        return [value]
    return []


def order_payload(env, cargo_photo_url) -> dict:
    return {
        "from_city_id": env.ids["from_city"],
        "to_city_id": env.ids["to_city"],
        "pickup_address": "Toshkent, Chilonzor",
        "dropoff_address": "Samarqand center",
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": cargo_photo_url,
    }


def insert_order(env, cargo_photo_url: str | None, status: str = "draft") -> int:
    db = env.session_factory()
    order = Order(
        order_number=f"ORD-FILES-{uuid4().hex[:8]}",
        client_id=env.ids["client"],
        from_city_id=env.ids["from_city"],
        to_city_id=env.ids["to_city"],
        pickup_address="Toshkent, Chilonzor",
        dropoff_address="Samarqand, Registon",
        sender_phone="+998901234567",
        receiver_phone="+998911112233",
        cargo_photo_url=cargo_photo_url,
        payment_method="cash",
        payment_status="unpaid",
        status=status,
    )
    db.add(order)
    db.commit()
    order_id = order.id
    db.close()
    return order_id


# ── Public mount removed ─────────────────────────────────────────────────────


def test_public_uploads_path_is_not_served(env) -> None:
    key = legacy_key()
    write_stored_file(env.upload_dir, key, b"SECRET-PASSPORT")

    public = env.client.get(f"/uploads/{key}")
    unsigned = env.client.get(f"{FILES_PREFIX}{key}")

    assert public.status_code == 404
    assert b"SECRET-PASSPORT" not in public.content
    assert unsigned.status_code == 403
    assert b"SECRET-PASSPORT" not in unsigned.content


# ── Download endpoint ────────────────────────────────────────────────────────


def test_upload_returns_signed_url_that_downloads_with_safe_headers(env) -> None:
    file_url = upload(env, "client", content=JPEG_BYTES)
    assert file_url.startswith(f"{FILES_PREFIX}cargo_photo/")
    assert f"/u{env.ids['client']}/" in file_url

    response = env.client.get(file_url)

    assert response.status_code == 200
    assert response.content == JPEG_BYTES
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert "photo.jpg" not in disposition


def test_pdf_document_is_served_as_pdf(env) -> None:
    file_url = upload(env, "driver", "passport", b"%PDF-1.4", "passport.pdf", "application/pdf")

    response = env.client.get(file_url)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_expired_signed_url_is_rejected(env) -> None:
    key = legacy_key()
    write_stored_file(env.upload_dir, key, b"SECRET")
    expired = sign_file_key(key, now=time.time() - 3 * 3600)

    response = env.client.get(expired)

    assert response.status_code == 403
    assert b"SECRET" not in response.content


def test_tampered_signature_key_or_expiry_is_rejected(env) -> None:
    key = legacy_key()
    other_key = legacy_key()
    write_stored_file(env.upload_dir, key, b"SECRET-A")
    write_stored_file(env.upload_dir, other_key, b"SECRET-B")
    good = sign_file_key(key)
    exp = parse_qs(urlsplit(good).query)["exp"][0]
    sig = parse_qs(urlsplit(good).query)["sig"][0]

    flipped_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    attempts = [
        f"{FILES_PREFIX}{key}?exp={exp}&sig={flipped_sig}",
        f"{FILES_PREFIX}{other_key}?exp={exp}&sig={sig}",
        f"{FILES_PREFIX}{key}?exp={int(exp) + 300}&sig={sig}",
        f"{FILES_PREFIX}{key}?exp={exp}",
        f"{FILES_PREFIX}{key}?sig={sig}",
        f"{FILES_PREFIX}{key}?exp=abc&sig={sig}",
    ]
    assert env.client.get(good).status_code == 200
    for url in attempts:
        response = env.client.get(url)
        assert response.status_code == 403, url
        assert b"SECRET" not in response.content


def test_signature_from_a_far_future_expiry_is_rejected() -> None:
    key = legacy_key()
    assert verify_file_signature(key, str(int(time.time()) + 10 * 86400), "x" * 43) is False


def test_path_traversal_attempts_are_rejected(env) -> None:
    outside = env.tmp_path / "secret.jpg"
    outside.write_bytes(b"OUTSIDE-SECRET")

    for raw in [
        f"{FILES_PREFIX}..%2Fsecret.jpg?exp=1&sig=x",
        f"{FILES_PREFIX}cargo_photo/2026/06/..%2F..%2F..%2F..%2Fsecret.jpg?exp=1&sig=x",
        f"{FILES_PREFIX}cargo_photo/2026/06/%2e%2e/%2e%2e/%2e%2e/%2e%2e/secret.jpg?exp=1&sig=x",
        f"{FILES_PREFIX}cargo_photo%5C2026%5C06%5C..%5C..%5C..%5C..%5Csecret.jpg?exp=1&sig=x",
    ]:
        response = env.client.get(raw)
        assert response.status_code in {403, 404}, raw
        assert b"OUTSIDE-SECRET" not in response.content

    for value in [
        "/uploads/../secret.jpg",
        "/uploads/cargo_photo/2026/06/../../../../secret.jpg",
        "cargo_photo/2026/06/..%2F..%2Fsecret.jpg",
        "cargo_photo/2026/06/x.svg",
        "cargo_photo/2026/06/x.html",
        "pickup_proof/2026/06/x.jpg",
        "C:\\secret.jpg",
        "/etc/passwd",
        "https://evil.example/secret.jpg",
        "",
        None,
    ]:
        assert normalize_storage_key(value) is None, value
    with pytest.raises(ValueError):
        sign_file_key("../secret.jpg")
    assert resolve_upload_path("../secret.jpg") is None


def test_signed_url_for_missing_file_is_404(env) -> None:
    response = env.client.get(sign_file_key(legacy_key()))
    assert response.status_code == 404


# ── Normalization of stored values ───────────────────────────────────────────


def test_stored_value_variants_normalize_to_the_same_key(env) -> None:
    key = f"cargo_photo/2026/06/u7/{uuid4().hex}.webp"
    signed = sign_file_key(key)
    for value in [
        key,
        f"/uploads/{key}",
        f"https://api.elchigo.uz/uploads/{key}",
        signed,
        f"https://api.elchigo.uz{signed}",
        sign_file_key(key, now=time.time() - 86400),
    ]:
        assert normalize_storage_key(value) == key, value


def test_signed_urls_are_stable_within_an_expiry_bucket(env) -> None:
    key = legacy_key()
    assert sign_file_key(key, now=1_000_000) == sign_file_key(key, now=1_000_010)


def test_legacy_document_value_is_returned_as_working_signed_url(env) -> None:
    key = legacy_key("passport")
    write_stored_file(env.upload_dir, key, b"LEGACY-PASSPORT")
    db = env.session_factory()
    db.add(DriverDocument(driver_id=env.ids["driver_profile"], document_type="passport", file_url=f"/uploads/{key}", status="pending"))
    db.commit()
    db.close()

    admin_view = env.client.get(f"/api/v1/admin/drivers/{env.ids['driver_profile']}", headers=auth(env.tokens["operator"]))
    own_view = env.client.get("/api/v1/driver/documents", headers=auth(env.tokens["driver"]))

    assert admin_view.status_code == 200
    assert own_view.status_code == 200
    for response in (admin_view, own_view):
        urls = collect_file_urls(response.json())
        assert len(urls) == 1
        assert "/uploads/" not in response.text
        download = env.client.get(urls[0])
        assert download.status_code == 200
        assert download.content == b"LEGACY-PASSPORT"


def test_legacy_absolute_cargo_photo_value_is_returned_signed(env) -> None:
    key = legacy_key("cargo_photo")
    write_stored_file(env.upload_dir, key, b"LEGACY-CARGO")
    order_id = insert_order(env, f"https://api.elchigo.uz/uploads/{key}")

    response = env.client.get(f"/api/v1/client/orders/{order_id}", headers=auth(env.tokens["client"]))

    assert response.status_code == 200
    photo_url = response.json()["data"]["cargo_photo_url"]
    assert photo_url.startswith(FILES_PREFIX)
    assert env.client.get(photo_url).content == b"LEGACY-CARGO"


def test_unresolvable_stored_value_is_not_echoed(env) -> None:
    assert signed_file_url("https://evil.example/x.jpg") is None
    assert signed_file_url(None) is None


# ── Attaching uploads ────────────────────────────────────────────────────────


def test_client_can_attach_own_upload_and_db_stores_no_signature(env) -> None:
    file_url = upload(env, "client")

    response = env.client.post("/api/v1/client/orders", headers=auth(env.tokens["client"]), json=order_payload(env, file_url))

    assert response.status_code == 200, response.text
    assert response.json()["data"]["cargo_photo_url"].startswith(FILES_PREFIX)
    db = env.session_factory()
    order = db.get(Order, response.json()["data"]["id"])
    assert order.cargo_photo_url == f"/uploads/{normalize_storage_key(file_url)}"
    assert "sig=" not in order.cargo_photo_url
    db.close()


def test_user_cannot_attach_another_users_upload(env) -> None:
    others_url = upload(env, "other_client")
    others_key = normalize_storage_key(others_url)
    unbound_legacy = legacy_key("cargo_photo")
    write_stored_file(env.upload_dir, unbound_legacy)
    missing_own = f"cargo_photo/2026/06/u{env.ids['client']}/{uuid4().hex}.jpg"

    for value in [others_url, f"/uploads/{others_key}", others_key, f"/uploads/{unbound_legacy}", missing_own, "not-a-file"]:
        response = env.client.post("/api/v1/client/orders", headers=auth(env.tokens["client"]), json=order_payload(env, value))
        assert response.status_code == 400, value
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.json()["error"]["details"] == {"field": "cargo_photo_url"}

    document = env.client.post(
        "/api/v1/driver/documents",
        headers=auth(env.tokens["driver"]),
        json={"document_type": "passport", "file_url": upload(env, "other_client", "passport")},
    )
    assert document.status_code == 400
    assert document.json()["error"]["details"] == {"field": "file_url"}


def test_order_edit_accepts_unchanged_legacy_or_expired_signed_value(env) -> None:
    file_url = upload(env, "client")
    created = env.client.post("/api/v1/client/orders", headers=auth(env.tokens["client"]), json=order_payload(env, file_url))
    order_id = created.json()["data"]["id"]
    expired = sign_file_key(normalize_storage_key(file_url), now=time.time() - 7200)

    edit = env.client.patch(f"/api/v1/client/orders/{order_id}", headers=auth(env.tokens["client"]), json=order_payload(env, expired))
    assert edit.status_code == 200, edit.text

    legacy_value = f"/uploads/{legacy_key('cargo_photo')}"
    legacy_order_id = insert_order(env, legacy_value)
    legacy_edit = env.client.patch(
        f"/api/v1/client/orders/{legacy_order_id}",
        headers=auth(env.tokens["client"]),
        json=order_payload(env, legacy_value),
    )
    assert legacy_edit.status_code == 200, legacy_edit.text
    db = env.session_factory()
    assert db.get(Order, legacy_order_id).cargo_photo_url == legacy_value
    db.close()


# ── Visibility ───────────────────────────────────────────────────────────────


def test_unauthorized_viewers_do_not_receive_signed_urls(env) -> None:
    key = legacy_key("cargo_photo")
    write_stored_file(env.upload_dir, key)
    order_id = insert_order(env, f"/uploads/{key}", status="published")
    db = env.session_factory()
    db.add(DriverDocument(driver_id=env.ids["driver_profile"], document_type="passport", file_url=f"/uploads/{legacy_key()}", status="pending"))
    db.commit()
    db.close()

    responses = [
        env.client.get(f"/api/v1/client/orders/{order_id}", headers=auth(env.tokens["other_client"])),
        env.client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(env.tokens["driver"])),
        env.client.get(f"/api/v1/admin/orders/{order_id}", headers=auth(env.tokens["client"])),
        env.client.get(f"/api/v1/admin/drivers/{env.ids['driver_profile']}", headers=auth(env.tokens["client"])),
        env.client.get("/api/v1/driver/documents", headers=auth(env.tokens["client"])),
    ]
    for response in responses:
        assert response.status_code >= 400, response.request.url
        assert FILES_PREFIX not in response.text
        assert "sig=" not in response.text


# ── Audit log and account deletion ───────────────────────────────────────────


def test_audit_log_never_contains_signed_urls(env) -> None:
    file_url = upload(env, "driver", "passport")
    response = env.client.post(
        "/api/v1/driver/documents",
        headers=auth(env.tokens["driver"]),
        json={"document_type": "passport", "file_url": file_url},
    )
    assert response.status_code == 200
    assert response.json()["data"]["file_url"].startswith(FILES_PREFIX)

    db = env.session_factory()
    logs = list(db.scalars(select(AuditLog)))
    db.close()
    assert logs
    dumped = json.dumps([log.details for log in logs])
    assert "sig=" not in dumped
    assert FILES_PREFIX not in dumped


def test_account_deletion_removes_nested_and_legacy_document_files(env) -> None:
    file_url = upload(env, "driver", "passport")
    submitted = env.client.post(
        "/api/v1/driver/documents",
        headers=auth(env.tokens["driver"]),
        json={"document_type": "passport", "file_url": file_url},
    )
    assert submitted.status_code == 200
    uploaded_path = resolve_upload_path(normalize_storage_key(file_url))
    legacy = legacy_key("selfie")
    legacy_path = write_stored_file(env.upload_dir, legacy)
    db = env.session_factory()
    db.add(DriverDocument(driver_id=env.ids["driver_profile"], document_type="selfie", file_url=f"/uploads/{legacy}", status="pending"))
    db.commit()
    db.close()
    assert uploaded_path.is_file() and legacy_path.is_file()

    response = env.client.delete("/api/v1/auth/me", headers=auth(env.tokens["driver"]))

    assert response.status_code == 200, response.text
    assert not uploaded_path.exists()
    assert not legacy_path.exists()


def test_remove_upload_never_escapes_upload_root(env) -> None:
    outside = env.tmp_path / "keep.jpg"
    outside.write_bytes(b"keep")

    _remove_upload("/uploads/../keep.jpg")
    _remove_upload(str(outside))

    assert outside.exists()


# ── Signing key configuration ────────────────────────────────────────────────


def test_signing_key_is_derived_not_raw_secret_and_explicit_key_wins(env, monkeypatch: pytest.MonkeyPatch) -> None:
    key = legacy_key()
    derived = file_access._signing_key()
    assert derived != settings.secret_key.encode("utf-8")
    derived_url = sign_file_key(key, now=1_000_000)

    monkeypatch.setattr(settings, "file_url_signing_key", "k" * 40)
    assert file_access._signing_key() == b"k" * 40
    explicit_url = sign_file_key(key, now=1_000_000)
    assert explicit_url != derived_url
    exp = parse_qs(urlsplit(derived_url).query)["exp"][0]
    derived_sig = parse_qs(urlsplit(derived_url).query)["sig"][0]
    assert verify_file_signature(key, exp, derived_sig, now=1_000_000) is False


def test_signing_key_setting_validation() -> None:
    assert Settings(file_url_signing_key="   ").file_url_signing_key is None
    with pytest.raises(ValidationError):
        Settings(file_url_signing_key="too-short")


# ── Wave 0.5 regressions ─────────────────────────────────────────────────────


def test_non_ascii_expiry_or_signature_is_403_not_500(env) -> None:
    key = legacy_key()
    write_stored_file(env.upload_dir, key, b"SECRET")
    good = sign_file_key(key)
    exp = parse_qs(urlsplit(good).query)["exp"][0]
    sig = parse_qs(urlsplit(good).query)["sig"][0]

    for url in [
        f"{FILES_PREFIX}{key}?exp=%C2%B2&sig={sig}",
        f"{FILES_PREFIX}{key}?exp=%D9%A1%D9%A2&sig={sig}",
        f"{FILES_PREFIX}{key}?exp={exp}&sig=%C3%A9{sig[1:]}",
        f"{FILES_PREFIX}{key}?exp={exp}&sig={sig[:-1]}%C3%A9",
    ]:
        response = env.client.get(url)
        assert response.status_code == 403, url
        assert b"SECRET" not in response.content
    assert verify_file_signature(key, "²", sig) is False
    assert verify_file_signature(key, exp, "é" * 43) is False


def make_approved_driver(env, phone: str) -> tuple[int, str]:
    db = env.session_factory()
    user = User(phone=phone, role="driver", status="active", is_phone_verified=True)
    db.add(user)
    db.commit()
    profile = DriverProfile(user_id=user.id, verification_status="approved", is_available=True)
    db.add(profile)
    db.commit()
    db.add(DriverRoute(driver_id=profile.id, from_city_id=env.ids["from_city"], to_city_id=env.ids["to_city"], status="available"))
    db.commit()
    result = (profile.id, create_access_token(str(user.id)))
    db.close()
    return result


def set_order(env, order_id: int, **fields) -> None:
    db = env.session_factory()
    order = db.get(Order, order_id)
    for name, value in fields.items():
        setattr(order, name, value)
    db.commit()
    db.close()


def add_bid(env, order_id: int, driver_id: int) -> None:
    db = env.session_factory()
    db.add(Bid(order_id=order_id, driver_id=driver_id, price=Decimal("50000"), status="active"))
    db.commit()
    db.close()


def assert_working_photo_link(env, url: str | None, content: bytes) -> None:
    assert url is not None and url.startswith(FILES_PREFIX)
    download = env.client.get(url)
    assert download.status_code == 200
    assert download.content == content
    assert download.headers["content-type"] == "image/jpeg"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["x-content-type-options"] == "nosniff"


def test_cargo_photo_link_only_for_owner_assigned_driver_and_staff(env) -> None:
    key = legacy_key("cargo_photo")
    write_stored_file(env.upload_dir, key, JPEG_BYTES)
    assigned_id, assigned_token = make_approved_driver(env, "+998930000101")
    bidder_id, bidder_token = make_approved_driver(env, "+998930000102")
    _feed_id, feed_token = make_approved_driver(env, "+998930000103")

    order_id = insert_order(env, f"/uploads/{key}", status="published")

    feed = env.client.get("/api/v1/driver/orders/feed", headers=auth(feed_token))
    assert feed.status_code == 200, feed.text
    items = feed.json()["data"]["items"]
    assert [item["id"] for item in items] == [order_id]
    assert items[0]["cargo_photo_url"] is None
    matched_detail = env.client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(feed_token))
    assert matched_detail.status_code == 200
    assert matched_detail.json()["data"]["cargo_photo_url"] is None

    add_bid(env, order_id, bidder_id)
    add_bid(env, order_id, assigned_id)
    set_order(env, order_id, status="accepted", assigned_driver_id=assigned_id)

    owner = env.client.get(f"/api/v1/client/orders/{order_id}", headers=auth(env.tokens["client"]))
    assigned = env.client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(assigned_token))
    admin = env.client.get(f"/api/v1/admin/orders/{order_id}", headers=auth(env.tokens["admin"]))
    for response in (owner, assigned, admin):
        assert response.status_code == 200, response.text
        assert_working_photo_link(env, response.json()["data"]["cargo_photo_url"], JPEG_BYTES)

    bidder_detail = env.client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(bidder_token))
    bidder_list = env.client.get("/api/v1/driver/orders", headers=auth(bidder_token))
    assert bidder_detail.status_code == 200
    assert bidder_detail.json()["data"]["cargo_photo_url"] is None
    assert bidder_list.status_code == 200
    assert all(item["cargo_photo_url"] is None for item in bidder_list.json()["data"]["items"])
    assert FILES_PREFIX not in bidder_detail.text + bidder_list.text

    # Reassigned: the previously assigned driver becomes a plain bidder.
    set_order(env, order_id, assigned_driver_id=bidder_id)
    reassigned = env.client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(assigned_token))
    assert reassigned.status_code == 200
    assert reassigned.json()["data"]["cargo_photo_url"] is None

    # Cancelled: assigned_driver_id is kept, the photo link is not.
    set_order(env, order_id, status="cancelled")
    for token in (bidder_token, assigned_token):
        detail = env.client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(token))
        listing = env.client.get("/api/v1/driver/orders", headers=auth(token))
        assert FILES_PREFIX not in detail.text + listing.text


def test_upload_content_must_match_magic_bytes(env) -> None:
    def post(upload_type, filename, content, mime):
        return env.client.post(
            "/api/v1/files/upload",
            headers=auth(env.tokens["client"]),
            data={"type": upload_type},
            files={"file": (filename, content, mime)},
        )

    rejected = [
        ("cargo_photo", "photo.jpg", b"not-an-image", "image/jpeg"),
        ("cargo_photo", "photo.png", b"<html><script>alert(1)</script>", "image/png"),
        ("passport", "passport.jpg", b"%PDF-1.4 disguised", "image/jpeg"),
        ("passport", "passport.pdf", JPEG_BYTES, "application/pdf"),
        ("passport", "passport.pdf", b"MZ\x90\x00", "application/pdf"),
    ]
    for case in rejected:
        response = post(*case)
        assert response.status_code == 400, case
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    webp = post("selfie", "selfie.webp", WEBP_BYTES, "image/webp")
    assert webp.status_code == 200
    assert webp.json()["data"]["file_url"].split("?", 1)[0].endswith(".webp")

    # Mislabelled image (PNG bytes named .jpg): stored and served as PNG.
    mislabelled = post("cargo_photo", "photo.jpg", PNG_BYTES, "image/jpeg")
    assert mislabelled.status_code == 200
    body = mislabelled.json()["data"]
    assert body["mime_type"] == "image/png"
    assert body["file_url"].split("?", 1)[0].endswith(".png")
    served = env.client.get(body["file_url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"


def test_upload_type_must_match_attach_target(env) -> None:
    selfie_url = upload(env, "driver", "selfie")
    as_passport = env.client.post(
        "/api/v1/driver/documents",
        headers=auth(env.tokens["driver"]),
        json={"document_type": "passport", "file_url": selfie_url},
    )
    assert as_passport.status_code == 400
    assert as_passport.json()["error"]["details"] == {"field": "file_url"}
    as_selfie = env.client.post(
        "/api/v1/driver/documents",
        headers=auth(env.tokens["driver"]),
        json={"document_type": "selfie", "file_url": selfie_url},
    )
    assert as_selfie.status_code == 200

    passport_url = upload(env, "client", "passport")
    as_cargo = env.client.post("/api/v1/client/orders", headers=auth(env.tokens["client"]), json=order_payload(env, passport_url))
    assert as_cargo.status_code == 400
    assert as_cargo.json()["error"]["details"] == {"field": "cargo_photo_url"}


def test_account_deletion_keeps_files_when_transaction_rolls_back(env, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import account_deletion_service

    file_url = upload(env, "driver", "passport")
    submitted = env.client.post(
        "/api/v1/driver/documents",
        headers=auth(env.tokens["driver"]),
        json={"document_type": "passport", "file_url": file_url},
    )
    assert submitted.status_code == 200
    stored_path = resolve_upload_path(normalize_storage_key(file_url))

    def failing_audit(*args, **kwargs):
        raise RuntimeError("simulated failure before commit")

    monkeypatch.setattr(account_deletion_service, "write_audit_log", failing_audit)
    db = env.session_factory()
    user = db.get(User, env.ids["driver"])
    with pytest.raises(RuntimeError):
        account_deletion_service.delete_own_account(db, user)
    db.close()

    assert stored_path.is_file()
    db = env.session_factory()
    assert db.scalar(select(DriverDocument).where(DriverDocument.driver_id == env.ids["driver_profile"])) is not None
    db.close()
