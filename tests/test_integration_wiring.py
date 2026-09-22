"""Wave-1 integration wiring: v2 routers, health probes, single v2 DomainError envelope, ports."""

from collections import Counter

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.contracts.dto import ErrorEnvelope
from app.contracts.errors import DomainError, ErrorCode
from app.main import app, create_app


def _paths() -> set[str]:
    return set(app.openapi()["paths"])


def test_all_wave1_v2_routes_and_probes_are_mounted() -> None:
    paths = _paths()
    for expected in (
        "/api/v2/me",
        "/api/v2/me/roles",
        "/api/v2/regions",
        "/api/v2/admin/feature-flags",
        "/api/v2/trips",
        "/api/v2/trips/{trip_id}/availability",
        "/api/v2/listings",
        "/api/v2/proposals/{thread_id}/counter",
        "/api/v2/wallet",
        "/api/v2/admin/commission-policies",
        "/api/v2/admin/ledger/adjustments",
        "/health/live",
        "/health/ready",
        "/api/v1/health",
    ):
        assert expected in paths, expected
    assert not any(p.startswith("/api/v2/api/") for p in paths)


def test_no_duplicate_method_and_path() -> None:
    pairs = Counter(
        (method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods
    )
    assert [pair for pair, count in pairs.items() if count > 1] == []


def test_single_v2_domain_error_envelope_and_v1_unchanged() -> None:
    probe_app = create_app()

    @probe_app.get("/api/v2/_probe_domain_error")
    def _probe() -> None:
        raise DomainError(ErrorCode.CAPACITY_UNAVAILABLE, details={"segment": "B-C"})

    @probe_app.get("/api/v1/_probe_domain_error")
    def _probe_v1() -> None:
        raise DomainError(ErrorCode.CAPACITY_UNAVAILABLE)

    client = TestClient(probe_app)
    response = client.get("/api/v2/_probe_domain_error", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 409
    body = ErrorEnvelope.model_validate(response.json())
    assert body.error.code == "CAPACITY_UNAVAILABLE"
    assert body.error.details == {"segment": "B-C"}
    assert body.error.request_id == "req-123"

    # A DomainError outside /api/v2 is not rendered as a v2 envelope.
    stray = client.get("/api/v1/_probe_domain_error")
    assert stray.status_code == 500
    assert stray.json() == {"success": False, "error": {"code": "SERVER_ERROR", "message": "Internal server error"}}

    # v1 errors still go through the v1 HTTPException handler (unchanged envelope).
    v1 = client.get("/api/v1/auth/me")
    assert v1.status_code == 401
    assert v1.json() == {"success": False, "error": {"code": "UNAUTHORIZED", "message": "Authentication required"}}


def test_identity_web_shim_re_exports_moved_plumbing() -> None:
    import app.api.v2.web as moved
    import app.modules.identity.web as shim

    for name in ("run_command", "run_versioned", "domain_error_handler", "get_session", "current_user_id", "page_scope"):
        assert getattr(shim, name) is getattr(moved, name)


def test_ports_are_configured_with_a1_adapters() -> None:
    from app.modules.marketplace.adapters import FlagServiceAdapter, WalletFeeAdapter
    from app.modules.marketplace.ports import get_ports
    from app.modules.trips.adapters import GeoServiceAdapter
    from app.modules.trips.ports import get_geo_port

    create_app()  # wiring is idempotent
    ports = get_ports()
    assert isinstance(ports.geo, GeoServiceAdapter)
    assert isinstance(ports.flags, FlagServiceAdapter)
    assert isinstance(ports.fees, WalletFeeAdapter)
    assert isinstance(get_geo_port(), GeoServiceAdapter)


def test_health_live() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
