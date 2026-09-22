"""HTTP plumbing shared by the v2 routers (moved from ``app.modules.identity.web``, integration pass 2).

* ``get_session`` / ``current_user_id``: v1 bearer token (ADR-0007) and the request's DB session.
* ``run_command``: idempotent command (ADR-0005) over ``app.modules.platform.service.run_idempotent``;
  commits on 2xx and on a stored domain 4xx, rolls back otherwise.
* ``run_versioned``: non-idempotent versioned mutation (PATCH); commits or rolls back.
* ``domain_error_handler``: renders ``DomainError`` as the v2 ``ErrorEnvelope`` (the single v2
  handler; ``app.main`` applies it to ``/api/v2`` paths only).
* Signed keyset cursors (``crypto.PURPOSE_CURSOR_SIGNING``).

Behaviour is unchanged by the move; ``app.modules.identity.web`` re-exports every name.
A3's wallet router keeps its own equivalent helpers (it renders envelopes itself).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, Request, status as status_codes
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.contracts.cursor import CursorValue, decode_cursor, encode_cursor
from app.contracts.db_errors import map_db_error
from app.contracts.dto import ApiWarning, ErrorEnvelope, PageMeta
from app.contracts.errors import ERROR_CATALOGUE, WARNING_CATALOGUE, DomainError, ErrorCode, WarningCode
from app.contracts.idempotency import IDEMPOTENT_REPLAY_HEADER
from app.contracts.timeutil import parse_iso_datetime, to_iso_utc
from app.core.config import cursor_signing_secret, settings
from app.db.session import get_db
from app.models import User
from app.modules.platform.service import (
    CommandResult,
    constraint_name_of,
    domain_error_body,
    run_idempotent,
    run_with_db_retry,
    sqlstate_of,
)

T = TypeVar("T")
logger = logging.getLogger("elchi.api.v2")

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 409, 429)
}


def get_session(db: Session = Depends(get_db)) -> Session:
    return db


_optional_bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/verify-otp", auto_error=False)
# Same scheme, never auto-erroring: the token is read again only to check the §17.6 session claim.
_session_bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/verify-otp", auto_error=False)


def current_user_id(
    user: User = Depends(get_current_user),
    token: str | None = Depends(_session_bearer),
    db: Session = Depends(get_db),
) -> int:
    """Authenticated caller of a v2 route.

    ``get_current_user`` already checks the token and binds ``actor_id`` for JSON logs (BR #13). Wave 6 adds
    §17.6 on the v2 surface: an access token whose **login session** was revoked (logout, refresh rotation, admin
    revoke) is refused at once instead of staying usable until it expires. v1 keeps its previous behaviour - that
    would be a v1 contract change and needs its own decision.
    """
    if token:
        from app.core.security import verify_token
        from app.services.auth_service import session_revoked

        if session_revoked(db, verify_token(token)):
            raise HTTPException(status_code=status_codes.HTTP_401_UNAUTHORIZED, detail="Session revoked.")
    return user.id




def optional_user_id(token: str | None = Depends(_optional_bearer), db: Session = Depends(get_db)) -> int | None:
    """Public endpoints that show more to an authenticated owner (L2, T8). A bad token is still 401."""
    if not token:
        return None
    return get_current_user(token=token, db=db).id


def envelope_body(
    dto: BaseModel | Sequence[BaseModel],
    meta: PageMeta | None = None,
    warnings: Sequence[ApiWarning] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True, "data": None, "message": None, "meta": None}
    if isinstance(dto, BaseModel):
        body["data"] = dto.model_dump(mode="json")
    else:
        body["data"] = [item.model_dump(mode="json") for item in dto]
    if meta is not None:
        body["meta"] = meta.model_dump(mode="json")
    if warnings:
        # Wave 1.6 (Q43): e.g. CONTACT_INFO_MASKED; the key is omitted when there is nothing to report.
        body["warnings"] = [warning.model_dump(mode="json") for warning in warnings]
    return body


def to_api_warnings(items: Sequence[Any] | None) -> list[ApiWarning]:
    """Normalise handler warnings into envelope ``ApiWarning`` items (wave 1.6, Q43).

    Accepts ``ApiWarning``, other pydantic models or dicts such as the marketplace free-text warning
    ``{code, field, categories, match_count, filter_version}``; unknown keys become ``details``.
    """
    result: list[ApiWarning] = []
    for item in items or ():
        if isinstance(item, ApiWarning):
            result.append(item)
            continue
        data = item.model_dump(mode="json") if isinstance(item, BaseModel) else dict(item)
        code = str(data.pop("code"))
        field = data.pop("field", None)
        message = data.pop("message", None)
        details = data.pop("details", None)
        if details is None:
            details = data or None
        if message is None:
            try:
                message = WARNING_CATALOGUE[WarningCode(code)]
            except ValueError:
                message = code
        result.append(ApiWarning(code=code, message=message, field=field, details=details))
    return result


def split_handler_result(result: Any) -> tuple[Any, list[ApiWarning]]:
    """A handler returns a DTO, or ``(dto, warnings)`` when it has non-fatal warnings to report."""
    if isinstance(result, tuple):
        dto, warnings = result
        return dto, to_api_warnings(warnings)
    return result, []


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path_format", None) or getattr(route, "path", None) or request.url.path


def run_command(
    request: Request,
    session: Session,
    *,
    actor_user_id: int,
    idempotency_key: str | None,
    body: BaseModel | None,
    handler: Callable[[], BaseModel | tuple[BaseModel, Sequence[Any]]],
    success_status: int = 200,
    resource_type: str | None = None,
    after_command: Callable[[bool], None] | None = None,
) -> JSONResponse:
    """Execute a command once per ``Idempotency-Key`` and return its (possibly replayed) envelope.

    ``after_command(replayed)`` (wave 2) runs in the same transaction after the idempotent step, before the
    commit and inside the deadlock retry: a side effect that must survive the handler's rolled-back domain
    4xx savepoint (e.g. counting a wrong proof code, spec §11). It must not write on a replay.

    ``handler`` must build its DTO before returning (the commit expires ORM state). It may return
    ``(dto, warnings)``; warnings go to ``Envelope.warnings`` and are stored with the response, so an
    idempotent replay returns the same warnings.
    Domain 4xx are stored and replayed without domain writes (savepoint, BR D8).
    """

    def wrapped() -> CommandResult:
        dto, warnings = split_handler_result(handler())
        return CommandResult(
            status_code=success_status,
            body=envelope_body(dto, warnings=warnings),
            resource_type=resource_type,
            resource_id=getattr(dto, "id", None),
        )

    def attempt():  # noqa: ANN202 - IdempotentResponse
        result = run_idempotent(
            session,
            actor_user_id=actor_user_id,
            method=request.method,
            route_template=_route_template(request),
            idempotency_key=idempotency_key,
            body=None if body is None else body.model_dump(mode="json"),
            handler=wrapped,
            path_params=dict(request.path_params),
        )
        if after_command is not None:
            after_command(result.replayed)
        session.commit()
        return result

    try:
        # Deadlock/serialization (40P01/40001): whole transaction rolled back and retried with the
        # same key, at most 3 attempts, then 503 SERVICE_UNAVAILABLE (ADR-0017 §5).
        result = run_with_db_retry(session, attempt)
    except BaseException:
        session.rollback()
        raise
    headers = {IDEMPOTENT_REPLAY_HEADER: "true"} if result.replayed else None
    return JSONResponse(status_code=result.status_code, content=result.body, headers=headers)


def run_versioned(session: Session, handler: Callable[[], T]) -> T:
    """Non-idempotent versioned mutation (``expected_version`` guards replays); retried like commands."""

    def attempt() -> T:
        result = handler()
        session.commit()
        return result

    try:
        return run_with_db_retry(session, attempt)
    except BaseException:
        session.rollback()
        raise


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status, content=domain_error_body(exc, request.headers.get("X-Request-ID"))
    )


def db_error_to_domain_error(exc: DBAPIError) -> DomainError:
    """Wave 2.1: a non-retryable DB error (deferred trigger, CHECK, unique, guard trigger) as a v2 ``DomainError``.

    Rules live in ``app.contracts.db_errors``; ``details`` carry only ``reason`` - the DB message, constraint and
    SQLSTATE are logged, never returned.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    sqlstate = sqlstate_of(exc)
    constraint = constraint_name_of(exc)
    message = getattr(diag, "message_primary", None) if diag is not None else None
    if message is None and orig is not None:
        message = str(orig).split("\n", 1)[0]
    rule = map_db_error(
        sqlstate=sqlstate,
        constraint=constraint,
        message=message,
        connection_lost=bool(getattr(exc, "connection_invalidated", False)),
    )
    log = logger.error if ERROR_CATALOGUE[rule.code].http_status >= 500 else logger.warning
    log("v2 DB error mapped: sqlstate=%s constraint=%s code=%s reason=%s message=%s",
        sqlstate, constraint, rule.code.value, rule.reason, message)
    return DomainError(rule.code, details={"reason": rule.reason})


async def db_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Renders DB errors that escaped the services of an ``/api/v2`` request as ``ErrorEnvelope`` (not stored for
    idempotent replay: the transaction was rolled back). ``app.main`` applies it to ``/api/v2`` paths only."""
    return await domain_error_handler(request, db_error_to_domain_error(exc))


# --- cursors -------------------------------------------------------------------------------------


def _cursor_secret() -> bytes:
    return cursor_signing_secret(settings)


def page_scope(endpoint: str, **filters: object) -> str:
    parts = [endpoint] + [f"{key}={filters[key]}" for key in sorted(filters) if filters[key] is not None]
    return "|".join(parts)


def encode_page_cursor(values: Sequence[CursorValue | datetime], scope: str) -> str:
    return encode_cursor(
        [to_iso_utc(value) if isinstance(value, datetime) else value for value in values],
        scope=scope,
        secret=_cursor_secret(),
    )


def decode_time_id_cursor(token: str | None, scope: str) -> tuple[datetime, int] | None:
    if token is None:
        return None
    values = decode_cursor(token, scope=scope, secret=_cursor_secret())
    try:
        moment, row_id = values
        if isinstance(row_id, bool) or not isinstance(row_id, int) or not isinstance(moment, str):
            raise ValueError
        return parse_iso_datetime(moment), row_id
    except (TypeError, ValueError):
        raise DomainError(ErrorCode.INVALID_CURSOR) from None


def decode_id_cursor(token: str | None, scope: str) -> int | None:
    if token is None:
        return None
    values = decode_cursor(token, scope=scope, secret=_cursor_secret())
    if len(values) != 1 or isinstance(values[0], bool) or not isinstance(values[0], int):
        raise DomainError(ErrorCode.INVALID_CURSOR)
    return values[0]
