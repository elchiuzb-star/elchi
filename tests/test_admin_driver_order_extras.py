"""Additive v1 admin endpoints (mobile-app admin panel TODOs).

GET  /api/v1/admin/drivers/{driver_id}/documents | routes | orders   (operator, admin, super_admin)
GET  /api/v1/admin/drivers/{driver_id}/audit-logs                    (admin, super_admin)
POST /api/v1/admin/drivers/{driver_id}/unblock                       (admin, super_admin; emergency block: super_admin)
GET  /api/v1/admin/orders/{order_id}/eligible-drivers                (operator, admin, super_admin)

SQLite suite: auth, 404, envelope/shape and the v1 side of unblock. The v2 eligibility interplay (Q15) needs
PostgreSQL v2 tables and is not covered here.
"""

import pytest
from sqlalchemy import select

from app.models import AuditLog, DriverProfile, DriverRoute, Order, User
from tests.test_admin_driver_verification import (  # noqa: F401 - fixture import
    admin_drivers_client,
    create_driver,
    create_order,
    headers,
)

PAGINATION_KEYS = {"page", "limit", "total", "total_pages"}
DRIVER_LISTS = ("documents", "routes", "orders")


def _assert_page(body: dict) -> dict:
    assert set(body) == {"success", "data", "message"}
    assert body["success"] is True and body["message"] == "OK"
    assert set(body["data"]["pagination"]) == PAGINATION_KEYS
    assert isinstance(body["data"]["items"], list)
    return body["data"]


# --- documents / routes / orders -------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["operator", "admin", "super_admin"])
@pytest.mark.parametrize("kind", DRIVER_LISTS)
def test_staff_can_read_driver_lists(admin_drivers_client, role: str, kind: str) -> None:
    client, tokens, _factory, ids = admin_drivers_client

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}/{kind}", headers=headers(tokens[role]))

    assert response.status_code == 200
    _assert_page(response.json())


def test_driver_documents_and_routes_match_detail(admin_drivers_client) -> None:
    client, tokens, _factory, ids = admin_drivers_client
    detail = client.get(f"/api/v1/admin/drivers/{ids['driver']}", headers=headers(tokens["operator"])).json()["data"]

    documents = client.get(f"/api/v1/admin/drivers/{ids['driver']}/documents", headers=headers(tokens["operator"]))
    routes = client.get(f"/api/v1/admin/drivers/{ids['driver']}/routes", headers=headers(tokens["operator"]))

    doc_page = _assert_page(documents.json())
    assert doc_page["pagination"]["total"] == 5
    assert {item["id"] for item in doc_page["items"]} == {item["id"] for item in detail["documents"]}
    assert set(doc_page["items"][0]) == set(detail["documents"][0])
    route_page = _assert_page(routes.json())
    assert route_page["items"] == detail["routes"]


def test_driver_orders_lists_assigned_orders_only(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    assigned = create_order(factory, ids)
    create_order(factory, ids)  # unassigned: not listed
    db = factory()
    db.get(Order, assigned).assigned_driver_id = ids["driver"]
    db.get(Order, assigned).status = "accepted"
    db.commit()
    db.close()

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}/orders", headers=headers(tokens["admin"]))
    page = _assert_page(response.json())
    assert [item["id"] for item in page["items"]] == [assigned]
    assert page["items"][0]["status"] == "accepted"

    filtered = client.get(
        f"/api/v1/admin/drivers/{ids['driver']}/orders?status=cancelled", headers=headers(tokens["admin"])
    )
    assert _assert_page(filtered.json())["items"] == []
    invalid = client.get(f"/api/v1/admin/drivers/{ids['driver']}/orders?status=nope", headers=headers(tokens["admin"]))
    assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("kind", [*DRIVER_LISTS, "audit-logs"])
def test_driver_lists_unknown_driver_is_404(admin_drivers_client, kind: str) -> None:
    client, tokens, _factory, _ids = admin_drivers_client

    response = client.get(f"/api/v1/admin/drivers/999999/{kind}", headers=headers(tokens["admin"]))

    assert response.status_code == 404
    assert response.json() == {"success": False, "error": {"code": "NOT_FOUND", "message": "Driver not found"}}


@pytest.mark.parametrize("kind", [*DRIVER_LISTS, "audit-logs"])
def test_driver_lists_require_authentication(admin_drivers_client, kind: str) -> None:
    client, _tokens, _factory, ids = admin_drivers_client

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}/{kind}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("role", ["client", "driver_user"])
@pytest.mark.parametrize("kind", [*DRIVER_LISTS, "audit-logs"])
def test_marketplace_users_cannot_read_driver_lists(admin_drivers_client, role: str, kind: str) -> None:
    client, tokens, _factory, ids = admin_drivers_client

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}/{kind}", headers=headers(tokens[role]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- audit logs ------------------------------------------------------------------------------------------------


def test_driver_audit_logs_admin_only_and_scoped(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    other = create_driver(factory, ids, verification_status="approved")
    client.post(f"/api/v1/admin/drivers/{other['driver_id']}/block", headers=headers(tokens["admin"]), json={"reason": "x"})
    approve = client.post(f"/api/v1/admin/drivers/{ids['driver']}/approve", headers=headers(tokens["admin"]), json={})
    assert approve.status_code == 200

    operator = client.get(f"/api/v1/admin/drivers/{ids['driver']}/audit-logs", headers=headers(tokens["operator"]))
    assert operator.status_code == 403
    assert operator.json()["error"] == {"code": "FORBIDDEN", "message": "Admin or super admin role required"}

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}/audit-logs", headers=headers(tokens["super_admin"]))
    page = _assert_page(response.json())
    actions = [item["action"] for item in page["items"]]
    assert actions.count("driver_approved") == 1
    assert actions.count("driver_document_status_updated") == 5
    assert "driver_blocked" not in actions  # the other driver's block is not attributed here
    assert {"id", "actor", "actor_role", "entity_type", "entity_id", "action", "reason", "old_value", "new_value",
            "created_at"} <= set(page["items"][0])


# --- unblock ---------------------------------------------------------------------------------------------------


def _block(client, token: str, driver_id: int, **extra) -> None:
    response = client.post(
        f"/api/v1/admin/drivers/{driver_id}/block", headers=headers(token), json={"reason": "Fraud check", **extra}
    )
    assert response.status_code == 200, response.json()


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_unblock_restores_pre_block_status_without_re_enabling(admin_drivers_client, role: str) -> None:
    client, tokens, factory, ids = admin_drivers_client
    driver = create_driver(factory, ids, verification_status="approved", is_available=True, with_route=True)
    _block(client, tokens["admin"], driver["driver_id"])

    response = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens[role]), json={"reason": "Cleared"}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"success", "data", "message"} and body["message"] == "Driver unblocked"
    data = body["data"]
    assert data["verification_status"] == "approved"
    assert data["user_status"] == "active"
    assert data["is_available"] is False
    assert data["emergency"] is False
    assert data["reason"] == "Cleared"
    db = factory()
    profile = db.get(DriverProfile, driver["driver_id"])
    assert profile.verification_status == "approved" and profile.is_available is False
    assert db.get(User, driver["user_id"]).status == "active"
    routes = list(db.scalars(select(DriverRoute).where(DriverRoute.driver_id == driver["driver_id"])))
    assert routes and all(route.status == "unavailable" for route in routes)  # driver re-enables them
    audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "driver_unblocked", AuditLog.entity_id == driver["driver_id"])
    )
    assert audit is not None and audit.entity_type == "drivers"
    assert audit.details["reason"] == "Cleared"
    assert audit.details["new_value"]["verification_status"] == "approved"
    db.close()


def test_unblock_of_pending_driver_returns_to_pending(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    driver = create_driver(factory, ids, verification_status="pending")
    _block(client, tokens["admin"], driver["driver_id"])

    response = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["admin"]), json={"reason": "ok"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["verification_status"] == "pending"


def test_emergency_block_is_lifted_by_super_admin_only(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    driver = create_driver(factory, ids, verification_status="approved")
    _block(client, tokens["super_admin"], driver["driver_id"], emergency=True)

    admin = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["admin"]), json={"reason": "ok"}
    )
    assert admin.status_code == 403
    assert admin.json()["error"] == {"code": "FORBIDDEN", "message": "Only super_admin can lift an emergency full block"}
    db = factory()
    assert db.get(DriverProfile, driver["driver_id"]).verification_status == "blocked"
    db.close()

    super_admin = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["super_admin"]), json={"reason": "ok"}
    )
    assert super_admin.status_code == 200
    assert super_admin.json()["data"]["emergency"] is True
    assert super_admin.json()["data"]["user_status"] == "active"


def test_block_unblock_block_cycle_uses_latest_block(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    driver = create_driver(factory, ids, verification_status="approved")
    _block(client, tokens["super_admin"], driver["driver_id"], emergency=True)
    client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["super_admin"]), json={"reason": "a"}
    )
    _block(client, tokens["admin"], driver["driver_id"])

    # The earlier emergency block is closed by the unblock: a plain admin may lift the new, ordinary block.
    response = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["admin"]), json={"reason": "b"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["emergency"] is False


def test_unblock_errors(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    driver = create_driver(factory, ids, verification_status="approved")

    not_blocked = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["admin"]), json={"reason": "x"}
    )
    assert not_blocked.status_code == 400
    assert not_blocked.json()["error"] == {"code": "DRIVER_INVALID_STATUS", "message": "Driver is not blocked"}

    _block(client, tokens["admin"], driver["driver_id"])
    no_reason = client.post(f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["admin"]), json={})
    assert no_reason.status_code == 400 and no_reason.json()["error"]["code"] == "VALIDATION_ERROR"

    operator = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", headers=headers(tokens["operator"]), json={"reason": "x"}
    )
    assert operator.status_code == 403 and operator.json()["error"]["code"] == "FORBIDDEN"

    anonymous = client.post(f"/api/v1/admin/drivers/{driver['driver_id']}/unblock", json={"reason": "x"})
    assert anonymous.status_code == 401

    unknown = client.post("/api/v1/admin/drivers/999999/unblock", headers=headers(tokens["admin"]), json={"reason": "x"})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"

    db = factory()
    assert db.get(DriverProfile, driver["driver_id"]).verification_status == "blocked"
    db.close()


# --- eligible drivers ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["operator", "admin", "super_admin"])
def test_eligible_drivers_mirror_assignment_checks(admin_drivers_client, role: str) -> None:
    client, tokens, factory, ids = admin_drivers_client
    order_id = create_order(factory, ids)
    eligible = create_driver(factory, ids, verification_status="approved", with_route=True)
    create_driver(factory, ids, verification_status="pending", with_route=True)
    create_driver(factory, ids, verification_status="approved", with_route=False)
    create_driver(factory, ids, verification_status="approved", with_route=True, user_status="blocked")

    response = client.get(f"/api/v1/admin/orders/{order_id}/eligible-drivers", headers=headers(tokens[role]))

    assert response.status_code == 200
    data = _assert_page(response.json())
    assert data["order_id"] == order_id and data["order_status"] == "published" and data["assignable"] is True
    assert [item["id"] for item in data["items"]] == [eligible["driver_id"]]
    item = data["items"][0]
    assert {"id", "user", "car_model", "plate_number", "verification_status", "is_available", "has_active_bid"} <= set(item)
    assert item["has_active_bid"] is False

    # The listed driver is accepted by the real assignment.
    if role != "operator":
        assign = client.post(
            f"/api/v1/admin/orders/{order_id}/assign-driver",
            headers=headers(tokens[role]),
            json={"driver_id": eligible["driver_id"], "final_price": 50000, "reason": "manual"},
        )
        assert assign.status_code == 200, assign.json()


def test_eligible_drivers_search_and_errors(admin_drivers_client) -> None:
    client, tokens, factory, ids = admin_drivers_client
    order_id = create_order(factory, ids)
    driver = create_driver(factory, ids, verification_status="approved", with_route=True)

    hit = client.get(
        f"/api/v1/admin/orders/{order_id}/eligible-drivers?search=01B", headers=headers(tokens["operator"])
    )
    assert [item["id"] for item in _assert_page(hit.json())["items"]] == [driver["driver_id"]]
    miss = client.get(
        f"/api/v1/admin/orders/{order_id}/eligible-drivers?search=zzz-none", headers=headers(tokens["operator"])
    )
    assert _assert_page(miss.json())["items"] == []

    unknown = client.get("/api/v1/admin/orders/999999/eligible-drivers", headers=headers(tokens["operator"]))
    assert unknown.status_code == 404
    assert unknown.json() == {"success": False, "error": {"code": "NOT_FOUND", "message": "Order not found"}}

    assert client.get(f"/api/v1/admin/orders/{order_id}/eligible-drivers").status_code == 401
    for role in ("client", "driver_user"):
        denied = client.get(f"/api/v1/admin/orders/{order_id}/eligible-drivers", headers=headers(tokens[role]))
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
