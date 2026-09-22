"""Routing adapter tests: fake determinism, hosted adapter contract (recorded fake), outage, tx guard,
production refusal (decision 24), attribution (BR #16), key hygiene (BR #11)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.modules.geo.config import PRODUCTION_PROVIDER_REFUSAL, GeoSettings, build_routing_provider
from app.modules.geo.geometry import encode_polyline, haversine_m, linestring_ewkt, point_ewkt
from app.modules.geo.routing import (
    DisabledRoutingProvider,
    FakeRoutingProvider,
    GeoapifyRoutingProvider,
    OsrmRoutingProvider,
    RouteResult,
    RoutingUnavailable,
    assert_outside_transaction,
    route_outside_transaction,
)
from app.modules.geo.routing.base import PROVIDER_ATTRIBUTIONS
from app.modules.geo.routing.geoapify import parse_geoapify_response
from app.modules.geo.types import LatLng

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "geo" / "geoapify_routing_response.json"
TOSHKENT = LatLng(41.2869, 69.2025)
SAMARQAND = LatLng(39.6542, 66.9597)
QARSHI = LatLng(38.8606, 65.7847)
SECRET = "test-key-never-leaks-0123456789"


def test_fake_router_is_deterministic_and_integer() -> None:
    a = FakeRoutingProvider().route([TOSHKENT, SAMARQAND, QARSHI])
    assert a == FakeRoutingProvider().route([TOSHKENT, SAMARQAND, QARSHI])
    assert a.distance_m == sum(leg.distance_m for leg in a.legs) and isinstance(a.distance_m, int)
    assert a.duration_s == sum(leg.duration_s for leg in a.legs)
    assert a.is_estimate and a.provider == "fake"
    assert 1.2 < a.legs[0].distance_m / haversine_m(TOSHKENT, SAMARQAND) < 1.3


def test_haversine_metres() -> None:
    assert 995 < haversine_m(LatLng(41.2995, 69.2401), LatLng(41.3085, 69.2401)) < 1005


def test_fake_outage_raises() -> None:
    with pytest.raises(RoutingUnavailable) as info:
        FakeRoutingProvider(outage=True).route([TOSHKENT, QARSHI])
    assert info.value.reason == "fake_outage"


def _transport(status: int = 200, body: object | None = None, exc: Exception | None = None, seen: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if exc is not None:
            raise exc
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.MockTransport(handler)


def test_geoapify_contract_parses_recorded_response() -> None:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    seen: list[httpx.Request] = []
    provider = GeoapifyRoutingProvider(SECRET, transport=_transport(body=body, seen=seen))
    result = provider.route([TOSHKENT, SAMARQAND, QARSHI])
    assert (result.distance_m, result.duration_s) == (437812, 19689)
    assert [(leg.distance_m, leg.duration_s) for leg in result.legs] == [(301004, 12912), (136808, 6777)]
    assert result.geometry[0] == TOSHKENT and result.geometry[-1] == QARSHI and len(result.geometry) == 6
    request = seen[0]
    assert request.url.params["waypoints"] == "41.286900,69.202500|39.654200,66.959700|38.860600,65.784700"
    assert request.url.params["mode"] == "drive" and request.url.scheme == "https"
    assert SECRET not in repr(provider)


@pytest.mark.parametrize(
    ("status", "reason"),
    [(429, "quota"), (401, "auth"), (403, "auth"), (500, "upstream_error"), (503, "upstream_error"), (400, "http_400")],
)
def test_geoapify_http_errors_are_routing_unavailable(status: int, reason: str) -> None:
    provider = GeoapifyRoutingProvider(SECRET, transport=_transport(status=status, body={"error": "x"}))
    with pytest.raises(RoutingUnavailable) as info:
        provider.route([TOSHKENT, QARSHI])
    assert info.value.reason == reason and SECRET not in str(info.value)


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectTimeout("t"), httpx.ConnectError(f"boom https://api.geoapify.com/v1/routing?apiKey={SECRET}")],
)
def test_geoapify_network_errors_never_leak_key(exc: Exception) -> None:
    provider = GeoapifyRoutingProvider(SECRET, transport=_transport(exc=exc))
    with pytest.raises(RoutingUnavailable) as info:
        provider.route([TOSHKENT, QARSHI])
    assert SECRET not in str(info.value) and info.value.__cause__ is None


def test_httpx_request_logs_with_api_key_are_suppressed(caplog: pytest.LogCaptureFixture) -> None:
    """Fails without suppression: httpx logs ``HTTP Request: GET <url with apiKey>`` at INFO."""
    import importlib

    import app.modules.geo.routing.geoapify as geoapify_module

    loggers = [logging.getLogger("httpx"), logging.getLogger("httpcore")]
    saved = [lg.level for lg in loggers]
    try:
        for lg in loggers:
            lg.setLevel(logging.NOTSET)  # inherit DEBUG from root below: httpx would log the URL
        caplog.set_level(logging.DEBUG)
        importlib.reload(geoapify_module)  # module import must re-apply the suppression
        assert all(lg.getEffectiveLevel() >= logging.WARNING for lg in loggers)
        body = json.loads(FIXTURE.read_text(encoding="utf-8"))
        provider = geoapify_module.GeoapifyRoutingProvider(SECRET, transport=_transport(body=body))
        provider.route([TOSHKENT, SAMARQAND, QARSHI])
        assert SECRET not in caplog.text
        assert all(SECRET not in record.getMessage() for record in caplog.records)
    finally:
        for lg, level in zip(loggers, saved):
            lg.setLevel(level)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"features": []},
        {"features": [{"properties": {"distance": -1, "time": 1, "legs": [{"distance": 1, "time": 1}]}, "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}}]},
        {"features": [{"properties": {"distance": 10, "time": 1, "legs": []}, "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}}]},
        {"features": [{"properties": {"distance": 10, "time": 1, "legs": [{"distance": 1, "time": 1}]}, "geometry": {"type": "Point", "coordinates": [1, 1]}}]},
        {"features": [{"properties": {"distance": 10, "time": float("nan"), "legs": [{"distance": 1, "time": 1}]}, "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}}]},
    ],
)
def test_geoapify_malformed_responses_are_not_trusted(body: dict) -> None:
    with pytest.raises(RoutingUnavailable) as info:
        parse_geoapify_response(body, waypoint_count=2)
    assert info.value.reason == "bad_response"


def test_decision_24_no_routing_provider_in_production() -> None:
    for provider_name in ("fake", "geoapify", "disabled"):
        settings = GeoSettings(routing_provider=provider_name, geoapify_api_key=SECRET)
        refused = build_routing_provider(settings, production=True)
        assert isinstance(refused, DisabledRoutingProvider) and refused.reason == PRODUCTION_PROVIDER_REFUSAL
        with pytest.raises(RoutingUnavailable):
            refused.route([TOSHKENT, QARSHI])
    assert isinstance(build_routing_provider(GeoSettings(routing_provider="fake"), production=False), FakeRoutingProvider)
    assert isinstance(build_routing_provider(GeoSettings(routing_provider="geoapify"), production=False), DisabledRoutingProvider)
    assert isinstance(build_routing_provider(GeoSettings(routing_provider="geoapify", geoapify_api_key=SECRET), production=False), GeoapifyRoutingProvider)
    assert SECRET not in repr(GeoSettings(geoapify_api_key=SECRET))


def test_providers_carry_attribution() -> None:
    assert FakeRoutingProvider.attribution == PROVIDER_ATTRIBUTIONS["fake"]
    assert GeoapifyRoutingProvider.attribution == PROVIDER_ATTRIBUTIONS["geoapify"]
    assert "OpenStreetMap" in PROVIDER_ATTRIBUTIONS["geoapify"]


def test_router_refuses_to_run_inside_a_db_transaction() -> None:
    engine = create_engine("sqlite://")
    provider = FakeRoutingProvider()
    with Session(engine) as session:
        assert_outside_transaction(session)
        route_outside_transaction(session, provider, [TOSHKENT, QARSHI])
        session.execute(text("SELECT 1"))
        with pytest.raises(RuntimeError, match="transaction"):
            route_outside_transaction(session, provider, [TOSHKENT, QARSHI])
        session.rollback()
        route_outside_transaction(session, provider, [TOSHKENT, QARSHI])
    assert len(provider.calls) == 2


def test_route_result_cache_roundtrip_and_encoders() -> None:
    result = FakeRoutingProvider().route([TOSHKENT, SAMARQAND, QARSHI])
    assert RouteResult.from_cache_json(json.loads(json.dumps(result.to_cache_json()))) == result
    assert encode_polyline([LatLng(38.5, -120.2), LatLng(40.7, -120.95), LatLng(43.252, -126.453)]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    assert point_ewkt(TOSHKENT) == "SRID=4326;POINT(69.2025 41.2869)"
    assert linestring_ewkt([TOSHKENT, QARSHI]).startswith("SRID=4326;LINESTRING(69.2025 41.2869, ")


def test_latlng_validation() -> None:
    for bad in ((91, 0), (0, 181), (float("nan"), 0), (True, 0)):
        with pytest.raises((ValueError, TypeError)):
            LatLng(*bad)


# --- OSRM: our own router (no third party, so no key and no external data flow) ---------------------------

OSRM_BODY = {
    "code": "Ok",
    "routes": [
        {
            "distance": 437812.4,
            "duration": 19689.1,
            "legs": [
                {"distance": 301004.0, "duration": 12912.2},
                {"distance": 136808.4, "duration": 6776.9},
            ],
            # GeoJSON order: longitude first. The adapter must flip it, or every route is drawn in China.
            "geometry": {
                "type": "LineString",
                "coordinates": [[69.2025, 41.2869], [67.5, 40.4], [66.9597, 39.6542], [65.7847, 38.8606]],
            },
        }
    ],
}


def test_osrm_parses_a_route_and_flips_geojson_order() -> None:
    seen: list[httpx.Request] = []
    provider = OsrmRoutingProvider(transport=_transport(body=OSRM_BODY, seen=seen))
    result = provider.route([TOSHKENT, SAMARQAND, QARSHI])

    assert (result.distance_m, result.duration_s) == (437812, 19689)
    assert [(leg.distance_m, leg.duration_s) for leg in result.legs] == [(301004, 12912), (136808, 6777)]
    assert result.geometry[0] == TOSHKENT and result.geometry[-1] == QARSHI
    # A routed answer over a real network, not the straight-line guess `fake` produces.
    assert result.is_estimate is False and result.provider == "osrm"

    request = seen[0]
    assert request.url.path == "/route/v1/driving/69.202500,41.286900;66.959700,39.654200;65.784700,38.860600"
    assert request.url.params["geometries"] == "geojson"
    assert request.url.params["overview"] == "full"


@pytest.mark.parametrize("code", ["NoRoute", "NoSegment", "NoTrips"])
def test_osrm_no_route_is_not_a_guess(code: str) -> None:
    """Two places with no road between them is an answer, and it must not become a straight line (AC35)."""
    provider = OsrmRoutingProvider(transport=_transport(status=400, body={"code": code, "message": "x"}))
    with pytest.raises(RoutingUnavailable) as info:
        provider.route([TOSHKENT, QARSHI])
    assert info.value.reason == "no_route" and info.value.provider == "osrm"


@pytest.mark.parametrize(
    "body",
    [
        {"code": "Ok", "routes": []},
        {"code": "Ok", "routes": [{"distance": 1, "duration": 1, "legs": [], "geometry": {"coordinates": []}}]},
        # One leg per gap between waypoints, or legs cannot be lined up with stops.
        {"code": "Ok", "routes": [{"distance": 1, "duration": 1, "legs": [{"distance": 1, "duration": 1}],
                                   "geometry": {"coordinates": [[69.2, 41.2], [65.7, 38.8]]}}]},
        {"code": "Ok", "routes": [{"distance": 1, "duration": 1}]},
        {"routes": [{"distance": 1, "duration": 1}]},
        [],
    ],
)
def test_osrm_malformed_responses_are_not_trusted(body: object) -> None:
    provider = OsrmRoutingProvider(transport=_transport(body=body))
    with pytest.raises(RoutingUnavailable):
        provider.route([TOSHKENT, SAMARQAND, QARSHI])


def test_osrm_container_being_down_is_an_outage_not_a_route() -> None:
    provider = OsrmRoutingProvider(transport=_transport(exc=httpx.ConnectError("connection refused")))
    with pytest.raises(RoutingUnavailable) as info:
        provider.route([TOSHKENT, QARSHI])
    assert info.value.reason == "network"


def test_osrm_is_selectable_but_still_refused_in_production() -> None:
    """Decision 24 is about *routing in production*, not about who owns the router."""
    settings = GeoSettings(routing_provider="osrm", osrm_base_url="http://127.0.0.1:5000")
    assert isinstance(build_routing_provider(settings, production=False), OsrmRoutingProvider)
    refused = build_routing_provider(settings, production=True)
    assert isinstance(refused, DisabledRoutingProvider) and refused.reason == PRODUCTION_PROVIDER_REFUSAL


def test_osrm_needs_no_credentials() -> None:
    """There is no third party to authenticate to, so there is no key that could leak."""
    provider = OsrmRoutingProvider(base_url="http://127.0.0.1:5000")
    assert "key" not in repr(provider).lower()
    assert PROVIDER_ATTRIBUTIONS["osrm"] == OsrmRoutingProvider.attribution
