"""v1 hardening (H1): operator permissions, forced `disputed`, client cancel closes
bids, update_bid never revives a bid, account deletion vs disputes, and
store-review account isolation.

Behavioural rules only. Row-lock/race invariants are proven on PostgreSQL in
tests/pg/test_v1_order_races.py (SQLite cannot prove them).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, Bid, City, Dispute, DriverProfile, DriverRoute, Order, OrderOffer, StatusHistory, User
from app.services import sms_service

REVIEW_CLIENT_PHONE = "+998900000010"
REVIEW_DRIVER_PHONE = "+998900000011"


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "review_login_phones", f"{REVIEW_CLIENT_PHONE},{REVIEW_DRIVER_PHONE}")
    monkeypatch.setattr(settings, "review_login_otp", None)

    db = SessionLocal()
    users = {
        "client": User(phone="+998931000001", role="client", status="active", is_phone_verified=True),
        "review_client": User(phone=REVIEW_CLIENT_PHONE, role="client", status="active", is_phone_verified=True),
        "operator": User(phone="+998931000003", role="operator", status="active", is_phone_verified=True),
        "admin": User(phone="+998931000004", role="admin", status="active", is_phone_verified=True),
        "super_admin": User(phone="+998931000005", role="super_admin", status="active", is_phone_verified=True),
        "driver": User(phone="+998931000006", role="driver", status="active", is_phone_verified=True),
        "driver2": User(phone="+998931000007", role="driver", status="active", is_phone_verified=True),
        "review_driver": User(phone=REVIEW_DRIVER_PHONE, role="driver", status="active", is_phone_verified=True),
    }
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    db.add_all([*users.values(), from_city, to_city])
    db.flush()
    profiles = {}
    for key in ("driver", "driver2", "review_driver"):
        profile = DriverProfile(user_id=users[key].id, full_name=key, verification_status="approved", is_available=True)
        db.add(profile)
        db.flush()
        db.add(DriverRoute(driver_id=profile.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
        profiles[key] = profile.id
    db.commit()
    ids = {key: user.id for key, user in users.items()}
    ids.update({f"{key}_profile": value for key, value in profiles.items()})
    ids.update({"from_city": from_city.id, "to_city": to_city.id})
    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    db.close()

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), tokens, SessionLocal, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def insert_order(SessionLocal, ids, *, client: str = "client", status: str = "bidding", driver: str | None = None) -> int:
    with SessionLocal() as db:
        count = db.scalar(select(func.count(Order.id))) + 1
        order = Order(
            order_number=f"ORD-H1-{count}",
            client_id=ids[client],
            from_city_id=ids["from_city"],
            to_city_id=ids["to_city"],
            pickup_address="Toshkent, Chilonzor",
            dropoff_address="Samarqand, Registon",
            sender_phone="+998901234567",
            receiver_phone="+998911112233",
            suggested_price=Decimal("60000"),
            final_price=Decimal("55000") if driver else None,
            status=status,
            assigned_driver_id=ids[f"{driver}_profile"] if driver else None,
        )
        db.add(order)
        db.commit()
        return order.id


def insert_bid(SessionLocal, order_id: int, profile_id: int, *, status: str = "active", price: int = 55000) -> int:
    with SessionLocal() as db:
        bid = Bid(order_id=order_id, driver_id=profile_id, price=Decimal(price), status=status)
        db.add(bid)
        db.commit()
        return bid.id


def create_and_publish(client: TestClient, token: str, ids) -> tuple[int, dict]:
    created = client.post(
        "/api/v1/client/orders",
        headers=auth(token),
        json={
            "from_city_id": ids["from_city"],
            "to_city_id": ids["to_city"],
            "pickup_address": "Toshkent, Chilonzor",
            "dropoff_address": "Samarqand, Registon",
            "sender_phone": "+998901234567",
            "receiver_phone": "+998911112233",
        },
    )
    assert created.status_code == 200, created.text
    order_id = created.json()["data"]["id"]
    published = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=auth(token))
    assert published.status_code == 200, published.text
    return order_id, published.json()["data"]


# ── Decision 2: operators are read-only on admin order endpoints ─────────────


def test_operator_cannot_force_status_assign_or_cancel_but_can_read(env) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="bidding")
    bid_id = insert_bid(SessionLocal, order_id, ids["driver_profile"])

    forced = client.patch(f"/api/v1/admin/orders/{order_id}/status", headers=auth(tokens["operator"]), json={"status": "accepted", "reason": "x"})
    assigned = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=auth(tokens["operator"]),
        json={"driver_id": ids["driver_profile"], "final_price": 55000, "reason": "x"},
    )
    cancelled = client.post(f"/api/v1/admin/orders/{order_id}/cancel", headers=auth(tokens["operator"]), json={"reason": "x"})

    for response in (forced, assigned, cancelled):
        assert response.status_code == 403
        assert response.json() == {"success": False, "error": {"code": "FORBIDDEN", "message": "Admin role required"}}
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == "bidding"
        assert order.assigned_driver_id is None
        assert db.get(Bid, bid_id).status == "active"
        assert db.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id)) == 0

    assert client.get("/api/v1/admin/orders", headers=auth(tokens["operator"])).status_code == 200
    assert client.get(f"/api/v1/admin/orders/{order_id}", headers=auth(tokens["operator"])).status_code == 200


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admin_roles_keep_mutation_access(env, role: str) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="bidding")

    response = client.post(f"/api/v1/admin/orders/{order_id}/cancel", headers=auth(tokens[role]), json={"reason": "Client unreachable"})

    assert response.status_code == 200
    assert response.json()["data"]["new_status"] == "cancelled"


# ── Decision 3: forced `disputed` requires an active dispute record ───────────


def test_admin_cannot_force_disputed_without_dispute_record(env) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="in_transit", driver="driver")

    response = client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        headers=auth(tokens["admin"]),
        json={"status": "disputed", "reason": "Client complained by phone"},
    )

    assert response.status_code == 409
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "DISPUTE_REQUIRED"
    assert f"/api/v1/orders/{order_id}/disputes" in response.json()["error"]["message"]
    with SessionLocal() as db:
        assert db.get(Order, order_id).status == "in_transit"
        assert db.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id)) == 0


@pytest.mark.parametrize("dispute_status", ["resolved", "rejected"])
def test_closed_dispute_does_not_allow_forcing_disputed(env, dispute_status: str) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="delivered", driver="driver")
    with SessionLocal() as db:
        db.add(Dispute(order_id=order_id, opened_by_user_id=ids["client"], reason="delayed", status=dispute_status, previous_order_status="delivered"))
        db.commit()

    response = client.patch(f"/api/v1/admin/orders/{order_id}/status", headers=auth(tokens["admin"]), json={"status": "disputed", "reason": "x"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DISPUTE_REQUIRED"


def insert_dispute(SessionLocal, ids, order_id: int, dispute_status: str, previous: str = "delivered") -> int:
    with SessionLocal() as db:
        dispute = Dispute(order_id=order_id, opened_by_user_id=ids["client"], reason="damaged", status=dispute_status, previous_order_status=previous)
        db.add(dispute)
        db.commit()
        return dispute.id


# Decision 12: no manual status change while a dispute is open or under review.
@pytest.mark.parametrize("dispute_status", ["open", "under_review"])
@pytest.mark.parametrize(
    ("order_status", "target"),
    [("disputed", "delivered"), ("disputed", "cancelled"), ("disputed", "confirmed"), ("delivered", "disputed"), ("in_transit", "delivered")],
)
def test_manual_status_change_refused_while_dispute_active(env, dispute_status: str, order_status: str, target: str) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status=order_status, driver="driver")
    dispute_id = insert_dispute(SessionLocal, ids, order_id, dispute_status)

    response = client.patch(f"/api/v1/admin/orders/{order_id}/status", headers=auth(tokens["super_admin"]), json={"status": target, "reason": "Manual"})

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "error": {
            "code": "DISPUTE_ACTIVE",
            "message": f"Order has an active dispute. Resolve or reject it via PATCH /api/v1/admin/disputes/{dispute_id} first",
        },
    }
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        assert order.status == order_status
        assert order.payment_status == "unpaid"
        assert db.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id)) == 0


@pytest.mark.parametrize("dispute_status", ["open", "under_review"])
def test_admin_cancel_refused_while_dispute_active(env, dispute_status: str) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="disputed", driver="driver")
    dispute_id = insert_dispute(SessionLocal, ids, order_id, dispute_status)

    response = client.post(f"/api/v1/admin/orders/{order_id}/cancel", headers=auth(tokens["admin"]), json={"reason": "Close it"})

    assert response.status_code == 409
    # Decision 37: the message points to the resolve-then-cancel workflow.
    assert response.json() == {
        "success": False,
        "error": {
            "code": "DISPUTE_ACTIVE",
            "message": (
                f"Order has an active dispute. Resolve or reject it via PATCH /api/v1/admin/disputes/{dispute_id} first, "
                f"then cancel the order via POST /api/v1/admin/orders/{order_id}/cancel"
            ),
        },
    }
    with SessionLocal() as db:
        assert db.get(Order, order_id).status == "disputed"

    # The workflow works: resolve the dispute (restores delivered), then cancel.
    resolved = client.patch(
        f"/api/v1/admin/disputes/{dispute_id}",
        headers=auth(tokens["admin"]),
        json={"status": "resolved", "resolution": "Refund agreed offline"},
    )
    assert resolved.status_code == 200
    cancelled = client.post(f"/api/v1/admin/orders/{order_id}/cancel", headers=auth(tokens["admin"]), json={"reason": "Close it"})
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["new_status"] == "cancelled"


def test_manual_status_change_allowed_again_after_dispute_closed(env) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="in_transit", driver="driver")
    insert_dispute(SessionLocal, ids, order_id, "resolved", previous="in_transit")

    response = client.patch(f"/api/v1/admin/orders/{order_id}/status", headers=auth(tokens["admin"]), json={"status": "delivered", "reason": "Driver confirmed by phone"})

    assert response.status_code == 200
    assert response.json()["data"]["new_status"] == "delivered"


# ── Decision 1 (behaviour part): cancel closes bids, update_bid never revives ──


def test_client_cancel_closes_all_active_bids_in_same_transaction(env) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="bidding")
    active_1 = insert_bid(SessionLocal, order_id, ids["driver_profile"])
    active_2 = insert_bid(SessionLocal, order_id, ids["driver2_profile"], price=61000)
    rejected = insert_bid(SessionLocal, order_id, ids["review_driver_profile"], status="rejected")

    response = client.post(f"/api/v1/client/orders/{order_id}/cancel", headers=auth(tokens["client"]), json={"reason": "Changed plans"})

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"
    with SessionLocal() as db:
        assert db.get(Bid, active_1).status == "closed"
        assert db.get(Bid, active_2).status == "closed"
        assert db.get(Bid, rejected).status == "rejected"
        assert db.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id, Bid.status == "active")) == 0
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "order_cancelled", AuditLog.entity_id == order_id))
        assert audit is not None


def test_bid_cannot_be_created_or_updated_after_client_cancel(env) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="bidding")
    bid_id = insert_bid(SessionLocal, order_id, ids["driver_profile"])
    assert client.post(f"/api/v1/client/orders/{order_id}/cancel", headers=auth(tokens["client"]), json={"reason": "x"}).status_code == 200

    created = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=auth(tokens["driver2"]), json={"price": 50000})
    updated = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=auth(tokens["driver"]), json={"price": 50000})

    assert created.status_code == 400
    assert created.json()["error"]["code"] == "ORDER_INVALID_STATUS"
    assert updated.status_code == 400
    assert updated.json()["error"]["code"] == "ORDER_INVALID_STATUS"
    with SessionLocal() as db:
        bid = db.get(Bid, bid_id)
        assert bid.status == "closed"
        assert bid.price == Decimal("55000")


@pytest.mark.parametrize("bid_status", ["closed", "rejected", "accepted"])
def test_update_bid_never_revives_non_active_bid_on_open_order(env, bid_status: str) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="bidding")
    bid_id = insert_bid(SessionLocal, order_id, ids["driver_profile"], status=bid_status)

    response = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=auth(tokens["driver"]), json={"price": 70000})

    assert response.status_code == 409
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "BID_NOT_ACTIVE"
    with SessionLocal() as db:
        bid = db.get(Bid, bid_id)
        assert bid.status == bid_status
        assert bid.price == Decimal("55000")
        assert bid.price_update_count == 0
        assert db.scalar(select(AuditLog).where(AuditLog.action == "driver_bid_updated")) is None


# ── Decision 4: account deletion refused while a dispute is unresolved ────────


@pytest.mark.parametrize("dispute_status", ["open", "under_review"])
def test_client_with_active_dispute_cannot_delete_account(env, dispute_status: str) -> None:
    client, tokens, SessionLocal, ids = env
    # Order already restored/confirmed, but the dispute is still open.
    order_id = insert_order(SessionLocal, ids, status="confirmed", driver="driver")
    with SessionLocal() as db:
        db.add(Dispute(order_id=order_id, opened_by_user_id=ids["driver"], reason="payment_issue", status=dispute_status, previous_order_status="delivered"))
        db.commit()

    for role in ("client", "driver"):
        response = client.delete("/api/v1/auth/me", headers=auth(tokens[role]))
        assert response.status_code == 409, role
        assert response.json() == {
            "success": False,
            "error": {
                "code": "ACTIVE_DISPUTES_EXIST",
                "message": "Hal qilinmagan nizolaringiz bor. Ular yopilgach hisobni o'chirish mumkin",
            },
        }
    with SessionLocal() as db:
        assert db.get(User, ids["client"]).status == "active"
        assert db.get(User, ids["driver"]).phone == "+998931000006"


@pytest.mark.parametrize("role", ["client", "driver"])
def test_party_to_disputed_order_cannot_delete_account(env, role: str) -> None:
    client, tokens, SessionLocal, ids = env
    insert_order(SessionLocal, ids, status="disputed", driver="driver")

    response = client.delete("/api/v1/auth/me", headers=auth(tokens[role]))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_DISPUTES_EXIST"
    with SessionLocal() as db:
        assert db.get(User, ids[role]).status == "active"


def test_resolved_dispute_does_not_block_deletion_and_other_users_unaffected(env) -> None:
    client, tokens, SessionLocal, ids = env
    order_id = insert_order(SessionLocal, ids, status="confirmed", driver="driver")
    with SessionLocal() as db:
        db.add(Dispute(order_id=order_id, opened_by_user_id=ids["client"], reason="delayed", status="resolved", previous_order_status="delivered"))
        db.commit()
    # A dispute on someone else's order must not block driver2.
    other_order = insert_order(SessionLocal, ids, status="disputed", driver="driver")
    assert other_order

    driver2 = client.delete("/api/v1/auth/me", headers=auth(tokens["driver2"]))
    assert driver2.status_code == 200
    assert driver2.json()["data"]["deleted"] is True

    # client still has a disputed order (other_order) -> blocked; resolve it -> allowed.
    assert client.delete("/api/v1/auth/me", headers=auth(tokens["client"])).status_code == 409
    with SessionLocal() as db:
        db.get(Order, other_order).status = "confirmed"
        db.commit()
    deleted = client.delete("/api/v1/auth/me", headers=auth(tokens["client"]))
    assert deleted.status_code == 200
    with SessionLocal() as db:
        assert db.get(User, ids["client"]).status == "deleted"


# ── Decision 5: store-review accounts never reach real users ─────────────────


def test_review_client_order_is_matched_and_shown_only_to_review_drivers(env) -> None:
    client, tokens, SessionLocal, ids = env

    order_id, published = create_and_publish(client, tokens["review_client"], ids)

    assert published["matched_drivers_count"] == 1
    with SessionLocal() as db:
        offered = set(db.scalars(select(OrderOffer.driver_id).where(OrderOffer.order_id == order_id)))
    assert offered == {ids["review_driver_profile"]}

    review_feed = client.get("/api/v1/driver/orders/feed", headers=auth(tokens["review_driver"]))
    real_feed = client.get("/api/v1/driver/orders/feed", headers=auth(tokens["driver"]))
    assert [item["id"] for item in review_feed.json()["data"]["items"]] == [order_id]
    assert real_feed.json()["data"]["items"] == []
    assert real_feed.json()["data"]["pagination"]["total"] == 0

    detail = client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(tokens["driver"]))
    bid = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=auth(tokens["driver"]), json={"price": 55000})
    assert detail.status_code == 403
    assert bid.status_code == 403
    assert bid.json()["error"]["code"] == "FORBIDDEN"

    review_bid = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=auth(tokens["review_driver"]), json={"price": 55000})
    assert review_bid.status_code == 200


def test_real_client_order_is_invisible_to_review_driver(env) -> None:
    client, tokens, SessionLocal, ids = env

    order_id, published = create_and_publish(client, tokens["client"], ids)

    assert published["matched_drivers_count"] == 2
    with SessionLocal() as db:
        offered = set(db.scalars(select(OrderOffer.driver_id).where(OrderOffer.order_id == order_id)))
    assert ids["review_driver_profile"] not in offered

    feed = client.get("/api/v1/driver/orders/feed", headers=auth(tokens["review_driver"]))
    assert feed.json()["data"]["items"] == []
    assert client.get(f"/api/v1/driver/orders/{order_id}", headers=auth(tokens["review_driver"])).status_code == 403
    bid = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=auth(tokens["review_driver"]), json={"price": 55000})
    assert bid.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id)) == 0


def test_review_driver_cannot_be_selected_updated_or_assigned_on_real_order(env) -> None:
    client, tokens, SessionLocal, ids = env
    real_order = insert_order(SessionLocal, ids, client="client", status="bidding")
    review_order = insert_order(SessionLocal, ids, client="review_client", status="bidding")
    # Bids that predate the allowlist (or were written directly) must still be unusable.
    review_bid_on_real = insert_bid(SessionLocal, real_order, ids["review_driver_profile"])
    real_bid_on_review = insert_bid(SessionLocal, review_order, ids["driver_profile"])

    selected = client.post(f"/api/v1/client/orders/{real_order}/select-driver", headers=auth(tokens["client"]), json={"bid_id": review_bid_on_real})
    selected_reverse = client.post(
        f"/api/v1/client/orders/{review_order}/select-driver", headers=auth(tokens["review_client"]), json={"bid_id": real_bid_on_review}
    )
    updated = client.patch(f"/api/v1/driver/bids/{review_bid_on_real}", headers=auth(tokens["review_driver"]), json={"price": 50000})
    assigned = client.post(
        f"/api/v1/admin/orders/{real_order}/assign-driver",
        headers=auth(tokens["admin"]),
        json={"driver_id": ids["review_driver_profile"], "final_price": 55000, "reason": "Manual"},
    )
    assigned_reverse = client.post(
        f"/api/v1/admin/orders/{review_order}/assign-driver",
        headers=auth(tokens["super_admin"]),
        json={"driver_id": ids["driver_profile"], "final_price": 55000, "reason": "Manual"},
    )

    assert selected.status_code == 400 and selected.json()["error"]["code"] == "DRIVER_NOT_AVAILABLE"
    assert selected_reverse.status_code == 400 and selected_reverse.json()["error"]["code"] == "DRIVER_NOT_AVAILABLE"
    assert updated.status_code == 403
    assert assigned.status_code == 400 and assigned.json()["error"]["code"] == "DRIVER_NOT_AVAILABLE"
    assert assigned_reverse.status_code == 400 and assigned_reverse.json()["error"]["code"] == "DRIVER_NOT_AVAILABLE"
    with SessionLocal() as db:
        for order_id in (real_order, review_order):
            order = db.get(Order, order_id)
            assert order.status == "bidding"
            assert order.assigned_driver_id is None
        assert db.get(Bid, review_bid_on_real).price == Decimal("55000")

    # Same-side assignment still works.
    ok = client.post(
        f"/api/v1/admin/orders/{review_order}/assign-driver",
        headers=auth(tokens["admin"]),
        json={"driver_id": ids["review_driver_profile"], "final_price": 55000, "reason": "Manual"},
    )
    assert ok.status_code == 200


def test_removing_phone_from_allowlist_makes_account_normal_again(env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Documented limitation: isolation is by allowlist only."""
    client, tokens, SessionLocal, ids = env
    order_id, _ = create_and_publish(client, tokens["client"], ids)
    assert client.get("/api/v1/driver/orders/feed", headers=auth(tokens["review_driver"])).json()["data"]["items"] == []

    monkeypatch.setattr(settings, "review_login_phones", "")

    feed = client.get("/api/v1/driver/orders/feed", headers=auth(tokens["review_driver"]))
    assert [item["id"] for item in feed.json()["data"]["items"]] == [order_id]


def test_no_sms_is_sent_to_review_phones(env, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _tokens, _SessionLocal, _ids = env
    sent: list[str] = []
    monkeypatch.setattr(settings, "sms_enabled", True)
    monkeypatch.setattr(settings, "eskiz_email", "sms@example.test")
    monkeypatch.setattr(settings, "eskiz_password", "secret")
    monkeypatch.setattr(sms_service, "_get_token", lambda force_refresh=False: "token")

    class Ok:
        status_code = 200
        text = "ok"

    def fake_post(token: str, mobile_phone: str, message: str):
        sent.append(mobile_phone)
        return Ok()

    monkeypatch.setattr(sms_service, "_post_message", fake_post)

    # Direct call is refused even with a configured gateway.
    assert sms_service.send_sms(REVIEW_CLIENT_PHONE, "code 1234") is False
    # OTP request for a review phone (fixed review code unset) sends nothing.
    review = client.post("/api/v1/auth/request-otp", json={"phone": REVIEW_DRIVER_PHONE, "role": "driver"})
    assert review.status_code == 200
    assert sent == []

    # Control: a normal phone does get the SMS through the same patched gateway.
    normal = client.post("/api/v1/auth/request-otp", json={"phone": "+998931999999", "role": "client"})
    assert normal.status_code == 200
    assert sent == ["998931999999"]


# ── H1-5: client bid list never crosses the review/real split ────────────────


def test_client_bid_list_hides_bids_across_review_split(env) -> None:
    client, tokens, SessionLocal, ids = env
    real_order = insert_order(SessionLocal, ids, client="client", status="bidding")
    review_order = insert_order(SessionLocal, ids, client="review_client", status="bidding")
    real_on_real = insert_bid(SessionLocal, real_order, ids["driver_profile"])
    review_on_real = insert_bid(SessionLocal, real_order, ids["review_driver_profile"], price=40000)
    review_on_review = insert_bid(SessionLocal, review_order, ids["review_driver_profile"])
    real_on_review = insert_bid(SessionLocal, review_order, ids["driver2_profile"], price=40000)

    real = client.get(f"/api/v1/client/orders/{real_order}/bids", headers=auth(tokens["client"]))
    review = client.get(f"/api/v1/client/orders/{review_order}/bids", headers=auth(tokens["review_client"]))

    assert real.status_code == 200 and review.status_code == 200
    assert [item["id"] for item in real.json()["data"]] == [real_on_real]
    assert [item["id"] for item in review.json()["data"]] == [review_on_review]
    assert review_on_real not in [item["id"] for item in real.json()["data"]]
    assert real_on_review not in [item["id"] for item in review.json()["data"]]


# ── H1-6: admin lists/details flag review accounts (additive field) ──────────


def test_admin_lists_and_details_flag_review_accounts(env) -> None:
    client, tokens, SessionLocal, ids = env
    real_order = insert_order(SessionLocal, ids, client="client", status="accepted", driver="driver")
    review_order = insert_order(SessionLocal, ids, client="review_client", status="bidding")
    token = tokens["operator"]

    drivers = {item["id"]: item for item in client.get("/api/v1/admin/drivers", headers=auth(token)).json()["data"]["items"]}
    assert drivers[ids["review_driver_profile"]]["is_review_account"] is True
    assert drivers[ids["driver_profile"]]["is_review_account"] is False
    assert client.get(f"/api/v1/admin/drivers/{ids['review_driver_profile']}", headers=auth(token)).json()["data"]["is_review_account"] is True
    assert client.get(f"/api/v1/admin/drivers/{ids['driver_profile']}", headers=auth(token)).json()["data"]["is_review_account"] is False

    clients = {item["id"]: item for item in client.get("/api/v1/admin/clients", headers=auth(token)).json()["data"]["items"]}
    assert clients[ids["review_client"]]["is_review_account"] is True
    assert clients[ids["client"]]["is_review_account"] is False
    assert client.get(f"/api/v1/admin/clients/{ids['review_client']}", headers=auth(token)).json()["data"]["is_review_account"] is True

    orders = {item["id"]: item for item in client.get("/api/v1/admin/orders", headers=auth(token)).json()["data"]["items"]}
    assert orders[review_order]["is_review_account"] is True
    assert orders[real_order]["is_review_account"] is False
    assert client.get(f"/api/v1/admin/orders/{review_order}", headers=auth(token)).json()["data"]["is_review_account"] is True
    assert client.get(f"/api/v1/admin/orders/{real_order}", headers=auth(token)).json()["data"]["is_review_account"] is False


def test_order_with_review_driver_is_flagged_and_flags_off_without_allowlist(env, monkeypatch: pytest.MonkeyPatch) -> None:
    client, tokens, SessionLocal, ids = env
    # Legacy row: real client, review driver assigned (e.g. before isolation existed).
    order_id = insert_order(SessionLocal, ids, client="client", status="accepted", driver="review_driver")
    assert client.get(f"/api/v1/admin/orders/{order_id}", headers=auth(tokens["admin"])).json()["data"]["is_review_account"] is True

    monkeypatch.setattr(settings, "review_login_phones", "")
    detail = client.get(f"/api/v1/admin/orders/{order_id}", headers=auth(tokens["admin"])).json()["data"]
    assert detail["is_review_account"] is False


# ── F7: batched review flags; decision 39: open items before leaving the allowlist ──


def test_review_order_ids_batches_the_page(env) -> None:
    from sqlalchemy import event as sa_event

    from app.services.review_accounts import review_order_ids

    client, tokens, SessionLocal, ids = env
    order_ids = [insert_order(SessionLocal, ids, client="client", status="bidding") for _ in range(5)]
    order_ids.append(insert_order(SessionLocal, ids, client="review_client", status="bidding"))
    order_ids.append(insert_order(SessionLocal, ids, client="client", status="accepted", driver="review_driver"))
    with SessionLocal() as db:
        orders = [db.get(Order, order_id) for order_id in order_ids]
        statements: list[str] = []
        listener = lambda conn, cursor, statement, *args: statements.append(statement)  # noqa: E731
        sa_event.listen(db.get_bind(), "before_cursor_execute", listener)
        try:
            result = review_order_ids(db, orders)
        finally:
            sa_event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert result == {order_ids[5], order_ids[6]}
    assert len(statements) == 2


def test_review_account_open_items_lists_what_blocks_allowlist_removal(env) -> None:
    from app.services.review_accounts import review_account_open_items

    client, tokens, SessionLocal, ids = env
    open_order = insert_order(SessionLocal, ids, client="review_client", status="bidding")
    insert_order(SessionLocal, ids, client="review_client", status="confirmed")
    insert_order(SessionLocal, ids, client="review_client", status="cancelled")
    disputed = insert_order(SessionLocal, ids, client="review_client", status="disputed", driver="review_driver")
    bid_id = insert_bid(SessionLocal, open_order, ids["review_driver_profile"])
    dispute_id = insert_dispute(SessionLocal, ids, disputed, "open")

    with SessionLocal() as db:
        client_items = review_account_open_items(db, REVIEW_CLIENT_PHONE)
        driver_items = review_account_open_items(db, REVIEW_DRIVER_PHONE)
        unknown = review_account_open_items(db, "+998909999998")

    assert [o["id"] for o in client_items["open_orders"]] == [open_order, disputed]
    assert client_items["active_bids"] == []
    assert [d["id"] for d in client_items["open_disputes"]] == [dispute_id]
    assert [o["id"] for o in driver_items["open_orders"]] == [disputed]
    assert [b["id"] for b in driver_items["active_bids"]] == [bid_id]
    assert [d["id"] for d in driver_items["open_disputes"]] == [dispute_id]
    assert unknown == {"phone": "+998909999998", "user_id": None, "open_orders": [], "active_bids": [], "open_disputes": []}


# ── N4 / A4: v2 bookings check in v1 account deletion ────────────────────────


@pytest.mark.parametrize("role", ["client", "driver2"])
def test_account_deletion_still_allowed_without_v2_bookings(env, role: str) -> None:
    """The bookings check returns an empty state here (no bookings, or no bookings table
    in this SQLite schema), so deletion proceeds exactly as before."""
    from app.modules.bookings import service as bookings_service

    client, tokens, SessionLocal, ids = env
    with SessionLocal() as db:
        state = bookings_service.blocking_state_for_user(db, ids[role], lock=True)
    assert state.blocks_deletion is False

    response = client.delete("/api/v1/auth/me", headers=auth(tokens[role]))

    assert response.status_code == 200, response.text
    assert response.json()["data"]["deleted"] is True
    with SessionLocal() as db:
        assert db.get(User, ids[role]).status == "deleted"


# ── L1: admin block/unblock never resurrects a deleted account ───────────────


def test_admin_block_and_unblock_of_deleted_client_is_404(env) -> None:
    client, tokens, SessionLocal, ids = env
    assert client.delete("/api/v1/auth/me", headers=auth(tokens["client"])).status_code == 200

    for action in ("block", "unblock"):
        response = client.post(f"/api/v1/admin/clients/{ids['client']}/{action}", headers=auth(tokens["admin"]), json={"reason": "x"})
        assert response.status_code == 404, action
        assert response.json() == {"success": False, "error": {"code": "CLIENT_NOT_FOUND", "message": "Client not found"}}
    with SessionLocal() as db:
        assert db.get(User, ids["client"]).status == "deleted"
        assert db.scalar(select(AuditLog).where(AuditLog.action.in_(["client_blocked", "client_unblocked"]))) is None

    # A live client is still blocked and unblocked normally, same response shape.
    blocked = client.post(f"/api/v1/admin/clients/{ids['review_client']}/block", headers=auth(tokens["admin"]), json={"reason": "x"})
    assert blocked.status_code == 200
    assert blocked.json()["data"]["status"] == "blocked" and blocked.json()["message"] == "Client blocked"
    unblocked = client.post(f"/api/v1/admin/clients/{ids['review_client']}/unblock", headers=auth(tokens["admin"]), json={})
    assert unblocked.status_code == 200 and unblocked.json()["data"]["status"] == "active"


def test_admin_driver_mutations_on_deleted_driver_are_404(env) -> None:
    client, tokens, SessionLocal, ids = env
    assert client.delete("/api/v1/auth/me", headers=auth(tokens["driver2"])).status_code == 200
    driver_id = ids["driver2_profile"]
    not_found = {"success": False, "error": {"code": "NOT_FOUND", "message": "Driver not found"}}

    responses = [
        client.post(f"/api/v1/admin/drivers/{driver_id}/block", headers=auth(tokens["admin"]), json={"reason": "fraud"}),
        client.post(f"/api/v1/admin/drivers/{driver_id}/reject", headers=auth(tokens["admin"]), json={"reason": "x"}),
        client.post(f"/api/v1/admin/drivers/{driver_id}/approve", headers=auth(tokens["admin"]), json={}),
        client.patch(f"/api/v1/admin/drivers/{driver_id}/vehicle", headers=auth(tokens["admin"]), json={"plate_number": "01A111AA"}),
    ]

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json() == not_found
    with SessionLocal() as db:
        profile = db.get(DriverProfile, driver_id)
        assert db.get(User, ids["driver2"]).status == "deleted"
        assert profile.plate_number is None
        assert profile.verification_status == "approved"
