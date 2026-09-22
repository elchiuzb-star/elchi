import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

from app.api.health_probes import router as health_probes_router
from app.api.v1 import api_router
from app.api.v2 import API_V2_PREFIX
from app.api.v2.router import api_router as api_v2_router
from app.api.v2.router import configure_v2_ports
from app.api.v2.web import db_error_handler as v2_db_error_handler
from app.api.v2.web import domain_error_handler as v2_domain_error_handler
from app.contracts.errors import DomainError
from app.core.config import settings
from app.modules import import_models
from app.ops.request_id import RequestIdMiddleware

import_models()

logger = logging.getLogger("elchi.api")

OPENAPI_TAGS = [
    {"name": "Health", "description": "Health check and service status."},
    {"name": "Auth", "description": "OTP login, token refresh, logout, and current user."},
    {"name": "Files", "description": "Authenticated upload of allowed MVP image/document files."},
    {"name": "Cities", "description": "Public city list."},
    {"name": "Route Tariffs", "description": "Suggested route pricing for authenticated users."},
    {"name": "Client Orders", "description": "Client order lifecycle, selection, confirmation, and rating."},
    {"name": "Driver Profile", "description": "Driver profile, documents, availability, and routes."},
    {"name": "Driver Orders", "description": "Driver feed, limited order detail, assigned order detail, and order rejection."},
    {"name": "Driver Bids", "description": "Driver bid creation and updates."},
    {"name": "Order Status", "description": "Assigned driver delivery status transitions."},
    {"name": "Disputes", "description": "User and admin dispute workflows."},
    {"name": "Notifications", "description": "In-app notification list and read state."},
    {"name": "Admin Orders", "description": "Operator/admin order review and manual interventions."},
    {"name": "Admin Drivers", "description": "Driver review, approval, rejection, and blocking."},
    {"name": "Admin Disputes", "description": "Operator/admin dispute review and resolution."},
    {"name": "Audit Logs", "description": "Admin/super admin read-only audit log access."},
]


def create_app() -> FastAPI:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app = FastAPI(
        title="Intercity Parcel Delivery Marketplace API",
        debug=settings.debug,
        version="1.0.0-mvp",
        description=(
            "Backend API for the MVP intercity parcel delivery marketplace. "
            "Clients create parcel orders, approved drivers bid by route, clients select a driver, "
            "drivers update delivery statuses, and clients confirm delivery. Payment is cash only."
        ),
        openapi_tags=OPENAPI_TAGS,
    )
    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_origin_regex=settings.cors_origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # Stage-2 API (ADR-0005) and prefix-less liveness/readiness probes (§19.2, BR N1).
    configure_v2_ports()
    app.include_router(api_v2_router, prefix=API_V2_PREFIX)
    app.include_router(health_probes_router)
    # Uploads are private: there is deliberately no public static mount. Files
    # are served only via signed URLs from GET /api/v1/files/{key} (see
    # app/utils/file_access.py).

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):  # noqa: ANN001
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # Added last so it is the outermost middleware: X-Request-ID on every response and the
    # request_id log context (BR #13). Bodies and status codes are untouched.
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):  # noqa: ANN201
        # The single v2 handler (app.api.v2.web) renders ErrorEnvelope for /api/v2 paths only.
        # v1 code never raises DomainError; if one ever escapes elsewhere it is a bug and is
        # answered with the generic v1 500 envelope, so v1 error handling stays unchanged.
        if request.url.path == API_V2_PREFIX or request.url.path.startswith(API_V2_PREFIX + "/"):
            return await v2_domain_error_handler(request, exc)
        logger.error("DomainError outside /api/v2: %s %s -> %s", request.method, request.url.path, exc.code)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": {"code": "SERVER_ERROR", "message": "Internal server error"}},
        )

    @app.exception_handler(DBAPIError)
    async def db_error_handler(request: Request, exc: DBAPIError):  # noqa: ANN201
        # Wave 2.1: DB-raised errors (deferred triggers, constraints) on /api/v2 get the v2 ErrorEnvelope via
        # app.contracts.db_errors. Elsewhere the exception is re-raised, so v1 behaviour is unchanged.
        if request.url.path == API_V2_PREFIX or request.url.path.startswith(API_V2_PREFIX + "/"):
            return await v2_db_error_handler(request, exc)
        raise exc

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):  # noqa: ANN001
        code = "SERVER_ERROR"
        message = str(exc.detail)
        if exc.status_code == 401:
            code = "UNAUTHORIZED"
            message = "Authentication required"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 400:
            code = "VALIDATION_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": {"code": code, "message": message}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):  # noqa: ANN001
        errors = []
        for error in exc.errors():
            sanitized = dict(error)
            if "ctx" in sanitized:
                sanitized["ctx"] = {key: str(value) for key, value in sanitized["ctx"].items()}
            errors.append(sanitized)
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder({
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid input",
                    "details": {"errors": errors},
                },
            }),
        )

    return app


app = create_app()
