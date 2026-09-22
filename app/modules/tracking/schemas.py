"""Tracking module DTOs (A6). Shared privacy-critical DTOs (points, booking/public tracking) are in ``app.contracts.dto``."""

from __future__ import annotations

from pydantic import Field, StrictInt

from app.contracts.dto import ContractModel, EmptyDTO, TrackingLastPointDTO, UtcDateTime
from app.contracts.enums import ClientPlatform, TrackingFreshness, TrackingGrantScope, TrackingSessionStatus


class TrackingSessionCreate(ContractModel):
    """K1 body. ``platform`` web is accepted but a browser is never a background tracker (§10.5)."""

    trip_id: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    platform: ClientPlatform
    app_version: str = Field(min_length=1, max_length=64)


class TrackingSessionDTO(ContractModel):
    """K1/K3. ``last_seq`` is null until the first accepted point."""

    id: str
    status: TrackingSessionStatus
    last_seq: int | None = None
    started_at: UtcDateTime
    ended_at: UtcDateTime | None = None
    recommended_interval_s: int


class TrackingGrantCreate(ContractModel):
    """K5 body; ``ttl_minutes`` between ``TRACKING_GRANT_MIN_TTL`` and ``TRACKING_GRANT_MAX_TTL`` (U4 pilot default)."""

    scope: TrackingGrantScope = TrackingGrantScope.RECIPIENT_LINK
    ttl_minutes: StrictInt


class TrackingGrantDTO(ContractModel):
    """K5. ``url`` carries the token and is shown exactly once: an idempotent replay returns ``url = null`` because the
    stored response never contains the token (only its hash is in the database, ADR-0018)."""

    id: str
    url: str | None = None
    valid_from: UtcDateTime
    expires_at: UtcDateTime


class TripTrackingAdminDTO(ContractModel):
    """K9 operator view (``ops.view``, audited). No "GPS active" flag - only the freshness of the last trusted point."""

    trip_id: str
    active_session: bool
    session_started_at: UtcDateTime | None = None
    freshness: TrackingFreshness
    last_point: TrackingLastPointDTO | None = None
