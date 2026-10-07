"""Shared PostgreSQL fixtures for A1 tests (identity, trips, marketplace).

Seeds real rows into A2's geo tables and A3's ``commission_policies`` so every DB
foreign key is exercised, then registers ports:

* ``SqlGeoAdapter`` - TEST-ONLY geo port over the real geo tables (corridors, confirmed roads).
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
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id
from app.contracts.timeutil import utc_now
from app.models import DriverProfile, User
from app.modules.marketplace import ports as marketplace_ports
from app.modules.marketplace.ports import CorridorRef, FeeQuote, MarketplacePorts, PolicyRef
from app.modules.marketplace.schemas import ListingCreate
from app.modules.trips import ports as trips_ports
from app.modules.trips import service as trips_service
from app.modules.trips.ports import RouteVersionRef
from app.modules.trips.schemas import TripCreate, VehicleCreate
from tests.pg.conftest import PgDatabase

#: ADR-0028 / Q160: the fixture road runs through four places A -> B -> C -> D. They are places (map points), not stops:
#: each sits in its own district whose centre is the place itself, so a district end and a marked place agree.
PLACE_NAMES = ("A", "B", "C", "D")
PLACE_COORDS = {"A": (69.24, 41.30), "B": (67.90, 40.10), "C": (66.60, 39.20), "D": (65.80, 38.86)}  # (lng, lat)
PLACE_DISTRICTS = {"A": ("UZ-TK", "Yunusobod"), "B": ("UZ-QA", "Jizzax yo'li"), "C": ("UZ-QA", "Chiroqchi"), "D": ("UZ-QA", "Qarshi")}
ROAD_WKT = "LINESTRING(69.24 41.30, 67.90 40.10, 66.60 39.20, 65.80 38.86)"
ROAD_DISTANCE_M, ROAD_DURATION_S = 520_000, 25_200


# --- ports -------------------------------------------------------------------------------------------


class SqlGeoAdapter:
    """TEST-ONLY geo port over the real geo tables (corridors and confirmed roads)."""

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
            text("SELECT id, public_id, status, distance_m, duration_s FROM route_versions WHERE id = ANY(:ids)"), {"ids": list(ids)}
        ).mappings().all()
        return {
            route["id"]: RouteVersionRef(
                id=route["id"],
                public_id=format_public_id(PublicIdPrefix.ROUTE_VERSION, route["public_id"]),
                status=route["status"],
                distance_m=route["distance_m"],
                duration_s=route["duration_s"],
            )
            for route in routes
        }


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
    region_ids: dict[str, int]  # code -> pk
    region_public_ids: dict[str, str]  # code -> api id
    district_ids: dict[str, int]  # place -> pk
    district_public_ids: dict[str, str]  # place -> api id
    place_positions: dict[str, int]  # place -> metres along the road
    route_id: int
    route_public_id: str
    policy_id: int
    flags: FakeFlags
    fees: FakeFees
    base_time: datetime

    def point(self, place: str, *, address: str | None = None) -> dict:
        """A marked place as ``PointEndInput`` JSON (Q88)."""
        lng, lat = PLACE_COORDS[place]
        body = {"lat": lat, "lng": lng, "district_id": self.district_public_ids[place]}
        if address is not None:
            body["address"] = address
        return body

    def end(self, place: str) -> dict:
        """A district end (region + district) as ``DirectionEndInput`` JSON (Q150)."""
        code = PLACE_DISTRICTS[place][0]
        return {"region_id": self.region_public_ids[code], "district_id": self.district_public_ids[place]}


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
        district_ids, district_public_ids = {}, {}
        for place, (code, name) in PLACE_DISTRICTS.items():
            lng, lat = PLACE_COORDS[place]
            row = s.execute(
                text(
                    "INSERT INTO geo_districts (public_id, region_id, name_uz, center_lat, center_lng) "
                    "SELECT gen_random_uuid(), id, :n, :lat, :lng FROM regions WHERE code = :c RETURNING id, public_id"
                ),
                {"c": code, "n": name, "lat": lat, "lng": lng},
            ).one()
            district_ids[place] = row.id
            district_public_ids[place] = format_public_id(PublicIdPrefix.DISTRICT, row.public_id)
        route = s.execute(
            text(
                "INSERT INTO route_versions (public_id, corridor_id, created_by_user_id, source, provider, provider_version, "
                "request_hash, geometry, distance_m, duration_s, is_estimate) VALUES (gen_random_uuid(), :c, :a, 'fixture', "
                "'fake', 'v1', :h, ST_GeomFromText(:wkt, 4326), :dist, :dur, true) RETURNING id, public_id"
            ),
            {"c": corridor, "a": admin, "h": uuid.uuid4().hex * 2, "wkt": ROAD_WKT, "dist": ROAD_DISTANCE_M, "dur": ROAD_DURATION_S},
        ).one()
        s.execute(text("UPDATE route_versions SET status = 'confirmed', confirmed_at = now() WHERE id = :r"), {"r": route.id})
        for state in ("internal", "pilot"):  # ADR-0028: a public corridor needs a confirmed road
            s.execute(text("UPDATE service_corridors SET rollout_state = :st WHERE id = :c"), {"st": state, "c": corridor})
        # region centres (where a region-only end meets the road): Toshkent at A, Qashqadaryo at D
        for code, place in (("UZ-TK", "A"), ("UZ-QA", "D")):
            s.execute(text("UPDATE regions SET center_lat = :lat, center_lng = :lng WHERE code = :c"),
                      {"c": code, "lng": PLACE_COORDS[place][0], "lat": PLACE_COORDS[place][1]})
        place_positions = {
            place: s.execute(
                text(
                    "SELECT round(ST_LineLocatePoint(rv.geometry, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)) * rv.distance_m)::int "
                    "FROM route_versions rv WHERE rv.id = :r"
                ),
                {"r": route.id, "lng": PLACE_COORDS[place][0], "lat": PLACE_COORDS[place][1]},
            ).scalar_one()
            for place in PLACE_NAMES
        }
        region_rows = s.execute(text("SELECT id, code, public_id FROM regions")).all()
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
        region_ids={row.code: row.id for row in region_rows},
        region_public_ids={row.code: format_public_id(PublicIdPrefix.REGION, row.public_id) for row in region_rows},
        district_ids=district_ids,
        district_public_ids=district_public_ids,
        place_positions=place_positions,
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
    places: Sequence[str] = PLACE_NAMES,
    baggage_ml: int = 200_000,
    cargo_g: int = 50_000,
    cargo_ml: int = 300_000,
) -> TripCreate:
    """A trip on the stretch of the road from ``places[0]`` to ``places[-1]`` (ADR-0028), one hour per place hop."""
    return TripCreate.model_validate(
        {
            "vehicle_id": vehicle_public_id,
            "route_version_id": world.route_public_id,
            "route_start_m": world.place_positions[places[0]],
            "route_end_m": world.place_positions[places[-1]],
            "planned_start_at": start.isoformat(),
            "planned_end_at": (start + timedelta(hours=len(places) - 1)).isoformat(),
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
            "origin_point": world.point(origin),
            "destination_point": world.point(destination),
            "departure_window_start": start.isoformat(),
            "departure_window_end": (start + timedelta(hours=1)).isoformat(),
            "price_basis": "per_seat",
            "unit_price_minor": unit_price_minor,
            "passenger": {"seat_count": seats, "adults": seats, "baggage": {"pieces": 1, "total_weight_g": 15_000, "total_volume_ml": 40_000}},
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
