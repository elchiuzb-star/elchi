"""Liveness and readiness probes (spec §19.2, AC34; API_V2_CONTRACT §14; BR finding N1).

Mounted without a prefix: ``GET /health/live`` and ``GET /health/ready``.
``GET /api/v1/health`` is untouched and stays the Dockerfile HEALTHCHECK target.

Semantics (BR N1 supersedes the "invariant -> 503" line in API_V2_CONTRACT §14):

========================  =============================  =========================
check                     value                          effect on HTTP / status
========================  =============================  =========================
database                  ok / unavailable / busy        unavailable -> 503;
                                                         busy (pool timeout) ->
                                                         ``degraded`` (200)
migrations                ok / ahead / mismatch /        ahead -> ``degraded`` (200);
                          unknown / skipped              mismatch, unknown -> 503
redis                     ok / unavailable /             not ok -> ``degraded``
                          not_configured                 (200)
production_invariants     ok / fail / error /            fail, error, not_available
                          not_available / not_applicable -> ``degraded`` (200) +
                          / skipped (DB down)            ERROR log signal
========================  =============================  =========================

Migrations (decision 32): ``ahead`` means every DB revision descends from the
code head (expand-only migrations, ADR-0016, keep the code working). DB behind
the code head or on a divergent branch is ``mismatch``/``unknown`` -> 503.
**Q50 (wave 5):** when this build does not ship the database's revision - an
image older than the database, i.e. a deploy rollback - the graph recorded in
``alembic_revision_lineage`` (migration 0067, written by ``alembic/env.py``) is
consulted instead of the script files, so such a rollback reports ``ahead``
(200 degraded) rather than a blind 503. A revision the database itself did not
record, or one that does not descend from the code head, stays 503.

Results are cached for ``cache_ttl_seconds`` (default 3 s) behind a lock, so a
burst of monitor/load-balancer probes shares one run (BR #5).

503 is reserved for "this process cannot serve correct data": the database is
unreachable or the schema is not at the head this code was built for. A
production-invariant violation (e.g. an overdraft test wallet in production) is
a data problem that must page someone, but answering 503 would take the whole
API -- frozen v1 clients included -- out of any load balancer that routes on
readiness. It is therefore reported as ``production_invariants: "fail"`` with a
rate-limited ERROR log record (logger ``elchi.health``, message
``production_invariants_failed``) for alerting.

The response is public and deliberately carries no details (no error strings,
versions or violation lists); details go to the log only.

Production-invariant hook contract (owner A3, ``app.modules.wallet.service``)::

    def assert_production_invariants(session: Session) -> Result

``Result`` is A3's ``ProductionInvariantReport`` (``ok``, ``is_production``,
``failed`` check names) or any object/mapping with ``ok: bool`` and optional
``violations``/``failed`` and ``is_production``; a plain bool is accepted. The
call runs in a session that is rolled back afterwards. An exception is reported
as ``error`` (logged), never as 503. Hooks run in every environment because A3
also treats a database *marked* production as production. A passing check is
``ok`` when the app or the hook says production, otherwise ``not_applicable``;
a missing module is ``not_available`` in production, ``not_applicable`` elsewhere.
"""

from __future__ import annotations

import importlib
import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session

logger = logging.getLogger("elchi.health")

router = APIRouter(tags=["Health"])

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_TIMEOUT_SECONDS = 2
REDIS_TIMEOUT_SECONDS = 1.0
INVARIANT_LOG_INTERVAL_SECONDS = 300.0

# (module path, attribute). Extend when another owner publishes an invariant check.
DEFAULT_INVARIANT_HOOKS: tuple[tuple[str, str], ...] = (
    ("app.modules.wallet.service", "assert_production_invariants"),
)
# Q48 money-flow gate (A3, wave 1.7 NEW-1). Optional: the first one that exists is used; when none
# exists yet the gate is simply not part of readiness (scripts/deploy.sh has an SQL fallback).
Q48_GATE_HOOKS: tuple[tuple[str, str], ...] = (
    ("app.modules.platform.service", "q48_gate_status"),
    ("app.modules.wallet.service", "q48_gate_status"),
)

# Informational notice hooks (Q57 style, wave 2.1): ``fn(session) -> list[str]`` (or objects/mappings with
# ``name``). Never change status/HTTP; a missing module is skipped, a crash is logged and ignored.
READINESS_NOTICE_HOOKS: tuple[tuple[str, str], ...] = (
    ("app.modules.geo.service", "readiness_notices"),
)

DEFAULT_CACHE_TTL_SECONDS = 3.0

DatabaseState = Literal["ok", "unavailable", "busy"]
MigrationState = Literal["ok", "ahead", "mismatch", "unknown", "skipped"]
RedisState = Literal["ok", "unavailable", "not_configured"]
InvariantState = Literal["ok", "fail", "error", "not_available", "not_applicable", "skipped"]
OverallState = Literal["ready", "degraded", "unavailable"]


class LiveResponse(BaseModel):
    status: Literal["live"]


class ReadinessChecks(BaseModel):
    database: DatabaseState
    migrations: MigrationState
    redis: RedisState
    production_invariants: InvariantState


class ReadinessResponse(BaseModel):
    status: OverallState
    checks: ReadinessChecks
    # Informational names only (Q57), e.g. "unconfirmed_seed_policy_active". Never affect status/HTTP.
    notices: list[str] = []


# ── helpers ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def shipped_script_directory() -> Any:
    """The Alembic script graph shipped with this build (the image copies alembic/)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def expected_migration_heads() -> tuple[str, ...]:
    """Heads of the shipped script graph = the schema this code was built for."""
    return tuple(sorted(shipped_script_directory().get_heads()))


def classify_schema(
    current: Sequence[str], expected: Sequence[str], script: Any
) -> Literal["ok", "ahead", "mismatch", "unknown"]:
    """Compare DB revisions with the code heads using the script graph (decision 32)."""
    current_set, expected_set = set(current), set(expected)
    if not current_set or not expected_set:
        return "unknown"
    if current_set == expected_set:
        return "ok"
    ancestors: set[str] = set()
    try:
        for revision in current_set:
            if script.get_revision(revision) is None:
                return "unknown"
            ancestors.update(r.revision for r in script.revision_map.iterate_revisions(revision, "base"))
    except Exception:  # noqa: BLE001 - alembic raises various errors for unknown/garbled ids
        return "unknown"
    # Ahead: every code head is an ancestor of the DB heads (the DB has everything this code needs).
    return "ahead" if expected_set <= ancestors else "mismatch"


LINEAGE_TABLE = "alembic_revision_lineage"


def read_revision_lineage(conn: Any) -> dict[str, set[str]]:
    """Q50: the applied migration graph as ``{revision: {parents}}``, or ``{}`` when it is not available.

    Written by ``alembic/env.py`` (table ``alembic_revision_lineage``). Reading it is what lets an image that is
    older than the database tell "the schema is a descendant of my head" (safe, rollback in progress) from
    "I have never heard of this schema" - without the newer migration files.
    """
    try:
        rows = conn.execute(text(f"SELECT revision, down_revision FROM {LINEAGE_TABLE}")).all()
    except Exception:  # noqa: BLE001 - table missing (older schema) or not readable: no lineage, not an error
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}
    graph: dict[str, set[str]] = {}
    for revision, parent in rows:
        graph.setdefault(str(revision), set())
        if parent is not None:
            graph[str(revision)].add(str(parent))
    return graph


def classify_with_lineage(
    current: Sequence[str], expected: Sequence[str], lineage: dict[str, set[str]]
) -> Literal["ahead", "mismatch", "unknown"]:
    """Decide ``ahead`` from the database's own graph when the script graph cannot (Q50)."""
    current_set, expected_set = set(current), set(expected)
    if not current_set or not expected_set or not lineage:
        return "unknown"
    if not current_set <= set(lineage):
        return "unknown"  # the database did not record its own head: nothing to reason from
    seen: set[str] = set()
    stack = list(current_set)
    while stack:
        revision = stack.pop()
        if revision in seen:
            continue
        seen.add(revision)
        stack.extend(lineage.get(revision, set()) - seen)
    if not expected_set <= seen:
        return "mismatch"  # the code head is not an ancestor: a divergent branch, never "just ahead"
    return "ahead"


def build_probe_engine(database_url: str) -> Engine:
    """Small dedicated pool with hard timeouts so a hung DB cannot hang the probe."""
    if database_url.startswith("postgresql"):
        return create_engine(
            database_url,
            pool_size=1,
            max_overflow=1,
            pool_timeout=DB_TIMEOUT_SECONDS,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                "connect_timeout": DB_TIMEOUT_SECONDS,
                "options": f"-c statement_timeout={DB_TIMEOUT_SECONDS * 1000}",
            },
        )
    return create_engine(database_url, pool_pre_ping=True)


def _resp_command(*parts: str) -> bytes:
    chunks = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        raw = part.encode("utf-8")
        chunks.append(b"$" + str(len(raw)).encode() + b"\r\n" + raw + b"\r\n")
    return b"".join(chunks)


def redis_ping(url: str, timeout: float = REDIS_TIMEOUT_SECONDS) -> bool:
    """AUTH (if the URL has credentials) + PING over RESP. No client dependency.

    Only ``redis://`` is supported: Redis lives on the internal compose network.
    Never raises; any failure (refused, timeout, auth error, bad URL) is False.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "redis" or not parts.hostname:
            return False
        port = parts.port or 6379
        with socket.create_connection((parts.hostname, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            stream = sock.makefile("rb")
            if parts.password is not None:
                auth = ["AUTH"]
                if parts.username:
                    auth.append(unquote(parts.username))
                auth.append(unquote(parts.password))
                sock.sendall(_resp_command(*auth))
                if not stream.readline().startswith(b"+OK"):
                    return False
            sock.sendall(_resp_command("PING"))
            return stream.readline().startswith(b"+PONG")
    except (OSError, ValueError):
        return False


def _notice_names(raw: Any) -> list[str]:
    names: list[str] = []
    for item in list(raw or ())[:20]:
        if isinstance(item, str):
            name = item
        elif isinstance(item, Mapping):
            name = item.get("name")
        else:
            name = getattr(item, "name", None)
        if isinstance(name, str) and name:
            names.append(name[:100])
    return names


def _normalise_invariant_result(result: Any) -> tuple[bool, list[str], bool | None]:
    """-> (ok, violation codes, hook's own production verdict or None).

    Accepts A3's ``ProductionInvariantReport`` (``ok``, ``is_production``,
    ``failed``), a mapping with the same keys (or ``violations``), or a bool.
    """
    if isinstance(result, bool):
        return result, [], None
    if isinstance(result, Mapping):
        get = result.get
    else:
        def get(key: str, default: Any = None) -> Any:
            return getattr(result, key, default)
    ok = get("ok")
    if not isinstance(ok, bool):
        raise TypeError("production invariant hook must return bool or an object/mapping with ok: bool")
    violations = get("violations") or get("failed") or get("problems") or ()
    if not violations and not ok:
        # e.g. platform.service.GateReport(ok, checks=(GateCheck(name, ok, detail), ...))
        derived = []
        for check in get("checks") or ():
            check_ok = check.get("ok") if isinstance(check, Mapping) else getattr(check, "ok", None)
            name = check.get("name") if isinstance(check, Mapping) else getattr(check, "name", None)
            if check_ok is False and name:
                derived.append(name)
        violations = derived
    is_production = get("is_production")
    return ok, [str(v)[:200] for v in list(violations)[:20]], is_production if isinstance(is_production, bool) else None


def result_notices(result: Any) -> list[str]:
    """Informational notice names (Q57) from a hook result: ``notices`` of objects/mappings/str."""
    if isinstance(result, bool) or result is None:
        return []
    raw = result.get("notices") if isinstance(result, Mapping) else getattr(result, "notices", None)
    return _notice_names(raw)


class _InvariantLogLimiter:
    """Log on every state change, and repeat an unchanged failure at most every N seconds."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._last_state: str | None = None
        self._last_logged = 0.0

    def should_log(self, state: str) -> bool:
        now = time.monotonic()
        with self._lock:
            changed = state != self._last_state
            due = now - self._last_logged >= self._interval
            self._last_state = state
            if changed or due:
                self._last_logged = now
                return True
            return False


_invariant_log_limiter = _InvariantLogLimiter(INVARIANT_LOG_INTERVAL_SECONDS)


# ── probe ────────────────────────────────────────────────────────────────────


@dataclass
class ReadinessProbe:
    engine_factory: Callable[[], Engine]
    redis_url: str | None
    environment: str
    expected_heads: Callable[[], Sequence[str]] = expected_migration_heads
    invariant_hooks: Sequence[tuple[str, str]] = DEFAULT_INVARIANT_HOOKS
    gate_hooks: Sequence[tuple[str, str]] = Q48_GATE_HOOKS
    notice_hooks: Sequence[tuple[str, str]] = READINESS_NOTICE_HOOKS
    log_limiter: _InvariantLogLimiter = field(default_factory=lambda: _invariant_log_limiter)
    script_directory: Callable[[], Any] = shipped_script_directory
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS
    clock: Callable[[], float] = time.monotonic
    _cache: tuple[float, ReadinessResponse] | None = field(default=None, init=False, repr=False)
    _notices: list[str] = field(default_factory=list, init=False, repr=False)
    _run_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    def run(self) -> ReadinessResponse:
        """Cached for ``cache_ttl_seconds``; concurrent callers wait for and share one run."""
        cached = self._cache
        if cached is not None and self.clock() - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        with self._run_lock:
            cached = self._cache
            if cached is not None and self.clock() - cached[0] < self.cache_ttl_seconds:
                return cached[1]
            result = self._run_uncached()
            self._cache = (self.clock(), result)
            return result

    def _run_uncached(self) -> ReadinessResponse:
        self._notices = []
        database, migrations, invariants = self._check_database()
        redis = self._check_redis()

        if database == "unavailable" or migrations in ("mismatch", "unknown"):
            status: OverallState = "unavailable"
        elif (
            database == "busy"
            or migrations == "ahead"
            or redis != "ok"
            or invariants in ("fail", "error", "not_available")
        ):
            status = "degraded"
        else:
            status = "ready"
        return ReadinessResponse(
            status=status,
            checks=ReadinessChecks(
                database=database, migrations=migrations, redis=redis, production_invariants=invariants
            ),
            notices=sorted(set(self._notices)),
        )

    def evaluate_hooks(self, engine: Engine) -> dict[str, Any]:
        """Per-hook detail for operators (``python -m app.ops.gates``); never exposed over HTTP."""
        out: dict[str, Any] = {}
        for group, hooks, first_only in (("invariants", self.invariant_hooks, False), ("q48_gate", self.gate_hooks, True)):
            for module_path, attribute in hooks:
                name = f"{module_path}.{attribute}"
                try:
                    hook = self._resolve_hook(module_path, attribute)
                except Exception as exc:  # noqa: BLE001
                    out[name] = {"group": group, "available": True, "error": type(exc).__name__}
                    continue
                if hook is None:
                    out[name] = {"group": group, "available": False}
                    continue
                try:
                    with Session(engine) as session:
                        try:
                            result = hook(session)
                            ok, failed, is_production = _normalise_invariant_result(result)
                        finally:
                            session.rollback()
                    out[name] = {"group": group, "available": True, "ok": ok, "failed": failed,
                                 "is_production": is_production, "notices": result_notices(result)}
                except Exception as exc:  # noqa: BLE001
                    out[name] = {"group": group, "available": True, "error": type(exc).__name__}
                if first_only:
                    break
        return out

    def _check_database(self) -> tuple[DatabaseState, MigrationState, InvariantState]:
        try:
            engine = self.engine_factory()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                try:
                    current = tuple(sorted(conn.execute(text("SELECT version_num FROM alembic_version")).scalars()))
                except Exception:  # noqa: BLE001 - missing table or permission: schema unknown
                    logger.warning("readiness_migrations_unreadable", exc_info=True)
                    current = None
                    conn.rollback()
                lineage = read_revision_lineage(conn) if current else {}
        except SQLAlchemyTimeoutError:
            # Pool exhausted: the DB answers, this process is saturated. Not "down".
            logger.warning("readiness_database_busy")
            return "busy", "skipped", "skipped"
        except Exception as exc:  # noqa: BLE001 - any connection failure means "unavailable"
            logger.warning("readiness_database_unavailable: %s", exc.__class__.__name__)
            return "unavailable", "skipped", "skipped"

        migrations = self._compare_heads(current, lineage)
        invariants = self._check_invariants(engine)
        self._collect_notices(engine)
        return "ok", migrations, invariants

    def _collect_notices(self, engine: Engine) -> None:
        """Informational notices only (Q57): never affects status, HTTP code or ``checks``."""
        for module_path, attribute in self.notice_hooks:
            hook = self._safe_resolve(module_path, attribute)
            if hook is None:
                continue
            try:
                with Session(engine) as session:
                    try:
                        result = hook(session)
                    finally:
                        session.rollback()
            except Exception:  # noqa: BLE001 - a crashing notice hook is logged, never a 503/degraded
                logger.warning("readiness_notice_hook_error hook=%s.%s", module_path, attribute, exc_info=True)
                continue
            if isinstance(result, (list, tuple, set, frozenset)):
                self._notices.extend(_notice_names(sorted(result, key=str) if isinstance(result, (set, frozenset)) else result))
            else:
                self._notices.extend(result_notices(result))

    def _compare_heads(
        self, current: tuple[str, ...] | None, lineage: dict[str, set[str]] | None = None
    ) -> MigrationState:
        try:
            expected = tuple(sorted(self.expected_heads()))
            script = self.script_directory()
        except Exception:  # noqa: BLE001 - broken packaging of alembic scripts
            logger.error("readiness_expected_heads_unavailable", exc_info=True)
            return "unknown"
        if current is None:
            return "unknown"
        state = classify_schema(current, expected, script)
        if state == "unknown" and lineage:
            # Q50: this build does not ship the revision the database is on. Ask the database itself whether that
            # revision descends from the head this build needs (deploy rollback) instead of answering 503 blindly.
            state = classify_with_lineage(current, expected, lineage)
            if state == "ahead":
                logger.warning(
                    "readiness_migrations_ahead_via_lineage db=%s code=%s", ",".join(current), ",".join(expected)
                )
                return state
        if state != "ok":
            logger.warning("readiness_migrations_%s db=%s code=%s", state, ",".join(current), ",".join(expected))
        return state

    def _check_redis(self) -> RedisState:
        if not self.redis_url:
            return "not_configured"
        if redis_ping(self.redis_url):
            return "ok"
        logger.warning("readiness_redis_unavailable")
        return "unavailable"

    def _check_invariants(self, engine: Engine) -> InvariantState:
        # Hooks run in every environment: A3's check also treats a *database*
        # marked production as production (staging app pointed at a prod DB).
        state: InvariantState = "ok"
        violations: list[str] = []
        production = self.is_production
        missing = False
        hooks = [(m, a, True) for m, a in self.invariant_hooks]
        gate_checked = False
        index = 0
        while index < len(hooks) or not gate_checked:
            if index >= len(hooks):
                # Q48 money gate (Q56) only matters where production money could flow: evaluated after the
                # invariant hooks, and only when the app or a hook says this is production.
                gate_checked = True
                if production:
                    gate = next(((m, a) for m, a in self.gate_hooks if self._safe_resolve(m, a) is not None), None)
                    if gate:
                        hooks.append((*gate, False))
                continue
            module_path, attribute, required = hooks[index]
            index += 1
            hook = self._resolve_hook(module_path, attribute)
            if hook is None:
                missing = missing or required
                continue
            try:
                with Session(engine) as session:
                    try:
                        result = hook(session)
                        ok, found, hook_production = _normalise_invariant_result(result)
                        self._notices.extend(result_notices(result))
                    finally:
                        session.rollback()
            except Exception:  # noqa: BLE001 - a crashing check is an error signal, not a 503
                logger.error("production_invariants_error hook=%s.%s", module_path, attribute, exc_info=True)
                state = "fail" if state == "fail" else "error"
                continue
            production = production or bool(hook_production)
            if not ok:
                state = "fail"
                violations.extend(f"{module_path}:{v}" for v in found)
        if state == "ok":
            if not production:
                return "not_applicable"
            if missing:
                state = "not_available"
        if state in ("fail", "error", "not_available") and self.log_limiter.should_log(state):
            level = logging.WARNING if state == "not_available" else logging.ERROR
            logger.log(
                level,
                "production_invariants_%s",
                "failed" if state == "fail" else state,
                extra={"event": f"production_invariants_{state}", "violations": violations},
            )
        elif state == "ok":
            self.log_limiter.should_log(state)
        return state

    @classmethod
    def _safe_resolve(cls, module_path: str, attribute: str) -> Callable[[Session], Any] | None:
        try:
            return cls._resolve_hook(module_path, attribute)
        except Exception:  # noqa: BLE001 - a broken optional module is reported by the required path/logs
            logger.error("readiness_gate_hook_import_error hook=%s.%s", module_path, attribute, exc_info=True)
            return None

    @staticmethod
    def _resolve_hook(module_path: str, attribute: str) -> Callable[[Session], Any] | None:
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            # Only "the owner has not shipped it yet" is not_available; an import
            # error *inside* the module is a bug and must surface as error.
            if exc.name and module_path.startswith(exc.name):
                return None
            raise
        return getattr(module, attribute, None)


_default_probe: ReadinessProbe | None = None
_default_probe_lock = threading.Lock()


def _redis_url_from_config() -> str | None:
    from app.core.config import settings

    value = getattr(settings, "redis_url", None) or os.environ.get("ELCHI_REDIS_URL")
    return value.strip() or None if isinstance(value, str) else None


def get_readiness_probe() -> ReadinessProbe:
    """FastAPI dependency; tests override it with their own probe."""
    global _default_probe
    if _default_probe is None:
        with _default_probe_lock:
            if _default_probe is None:
                from app.core.config import settings

                engine_holder: dict[str, Engine] = {}

                def engine_factory() -> Engine:
                    if "engine" not in engine_holder:
                        engine_holder["engine"] = build_probe_engine(settings.database_url)
                    return engine_holder["engine"]

                _default_probe = ReadinessProbe(
                    engine_factory=engine_factory,
                    redis_url=_redis_url_from_config(),
                    environment=settings.environment,
                )
    return _default_probe


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/health/live", response_model=LiveResponse)
def live(response: Response) -> LiveResponse:
    """The process is up and serving HTTP. Never touches dependencies."""
    response.headers["Cache-Control"] = "no-store"
    return LiveResponse(status="live")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Database unreachable, or schema behind/unknown to this build"}},
)
def ready(response: Response, probe: ReadinessProbe = Depends(get_readiness_probe)) -> ReadinessResponse:
    result = probe.run()
    response.headers["Cache-Control"] = "no-store"
    if result.status == "unavailable":
        response.status_code = 503
    return result
