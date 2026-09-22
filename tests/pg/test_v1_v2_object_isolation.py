"""No business object is mutable from both engines (Q4, ADR-0006, wave 13).

The stage-2 client publishes v2 listings; the frozen v1 Android app still publishes v1 orders (Q4 keeps the two
parcel markets running in parallel - there is no cutover inside stage 2). What must never happen is a *single*
object that both sides can change, because then two state machines, two lock orders and two money models would
race on one row.

This file asserts that separation where it actually lives, in the schema and in the routers, rather than
trusting that it is "obviously" true:

* a v2 listing/booking id addressed through the v1 order API changes nothing - v1 speaks in `orders.id`
  integers and the v2 aggregates are different tables with opaque public ids;
* no foreign key joins the legacy order tables to the v2 write tables in either direction;
* the legacy projection inside v2 is read-only: there is no command route under `/admin/legacy-orders`;
* v1 reaches into v2 only through service functions (ADR-0006) - no v1 module imports a v2 model or repository.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.models import User
from tests.pg.bookings.conftest import (  # noqa: F401  (bw/world are fixtures)
    BW,
    accept,
    bw,
    driver_trip,
    propose,
    publish_listing,
    parcel_request_body,
    scalar,
    world,
)
from tests.pg.conftest import PgDatabase

pytestmark = pytest.mark.pg

ROOT = Path(__file__).resolve().parents[2]
V1_MODULES = [
    *(ROOT / "app" / "api" / "v1").glob("*.py"),
    *(ROOT / "app" / "services").glob("*.py"),
]
# The v2 write tables: every aggregate the stage-2 engine owns.
V2_WRITE_TABLES = ("listings", "bookings", "trips", "proposal_threads", "proposal_versions", "wallet_accounts")
LEGACY_TABLES = ("orders", "order_offers", "bids")


def parcel_booking(bw: BW) -> tuple[str, int]:
    """One published v2 parcel listing with an accepted booking on it."""
    listing_id = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    _, trip_public = driver_trip(bw, bw.w.driver_id, "01A808AA")
    ref = propose(bw, listing_id, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000,
                  dropoff="C", price_basis="total")
    booking = accept(bw, ref, bw.w.client_id)
    return listing_id, booking.id


def v2_fingerprint(bw: BW, booking_id: int) -> tuple:
    with bw.db.engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT b.version, b.service_status, b.updated_at, l.version, l.status"
                "  FROM bookings b JOIN listings l ON l.id = b.request_listing_id WHERE b.id = :b"
            ),
            {"b": booking_id},
        ).one()


def test_the_v1_order_api_cannot_reach_a_v2_booking(bw: BW) -> None:
    from app.schemas.admin_driver import AdminDriverBlock  # noqa: F401  (import guard: v1 schemas load)
    from app.services import admin_order_service, order_service

    listing_id, booking_id = parcel_booking(bw)
    before = v2_fingerprint(bw, booking_id)

    with bw.db.session() as s:
        client = s.get(User, bw.w.client_id)
        admin = s.get(User, bw.super_id)

        # The numeric id of a v2 booking, offered to every v1 mutation that takes an order id.
        assert isinstance(order_service.get_owned_order(s, client, booking_id), JSONResponse)
        assert isinstance(order_service.publish_order(s, client, booking_id), JSONResponse)
        assert isinstance(admin_order_service.get_admin_order_detail(s, booking_id), JSONResponse)
        assert isinstance(
            admin_order_service.update_admin_order_status(s, admin, booking_id, _status_payload()), JSONResponse
        )
        s.rollback()

    assert v2_fingerprint(bw, booking_id) == before, "a v1 call must not touch a v2 aggregate"
    # The public id is not even an integer, so it can never be routed into v1 at all.
    assert not listing_id.isdigit()


def _status_payload():  # noqa: ANN202
    from app.schemas.admin_order import AdminOrderStatusUpdate

    return AdminOrderStatusUpdate(status="confirmed", reason="isolation probe")


def test_no_foreign_key_joins_the_two_engines(pg_db: PgDatabase) -> None:
    joins = pg_db_fk_pairs(pg_db)
    crossing = [
        (child, parent)
        for child, parent in joins
        if (child in LEGACY_TABLES and parent in V2_WRITE_TABLES) or (child in V2_WRITE_TABLES and parent in LEGACY_TABLES)
    ]
    assert crossing == [], f"a foreign key would let one engine's write cascade into the other: {crossing}"


def pg_db_fk_pairs(pg_db: PgDatabase) -> list[tuple[str, str]]:
    with pg_db.engine.connect() as conn:
        return [
            (row[0], row[1])
            for row in conn.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
                      FROM pg_constraint c
                     WHERE c.contype = 'f'
                    """
                )
            ).all()
        ]


def test_the_legacy_projection_inside_v2_is_read_only() -> None:
    from app.modules.operations.api import router

    legacy = [route for route in router.routes if "legacy-orders" in getattr(route, "path", "")]
    assert legacy, "the legacy projection should still be reachable"
    for route in legacy:
        assert set(route.methods) <= {"GET", "HEAD"}, f"{route.path} exposes {route.methods}"


def test_v1_modules_touch_v2_only_through_service_functions() -> None:
    """ADR-0006: v1 may read v2 through a domain's public service, never through its models or repository."""
    allowed_leaves = {"service", "views", "ports", "web"}
    offenders: list[str] = []
    for path in V1_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("app.modules."):
                continue
            parts = node.module.split(".")
            # `from app.modules.<domain> import service` and `from app.modules.<domain>.service import fn`
            leaves = [alias.name for alias in node.names] if len(parts) == 3 else [parts[-1]]
            for leaf in leaves:
                if leaf not in allowed_leaves:
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {node.module}.{leaf}")
    assert offenders == [], f"v1 must not reach into v2 internals: {offenders}"
