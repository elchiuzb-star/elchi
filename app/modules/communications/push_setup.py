"""Install the push provider at worker start-up (ADR-0022).

Only the worker sends push: ``communications.dispatch_outbox`` (creates push rows only when the provider is enabled)
and ``communications.push_delivery`` are both worker jobs, so the API process keeps the disabled default.

Decision table, evaluated once per process and logged once:

=====================================  ==================================================================
``ELCHI_PUSH_PROVIDER``                result
=====================================  ==================================================================
``disabled`` (default) / unset         ``DisabledPushProvider`` - in-app inbox only (Q82)
``fcm``, config incomplete/unreadable  ``DisabledPushProvider`` + one error line naming what is missing
``fcm``, production, no allow flag     ``DisabledPushProvider`` - K3 legal review not recorded
``fcm``, complete (and allowed)        ``FcmPushProvider`` with service-account credentials + httpx
=====================================  ==================================================================

Production is detected with ``platform.service.is_production`` (env **or** DB marker, fail closed: an unreachable
database counts as production). ``ELCHI_PUSH_ALLOW_PRODUCTION=true`` is the explicit, separate switch that may be
set only after the K3 legal review in ADR-0022 - it is not implied by anything else.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.modules.communications.providers import set_push_provider

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Engine

    from app.core.config import Settings

logger = logging.getLogger(__name__)


def make_token_lookup(engine: Engine | None = None) -> Callable[[str], str | None]:
    """``device public id -> registration token`` for ``FcmPushProvider``.

    Each call is its own short read-only session, closed before the provider makes its HTTP call, so no DB
    transaction is open while Google is contacted (AGENTS §6).
    """
    from app.modules.communications import service

    def lookup(device_public_id: str) -> str | None:
        bind = engine
        if bind is None:
            from app.db.session import engine as default_engine

            bind = default_engine
        with Session(bind) as session:
            try:
                return service.device_push_token(session, device_public_id)
            finally:
                session.rollback()

    return lookup


def _is_production(engine: Engine | None) -> bool:
    from app.modules.platform.service import is_production

    try:
        bind = engine
        if bind is None:
            from app.db.session import engine as default_engine

            bind = default_engine
        with Session(bind) as session:
            try:
                return is_production(session)
            finally:
                session.rollback()
    except Exception:  # noqa: BLE001 - an unknown environment is treated as production (fail closed)
        logger.warning("push_provider_production_check_failed treating_as=production")
        return True


def install_push_provider(
    *,
    config: Settings | None = None,
    engine: Engine | None = None,
    production: bool | None = None,
) -> str:
    """Install the configured provider; returns ``"fcm"`` or ``"disabled"``. Never raises on bad config."""
    from app.core.config import settings as default_settings

    config = config or default_settings
    if config.push_provider != "fcm":
        set_push_provider(None)
        logger.info("push_provider_disabled reason=not_selected")
        return "disabled"

    if not config.push_fcm_service_account_file:
        set_push_provider(None)
        logger.error("push_provider_disabled reason=config_incomplete missing=ELCHI_PUSH_FCM_SERVICE_ACCOUNT_FILE")
        return "disabled"

    is_prod = _is_production(engine) if production is None else production
    if is_prod and not config.push_allow_production:
        set_push_provider(None)
        logger.error("push_provider_disabled reason=production_not_allowed hint=ADR-0022_K3_legal_review")
        return "disabled"

    from app.modules.communications.fcm import FcmPushProvider
    from app.modules.communications.fcm_google import (
        HttpxTransport,
        ServiceAccountCredentials,
        ServiceAccountError,
        load_service_account,
    )

    try:
        account = load_service_account(config.push_fcm_service_account_file)
    except ServiceAccountError as exc:
        set_push_provider(None)
        logger.error("push_provider_disabled reason=service_account_unusable detail=%s", exc)
        return "disabled"
    project_id = config.push_fcm_project_id or account.project_id
    if not project_id:
        set_push_provider(None)
        logger.error("push_provider_disabled reason=config_incomplete missing=ELCHI_PUSH_FCM_PROJECT_ID")
        return "disabled"
    if account.project_id and config.push_fcm_project_id and account.project_id != config.push_fcm_project_id:
        logger.warning("push_fcm_project_mismatch configured=%s key_file=%s", config.push_fcm_project_id, account.project_id)

    set_push_provider(FcmPushProvider(
        credentials=ServiceAccountCredentials(account=account, project_id=project_id),
        transport=HttpxTransport(),
        token_lookup=make_token_lookup(engine),
    ))
    logger.info("push_provider_installed provider=fcm project=%s production=%s", project_id, is_prod)
    return "fcm"
