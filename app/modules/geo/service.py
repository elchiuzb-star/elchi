"""Public domain API of the geo module (owner A2). Other modules import only this file.

Transaction rules (ADR-0001, spec §15):
* Functions take the caller's ``Session`` and never commit.
* Router/provider calls happen only in ``fetch_route_outside_transaction`` and
  ``measure_detours_outside_transaction``, which refuse to run inside a transaction.
  Typical flow: read (``prepare_route_preview``) -> end the transaction -> fetch -> write.

Production detection everywhere: ``platform.service.is_production(session)`` (settings OR DB
marker, fail closed). There is no caller override. In production no routing provider is enabled
(Q24/Q46), so detour matches never occur there; only verified-stop matches work.

Published for A1/A4/A5:
* matching: ``evaluate_route_match``, ``measure_detours_outside_transaction``,
  ``validate_detour_quote(s)``, ``apply_insertions``, ``verify_existing_windows``,
  ``cumulative_detour_allowed``, ``find_candidates``, ``nearby_stop_ids``,
  ``planned_occurrences_from_route_version``;
* lookups: ``get_route_version`` / ``get_route_version_by_api_id``, ``get_stop`` / ``get_stops`` /
  ``get_stops_by_api_ids`` / ``get_stop_by_api_id`` / ``get_stop_points``, ``get_corridor`` /
  ``get_corridors`` / ``get_corridor_by_api_id``;
* flags: ``is_flag_enabled``, ``resolve_flags``, ``snapshot_flags``, ``production_flag_violations``;
* price bands (Q42): ``resolve_price_band``, ``select_price_band``, ``price_within_band``,
  ``assert_price_within_band`` (raises ``PRICE_OUT_OF_BAND``);
* hook for A4: ``set_active_booking_counter`` (corridor ``internal -> draft`` guard).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import (
    FLAG_CHANGE_SOURCE_ADMIN_API,
    FLAG_CHANGE_SOURCE_SETTING,
    FLAGS_LOCKED_IN_PRODUCTION,
    FLAGS_REQUIRING_APPROVAL_REFERENCE,
    Capability,
    CorridorRolloutState,
    FeatureFlagKey,
    FlagScopeType,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.money import validate_minor_amount
from app.contracts.state_machines import CORRIDOR_ROLLOUT
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.geo import flags as flag_rules
from app.modules.geo.flags import FlagResolution, FlagRow, FlagScopeContext
from app.modules.geo.pricing import (
    PRICE_BAND_BASIS,
    PriceBand,
    assert_price_within_band,
    evaluate_price_band,
    price_within_band,
    select_price_band,
)
from app.modules.geo.geometry import linestring_ewkt, point_ewkt
from app.modules.geo.matching import (
    apply_insertions,
    cumulative_detour_allowed,
    evaluate_route_match,
    measure_detours,
    validate_detour_quote,
    validate_detour_quotes,
    verify_existing_windows,
)
from app.modules.geo.models import (
    CorridorConfigVersion,
    CorridorPriceBand,
    CorridorPriceBandChange,
    CorridorStop,
    FeatureFlagChange,
    FeatureFlagValue,
    GeoDistrict,
    Region,
    RouteVersion,
    RouteVersionStop,
    ServiceCorridor,
)
from app.modules.geo.routing.base import (
    PROVIDER_ATTRIBUTIONS,
    RouteResult,
    RoutingProvider,
    RoutingUnavailable,
    assert_outside_transaction,
)
from app.modules.geo.types import (
    BookingWindow,
    DetourMeasurements,
    DetourQuote,
    LatLng,
    MatchRequest,
    OccurrenceTiming,
    RouteMatchResult,
    TimelineChange,
    TripRouteContext,
)
from app.modules.platform import service as platform_service

logger = logging.getLogger(__name__)

__all__ = [
    "V2_SERVICE_FLAGS",
    "mark_flag_change_source",
    "readiness_notices",
    "find_q47_violations",
    "price_band_warnings",
    "production_invariant_notices",
    "q48_gate_passed",
    "PRICE_BAND_BASIS",
    "PriceBand",
    "assert_price_within_band",
    "price_within_band",
    "resolve_price_band",
    "select_price_band",
    "BookingWindow",
    "CorridorInfo",
    "DetourQuote",
    "MatchRequest",
    "RouteCandidate",
    "RouteMatchResult",
    "RouteVersionInfo",
    "StopInfo",
    "TimelineChange",
    "TripRouteContext",
    "apply_insertions",
    "cumulative_detour_allowed",
    "evaluate_route_match",
    "find_candidates",
    "get_corridor",
    "get_corridor_by_api_id",
    "get_corridors",
    "get_route_version",
    "get_route_version_by_api_id",
    "get_stop",
    "get_stop_by_api_id",
    "get_stop_points",
    "get_stops",
    "get_stops_by_api_ids",
    "is_flag_enabled",
    "measure_detours_outside_transaction",
    "nearby_stop_ids",
    "planned_occurrences_from_route_version",
    "production_flag_violations",
    "resolve_flags",
    "set_active_booking_counter",
    "snapshot_flags",
    "validate_detour_quote",
    "validate_detour_quotes",
    "verify_existing_windows",
    "project_point_on_route",
    "RouteProjection",
    "MAX_POINT_ROUTE_OFFSET_M",
    "corridor_point_offset_m",
    "districts_by_ids",
    "evaluate_price_band",
]

ROUTE_DRAFT_TTL = timedelta(hours=24)
OPERABLE_ROLLOUT_STATES = frozenset({CorridorRolloutState.INTERNAL, CorridorRolloutState.PILOT, CorridorRolloutState.ACTIVE})
PUBLIC_ROLLOUT_STATES = frozenset({CorridorRolloutState.PILOT, CorridorRolloutState.ACTIVE})
# Q47: pilot/active corridors keep at least two active stops, each with meeting evidence (Q27),
# enforced continuously in the service and by a deferred DB trigger (0046).
PILOT_MIN_ACTIVE_STOPS = 2

# Read-only view of the contract machine (enforcement uses CORRIDOR_ROLLOUT.assert_transition).
ROLLOUT_TRANSITIONS: dict[CorridorRolloutState, frozenset[CorridorRolloutState]] = {
    state: frozenset(CorridorRolloutState(t.target) for t in CORRIDOR_ROLLOUT.transitions if t.source == state.value)
    for state in CorridorRolloutState
}


def is_production(db: Session) -> bool:
    """Single production check for geo: settings OR DB marker (``platform.service``)."""
    return platform_service.is_production(db)


# --- identifiers -----------------------------------------------------------------------


def corridor_api_id(value: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.CORRIDOR, value)


def stop_api_id(value: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.STOP, value)


def route_version_api_id(value: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.ROUTE_VERSION, value)


def region_api_id(value: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.REGION, value)


def district_api_id(value: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.DISTRICT, value)


def flag_api_id(value: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.FEATURE_FLAG, value)


# --- value objects -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegionInfo:
    id: int
    public_id: uuid.UUID
    code: str
    name_uz: str
    name_ru: str | None
    #: Wave 10: the direction picker asks for a district here. False for Tashkent city (the city is the unit).
    requires_district: bool = True
    #: Where a map opens for this region when no district centre applies (0080). Advisory only, exactly like
    #: `DistrictInfo.center_lat` - never an input to matching, capacity or price.
    center_lat: float | None = None
    center_lng: float | None = None

    @property
    def api_id(self) -> str:
        return region_api_id(self.public_id)


@dataclass(frozen=True, slots=True)
class CorridorConfigInfo:
    revision: int
    search_radius_m: int
    default_max_detour_minutes: int
    default_max_detour_m: int


@dataclass(frozen=True, slots=True)
class CorridorInfo:
    id: int
    public_id: uuid.UUID
    name: str
    origin_region: RegionInfo
    destination_region: RegionInfo
    rollout_state: CorridorRolloutState
    version: int
    config: CorridorConfigInfo
    updated_at: datetime

    @property
    def api_id(self) -> str:
        return corridor_api_id(self.public_id)

    @property
    def is_operable(self) -> bool:
        """New routes/listings may use it (internal, pilot, active)."""
        return self.rollout_state in OPERABLE_ROLLOUT_STATES


@dataclass(frozen=True, slots=True)
class StopInfo:
    id: int
    public_id: uuid.UUID
    corridor_id: int
    corridor_public_id: uuid.UUID
    district_id: int
    district_public_id: uuid.UUID
    district_name_uz: str
    name_uz: str
    name_ru: str | None
    point: LatLng
    meeting_note: str | None
    meeting_photo_file_id: str | None
    sequence_hint: int
    is_active: bool
    version: int

    @property
    def api_id(self) -> str:
        return stop_api_id(self.public_id)


@dataclass(frozen=True, slots=True)
class RouteVersionStopInfo:
    seq: int
    stop_id: int
    stop_public_id: uuid.UUID
    cumulative_distance_m: int
    cumulative_duration_s: int
    line_fraction: Decimal


@dataclass(frozen=True, slots=True)
class RouteVersionInfo:
    id: int
    public_id: uuid.UUID
    corridor_id: int
    created_by_user_id: int
    status: str
    source: str
    provider: str
    provider_version: str
    distance_m: int
    duration_s: int
    is_estimate: bool
    geometry: tuple[LatLng, ...]
    stops: tuple[RouteVersionStopInfo, ...]
    confirmed_at: datetime | None
    created_at: datetime

    @property
    def api_id(self) -> str:
        return route_version_api_id(self.public_id)

    @property
    def attribution(self) -> str:
        return PROVIDER_ATTRIBUTIONS.get(self.provider, "")


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """Spatial pre-filter hit (spec §6.3 step 2). Final decision: ``evaluate_route_match``."""

    route_version_id: int
    corridor_id: int
    pickup_distance_m: int
    dropoff_distance_m: int
    pickup_line_fraction: Decimal
    dropoff_line_fraction: Decimal
    pickup_stop_seqs: tuple[int, ...]
    dropoff_stop_seqs: tuple[int, ...]
    confirmed_at: datetime | None = None

    @property
    def forward_by_line_fraction(self) -> bool:
        """Hint only: loops/repeated stops are decided by occurrence order."""
        return self.pickup_line_fraction < self.dropoff_line_fraction


@dataclass(frozen=True, slots=True)
class RoutePreviewPlan:
    corridor: CorridorInfo
    stops: tuple[StopInfo, ...]
    waypoints: tuple[LatLng, ...]
    provider: str
    provider_version: str
    request_hash: str
    cached: RouteResult | None


@dataclass(frozen=True, slots=True)
class FlagValueInfo:
    id: int
    public_id: uuid.UUID
    flag_key: FeatureFlagKey
    scope_type: FlagScopeType
    scope_ref: str
    enabled: bool
    approval_reference: str | None
    reason: str
    version: int
    updated_by: int
    updated_at: datetime

    @property
    def api_id(self) -> str:
        return flag_api_id(self.public_id)


@dataclass(frozen=True, slots=True)
class FlagChangeInfo:
    id: int
    flag_key: FeatureFlagKey
    scope_type: FlagScopeType
    scope_ref: str
    value_version: int
    old_enabled: bool | None
    new_enabled: bool
    actor_user_id: int
    reason: str
    approval_reference: str | None
    changed_at: datetime


# --- catalogue reads ------------------------------------------------------------------------


def _region_info(row: Region) -> RegionInfo:
    return RegionInfo(
        row.id,
        row.public_id,
        row.code,
        row.name_uz,
        row.name_ru,
        bool(row.requires_district),
        float(row.center_lat) if row.center_lat is not None else None,
        float(row.center_lng) if row.center_lng is not None else None,
    )


def list_regions(db: Session, *, active_only: bool = True) -> list[RegionInfo]:
    query = select(Region).order_by(Region.name_uz, Region.id)
    if active_only:
        query = query.where(Region.is_active.is_(True))
    return [_region_info(row) for row in db.scalars(query)]


def get_region_by_code(db: Session, code: str) -> RegionInfo:
    row = db.scalar(select(Region).where(Region.code == code))
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return _region_info(row)


def get_region_by_api_id(db: Session, api_id: str) -> RegionInfo:
    public_id = parse_public_id(api_id, PublicIdPrefix.REGION)
    row = db.scalar(select(Region).where(Region.public_id == public_id))
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return _region_info(row)


def _latest_config_subquery():  # noqa: ANN202
    return (
        select(CorridorConfigVersion.corridor_id, func.max(CorridorConfigVersion.revision).label("revision"))
        .group_by(CorridorConfigVersion.corridor_id)
        .subquery()
    )


def _corridor_infos(db: Session, where: Any = None, *, limit: int | None = None) -> list[CorridorInfo]:
    origin = Region.__table__.alias("origin")
    destination = Region.__table__.alias("destination")
    latest = _latest_config_subquery()
    region_cols = []
    for prefix, table in (("o", origin), ("d", destination)):
        region_cols += [
            table.c[name].label(f"{prefix}_{name}")
            for name in ("id", "public_id", "code", "name_uz", "name_ru", "requires_district")
        ]
    query = (
        select(ServiceCorridor, CorridorConfigVersion, *region_cols)
        .join(latest, latest.c.corridor_id == ServiceCorridor.id)
        .join(
            CorridorConfigVersion,
            (CorridorConfigVersion.corridor_id == ServiceCorridor.id) & (CorridorConfigVersion.revision == latest.c.revision),
        )
        .join(origin, origin.c.id == ServiceCorridor.origin_region_id)
        .join(destination, destination.c.id == ServiceCorridor.destination_region_id)
        .order_by(ServiceCorridor.id)
    )
    if where is not None:
        query = query.where(where)
    if limit is not None:
        query = query.limit(limit)
    infos: list[CorridorInfo] = []
    for row in db.execute(query).all():
        corridor: ServiceCorridor = row[0]
        config: CorridorConfigVersion = row[1]
        infos.append(
            CorridorInfo(
                id=corridor.id,
                public_id=corridor.public_id,
                name=corridor.name,
                origin_region=RegionInfo(
                    row.o_id, row.o_public_id, row.o_code, row.o_name_uz, row.o_name_ru, bool(row.o_requires_district)
                ),
                destination_region=RegionInfo(
                    row.d_id, row.d_public_id, row.d_code, row.d_name_uz, row.d_name_ru, bool(row.d_requires_district)
                ),
                rollout_state=CorridorRolloutState(corridor.rollout_state),
                version=corridor.version,
                config=CorridorConfigInfo(config.revision, config.search_radius_m, config.default_max_detour_minutes, config.default_max_detour_m),
                updated_at=corridor.updated_at,
            )
        )
    return infos


def get_corridor(db: Session, corridor_id: int) -> CorridorInfo:
    found = _corridor_infos(db, ServiceCorridor.id == corridor_id)
    if not found:
        raise DomainError(ErrorCode.NOT_FOUND)
    return found[0]


def get_corridors(db: Session, corridor_ids: Iterable[int]) -> dict[int, CorridorInfo]:
    ids = sorted(set(corridor_ids))
    if not ids:
        return {}
    return {info.id: info for info in _corridor_infos(db, ServiceCorridor.id.in_(ids))}


def get_corridor_by_api_id(db: Session, api_id: str) -> CorridorInfo:
    public_id = parse_public_id(api_id, PublicIdPrefix.CORRIDOR)
    found = _corridor_infos(db, ServiceCorridor.public_id == public_id)
    if not found:
        raise DomainError(ErrorCode.NOT_FOUND)
    return found[0]


def _stop_query():  # noqa: ANN202
    return (
        select(
            CorridorStop,
            func.ST_Y(CorridorStop.point).label("lat"),
            func.ST_X(CorridorStop.point).label("lng"),
            GeoDistrict.public_id.label("district_public_id"),
            GeoDistrict.name_uz.label("district_name_uz"),
            ServiceCorridor.public_id.label("corridor_public_id"),
        )
        .join(GeoDistrict, GeoDistrict.id == CorridorStop.geo_district_id)
        .join(ServiceCorridor, ServiceCorridor.id == CorridorStop.corridor_id)
    )


def _stop_info(row: Any) -> StopInfo:
    stop: CorridorStop = row[0]
    return StopInfo(
        id=stop.id,
        public_id=stop.public_id,
        corridor_id=stop.corridor_id,
        corridor_public_id=row.corridor_public_id,
        district_id=stop.geo_district_id,
        district_public_id=row.district_public_id,
        district_name_uz=row.district_name_uz,
        name_uz=stop.name_uz,
        name_ru=stop.name_ru,
        point=LatLng(float(row.lat), float(row.lng)),
        meeting_note=stop.meeting_note,
        meeting_photo_file_id=stop.meeting_photo_file_id,
        sequence_hint=stop.sequence_hint,
        is_active=stop.is_active,
        version=stop.version,
    )


def get_stops(db: Session, stop_ids: Iterable[int]) -> dict[int, StopInfo]:
    ids = sorted(set(stop_ids))
    if not ids:
        return {}
    return {info.id: info for info in (_stop_info(row) for row in db.execute(_stop_query().where(CorridorStop.id.in_(ids))).all())}


def get_stop(db: Session, stop_id: int) -> StopInfo:
    found = get_stops(db, [stop_id])
    if stop_id not in found:
        raise DomainError(ErrorCode.NOT_FOUND)
    return found[stop_id]


def get_stops_by_api_ids(db: Session, api_ids: Iterable[str]) -> dict[str, StopInfo]:
    """Batch lookup; malformed or unknown ids are simply absent from the result."""
    public_ids: list[uuid.UUID] = []
    for api_id in dict.fromkeys(api_ids):
        try:
            public_ids.append(parse_public_id(api_id, PublicIdPrefix.STOP))
        except DomainError:
            continue
    if not public_ids:
        return {}
    rows = db.execute(_stop_query().where(CorridorStop.public_id.in_(public_ids))).all()
    return {info.api_id: info for info in (_stop_info(row) for row in rows)}


def get_stop_by_api_id(db: Session, api_id: str) -> StopInfo:
    public_id = parse_public_id(api_id, PublicIdPrefix.STOP)
    row = db.execute(_stop_query().where(CorridorStop.public_id == public_id)).first()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return _stop_info(row)


def get_stop_points(db: Session, stop_ids: Iterable[int]) -> dict[int, LatLng]:
    return {stop_id: info.point for stop_id, info in get_stops(db, stop_ids).items()}


def list_corridor_stops(db: Session, corridor: CorridorInfo, *, active_only: bool = True) -> list[StopInfo]:
    query = _stop_query().where(CorridorStop.corridor_id == corridor.id)
    if active_only:
        query = query.where(CorridorStop.is_active.is_(True))
    query = query.order_by(CorridorStop.sequence_hint, CorridorStop.id)
    return [_stop_info(row) for row in db.execute(query).all()]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_stops(db: Session, q: str, *, region: RegionInfo | None = None, limit: int = 20) -> list[StopInfo]:
    """Active stops of publicly visible corridors whose uz/ru name contains ``q``.

    No rate limit yet (BR #9): owned by A13 before launch.
    """
    term = q.strip()
    if len(term) < 2:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "q", "min_length": 2})
    pattern = f"%{_escape_like(term)}%"
    query = (
        _stop_query()
        .where(CorridorStop.is_active.is_(True))
        .where(ServiceCorridor.rollout_state.in_([s.value for s in PUBLIC_ROLLOUT_STATES]))
        .where(CorridorStop.name_uz.ilike(pattern, escape="\\") | CorridorStop.name_ru.ilike(pattern, escape="\\"))
        .order_by(CorridorStop.name_uz, CorridorStop.id)
        .limit(max(1, min(limit, 50)))
    )
    if region is not None:
        query = query.where(GeoDistrict.region_id == region.id)
    return [_stop_info(row) for row in db.execute(query).all()]


def count_active_stops(db: Session, corridor_ids: Sequence[int]) -> dict[int, int]:
    if not corridor_ids:
        return {}
    rows = db.execute(
        select(CorridorStop.corridor_id, func.count())
        .where(CorridorStop.corridor_id.in_(list(corridor_ids)), CorridorStop.is_active.is_(True))
        .group_by(CorridorStop.corridor_id)
    ).all()
    return {corridor_id: count for corridor_id, count in rows}


def list_public_corridors(db: Session, *, service_type: ServiceType | None = None) -> list[tuple[CorridorInfo, list[ServiceType], int]]:
    """Pilot/active corridors with the services whose flag is on for that corridor (G2)."""
    corridors = _corridor_infos(db, ServiceCorridor.rollout_state.in_([s.value for s in PUBLIC_ROLLOUT_STATES]))
    rows = _load_flag_rows(db)
    production = is_production(db)
    counts = count_active_stops(db, [c.id for c in corridors])
    result: list[tuple[CorridorInfo, list[ServiceType], int]] = []
    for corridor in corridors:
        context = _corridor_context(corridor)
        services = [
            service
            for service, key in ((ServiceType.PASSENGER, FeatureFlagKey.PASSENGER_ENABLED), (ServiceType.PARCEL, FeatureFlagKey.PARCEL_ENABLED))
            if flag_rules.resolve_flag(key, rows, context, production=production).enabled
        ]
        if service_type is not None and service_type not in services:
            continue
        result.append((corridor, services, counts.get(corridor.id, 0)))
    return result


def list_admin_corridors(db: Session, *, after_id: int | None, limit: int) -> tuple[list[CorridorInfo], int | None]:
    where = ServiceCorridor.id > after_id if after_id is not None else None
    items = _corridor_infos(db, where, limit=limit + 1)
    next_after = items[limit - 1].id if len(items) > limit else None
    return items[:limit], next_after


def nearby_stop_ids(db: Session, stop_id: int, *, radius_m: int, limit: int = 5) -> list[int]:
    """Other active stops of the same corridor within ``radius_m`` metres (geography), nearest first."""
    rows = db.execute(
        text(
            "SELECT o.id FROM corridor_stops s JOIN corridor_stops o "
            "ON o.corridor_id = s.corridor_id AND o.id <> s.id AND o.is_active "
            "WHERE s.id = :stop_id AND ST_DWithin(o.point::geography, s.point::geography, :radius) "
            "ORDER BY ST_Distance(o.point::geography, s.point::geography), o.id LIMIT :limit"
        ),
        {"stop_id": stop_id, "radius": radius_m, "limit": limit},
    ).all()
    return [row[0] for row in rows]


# --- catalogue writes (operator/admin) ----------------------------------------------------------


def _audit(db: Session, *, actor_user_id: int, entity_type: str, entity_id: int, action: str, old: dict | None, new: dict | None, reason: str | None) -> None:
    from app.models import User
    from app.services.audit_service import write_audit_log

    write_audit_log(db, db.get(User, actor_user_id), entity_type, entity_id, action, old_value=old, new_value=new, reason=reason)


def _duplicate(field: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_ERROR, details={"field": field, "reason": "duplicate"})


def _resolve_region_ref(db: Session, api_id: str, field: str) -> RegionInfo:
    try:
        region = get_region_by_api_id(db, api_id)
    except DomainError:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": field, "reason": "unknown_region"}) from None
    return region


def _resolve_district_ref(db: Session, api_id: str) -> GeoDistrict:
    try:
        public_id = parse_public_id(api_id, PublicIdPrefix.DISTRICT)
    except DomainError:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "district_id", "reason": "unknown_district"}) from None
    row = db.scalar(select(GeoDistrict).where(GeoDistrict.public_id == public_id, GeoDistrict.is_active.is_(True)))
    if row is None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "district_id", "reason": "unknown_district"})
    return row


def create_corridor(
    db: Session,
    *,
    actor_user_id: int,
    name: str,
    origin_region_api_id: str,
    destination_region_api_id: str,
    search_radius_m: int,
    default_max_detour_minutes: int,
    default_max_detour_m: int,
) -> CorridorInfo:
    origin = _resolve_region_ref(db, origin_region_api_id, "origin_region_id")
    destination = _resolve_region_ref(db, destination_region_api_id, "destination_region_id")
    corridor = ServiceCorridor(
        public_id=new_public_uuid(),
        name=name.strip(),
        origin_region_id=origin.id,
        destination_region_id=destination.id,
        rollout_state=CorridorRolloutState.DRAFT.value,
        version=1,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    try:
        with db.begin_nested():
            db.add(corridor)
            db.flush()
    except IntegrityError:
        raise _duplicate("name") from None
    db.add(
        CorridorConfigVersion(
            corridor_id=corridor.id,
            revision=1,
            search_radius_m=search_radius_m,
            default_max_detour_minutes=default_max_detour_minutes,
            default_max_detour_m=default_max_detour_m,
            ranking_weights={},
            price_reference={},
            created_by=actor_user_id,
        )
    )
    db.flush()
    _audit(
        db,
        actor_user_id=actor_user_id,
        entity_type="service_corridor",
        entity_id=corridor.id,
        action="corridor_created",
        old=None,
        new={"name": corridor.name, "origin": origin.code, "destination": destination.code, "search_radius_m": search_radius_m},
        reason=None,
    )
    return get_corridor(db, corridor.id)


def _lock_corridor(db: Session, api_id: str) -> ServiceCorridor:
    public_id = parse_public_id(api_id, PublicIdPrefix.CORRIDOR)
    row = db.scalar(select(ServiceCorridor).where(ServiceCorridor.public_id == public_id).with_for_update(key_share=True))
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def _lock_corridor_by_id(db: Session, corridor_id: int) -> None:
    """``FOR NO KEY UPDATE`` on the corridor row: serialises stop changes of one corridor (Q47)."""
    if db.scalar(select(ServiceCorridor.id).where(ServiceCorridor.id == corridor_id).with_for_update(key_share=True)) is None:
        raise DomainError(ErrorCode.NOT_FOUND)


# A4 registers a counter of non-terminal bookings on a corridor (STATE_MACHINES §10 internal -> draft).
ActiveBookingCounter = Callable[[Session, int], int]
_active_booking_counter: ActiveBookingCounter | None = None


def set_active_booking_counter(counter: ActiveBookingCounter | None) -> None:
    global _active_booking_counter
    _active_booking_counter = counter


def _active_bookings_on_corridor(db: Session, corridor_id: int) -> int:
    if _active_booking_counter is not None:
        return _active_booking_counter(db, corridor_id)
    if platform_service.table_exists(db, "bookings"):
        # Bookings exist but nobody wired the check: fail closed rather than guess.
        raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "booking_check_not_configured"})
    return 0


def _guard_failed(command: str, reason: str, **details: Any) -> DomainError:
    return DomainError(
        ErrorCode.INVALID_STATE_TRANSITION,
        details={"machine": CORRIDOR_ROLLOUT.name, "command": command, "reason": reason, **details},
    )


def _stops_missing_meeting_evidence(db: Session, corridor_id: int) -> list[str]:
    rows = db.scalars(
        select(CorridorStop.public_id)
        .where(
            CorridorStop.corridor_id == corridor_id,
            CorridorStop.is_active.is_(True),
            (CorridorStop.meeting_note.is_(None) | (func.btrim(CorridorStop.meeting_note) == "")),
            CorridorStop.meeting_photo_file_id.is_(None),
        )
        .order_by(CorridorStop.id)
    )
    return [stop_api_id(value) for value in rows]


def _public_corridor_violation(db: Session, corridor_id: int) -> tuple[str, dict[str, Any]] | None:
    active_stops = count_active_stops(db, [corridor_id]).get(corridor_id, 0)
    if active_stops < PILOT_MIN_ACTIVE_STOPS:
        return "needs_two_active_stops", {"active_stops": active_stops}
    missing = _stops_missing_meeting_evidence(db, corridor_id)
    if missing:
        return "stops_missing_meeting_evidence", {"stop_ids": missing}
    return None


def _assert_public_corridor_stops(db: Session, corridor_id: int) -> None:
    """Q47: after any stop change, a pilot/active corridor still has >= 2 active stops with evidence."""
    state = CorridorRolloutState(db.scalar(select(ServiceCorridor.rollout_state).where(ServiceCorridor.id == corridor_id)))
    if state not in PUBLIC_ROLLOUT_STATES:
        return
    violation = _public_corridor_violation(db, corridor_id)
    if violation is not None:
        reason, details = violation
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            details={"machine": "corridor_stops", "rollout_state": state.value, "reason": reason, **details},
        )


def _check_rollout(db: Session, corridor: CorridorInfo, target: CorridorRolloutState) -> str:
    source = corridor.rollout_state
    command = next((t.command for t in CORRIDOR_ROLLOUT.transitions if t.source == source.value and t.target == target.value), None)
    CORRIDOR_ROLLOUT.assert_transition(source.value, target.value, command=command)
    assert command is not None
    active_stops = count_active_stops(db, [corridor.id]).get(corridor.id, 0)
    if command == "start_internal" and active_stops < 1:
        raise _guard_failed(command, "needs_active_stop")
    if command == "return_to_draft":
        active = _active_bookings_on_corridor(db, corridor.id)
        if active:
            raise _guard_failed(command, "active_bookings", active_bookings=active)
    if command in ("start_pilot", "activate"):  # Q27/Q47: public corridors
        violation = _public_corridor_violation(db, corridor.id)
        if violation is not None:
            raise _guard_failed(command, violation[0], **violation[1])
    return command


def patch_corridor(db: Session, *, actor_user_id: int, corridor_api_id: str, expected_version: int, reason: str, changes: Mapping[str, Any]) -> CorridorInfo:
    """Versioned corridor edit (G9). Rollout through ``CORRIDOR_ROLLOUT`` with STATE_MACHINES §10 guards.
    Config edits create a new immutable config revision; existing trips/bookings keep their snapshots."""
    corridor = _lock_corridor(db, corridor_api_id)
    if corridor.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": corridor.version})
    before = get_corridor(db, corridor.id)
    changed: dict[str, Any] = {}

    if "rollout_state" in changes and CorridorRolloutState(changes["rollout_state"]) != before.rollout_state:
        target = CorridorRolloutState(changes["rollout_state"])
        changed["rollout_command"] = _check_rollout(db, before, target)
        corridor.rollout_state = target.value
        changed["rollout_state"] = target.value

    if "name" in changes and changes["name"].strip() != before.name:
        corridor.name = changes["name"].strip()
        changed["name"] = corridor.name

    config_fields = ("search_radius_m", "default_max_detour_minutes", "default_max_detour_m")
    new_config = {field: changes.get(field, getattr(before.config, field)) for field in config_fields}
    if any(new_config[field] != getattr(before.config, field) for field in config_fields):
        db.add(
            CorridorConfigVersion(
                corridor_id=corridor.id,
                revision=before.config.revision + 1,
                ranking_weights={},
                price_reference={},
                created_by=actor_user_id,
                **new_config,
            )
        )
        changed["config"] = new_config

    if not changed:
        return before
    corridor.version = corridor.version + 1
    corridor.updated_by = actor_user_id
    corridor.updated_at = utc_now()
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise _duplicate("name") from None
    _audit(
        db,
        actor_user_id=actor_user_id,
        entity_type="service_corridor",
        entity_id=corridor.id,
        action="corridor_updated",
        old={"rollout_state": before.rollout_state.value, "name": before.name, "config_revision": before.config.revision},
        new=changed,
        reason=reason,
    )
    return get_corridor(db, corridor.id)


# Q27 photo evidence must be an uploaded image of this dedicated type: `stop_photo`, image-only,
# uploadable only by staff holding ops.corridor_manage (v1 files route, wave 1.6 integration).
STOP_PHOTO_UPLOAD_TYPE = "stop_photo"


def _resolve_meeting_photo(value: str | None, *, actor_user_id: int, current_stored: str | None = None) -> str | None:
    """Validate a meeting photo reference with H0's file access rules (read-only use).

    F4 (accepted for the pilot): a photo is bound to its uploader. Only the staff member who uploaded it can
    attach it; another staff member can keep an already stored reference but cannot attach someone else's
    upload.
    """
    if value is None:
        return None
    from app.utils import file_access, file_validation

    def invalid(reason: str) -> DomainError:
        return DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "meeting_photo_file_id", "reason": reason})

    if STOP_PHOTO_UPLOAD_TYPE not in file_validation.ALLOWED_UPLOAD_TYPES or STOP_PHOTO_UPLOAD_TYPE not in file_validation.IMAGE_ONLY_TYPES:
        raise invalid("stop_photo_upload_type_unavailable")
    try:
        stored = file_access.resolve_attachment(
            value, user_id=actor_user_id, expected_upload_type=STOP_PHOTO_UPLOAD_TYPE, current_stored=current_stored
        )
    except file_access.FileReferenceError:
        raise invalid("invalid_file_reference") from None
    if stored is None:
        return None
    key = file_access.normalize_storage_key(stored)
    if key is None or file_access.key_extension(key) not in file_validation.ALLOWED_IMAGE_EXTENSIONS:
        raise invalid("invalid_file_reference")
    return stored


def create_stop(
    db: Session,
    *,
    actor_user_id: int,
    corridor_api_id: str,
    name_uz: str,
    name_ru: str | None,
    district_api_id: str,
    point: LatLng,
    meeting_note: str | None,
    sequence_hint: int,
    is_active: bool,
    meeting_photo_file_id: str | None = None,
) -> StopInfo:
    """G10. An active stop is recorded as verified by the staff member who activates it."""
    corridor = get_corridor_by_api_id(db, corridor_api_id)
    _lock_corridor_by_id(db, corridor.id)  # Q47: serialise stop changes per corridor
    district = _resolve_district_ref(db, district_api_id)
    photo = _resolve_meeting_photo(meeting_photo_file_id, actor_user_id=actor_user_id)
    now = utc_now()
    stop = CorridorStop(
        public_id=new_public_uuid(),
        corridor_id=corridor.id,
        geo_district_id=district.id,
        name_uz=name_uz.strip(),
        name_ru=name_ru.strip() if name_ru else None,
        point=func.ST_GeomFromEWKT(point_ewkt(point)),
        meeting_note=meeting_note,
        meeting_photo_file_id=photo,
        sequence_hint=sequence_hint,
        is_active=is_active,
        verified_by=actor_user_id if is_active else None,
        verified_at=now if is_active else None,
        version=1,
    )
    try:
        with db.begin_nested():
            db.add(stop)
            db.flush()
    except IntegrityError:
        raise _duplicate("name_uz") from None
    _assert_public_corridor_stops(db, corridor.id)
    _audit(
        db,
        actor_user_id=actor_user_id,
        entity_type="corridor_stop",
        entity_id=stop.id,
        action="corridor_stop_created",
        old=None,
        new={"corridor": corridor.api_id, "name_uz": stop.name_uz, "is_active": is_active},
        reason=None,
    )
    return get_stop(db, stop.id)


def _stop_used_by_confirmed_route(db: Session, stop_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(RouteVersionStop)
            .join(RouteVersion, RouteVersion.id == RouteVersionStop.route_version_id)
            .where(RouteVersionStop.stop_id == stop_id, RouteVersion.status == "confirmed")
        )
    )


def patch_stop(db: Session, *, actor_user_id: int, stop_api_id: str, expected_version: int, changes: Mapping[str, Any]) -> StopInfo:
    """G11. Location/district of a stop used by a confirmed route cannot move (create a new stop)."""
    public_id = parse_public_id(stop_api_id, PublicIdPrefix.STOP)
    corridor_id = db.scalar(select(CorridorStop.corridor_id).where(CorridorStop.public_id == public_id))
    if corridor_id is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    _lock_corridor_by_id(db, corridor_id)  # corridor row before the stop row (Q47)
    stop = db.scalar(select(CorridorStop).where(CorridorStop.public_id == public_id).with_for_update(key_share=True))
    if stop is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if "meeting_photo_file_id" in changes:
        changes = {
            **changes,
            "meeting_photo_file_id": _resolve_meeting_photo(
                changes["meeting_photo_file_id"], actor_user_id=actor_user_id, current_stored=stop.meeting_photo_file_id
            ),
        }
    if stop.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": stop.version})
    before = get_stop(db, stop.id)
    changed: dict[str, Any] = {}

    moved = "point" in changes and changes["point"] != before.point
    district: GeoDistrict | None = None
    if "district_id" in changes:
        district = _resolve_district_ref(db, changes["district_id"])
        moved = moved or district.id != before.district_id
    if moved and _stop_used_by_confirmed_route(db, stop.id):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "stop_used_by_confirmed_route"})

    if "point" in changes and changes["point"] != before.point:
        stop.point = func.ST_GeomFromEWKT(point_ewkt(changes["point"]))
        changed["point"] = {"lat": changes["point"].lat, "lng": changes["point"].lng}
    if district is not None and district.id != before.district_id:
        stop.geo_district_id = district.id
        changed["district_id"] = changes["district_id"]
    for field in ("name_uz", "name_ru", "meeting_note", "meeting_photo_file_id", "sequence_hint", "is_active"):
        if field in changes:
            value = changes[field]
            if isinstance(value, str) and field in ("name_uz", "name_ru"):
                value = value.strip() or None
            if value != getattr(before, field):
                setattr(stop, field, value)
                changed[field] = value
    if not changed:
        return before
    if stop.is_active and (changed.get("is_active") is True or "point" in changed or "district_id" in changed):
        stop.verified_by = actor_user_id
        stop.verified_at = utc_now()
    stop.version = stop.version + 1
    stop.updated_at = utc_now()
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise _duplicate("name_uz") from None
    _assert_public_corridor_stops(db, stop.corridor_id)
    _audit(
        db,
        actor_user_id=actor_user_id,
        entity_type="corridor_stop",
        entity_id=stop.id,
        action="corridor_stop_updated",
        old={"version": before.version, "is_active": before.is_active},
        new=changed,
        reason=None,
    )
    return get_stop(db, stop.id)


# --- route versions -----------------------------------------------------------------------------


def routing_request_hash(provider: str, provider_version: str, waypoints: Sequence[LatLng]) -> str:
    payload = {"provider": provider, "version": provider_version, "waypoints": [f"{p.lat:.6f},{p.lng:.6f}" for p in waypoints]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def prepare_route_preview(db: Session, provider: RoutingProvider, *, stop_api_ids: Sequence[str], departure_at: datetime) -> RoutePreviewPlan:
    """Phase 1 (read-only): validate stops/corridor and look up the routing cache."""
    ensure_aware_utc(departure_at, field="departure_at")
    if not 2 <= len(stop_api_ids) <= 25:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "stop_ids", "reason": "between_2_and_25"})
    if any(a == b for a, b in zip(stop_api_ids, stop_api_ids[1:])):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "stop_ids", "reason": "consecutive_duplicate"})
    stops = tuple(get_stop_by_api_id(db, api_id) for api_id in stop_api_ids)
    corridor_ids = {stop.corridor_id for stop in stops}
    if len(corridor_ids) != 1:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "stop_ids", "reason": "stops_from_different_corridors"})
    corridor = get_corridor(db, corridor_ids.pop())
    inactive = [stop.api_id for stop in stops if not stop.is_active]
    if not corridor.is_operable or inactive:
        raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"corridor_id": corridor.api_id, "inactive_stop_ids": inactive})
    waypoints = tuple(stop.point for stop in stops)
    request_hash = routing_request_hash(provider.name, provider.version, waypoints)
    cached_json = db.scalar(
        text("SELECT response FROM routing_cache WHERE provider = :p AND request_hash = :h AND expires_at > now()"),
        {"p": provider.name, "h": request_hash},
    )
    cached = None
    if cached_json is not None:
        try:
            cached = RouteResult.from_cache_json(cached_json)
        except (KeyError, TypeError, ValueError):
            cached = None
    return RoutePreviewPlan(corridor, stops, waypoints, provider.name, provider.version, request_hash, cached)


def _routing_unavailable(provider: str, reason: str) -> DomainError:
    # Provider detail stays in server logs (BR #12); clients get a generic, retryable error.
    logger.warning("routing unavailable: provider=%s reason=%s", provider, reason)
    return DomainError(ErrorCode.ROUTING_UNAVAILABLE, details={"retryable": True})


def _count_provider_call(db: Session | None, provider: str, *, failed: bool) -> None:
    """§10.8: one routing call against today's quota. Cached answers are not counted - they cost nothing."""
    if db is None or provider in ("disabled", "fake"):
        return
    try:
        from app.modules.operations import service as operations_service

        operations_service.record_provider_usage(
            db, provider=provider, operation="route", calls=1, failures=1 if failed else 0
        )
    except Exception:  # noqa: BLE001 - accounting never breaks a route lookup
        logger.warning("routing usage not counted provider=%s", provider)


def fetch_route_outside_transaction(db: Session | None, provider: RoutingProvider, plan: RoutePreviewPlan) -> tuple[RouteResult, bool]:
    """Phase 2: provider call with no open transaction. Failure -> ``503 ROUTING_UNAVAILABLE`` (AC35)."""
    if plan.cached is not None:
        return plan.cached, True
    assert_outside_transaction(db)
    try:
        result = provider.route(plan.waypoints)
    except RoutingUnavailable as exc:
        _count_provider_call(db, provider.name, failed=True)
        raise _routing_unavailable(exc.provider, exc.reason) from None
    _count_provider_call(db, provider.name, failed=False)
    distinct_points = len(set(result.geometry))
    if len(result.legs) != len(plan.waypoints) - 1 or result.distance_m <= 0 or result.duration_s <= 0 or distinct_points < 2:
        raise _routing_unavailable(provider.name, "bad_response")
    return result, False


def store_route_preview(
    db: Session,
    plan: RoutePreviewPlan,
    result: RouteResult,
    *,
    actor_user_id: int,
    from_cache: bool,
    cache_ttl_s: int,
    source: str = "routing_provider",
) -> RouteVersionInfo:
    """Phase 3 (write): cache the provider answer and create a ``draft`` route version (G5)."""
    if source == "fixture" and is_production(db):
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "fixture_routes_forbidden_in_production"})
    if not from_cache and cache_ttl_s > 0:
        db.execute(
            text(
                "INSERT INTO routing_cache (provider, request_hash, response, created_at, expires_at) "
                "VALUES (:p, :h, CAST(:r AS jsonb), now(), now() + make_interval(secs => :ttl)) "
                "ON CONFLICT (provider, request_hash) DO UPDATE "
                "SET response = EXCLUDED.response, created_at = EXCLUDED.created_at, expires_at = EXCLUDED.expires_at"
            ),
            {"p": plan.provider, "h": plan.request_hash, "r": json.dumps(result.to_cache_json()), "ttl": cache_ttl_s},
        )
    route = RouteVersion(
        public_id=new_public_uuid(),
        corridor_id=plan.corridor.id,
        created_by_user_id=actor_user_id,
        source=source,
        provider=result.provider,
        provider_version=result.provider_version,
        request_hash=plan.request_hash,
        geometry=func.ST_GeomFromEWKT(linestring_ewkt(result.geometry)),
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        is_estimate=result.is_estimate,
        status="draft",
    )
    db.add(route)
    db.flush()
    cumulative_m = cumulative_s = 0
    for seq, stop in enumerate(plan.stops):
        if seq > 0:
            leg = result.legs[seq - 1]
            cumulative_m += leg.distance_m
            cumulative_s += leg.duration_s
        db.execute(
            text(
                "INSERT INTO route_version_stops "
                "(route_version_id, seq, stop_id, cumulative_distance_m, cumulative_duration_s, line_fraction) "
                "SELECT rv.id, :seq, cs.id, :cm, :cs, round(ST_LineLocatePoint(rv.geometry, cs.point)::numeric, 7) "
                "FROM route_versions rv JOIN corridor_stops cs ON cs.id = :stop WHERE rv.id = :rv"
            ),
            {"rv": route.id, "seq": seq, "stop": stop.id, "cm": cumulative_m, "cs": cumulative_s},
        )
    return get_route_version(db, route.id)


def _route_version_info(db: Session, where: Any) -> RouteVersionInfo | None:
    row = db.execute(select(RouteVersion, func.ST_AsGeoJSON(RouteVersion.geometry).label("geojson")).where(where)).first()
    if row is None:
        return None
    route: RouteVersion = row[0]
    coords = json.loads(row.geojson)["coordinates"]
    stops = db.execute(
        select(RouteVersionStop, CorridorStop.public_id)
        .join(CorridorStop, CorridorStop.id == RouteVersionStop.stop_id)
        .where(RouteVersionStop.route_version_id == route.id)
        .order_by(RouteVersionStop.seq)
    ).all()
    return RouteVersionInfo(
        id=route.id,
        public_id=route.public_id,
        corridor_id=route.corridor_id,
        created_by_user_id=route.created_by_user_id,
        status=route.status,
        source=route.source,
        provider=route.provider,
        provider_version=route.provider_version,
        distance_m=route.distance_m,
        duration_s=route.duration_s,
        is_estimate=route.is_estimate,
        geometry=tuple(LatLng(lat=c[1], lng=c[0]) for c in coords),
        stops=tuple(
            RouteVersionStopInfo(s.seq, s.stop_id, stop_public_id, s.cumulative_distance_m, s.cumulative_duration_s, s.line_fraction)
            for s, stop_public_id in stops
        ),
        confirmed_at=route.confirmed_at,
        created_at=route.created_at,
    )


def get_route_version(db: Session, route_version_id: int) -> RouteVersionInfo:
    info = _route_version_info(db, RouteVersion.id == route_version_id)
    if info is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return info


def get_route_version_by_api_id(db: Session, api_id: str) -> RouteVersionInfo:
    public_id = parse_public_id(api_id, PublicIdPrefix.ROUTE_VERSION)
    info = _route_version_info(db, RouteVersion.public_id == public_id)
    if info is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return info


def list_corridor_routes(db: Session, corridor: CorridorInfo, *, limit: int = 20) -> list[RouteVersionInfo]:
    """G18: the confirmed route versions of a corridor - the roads a driver may plan a trip on.

    Why this exists: ``POST /trips`` needs a ``route_version_id``, and until this endpoint the only way to get
    one was ``POST /routes/preview``, which needs the routing provider. The provider is deliberately off until
    the legal/data-flow review (Q24/Q46), so a verified driver had no way at all to publish a trip - the whole
    supply side of the marketplace was unreachable in exactly the configuration production runs in.

    Reading the catalogue needs no provider: these routes were confirmed by a driver or an operator earlier,
    and they carry the same geometry, distance and attribution the preview would have returned.
    """
    rows = db.execute(
        select(RouteVersion.id)
        .where(RouteVersion.corridor_id == corridor.id, RouteVersion.status == "confirmed")
        .order_by(RouteVersion.confirmed_at.desc().nullslast(), RouteVersion.id.desc())
        .limit(max(1, min(int(limit), 50)))
    ).scalars()
    routes = [_route_version_info(db, RouteVersion.id == route_id) for route_id in rows]
    return [route for route in routes if route is not None]


#: Fallback only. The real value is ``service_corridors.max_point_offset_m`` (migration 0077): how far a marked
#: place may sit from the confirmed road is an operational judgement about a *corridor* - 3 km inside Tashkent
#: is nowhere near the road, 3 km on a long highway is a tight kerb-side tolerance - so it is configuration,
#: not a constant. This default is used only when a corridor row cannot be read.
MAX_POINT_ROUTE_OFFSET_M = 3_000


def corridor_point_offset_m(db: Session, corridor_id: int) -> int:
    """Q88 radius configured for this corridor, falling back to the pilot default.

    `ELCHI_GEO_DEV_POINT_OFFSET_M` widens it **outside production only**, so a developer can test the
    whole flow between any two places against one synthetic corridor. Production is decided by
    `platform.service.is_production` (DB marker *and* env, fail closed), exactly as the routing provider
    is - there is deliberately no way to reach this from a production database.
    """
    from app.modules.geo.config import get_geo_settings
    from app.modules.platform import service as platform_service

    override = get_geo_settings().dev_point_offset_m
    if override is not None and not platform_service.is_production(db):
        return int(override)
    value = db.execute(
        select(ServiceCorridor.max_point_offset_m).where(ServiceCorridor.id == corridor_id)
    ).scalar_one_or_none()
    return int(value) if value else MAX_POINT_ROUTE_OFFSET_M


@dataclass(frozen=True)
class RouteProjection:
    """Where a marked place falls on a confirmed road (Q88).

    ``fraction`` is the position along the line (0..1), ``offset_m`` how far the place is from the road, and
    ``seq_before`` the route stop the projection falls *after* - that is the segment whose capacity the booking
    consumes, so `booking_allocations` keeps working unchanged (AC12). The cumulative values are interpolated
    between the two surrounding stops, which is what an ETA for a mid-segment pickup has to be built on
    (spec §6.3 step 5).
    """

    route_version_id: int
    fraction: float
    offset_m: int
    seq_before: int
    seq_after: int
    cumulative_distance_m: int
    cumulative_duration_s: int
    #: Where the place sits *within* its segment, 0..1. The trip's own arrival times are interpolated with
    #: this, because a driver's plan - not the route's estimate - is what actually happens.
    segment_ratio: float


def project_point_on_route(
    db: Session, *, route_version_id: int, point: LatLng, max_offset_m: int = MAX_POINT_ROUTE_OFFSET_M
) -> RouteProjection | None:
    """Project a marked place onto a confirmed route, or ``None`` if it is too far from it.

    This is the check that keeps Q88 from becoming "anywhere on the map": the place has to sit on the road the
    driver actually agreed to drive. ``ST_LineLocatePoint`` is the mechanism the spec already names for this
    (§6.3), and the distance is measured on the geography so it is metres, not degrees.

    Returning ``None`` is a normal answer - the caller turns it into ``ROUTE_MISMATCH`` - not an error.
    """
    row = db.execute(
        text(
            """
            SELECT ST_LineLocatePoint(rv.geometry, p.geom) AS fraction,
                   ST_Distance(rv.geometry::geography, p.geom::geography) AS offset_m
              FROM route_versions rv,
                   (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS geom) p
             WHERE rv.id = :route_id
            """
        ),
        {"route_id": route_version_id, "lat": float(point.lat), "lng": float(point.lng)},
    ).one_or_none()
    if row is None:
        return None
    offset_m = int(round(float(row.offset_m)))
    if offset_m > max_offset_m:
        return None

    fraction = float(row.fraction)
    stops = db.execute(
        select(
            RouteVersionStop.seq,
            RouteVersionStop.line_fraction,
            RouteVersionStop.cumulative_distance_m,
            RouteVersionStop.cumulative_duration_s,
        )
        .where(RouteVersionStop.route_version_id == route_version_id)
        .order_by(RouteVersionStop.seq)
    ).all()
    if len(stops) < 2:
        return None

    # The segment the projection falls in: the last stop at or before it, clamped so the final stop is never
    # the "start" of a segment that has no end.
    index = 0
    for position, stop in enumerate(stops):
        if float(stop.line_fraction) <= fraction:
            index = position
    index = min(index, len(stops) - 2)
    before, after = stops[index], stops[index + 1]

    span = float(after.line_fraction) - float(before.line_fraction)
    ratio = 0.0 if span <= 0 else max(0.0, min(1.0, (fraction - float(before.line_fraction)) / span))
    return RouteProjection(
        route_version_id=route_version_id,
        fraction=fraction,
        offset_m=offset_m,
        seq_before=int(before.seq),
        seq_after=int(after.seq),
        cumulative_distance_m=int(
            round(before.cumulative_distance_m + ratio * (after.cumulative_distance_m - before.cumulative_distance_m))
        ),
        cumulative_duration_s=int(
            round(before.cumulative_duration_s + ratio * (after.cumulative_duration_s - before.cumulative_duration_s))
        ),
        segment_ratio=ratio,
    )


def confirm_route_version(db: Session, *, actor_user_id: int, route_version_api_id: str, now: datetime | None = None) -> RouteVersionInfo:
    """G6: the creator confirms a fresh draft whose corridor and stops are still active."""
    public_id = parse_public_id(route_version_api_id, PublicIdPrefix.ROUTE_VERSION)
    route = db.scalar(select(RouteVersion).where(RouteVersion.public_id == public_id).with_for_update())
    if route is None or route.created_by_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    current = now or utc_now()
    if route.status != "draft":
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "route_version", "from": route.status, "to": "confirmed"})
    if current - route.created_at > ROUTE_DRAFT_TTL:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "route_version", "reason": "draft_expired"})
    info = get_route_version(db, route.id)
    corridor = get_corridor(db, route.corridor_id)
    stops = get_stops(db, [s.stop_id for s in info.stops])
    inactive = [stops[s.stop_id].api_id for s in info.stops if not stops[s.stop_id].is_active]
    if not corridor.is_operable or inactive:
        raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"corridor_id": corridor.api_id, "inactive_stop_ids": inactive})
    route.status = "confirmed"
    route.confirmed_at = current
    db.flush()
    return get_route_version(db, route.id)


def planned_occurrences_from_route_version(
    route: RouteVersionInfo, *, planned_start_at: datetime, dwell_minutes: int = 0
) -> tuple[OccurrenceTiming, ...]:
    """Default schedule for a trip on this route (A1 may override per stop):
    arrival = start + cumulative driving time + dwell at every earlier intermediate stop."""
    start = ensure_aware_utc(planned_start_at, field="planned_start_at")
    result: list[OccurrenceTiming] = []
    for index, stop in enumerate(route.stops):
        dwell_before = dwell_minutes * max(0, index - 1) if index > 0 else 0
        arrival = start + timedelta(seconds=stop.cumulative_duration_s, minutes=dwell_before)
        is_intermediate = 0 < index < len(route.stops) - 1
        result.append(OccurrenceTiming(stop.seq, stop.stop_id, arrival, dwell_minutes if is_intermediate else 0))
    return tuple(result)


# --- matching ---------------------------------------------------------------------------------------

# Confirmed route versions near BOTH stops, newest first (BR #15). Exposed for the GiST plan test (BR #17).
FIND_CANDIDATES_SQL = """
WITH p AS (SELECT point FROM corridor_stops WHERE id = :pickup),
     d AS (SELECT point FROM corridor_stops WHERE id = :dropoff)
SELECT rv.id, rv.corridor_id, rv.confirmed_at,
       round(ST_Distance(rv.geometry::geography, p.point::geography))::int AS pickup_distance_m,
       round(ST_Distance(rv.geometry::geography, d.point::geography))::int AS dropoff_distance_m,
       round(ST_LineLocatePoint(rv.geometry, p.point)::numeric, 7) AS pickup_fraction,
       round(ST_LineLocatePoint(rv.geometry, d.point)::numeric, 7) AS dropoff_fraction,
       ARRAY(SELECT s.seq FROM route_version_stops s WHERE s.route_version_id = rv.id AND s.stop_id = :pickup ORDER BY s.seq) AS pickup_seqs,
       ARRAY(SELECT s.seq FROM route_version_stops s WHERE s.route_version_id = rv.id AND s.stop_id = :dropoff ORDER BY s.seq) AS dropoff_seqs
FROM route_versions rv, p, d
WHERE rv.status = 'confirmed'
  AND ST_DWithin(rv.geometry::geography, p.point::geography, :radius)
  AND ST_DWithin(rv.geometry::geography, d.point::geography, :radius)
  AND (CAST(:corridor_id AS bigint) IS NULL OR rv.corridor_id = CAST(:corridor_id AS bigint))
ORDER BY rv.confirmed_at DESC, rv.id DESC
LIMIT :limit
"""


def find_candidates(
    db: Session,
    *,
    pickup_stop_id: int,
    dropoff_stop_id: int,
    search_radius_m: int | None = None,
    corridor_id: int | None = None,
    limit: int = 100,
) -> list[RouteCandidate]:
    """Confirmed route versions passing within ``search_radius_m`` metres of BOTH stops.

    ``ST_DWithin(geometry::geography, point::geography, metres)`` on GiST expression indexes.
    Default radius: the pickup stop's corridor config. Newest confirmed routes first; callers
    filter by trip date/status in their own module.
    """
    if search_radius_m is None:
        search_radius_m = get_corridor(db, get_stop(db, pickup_stop_id).corridor_id).config.search_radius_m
    if search_radius_m <= 0:
        raise ValueError("search_radius_m must be positive")
    rows = db.execute(
        text(FIND_CANDIDATES_SQL),
        {"pickup": pickup_stop_id, "dropoff": dropoff_stop_id, "radius": search_radius_m, "corridor_id": corridor_id, "limit": limit},
    ).all()
    return [
        RouteCandidate(
            r.id, r.corridor_id, r.pickup_distance_m, r.dropoff_distance_m, r.pickup_fraction, r.dropoff_fraction,
            tuple(r.pickup_seqs), tuple(r.dropoff_seqs), r.confirmed_at,
        )
        for r in rows
    ]


def measure_detours_outside_transaction(
    db: Session | None,
    provider: RoutingProvider,
    trip: TripRouteContext,
    request: MatchRequest,
    stop_points: Mapping[int, LatLng],
    *,
    now: datetime | None = None,
) -> DetourMeasurements:
    """Router detour probes returning ``DetourQuote`` snapshots (spec §6.3 step 4, BR #3).

    Load ``stop_points`` first, end the transaction, then call. A4 later validates the quotes under
    lock with ``validate_detour_quote`` and ``verify_existing_windows`` (no router call).
    """
    assert_outside_transaction(db)
    return measure_detours(provider, trip, request, stop_points, now=now)


# --- feature flags ------------------------------------------------------------------------------------


def _load_flag_rows(db: Session, flag_key: FeatureFlagKey | None = None) -> list[FlagRow]:
    query = select(FeatureFlagValue.flag_key, FeatureFlagValue.scope_type, FeatureFlagValue.scope_ref, FeatureFlagValue.enabled)
    if flag_key is not None:
        query = query.where(FeatureFlagValue.flag_key == FeatureFlagKey(flag_key).value)
    return [FlagRow(FeatureFlagKey(k), FlagScopeType(s), ref, enabled) for k, s, ref, enabled in db.execute(query).all()]


def _corridor_context(corridor: CorridorInfo | None, *, region_codes: Sequence[str] = (), cohorts: Sequence[str] = ()) -> FlagScopeContext:
    regions = list(region_codes)
    corridor_ref = None
    if corridor is not None:
        corridor_ref = corridor.api_id
        regions.extend([corridor.origin_region.code, corridor.destination_region.code])
    return FlagScopeContext(corridor_ref=corridor_ref, region_refs=tuple(dict.fromkeys(regions)), cohort_refs=tuple(dict.fromkeys(cohorts)))


def resolve_flags(
    db: Session,
    *,
    corridor_id: int | None = None,
    region_codes: Sequence[str] = (),
    cohorts: Sequence[str] = (),
    keys: Iterable[FeatureFlagKey] | None = None,
) -> dict[FeatureFlagKey, FlagResolution]:
    corridor = get_corridor(db, corridor_id) if corridor_id is not None else None
    context = _corridor_context(corridor, region_codes=region_codes, cohorts=cohorts)
    rows = _load_flag_rows(db)
    production = is_production(db)
    return {key: flag_rules.resolve_flag(key, rows, context, production=production) for key in (keys or list(FeatureFlagKey))}


def is_flag_enabled(
    db: Session,
    flag_key: FeatureFlagKey,
    *,
    corridor_id: int | None = None,
    region_codes: Sequence[str] = (),
    cohorts: Sequence[str] = (),
) -> bool:
    """Effective value at call time (cohort > corridor > region > country > production default).

    Production (settings or DB marker): ``wallet_required`` is always True (Q1). Callers that must
    freeze the value for a booking snapshot it (``snapshot_flags``); flags never rewrite bookings.
    """
    key = FeatureFlagKey(flag_key)
    return resolve_flags(db, corridor_id=corridor_id, region_codes=region_codes, cohorts=cohorts, keys=[key])[key].enabled


def snapshot_flags(db: Session, *, corridor_id: int | None, cohorts: Sequence[str] = ()) -> dict[str, bool]:
    """All flags as ``{key: bool}`` for ``bookings.terms_snapshot.flags`` (ADR-0008 §5)."""
    return {key.value: res.enabled for key, res in resolve_flags(db, corridor_id=corridor_id, cohorts=cohorts).items()}


def production_flag_violations(db: Session) -> list[dict[str, Any]]:
    """Rows contradicting production rules (readiness/alerts); empty outside production.

    * a locked flag with another value (``wallet_required=false``, Q1);
    * an approval-required flag enabled without an approval reference (Q5, K7).
    """
    if not is_production(db):
        return []
    violations: list[dict[str, Any]] = []
    rows = db.execute(
        select(FeatureFlagValue.flag_key, FeatureFlagValue.scope_type, FeatureFlagValue.scope_ref, FeatureFlagValue.enabled, FeatureFlagValue.approval_reference)
        .order_by(FeatureFlagValue.id)
    ).all()
    for key_value, scope_type, scope_ref, enabled, approval in rows:
        key = FeatureFlagKey(key_value)
        locked = FLAGS_LOCKED_IN_PRODUCTION.get(key)
        if locked is not None and enabled != locked:
            violations.append({"flag_key": key.value, "scope_type": scope_type, "scope_ref": scope_ref, "enabled": enabled, "rule": "locked_value"})
        if key in FLAGS_REQUIRING_APPROVAL_REFERENCE and enabled and not (approval or "").strip():
            violations.append({"flag_key": key.value, "scope_type": scope_type, "scope_ref": scope_ref, "enabled": enabled, "rule": "approval_reference_required"})
    return violations


def _flag_info(row: FeatureFlagValue) -> FlagValueInfo:
    return FlagValueInfo(
        row.id,
        row.public_id,
        FeatureFlagKey(row.flag_key),
        FlagScopeType(row.scope_type),
        row.scope_ref,
        row.enabled,
        row.approval_reference,
        row.reason,
        row.version,
        row.updated_by,
        row.updated_at,
    )


def list_flag_values(db: Session, *, flag_key: FeatureFlagKey | None = None, scope_type: FlagScopeType | None = None) -> list[FlagValueInfo]:
    query = select(FeatureFlagValue).order_by(FeatureFlagValue.flag_key, FeatureFlagValue.scope_type, FeatureFlagValue.scope_ref, FeatureFlagValue.id)
    if flag_key is not None:
        query = query.where(FeatureFlagValue.flag_key == FeatureFlagKey(flag_key).value)
    if scope_type is not None:
        query = query.where(FeatureFlagValue.scope_type == FlagScopeType(scope_type).value)
    return [_flag_info(row) for row in db.scalars(query)]


def mark_flag_change_source(db: Session | Connection) -> None:
    """Q72: mark the current transaction as the application/admin-API flag writer.

    Equivalent to ``SET LOCAL elchi.flag_change_source = 'admin_api'`` (``set_config(..., is_local => true)``),
    so it lasts until the transaction (or the savepoint it was set in) ends. The 0057 trigger refuses turning a
    v2 service flag ON without it; turning OFF never needs it. Called by :func:`set_flag_value`; tests that
    enable flags with raw SQL call it on the same session/connection first. No-op outside PostgreSQL.

    Limitation (ADR-0008 Q72): the marker is a plain transaction setting. Anyone connected with the app role
    (e.g. psql) can set it too, and the table owner/superuser can disable the trigger. The guard stops
    accidental psql/migration enables, not a deliberate actor with full DB rights (Q36 roles, the
    ``feature_flag_changes`` history and monitoring cover that).
    """
    bind = db.get_bind() if isinstance(db, Session) else db
    if bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": FLAG_CHANGE_SOURCE_SETTING, "value": FLAG_CHANGE_SOURCE_ADMIN_API},
    )


def _mark_flag_change_source_for_write(db: Session) -> str | None:
    """Set the Q72 marker; returns the previous value (``None`` outside PostgreSQL)."""
    if db.get_bind().dialect.name != "postgresql":
        return None
    previous = db.scalar(text("SELECT coalesce(current_setting(:name, true), '')"), {"name": FLAG_CHANGE_SOURCE_SETTING}) or ""
    mark_flag_change_source(db)
    return previous


def _restore_flag_change_source(db: Session, previous: str | None) -> None:
    if previous is None or previous == FLAG_CHANGE_SOURCE_ADMIN_API:
        return
    db.execute(text("SELECT set_config(:name, :value, true)"), {"name": FLAG_CHANGE_SOURCE_SETTING, "value": previous})


def set_flag_value(
    db: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Iterable[Capability],
    actor_is_super_admin: bool,
    flag_key: FeatureFlagKey,
    scope_type: FlagScopeType,
    scope_ref: str,
    enabled: bool,
    reason: str,
    approval_reference: str | None = None,
    expected_version: int | None = None,
) -> FlagValueInfo:
    """F3 upsert. History row is appended by the DB trigger; ``audit_logs`` gets the staff action.
    Production rules (Q1, Q5, Q56) are checked here and again by DB triggers (0033, 0043, 0053)."""
    key = FeatureFlagKey(flag_key)
    scope = FlagScopeType(scope_type)
    flag_rules.authorize_flag_change(
        key,
        enabled=enabled,
        approval_reference=approval_reference,
        actor_capabilities=actor_capabilities,
        actor_is_super_admin=actor_is_super_admin,
        production=is_production(db),
    )
    ref = flag_rules.validate_scope_ref(scope, scope_ref)
    if scope is FlagScopeType.CORRIDOR:
        get_corridor_by_api_id(db, ref)
    elif scope is FlagScopeType.REGION:
        get_region_by_code(db, ref)
    clean_reason = reason.strip() if isinstance(reason, str) else ""
    if not 1 <= len(clean_reason) <= flag_rules.MAX_REASON_LENGTH:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    approval = flag_rules.normalize_approval_reference(approval_reference)

    current = db.scalar(
        select(FeatureFlagValue)
        .where(FeatureFlagValue.flag_key == key.value, FeatureFlagValue.scope_type == scope.value, FeatureFlagValue.scope_ref == ref)
        .with_for_update(key_share=True)
    )
    if enabled and (current is None or not current.enabled) and key is FeatureFlagKey.PASSENGER_ENABLED and is_production(db):
        # Q87/U7: the passenger service may not be switched on while support has no reachable phone. §16 forbids
        # promising help that does not exist; the check reads the same configuration S13 answers from.
        from app.modules.trust_support.config import support_contacts

        available, _phone, _hours = support_contacts()
        if not available:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                details={"flag_key": key.value, "reason": "support_contact_not_configured"},
            )
    if enabled and (current is None or not current.enabled) and key in V2_SERVICE_FLAGS and is_production(db):
        passed, gate_reason = q48_gate_passed(db)
        if not passed:  # Q56: no v2 service switched on in production while the Q48 launch gate fails
            raise DomainError(
                ErrorCode.PRODUCTION_INVARIANTS_FAILED,
                details={"gate": "q48", "reason": gate_reason, "flag_key": key.value},
            )
    if current is None:
        if expected_version is not None:
            raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": None})
        old_enabled = None
        statement = text(
            "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, approval_reference, reason, version, updated_by) "
            "VALUES (:public_id, :k, :s, :r, :e, :a, :reason, 1, :u) "
            "ON CONFLICT (flag_key, scope_type, scope_ref) DO NOTHING RETURNING id"
        )
        params = {"public_id": new_public_uuid(), "k": key.value, "s": scope.value, "r": ref, "e": enabled, "a": approval, "reason": clean_reason, "u": actor_user_id}
    else:
        if expected_version is None or expected_version != current.version:
            raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": current.version})
        old_enabled = current.enabled
        statement = text(
            "UPDATE feature_flag_values SET enabled = :e, approval_reference = :a, reason = :reason, "
            "updated_by = :u, version = version + 1 WHERE id = :id RETURNING id"
        )
        params = {"e": enabled, "a": approval, "reason": clean_reason, "u": actor_user_id, "id": current.id}

    # Q72: this is the application/admin-API writer. The marker is set only after every check, covers only this
    # one statement and is put back to whatever the transaction carried before (try/finally), so a caller that
    # catches an error in the same transaction is not left with it. After a DB error the transaction is aborted
    # (the setting is discarded with it), so no restore is attempted then.
    previous_source = _mark_flag_change_source_for_write(db)
    db_failed = False
    try:
        new_id = db.scalar(statement, params)
    except DBAPIError:
        db_failed = True
        raise
    finally:
        if not db_failed:
            _restore_flag_change_source(db, previous_source)
    if new_id is None:  # INSERT: a concurrent writer created it first
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": 1})
    row = db.execute(select(FeatureFlagValue).where(FeatureFlagValue.id == new_id).execution_options(populate_existing=True)).scalar_one()
    info = _flag_info(row)
    _audit(
        db,
        actor_user_id=actor_user_id,
        entity_type="feature_flag_value",
        entity_id=info.id,
        action="feature_flag_set",
        old={"enabled": old_enabled} if old_enabled is not None else None,
        new={"flag_key": key.value, "scope_type": scope.value, "scope_ref": ref, "enabled": enabled, "approval_reference": approval, "version": info.version},
        reason=clean_reason,
    )
    return info


def list_flag_history(db: Session, *, flag_key: FeatureFlagKey, after_id: int | None, limit: int) -> tuple[list[FlagChangeInfo], int | None]:
    query = select(FeatureFlagChange).where(FeatureFlagChange.flag_key == FeatureFlagKey(flag_key).value)
    if after_id is not None:
        query = query.where(FeatureFlagChange.id < after_id)
    rows = list(db.scalars(query.order_by(FeatureFlagChange.id.desc()).limit(limit + 1)))
    items = [
        FlagChangeInfo(
            r.id, FeatureFlagKey(r.flag_key), FlagScopeType(r.scope_type), r.scope_ref, r.value_version,
            r.old_enabled, r.new_enabled, r.actor_user_id, r.reason, r.approval_reference, r.changed_at,
        )
        for r in rows[:limit]
    ]
    return items, (items[-1].id if len(rows) > limit else None)


def user_api_ids(db: Session, user_ids: Iterable[int]) -> dict[int, str | None]:
    """``usr_…`` ids from ``users.public_id`` (A1, migration 0032)."""
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    has_column = db.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'public_id')"
        )
    )
    if not has_column:
        return {user_id: None for user_id in ids}
    rows = db.execute(text("SELECT id, public_id FROM users WHERE id = ANY(:ids)"), {"ids": ids}).all()
    found = {row[0]: (format_public_id(PublicIdPrefix.USER, row[1]) if row[1] is not None else None) for row in rows}
    return {user_id: found.get(user_id) for user_id in ids}


# --- corridor price bands (Q42) --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriceBandInfo:
    id: int
    corridor_id: int
    corridor_public_id: uuid.UUID
    service_type: ServiceType
    origin_stop_id: int | None
    origin_stop_public_id: uuid.UUID | None
    destination_stop_id: int | None
    destination_stop_public_id: uuid.UUID | None
    floor_minor: int
    ceiling_minor: int
    currency: str
    is_active: bool
    #: Q90: false = the band advises (warning + ranking); true = an admin-imposed abuse/safety limit that
    #: refuses a price. Nothing else in the product refuses a negotiated amount.
    enforced: bool
    version: int
    reason: str
    updated_by: int
    updated_at: datetime

    @property
    def price_basis(self):  # noqa: ANN201
        return PRICE_BAND_BASIS[self.service_type]

    def to_band(self) -> PriceBand:
        return PriceBand(
            corridor_id=self.corridor_id,
            service_type=self.service_type,
            origin_stop_id=self.origin_stop_id,
            destination_stop_id=self.destination_stop_id,
            floor_minor=self.floor_minor,
            ceiling_minor=self.ceiling_minor,
            is_active=self.is_active,
            version=self.version,
            currency=self.currency,
        )


@dataclass(frozen=True, slots=True)
class PriceBandChangeInfo:
    id: int
    service_type: ServiceType
    origin_stop_public_id: uuid.UUID | None
    destination_stop_public_id: uuid.UUID | None
    band_version: int
    old_floor_minor: int | None
    old_ceiling_minor: int | None
    old_is_active: bool | None
    new_floor_minor: int
    new_ceiling_minor: int
    new_is_active: bool
    actor_user_id: int
    reason: str
    changed_at: datetime


def _band_query():  # noqa: ANN202
    origin = CorridorStop.__table__.alias("band_origin")
    destination = CorridorStop.__table__.alias("band_destination")
    return (
        select(
            CorridorPriceBand,
            ServiceCorridor.public_id.label("corridor_public_id"),
            origin.c.public_id.label("origin_public_id"),
            destination.c.public_id.label("destination_public_id"),
        )
        .join(ServiceCorridor, ServiceCorridor.id == CorridorPriceBand.corridor_id)
        .outerjoin(origin, origin.c.id == CorridorPriceBand.origin_stop_id)
        .outerjoin(destination, destination.c.id == CorridorPriceBand.destination_stop_id)
    )


def _band_info(row: Any) -> PriceBandInfo:
    band: CorridorPriceBand = row[0]
    return PriceBandInfo(
        band.id, band.corridor_id, row.corridor_public_id, ServiceType(band.service_type),
        band.origin_stop_id, row.origin_public_id, band.destination_stop_id, row.destination_public_id,
        band.floor_minor, band.ceiling_minor, band.currency, band.is_active, band.enforced, band.version,
        band.reason, band.updated_by, band.updated_at,
    )


def list_price_bands(db: Session, corridor: CorridorInfo) -> list[PriceBandInfo]:
    rows = db.execute(
        _band_query()
        .where(CorridorPriceBand.corridor_id == corridor.id)
        .order_by(CorridorPriceBand.service_type, CorridorPriceBand.origin_stop_id.is_not(None), CorridorPriceBand.id)
    ).all()
    return [_band_info(row) for row in rows]


def resolve_price_band(
    db: Session,
    *,
    corridor_id: int,
    service_type: ServiceType,
    origin_stop_id: int | None,
    destination_stop_id: int | None,
) -> PriceBand | None:
    """Q42 reference band for a proposal segment (read-only): the active segment band, else the active
    corridor-wide band, else ``None``.

    Q88: either end may be a map point instead of a stop, and then there is no segment to look up - the
    corridor-wide band answers for the whole direction. A point-ended listing is therefore *never* without a
    price reference merely because it was marked on the map, which is what kept it out of the ranking before.

    Q90: what comes back advises (ranking, warning) and only refuses when the band is ``enforced``.
    """
    svc = ServiceType(service_type)
    segment_scoped = origin_stop_id is not None and destination_stop_id is not None
    scope = (
        CorridorPriceBand.origin_stop_id.is_(None)
        | ((CorridorPriceBand.origin_stop_id == origin_stop_id) & (CorridorPriceBand.destination_stop_id == destination_stop_id))
        if segment_scoped
        else CorridorPriceBand.origin_stop_id.is_(None)
    )
    rows = db.scalars(
        select(CorridorPriceBand).where(
            CorridorPriceBand.corridor_id == corridor_id,
            CorridorPriceBand.service_type == svc.value,
            CorridorPriceBand.is_active.is_(True),
            scope,
        )
    ).all()
    bands = [
        PriceBand(r.corridor_id, ServiceType(r.service_type), r.origin_stop_id, r.destination_stop_id, r.floor_minor, r.ceiling_minor, r.is_active, r.version, r.currency, r.enforced)
        for r in rows
    ]
    return select_price_band(bands, corridor_id=corridor_id, service_type=svc, origin_stop_id=origin_stop_id, destination_stop_id=destination_stop_id)


def _band_invalid(field: str, reason: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_ERROR, details={"field": field, "reason": reason})


def set_price_band(
    db: Session,
    *,
    actor_user_id: int,
    corridor_api_id: str,
    service_type: ServiceType,
    origin_stop_api_id: str | None,
    destination_stop_api_id: str | None,
    floor_minor: int,
    ceiling_minor: int,
    is_active: bool,
    reason: str,
    enforced: bool = False,
    expected_version: int | None = None,
) -> PriceBandInfo:
    """Versioned upsert of one band scope (G13). History row by DB trigger; staff action audited."""
    svc = ServiceType(service_type)
    corridor = get_corridor_by_api_id(db, corridor_api_id)
    if (origin_stop_api_id is None) != (destination_stop_api_id is None):
        raise _band_invalid("origin_stop_id", "segment_needs_both_stops")
    origin_id = destination_id = None
    if origin_stop_api_id is not None and destination_stop_api_id is not None:
        if origin_stop_api_id == destination_stop_api_id:
            raise _band_invalid("destination_stop_id", "same_stop")
        stops = get_stops_by_api_ids(db, [origin_stop_api_id, destination_stop_api_id])
        for field, api_id in (("origin_stop_id", origin_stop_api_id), ("destination_stop_id", destination_stop_api_id)):
            info = stops.get(api_id)
            if info is None or info.corridor_id != corridor.id:
                raise _band_invalid(field, "stop_not_in_corridor")
        origin_id, destination_id = stops[origin_stop_api_id].id, stops[destination_stop_api_id].id
    for field, value in (("floor_minor", floor_minor), ("ceiling_minor", ceiling_minor)):
        try:
            validate_minor_amount(value, allow_zero=False, name=field)
        except (TypeError, ValueError):
            raise _band_invalid(field, "positive_integer_required") from None
    if floor_minor > ceiling_minor:
        raise _band_invalid("floor_minor", "floor_above_ceiling")
    clean_reason = reason.strip() if isinstance(reason, str) else ""
    if not 1 <= len(clean_reason) <= 500:
        raise _band_invalid("reason", "required")

    current = db.scalar(
        select(CorridorPriceBand)
        .where(
            CorridorPriceBand.corridor_id == corridor.id,
            CorridorPriceBand.service_type == svc.value,
            CorridorPriceBand.origin_stop_id.is_not_distinct_from(origin_id),
            CorridorPriceBand.destination_stop_id.is_not_distinct_from(destination_id),
        )
        .with_for_update(key_share=True)
    )
    params = {"f": floor_minor, "c": ceiling_minor, "a": is_active, "e": bool(enforced), "r": clean_reason, "u": actor_user_id}
    if current is None:
        if expected_version is not None:
            raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": None})
        band_id = db.scalar(
            text(
                "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, origin_stop_id, destination_stop_id, "
                "floor_minor, ceiling_minor, is_active, enforced, reason, version, updated_by) "
                "VALUES (:p, :corridor, :s, :basis, :o, :d, :f, :c, :a, :e, :r, 1, :u) ON CONFLICT DO NOTHING RETURNING id"
            ),
            {**params, "p": new_public_uuid(), "corridor": corridor.id, "s": svc.value, "basis": PRICE_BAND_BASIS[svc].value, "o": origin_id, "d": destination_id},
        )
        if band_id is None:  # a concurrent writer created this scope first
            raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": 1})
        old = None
    else:
        if expected_version is None or expected_version != current.version:
            raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": current.version})
        old = {
            "floor_minor": current.floor_minor,
            "ceiling_minor": current.ceiling_minor,
            "is_active": current.is_active,
            "enforced": current.enforced,
        }
        band_id = current.id
        db.execute(
            text(
                "UPDATE corridor_price_bands SET floor_minor = :f, ceiling_minor = :c, is_active = :a, "
                "enforced = :e, reason = :r, updated_by = :u, version = version + 1 WHERE id = :id"
            ),
            {**params, "id": current.id},
        )
    info = _band_info(db.execute(_band_query().where(CorridorPriceBand.id == band_id).execution_options(populate_existing=True)).one())
    _audit(
        db,
        actor_user_id=actor_user_id,
        entity_type="corridor_price_band",
        entity_id=info.id,
        action="corridor_price_band_set",
        old=old,
        new={
            "corridor": corridor.api_id, "service_type": svc.value, "origin_stop_id": origin_stop_api_id,
            "destination_stop_id": destination_stop_api_id, "floor_minor": floor_minor, "ceiling_minor": ceiling_minor,
            "is_active": is_active, "enforced": bool(enforced), "version": info.version,
        },
        reason=clean_reason,
    )
    return info


def list_price_band_history(db: Session, *, corridor: CorridorInfo, after_id: int | None, limit: int) -> tuple[list[PriceBandChangeInfo], int | None]:
    origin = CorridorStop.__table__.alias("change_origin")
    destination = CorridorStop.__table__.alias("change_destination")
    query = (
        select(CorridorPriceBandChange, origin.c.public_id.label("origin_public_id"), destination.c.public_id.label("destination_public_id"))
        .outerjoin(origin, origin.c.id == CorridorPriceBandChange.origin_stop_id)
        .outerjoin(destination, destination.c.id == CorridorPriceBandChange.destination_stop_id)
        .where(CorridorPriceBandChange.corridor_id == corridor.id)
    )
    if after_id is not None:
        query = query.where(CorridorPriceBandChange.id < after_id)
    rows = db.execute(query.order_by(CorridorPriceBandChange.id.desc()).limit(limit + 1)).all()
    items = [
        PriceBandChangeInfo(
            c.id, ServiceType(c.service_type), row.origin_public_id, row.destination_public_id, c.band_version,
            c.old_floor_minor, c.old_ceiling_minor, c.old_is_active, c.new_floor_minor, c.new_ceiling_minor,
            c.new_is_active, c.actor_user_id, c.reason, c.changed_at,
        )
        for row in rows[:limit]
        for c in (row[0],)
    ]
    return items, (items[-1].id if len(rows) > limit else None)


# --- Q56: v2 service flags behind the Q48 launch gate --------------------------------------------------

V2_SERVICE_FLAGS: frozenset[FeatureFlagKey] = frozenset(
    {
        FeatureFlagKey.PASSENGER_ENABLED,
        FeatureFlagKey.PARCEL_ENABLED,
        FeatureFlagKey.DRIVER_LISTING_ENABLED,
        FeatureFlagKey.CORRIDOR_MATCHING_ENABLED,
        FeatureFlagKey.TRACKING_ENABLED,
        FeatureFlagKey.CARD_PAYMENTS_ENABLED,
    }
)
# A3's gate, expected as ``app.modules.platform.service.q48_gate_status(session)`` returning a bool or an
# object with ``passed: bool``. Until it exists the gate counts as failed (fail closed).
Q48_GATE_FUNCTION = "q48_gate_status"


def q48_gate_passed(db: Session) -> tuple[bool, str]:
    """``(passed, reason)``; only an explicit ``True`` passes (``gate_unavailable`` / ``gate_error`` / ``gate_failed``)."""
    gate = getattr(platform_service, Q48_GATE_FUNCTION, None)
    if gate is None:
        return False, "gate_unavailable"
    try:
        result = gate(db)
    except Exception:  # noqa: BLE001 - any failure to evaluate the gate refuses the enable
        logger.exception("q48 gate evaluation failed")
        return False, "gate_error"
    passed = result if isinstance(result, bool) else getattr(result, "passed", None)
    return (True, "passed") if passed is True else (False, "gate_failed")


# --- F1: existing Q47 violations (read-only) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Q47Violation:
    corridor_id: int
    corridor_public_id: uuid.UUID
    name: str
    rollout_state: CorridorRolloutState
    active_stops: int
    stops_missing_evidence: tuple[str, ...]

    @property
    def api_id(self) -> str:
        return corridor_api_id(self.corridor_public_id)

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.active_stops < PILOT_MIN_ACTIVE_STOPS:
            reasons.append("needs_two_active_stops")
        if self.stops_missing_evidence:
            reasons.append("stops_missing_meeting_evidence")
        return tuple(reasons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "corridor_id": self.api_id,
            "name": self.name,
            "rollout_state": self.rollout_state.value,
            "active_stops": self.active_stops,
            "stops_missing_evidence": list(self.stops_missing_evidence),
            "reasons": list(self.reasons),
        }


Q47_VIOLATIONS_SQL = """
SELECT c.id, c.public_id, c.name, c.rollout_state,
       count(s.id) FILTER (WHERE s.is_active) AS active_stops,
       coalesce(array_agg(s.public_id ORDER BY s.id) FILTER (
           WHERE s.is_active AND (s.meeting_note IS NULL OR btrim(s.meeting_note) = '') AND s.meeting_photo_file_id IS NULL
       ), '{}') AS missing
FROM service_corridors c
LEFT JOIN corridor_stops s ON s.corridor_id = c.id
WHERE c.rollout_state IN ('pilot', 'active')
GROUP BY c.id, c.public_id, c.name, c.rollout_state
HAVING count(s.id) FILTER (WHERE s.is_active) < 2
    OR count(s.id) FILTER (
           WHERE s.is_active AND (s.meeting_note IS NULL OR btrim(s.meeting_note) = '') AND s.meeting_photo_file_id IS NULL
       ) > 0
ORDER BY c.id
"""


def find_q47_violations(db: Session) -> list[Q47Violation]:
    """Pilot/active corridors that already break Q47. Read-only; repair per ``app.modules.geo.checks`` runbook."""
    return [
        Q47Violation(r.id, r.public_id, r.name, CorridorRolloutState(r.rollout_state), int(r.active_stops), tuple(stop_api_id(u) for u in r.missing))
        for r in db.execute(text(Q47_VIOLATIONS_SQL)).all()
    ]


def production_invariant_notices(db: Session) -> list[dict[str, Any]]:
    """Geo notices for readiness/alerts (A10a): never a 503, always reported (Q47 in every environment)."""
    notices: list[dict[str, Any]] = [{"check": "geo.q47", **violation.as_dict()} for violation in find_q47_violations(db)]
    notices.extend({"check": "geo.flags", **item} for item in production_flag_violations(db))
    return notices


# Readiness notice names (Q57 style: information only, never a 503 / never ``production_invariants: fail``).
NOTICE_Q47_VIOLATIONS_PRESENT = "q47_violations_present"
NOTICE_PRODUCTION_FLAG_VIOLATIONS_PRESENT = "production_flag_violations_present"
NOTICE_ROUTING_PROVIDER_DISABLED = "routing_provider_disabled"
NOTICE_GEO_CHECK_ERROR = "geo_readiness_check_error"


def readiness_notices(db: Session) -> list[str]:
    """Geo notice names for ``/health/ready`` ``notices`` (A10a). Read-only, never raises, never commits.

    * ``q47_violations_present`` - a pilot/active corridor breaks Q47 (details: ``find_q47_violations``);
    * ``production_flag_violations_present`` - production flag rows contradict Q1/Q5 (``production_flag_violations``);
    * ``routing_provider_disabled`` - no routing provider: detour matches are unavailable, stop matches work
      (always in production, Q24/Q46);
    * ``geo_readiness_check_error`` - one of the checks could not run (logged); the others still report.
    Each check runs in its own savepoint so a failing query does not poison the caller's transaction.
    """
    from app.modules.geo.config import build_routing_provider  # lazy: config imports the provider clients
    from app.modules.geo.routing.base import DisabledRoutingProvider

    checks: tuple[tuple[str, Callable[[], bool]], ...] = (
        (NOTICE_Q47_VIOLATIONS_PRESENT, lambda: bool(find_q47_violations(db))),
        (NOTICE_PRODUCTION_FLAG_VIOLATIONS_PRESENT, lambda: bool(production_flag_violations(db))),
        (NOTICE_ROUTING_PROVIDER_DISABLED, lambda: isinstance(build_routing_provider(production=is_production(db)), DisabledRoutingProvider)),
    )
    notices: list[str] = []
    for name, check in checks:
        try:
            with db.begin_nested():
                present = check()
        except Exception:  # noqa: BLE001 - readiness notices are information only
            logger.warning("geo_readiness_notice_check_failed notice=%s", name, exc_info=True)
            if NOTICE_GEO_CHECK_ERROR not in notices:
                notices.append(NOTICE_GEO_CHECK_ERROR)
            continue
        if present:
            notices.append(name)
    return notices


# --- F3/Q53: operator warning on price band configuration ---------------------------------------------


def price_band_warnings(db: Session, *, corridor_id: int, service_type: ServiceType) -> list[dict[str, Any]]:
    """Warn when the active corridor-wide floor is above the lowest active segment floor: corridor-wide bands
    are meant as loose safety limits, exact segment bands set real prices (Q53)."""
    svc = ServiceType(service_type)
    rows = db.execute(
        select(CorridorPriceBand.origin_stop_id.is_(None).label("corridor_wide"), func.min(CorridorPriceBand.floor_minor))
        .where(
            CorridorPriceBand.corridor_id == corridor_id,
            CorridorPriceBand.service_type == svc.value,
            CorridorPriceBand.is_active.is_(True),
        )
        .group_by(CorridorPriceBand.origin_stop_id.is_(None))
    ).all()
    corridor_floor = next((floor for wide, floor in rows if wide), None)
    segment_floor = next((floor for wide, floor in rows if not wide), None)
    if corridor_floor is not None and segment_floor is not None and corridor_floor > segment_floor:
        return [
            {
                "code": "CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR",
                "service_type": svc.value,
                "corridor_floor_minor": int(corridor_floor),
                "lowest_segment_floor_minor": int(segment_floor),
            }
        ]
    return []


# --- districts as a direction unit (wave 10) ---------------------------------------------


@dataclass(frozen=True, slots=True)
class DistrictInfo:
    id: int
    public_id: uuid.UUID
    region_id: int
    region_public_id: uuid.UUID
    region_code: str
    region_name_uz: str
    name_uz: str
    name_ru: str | None
    is_active: bool
    #: Where a map opens when this district is chosen (0079). **Advisory only** - the specification rejects
    #: deciding a route by district (§2) and Q88 projects a marked point onto a confirmed route instead. It is
    #: a camera position, never an input to matching, capacity or price. `None` for a district nobody has
    #: placed yet; the client then falls back to the region.
    center_lat: float | None
    center_lng: float | None
    #: Active stops of publicly visible corridors that sit in this district. Zero means the district can be
    #: named in a search, but no verified stop serves it yet - the client says so instead of promising a ride.
    stops_count: int

    @property
    def api_id(self) -> str:
        return district_api_id(self.public_id)


@dataclass(frozen=True, slots=True)
class CorridorDistrictInfo:
    """One district on a corridor, in travel order.

    ``on_confirmed_route`` is the whole honesty of this type. ``True`` means some confirmed route version of
    the corridor really stops in that district, so a listing there can be served without leaving the road the
    driver agreed to. ``False`` means the district merely owns a stop of the corridor while no confirmed route
    passes it yet - the catalogue knows the place, the road does not (spec 6.1: not every Tashkent -> Qarshi
    route goes through Chiroqchi).
    """

    district: DistrictInfo
    sequence: int
    stops_count: int
    on_confirmed_route: bool


_DISTRICT_SELECT = (
    "SELECT d.id, d.public_id, d.region_id, r.public_id AS region_public_id, r.code AS region_code, "
    "r.name_uz AS region_name_uz, d.name_uz, d.name_ru, d.is_active, d.center_lat, d.center_lng, "
    "(SELECT count(*) FROM corridor_stops cs JOIN service_corridors sc ON sc.id = cs.corridor_id "
    " WHERE cs.geo_district_id = d.id AND cs.is_active AND sc.rollout_state = ANY(:public_states)) AS stops_count "
    "FROM geo_districts d JOIN regions r ON r.id = d.region_id"
)


def _district_info(row: Any) -> DistrictInfo:  # noqa: ANN401 - Row
    return DistrictInfo(
        id=row.id,
        public_id=row.public_id,
        region_id=row.region_id,
        region_public_id=row.region_public_id,
        region_code=row.region_code,
        region_name_uz=row.region_name_uz,
        name_uz=row.name_uz,
        name_ru=row.name_ru,
        is_active=row.is_active,
        center_lat=float(row.center_lat) if row.center_lat is not None else None,
        center_lng=float(row.center_lng) if row.center_lng is not None else None,
        stops_count=int(row.stops_count or 0),
    )


def _public_states() -> list[str]:
    return [state.value for state in PUBLIC_ROLLOUT_STATES]


def list_districts(
    db: Session,
    *,
    region: RegionInfo | None = None,
    q: str | None = None,
    active_only: bool = True,
    limit: int = 200,
) -> list[DistrictInfo]:
    """G16: the district catalogue of a region, for the direction picker.

    Districts are operator data (``scripts/import_legacy_districts.py`` copies the verified legacy names);
    this never invents one, so an empty answer means "nobody has entered them yet", not "there are none".
    """
    clauses = []
    params: dict[str, Any] = {"public_states": _public_states(), "limit": max(1, min(int(limit), 500))}
    if region is not None:
        clauses.append("d.region_id = :region_id")
        params["region_id"] = region.id
    if active_only:
        clauses.append("d.is_active")
    term = (q or "").strip()
    if term:
        if len(term) < 2:
            return []
        clauses.append("(d.name_uz ILIKE :term ESCAPE '\\' OR d.name_ru ILIKE :term ESCAPE '\\')")
        params["term"] = f"%{_escape_like(term)}%"
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(text(f"{_DISTRICT_SELECT}{where} ORDER BY d.name_uz, d.id LIMIT :limit"), params).all()
    return [_district_info(row) for row in rows]


def districts_by_ids(db: Session, district_ids: Iterable[int]) -> dict[int, DistrictInfo]:
    """Districts by primary key - what a DTO needs to name a map point's advisory district (Q88)."""
    ids = [int(value) for value in district_ids if value]
    if not ids:
        return {}
    rows = db.execute(
        text(f"{_DISTRICT_SELECT} WHERE d.id = ANY(:ids)"),
        {"ids": ids, "public_states": _public_states()},
    ).all()
    return {row.id: _district_info(row) for row in rows}


def get_district_by_api_id(db: Session, api_id: str) -> DistrictInfo:
    public_id = parse_public_id(api_id, PublicIdPrefix.DISTRICT)
    row = db.execute(
        text(f"{_DISTRICT_SELECT} WHERE d.public_id = :u"),
        {"u": public_id, "public_states": _public_states()},
    ).first()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return _district_info(row)


_CORRIDOR_ROUTE_DISTRICTS_SQL = text(
    "SELECT rvs.route_version_id, rvs.seq, cs.geo_district_id AS district_id "
    "FROM route_version_stops rvs "
    "JOIN route_versions rv ON rv.id = rvs.route_version_id "
    "JOIN corridor_stops cs ON cs.id = rvs.stop_id "
    "WHERE rv.corridor_id = :corridor AND rv.status = 'confirmed' "
    "ORDER BY rvs.route_version_id, rvs.seq"
)

_CORRIDOR_STOP_DISTRICTS_SQL = text(
    "SELECT cs.geo_district_id AS district_id, min(cs.sequence_hint) AS seq, count(*) AS stops_count "
    "FROM corridor_stops cs WHERE cs.corridor_id = :corridor AND cs.is_active "
    "GROUP BY cs.geo_district_id ORDER BY seq, district_id"
)


def corridor_districts(db: Session, corridor: CorridorInfo) -> list[CorridorDistrictInfo]:
    """G17: the districts a corridor passes, in travel order - what "Toshkent -> Qarshi" really covers.

    Order comes from the **confirmed route versions** of the corridor: their stop sequence is the road the
    drivers of this corridor actually agreed to. Districts that only own a stop, with no confirmed route
    reaching them, are appended with ``on_confirmed_route=False`` rather than being dropped (the picker may
    still offer them) or silently promoted (the spec forbids assuming they are on the way).

    A district is placed at its earliest position across the confirmed routes, so two alternative roads give
    one ordered list instead of two conflicting ones.
    """
    earliest: dict[int, int] = {}
    for row in db.execute(_CORRIDOR_ROUTE_DISTRICTS_SQL, {"corridor": corridor.id}).all():
        district_id = int(row.district_id)
        position = int(row.seq)
        if district_id not in earliest or position < earliest[district_id]:
            earliest[district_id] = position

    stop_rows = db.execute(_CORRIDOR_STOP_DISTRICTS_SQL, {"corridor": corridor.id}).all()
    stop_counts = {int(row.district_id): int(row.stops_count) for row in stop_rows}
    hint_order = {int(row.district_id): int(row.seq or 0) for row in stop_rows}

    district_ids = list(dict.fromkeys([*earliest, *stop_counts]))
    if not district_ids:
        return []
    rows = db.execute(
        text(f"{_DISTRICT_SELECT} WHERE d.id = ANY(:ids)"),
        {"ids": district_ids, "public_states": _public_states()},
    ).all()
    infos = {row.id: _district_info(row) for row in rows}

    ordered = sorted(
        (did for did in district_ids if did in infos),
        # On-route districts first, in route order; the rest keep the operator's stop order.
        key=lambda did: (0, earliest[did]) if did in earliest else (1, hint_order.get(did, 0), did),
    )
    return [
        CorridorDistrictInfo(
            district=infos[did],
            sequence=index,
            stops_count=stop_counts.get(did, 0),
            on_confirmed_route=did in earliest,
        )
        for index, did in enumerate(ordered)
    ]
