"""Platform domain API (A3): idempotency (ADR-0005 savepoint pattern), outbox, environment marker.

Public functions take the caller's ``Session`` and never commit; the API layer
commits (or rolls back) the single transaction (spec §15).

Idempotency flow (``run_idempotent``)::

    BEGIN (caller)
      acquire_idempotency   INSERT ... ON CONFLICT DO NOTHING; SELECT ... FOR UPDATE
                            other hash      -> DomainError IDEMPOTENCY_KEY_REUSED (409, not stored)
                            completed       -> stored status/body, replayed=True
                            lock wait > 5 s -> DomainError IDEMPOTENCY_IN_PROGRESS (409, tx aborted)
      SAVEPOINT command
        handler()           domain locks + writes
      success -> RELEASE; store 2xx body
      DomainError 4xx -> ROLLBACK TO SAVEPOINT (domain writes undone); store 4xx body
      DomainError 5xx / any other exception -> re-raised, caller rolls back everything
    COMMIT (caller)

Environment marker (BR N1): the singleton row ``platform_environment(id=1)`` says
which deployment environment this *database* belongs to. It is seeded by
migration 0031 from ``ELCHI_ENVIRONMENT`` (never downgraded automatically) and can
be set by deploy tooling with ``python -m app.modules.platform.environment``.
DB triggers (0031, 0041) refuse to leave ``production`` and refuse
``wallet_accounts.test_overdraft_allowed = true`` while the marker is ``production``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.idempotency import (
    IDEMPOTENCY_RECORD_TTL,
    record_scope,
    request_hash,
    validate_idempotency_key,
)
from app.contracts.timeutil import utc_now
from app.modules.platform.models import IdempotencyRecord, OutboxEvent, PlatformEnvironment

__all__ = [
    "CommandResult",
    "DbMarkerState",
    "DeploymentEnvironment",
    "ENVIRONMENT_ALIASES",
    "get_db_marker_state",
    "IdempotencyClaim",
    "IdempotentResponse",
    "RETRYABLE_SQLSTATES",
    "acquire_idempotency",
    "app_environment",
    "complete_idempotency",
    "constraint_name_of",
    "enqueue_event",
    "get_db_environment",
    "is_production",
    "is_retryable_db_error",
    "lookup_idempotent_response",
    "GateCheck",
    "GateReport",
    "q48_gate_status",
    "normalize_environment",
    "run_idempotent",
    "run_with_db_retry",
    "set_db_environment",
    "sqlstate_of",
    "table_exists",
]

IDEMPOTENCY_LOCK_TIMEOUT = "5s"
STATE_PROCESSING = "processing"
STATE_COMPLETED = "completed"
# Deadlock and serialization failure: retried with the same idempotency key (ADR-0017 §5).
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})
LOCK_NOT_AVAILABLE = "55P03"

T = TypeVar("T")


# --- DB error helpers ------------------------------------------------------------------


def sqlstate_of(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def constraint_name_of(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None) if diag is not None else None


def is_retryable_db_error(exc: BaseException) -> bool:
    return isinstance(exc, DBAPIError) and sqlstate_of(exc) in RETRYABLE_SQLSTATES


def run_with_db_retry(session: Session, fn: Callable[[], T], *, attempts: int = 3) -> T:
    """Run ``fn`` (which must include its own commit); retry deadlock/serialization failures.

    Each failed attempt rolls back the whole transaction. After ``attempts``
    failures the caller gets ``503 SERVICE_UNAVAILABLE`` (ADR-0017 §5).
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for _ in range(attempts):
        try:
            return fn()
        except DBAPIError as exc:
            session.rollback()
            if not is_retryable_db_error(exc):
                raise
    raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "db_contention_retries_exhausted"})


def table_exists(session: Session, table_name: str) -> bool:
    """True if the table exists (the legacy SQLite suite may not have created v2 tables)."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return session.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table_name}).scalar_one()
    from sqlalchemy import inspect

    return inspect(session.connection()).has_table(table_name)


# --- Idempotency ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What a domain handler returns: HTTP status and a JSON-serialisable body."""

    status_code: int
    body: Any
    resource_type: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class IdempotentResponse:
    status_code: int
    body: Any
    replayed: bool
    resource_type: str | None = None
    resource_id: str | None = None


@dataclass(slots=True)
class IdempotencyClaim:
    record: IdempotencyRecord
    replay: IdempotentResponse | None


def acquire_idempotency(
    session: Session,
    *,
    actor_user_id: int,
    method: str,
    route_template: str,
    idempotency_key: str | None,
    body: Any,
    path_params: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> IdempotencyClaim:
    """Claim ``(actor, METHOD route, key)`` or return the stored response for a replay."""
    key = validate_idempotency_key(idempotency_key)
    route = record_scope(method, route_template)
    digest = request_hash(method, route_template, body, path_params)
    now = now or utc_now()
    expires_at = now + IDEMPOTENCY_RECORD_TTL
    dialect = session.get_bind().dialect.name

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

        # Bound the wait for a concurrent in-flight request with the same key.
        session.execute(text(f"SET LOCAL lock_timeout = '{IDEMPOTENCY_LOCK_TIMEOUT}'"))
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    try:
        inserted_id = session.execute(
            dialect_insert(IdempotencyRecord)
            .values(
                actor_user_id=actor_user_id,
                route=route,
                idem_key=key,
                request_hash=digest,
                state=STATE_PROCESSING,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=["actor_user_id", "route", "idem_key"])
            .returning(IdempotencyRecord.id)
        ).scalar_one_or_none()
        record = session.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.actor_user_id == actor_user_id,
                IdempotencyRecord.route == route,
                IdempotencyRecord.idem_key == key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
    except OperationalError as exc:
        if sqlstate_of(exc) == LOCK_NOT_AVAILABLE:
            # The transaction is aborted; the caller must roll back. Nothing is stored.
            raise DomainError(
                ErrorCode.IDEMPOTENCY_IN_PROGRESS, details={"retry_after_s": 1}
            ) from exc
        raise
    finally:
        if dialect == "postgresql" and session.is_active:
            try:
                session.execute(text("SET LOCAL lock_timeout TO DEFAULT"))
            except DBAPIError:
                pass

    if inserted_id is not None:
        return IdempotencyClaim(record=record, replay=None)

    record_expires = record.expires_at
    if record_expires.tzinfo is None:  # SQLite returns naive values
        from app.contracts.timeutil import UTC

        record_expires = record_expires.replace(tzinfo=UTC)
    if record_expires <= now:
        # Expired key: may be reused for any request (IDEMPOTENCY_RECORD_TTL).
        record.request_hash = digest
        record.state = STATE_PROCESSING
        record.response_status = None
        record.response_body = None
        record.resource_type = None
        record.resource_id = None
        record.expires_at = expires_at
        record.updated_at = now
        session.flush()
        return IdempotencyClaim(record=record, replay=None)

    if record.request_hash != digest:
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REUSED)
    if record.state != STATE_COMPLETED:  # pragma: no cover - processing rows are never committed
        raise DomainError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, details={"retry_after_s": 1})
    return IdempotencyClaim(
        record=record,
        replay=IdempotentResponse(
            status_code=int(record.response_status),
            body=record.response_body,
            replayed=True,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
        ),
    )


def complete_idempotency(
    session: Session,
    claim: IdempotencyClaim,
    *,
    status_code: int,
    body: Any,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> IdempotentResponse:
    if status_code >= 500:
        raise ValueError("5xx responses are never stored (ADR-0005)")
    record = claim.record
    record.state = STATE_COMPLETED
    record.response_status = status_code
    record.response_body = body
    record.resource_type = resource_type
    record.resource_id = resource_id
    record.updated_at = utc_now()
    session.flush()
    return IdempotentResponse(status_code, body, False, resource_type, resource_id)


def lookup_idempotent_response(
    session: Session,
    *,
    actor_user_id: int,
    method: str,
    route_template: str,
    idempotency_key: str | None,
    body: Any,
    path_params: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> IdempotentResponse | None:
    """Read-only replay lookup (wave 1.6, for A2's G5): no INSERT, no row lock, no ``SET LOCAL``.

    * a committed, unexpired record with the same request hash -> its stored response (``replayed=True``);
    * the same key with another request hash -> ``DomainError(IDEMPOTENCY_KEY_REUSED)``;
    * no record, an expired record, or an in-flight (uncommitted, invisible) first request -> ``None``.
    The caller then runs the command through ``run_idempotent``, which re-checks under the lock.
    """
    key = validate_idempotency_key(idempotency_key)
    route = record_scope(method, route_template)
    digest = request_hash(method, route_template, body, path_params)
    now = now or utc_now()
    record = session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == actor_user_id,
            IdempotencyRecord.route == route,
            IdempotencyRecord.idem_key == key,
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:  # SQLite
        from app.contracts.timeutil import UTC

        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return None
    if record.request_hash != digest:
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REUSED)
    if record.state != STATE_COMPLETED:  # pragma: no cover - processing rows are never committed
        return None
    return IdempotentResponse(int(record.response_status), record.response_body, True,
                              record.resource_type, record.resource_id)


def domain_error_body(exc: DomainError, request_id: str | None = None) -> dict[str, Any]:
    return {"success": False, "error": exc.to_error_body(request_id)}


def run_idempotent(
    session: Session,
    *,
    actor_user_id: int,
    method: str,
    route_template: str,
    idempotency_key: str | None,
    body: Any,
    handler: Callable[[], CommandResult],
    path_params: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> IdempotentResponse:
    """Execute ``handler`` exactly once per key (savepoint pattern, ADR-0005 §4, BR D8).

    Does not commit. The caller commits on return and rolls back on exception.
    """
    claim = acquire_idempotency(
        session,
        actor_user_id=actor_user_id,
        method=method,
        route_template=route_template,
        idempotency_key=idempotency_key,
        body=body,
        path_params=path_params,
        now=now,
    )
    if claim.replay is not None:
        return claim.replay

    savepoint = session.begin_nested()
    try:
        result = handler()
    except DomainError as exc:
        savepoint.rollback()
        if exc.http_status >= 500:
            raise
        return complete_idempotency(session, claim, status_code=exc.http_status, body=domain_error_body(exc))
    except BaseException:
        if savepoint.is_active:
            savepoint.rollback()
        raise
    savepoint.commit()
    if result.status_code >= 500:
        raise ValueError("handlers must raise for 5xx instead of returning it")
    return complete_idempotency(
        session,
        claim,
        status_code=result.status_code,
        body=result.body,
        resource_type=result.resource_type,
        resource_id=result.resource_id,
    )


# --- Outbox -------------------------------------------------------------------------------------


def enqueue_event(
    session: Session,
    envelope: EventEnvelope,
    *,
    aggregate_id: int | None = None,
    dedup_key: str | None = None,
) -> OutboxEvent:
    """Write the event in the caller's transaction (ADR-0012). Rolled back with it.

    The stored payload is the full allowlisted payload. Recipient copies are built
    at dispatch with ``app.contracts.events.payload_for_audience`` (Q16/N2): wallet
    and commission events never reach clients and client copies drop commission keys.
    """
    if not isinstance(envelope, EventEnvelope):
        raise TypeError("envelope must be an EventEnvelope")
    row = OutboxEvent(
        event_id=envelope.event_id,
        event_type=envelope.event_type.value,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_public_id=envelope.aggregate_public_id,
        aggregate_version=envelope.aggregate_version,
        occurred_at=envelope.occurred_at,
        payload=dict(envelope.payload),
        dedup_key=dedup_key,
        attempts=0,
        next_attempt_at=envelope.occurred_at,
    )
    session.add(row)
    session.flush()
    return row


# --- Environment marker (BR N1) --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    ok: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class GateReport:
    """Q48 money gate (Q56). ``ok`` only when every check passes."""

    ok: bool
    checks: tuple[GateCheck, ...]

    @property
    def passed(self) -> bool:
        """Alias of ``ok`` (A2 geo flag gate reads ``passed``)."""
        return self.ok

    @property
    def failed(self) -> list[str]:
        return [check.name for check in self.checks if not check.ok]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks]}


def q48_gate_status(session: Session) -> GateReport:
    """Pure read of the Q48 production money gate (Q56), evaluated as the session's current role.

    Checks (SQL ``public.q48_gate_checks()`` from migrations 0052/0055, one source of truth for app and DB triggers):
    ``app_role_not_superuser``, ``app_role_cannot_write_balances``, ``balance_guard_uses_trigger_depth``,
    ``ledger_source_links_enforced``, ``seed_rate_confirmed``, ``approver_guard_enforced`` (Q69) and
    ``app_role_owns_no_objects`` (Q71). Not PostgreSQL or migration missing -> not ok.
    """
    if session.get_bind().dialect.name != "postgresql":
        return GateReport(False, (GateCheck("postgresql", False, "not_postgresql"),))
    present = session.execute(text("SELECT to_regprocedure('public.q48_gate_checks()') IS NOT NULL")).scalar_one()
    if not present:
        return GateReport(False, (GateCheck("gate_function_present", False, "migration_20260915_0052_missing"),))
    checks = tuple(
        GateCheck(name, bool(ok), detail)
        for name, ok, detail in session.execute(text("SELECT check_name, ok, detail FROM public.q48_gate_checks()")).all()
    )
    return GateReport(bool(checks) and all(check.ok for check in checks), checks)


class DeploymentEnvironment(StrEnum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TEST = "test"


# Allowlist (wave 1.5 BR #3). ``local`` is the only alias; anything else is an error, never development.
ENVIRONMENT_ALIASES: dict[str, DeploymentEnvironment] = {
    "local": DeploymentEnvironment.DEVELOPMENT,
    "development": DeploymentEnvironment.DEVELOPMENT,
    "test": DeploymentEnvironment.TEST,
    "staging": DeploymentEnvironment.STAGING,
    "production": DeploymentEnvironment.PRODUCTION,
}


def normalize_environment(value: str | None) -> DeploymentEnvironment:
    """Map ``ELCHI_ENVIRONMENT`` through the allowlist. Unknown values (``prod``, ``live``, "") raise."""
    key = (value or "").strip().lower()
    try:
        return ENVIRONMENT_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"unknown environment {value!r}; allowed: {', '.join(sorted(ENVIRONMENT_ALIASES))}"
        ) from None


def app_environment() -> DeploymentEnvironment:
    """The app's environment. Raises ``ValueError`` for a value outside the allowlist."""
    from app.core.config import settings

    return normalize_environment(settings.environment)


@dataclass(frozen=True, slots=True)
class DbMarkerState:
    table_present: bool
    environment: DeploymentEnvironment | None

    @property
    def missing(self) -> bool:
        """The marker table exists (migrated DB) but has no row: guards treat this as production."""
        return self.table_present and self.environment is None


def get_db_marker_state(session: Session) -> DbMarkerState:
    if not table_exists(session, PlatformEnvironment.__tablename__):
        return DbMarkerState(False, None)
    value = session.execute(select(PlatformEnvironment.environment).where(PlatformEnvironment.id == 1)).scalar_one_or_none()
    # The DB CHECK constraint restricts values to the four canonical names.
    return DbMarkerState(True, None if value is None else DeploymentEnvironment(value))


def get_db_environment(session: Session) -> DeploymentEnvironment | None:
    """The database's marker, or ``None`` when the table/row is absent (see ``get_db_marker_state``)."""
    return get_db_marker_state(session).environment


def set_db_environment(
    session: Session, environment: DeploymentEnvironment | str, *, set_by: str, note: str | None = None
) -> DeploymentEnvironment:
    """Upsert the marker. The DB trigger rejects leaving ``production`` and entering it
    while any ``test_overdraft_allowed`` wallet exists."""
    env = DeploymentEnvironment(environment)
    if not set_by or not set_by.strip():
        raise ValueError("set_by is required for the audit trail")
    row = session.get(PlatformEnvironment, 1)
    if row is None:
        session.add(PlatformEnvironment(id=1, environment=env.value, set_by=set_by, note=note))
    else:
        row.environment = env.value
        row.set_by = set_by
        row.note = note
        row.updated_at = utc_now()
    session.flush()
    return env


def is_production(session: Session | None = None) -> bool:
    """Fail closed (wave 1.5 BR #2/#3): production if the app says so, the app value is not in the
    allowlist, the database marker says so, or a migrated database has no marker row."""
    try:
        if app_environment() is DeploymentEnvironment.PRODUCTION:
            return True
    except ValueError:
        return True
    if session is None:
        return False
    state = get_db_marker_state(session)
    return state.missing or state.environment is DeploymentEnvironment.PRODUCTION


def new_event_id() -> uuid.UUID:
    return uuid.uuid4()
