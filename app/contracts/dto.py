"""Pydantic v2 base DTOs for API v2 (ADR-0005).

Envelope decision: v2 keeps the v1 shape ``{success, data, message}`` /
``{success: false, error: {...}}`` so existing client HTTP helpers keep working;
v2 adds optional ``meta`` for pagination. HTTP status is authoritative.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.contracts.communications import CHAT_TEXT_MAX_LENGTH
from app.contracts.enums import (
    ActorSide,
    ChatModerationStatus,
    ChatThreadKind,
    ClientPlatform,
    Currency,
    KpiMetric,
    ListingKind,
    MatchReason,
    MatchType,
    OpsQueue,
    PriceBasis,
    QuickReplyCode,
    ReputationLabel,
    ServiceType,
    ShareLinkChannel,
    TrackingFreshness,
    TrackingPointRejectReason,
    TrackingSessionStatus,
    TrackingWindowReason,
    VehicleClass,
)
from app.contracts.feed import MATCH_SCOPE_CONFIRMED_STOPS
from app.contracts.operations import (
    SHARE_LINK_DEFAULT_TTL_HOURS,
    SHARE_LINK_MAX_TTL_HOURS,
    SHARE_LINK_MIN_TTL_HOURS,
)
from app.contracts.tracking import MAX_ACCURACY_M, MAX_SPEED_MPS_INPUT, TRACKING_SUBJECT_LABEL_KEY

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

T = TypeVar("T")

# Use for every v2 datetime field: naive values fail validation.
UtcDateTime = AwareDatetime


class ContractModel(BaseModel):
    """Base for request/response DTOs: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)


class MoneyDTO(ContractModel):
    amount_minor: StrictInt = Field(ge=0, description="Integer minor units; UZS: 1 so'm = 100 tiyin.")
    currency: Currency = Currency.UZS


class MediaRefDTO(ContractModel):
    """One private upload a viewer is allowed to render.

    The bucket is never public: ``url`` is a short-lived signed link (``app.utils.file_access``) and it is minted
    only inside a response that was already authorized for this viewer. ``file_id`` is the stable storage key -
    useful for caching and support, worthless on its own, because the download endpoint verifies the signature
    rather than the key. When the link expires the client re-reads the resource that carried it.
    """

    file_id: str = Field(max_length=255, description="Opaque storage key; grants no access by itself.")
    url: str = Field(max_length=2048, description="Short-lived signed URL.")
    expires_at: AwareDatetime
    content_type: str = Field(max_length=100)


class PageQuery(ContractModel):
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
    cursor: str | None = Field(default=None, max_length=512)


class PageMeta(ContractModel):
    next_cursor: str | None = None
    limit: int


class VersionedCommand(ContractModel):
    """Commands on versioned aggregates carry optimistic concurrency."""

    expected_version: StrictInt = Field(ge=1)


class ErrorBody(ContractModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorEnvelope(ContractModel):
    success: Literal[False] = False
    error: ErrorBody


class ApiWarning(ContractModel):
    """Non-fatal outcome of a successful command (``errors.WarningCode``), e.g. masked contact info (Q43)."""

    code: str
    message: str
    field: str | None = None
    details: dict[str, Any] | None = None


class Envelope(ContractModel, Generic[T]):
    success: Literal[True] = True
    data: T
    message: str | None = None
    meta: PageMeta | None = None
    # Wave 1.6, additive: absent/null when there is nothing to report.
    warnings: list[ApiWarning] | None = None


class BookingVehicleDisclosureDTO(ContractModel):
    """Vehicle shown to a booking participant after accept (wave 2.1, Q64; ``app.contracts.disclosure``).

    Before accept only ``vehicle_class`` + ``seat_capacity`` exist (Q43, ``TripPublicDTO``). After accept: masked
    plate + make/model + colour. ``plate_number`` (full) is ``null`` until ``disclosure.full_plate_visible`` is
    true (trip ``boarding`` or <= 30 min before the pickup); ``plate_number_visible_from`` tells the client when.
    Staff views may always carry the full plate (audited by the owner module).
    """

    vehicle_class: VehicleClass
    seat_capacity: StrictInt = Field(ge=1)
    make_model: str
    color: str
    plate_masked: str
    plate_number: str | None = None
    plate_number_visible_from: UtcDateTime | None = None


# --- wave 3 (16.09.2026): privacy-critical shared DTOs (A6 tracking, A7 chat/events) -------------------------------


class TrackingPointIn(ContractModel):
    """One GPS point of ``POST /tracking/sessions/{id}/points:batch`` (K2, §10.3). Units are integers except degrees."""

    seq: StrictInt = Field(ge=0)
    captured_at: UtcDateTime
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: StrictInt = Field(ge=0, le=MAX_ACCURACY_M)
    speed_mps: StrictInt | None = Field(default=None, ge=0, le=MAX_SPEED_MPS_INPUT)
    heading_deg: StrictInt | None = Field(default=None, ge=0, le=359)
    battery_pct: StrictInt | None = Field(default=None, ge=0, le=100)
    is_mock: StrictBool = False


class PointsBatchIn(ContractModel):
    """K2 body. More than ``tracking.MAX_POINTS_PER_BATCH`` points -> 400 TRACKING_BATCH_TOO_LARGE (service check,
    deliberately not a schema limit so the dedicated code is returned)."""

    points: list[TrackingPointIn] = Field(min_length=1)


class PointRejectionDTO(ContractModel):
    seq: StrictInt
    reason: TrackingPointRejectReason


class PointsBatchAck(ContractModel):
    """Returned only after the DB commit (§10.4)."""

    accepted_seqs: list[int]
    duplicate_seqs: list[int]
    rejected: list[PointRejectionDTO]
    session_status: TrackingSessionStatus


class TrackingLastPointDTO(ContractModel):
    lat: float
    lng: float
    accuracy_m: int
    low_accuracy: bool
    captured_at: UtcDateTime
    received_at: UtcDateTime


class TrackingWindowDTO(ContractModel):
    is_open: bool
    reason: TrackingWindowReason
    opens_at: UtcDateTime | None = None


class BookingTrackingDTO(ContractModel):
    """K4. No phone, name, plate or other booking's data; no "GPS active" flag - only freshness of the last trusted
    point (§10.4-§10.5, AC32). ``last_point`` is null while the window is closed."""

    booking_id: str
    window: TrackingWindowDTO
    freshness: TrackingFreshness
    last_point: TrackingLastPointDTO | None = None
    driver_arrived_at: UtcDateTime | None = None
    eta_window_start: UtcDateTime | None = None
    eta_window_end: UtcDateTime | None = None
    eta_is_estimate: bool = True
    subject_label: str = TRACKING_SUBJECT_LABEL_KEY


class PublicTrackingDTO(ContractModel):
    """K7 recipient link (token). No personal data; served with ``Referrer-Policy: no-referrer``."""

    freshness: TrackingFreshness
    last_point: TrackingLastPointDTO | None = None
    status_label: str
    subject_label: str = TRACKING_SUBJECT_LABEL_KEY


class ChatMessageCreate(ContractModel):
    """N7 body. Text is filtered (Q43, proof codes masked Q65); a quick reply never changes the agreement (§16)."""

    text: str | None = Field(default=None, max_length=CHAT_TEXT_MAX_LENGTH)
    quick_reply_code: QuickReplyCode | None = None
    attachment_file_id: str | None = None  # not accepted in wave 3 (communications.CHAT_ATTACHMENTS_ENABLED)

    @model_validator(mode="after")
    def _text_or_quick_reply(self) -> ChatMessageCreate:
        if not self.text and self.quick_reply_code is None:
            raise ValueError("text or quick_reply_code is required")
        return self


class ChatMessageDTO(ContractModel):
    """N6/N7. Author is a side, never a user id, name or phone (Q43); ``text`` is the stored masked text."""

    id: str
    author_side: ActorSide
    is_mine: bool
    text: str | None = None
    quick_reply_code: QuickReplyCode | None = None
    moderation_status: ChatModerationStatus = ChatModerationStatus.VISIBLE
    created_at: UtcDateTime


class ChatThreadDTO(ContractModel):
    """N6. What the chat screen needs *before* it draws a composer.

    Without this the client cannot tell "you may write" from "this conversation is over": it shows an input,
    the person types, and the send comes back 409 CHAT_CLOSED - which reads as a bug in the app rather than
    the rule that a finished trip stops being a place to negotiate.

    ``writable_until`` is null while the booking is still running (nothing is counting down yet) and also
    once it has passed; ``writable`` is the answer either way, computed by ``communications.chat_writable``.
    """

    kind: ChatThreadKind
    writable: bool
    writable_until: UtcDateTime | None = Field(
        default=None,
        description="When a terminal booking's chat stops accepting messages; null when nothing is counting.",
    )
    message_count: int = 0


class EventDTO(ContractModel):
    """N1 ``GET /events``. ``payload`` is ``events.payload_for_audience`` of the caller's audience (N2, Q16)."""

    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: StrictInt = Field(ge=1)
    occurred_at: UtcDateTime
    payload: dict[str, Any]


# --- wave 3 integration: A7 communications DTOs. Single definition: app/modules/communications/schemas.py re-exports
# these classes (wave 3.1) and defines no copies; tests/contracts/test_wave3_integration.py checks the identity. ---

PUSH_TOKEN_MAX_LENGTH = 4096
REASON_MAX_LENGTH = 500


class PushTokenRegister(ContractModel):
    """N2. The raw token/subscription is hashed and never stored or returned (Q82: in-app only until a provider ADR)."""

    platform: ClientPlatform
    token_or_subscription: str = Field(min_length=16, max_length=PUSH_TOKEN_MAX_LENGTH)
    app_version: str | None = Field(default=None, max_length=32)


class DeviceDTO(ContractModel):
    id: str
    platform: ClientPlatform
    created_at: UtcDateTime


class NotificationDTO(ContractModel):
    """N4/N5 in-app inbox row; ``params`` is the recipient's audience copy of the event payload (N2, Q16)."""

    id: str
    type: str
    title_key: str
    body_key: str
    params: dict[str, Any]
    is_read: bool
    created_at: UtcDateTime
    link: str | None = None


class OutboxEventAdminDTO(ContractModel):
    """N8/N9 operator queue. ``payload`` is the STAFF copy."""

    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: StrictInt
    occurred_at: UtcDateTime
    payload: dict[str, Any]
    attempts: StrictInt
    next_attempt_at: UtcDateTime
    dispatched_at: UtcDateTime | None = None
    dead_lettered_at: UtcDateTime | None = None
    last_error: str | None = None


class OutboxRetryRequest(ContractModel):
    reason: str = Field(min_length=3, max_length=REASON_MAX_LENGTH)


class ChatMessageAdminDTO(ContractModel):
    """N10 staff view (audited): adds the author's public user id and filter category counts."""

    id: str
    author_side: ActorSide
    author_user_id: str
    text: str | None = None
    quick_reply_code: QuickReplyCode | None = None
    contact_filter_categories: dict[str, int]
    moderation_status: ChatModerationStatus
    moderated_at: UtcDateTime | None = None
    created_at: UtcDateTime


class ChatHideRequest(ContractModel):
    reason: str = Field(min_length=3, max_length=REASON_MAX_LENGTH)


# --- wave 3 integration: A5 feed DTOs without A1 module dependencies (copied from marketplace/feed/schemas.py;
# FeedItemDTO / MatchDTO stay module-owned because they embed A1's ListingPublicDTO) ---------------------------------


class FeedMatchDTO(ContractModel):
    match_type: MatchType
    reasons: list[MatchReason]
    pickup_eta_window_start: UtcDateTime | None = None
    pickup_eta_window_end: UtcDateTime | None = None
    detour_minutes: int | None = Field(default=None, description="Never set in production (Q46).")
    is_estimate: bool = True


class FeedReputationDTO(ContractModel):
    label: ReputationLabel
    rating_count: int
    average_rating: float | None = Field(default=None, description="Shown average; null without ratings (no fake 4.5).")
    completed_bookings: int


class TripAvailabilitySummaryDTO(ContractModel):
    """Remaining capacity on the matched segment (no vehicle identity, Q43)."""

    seat_capacity: int | None = None
    min_remaining_seats: int | None = None
    min_remaining_cargo_weight_g: int | None = None
    min_remaining_cargo_volume_ml: int | None = None


class FeedPageMeta(PageMeta):
    """M1/M2 ``meta``: ``ranking_version`` (feed.RANKING_VERSION), ``match_scope``, ``degraded`` (e.g. ROUTING_UNAVAILABLE)."""

    ranking_version: str
    match_scope: str = MATCH_SCOPE_CONFIRMED_STOPS
    degraded: list[str] = Field(default_factory=list, description='e.g. ["ROUTING_UNAVAILABLE"]: detours not measured.')


class EmptyDTO(ContractModel):
    """``{}`` payload of a command whose answer is "done" (delete/revoke). Wave 4: owned by the contract."""


# --- wave 4 (A13): operations and growth DTOs (API_V2_CONTRACT §13) --------------------------------------------


class ShareLinkCreate(ContractModel):
    """O1. ``ttl_hours`` is bounded by contracts.operations; the channel only picks the share text."""

    channel: ShareLinkChannel = ShareLinkChannel.GENERIC
    ttl_hours: StrictInt = Field(
        default=SHARE_LINK_DEFAULT_TTL_HOURS, ge=SHARE_LINK_MIN_TTL_HOURS, le=SHARE_LINK_MAX_TTL_HOURS
    )


class ShareLinkDTO(ContractModel):
    """O1. ``url`` carries the secret token and is returned once, at creation; the server stores only its hash."""

    id: str
    channel: ShareLinkChannel
    url: str
    share_text: str
    expires_at: UtcDateTime
    created_at: UtcDateTime


class PublicListingPageDTO(ContractModel):
    """O3, the page an outsider opens (§20.2). No owner name, phone, plate or exact address (Q43)."""

    kind: ListingKind
    service_type: ServiceType
    origin_stop_name: str
    destination_stop_name: str
    departure_date: str = Field(description="Local date (Asia/Tashkent) of the departure window start.")
    departure_window_start: UtcDateTime
    departure_window_end: UtcDateTime
    timezone: str
    price_basis: PriceBasis
    unit_price_minor: StrictInt
    quantity: StrictInt
    total_minor: StrictInt
    currency: Currency
    status_open: StrictBool
    cta: str = Field(description="What the viewer can do next; the app asks for OTP before any offer.")


class OpsQueueItemDTO(ContractModel):
    """O4. ``summary`` is a short operator label: route, status and counts, never a phone or a name."""

    queue: OpsQueue
    item_type: str
    item_id: str
    corridor: str | None = None
    age_minutes: StrictInt
    summary: str


class KpiValueDTO(ContractModel):
    """One §20.4 metric. ``value`` is null when the denominator is 0: no ratio is invented from nothing."""

    metric: KpiMetric
    numerator: StrictInt
    denominator: StrictInt
    value: float | None = None
    target: float | None = None
    small_sample: StrictBool = Field(default=False, description="denominator < KPI_SMALL_SAMPLE_BELOW (§20.4).")


class KpiDTO(ContractModel):
    date_from: str
    date_to: str
    corridor_id: str | None = None
    metrics: list[KpiValueDTO]
    missing_metrics: list[str] = Field(
        default_factory=list, description="Metrics this system does not measure; absent, never reported as zero."
    )
    computed_at: UtcDateTime | None = None


class SloValueDTO(ContractModel):
    name: str
    value: float | None = None
    target: float | None = None
    sample_size: StrictInt = 0
    measured: StrictBool = True
    note: str | None = None


class SloDTO(ContractModel):
    """O6 (§19.3). Tracking freshness covers every trip, so offline trips cannot be hidden to flatter the number."""

    date_from: str
    date_to: str
    indicators: list[SloValueDTO]


class ProviderQuotaDTO(ContractModel):
    """§10.8 map/routing consumption for one provider on one day.

    ``credits`` is Elchi's own estimate from the published per-operation weights, never the provider's invoice;
    ``estimated`` says so explicitly. ``state`` is ``ok`` / ``warn`` (>= 70 %) / ``restrict`` (>= 85 %). GPS
    ingestion is never counted here and never restricted by this number.
    """

    provider: str
    day: str
    calls: StrictInt
    credits: float
    failures: StrictInt
    limit: StrictInt
    ratio: float
    state: Literal["ok", "warn", "restrict"]
    estimated: StrictBool = True


class ListingOnBehalfCreate(ContractModel):
    """O7 (§20.2). The real owner and their consent are recorded; the operator never becomes the owner."""

    owner_user_id: str
    consent_reference: str = Field(min_length=3, max_length=200)


class ParcelPolicyItemDTO(ContractModel):
    """§5.2 one rule of the approved prohibited/restricted items policy.

    ``legal_basis`` and ``source_ref`` are mandatory for a ``prohibited`` rule in the database: the app never
    tells a user "this is forbidden" without naming the rule it comes from and when that source was checked.
    """

    code: str
    category: Literal["prohibited", "restricted", "business_declined"]
    applies_to: Literal["parcel", "passenger_baggage", "all"] = "parcel"
    title: str
    description: str
    legal_basis: str | None = None
    source_ref: str | None = None
    source_checked_on: str | None = None


class ParcelPolicyDTO(ContractModel):
    """§5.2 what a client sees before describing a parcel.

    ``approved=false`` means the list is not published yet - **not** that anything may be sent. In production a
    new parcel listing or booking is refused while it is false (`503 PARCEL_POLICY_UNCONFIRMED`); bookings that
    already exist are unaffected.
    """

    approved: StrictBool
    label: str | None = None
    effective_from: UtcDateTime | None = None
    items: list[ParcelPolicyItemDTO] = Field(default_factory=list)
    notice: str


class ParcelPolicyItemCreate(ContractModel):
    code: str = Field(min_length=2, max_length=64)
    category: Literal["prohibited", "restricted", "business_declined"]
    applies_to: Literal["parcel", "passenger_baggage", "all"] = "parcel"
    title_uz: str = Field(min_length=2, max_length=200)
    description_uz: str = Field(min_length=2, max_length=2000)
    legal_basis: str | None = Field(default=None, max_length=500)
    source_ref: str | None = Field(default=None, max_length=500)
    source_checked_on: str | None = Field(default=None, max_length=10)
    display_order: StrictInt | None = None


class ParcelPolicyVersionCreate(ContractModel):
    """Drafting a policy is a staff action; it applies to nobody until another super_admin confirms it."""

    label: str = Field(min_length=2, max_length=64)
    source_note: str | None = Field(default=None, max_length=2000)
    items: list[ParcelPolicyItemCreate] = Field(min_length=1)


class ParcelPolicyVersionDTO(ContractModel):
    id: str
    label: str
    status: Literal["draft", "active", "superseded"]
    item_count: StrictInt
    created_by: str | None = None
    confirmed_by: str | None = None
    confirmed_at: UtcDateTime | None = None
    effective_from: UtcDateTime | None = None
    version: StrictInt


class LegacyOrderViewDTO(ContractModel):
    """O8 (Q4, AC37, spec §18.1 M4). A v1 order as v2 may *read* it: no row of it exists in any v2 write table.

    ``legacy_calculated_fee_minor`` is what v1 calculated, not money the platform received and not a driver
    debt (spec §9.2, §18.2). ``flags`` names what v1 never stored - a promised window (``unknown_time``) and
    cargo weight/volume/size (``unknown_dimensions``) - instead of filling those gaps with a plausible number.
    The summary carries no phone, name or exact address: the projection does not expose them (ADR-0020).
    """

    legacy_order_number: str
    status: str
    route_summary: str
    engine: Literal["v1"] = "v1"
    final_price_minor: StrictInt | None = None
    legacy_calculated_fee_minor: StrictInt | None = None
    currency: Currency = Currency.UZS
    flags: list[str] = Field(default_factory=list, description="unknown_time, unknown_dimensions")
    created_at: UtcDateTime
    updated_at: UtcDateTime
