"""API v2 router for geo (G1-G11) and feature flags (F1-F4). Mounted by the integrator under ``/api/v2``.

* Commands G5, G6, G8, G10, F3 run through ``app.api.v2.web.run_command`` (``platform.run_idempotent``,
  savepoint pattern) inside ``platform.run_with_db_retry``. G9/G11 are versioned PATCHes.
* G5 never calls the router for a replay: it validates the key and asks A3's read-only
  ``platform.service.lookup_idempotent_response`` first; only an unused/expired/in-flight key proceeds to
  read -> end transaction -> router -> write (spec §15), and ``run_idempotent`` re-checks under the lock.
* Every route declares ``response_model=Envelope[...]``.
* Production (Q24/Q46): no routing provider, so G5 answers 503 and matching never returns detours;
  nothing here advertises detours as available in production.
* Price bands (Q42): G12 list and G14 history (``ops.view``), G13 upsert (``ops.corridor_manage``,
  Idempotency-Key, ``expected_version``, audited; Q53 warning ``CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR``).
* F1: ``GET /admin/geo/checks/q47`` (``ops.view``) lists corridors already violating Q47.
* Capabilities: staff capabilities from ``STAFF_ROLE_CAPABILITIES[users.role]`` plus
  ``identity.service.get_capabilities`` (marketplace, e.g. ``trip.create``).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v2.web import ERROR_RESPONSES, decode_id_cursor, encode_page_cursor, run_command, run_versioned
from app.contracts.dto import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, Envelope, PageMeta
from app.contracts.enums import STAFF_ROLE_CAPABILITIES, Capability, FeatureFlagKey, FlagScopeType, Role, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.idempotency import IDEMPOTENT_REPLAY_HEADER, validate_idempotency_key
from app.db.session import get_db
from app.models import User
from app.modules.geo import service
from app.modules.geo.config import build_routing_provider, get_geo_settings
from app.modules.geo.flags import CLIENT_VISIBLE_FLAGS
from app.modules.geo.geometry import encode_polyline
from app.modules.geo.routing.base import RoutingProvider
from app.modules.geo.schemas import (
    AdminStopDTO,
    CorridorDistrictDTO,
    DistrictDTO,
    PriceBandChangeDTO,
    Q47ViolationDTO,
    PriceBandDTO,
    PriceBandUpsert,
    CorridorAdminDTO,
    CorridorConfigDTO,
    CorridorCreate,
    CorridorDTO,
    CorridorPatch,
    DistrictRefDTO,
    EffectiveFlagsDTO,
    EffectiveFlagValuesDTO,
    FlagChangeDTO,
    FlagValueDTO,
    FlagValueUpsert,
    PointDTO,
    RegionDTO,
    RegionRefDTO,
    RoutePreviewRequest,
    RouteVersionDTO,
    RouteVersionStopDTO,
    StopCreate,
    StopDTO,
    StopPatch,
)
from app.modules.geo.types import LatLng
from app.modules.platform import service as platform_service
from app.utils.file_access import signed_file_url

router = APIRouter()

GEO_TAG = "Geo v2"
FLAGS_TAG = "Feature Flags v2"


# --- dependencies ------------------------------------------------------------------------------


def get_routing_provider(db: Session = Depends(get_db)) -> RoutingProvider:
    # Decision 24: no provider in production (settings OR DB marker).
    return build_routing_provider(production=platform_service.is_production(db))


def _identity_capabilities(db: Session, user_id: int) -> frozenset[Capability]:
    try:
        identity = importlib.import_module("app.modules.identity.service")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("app.modules.identity"):
            return frozenset()
        raise
    result = identity.get_capabilities(db, user_id)
    return frozenset(Capability(value) for value in getattr(result, "capabilities", result))


def resolve_capabilities(db: Session, user: User) -> frozenset[Capability]:
    caps: set[Capability] = set()
    if user.role in {role.value for role in Role}:
        caps |= STAFF_ROLE_CAPABILITIES.get(Role(user.role), frozenset())
    caps |= _identity_capabilities(db, user.id)
    return frozenset(caps)


class Actor:
    def __init__(self, user_id: int, role: str, capabilities: frozenset[Capability]) -> None:
        self.user_id = user_id
        self.role = role
        self.capabilities = capabilities

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN.value


def require_capability(capability: Capability) -> Callable[..., Actor]:
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Actor:
        caps = resolve_capabilities(db, user)
        if capability not in caps:
            code = ErrorCode.FORBIDDEN if capability.value.startswith(("ops.", "finance.", "staff.")) else ErrorCode.CAPABILITY_REQUIRED
            raise DomainError(code, details={"capability": capability.value})
        # ADR-0021: turning a service flag on is a step-up command (audit-only until two super_admins exist).
        from app.modules.identity import mfa

        mfa.require_step_up(db, user_id=user.id, capability=capability)
        return Actor(user.id, user.role, caps)

    return dependency


def _command(
    request: Request,
    db: Session,
    *,
    actor: Actor,
    idempotency_key: str | None,
    body: BaseModel | None,
    handler: Callable[[], BaseModel],
    success_status: int = 200,
    resource_type: str,
) -> JSONResponse:
    return platform_service.run_with_db_retry(
        db,
        lambda: run_command(
            request,
            db,
            actor_user_id=actor.user_id,
            idempotency_key=idempotency_key,
            body=body,
            handler=handler,
            success_status=success_status,
            resource_type=resource_type,
        ),
    )


def _route_template(request: Request) -> str:
    # Same template ``app.api.v2.web.run_command`` stores the idempotency record under.
    route = request.scope.get("route")
    return getattr(route, "path_format", None) or getattr(route, "path", None) or request.url.path


# --- mappers ---------------------------------------------------------------------------------------


def _stop_dto(stop: service.StopInfo) -> StopDTO:
    return StopDTO(
        id=stop.api_id,
        name_uz=stop.name_uz,
        name_ru=stop.name_ru,
        district=DistrictRefDTO(id=service.district_api_id(stop.district_public_id), name_uz=stop.district_name_uz),
        point=PointDTO(lat=stop.point.lat, lng=stop.point.lng),
        meeting_note=stop.meeting_note,
        is_active=stop.is_active,
    )


def _admin_stop_dto(stop: service.StopInfo) -> AdminStopDTO:
    return AdminStopDTO(
        **_stop_dto(stop).model_dump(),
        corridor_id=service.corridor_api_id(stop.corridor_public_id),
        meeting_photo_file_id=stop.meeting_photo_file_id,
        meeting_photo_url=signed_file_url(stop.meeting_photo_file_id),
        sequence_hint=stop.sequence_hint,
        version=stop.version,
    )


def _region_ref(region: service.RegionInfo) -> RegionRefDTO:
    return RegionRefDTO(id=region.api_id, code=region.code, name_uz=region.name_uz)


def _district_dto(district: service.DistrictInfo) -> DistrictDTO:
    return DistrictDTO(
        id=district.api_id,
        region=RegionRefDTO(
            id=service.region_api_id(district.region_public_id),
            code=district.region_code,
            name_uz=district.region_name_uz,
        ),
        name_uz=district.name_uz,
        name_ru=district.name_ru,
        is_active=district.is_active,
        center_lat=district.center_lat,
        center_lng=district.center_lng,
        stops_count=district.stops_count,
    )


def _corridor_dto(corridor: service.CorridorInfo, services: list[ServiceType], stops_count: int) -> CorridorDTO:
    return CorridorDTO(
        id=corridor.api_id,
        name=corridor.name,
        origin_region=_region_ref(corridor.origin_region),
        destination_region=_region_ref(corridor.destination_region),
        enabled_services=services,
        stops_count=stops_count,
    )


def _corridor_admin_dto(db: Session, corridor: service.CorridorInfo) -> CorridorAdminDTO:
    resolutions = service.resolve_flags(db, corridor_id=corridor.id, keys=[FeatureFlagKey.PASSENGER_ENABLED, FeatureFlagKey.PARCEL_ENABLED])
    services = [
        s for s, k in ((ServiceType.PASSENGER, FeatureFlagKey.PASSENGER_ENABLED), (ServiceType.PARCEL, FeatureFlagKey.PARCEL_ENABLED)) if resolutions[k].enabled
    ]
    base = _corridor_dto(corridor, services, service.count_active_stops(db, [corridor.id]).get(corridor.id, 0))
    return CorridorAdminDTO(
        **base.model_dump(),
        rollout_state=corridor.rollout_state,
        config_version=corridor.config.revision,
        config=CorridorConfigDTO(
            revision=corridor.config.revision,
            search_radius_m=corridor.config.search_radius_m,
            default_max_detour_minutes=corridor.config.default_max_detour_minutes,
            default_max_detour_m=corridor.config.default_max_detour_m,
        ),
        version=corridor.version,
        updated_at=corridor.updated_at,
    )


def _route_dto(route: service.RouteVersionInfo) -> RouteVersionDTO:
    return RouteVersionDTO(
        id=route.api_id,
        status=route.status,  # type: ignore[arg-type]
        stops=[
            RouteVersionStopDTO(
                stop_id=service.stop_api_id(s.stop_public_id),
                seq=s.seq,
                cumulative_distance_m=s.cumulative_distance_m,
                cumulative_duration_s=s.cumulative_duration_s,
            )
            for s in route.stops
        ],
        distance_m=route.distance_m,
        duration_s=route.duration_s,
        geometry_polyline=encode_polyline(route.geometry),
        provider=route.provider,
        provider_version=route.provider_version,
        is_estimate=route.is_estimate,
        attribution=route.attribution,
    )


def _flag_dto(info: service.FlagValueInfo, users: dict[int, str | None]) -> FlagValueDTO:
    return FlagValueDTO(
        id=info.api_id,
        flag_key=info.flag_key,
        scope_type=info.scope_type,
        scope_ref=info.scope_ref,
        enabled=info.enabled,
        approval_reference=info.approval_reference,
        version=info.version,
        updated_by=users.get(info.updated_by),
        updated_at=info.updated_at,
    )


# --- G1-G4: public catalogue ------------------------------------------------------------------------


@router.get("/regions", response_model=Envelope[list[RegionDTO]], tags=[GEO_TAG])
def list_regions(db: Session = Depends(get_db)) -> Envelope[list[RegionDTO]]:
    items = [
        RegionDTO(
            id=r.api_id,
            code=r.code,
            name_uz=r.name_uz,
            name_ru=r.name_ru,
            requires_district=r.requires_district,
            center_lat=r.center_lat,
            center_lng=r.center_lng,
        )
        for r in service.list_regions(db)
    ]
    return Envelope[list[RegionDTO]](data=items)


@router.get("/corridors", response_model=Envelope[list[CorridorDTO]], tags=[GEO_TAG])
def list_corridors(service_type: ServiceType | None = Query(default=None), db: Session = Depends(get_db)) -> Envelope[list[CorridorDTO]]:
    items = [_corridor_dto(c, services, count) for c, services, count in service.list_public_corridors(db, service_type=service_type)]
    return Envelope[list[CorridorDTO]](data=items)


@router.get("/corridors/{corridor_id}/stops", response_model=Envelope[list[StopDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def list_corridor_stops(corridor_id: str = Path(max_length=64), db: Session = Depends(get_db)) -> Envelope[list[StopDTO]]:
    corridor = service.get_corridor_by_api_id(db, corridor_id)
    if corridor.rollout_state not in service.PUBLIC_ROLLOUT_STATES:
        raise DomainError(ErrorCode.NOT_FOUND)
    return Envelope[list[StopDTO]](data=[_stop_dto(s) for s in service.list_corridor_stops(db, corridor)])


@router.get("/districts", response_model=Envelope[list[DistrictDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def list_districts(
    region_id: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[DistrictDTO]]:
    """G16: the district catalogue, the second step of the direction picker (wave 10).

    An unknown region answers with an empty list rather than 404: the picker is a catalogue, not a resource.
    """
    region = None
    if region_id is not None:
        try:
            region = service.get_region_by_api_id(db, region_id)
        except DomainError:
            return Envelope[list[DistrictDTO]](data=[])
    districts = service.list_districts(db, region=region, q=q, limit=limit)
    return Envelope[list[DistrictDTO]](data=[_district_dto(d) for d in districts])


@router.get(
    "/corridors/{corridor_id}/districts",
    response_model=Envelope[list[CorridorDistrictDTO]],
    responses=ERROR_RESPONSES,
    tags=[GEO_TAG],
)
def list_corridor_districts(
    corridor_id: str = Path(max_length=64), db: Session = Depends(get_db)
) -> Envelope[list[CorridorDistrictDTO]]:
    """G17: which districts this direction really passes, in travel order (wave 10).

    This is what "Toshkent -> Qarshi" covers: the districts of the stops on the corridor's confirmed routes.
    Districts whose stops no confirmed route reaches are still listed, with ``on_confirmed_route=false``, so
    the client can offer them without claiming they are on the way (spec 6.1, 6.5).
    """
    corridor = service.get_corridor_by_api_id(db, corridor_id)
    if corridor.rollout_state not in service.PUBLIC_ROLLOUT_STATES:
        raise DomainError(ErrorCode.NOT_FOUND)
    items = [
        CorridorDistrictDTO(
            district=_district_dto(entry.district),
            sequence=entry.sequence,
            stops_count=entry.stops_count,
            on_confirmed_route=entry.on_confirmed_route,
        )
        for entry in service.corridor_districts(db, corridor)
    ]
    return Envelope[list[CorridorDistrictDTO]](data=items)


@router.get(
    "/corridors/{corridor_id}/routes",
    response_model=Envelope[list[RouteVersionDTO]],
    responses=ERROR_RESPONSES,
    tags=[GEO_TAG],
)
def list_corridor_routes(
    corridor_id: str = Path(max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Envelope[list[RouteVersionDTO]]:
    """G18: confirmed route versions of this corridor, newest first.

    A driver plans a trip on one of these. ``POST /routes/preview`` builds a *new* road and therefore needs the
    routing provider, which stays off until the legal review (Q24/Q46); reading roads that were confirmed
    earlier needs no provider, so the supply side keeps working in that configuration.
    """
    corridor = service.get_corridor_by_api_id(db, corridor_id)
    if corridor.rollout_state not in service.PUBLIC_ROLLOUT_STATES:
        raise DomainError(ErrorCode.NOT_FOUND)
    return Envelope[list[RouteVersionDTO]](
        data=[_route_dto(route) for route in service.list_corridor_routes(db, corridor, limit=limit)]
    )


@router.get("/stops/search", response_model=Envelope[list[StopDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def search_stops(
    q: str = Query(min_length=2, max_length=80),
    region_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Envelope[list[StopDTO]]:
    region = None
    if region_id is not None:
        try:
            region = service.get_region_by_api_id(db, region_id)
        except DomainError:
            return Envelope[list[StopDTO]](data=[])
    return Envelope[list[StopDTO]](data=[_stop_dto(s) for s in service.search_stops(db, q, region=region, limit=limit)])


# --- G5-G6: route versions ---------------------------------------------------------------------------


@router.post(
    "/routes/preview", response_model=Envelope[RouteVersionDTO], status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES, tags=[GEO_TAG]
)
def preview_route(
    body: RoutePreviewRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_capability(Capability.TRIP_CREATE)),
    provider: RoutingProvider = Depends(get_routing_provider),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run(handler: Callable[[], BaseModel]) -> JSONResponse:
        return _command(
            request, db, actor=actor, idempotency_key=idempotency_key, body=body, handler=handler,
            success_status=status.HTTP_201_CREATED, resource_type="route_version",
        )

    # 1. Replay without the router: read-only lookup (A3). A different body raises IDEMPOTENCY_KEY_REUSED;
    #    an unused, expired or in-flight key returns None and run_idempotent re-checks under the lock.
    validate_idempotency_key(idempotency_key)
    try:
        stored = platform_service.lookup_idempotent_response(
            db,
            actor_user_id=actor.user_id,
            method=request.method,
            route_template=_route_template(request),
            idempotency_key=idempotency_key,
            body=body.model_dump(mode="json"),
            path_params=dict(request.path_params),
        )
    finally:
        db.rollback()  # read-only; nothing to keep
    if stored is not None:
        return JSONResponse(status_code=stored.status_code, content=stored.body, headers={IDEMPOTENT_REPLAY_HEADER: "true"})

    # 2. Read-only phase; a domain 4xx is stored for replay like any other command.
    try:
        plan = service.prepare_route_preview(db, provider, stop_api_ids=body.stop_ids, departure_at=body.departure_at)
    except DomainError as exc:
        db.rollback()
        error = exc

        def replay_error() -> BaseModel:
            raise error

        return run(replay_error)
    db.rollback()  # no transaction may be open during the router call (spec §15)

    # 3. Router (outside any transaction); outage -> 503, never stored.
    result, from_cache = service.fetch_route_outside_transaction(db, provider, plan)
    ttl = get_geo_settings().routing_cache_ttl_s

    # 4. Write phase under the idempotency record.
    return run(
        lambda: _route_dto(
            service.store_route_preview(db, plan, result, actor_user_id=actor.user_id, from_cache=from_cache, cache_ttl_s=ttl)
        )
    )


@router.post("/routes/{route_version_id}/confirm", response_model=Envelope[RouteVersionDTO], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def confirm_route(
    request: Request,
    route_version_id: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_capability(Capability.TRIP_CREATE)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    return _command(
        request, db, actor=actor, idempotency_key=idempotency_key, body=None,
        handler=lambda: _route_dto(service.confirm_route_version(db, actor_user_id=actor.user_id, route_version_api_id=route_version_id)),
        resource_type="route_version",
    )


# --- G7-G11: admin corridors and stops ------------------------------------------------------------------


@router.get("/admin/corridors", response_model=Envelope[list[CorridorAdminDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def admin_list_corridors(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[CorridorAdminDTO]]:
    scope = "GET /admin/corridors"
    items, next_after = service.list_admin_corridors(db, after_id=decode_id_cursor(cursor, scope), limit=limit)
    next_cursor = encode_page_cursor([next_after], scope) if next_after is not None else None
    return Envelope[list[CorridorAdminDTO]](
        data=[_corridor_admin_dto(db, c) for c in items],
        meta=PageMeta(next_cursor=next_cursor, limit=limit),
    )


@router.post(
    "/admin/corridors", response_model=Envelope[CorridorAdminDTO], status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES, tags=[GEO_TAG]
)
def admin_create_corridor(
    body: CorridorCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_capability(Capability.OPS_CORRIDOR_MANAGE)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def handler() -> CorridorAdminDTO:
        corridor = service.create_corridor(
            db,
            actor_user_id=actor.user_id,
            name=body.name,
            origin_region_api_id=body.origin_region_id,
            destination_region_api_id=body.destination_region_id,
            search_radius_m=body.search_radius_m,
            default_max_detour_minutes=body.default_max_detour_minutes,
            default_max_detour_m=body.default_max_detour_m,
        )
        return _corridor_admin_dto(db, corridor)

    return _command(
        request, db, actor=actor, idempotency_key=idempotency_key, body=body, handler=handler,
        success_status=status.HTTP_201_CREATED, resource_type="service_corridor",
    )


@router.patch("/admin/corridors/{corridor_id}", response_model=Envelope[CorridorAdminDTO], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def admin_patch_corridor(
    body: CorridorPatch,
    corridor_id: str = Path(max_length=64),
    actor: Actor = Depends(require_capability(Capability.OPS_CORRIDOR_MANAGE)),
    db: Session = Depends(get_db),
) -> Envelope[CorridorAdminDTO]:
    changes = {name: getattr(body, name) for name in body.model_fields_set if name not in ("expected_version", "reason")}

    def handler() -> CorridorAdminDTO:
        corridor = service.patch_corridor(
            db, actor_user_id=actor.user_id, corridor_api_id=corridor_id, expected_version=body.expected_version, reason=body.reason, changes=changes
        )
        return _corridor_admin_dto(db, corridor)

    return Envelope[CorridorAdminDTO](data=run_versioned(db, handler))


@router.get(
    "/admin/corridors/{corridor_id}/stops", response_model=Envelope[list[AdminStopDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG]
)
def admin_list_corridor_stops(
    corridor_id: str = Path(max_length=64),
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[AdminStopDTO]]:
    """Every stop of a corridor for staff - inactive ones and draft corridors included, with the ``version`` a
    ``PATCH /admin/stops/{id}`` needs and the Q27 evidence. The public list shows only active stops of open corridors."""
    corridor = service.get_corridor_by_api_id(db, corridor_id)
    return Envelope[list[AdminStopDTO]](
        data=[_admin_stop_dto(stop) for stop in service.list_corridor_stops(db, corridor, active_only=False)]
    )


@router.post(
    "/admin/corridors/{corridor_id}/stops",
    response_model=Envelope[AdminStopDTO],
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    tags=[GEO_TAG],
)
def admin_create_stop(
    body: StopCreate,
    request: Request,
    corridor_id: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_capability(Capability.OPS_CORRIDOR_MANAGE)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def handler() -> AdminStopDTO:
        stop = service.create_stop(
            db,
            actor_user_id=actor.user_id,
            corridor_api_id=corridor_id,
            name_uz=body.name_uz,
            name_ru=body.name_ru,
            district_api_id=body.district_id,
            point=LatLng(body.point.lat, body.point.lng),
            meeting_note=body.meeting_note,
            meeting_photo_file_id=body.meeting_photo_file_id,
            sequence_hint=body.sequence_hint,
            is_active=body.is_active,
        )
        return _admin_stop_dto(stop)

    return _command(
        request, db, actor=actor, idempotency_key=idempotency_key, body=body, handler=handler,
        success_status=status.HTTP_201_CREATED, resource_type="corridor_stop",
    )


@router.patch("/admin/stops/{stop_id}", response_model=Envelope[AdminStopDTO], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def admin_patch_stop(
    body: StopPatch,
    stop_id: str = Path(max_length=64),
    actor: Actor = Depends(require_capability(Capability.OPS_CORRIDOR_MANAGE)),
    db: Session = Depends(get_db),
) -> Envelope[AdminStopDTO]:
    changes: dict[str, Any] = {}
    for name in body.model_fields_set - {"expected_version"}:
        value = getattr(body, name)
        changes[name] = LatLng(value.lat, value.lng) if name == "point" else value

    def handler() -> AdminStopDTO:
        return _admin_stop_dto(
            service.patch_stop(db, actor_user_id=actor.user_id, stop_api_id=stop_id, expected_version=body.expected_version, changes=changes)
        )

    return Envelope[AdminStopDTO](data=run_versioned(db, handler))


# --- F1-F4: feature flags ---------------------------------------------------------------------------------


@router.get("/feature-flags/effective", response_model=Envelope[EffectiveFlagsDTO], responses=ERROR_RESPONSES, tags=[FLAGS_TAG])
def effective_flags(corridor_id: str | None = Query(default=None, max_length=64), db: Session = Depends(get_db)) -> Envelope[EffectiveFlagsDTO]:
    internal_id = service.get_corridor_by_api_id(db, corridor_id).id if corridor_id is not None else None
    resolved = service.resolve_flags(db, corridor_id=internal_id, keys=CLIENT_VISIBLE_FLAGS)
    values = EffectiveFlagValuesDTO(**{key.value: resolved[key].enabled for key in CLIENT_VISIBLE_FLAGS})
    return Envelope[EffectiveFlagsDTO](data=EffectiveFlagsDTO(corridor_id=corridor_id, flags=values))


@router.get("/admin/feature-flags", response_model=Envelope[list[FlagValueDTO]], responses=ERROR_RESPONSES, tags=[FLAGS_TAG])
def admin_list_flags(
    flag_key: FeatureFlagKey | None = Query(default=None),
    scope_type: FlagScopeType | None = Query(default=None),
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[FlagValueDTO]]:
    items = service.list_flag_values(db, flag_key=flag_key, scope_type=scope_type)
    users = service.user_api_ids(db, [i.updated_by for i in items])
    return Envelope[list[FlagValueDTO]](data=[_flag_dto(i, users) for i in items])


@router.put(
    "/admin/feature-flags/{flag_key}/scopes/{scope_type}/{scope_ref}",
    response_model=Envelope[FlagValueDTO],
    responses=ERROR_RESPONSES,
    tags=[FLAGS_TAG],
)
def admin_set_flag(
    body: FlagValueUpsert,
    request: Request,
    flag_key: FeatureFlagKey,
    scope_type: FlagScopeType,
    scope_ref: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_capability(Capability.OPS_FEATURE_FLAG_MANAGE)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def handler() -> FlagValueDTO:
        info = service.set_flag_value(
            db,
            actor_user_id=actor.user_id,
            actor_capabilities=actor.capabilities,
            actor_is_super_admin=actor.is_super_admin,
            flag_key=flag_key,
            scope_type=scope_type,
            scope_ref=scope_ref,
            enabled=body.enabled,
            reason=body.reason,
            approval_reference=body.approval_reference,
            expected_version=body.expected_version,
        )
        return _flag_dto(info, service.user_api_ids(db, [info.updated_by]))

    return _command(
        request, db, actor=actor, idempotency_key=idempotency_key, body=body, handler=handler, resource_type="feature_flag_value"
    )


@router.get("/admin/feature-flags/{flag_key}/history", response_model=Envelope[list[FlagChangeDTO]], responses=ERROR_RESPONSES, tags=[FLAGS_TAG])
def admin_flag_history(
    flag_key: FeatureFlagKey,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[FlagChangeDTO]]:
    scope = f"GET /admin/feature-flags/{flag_key.value}/history"
    items, next_after = service.list_flag_history(db, flag_key=flag_key, after_id=decode_id_cursor(cursor, scope), limit=limit)
    users = service.user_api_ids(db, [i.actor_user_id for i in items])
    data = [
        FlagChangeDTO(
            scope_type=i.scope_type,
            scope_ref=i.scope_ref,
            version=i.value_version,
            old_enabled=i.old_enabled,
            new_enabled=i.new_enabled,
            actor=users.get(i.actor_user_id),
            reason=i.reason,
            approval_reference=i.approval_reference,
            changed_at=i.changed_at,
        )
        for i in items
    ]
    next_cursor = encode_page_cursor([next_after], scope) if next_after is not None else None
    return Envelope[list[FlagChangeDTO]](data=data, meta=PageMeta(next_cursor=next_cursor, limit=limit))


# --- G12-G14: corridor price bands (Q42) -----------------------------------------------------------


def _price_band_dto(info: service.PriceBandInfo, users: dict[int, str | None]) -> PriceBandDTO:
    return PriceBandDTO(
        corridor_id=service.corridor_api_id(info.corridor_public_id),
        service_type=info.service_type,
        price_basis=info.price_basis,
        origin_stop_id=service.stop_api_id(info.origin_stop_public_id) if info.origin_stop_public_id else None,
        destination_stop_id=service.stop_api_id(info.destination_stop_public_id) if info.destination_stop_public_id else None,
        floor_minor=info.floor_minor,
        ceiling_minor=info.ceiling_minor,
        currency=info.currency,
        is_active=info.is_active,
        enforced=info.enforced,
        version=info.version,
        reason=info.reason,
        updated_by=users.get(info.updated_by),
        updated_at=info.updated_at,
    )


@router.get("/admin/corridors/{corridor_id}/price-bands", response_model=Envelope[list[PriceBandDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def admin_list_price_bands(
    corridor_id: str = Path(max_length=64),
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[PriceBandDTO]]:
    corridor = service.get_corridor_by_api_id(db, corridor_id)
    items = service.list_price_bands(db, corridor)
    users = service.user_api_ids(db, [i.updated_by for i in items])
    return Envelope[list[PriceBandDTO]](data=[_price_band_dto(i, users) for i in items])


@router.get(
    "/admin/corridors/{corridor_id}/price-bands/history", response_model=Envelope[list[PriceBandChangeDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG]
)
def admin_price_band_history(
    corridor_id: str = Path(max_length=64),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[PriceBandChangeDTO]]:
    corridor = service.get_corridor_by_api_id(db, corridor_id)
    scope = f"GET /admin/corridors/{corridor.api_id}/price-bands/history"
    items, next_after = service.list_price_band_history(db, corridor=corridor, after_id=decode_id_cursor(cursor, scope), limit=limit)
    users = service.user_api_ids(db, [i.actor_user_id for i in items])
    data = [
        PriceBandChangeDTO(
            service_type=i.service_type,
            origin_stop_id=service.stop_api_id(i.origin_stop_public_id) if i.origin_stop_public_id else None,
            destination_stop_id=service.stop_api_id(i.destination_stop_public_id) if i.destination_stop_public_id else None,
            version=i.band_version,
            old_floor_minor=i.old_floor_minor,
            old_ceiling_minor=i.old_ceiling_minor,
            old_is_active=i.old_is_active,
            new_floor_minor=i.new_floor_minor,
            new_ceiling_minor=i.new_ceiling_minor,
            new_is_active=i.new_is_active,
            actor=users.get(i.actor_user_id),
            reason=i.reason,
            changed_at=i.changed_at,
        )
        for i in items
    ]
    next_cursor = encode_page_cursor([next_after], scope) if next_after is not None else None
    return Envelope[list[PriceBandChangeDTO]](data=data, meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.put(
    "/admin/corridors/{corridor_id}/price-bands/{service_type}", response_model=Envelope[PriceBandDTO], responses=ERROR_RESPONSES, tags=[GEO_TAG]
)
def admin_set_price_band(
    body: PriceBandUpsert,
    request: Request,
    service_type: ServiceType,
    corridor_id: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_capability(Capability.OPS_CORRIDOR_MANAGE)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def handler() -> tuple[PriceBandDTO, list[dict[str, Any]]]:
        info = service.set_price_band(
            db,
            actor_user_id=actor.user_id,
            corridor_api_id=corridor_id,
            service_type=service_type,
            origin_stop_api_id=body.origin_stop_id,
            destination_stop_api_id=body.destination_stop_id,
            floor_minor=body.floor_minor,
            ceiling_minor=body.ceiling_minor,
            is_active=body.is_active,
            enforced=body.enforced,
            reason=body.reason,
            expected_version=body.expected_version,
        )
        warnings = [
            {**warning, "message": PRICE_BAND_WARNING_MESSAGE}
            for warning in service.price_band_warnings(db, corridor_id=info.corridor_id, service_type=info.service_type)
        ]
        return _price_band_dto(info, service.user_api_ids(db, [info.updated_by])), warnings

    return _command(
        request, db, actor=actor, idempotency_key=idempotency_key, body=body, handler=handler, resource_type="corridor_price_band"
    )


PRICE_BAND_WARNING_MESSAGE = (
    "The corridor-wide floor is above the lowest segment floor. Corridor-wide bands are loose safety limits; "
    "exact segment bands set real prices (Q53)."
)


@router.get("/admin/geo/checks/q47", response_model=Envelope[list[Q47ViolationDTO]], responses=ERROR_RESPONSES, tags=[GEO_TAG])
def admin_q47_check(
    _actor: Actor = Depends(require_capability(Capability.OPS_VIEW)),
    db: Session = Depends(get_db),
) -> Envelope[list[Q47ViolationDTO]]:
    items = [Q47ViolationDTO(**violation.as_dict()) for violation in service.find_q47_violations(db)]
    return Envelope[list[Q47ViolationDTO]](data=items)
