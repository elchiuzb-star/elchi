"""SYNTHETIC parcel size catalog for PostgreSQL tests (ADR-0026, Q140).

Every value here is invented for tests and marked ``synthetic`` - it is never a real tariff or limit. The catalog is
written straight into the tables (two different users as author and confirmer, like the service requires), once per
database; later calls return the same active version.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.contracts.ids import PublicIdPrefix, format_public_id
from tests.pg.conftest import PgDatabase

# code -> (name_uz, icon, length, width, height cm, weight g, volume ml) - synthetic
SYNTHETIC_ITEMS: dict[str, tuple[str, str, int, int, int, int, int]] = {
    "envelope": ("Hujjat / konvert (sintetik)", "envelope", 35, 25, 3, 500, 2_000),
    "small_box": ("Kichik quti (sintetik)", "box_small", 30, 20, 20, 5_000, 12_000),
    "medium_box": ("O'rta quti (sintetik)", "box_medium", 50, 40, 40, 15_000, 80_000),
}


def synthetic_category(db: PgDatabase, code: str = "small_box") -> str:
    """Public id of a category of the active synthetic catalog (created on first use)."""
    with db.engine.begin() as conn:
        version_id = conn.execute(text("SELECT id FROM parcel_category_versions WHERE status = 'active'")).scalar()
        if version_id is None:
            users = [row[0] for row in conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 2"))]
            if len(users) < 2:
                raise RuntimeError("the synthetic catalog needs two users in the test world")
            version_id = conn.execute(text(
                "INSERT INTO parcel_category_versions (public_id, label, status, synthetic, source_note, created_by, "
                "confirmed_by, confirmed_at, effective_from) VALUES (:p, :label, 'active', true, 'synthetic test catalog', "
                ":a, :b, now(), now()) RETURNING id"
            ), {"p": uuid.uuid4(), "label": f"synthetic-{uuid.uuid4().hex[:8]}", "a": users[0], "b": users[1]}).scalar_one()
            for order, (item_code, (name, icon, length, width, height, weight, volume)) in enumerate(SYNTHETIC_ITEMS.items()):
                conn.execute(text(
                    "INSERT INTO parcel_category_items (public_id, catalog_version_id, code, name_uz, icon_key, max_length_cm, "
                    "max_width_cm, max_height_cm, max_weight_g, max_volume_ml, display_order) "
                    "VALUES (:p, :v, :c, :n, :i, :l, :w, :h, :g, :ml, :o)"
                ), {"p": uuid.uuid4(), "v": version_id, "c": item_code, "n": name, "i": icon, "l": length, "w": width,
                    "h": height, "g": weight, "ml": volume, "o": order * 10})
        public = conn.execute(text(
            "SELECT public_id FROM parcel_category_items WHERE catalog_version_id = :v AND code = :c"
        ), {"v": version_id, "c": code}).scalar_one()
    return format_public_id(PublicIdPrefix.PARCEL_CATEGORY, public)
