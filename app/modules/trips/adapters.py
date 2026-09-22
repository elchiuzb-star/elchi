"""Default geo adapter for the trips/marketplace ports over ``app.modules.geo.service`` (A2)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.modules.trips.ports import RouteStopRef, RouteVersionRef, StopRef


def _stop(info) -> StopRef:  # noqa: ANN001 - geo.service.StopInfo
    return StopRef(
        id=info.id,
        public_id=info.api_id,
        corridor_id=info.corridor_id,
        name_uz=info.name_uz,
        name_ru=info.name_ru,
        is_active=info.is_active,
    )


def _route(info) -> RouteVersionRef:  # noqa: ANN001 - geo.service.RouteVersionInfo
    return RouteVersionRef(
        id=info.id,
        public_id=info.api_id,
        status=str(getattr(info.status, "value", info.status)),
        stops=tuple(
            RouteStopRef(stop.seq, stop.stop_id, stop.cumulative_distance_m, stop.cumulative_duration_s)
            for stop in info.stops
        ),
    )


class GeoServiceAdapter:
    """Implements ``TripsGeoPort`` and ``MarketplaceGeoPort``."""

    def stops_by_public_ids(self, session: Session, public_ids: Sequence[str]) -> dict[str, StopRef]:
        from app.modules.geo import service as geo_service

        return {key: _stop(info) for key, info in geo_service.get_stops_by_api_ids(session, public_ids).items()}

    def stops_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, StopRef]:
        from app.modules.geo import service as geo_service

        return {key: _stop(info) for key, info in geo_service.get_stops(session, ids).items()}

    def corridors_by_ids(self, session: Session, ids: Sequence[int]):  # noqa: ANN201 - dict[int, CorridorRef]
        from app.modules.geo import service as geo_service
        from app.modules.marketplace.ports import CorridorRef

        return {
            key: CorridorRef(info.id, info.api_id, str(getattr(info.rollout_state, "value", info.rollout_state)))
            for key, info in geo_service.get_corridors(session, ids).items()
        }

    def route_version_by_public_id(self, session: Session, public_id: str) -> RouteVersionRef | None:
        from app.modules.geo import service as geo_service

        try:
            return _route(geo_service.get_route_version_by_api_id(session, public_id))
        except DomainError as exc:
            if exc.code is ErrorCode.NOT_FOUND:
                return None
            raise

    def route_versions_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, RouteVersionRef]:
        from app.modules.geo import service as geo_service

        result: dict[int, RouteVersionRef] = {}
        for route_id in sorted(set(ids)):
            try:
                result[route_id] = _route(geo_service.get_route_version(session, route_id))
            except DomainError as exc:
                if exc.code is not ErrorCode.NOT_FOUND:
                    raise
        return result
