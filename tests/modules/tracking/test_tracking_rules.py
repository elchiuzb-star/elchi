"""Pure tracking rules (A6): point classification (AC28, §10.4), payload hash, U1 window rule, grant TTL (U4),
event payload allowlist (§15), migration constants. No DB."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.contracts import tracking as contract
from app.contracts.enums import EventType, TrackingQualityFlag as Q, TrackingWindowReason
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import payload_violations
from app.modules.tracking import rules
from app.modules.tracking.ws import parse_subscription

T0 = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"


def classify(at: datetime, lat: float = 41.3, lng: float = 69.24, *, acc: int = 10, mock: bool = False,
             live: rules.Fix | None = None, candidate: rules.Fix | None = None) -> rules.PointDecision:
    return rules.classify_point(captured_at=at, lat=lat, lng=lng, accuracy_m=acc, is_mock=mock, live=live, candidate=candidate)


def test_distance_is_integer_metres() -> None:
    assert rules.distance_m(41.3, 69.24, 41.3, 69.24) == 0
    one_degree_lat = rules.distance_m(41.0, 69.0, 42.0, 69.0)
    assert isinstance(one_degree_lat, int) and 111_000 < one_degree_lat < 111_400


def test_first_point_moves_live_and_low_accuracy_stays_trusted() -> None:
    decision = classify(T0, acc=150)
    assert decision.flags == (Q.LOW_ACCURACY,) and decision.moves_live and decision.becomes_candidate


def test_mock_point_is_never_live_nor_a_reference() -> None:
    decision = classify(T0, mock=True)
    assert Q.MOCK_LOCATION in decision.flags and not decision.moves_live and not decision.becomes_candidate


def test_ac28_older_point_is_history_only() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    decision = classify(T0 - timedelta(seconds=30), live=live)
    assert decision.flags == (Q.OUT_OF_ORDER,) and not decision.moves_live and not decision.becomes_candidate
    same_time = classify(T0, live=live)
    assert same_time.flags == () and not same_time.moves_live


def test_single_jump_is_flagged_and_second_consistent_point_recovers() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    jump = classify(T0 + timedelta(seconds=10), lat=42.3, live=live)  # ~111 km in 10 s
    assert jump.flags == (Q.IMPLAUSIBLE_SPEED,) and not jump.moves_live and jump.becomes_candidate
    candidate = rules.Fix(T0 + timedelta(seconds=10), 42.3, 69.24)
    follow = classify(T0 + timedelta(seconds=20), lat=42.3001, live=live, candidate=candidate)
    assert follow.flags == () and follow.moves_live
    back_home = classify(T0 + timedelta(seconds=20), lat=41.3001, live=live, candidate=candidate)
    assert back_home.flags == () and back_home.moves_live  # plausible from the live marker


def test_normal_driving_is_plausible() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    assert classify(T0 + timedelta(seconds=10), lat=41.3027, live=live).flags == ()  # ~300 m / 10 s = 30 m/s


def test_payload_hash_is_stable_and_sensitive() -> None:
    base = dict(seq=1, captured_at=T0, lat=41.3, lng=69.24, accuracy_m=10, speed_mps=None, heading_deg=None, battery_pct=80, is_mock=False)
    same = rules.point_payload_hash(**{**base, "captured_at": T0.astimezone(timezone(timedelta(hours=5)))})
    assert rules.point_payload_hash(**base) == same and len(same) == 64
    assert rules.point_payload_hash(**{**base, "lat": 41.3000001}) != same


def test_u1_parcel_sender_window_default_is_from_pickup() -> None:
    assert rules.PARCEL_SENDER_SEES_LIVE_LOCATION_BEFORE_PICKUP is False
    window = rules.booking_tracking_window(service_type="parcel", service_status="confirmed", trip_status="boarding",
                                           pickup_window_start=T0, now=T0)
    assert not window.is_open and window.reason is TrackingWindowReason.PARCEL_NOT_PICKED_UP
    assert rules.parcel_open_statuses() == contract.PARCEL_TRACKING_STATUSES


def test_u1_switch_opens_parcel_before_pickup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rules, "PARCEL_SENDER_SEES_LIVE_LOCATION_BEFORE_PICKUP", True)
    window = rules.booking_tracking_window(service_type="parcel", service_status="awaiting_pickup", trip_status="boarding",
                                           pickup_window_start=T0, now=T0)
    assert window.is_open
    finished = rules.booking_tracking_window(service_type="parcel", service_status="delivered", trip_status="in_progress",
                                             pickup_window_start=T0, now=T0)
    assert not finished.is_open


@pytest.mark.parametrize("minutes, ok", [(14, False), (15, True), (1440, True), (1441, False)])
def test_grant_ttl_bounds(minutes: int, ok: bool) -> None:
    if ok:
        assert rules.grant_ttl(minutes) == timedelta(minutes=minutes)
    else:
        with pytest.raises(DomainError) as info:
            rules.grant_ttl(minutes)
        assert info.value.code is ErrorCode.VALIDATION_ERROR and info.value.details["min"] == 15


def _window(service: str, status: str, now: datetime):  # noqa: ANN202
    return rules.booking_tracking_window(service_type=service, service_status=status, trip_status="planned",
                                         pickup_window_start=T0, now=now)


def test_l10_parcel_grant_before_pickup_starts_at_pickup_and_cannot_expire_first() -> None:
    now = T0 - timedelta(hours=10)
    start, until = rules.grant_validity(window=_window("parcel", "confirmed", now), service_type="parcel",
                                        pickup_window_start=T0, now=now, ttl=timedelta(minutes=15))
    assert start == T0 and until == T0 + timedelta(minutes=15)
    picked = rules.grant_validity(window=_window("parcel", "picked_up", now), service_type="parcel",
                                  pickup_window_start=T0, now=now, ttl=timedelta(hours=1))
    assert picked == (now, now + timedelta(hours=1))  # window already open: starts now


def test_passenger_grant_starts_at_window_opening() -> None:
    now = T0 - timedelta(hours=3)
    start, until = rules.grant_validity(window=_window("passenger", "confirmed", now), service_type="passenger",
                                        pickup_window_start=T0, now=now, ttl=timedelta(hours=2))
    assert start == T0 - timedelta(minutes=30) and until == start + timedelta(hours=2)


@pytest.mark.parametrize("service, status, anchor", [("parcel", "awaiting_pickup", T0),
                                                     ("passenger", "confirmed", T0 - timedelta(minutes=30))])
def test_grant_issued_too_far_ahead_is_refused(service: str, status: str, anchor: datetime) -> None:
    ok_now = anchor - contract.TRACKING_GRANT_MAX_TTL
    rules.grant_validity(window=_window(service, status, ok_now), service_type=service, pickup_window_start=T0, now=ok_now,
                         ttl=timedelta(minutes=15))
    early = ok_now - timedelta(seconds=1)
    with pytest.raises(DomainError) as info:
        rules.grant_validity(window=_window(service, status, early), service_type=service, pickup_window_start=T0, now=early,
                             ttl=timedelta(minutes=15))
    assert info.value.code is ErrorCode.VALIDATION_ERROR and info.value.details["reason"] == "grant_too_early"
    assert info.value.details["issuable_from"].startswith(ok_now.strftime("%Y-%m-%dT%H:%M"))


def test_event_payloads_are_allowlisted_and_coordinate_free() -> None:
    stale = rules.stale_payload(trip_public_id="trp_x", last_captured_at=T0)
    assert payload_violations(EventType.TRACKING_STALE, stale) == [] and stale["freshness"] == "lost"
    assert rules.stale_payload(trip_public_id="trp_x", last_captured_at=None)["freshness"] == "no_data"
    opened = rules.window_opened_payload(booking_public_id="bkg_x", trip_public_id="trp_x", service_type="parcel", opens_at=None)
    assert payload_violations(EventType.TRACKING_WINDOW_OPENED, opened) == []
    for payload in (stale, opened):
        assert not {"lat", "lng", "point", "phone"} & set(payload)


def test_migration_constants_match_contract() -> None:
    spec = importlib.util.spec_from_file_location("a6_migration_0058", VERSIONS / "20260916_0058_tracking_sessions_points.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert timedelta(days=module.RAW_POINT_RETENTION_DAYS) == contract.RAW_POINT_RETENTION
    assert module.revision == "20260916_0058" and module.down_revision == "20260915_0057"


def test_ws_subscription_parsing() -> None:
    assert parse_subscription({"action": "subscribe", "tracking_token": "abc"}, None).tracking_token == "abc"
    sub = parse_subscription({"action": "subscribe", "booking_id": "bkg_x"}, "Bearer jwt")
    assert sub.booking_id == "bkg_x" and sub.access_token == "jwt"
    assert parse_subscription({"action": "subscribe", "booking_id": "bkg_x"}, None) is None
    assert parse_subscription(["subscribe"], None) is None


# --- Q149: location-spoofing signals ---------------------------------------------------------------------------------


def classify_speed(at: datetime, lat: float, speed: int | None, *, acc: int = 10, live: rules.Fix | None = None,
                   candidate: rules.Fix | None = None) -> rules.PointDecision:
    return rules.classify_point(captured_at=at, lat=lat, lng=69.24, accuracy_m=acc, is_mock=False, live=live,
                                candidate=candidate, speed_mps=speed)


def test_q149_zero_accuracy_is_flagged_and_never_moves_the_marker() -> None:
    decision = classify(T0, acc=0)
    assert decision.flags == (Q.ZERO_ACCURACY,) and not decision.moves_live
    assert Q.ZERO_ACCURACY in contract.SUSPICIOUS_QUALITY_FLAGS


def test_q149_device_says_standing_while_the_fix_drives_away() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    moved = classify_speed(T0 + timedelta(seconds=10), 41.3027, 0, live=live)  # ~300 m in 10 s, device says 0 m/s
    assert moved.flags == (Q.SPEED_MISMATCH,)
    assert moved.moves_live  # a signal for review, not a veto: an honest car is never frozen by it


def test_q149_device_says_fast_while_the_fix_stands_still() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    assert classify_speed(T0 + timedelta(seconds=20), 41.3, 25, live=live).flags == (Q.SPEED_MISMATCH,)


def test_q149_honest_driving_and_jitter_are_not_mismatches() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    assert classify_speed(T0 + timedelta(seconds=10), 41.3027, 28, live=live).flags == ()  # 30 m/s, reports 28
    # a 150 m jump in a city canyon with ±150 m accuracy while standing: jitter, not spoofing
    jitter = classify_speed(T0 + timedelta(seconds=10), 41.30135, 0, acc=150, live=live)
    assert Q.SPEED_MISMATCH not in jitter.flags
    # an average over minutes legitimately differs from an instant reading: not compared
    assert classify_speed(T0 + timedelta(minutes=5), 41.3, 25, live=live).flags == ()
    # no speed from the device: nothing to compare
    assert classify_speed(T0 + timedelta(seconds=10), 41.3027, None, live=live).flags == ()


def test_q149_mismatch_is_measured_from_the_trusted_marker_not_a_spoofed_jump() -> None:
    live = rules.Fix(T0, 41.3, 69.24)
    spoofed_jump = rules.Fix(T0 + timedelta(seconds=10), 42.3, 69.24)  # the untrusted candidate after a teleport
    # the honest point back next to the marker, standing: no mismatch although it is 111 km from the jump
    back = classify_speed(T0 + timedelta(seconds=20), 41.3, 0, live=live, candidate=spoofed_jump)
    assert Q.SPEED_MISMATCH not in back.flags


@pytest.mark.parametrize(
    "reported, distance, elapsed, accuracy, expected",
    [(0, 300, 10, 10, True), (28, 300, 10, 10, False), (25, 0, 20, 10, True), (0, 150, 10, 150, False),
     (None, 300, 10, 10, False), (0, 3000, 60, 10, False), (0, 300, 3, 10, False)],
)
def test_q149_speed_mismatch_contract(reported, distance, elapsed, accuracy, expected) -> None:  # noqa: ANN001
    assert contract.is_speed_mismatch(reported, distance, elapsed, accuracy) is expected


def test_q149_migration_accepts_every_flag_and_signal_type() -> None:
    from app.contracts.enums import FraudSignalType

    spec = importlib.util.spec_from_file_location("a0a_migration_0095", VERSIONS / "20260925_0095_tracking_spoofing_signals.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.QUALITY_FLAGS) == {flag.value for flag in Q}
    assert set(module.FRAUD_SIGNAL_TYPES) == {kind.value for kind in FraudSignalType}
    assert module.down_revision == "20260925_0094"
