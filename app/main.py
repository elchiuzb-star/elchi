from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api.v1 import api_router
from app.core.config import settings

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
    app.mount(
        settings.public_upload_base_url,
        StaticFiles(directory=settings.upload_dir),
        name="uploads",
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):  # noqa: ANN001
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

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
