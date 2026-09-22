"""Wave 3 contract additions (16.09.2026): tracking (A6), communications (A7), trust & support (A12), feed (A5)."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import communications, db_errors, feed, tracking, trust
from app.contracts.dto import (
    BookingTrackingDTO,
    ChatMessageCreate,
    ChatMessageDTO,
    EventDTO,
    PointsBatchIn,
    PublicTrackingDTO,
    TrackingPointIn,
)
from app.contracts.enums import (
    STAFF_ROLE_CAPABILITIES,
    Capability,
    ChatThreadKind,
    DisputeType,
    EventType,
    ReputationLabel,
    Role,
    ServiceType,
    TrackingQualityFlag,
    TrackingWindowReason,
)
from app.contracts.errors import ErrorCode, http_status_for
from app.contracts.events import (
    EVENT_AUDIENCES,
    EVENT_PAYLOAD_ALLOWLIST,
    EventAudience,
    EventEnvelope,
    payload_for_audience,
)
from app.contracts.ids import PublicIdPrefix
from app.contracts.state_machines import ALL_MACHINES, SUPPORT_TICKET, TRUST_REVIEW

NOW = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[2]
FORBIDDEN_PAYLOAD_KEYS = {"phone", "text", "message", "name", "full_name", "lat", "lng", "point", "code", "token",
                          "address", "description", "comment"}
IDENTIFYING_FIELDS = {"phone", "contact_phone", "full_name", "display_name", "plate_number", "user_id", "author_user_id",
                      "driver_id", "client_id", "gps_active"}


@pytest.mark.parametrize(("code", "status"), [(ErrorCode.TRACKING_SESSION_CLOSED, 409), (ErrorCode.CHAT_CLOSED, 409),
                                              (ErrorCode.SAVED_SEARCH_LIMIT_REACHED, 409)])
def test_wave3_error_codes(code: ErrorCode, status: int) -> None:
    assert http_status_for(code) == status


def test_wave3_public_id_prefixes_unique() -> None:
    values = [prefix.value for prefix in PublicIdPrefix]
    assert len(values) == len(set(values))
    assert {PublicIdPrefix.SUPPORT_TICKET.value, PublicIdPrefix.TRUST_REVIEW.value, PublicIdPrefix.NOTIFICATION.value} == {
        "sup", "trv", "ntf"}


def test_trust_review_capability_is_operator_plus_q45() -> None:
    for role in (Role.OPERATOR, Role.ADMIN, Role.SUPER_ADMIN):
        assert Capability.OPS_TRUST_REVIEW in STAFF_ROLE_CAPABILITIES[role]
    assert Capability.OPS_TRUST_REVIEW not in STAFF_ROLE_CAPABILITIES[Role.FINANCE]


# --- events ---------------------------------------------------------------------------------------------------------

WAVE3_EVENTS = [
    EventType.CHAT_MESSAGE_CREATED, EventType.BOOKING_DRIVER_ARRIVED, EventType.TRACKING_WINDOW_OPENED,
    EventType.SAVED_SEARCH_MATCHED, EventType.TRUST_REVIEW_OPENED, EventType.TRUST_WARNING_ISSUED,
    EventType.SUPPORT_TICKET_OPENED, EventType.SUPPORT_SOS_RAISED, EventType.SUPPORT_TICKET_STATUS_CHANGED,
    EventType.RATING_PUBLISHED,
]


@pytest.mark.parametrize("event_type", WAVE3_EVENTS, ids=lambda e: e.value)
def test_wave3_event_payloads_carry_no_personal_data(event_type: EventType) -> None:
    keys = EVENT_PAYLOAD_ALLOWLIST[event_type]
    assert not (keys & FORBIDDEN_PAYLOAD_KEYS)
    assert EventAudience.STAFF in EVENT_AUDIENCES[event_type]


@pytest.mark.parametrize("event_type", [EventType.TRUST_REVIEW_OPENED, EventType.SUPPORT_SOS_RAISED,
                                        EventType.SUPPORT_TICKET_OPENED, EventType.CONTACT_FILTER_HIT])
def test_staff_only_trust_events(event_type: EventType) -> None:
    assert EVENT_AUDIENCES[event_type] == frozenset({EventAudience.STAFF})
    assert payload_for_audience(event_type, {}, EventAudience.CLIENT) is None
    assert payload_for_audience(event_type, {}, EventAudience.DRIVER) is None


def test_competing_driver_copy_has_listing_id_only_adr0019() -> None:
    payload = {"listing_id": "lst_x", "thread_id": "prp_x", "revision": 2, "author_side": "driver"}
    assert payload_for_audience(EventType.PROPOSAL_CREATED, payload, EventAudience.COMPETING_DRIVER) == {
        "listing_id": "lst_x"}
    assert payload_for_audience(EventType.PROPOSAL_REJECTED, payload, EventAudience.COMPETING_DRIVER) is None
    assert payload_for_audience(EventType.BOOKING_ACCEPTED, {"service_type": "parcel"},
                                EventAudience.COMPETING_DRIVER) is None
    assert payload_for_audience(EventType.PROPOSAL_CREATED, payload, EventAudience.CLIENT) == payload


def test_chat_event_envelope_rejects_text() -> None:
    EventEnvelope(EventType.CHAT_MESSAGE_CREATED, "chat_thread", "cht_x", 1, NOW,
                  {"thread_id": "cht_x", "thread_kind": "booking", "message_id": "msg_x", "author_side": "client"})
    with pytest.raises(ValueError):
        EventEnvelope(EventType.CHAT_MESSAGE_CREATED, "chat_thread", "cht_x", 1, NOW, {"text": "salom"})


# --- state machines -------------------------------------------------------------------------------------------------


def test_wave3_machines_registered_and_terminal() -> None:
    assert TRUST_REVIEW in ALL_MACHINES and SUPPORT_TICKET in ALL_MACHINES
    assert TRUST_REVIEW.terminal == {"dismissed", "actioned"}
    assert SUPPORT_TICKET.terminal == {"resolved"}
    assert not TRUST_REVIEW.is_allowed("actioned", "open")


# --- tracking -------------------------------------------------------------------------------------------------------


def _window(service: str, status: str, trip: str = "planned", pickup: datetime = NOW + timedelta(hours=1)):
    return tracking.tracking_window(service_type=service, service_status=status, trip_status=trip,
                                    pickup_window_start=pickup, now=NOW)


def test_passenger_window_opens_30_min_before_pickup_ac44() -> None:
    early = _window("passenger", "confirmed", pickup=NOW + timedelta(days=2))
    assert not early.is_open and early.reason is TrackingWindowReason.NOT_YET_OPEN
    assert early.opens_at == NOW + timedelta(days=2) - timedelta(minutes=30)
    assert _window("passenger", "awaiting_pickup", pickup=NOW + timedelta(minutes=30)).is_open
    assert _window("passenger", "onboard", trip="in_progress", pickup=NOW + timedelta(days=1)).is_open
    assert _window("passenger", "arrived", trip="in_progress").reason is TrackingWindowReason.BOOKING_FINISHED


def test_parcel_window_is_pickup_to_delivery_and_trip_end_closes() -> None:
    assert _window("parcel", "awaiting_pickup").reason is TrackingWindowReason.PARCEL_NOT_PICKED_UP
    assert _window("parcel", "in_transit", trip="in_progress").is_open
    assert _window("parcel", "delivered", trip="in_progress").reason is TrackingWindowReason.BOOKING_FINISHED
    closed = _window("parcel", "return_required", trip="completed")
    assert not closed.is_open and closed.reason is TrackingWindowReason.TRIP_FINISHED


def test_point_rejection_and_trust() -> None:
    assert tracking.point_rejection(NOW, NOW) is None
    assert tracking.point_rejection(NOW + timedelta(seconds=61), NOW).value == "future_timestamp"
    assert tracking.point_rejection(NOW - timedelta(hours=25), NOW).value == "too_old"
    assert tracking.is_trusted_for_live([TrackingQualityFlag.LOW_ACCURACY])
    assert not tracking.is_trusted_for_live(["mock_location"])
    assert tracking.is_implausible_speed(1000, 10.0) and not tracking.is_implausible_speed(500, 10.0)


def test_tracking_point_dto_units_are_integers() -> None:
    point = TrackingPointIn(seq=1, captured_at="2026-09-16T14:00:00+05:00", lat=41.31, lng=69.28, accuracy_m=12)
    assert point.speed_mps is None and point.is_mock is False
    for bad in ({"accuracy_m": 12.5}, {"lat": 91}, {"captured_at": "2026-09-16T14:00:00"}, {"heading_deg": 360},
                {"phone": "+998901234567"}):
        data = {"seq": 1, "captured_at": "2026-09-16T14:00:00+05:00", "lat": 41.3, "lng": 69.2, "accuracy_m": 5} | bad
        with pytest.raises(ValidationError):
            TrackingPointIn(**data)
    with pytest.raises(ValidationError):
        PointsBatchIn(points=[])


@pytest.mark.parametrize("model", [BookingTrackingDTO, PublicTrackingDTO, ChatMessageDTO])
def test_shared_dtos_have_no_identifying_fields(model: type) -> None:
    assert not (set(model.model_fields) & IDENTIFYING_FIELDS)


# --- communications -------------------------------------------------------------------------------------------------


def test_chat_create_requires_text_or_quick_reply() -> None:
    assert ChatMessageCreate(quick_reply_code="at_stop").text is None
    with pytest.raises(ValidationError):
        ChatMessageCreate()
    with pytest.raises(ValidationError):
        ChatMessageCreate(text="x" * (communications.CHAT_TEXT_MAX_LENGTH + 1))
    assert communications.CHAT_MASK_PROOF_CODES is True and communications.CHAT_ATTACHMENTS_ENABLED is False


def test_chat_writable_rules() -> None:
    assert communications.chat_writable(kind=ChatThreadKind.PROPOSAL, now=NOW, proposal_thread_open=True)
    assert not communications.chat_writable(kind="proposal", now=NOW, proposal_thread_open=False)
    assert communications.chat_writable(kind="booking", now=NOW)
    assert communications.chat_writable(kind="booking", now=NOW, booking_terminal_at=NOW - timedelta(hours=23))
    assert not communications.chat_writable(kind="booking", now=NOW, booking_terminal_at=NOW - timedelta(hours=24))


def test_outbox_retry_schedule_adr0012() -> None:
    assert communications.outbox_retry_delay(1) == timedelta(minutes=1)
    assert communications.outbox_retry_delay(5) == timedelta(hours=6)
    assert communications.outbox_retry_delay(9) == timedelta(hours=6)
    assert communications.outbox_retry_delay(10) is None
    assert communications.PUSH_PAYLOAD_KEYS == {"event_type", "aggregate_id", "title_key"}


def test_event_dto_and_dispatched_event() -> None:
    EventDTO(id="evt_x", event_type="booking.accepted", aggregate_type="booking", aggregate_id="bkg_x",
             aggregate_version=1, occurred_at=NOW, payload={})
    event = communications.DispatchedEvent(uuid.uuid4(), EventType.LISTING_PUBLISHED, "listing", "lst_x", 1, 1, NOW, {})
    assert event.event_type is EventType.LISTING_PUBLISHED


# --- trust ----------------------------------------------------------------------------------------------------------


def test_blocking_dispute_types_state_machines_s8() -> None:
    assert trust.BLOCKING_DISPUTE_TYPES == {DisputeType.SERVICE, DisputeType.COMMISSION, DisputeType.PAYMENT,
                                            DisputeType.DELIVERY}


def test_probe_signatures_match_bookings_hooks() -> None:
    from app.modules.bookings import service as bookings_service

    assert callable(bookings_service.set_blocking_dispute_probe)
    assert callable(bookings_service.set_payment_dispute_opener)
    assert bookings_service.dispute_state.__name__ == "dispute_state"


def test_q45_strike_rules() -> None:
    assert not trust.hit_is_strike(0) and trust.hit_is_strike(1)
    assert trust.strikes_need_review(3) and not trust.strikes_need_review(2)
    assert trust.is_quick_cancel_after_chat(NOW - timedelta(minutes=30), NOW)
    assert not trust.is_quick_cancel_after_chat(NOW - timedelta(hours=2), NOW)
    assert not trust.is_quick_cancel_after_chat(None, NOW)
    assert trust.is_repeated_pair_cancellation(2)
    assert trust.SUPPORT_PROMISES_RESPONSE_TIME is False


def test_reputation_never_fakes_a_rating_ac36() -> None:
    new = trust.ReputationSummary(user_id=1, service_type=ServiceType.PASSENGER)
    assert new.label is ReputationLabel.NEW_VERIFIED and new.average_rating is None
    assert new.adjusted_rating == pytest.approx(4.5)
    one_five = trust.ReputationSummary(user_id=2, service_type=ServiceType.PASSENGER, rating_count=1, rating_sum=5)
    veteran = trust.ReputationSummary(user_id=3, service_type=ServiceType.PASSENGER, rating_count=200, rating_sum=960)
    assert one_five.average_rating == 5.0
    assert one_five.adjusted_rating < veteran.adjusted_rating  # 1 x 5.0 is not blindly first (AC36)


# --- feed -----------------------------------------------------------------------------------------------------------


def test_ranking_weights_match_spec_8_2_and_8_4() -> None:
    assert feed.score_weights_are_normalized(feed.CLIENT_SCORE_WEIGHTS)
    assert feed.score_weights_are_normalized(feed.DRIVER_SCORE_WEIGHTS)
    assert feed.score_weights_are_normalized(feed.RELIABILITY_WEIGHTS)
    assert feed.SAVED_SEARCH_MAX_PER_USER > 0


# --- DB error rules and migration stubs -----------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "code"), [
    ("tracking_session_superseded", ErrorCode.TRACKING_SESSION_SUPERSEDED),
    ("tracking_session_closed", ErrorCode.TRACKING_SESSION_CLOSED),
    ("chat_message_immutable", ErrorCode.INTEGRITY_CONFLICT),
    ("uq_disputes_v2_booking_type_active", ErrorCode.DISPUTE_ALREADY_OPEN),
    ("saved_search_limit", ErrorCode.SAVED_SEARCH_LIMIT_REACHED),
    ("append_only_violation", ErrorCode.INTEGRITY_CONFLICT),
])
def test_wave3_constraint_rules(name: str, code: ErrorCode) -> None:
    assert db_errors.map_db_error(sqlstate="23514", constraint=name).code is code


@pytest.mark.parametrize(("filename", "revision", "down"), [
    ("20260916_0058_tracking_sessions_points.py", "20260916_0058", "20260915_0057"),
    ("20260916_0059_communications_chat_notifications.py", "20260916_0059", "20260916_0058"),
    ("20260916_0060_trust_support_disputes_strikes.py", "20260916_0060", "20260916_0059"),
    ("20260916_0061_marketplace_saved_searches.py", "20260916_0061", "20260916_0060"),
])
def test_wave3_migration_chain(filename: str, revision: str, down: str) -> None:
    path = REPO / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"wave3_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.revision, module.down_revision) == (revision, down)
