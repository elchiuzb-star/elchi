"""Shared PostgreSQL fixtures for A1 tests (identity, trips, marketplace).

Seeds real rows into A2's geo tables and A3's ``commission_policies`` so every DB
foreign key is exercised, then registers ports:

* ``SqlGeoAdapter`` - TEST-ONLY stand-in for ``app.modules.geo.service`` lookups
  (A2 has not published them yet); reads the real geo tables.
* ``FakeFlags`` / ``FakeFees`` - narrow fakes for ``is_flag_enabled`` (A2) and
  ``quote_fee`` (A3). ``FakeFees`` returns the seeded real policy id with a
  mutable ``fee_bps`` so AC43 (policy change after a quote) can be simulated.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers legacy mappers)
from app.contracts.enums import FeatureFlagKey
from app.contracts.errors import DomainError
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id
from app.contracts.timeutil import utc_now
from app.models import DriverProfile, User
from app.modules.marketplace import ports as marketplace_ports
from app.modules.marketplace.ports import CorridorRef, FeeQuote, MarketplacePorts, PolicyRef
from app.modules.marketplace.schemas import ListingCreate
from app.modules.trips import ports as trips_ports
from app.modules.trips import service as trips_service
from app.modules.trips.ports import RouteStopRef, RouteVersionRef, StopRef
from app.modules.trips.schemas import TripCreate, VehicleCreate
from tests.pg.conftest import PgDatabase

STOP_NAMES = ("A", "B", "C", "D")
STOP_COORDS = {"A": (69.24, 41.30), "B": (67.90, 40.10), "C": (66.60, 39.20), "D": (65.80, 38.86)}


# --- ports -------------------------------------------------------------------------------------------


def _stop(row) -> StopRef:  # noqa: ANN001
    return StopRef(
        id=row["id"],
        public_id=format_public_id(PublicIdPrefix.STOP, row["public_id"]),
        corridor_id=row["corridor_id"],
        name_uz=row["name_uz"],
        name_ru=row["name_ru"],
        is_active=row["is_active"],
    )


class SqlGeoAdapter:
    _STOPS = "SELECT id, public_id, corridor_id, name_uz, name_ru, is_active FROM corridor_stops"

    def stops_by_public_ids(self, session: Session, public_ids: Sequence[str]) -> dict[str, StopRef]:
        wanted: dict[uuid.UUID, str] = {}
        for public_id in public_ids:
            try:
                wanted[parse_public_id(public_id, PublicIdPrefix.STOP)] = public_id
            except DomainError:
                continue
        rows = session.execute(text(f"{self._STOPS} WHERE public_id = ANY(:ids)"), {"ids": list(wanted)}).mappings()
        return {wanted[row["public_id"]]: _stop(row) for row in rows}

    def stops_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, StopRef]:
        rows = session.execute(text(f"{self._STOPS} WHERE id = ANY(:ids)"), {"ids": list(ids)}).mappings()
        return {row["id"]: _stop(row) for row in rows}

    def corridors_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, CorridorRef]:
        rows = session.execute(
            text("SELECT id, public_id, rollout_state FROM service_corridors WHERE id = ANY(:ids)"), {"ids": list(ids)}
        ).mappings()
        return {
            row["id"]: CorridorRef(row["id"], format_public_id(PublicIdPrefix.CORRIDOR, row["public_id"]), row["rollout_state"])
            for row in rows
        }

    def route_version_by_public_id(self, session: Session, public_id: str) -> RouteVersionRef | None:
        value = parse_public_id(public_id, PublicIdPrefix.ROUTE_VERSION)
        route_id = session.execute(text("SELECT id FROM route_versions WHERE public_id = :u"), {"u": value}).scalar()
        return None if route_id is None else self.route_versions_by_ids(session, [route_id]).get(route_id)

    def route_versions_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, RouteVersionRef]:
        routes = session.execute(
            text("SELECT id, public_id, status FROM route_versions WHERE id = ANY(:ids)"), {"ids": list(ids)}
        ).mappings().all()
        result = {}
        for route in routes:
            stops = session.execute(
                text(
                    "SELECT seq, stop_id, cumulative_distance_m, cumulative_duration_s FROM route_version_stops "
                    "WHERE route_version_id = :id ORDER BY seq"
                ),
                {"id": route["id"]},
            ).all()
            result[route["id"]] = RouteVersionRef(
                id=route["id"],
                public_id=format_public_id(PublicIdPrefix.ROUTE_VERSION, route["public_id"]),
                status=route["status"],
                stops=tuple(RouteStopRef(*row) for row in stops),
            )
        return result


@dataclass
class FakeFlags:
    disabled: set[FeatureFlagKey] = field(default_factory=set)
    calls: list[tuple[FeatureFlagKey, int]] = field(default_factory=list)

    def is_enabled(self, session: Session, key: FeatureFlagKey, *, corridor_id: int) -> bool:
        self.calls.append((key, corridor_id))
        return key not in self.disabled


@dataclass
class FakeFees:
    policy_id: int
    policy_public_id: str
    policy_kind: str = "standard"
    fee_bps: int = 1500

    def quote(self, session: Session, *, corridor_id: int, service_type, total_minor: int, at: datetime) -> FeeQuote:  # noqa: ANN001
        return FeeQuote(self.policy_id, self.policy_public_id, self.policy_kind, self.fee_bps)

    def policy_refs(self, session: Session, policy_ids: Sequence[int]) -> dict[int, PolicyRef]:
        return {policy_id: PolicyRef(self.policy_public_id, self.policy_kind) for policy_id in policy_ids}


# --- world -------------------------------------------------------------------------------------------


@dataclass
class World:
    db: PgDatabase
    admin_id: int
    client_id: int
    client2_id: int
    driver_id: int
    driver2_id: int
    corridor_id: int
    stop_ids: dict[str, int]
    stop_public_ids: dict[str, str]
    route_id: int
    route_public_id: str
    policy_id: int
    flags: FakeFlags
    fees: FakeFees
    base_time: datetime


def add_user(session: Session, phone: str, role: str, *, full_name: str | None = None, driver_status: str | None = None) -> int:
    user = User(phone=phone, role=role, status="active", is_phone_verified=True, full_name=full_name)
    session.add(user)
    session.flush()
    if driver_status is not None:
        session.add(DriverProfile(user_id=user.id, full_name=full_name, verification_status=driver_status))
        session.flush()
    return user.id


def build_world(db: PgDatabase) -> World:
    with db.session() as s:
        admin = add_user(s, "+998900000100", "admin", full_name="Admin Adminov")
        client = add_user(s, "+998900000201", "client", full_name="Aziza Karimova")
        client2 = add_user(s, "+998900000202", "client", full_name="Bekzod Aliyev")
        driver = add_user(s, "+998900000301", "driver", full_name="Dilshod Rahimov", driver_status="approved")
        driver2 = add_user(s, "+998900000302", "driver", full_name="Jasur Toshev", driver_status="approved")
        regions = [
            s.execute(
                text("INSERT INTO regions (public_id, code, name_uz) VALUES (gen_random_uuid(), :c, :n) RETURNING id"),
                {"c": code, "n": name},
            ).scalar_one()
            for code, name in (("UZ-TK", "Toshkent"), ("UZ-QA", "Qashqadaryo"))
        ]
        district = s.execute(
            text("INSERT INTO geo_districts (public_id, region_id, name_uz) VALUES (gen_random_uuid(), :r, 'Chiroqchi') RETURNING id"),
            {"r": regions[1]},
        ).scalar_one()
        corridor = s.execute(
            text(
                "INSERT INTO service_corridors (public_id, name, origin_region_id, destination_region_id, rollout_state, "
                "created_by, updated_by) VALUES (gen_random_uuid(), 'Toshkent - Qarshi', :o, :d, 'draft', :a, :a) RETURNING id"
            ),
            {"o": regions[0], "d": regions[1], "a": admin},
        ).scalar_one()
        s.execute(
            text(
                "INSERT INTO corridor_config_versions (corridor_id, revision, search_radius_m, default_max_detour_minutes, "
                "default_max_detour_m, created_by) VALUES (:c, 1, 3000, 15, 5000, :a)"
            ),
            {"c": corridor, "a": admin},
        )
        stop_ids, stop_public_ids = {}, {}
        for name in STOP_NAMES:
            lng, lat = STOP_COORDS[name]
            row = s.execute(
                text(
                    "INSERT INTO corridor_stops (public_id, corridor_id, geo_district_id, name_uz, name_ru, point, is_active, "
                    "verified_by, verified_at, meeting_note) VALUES (gen_random_uuid(), :c, :d, :n, :n, "
                    "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), true, :a, now(), 'Bekat oldida') RETURNING id, public_id"
                ),
                {"c": corridor, "d": district, "n": f"Bekat {name}", "lng": lng, "lat": lat, "a": admin},
            ).one()
            stop_ids[name] = row.id
            stop_public_ids[name] = format_public_id(PublicIdPrefix.STOP, row.public_id)
        for state in ("internal", "pilot"):  # A2 (0046): pilot needs >= 2 active stops with meeting notes
            s.execute(text("UPDATE service_corridors SET rollout_state = :st WHERE id = :c"), {"st": state, "c": corridor})
        route = s.execute(
            text(
                "INSERT INTO route_versions (public_id, corridor_id, created_by_user_id, source, provider, provider_version, "
                "request_hash, geometry, distance_m, duration_s, is_estimate) VALUES (gen_random_uuid(), :c, :a, 'fixture', "
                "'fake', 'v1', :h, ST_GeomFromText('LINESTRING(69.24 41.30, 67.90 40.10, 66.60 39.20, 65.80 38.86)', 4326), "
                "520000, 25200, true) RETURNING id, public_id"
            ),
            {"c": corridor, "a": admin, "h": uuid.uuid4().hex * 2},
        ).one()
        for seq, name in enumerate(STOP_NAMES):
            s.execute(
                text(
                    "INSERT INTO route_version_stops (route_version_id, seq, stop_id, cumulative_distance_m, "
                    "cumulative_duration_s, line_fraction) VALUES (:r, :seq, :stop, :dist, :dur, :frac)"
                ),
                {"r": route.id, "seq": seq, "stop": stop_ids[name], "dist": seq * 170000, "dur": seq * 8400, "frac": seq / 3},
            )
        s.execute(text("UPDATE route_versions SET status = 'confirmed', confirmed_at = now() WHERE id = :r"), {"r": route.id})
        policy = s.execute(
            text(
                "INSERT INTO commission_policies (public_id, kind, scope_corridor_id, fee_bps, effective_from, reason, created_by) "
                "VALUES (gen_random_uuid(), 'standard', :c, 1500, now(), 'A1 test policy', :a) RETURNING id, public_id"
            ),
            {"c": corridor, "a": admin},
        ).one()
        s.commit()
    base = (utc_now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    return World(
        db=db,
        admin_id=admin,
        client_id=client,
        client2_id=client2,
        driver_id=driver,
        driver2_id=driver2,
        corridor_id=corridor,
        stop_ids=stop_ids,
        stop_public_ids=stop_public_ids,
        route_id=route.id,
        route_public_id=format_public_id(PublicIdPrefix.ROUTE_VERSION, route.public_id),
        policy_id=policy.id,
        flags=FakeFlags(),
        fees=FakeFees(policy_id=policy.id, policy_public_id=format_public_id(PublicIdPrefix.COMMISSION_POLICY, policy.public_id)),
        base_time=base,
    )


@pytest.fixture
def world(pg_db: PgDatabase) -> Iterator[World]:
    built = build_world(pg_db)
    geo = SqlGeoAdapter()
    trips_ports.set_geo_port(geo)
    marketplace_ports.configure_ports(MarketplacePorts(geo=geo, flags=built.flags, fees=built.fees))
    try:
        yield built
    finally:
        trips_ports.set_geo_port(None)
        marketplace_ports.configure_ports(None)


COUNTER_TRIGGER = "trg_trip_segment_resources_counters_match_allocations"


@pytest.fixture
def unchecked_segment_counters(world: World) -> World:
    """TEST-ONLY: disable the 0054 deferred counter trigger in this test's own database.

    Pure capacity-arithmetic tests call ``trips_service.reserve`` / ``release`` and commit without booking
    allocations (A4). In production every counter change is tied to an allocation change and the trigger
    stays on; ``tests/pg/trips/test_trips_wave21_pg.py`` proves it rejects a bare counter change.
    """
    with world.db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE trip_segment_resources DISABLE TRIGGER {COUNTER_TRIGGER}"))
    return world


# --- builders ------------------------------------------------------------------------------------------


def make_vehicle(
    world: World,
    driver_id: int,
    plate: str,
    *,
    seats: int = 4,
    baggage_ml: int | None = 400_000,
    cargo_g: int | None = 100_000,
    cargo_ml: int | None = 500_000,
    approve: bool = True,
) -> str:
    with world.db.session() as s:
        vehicle = trips_service.create_vehicle(
            s,
            driver_user_id=driver_id,
            data=VehicleCreate(
                plate_number=plate,
                make_model="Chevrolet Cobalt",
                color="oq",
                seat_capacity=seats,
                baggage_capacity_ml=baggage_ml,
                cargo_max_weight_g=cargo_g,
                cargo_max_volume_ml=cargo_ml,
            ),
        )
        public_id = trips_service.vehicle_public_id(vehicle)
        if approve:
            trips_service.verify_vehicle(
                s, vehicle_public_id=public_id, actor_user_id=world.admin_id, expected_version=1, decision="approve", reason=None
            )
        s.commit()
        return public_id


def trip_create(
    world: World,
    vehicle_public_id: str,
    *,
    start: datetime,
    seats: int = 4,
    stops: Sequence[str] = STOP_NAMES,
    baggage_ml: int = 200_000,
    cargo_g: int = 50_000,
    cargo_ml: int = 300_000,
) -> TripCreate:
    return TripCreate.model_validate(
        {
            "vehicle_id": vehicle_public_id,
            "route_version_id": world.route_public_id,
            "stops": [
                {"stop_id": world.stop_public_ids[name], "seq": index + 1, "planned_arrival_at": (start + timedelta(hours=index)).isoformat()}
                for index, name in enumerate(stops)
            ],
            "planned_start_at": start.isoformat(),
            "planned_end_at": (start + timedelta(hours=len(stops))).isoformat(),
            "seat_capacity": seats,
            "baggage_capacity_ml": baggage_ml,
            "cargo_capacity_weight_g": cargo_g,
            "cargo_capacity_volume_ml": cargo_ml,
            "max_detour_minutes": 15,
            "max_detour_m": 5000,
        }
    )


def make_trip(world: World, driver_id: int, vehicle_public_id: str, *, start: datetime, **kwargs: object) -> tuple[int, str]:
    with world.db.session() as s:
        trip = trips_service.create_trip(s, driver_user_id=driver_id, data=trip_create(world, vehicle_public_id, start=start, **kwargs))
        s.commit()
        return trip.id, trips_service.trip_public_id(trip)


def passenger_request(
    world: World, *, start: datetime, seats: int = 2, unit_price_minor: int = 20_000_000, origin: str = "A", destination: str = "D"
) -> ListingCreate:
    return ListingCreate.model_validate(
        {
            "kind": "request",
            "service_type": "passenger",
            "origin_stop_id": world.stop_public_ids[origin],
            "destination_stop_id": world.stop_public_ids[destination],
            "departure_window_start": start.isoformat(),
            "departure_window_end": (start + timedelta(hours=1)).isoformat(),
            "price_basis": "per_seat",
            "unit_price_minor": unit_price_minor,
            "passenger": {"seat_count": seats, "adults": seats, "baggage": {"pieces": 1, "total_weight_g": 15_000, "total_volume_ml": 40_000}},
        }
    )


def passenger_offer(world: World, trip_public_id: str, *, start: datetime, unit_price_minor: int = 20_000_000) -> ListingCreate:
    return ListingCreate.model_validate(
        {
            "kind": "trip_offer",
            "service_type": "passenger",
            "origin_stop_id": world.stop_public_ids["A"],
            "destination_stop_id": world.stop_public_ids["D"],
            "departure_window_start": start.isoformat(),
            "departure_window_end": (start + timedelta(hours=1)).isoformat(),
            "price_basis": "per_seat",
            "unit_price_minor": unit_price_minor,
            "trip_id": trip_public_id,
        }
    )


# --- concurrency helpers -------------------------------------------------------------------------------


def wait_for_lock_waiters(world: World, expected: int, timeout_s: float = 15.0) -> None:
    """Block until ``expected`` sessions of this test database wait on a heavyweight lock."""
    deadline = time.monotonic() + timeout_s
    with world.db.engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
            ).scalar_one()
            conn.rollback()  # fresh stats snapshot on the next poll
            if waiting >= expected:
                return
            time.sleep(0.05)
    raise AssertionError(f"expected {expected} sessions waiting on a lock")


def run_in_thread(fn) -> tuple[threading.Thread, dict]:  # noqa: ANN001
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - asserted by the caller
            outcome["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    return thread, outcome
