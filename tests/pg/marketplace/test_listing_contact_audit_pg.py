"""BR M2 on PostgreSQL via HTTP: staff views of listing phones leave an audit row without values; owner views don't."""

from __future__ import annotations

from tests.pg.marketplace.catalog_world import synthetic_category

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate
from tests.pg.identity.a1_world import World
from tests.pg.marketplace.test_a1_api_pg import auth, client  # noqa: F401  (fixture)

pytestmark = pytest.mark.pg

SENDER_PHONE, RECEIVER_PHONE = "+998900000201", "+998977777777"


def _audit_rows(world: World) -> list[dict]:
    with world.db.engine.connect() as conn:
        return list(conn.execute(text("SELECT details FROM audit_logs WHERE action = 'listing_contacts_viewed' ORDER BY id")).scalars())


def test_staff_listing_phone_view_is_audited_without_values(client, world: World) -> None:  # noqa: F811
    body = ListingCreate.model_validate(
        {
            "kind": "request",
            "service_type": "parcel",
            "origin_stop_id": world.stop_public_ids["A"],
            "destination_stop_id": world.stop_public_ids["C"],
            "departure_window_start": world.base_time.isoformat(),
            "departure_window_end": (world.base_time + timedelta(hours=2)).isoformat(),
            "price_basis": "total",
            "unit_price_minor": 7_000_000,
            "parcel": {
                "parcel_type": "documents", "category_id": synthetic_category(world.db), "payer": "sender",  # Q140
                "sender": {"name": "Aziza Karimova", "phone": SENDER_PHONE},
                "receiver": {"name": "Nodira Qosimova", "phone": RECEIVER_PHONE},
            },
        }
    )
    with world.db.session() as s:
        listing = marketplace_service.create_listing(s, owner_user_id=world.client_id, data=body)
        listing_id = marketplace_service.listing_public_id(listing)
        marketplace_service.publish_listing(s, listing_public_id=listing_id, actor_user_id=world.client_id, expected_version=1)
        s.commit()

    owner = client.get(f"/api/v2/listings/{listing_id}", headers=auth(world.client_id, "client"))
    assert owner.status_code == 200 and owner.json()["data"]["parcel"]["receiver"]["phone"] == RECEIVER_PHONE
    assert _audit_rows(world) == []  # owner views are not audited

    public = client.get(f"/api/v2/listings/{listing_id}", headers=auth(world.driver_id, "driver"))
    assert public.status_code == 200 and RECEIVER_PHONE not in public.text
    assert _audit_rows(world) == []  # no phone shown -> no row

    staff = client.get(f"/api/v2/listings/{listing_id}", headers=auth(world.admin_id, "admin"))
    assert staff.status_code == 200 and staff.json()["data"]["parcel"]["sender"]["phone"] == SENDER_PHONE
    rows = _audit_rows(world)
    assert rows == [{"listing_ids": [listing_id], "surface": "L2", "fields": ["parcel.receiver.phone", "parcel.sender.phone"]}]
    assert SENDER_PHONE not in str(rows) and RECEIVER_PHONE not in str(rows)
