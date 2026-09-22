"""Wave 5 / A10b: migration 0066 types the legacy naive timestamps (Q9) - on real PostgreSQL.

Proves:

* all eleven v1 columns are ``timestamptz`` after the chain, and the stored **instant** is unchanged;
* the conversion did not rewrite the tables (same filenode) - the ACCESS EXCLUSIVE lock is short;
* 0065's projection survives: the views, their comment and their INSTEAD OF read-only triggers are back;
* **v1 wire compatibility (AGENTS §2)**: a v1 response still serializes these fields without an offset, exactly
  as the frozen Android client has always received them, while ``created_at`` keeps its offset as before;
* the migration **refuses** to convert a column whose data contradicts UTC instead of casting it silently, and
  leaves the schema untouched in that case (Q9 evidence, spec §18.3 forward fix).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi.encoders import jsonable_encoder

import app.models  # noqa: F401  (registers the legacy mappers)
from app.models import City, Order, User
from app.services import admin_order_service, order_service
from tests.pg.conftest import PgDatabase, _libpq_dsn, run_alembic

pytestmark = pytest.mark.pg

REVISION_0065 = "20260916_0065"
CONVERTED: dict[str, tuple[str, ...]] = {
    "orders": ("published_at", "accepted_at", "picked_up_at", "in_transit_at", "delivered_at", "confirmed_at",
               "cancelled_at"),
    "disputes": ("resolved_at",),
    "driver_documents": ("reviewed_at",),
    "order_offers": ("shown_at", "responded_at"),
}
PUBLISHED_AT = datetime(2026, 9, 10, 4, 30, 15, tzinfo=UTC)


def _connect(db: PgDatabase) -> psycopg.Connection:
    return psycopg.connect(_libpq_dsn(db.url), autocommit=True)


def _seed_order(db: PgDatabase, *, published_at: datetime | None = PUBLISHED_AT) -> int:
    with db.session() as s:
        client = User(phone="+998970000201", role="client", status="active", is_phone_verified=True)
        from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
        to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
        s.add_all([client, from_city, to_city])
        s.flush()
        order = Order(
            order_number="EL-TS-0001", client_id=client.id, from_city_id=from_city.id, to_city_id=to_city.id,
            pickup_address="Toshkent", dropoff_address="Samarqand", sender_phone="+998901234567",
            receiver_phone="+998911112233", status="published", published_at=published_at,
            final_price=Decimal("50000.00"),
        )
        s.add(order)
        s.commit()
        return order.id


def test_every_legacy_column_is_timestamptz_and_keeps_its_instant(pg_db: PgDatabase) -> None:
    order_id = _seed_order(pg_db)
    with _connect(pg_db) as conn:
        types = dict(
            conn.execute(
                "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name IN "
                "('published_at','accepted_at','picked_up_at','in_transit_at','delivered_at','confirmed_at',"
                " 'cancelled_at','resolved_at','reviewed_at','shown_at','responded_at') "
                "AND table_name IN ('orders','disputes','driver_documents','order_offers')"
            ).fetchall()
        )
        expected = {f"{table}.{column}" for table, columns in CONVERTED.items() for column in columns}
        assert set(types) == expected
        assert set(types.values()) == {"timestamp with time zone"}, types

        stored = conn.execute("SELECT published_at FROM orders WHERE id = %s", (order_id,)).fetchone()[0]
        assert stored == PUBLISHED_AT  # same instant, now aware


def test_conversion_did_not_rewrite_the_tables(pg_db: PgDatabase) -> None:
    """PG >= 12 skips the rewrite when the session zone is UTC, which is why 0066 pins it with SET LOCAL."""
    with _connect(pg_db) as conn:
        before = {
            table: conn.execute("SELECT pg_relation_filenode(%s)", (f"public.{table}",)).fetchone()[0]
            for table in CONVERTED
        }
        assert run_alembic(pg_db.url, "downgrade", REVISION_0065).returncode == 0
        assert run_alembic(pg_db.url, "upgrade", "head").returncode == 0
        after = {
            table: conn.execute("SELECT pg_relation_filenode(%s)", (f"public.{table}",)).fetchone()[0]
            for table in CONVERTED
        }
    assert after == before, "ALTER ... TYPE timestamptz rewrote a table: the lock window is longer than planned"


def test_projection_views_and_their_read_only_triggers_survive_the_conversion(pg_db: PgDatabase) -> None:
    _seed_order(pg_db)
    with _connect(pg_db) as conn:
        assert conn.execute("SELECT count(*) FROM legacy_parcel_orders_v").fetchone()[0] == 1
        comment = conn.execute(
            "SELECT obj_description(to_regclass('public.legacy_parcel_orders_v'), 'pg_class')"
        ).fetchone()[0]
        assert comment and "AC37" in comment
        # the view now carries the typed column ...
        assert conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'legacy_parcel_orders_v' AND column_name = 'published_at'"
        ).fetchone()[0] == "timestamp with time zone"
        # ... and is still read-only for every role (0065's INSTEAD OF triggers were restored).
        with pytest.raises(psycopg.errors.RestrictViolation) as excinfo:
            conn.execute("DELETE FROM legacy_parcel_orders_v")
        assert excinfo.value.diag.constraint_name == "legacy_object_read_only"


def test_v1_responses_keep_the_offset_free_shape(pg_db: PgDatabase) -> None:
    """AGENTS §2: the DB type changed, the Android wire format did not."""
    order_id = _seed_order(pg_db)
    with pg_db.session() as session:
        order = session.get(Order, order_id)
        assert order.published_at == PUBLISHED_AT  # aware in Python
        for payload in (
            order_service.order_detail_to_dict(session, order),
            admin_order_service.admin_order_detail_to_dict(session, order),
        ):
            encoded = jsonable_encoder(payload)
            assert encoded["published_at"] == "2026-09-10T04:30:15", encoded["published_at"]
            # created_at was always timestamptz and always carried its offset - that does not change either.
            assert encoded["created_at"].endswith("+00:00") or encoded["created_at"].endswith("Z")


def test_0066_refuses_a_column_whose_data_contradicts_utc(pg_db: PgDatabase) -> None:
    order_id = _seed_order(pg_db)
    assert run_alembic(pg_db.url, "downgrade", REVISION_0065).returncode == 0
    with _connect(pg_db) as conn:
        assert conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'published_at'"
        ).fetchone()[0] == "timestamp without time zone"
        # A value five hours in the future of the row's whole lifetime: the UTC+5 wall clock of Asia/Tashkent.
        conn.execute(
            "UPDATE orders SET published_at = (created_at AT TIME ZONE 'UTC') + INTERVAL '5 hours' WHERE id = %s",
            (order_id,),
        )

    result = run_alembic(pg_db.url, "upgrade", "head")
    assert result.returncode != 0, result.stdout
    assert "0066 refuses to convert public.orders.published_at" in result.stdout + result.stderr

    with _connect(pg_db) as conn:
        # Nothing was altered: the column is still naive and the projection is still the 0065 one.
        assert conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'published_at'"
        ).fetchone()[0] == "timestamp without time zone"
        assert conn.execute("SELECT count(*) FROM legacy_parcel_orders_v").fetchone()[0] == 1
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION_0065


def test_audit_script_reports_utc_for_real_rows(pg_db: PgDatabase) -> None:
    """scripts/legacy_timestamp_audit.py is the pre-deploy evidence; it must agree with the migration."""
    import importlib.util
    import sys
    from pathlib import Path

    _seed_order(pg_db, published_at=PUBLISHED_AT)
    with pg_db.session() as session:
        order = session.get(Order, 1) or session.query(Order).first()
        order.created_at = PUBLISHED_AT - timedelta(minutes=5)
        order.updated_at = PUBLISHED_AT + timedelta(minutes=5)
        session.commit()

    spec = importlib.util.spec_from_file_location(
        "elchi_ts_audit", Path(__file__).resolve().parents[3] / "scripts" / "legacy_timestamp_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    with _connect(pg_db) as conn:
        results = module.audit(conn, "Asia/Tashkent")
    by_name = {f"{r.table}.{r.column}": r for r in results}
    # After 0066 every column is already typed; the audit says so instead of inventing a verdict.
    assert {r.verdict for r in results} == {"already_typed"}, by_name
