"""Wave 5 / A10b: the legacy read-only projection on real PostgreSQL (Q4, AC37, spec §18.1 M4).

Proves, against a real database and the real migration chain:

* the four ``legacy_*_v`` views project v1 rows with the agreed mapping (minor units, ``unknown_*`` flags,
  ``engine='v1'``) and carry no phone, address or cargo photo;
* **read-only is enforced, not documented**: INSERT/UPDATE/DELETE through every view is refused for the database
  owner (INSTEAD OF trigger, ``legacy_object_read_only``) *and* for the app role of decision 36 (privilege);
* AC37: rebuilding the projection (downgrade + upgrade of 0065) changes no row, duplicates nothing and writes
  nothing into any v2 write table - reading it never creates a booking, a ledger row or a wallet hold, so the
  old calculated fee cannot be charged again (spec §18.2);
* the O8 reader refuses a caller without ``ops.view`` and 404s an unknown order number.
"""

from __future__ import annotations

import importlib.util
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import errors, sql
from sqlalchemy.engine import URL

import app.models  # noqa: F401  (registers the legacy mappers)
from app.contracts.errors import DomainError, ErrorCode
from app.models import City, Dispute, District, Order, Rating, StatusHistory, User
from app.modules.operations import service as operations_service
from tests.pg.conftest import PgDatabase, _libpq_dsn, run_alembic

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]
PREVIOUS_REVISION = "20260916_0064"
LEGACY_VIEWS = (
    "legacy_parcel_orders_v",
    "legacy_order_status_history_v",
    "legacy_ratings_v",
    "legacy_disputes_v",
)
# Every v2 table a legacy row must never reach (ADR-0006 §3, Q4).
V2_WRITE_TABLES = (
    "listings",
    "trips",
    "bookings",
    "proposal_threads",
    "proposal_versions",
    "ratings_v2",
    "disputes_v2",
    "ledger_transactions",
    "ledger_entries",
    "wallet_holds",
    "wallet_accounts",
)


def _load_db_roles():
    import sys

    spec = importlib.util.spec_from_file_location("elchi_db_roles_legacy", REPO_ROOT / "scripts" / "db_roles.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve the defining module through sys.modules
    spec.loader.exec_module(module)
    return module


db_roles = _load_db_roles()


@dataclass(frozen=True)
class Seeded:
    order_id: int
    order_number: str
    client_id: int
    staff_id: int


def _seed(db: PgDatabase) -> Seeded:
    """One finished v1 order with its history, rating and dispute - the rows the projection reads."""
    number = f"EL{uuid.uuid4().hex[:8].upper()}"
    with db.session() as s:
        client = User(phone="+998970000101", role="client", status="active", is_phone_verified=True)
        staff = User(phone="+998970000102", role="admin", status="active", is_phone_verified=True)
        from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=True)
        to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
        s.add_all([client, staff, from_city, to_city])
        s.flush()
        district = District(city_id=from_city.id, name_uz="Chilonzor", is_active=True)
        s.add(district)
        s.flush()
        order = Order(
            order_number=number, client_id=client.id, from_city_id=from_city.id, to_city_id=to_city.id,
            from_district_id=district.id, pickup_address="Toshkent, Chilonzor 12",
            dropoff_address="Samarqand, Registon 3", sender_phone="+998901234567", receiver_phone="+998911112233",
            cargo_photo_url="private/cargo/secret.jpg", cargo_type="documents", status="confirmed",
            final_price=Decimal("150000.00"), system_fee=Decimal("12345.67"), system_fee_rate=Decimal("0.1000"),
            driver_income=Decimal("137654.33"), client_price=Decimal("140000.50"),
        )
        s.add(order)
        s.flush()
        driver_profile_id = _driver_profile(s)
        s.add_all(
            [
                StatusHistory(order_id=order.id, old_status="published", new_status="confirmed",
                              changed_by_user_id=staff.id, changed_by_role="admin", reason="manual"),
                Rating(order_id=order.id, client_id=client.id, driver_id=driver_profile_id, rating=5,
                       comment="rahmat"),
                Dispute(order_id=order.id, opened_by_user_id=client.id, reason="late", comment="kech keldi",
                        status="open", previous_order_status="delivered"),
            ]
        )
        s.commit()
        return Seeded(order_id=order.id, order_number=number, client_id=client.id, staff_id=staff.id)


def _driver_profile(session) -> int:
    """A minimal approved driver profile: ratings reference driver_profiles(id)."""
    from app.models import DriverProfile

    user = User(phone="+998970000103", role="driver", status="active", is_phone_verified=True)
    session.add(user)
    session.flush()
    profile = DriverProfile(user_id=user.id, full_name="Driver A", verification_status="approved",
                            is_available=True, plate_number="01A777AA")
    session.add(profile)
    session.flush()
    return profile.id


def _connect(url: URL) -> psycopg.Connection:
    return psycopg.connect(_libpq_dsn(url), autocommit=True)


def test_views_project_legacy_rows_without_pii(pg_db: PgDatabase) -> None:
    seeded = _seed(pg_db)
    with _connect(pg_db.url) as conn:
        row = conn.execute(
            "SELECT legacy_order_number, status, from_city_name, from_district_name, to_city_name, "
            "final_price_minor, legacy_calculated_fee_minor, client_price_minor, unknown_time, "
            "unknown_dimensions, engine FROM legacy_parcel_orders_v WHERE legacy_order_id = %s",
            (seeded.order_id,),
        ).fetchone()
        assert row == (
            seeded.order_number, "confirmed", "Toshkent", "Chilonzor", "Samarqand",
            15_000_000, 1_234_567, 14_000_050, True, True, "v1",
        )
        # No PII column exists at all: a caller cannot select what the view does not carry (ADR-0020).
        columns = {
            name
            for (name,) in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'legacy_parcel_orders_v'"
            ).fetchall()
        }
        assert columns.isdisjoint(
            {"sender_phone", "receiver_phone", "pickup_address", "dropoff_address", "cargo_photo_url",
             "pickup_lat", "pickup_lng", "dropoff_lat", "dropoff_lng", "comment"}
        )
        assert conn.execute("SELECT count(*) FROM legacy_order_status_history_v").fetchone()[0] == 1
        assert conn.execute("SELECT stars, engine FROM legacy_ratings_v").fetchone() == (5, "v1")
        assert conn.execute("SELECT status, engine FROM legacy_disputes_v").fetchone() == ("open", "v1")
        # previous_order_status stays in v1 (DATA_MODEL §3).
        dispute_columns = {
            name
            for (name,) in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'legacy_disputes_v'"
            ).fetchall()
        }
        assert "previous_order_status" not in dispute_columns


def test_every_view_refuses_writes_for_the_database_owner(pg_db: PgDatabase) -> None:
    """The INSTEAD OF trigger holds for every role, so a psql session cannot edit a legacy row through v2."""
    _seed(pg_db)
    statements = {
        "legacy_parcel_orders_v": (
            "INSERT INTO legacy_parcel_orders_v (legacy_order_number) VALUES ('X')",
            "UPDATE legacy_parcel_orders_v SET status = 'cancelled'",
            "DELETE FROM legacy_parcel_orders_v",
        ),
        "legacy_order_status_history_v": (
            "INSERT INTO legacy_order_status_history_v (new_status) VALUES ('x')",
            "UPDATE legacy_order_status_history_v SET new_status = 'x'",
            "DELETE FROM legacy_order_status_history_v",
        ),
        "legacy_ratings_v": (
            "INSERT INTO legacy_ratings_v (stars) VALUES (5)",
            "UPDATE legacy_ratings_v SET stars = 1",
            "DELETE FROM legacy_ratings_v",
        ),
        "legacy_disputes_v": (
            "INSERT INTO legacy_disputes_v (status) VALUES ('open')",
            "UPDATE legacy_disputes_v SET status = 'resolved'",
            "DELETE FROM legacy_disputes_v",
        ),
    }
    with _connect(pg_db.url) as conn:
        for view, sqls in statements.items():
            for statement in sqls:
                with pytest.raises(errors.RestrictViolation) as excinfo:
                    conn.execute(statement)
                assert excinfo.value.diag.constraint_name == "legacy_object_read_only", (view, statement)
    # Nothing changed.
    with _connect(pg_db.url) as conn:
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM orders").fetchone()[0] == "confirmed"


def test_app_role_keeps_select_and_loses_dml_on_the_projection(pg_empty_db: PgDatabase) -> None:
    """Second layer (decision 36): the blanket DML grant covers views, so db_roles revokes it again."""
    suffix = uuid.uuid4().hex[:10]
    owner, app = f"elchi_pgtest_owner_{suffix}", f"elchi_pgtest_app_{suffix}"
    password = uuid.uuid4().hex
    plan = db_roles.RolePlan(database=pg_empty_db.name, owner=owner, owner_password=password,
                             app=app, app_password=password)
    admin_dsn = _libpq_dsn(pg_empty_db.url)
    try:
        db_roles.bootstrap(admin_dsn, plan)
        owner_url = pg_empty_db.url.set(username=owner, password=password)
        result = run_alembic(owner_url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr
        db_roles.bootstrap(admin_dsn, plan)  # post-migration run, as deploy.sh does

        app_url = pg_empty_db.url.set(username=app, password=password)
        with _connect(app_url) as conn:
            for view in LEGACY_VIEWS:
                assert conn.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == 0  # SELECT stays
                with pytest.raises(errors.InsufficientPrivilege):
                    conn.execute(f"DELETE FROM {view}")
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            for role in (app, owner):
                conn.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role)))
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def test_ac37_rebuilding_the_projection_twice_duplicates_nothing_and_writes_nothing(pg_db: PgDatabase) -> None:
    seeded = _seed(pg_db)

    def snapshot() -> dict[str, int]:
        with _connect(pg_db.url) as conn:
            counts = {view: conn.execute(f"SELECT count(*) FROM {view}").fetchone()[0] for view in LEGACY_VIEWS}
            counts.update(
                {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in V2_WRITE_TABLES}
            )
            return counts

    before = snapshot()
    assert before["legacy_parcel_orders_v"] == 1
    assert all(before[table] == 0 for table in V2_WRITE_TABLES), before

    for _ in range(2):
        assert run_alembic(pg_db.url, "downgrade", PREVIOUS_REVISION).returncode == 0
        assert run_alembic(pg_db.url, "upgrade", "head").returncode == 0

    assert snapshot() == before
    with _connect(pg_db.url) as conn:
        # The one legacy order is still one row, still with its calculated (never charged) fee.
        assert conn.execute(
            "SELECT legacy_calculated_fee_minor FROM legacy_parcel_orders_v WHERE legacy_order_number = %s",
            (seeded.order_number,),
        ).fetchall() == [(1_234_567,)]


def test_o8_reader_requires_ops_view_and_reports_unknown_order_as_not_found(pg_db: PgDatabase) -> None:
    seeded = _seed(pg_db)
    with pg_db.session() as session:
        rows = operations_service.legacy_orders(session, actor_user_id=seeded.staff_id)
        assert [row.legacy_order_number for row in rows] == [seeded.order_number]
        row = rows[0]
        assert row.route_summary == "Toshkent (Chilonzor) → Samarqand"
        assert row.flags == ("unknown_time", "unknown_dimensions")
        assert row.final_price_minor == 15_000_000
        assert row.legacy_calculated_fee_minor == 1_234_567

        detail = operations_service.legacy_order(
            session, actor_user_id=seeded.staff_id, legacy_order_number=seeded.order_number
        )
        assert detail.legacy_order_id == seeded.order_id

        with pytest.raises(DomainError) as unknown:
            operations_service.legacy_order(
                session, actor_user_id=seeded.staff_id, legacy_order_number="EL-DOES-NOT-EXIST"
            )
        assert unknown.value.code is ErrorCode.NOT_FOUND

        with pytest.raises(DomainError) as forbidden:
            operations_service.legacy_orders(session, actor_user_id=seeded.client_id)
        assert forbidden.value.code in {ErrorCode.FORBIDDEN, ErrorCode.CAPABILITY_REQUIRED}
