"""Unit tests for route matching (AC15, AC16, AC17, AC35; spec §6.3-6.5; wave 1.5 BR #1-#4).

Stop ids are arbitrary integers: nothing here (or in the code) knows which district
is "on the way". Synthetic schedule: Toshkent 06:00 -> Samarqand 10:00 -> Chiroqchi
12:00 -> Qarshi 13:00 (all +05:00), 5-minute dwell at intermediate stops.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.enums import MatchType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.geo.matching import (
    apply_insertions,
    cumulative_detour_allowed,
    evaluate_route_match,
    measure_detours,
    validate_detour_quote,
    validate_detour_quotes,
    verify_existing_windows,
)
from app.modules.geo.routing import FakeRoutingProvider
from app.modules.geo.types import (
    DETOUR_QUOTE_TTL,
    BookingWindow,
    DetourMeasurements,
    DetourQuote,
    LatLng,
    MatchReason,
    MatchRequest,
    OccurrenceTiming,
    TripRouteContext,
)

TZ = timezone(timedelta(hours=5))
TOSHKENT, SAMARQAND, CHIROQCHI, QARSHI, GUZOR, KITOB = 11, 12, 13, 14, 15, 16
ROUTE_VERSION, TRIP_VERSION = 7, 3
ROUTE_PUBLIC_ID = "rtv_" + "a" * 26
MEASURED = datetime(2026, 9, 20, 0, 0, tzinfo=TZ)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 20, hour, minute, tzinfo=TZ)


def occurrences(stops=((TOSHKENT, 6), (SAMARQAND, 10), (CHIROQCHI, 12), (QARSHI, 13))) -> tuple[OccurrenceTiming, ...]:  # noqa: ANN001
    return tuple(
        OccurrenceTiming(seq=i, stop_id=stop, planned_arrival_at=at(hour), dwell_minutes=5 if 0 < i < len(stops) - 1 else 0)
        for i, (stop, hour) in enumerate(stops)
    )


def trip(stops=None, **kw) -> TripRouteContext:  # noqa: ANN001, ANN003
    params = dict(route_version_id=ROUTE_VERSION, route_version_public_id=ROUTE_PUBLIC_ID, trip_version=TRIP_VERSION, max_detour_minutes=30, max_detour_m=20_000, pickup_wait_minutes=10)
    params.update(kw)
    occ = params.pop("occurrences", None) or (occurrences(stops) if stops else occurrences())
    return TripRouteContext(occurrences=occ, **params)


def quote(stop: int, after_seq: int, offset_s: int, extra_s: int, extra_m: int, **kw) -> DetourQuote:  # noqa: ANN003
    params = dict(
        route_version_id=ROUTE_PUBLIC_ID,
        trip_version=TRIP_VERSION,
        measured_at=MEASURED,
        expires_at=MEASURED + DETOUR_QUOTE_TTL,
        provider="fake",
        provider_version="fake-1",
    )
    params.update(kw)
    return DetourQuote(stop_id=stop, after_seq=after_seq, arrive_offset_s=offset_s, extra_s=extra_s, extra_m=extra_m, **params)


def request(pickup: int, dropoff: int, start: datetime, end: datetime, **kw) -> MatchRequest:  # noqa: ANN003
    return MatchRequest(pickup_stop_id=pickup, dropoff_stop_id=dropoff, pickup_window_start=start, pickup_window_end=end, **kw)


# --- classification ---------------------------------------------------------------


def test_full_route_is_exact() -> None:
    result = evaluate_route_match(trip(), request(TOSHKENT, QARSHI, at(5, 30), at(6, 30)))
    assert result.matched and result.match_type is MatchType.EXACT
    assert MatchReason.FULL_ROUTE in result.reasons
    assert result.pickup.occurrence_seq == 0 and result.dropoff.occurrence_seq == 3
    assert result.detour_minutes == 0 and result.detour_quotes == ()


def test_intermediate_segment_is_on_route() -> None:
    result = evaluate_route_match(trip(), request(TOSHKENT, CHIROQCHI, at(5, 30), at(6, 30)))
    assert result.matched and result.match_type is MatchType.ON_ROUTE
    assert MatchReason.INTERMEDIATE_SEGMENT in result.reasons


def test_detour_within_limit_is_detour_and_carries_its_quote() -> None:
    q = quote(KITOB, 1, 5400, 900, 8_000)
    result = evaluate_route_match(trip(), request(KITOB, QARSHI, at(11, 30), at(12, 30)), detours=DetourMeasurements((q,)))
    assert result.matched and result.match_type is MatchType.DETOUR
    assert result.pickup.kind == "detour" and result.pickup.after_seq == 1
    assert result.detour_s == 900 and result.detour_minutes == 15 and result.is_estimate
    assert result.pickup_eta_window_start == at(11, 35)  # Samarqand 10:00 + 5 dwell + 90 min driving
    assert result.detour_quotes == (q,)


def test_alternative_only_when_requested_and_marked() -> None:
    strict = evaluate_route_match(trip(), request(SAMARQAND, QARSHI, at(14), at(15)))
    assert not strict.matched and strict.error_code is ErrorCode.TIME_WINDOW_CONFLICT
    loose = evaluate_route_match(trip(), request(SAMARQAND, QARSHI, at(12), at(13)), include_alternatives=True)
    assert loose.matched and loose.match_type is MatchType.ALTERNATIVE
    assert MatchReason.TIME_DIFFERS in loose.reasons


def test_nearby_stop_is_only_an_alternative() -> None:
    near = request(GUZOR, QARSHI, at(11), at(13), pickup_alternative_stop_ids=(CHIROQCHI,))
    assert not evaluate_route_match(trip(), near).matched
    result = evaluate_route_match(trip(), near, include_alternatives=True)
    assert result.match_type is MatchType.ALTERNATIVE
    assert result.pickup.stop_id == CHIROQCHI and result.pickup.is_alternative_stop
    assert MatchReason.NEARBY_STOP in result.reasons


# --- AC14 / AC16 -------------------------------------------------------------------------


def test_ac14_stop_not_on_route_is_not_matched() -> None:
    route_without_chiroqchi = trip(stops=((TOSHKENT, 6), (SAMARQAND, 10), (GUZOR, 12), (QARSHI, 13)))
    result = evaluate_route_match(route_without_chiroqchi, request(CHIROQCHI, QARSHI, at(11), at(13)))
    assert not result.matched and result.match_type is None
    assert result.error_code is ErrorCode.ROUTE_MISMATCH
    assert MatchReason.PICKUP_NOT_ON_ROUTE in result.reasons and not result.degraded


def test_ac16_reverse_direction_is_rejected() -> None:
    result = evaluate_route_match(trip(), request(QARSHI, CHIROQCHI, at(5), at(23)), include_alternatives=True)
    assert not result.matched and result.error_code is ErrorCode.ROUTE_MISMATCH
    assert result.reasons == (MatchReason.REVERSE_DIRECTION,)


def test_both_pickup_and_dropoff_are_checked() -> None:
    result = evaluate_route_match(trip(), request(SAMARQAND, GUZOR, at(9, 30), at(10, 30)))
    assert not result.matched and MatchReason.DROPOFF_NOT_ON_ROUTE in result.reasons


def test_same_stop_rejected() -> None:
    result = evaluate_route_match(trip(), request(QARSHI, QARSHI, at(5), at(23)))
    assert result.error_code is ErrorCode.ROUTE_MISMATCH and result.reasons == (MatchReason.SAME_STOP,)


# --- AC15 and ETA semantics (BR #1) -----------------------------------------------------------


def test_ac15_pickup_eta_uses_intermediate_stop_not_origin_departure() -> None:
    req = request(CHIROQCHI, QARSHI, at(11, 45), at(12, 30))
    result = evaluate_route_match(trip(), req)
    assert result.matched and result.match_type is MatchType.ON_ROUTE
    assert result.pickup_eta_window_start == at(12, 0)
    assert result.pickup_eta_window_end == at(12, 10)  # max(wait 10, dwell 5)
    assert result.dropoff.eta_window_start == at(13, 0) and result.dropoff.eta_window_end == at(13, 1)
    early = evaluate_route_match(trip(), request(CHIROQCHI, QARSHI, at(5, 45), at(6, 30)))
    assert not early.matched and early.error_code is ErrorCode.TIME_WINDOW_CONFLICT


def test_no_blanket_slack_from_detour_already_used() -> None:
    # Wave 1 widened every window end by detour_used; that is gone. The used budget no longer moves ETAs.
    used = trip(detour_used_s=1200)
    late = evaluate_route_match(used, request(CHIROQCHI, QARSHI, at(12, 25), at(12, 40)))
    assert not late.matched and late.error_code is ErrorCode.TIME_WINDOW_CONFLICT
    origin = evaluate_route_match(used, request(TOSHKENT, QARSHI, at(5, 55), at(6, 5)))
    assert origin.pickup_eta_window_start == at(6, 0) and origin.pickup_eta_window_end == at(6, 10)


def test_accepted_detour_before_an_occurrence_shifts_only_later_arrivals() -> None:
    accepted = quote(KITOB, 1, 3600, 1200, 5_000)
    change = apply_insertions(occurrences(), [accepted], inserted_dwell_minutes=2)
    arrivals = {o.seq: (o.stop_id, o.planned_arrival_at) for o in change.occurrences}
    assert arrivals == {
        0: (TOSHKENT, at(6, 0)),
        1: (SAMARQAND, at(10, 0)),
        2: (KITOB, at(11, 5)),  # 10:00 + 5 dwell + 60 min
        3: (CHIROQCHI, at(12, 22)),  # 12:00 + 20 min extra + 2 min inserted dwell
        4: (QARSHI, at(13, 22)),
    }
    assert change.seq_map == {0: 0, 1: 1, 2: 3, 3: 4} and change.inserted_seqs == (2,)

    after = trip(occurrences=change.occurrences, trip_version=TRIP_VERSION + 1, detour_used_s=1200, detour_used_m=5_000)
    chiroqchi = evaluate_route_match(after, request(CHIROQCHI, QARSHI, at(12, 15), at(12, 30)))
    assert chiroqchi.matched and chiroqchi.pickup_eta_window_start == at(12, 22)
    origin = evaluate_route_match(after, request(TOSHKENT, QARSHI, at(5, 55), at(6, 5)))
    assert origin.match_type is MatchType.EXACT and origin.pickup_eta_window_start == at(6, 0)


def test_two_insertions_renumber_and_accumulate() -> None:
    change = apply_insertions(occurrences(), [quote(GUZOR, 2, 600, 300, 1), quote(KITOB, 0, 600, 300, 1)])
    assert change.seq_map == {0: 0, 1: 2, 2: 3, 3: 5} and change.inserted_seqs == (1, 4)
    arrivals = [(o.seq, o.stop_id, o.planned_arrival_at) for o in change.occurrences]
    assert arrivals == [
        (0, TOSHKENT, at(6, 0)),
        (1, KITOB, at(6, 10)),
        (2, SAMARQAND, at(10, 5)),
        (3, CHIROQCHI, at(12, 5)),
        (4, GUZOR, at(12, 20)),
        (5, QARSHI, at(13, 10)),
    ]


def test_decision_25_double_detour_on_same_leg_rejected() -> None:
    with pytest.raises(ValueError, match="same leg"):
        apply_insertions(occurrences(), [quote(KITOB, 1, 60, 60, 1), quote(GUZOR, 1, 60, 60, 1)])
    detours = DetourMeasurements((quote(KITOB, 1, 600, 60, 1), quote(GUZOR, 1, 900, 60, 1)))
    result = evaluate_route_match(trip(), request(KITOB, GUZOR, at(10), at(12)), detours=detours)
    assert result.error_code is ErrorCode.ROUTE_MISMATCH and result.reasons == (MatchReason.DETOUR_ORDER_UNKNOWN,)
    with pytest.raises(DomainError) as info:
        validate_detour_quotes([quote(KITOB, 1, 1, 1, 1), quote(GUZOR, 1, 1, 1, 1)], trip(), now=MEASURED)
    assert info.value.code is ErrorCode.ROUTE_MISMATCH


def test_pickup_detour_delays_dropoff_by_extra_and_inserted_dwell() -> None:
    q = quote(KITOB, 1, 3600, 600, 1)
    result = evaluate_route_match(trip(inserted_stop_dwell_minutes=3), request(KITOB, QARSHI, at(11), at(11, 30)), detours=DetourMeasurements((q,)))
    assert result.dropoff.eta_window_start == at(13, 13)  # 13:00 + 10 min extra + 3 min dwell at Kitob


def test_dropoff_window_is_checked_too() -> None:
    req = request(SAMARQAND, QARSHI, at(9, 50), at(10, 30), dropoff_window_start=at(15), dropoff_window_end=at(16))
    assert evaluate_route_match(trip(), req).error_code is ErrorCode.TIME_WINDOW_CONFLICT


# --- AC17 and seconds (BR #2) -----------------------------------------------------------------


def test_ac17_each_pickup_10_min_but_total_40_exceeds_30_limit() -> None:
    used_s = used_m = 0
    version = TRIP_VERSION
    outcomes = []
    for _ in range(4):
        ctx = trip(detour_used_s=used_s, detour_used_m=used_m, trip_version=version)
        q = quote(KITOB, 1, 3600, 600, 3_000, trip_version=version)
        result = evaluate_route_match(ctx, request(KITOB, QARSHI, at(11), at(12)), detours=DetourMeasurements((q,)))
        outcomes.append(result)
        if result.matched:
            used_s += result.detour_s
            used_m += result.detour_m
            version += 1  # accept bumps the trip version, so the next quote must be re-measured
    assert [r.matched for r in outcomes] == [True, True, True, False]
    assert used_s == 1800
    assert outcomes[3].error_code is ErrorCode.DETOUR_LIMIT_EXCEEDED
    assert outcomes[3].details["detour_used_s"] == 1800 and outcomes[3].details["detour_added_s"] == 600
    assert outcomes[3].details["max_detour_s"] == 1800


def test_detour_budget_is_counted_in_seconds_not_rounded_minutes() -> None:
    assert cumulative_detour_allowed(detour_used_s=1799, detour_used_m=0, added_s=1, added_m=0, max_detour_minutes=30, max_detour_m=1)
    assert not cumulative_detour_allowed(detour_used_s=1799, detour_used_m=0, added_s=2, added_m=0, max_detour_minutes=30, max_detour_m=1)
    ok = evaluate_route_match(trip(detour_used_s=1741), request(KITOB, QARSHI, at(11), at(12)), detours=DetourMeasurements((quote(KITOB, 1, 3600, 59, 1),)))
    assert ok.matched and ok.detour_minutes == 1


def test_pickup_and_dropoff_detours_add_up() -> None:
    detours = DetourMeasurements((quote(KITOB, 1, 3600, 1200, 1), quote(GUZOR, 2, 1200, 1200, 1)))
    result = evaluate_route_match(trip(), request(KITOB, GUZOR, at(10), at(12)), detours=detours)
    assert not result.matched and result.error_code is ErrorCode.DETOUR_LIMIT_EXCEEDED


def test_detour_distance_limit_also_cumulative() -> None:
    detours = DetourMeasurements((quote(KITOB, 1, 3600, 60, 6_000),))
    result = evaluate_route_match(trip(detour_used_m=15_000), request(KITOB, QARSHI, at(10), at(12)), detours=detours)
    assert result.error_code is ErrorCode.DETOUR_LIMIT_EXCEEDED


# --- DetourQuote freshness (BR #3) -----------------------------------------------------------------


def test_quotes_for_another_trip_version_or_expired_are_ignored() -> None:
    req = request(KITOB, QARSHI, at(11), at(12))
    stale = DetourMeasurements((quote(KITOB, 1, 3600, 60, 1, trip_version=TRIP_VERSION - 1),))
    assert evaluate_route_match(trip(), req, detours=stale).reasons == (MatchReason.PICKUP_NOT_ON_ROUTE,)
    other_route = DetourMeasurements((quote(KITOB, 1, 3600, 60, 1, route_version_id="rtv_" + "b" * 26),))
    assert not evaluate_route_match(trip(), req, detours=other_route).matched
    fresh = DetourMeasurements((quote(KITOB, 1, 3600, 60, 1),))
    assert evaluate_route_match(trip(), req, detours=fresh, now=MEASURED + timedelta(minutes=5)).matched
    assert not evaluate_route_match(trip(), req, detours=fresh, now=MEASURED + DETOUR_QUOTE_TTL).matched


@pytest.mark.parametrize(
    ("kwargs", "now", "reason"),
    [
        ({"route_version_id": "rtv_" + "b" * 26}, MEASURED, "route_version_changed"),
        ({"trip_version": TRIP_VERSION + 1}, MEASURED, "trip_version_changed"),
        ({}, MEASURED + DETOUR_QUOTE_TTL, "detour_quote_expired"),
        ({"after_seq": 3}, MEASURED, "after_seq_missing"),
        ({"after_seq": 9}, MEASURED, "after_seq_missing"),
    ],
)
def test_validate_detour_quote_rejects_stale_quotes(kwargs: dict, now: datetime, reason: str) -> None:
    params = {"stop": KITOB, "after_seq": 1, "offset_s": 3600, "extra_s": 60, "extra_m": 1}
    params["after_seq"] = kwargs.pop("after_seq", 1)
    q = quote(params["stop"], params["after_seq"], params["offset_s"], params["extra_s"], params["extra_m"], **kwargs)
    with pytest.raises(DomainError) as info:
        validate_detour_quote(q, trip(), now=now)
    assert info.value.code is ErrorCode.ROUTE_CHANGED and info.value.details["reason"] == reason


def test_validate_detour_quote_accepts_fresh_quote() -> None:
    validate_detour_quote(quote(KITOB, 1, 3600, 60, 1), trip(), now=MEASURED + DETOUR_QUOTE_TTL - timedelta(seconds=1))


def test_quote_requires_expiry_after_measurement() -> None:
    with pytest.raises(ValueError):
        quote(KITOB, 1, 1, 1, 1, expires_at=MEASURED)


# --- existing booking windows (BR #4) ---------------------------------------------------------------


def test_insertion_breaking_existing_pickup_window_is_rejected() -> None:
    windows = [
        BookingWindow("bkg_chiroqchi", 2, "pickup", at(12, 0), at(12, 15)),
        BookingWindow("bkg_samarqand", 1, "pickup", at(9, 50), at(10, 10)),  # before the insertion: unaffected
        BookingWindow("bkg_wide", 3, "dropoff", at(13, 0), at(14, 0)),
    ]
    with pytest.raises(DomainError) as info:
        verify_existing_windows(trip(), windows, quote(KITOB, 1, 3600, 1200, 1))
    assert info.value.code is ErrorCode.TIME_WINDOW_CONFLICT
    assert info.value.details == {"reason": "breaks_existing_booking_windows", "bookings": ["bkg_chiroqchi"]}


def test_insertion_within_existing_windows_returns_new_timeline() -> None:
    windows = [BookingWindow("bkg_chiroqchi", 2, "pickup", at(12, 0), at(12, 15)), BookingWindow("bkg_qarshi", 3, "dropoff", at(13, 0), at(13, 30))]
    change = verify_existing_windows(trip(), windows, quote(KITOB, 1, 3600, 300, 1))
    assert change.seq_map[2] == 3 and change.occurrences[3].planned_arrival_at == at(12, 5)


def test_dropoff_window_broken_and_already_broken_window_not_blamed() -> None:
    windows = [
        BookingWindow("bkg_qarshi", 3, "dropoff", at(13, 0), at(13, 5)),
        BookingWindow("bkg_already_late", 2, "pickup", at(8, 0), at(8, 30)),
    ]
    with pytest.raises(DomainError) as info:
        verify_existing_windows(trip(), windows, [quote(KITOB, 1, 3600, 600, 1)])
    assert info.value.details["bookings"] == ["bkg_qarshi"]


# --- loops / determinism ---------------------------------------------------------------------------


def test_loop_route_uses_occurrence_order() -> None:
    a, b, c, d = 21, 22, 23, 24
    loop = trip(stops=((a, 6), (b, 7), (c, 8), (b, 9), (d, 10)))
    c_to_b = evaluate_route_match(loop, request(c, b, at(7, 55), at(8, 10)))
    assert c_to_b.matched and c_to_b.pickup.occurrence_seq == 2 and c_to_b.dropoff.occurrence_seq == 3
    b_to_c = evaluate_route_match(loop, request(b, c, at(6, 55), at(7, 5)))
    assert b_to_c.matched and b_to_c.pickup.occurrence_seq == 1
    late_b = evaluate_route_match(loop, request(b, d, at(8, 55), at(9, 5)))
    assert late_b.matched and late_b.pickup.occurrence_seq == 3
    assert evaluate_route_match(loop, request(d, b, at(5), at(23))).error_code is ErrorCode.ROUTE_MISMATCH
    assert evaluate_route_match(loop, request(b, a, at(5), at(23))).reasons == (MatchReason.REVERSE_DIRECTION,)


def test_best_candidate_is_deterministic() -> None:
    a, b, c = 31, 32, 33
    loop = trip(stops=((a, 6), (b, 7), (a, 8), (b, 9), (c, 10)))
    first = evaluate_route_match(loop, request(a, b, at(5), at(23)))
    assert first == evaluate_route_match(loop, request(a, b, at(5), at(23)))
    assert first.pickup.occurrence_seq == 0 and first.dropoff.occurrence_seq == 1


# --- AC35: routing outage ---------------------------------------------------------------------------

COORDS = {
    TOSHKENT: LatLng(41.3111, 69.2797),
    SAMARQAND: LatLng(39.6542, 66.9597),
    CHIROQCHI: LatLng(39.0336, 66.5722),
    QARSHI: LatLng(38.8606, 65.7847),
    KITOB: LatLng(39.1167, 66.8833),
    GUZOR: LatLng(38.6208, 66.2481),
}


def test_ac35_router_outage_gives_degraded_result_not_a_match() -> None:
    route = trip(stops=((TOSHKENT, 6), (SAMARQAND, 10), (GUZOR, 12), (QARSHI, 13)))
    req = request(KITOB, QARSHI, at(10), at(13))
    measured = measure_detours(FakeRoutingProvider(outage=True), route, req, COORDS, now=MEASURED)
    assert measured.quotes == () and measured.unavailable_stop_ids == {KITOB}
    result = evaluate_route_match(route, req, detours=measured, include_alternatives=True)
    assert not result.matched and result.match_type is None
    assert result.error_code is ErrorCode.ROUTING_UNAVAILABLE and result.degraded
    assert MatchReason.ROUTING_UNAVAILABLE in result.reasons


def test_outage_does_not_block_matches_on_existing_stops() -> None:
    req = request(CHIROQCHI, QARSHI, at(11, 50), at(12, 20))
    provider = FakeRoutingProvider(outage=True)
    measured = measure_detours(provider, trip(), req, COORDS)
    assert provider.calls == []
    assert evaluate_route_match(trip(), req, detours=measured).match_type is MatchType.ON_ROUTE


def test_measure_detours_returns_quotes_bound_to_trip_version() -> None:
    route = trip(stops=((TOSHKENT, 6), (SAMARQAND, 10), (GUZOR, 12), (QARSHI, 13)))
    req = request(KITOB, QARSHI, at(10), at(13))
    one = measure_detours(FakeRoutingProvider(), route, req, COORDS, now=MEASURED)
    assert one == measure_detours(FakeRoutingProvider(), route, req, COORDS, now=MEASURED)
    assert {q.after_seq for q in one.quotes} == {0, 1}
    for q in one.quotes:
        assert (q.route_version_id, q.trip_version, q.provider, q.provider_version) == (ROUTE_PUBLIC_ID, TRIP_VERSION, "fake", "fake-1")
        assert q.measured_at == MEASURED and q.expires_at == MEASURED + DETOUR_QUOTE_TTL
        assert q.extra_s >= 0 and q.extra_m >= 0
        validate_detour_quote(q, route, now=MEASURED)


def test_partial_router_failure_discards_partial_measurements() -> None:
    class FlakyProvider(FakeRoutingProvider):
        def route(self, waypoints):  # noqa: ANN001, ANN201
            if len(self.calls) >= 2:
                self.outage = True
            return super().route(waypoints)

    route = trip(stops=((TOSHKENT, 6), (SAMARQAND, 10), (GUZOR, 12), (QARSHI, 13)))
    measured = measure_detours(FlakyProvider(), route, request(KITOB, QARSHI, at(10), at(13)), COORDS)
    assert measured.quotes == () and measured.unavailable_stop_ids == {KITOB}


# --- input validation ---------------------------------------------------------------------------------


def test_context_validation() -> None:
    with pytest.raises(ValueError):
        trip(stops=((TOSHKENT, 6),))
    with pytest.raises(ValueError):
        TripRouteContext(
            route_version_id=1,
            trip_version=1,
            occurrences=(OccurrenceTiming(1, TOSHKENT, at(6)), OccurrenceTiming(1, QARSHI, at(7))),
            max_detour_minutes=10,
            max_detour_m=10,
        )
    with pytest.raises(ValueError):
        trip(detour_used_s=1801)
    with pytest.raises(ValueError):
        trip(trip_version=0)
    with pytest.raises(ValueError):
        request(TOSHKENT, QARSHI, at(7), at(6))
    with pytest.raises(ValueError):
        OccurrenceTiming(0, TOSHKENT, datetime(2026, 9, 20, 6))
    with pytest.raises(ValueError):
        BookingWindow("b", 1, "pickup", at(7), at(6))


def test_geo_quote_is_a_contract_quote() -> None:
    from app.contracts.detour import DEFAULT_DETOUR_QUOTE_TTL, detour_legs_conflict, total_detour_seconds
    from app.contracts.detour import DetourQuote as ContractDetourQuote

    a, b = quote(KITOB, 1, 3600, 60, 1), quote(GUZOR, 2, 600, 90, 1)
    assert isinstance(a, ContractDetourQuote) and DETOUR_QUOTE_TTL == DEFAULT_DETOUR_QUOTE_TTL
    assert a.is_valid_for(route_version_id=ROUTE_PUBLIC_ID, trip_version=TRIP_VERSION, now=MEASURED)
    assert total_detour_seconds([a, b]) == 150 and not detour_legs_conflict([a, b])


def test_quotes_need_route_version_public_id() -> None:
    no_public = TripRouteContext(route_version_id=ROUTE_VERSION, trip_version=TRIP_VERSION, occurrences=occurrences(), max_detour_minutes=30, max_detour_m=1)
    with pytest.raises(ValueError, match="route_version_public_id"):
        measure_detours(FakeRoutingProvider(), no_public, request(KITOB, QARSHI, at(10), at(13)), COORDS)
    with pytest.raises(ValueError, match="route_version_public_id"):
        validate_detour_quote(quote(KITOB, 1, 1, 1, 1), no_public, now=MEASURED)
    detours = DetourMeasurements((quote(KITOB, 1, 3600, 60, 1),))
    with pytest.raises(ValueError, match="route_version_public_id"):  # BR N3: explicit, not a silent off-route
        evaluate_route_match(no_public, request(KITOB, QARSHI, at(11), at(12)), detours=detours)
    # Without quotes a context lacking the public id still matches on existing stops.
    assert evaluate_route_match(no_public, request(SAMARQAND, QARSHI, at(9, 55), at(10, 5))).matched
