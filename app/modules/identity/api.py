"""API v2 identity router (I1, I2, I3, I5). Mounted by the integrator under ``/api/v2``."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts.dto import Envelope
from app.contracts.enums import STAFF_ROLES, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.core.config import settings
from app.modules.identity import mfa as staff_mfa
from app.modules.identity import service as identity_service
from app.modules.identity.schemas import (
    CapabilitiesDTO,
    DriverEligibilityCommand,
    DriverEligibilityDTO,
    DriverEligibilitySummaryDTO,
    MeDTO,
    RoleActivateRequest,
    StaffMfaCodeCommand,
    StaffMfaEnrollmentDTO,
    StaffMfaFactorDTO,
    StaffMfaRecoveryDTO,
    StaffMfaResetCommand,
    StaffMfaResetDTO,
    StaffMfaStateDTO,
    StaffMfaStepUpDTO,
)
from app.modules.identity.web import ERROR_RESPONSES, current_user_id, get_session, run_command

router = APIRouter(tags=["v2 Identity"])


def capabilities_dto(caps: identity_service.CapabilitySet) -> CapabilitiesDTO:
    driver = None
    if Role.DRIVER in caps.roles:
        driver = DriverEligibilitySummaryDTO(
            verification_status=caps.driver.verification_status if caps.driver else None,
            eligible=caps.driver_eligible,
            reasons=list(caps.driver_reasons),
            has_active_obligations=bool(caps.driver and caps.driver.has_active_obligations),
        )
    return CapabilitiesDTO(
        roles=sorted(caps.roles, key=lambda role: role.value),
        capabilities=sorted(caps.capabilities, key=lambda capability: capability.value),
        driver_eligibility=driver,
    )


@router.get("/me", response_model=Envelope[MeDTO], responses=ERROR_RESPONSES)
def get_me(user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> Envelope[MeDTO]:
    summary = identity_service.get_user_summary(session, user_id)
    caps = identity_service.get_capabilities(session, user_id)
    return Envelope[MeDTO](
        data=MeDTO(
            id=summary.public_id,
            phone=summary.phone,
            full_name=summary.full_name,
            primary_role=Role(summary.primary_role),
            roles=sorted(caps.roles, key=lambda role: role.value),
            status=summary.status,
            created_at=summary.created_at,
        )
    )


@router.get("/me/capabilities", response_model=Envelope[CapabilitiesDTO], responses=ERROR_RESPONSES)
def get_my_capabilities(
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[CapabilitiesDTO]:
    return Envelope[CapabilitiesDTO](data=capabilities_dto(identity_service.get_capabilities(session, user_id)))


@router.post("/me/roles", response_model=Envelope[CapabilitiesDTO], responses=ERROR_RESPONSES)
def activate_my_role(
    body: RoleActivateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: capabilities_dto(
            identity_service.activate_role(session, user_id, body.role, granted_by=user_id)
        ),
        resource_type="user",
    )


@router.post(
    "/admin/drivers/{user_id}/eligibility", response_model=Envelope[DriverEligibilityDTO], responses=ERROR_RESPONSES
)
def set_driver_eligibility(
    user_id: str,
    body: DriverEligibilityCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor_user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> DriverEligibilityDTO:
        state = identity_service.set_driver_eligibility(
            session,
            driver_user_id=identity_service.resolve_user_id(session, user_id),
            actor_user_id=actor_user_id,
            action=body.action,
            expected_version=body.expected_version,
            reason=body.reason,
        )
        return DriverEligibilityDTO(
            user_id=state.user_public_id,
            eligible=state.eligible,
            blocked_reason=state.blocked_reason,
            active_trip_ids=list(state.active_trip_public_ids),
            version=state.version,
        )

    return run_command(
        request,
        session,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=handler,
        resource_type="driver_eligibility",
    )


# --- I6-I11: staff MFA (ADR-0021, API_V2_CONTRACT §13a) ---------------------------------------------------
#
# The service layer was written in wave 8 and enforcement already runs inside ``require_capability``; without
# these routes a staff member had no way to enroll a factor or to prove one, so enforcement could never be
# switched on honestly. Nothing here returns a secret twice and nothing here logs a code.


def _staff_only(session: Session, user_id: int) -> identity_service.CapabilitySet:
    """MFA belongs to staff accounts (Q3). A marketplace account is refused before anything is written."""
    caps = identity_service.get_capabilities(session, user_id)
    if not (set(caps.roles) & set(STAFF_ROLES)):
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "staff_only"})
    return caps


def _failure_recorder(
    session: Session, failed: Callable[[], bool], *, user_id: int, purpose: str, actor_user_id: int | None = None
) -> Callable[[bool], None]:
    """Keep the wrong-code row after the domain 4xx rolled the handler's writes back (BR D8)."""

    def after_command(replayed: bool) -> None:
        if replayed or not failed():
            return
        staff_mfa.record_failed_attempt(
            session, user_id=user_id, purpose=purpose, actor_user_id=actor_user_id
        )

    return after_command


def _state_dto(session: Session, user_id: int) -> StaffMfaStateDTO:
    state = staff_mfa.state(session, user_id)
    return StaffMfaStateDTO(
        enrolled=state.enrolled,
        active=state.active,
        pending_activation=state.pending,
        mode=settings.staff_mfa_mode,
        enforced=not state.audit_only,
        active_super_admin_count=staff_mfa.active_super_admin_count(session),
        stepped_up_at=state.stepped_up_at,
        step_up_fresh=state.step_up_fresh(),
        step_up_max_age_seconds=int(staff_mfa.STEP_UP_MAX_AGE.total_seconds()),
        recovery_codes_remaining=staff_mfa.unused_recovery_code_count(session, user_id),
        failed_attempts_in_window=staff_mfa.recent_failed_attempts(session, user_id),
        max_failed_attempts=staff_mfa.MAX_FAILED_ATTEMPTS,
    )


@router.get("/me/mfa", response_model=Envelope[StaffMfaStateDTO], responses=ERROR_RESPONSES)
def get_my_mfa_state(
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[StaffMfaStateDTO]:
    _staff_only(session, user_id)
    return Envelope[StaffMfaStateDTO](data=_state_dto(session, user_id))


@router.post(
    "/me/mfa/enroll", response_model=Envelope[StaffMfaEnrollmentDTO], status_code=201, responses=ERROR_RESPONSES
)
def enroll_my_mfa(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Start an enrollment.

    The factor is *pending*: it grants nothing until a different super_admin activates it, and an existing
    active factor keeps working until then - a new phone must not disarm the old one.
    """

    def handler() -> StaffMfaEnrollmentDTO:
        caps = _staff_only(session, user_id)
        summary = identity_service.get_user_summary(session, caps.user_id)
        secret = staff_mfa.enroll(session, user_id=user_id, account_name=summary.phone)
        return StaffMfaEnrollmentDTO(
            factor_id=secret.factor_public_id,
            secret=secret.secret,
            provisioning_uri=secret.provisioning_uri,
            recovery_codes=list(secret.recovery_codes),
        )

    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=None,
        handler=handler,
        success_status=201,
        resource_type="staff_mfa_factor",
    )


@router.post("/me/mfa/step-up", response_model=Envelope[StaffMfaStepUpDTO], responses=ERROR_RESPONSES)
def step_up_my_mfa(
    body: StaffMfaCodeCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Prove the factor, so the next few minutes of money and flag commands are allowed (STEP_UP_MAX_AGE)."""

    failed = False

    def handler() -> StaffMfaStepUpDTO:
        nonlocal failed
        _staff_only(session, user_id)
        if not staff_mfa.step_up(session, user_id=user_id, code=body.code):
            failed = True
            # The reason stays deliberately coarse: it never says whether a factor exists.
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "invalid_code"})
        moment = staff_mfa.last_step_up_at(session, user_id) or utc_now()
        return StaffMfaStepUpDTO(stepped_up_at=moment, expires_at=moment + staff_mfa.STEP_UP_MAX_AGE)

    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=handler,
        after_command=_failure_recorder(session, lambda: failed, user_id=user_id, purpose="step_up"),
        resource_type="staff_mfa_factor",
    )


@router.post("/me/mfa/recovery", response_model=Envelope[StaffMfaRecoveryDTO], responses=ERROR_RESPONSES)
def use_my_recovery_code(
    body: StaffMfaCodeCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Spend one recovery code.

    It buys the right to enroll again - it is never a step-up and never an approval (Q17/Q49), so the response
    says exactly that instead of quietly handing back an authorised session.
    """

    failed = False

    def handler() -> StaffMfaRecoveryDTO:
        nonlocal failed
        _staff_only(session, user_id)
        had_factor = staff_mfa.state(session, user_id).active
        if not staff_mfa.consume_recovery_code(session, user_id=user_id, code=body.code):
            failed = True
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "invalid_code"})
        return StaffMfaRecoveryDTO(
            enrollment_allowed=True,
            recovery_codes_remaining=staff_mfa.unused_recovery_code_count(session, user_id),
            factor_revoked=had_factor,
        )

    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=handler,
        after_command=_failure_recorder(session, lambda: failed, user_id=user_id, purpose="recovery"),
        resource_type="staff_mfa_factor",
    )


@router.post(
    "/admin/staff/{user_id}/mfa/activate", response_model=Envelope[StaffMfaFactorDTO], responses=ERROR_RESPONSES
)
def activate_staff_mfa(
    user_id: str,
    body: StaffMfaCodeCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor_user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """A *different* super_admin confirms one live code from the subject's authenticator (``staff.mfa_approve``).

    Self-activation is refused by the service and by the database (``ck_staff_mfa_factors_two_person``).
    """

    outcome: dict[str, int | bool] = {"failed": False, "subject_id": 0}

    def handler() -> StaffMfaFactorDTO:
        subject_id = identity_service.resolve_user_id(session, user_id)
        outcome["subject_id"] = subject_id
        try:
            factor = staff_mfa.activate(
                session, actor_user_id=actor_user_id, subject_user_id=subject_id, code=body.code
            )
        except DomainError as exc:
            outcome["failed"] = exc.code is ErrorCode.VALIDATION_ERROR
            raise
        return StaffMfaFactorDTO(
            user_id=identity_service.user_public_id(session, subject_id),
            status=factor.status,
            activated_at=factor.activated_at,
            version=factor.version,
        )

    def after_command(replayed: bool) -> None:
        # The wrong code was the subject's, offered by the approver: both are named in the trail.
        if replayed or not outcome["failed"]:
            return
        staff_mfa.record_failed_attempt(
            session, user_id=int(outcome["subject_id"]), purpose="activation", actor_user_id=actor_user_id
        )

    return run_command(
        request,
        session,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=handler,
        after_command=after_command,
        resource_type="staff_mfa_factor",
    )


@router.post(
    "/admin/staff/{user_id}/mfa/reset", response_model=Envelope[StaffMfaResetDTO], responses=ERROR_RESPONSES
)
def reset_staff_mfa(
    user_id: str,
    body: StaffMfaResetCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor_user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Lost phone: a different super_admin revokes the factor and the unused recovery codes.

    It grants nothing - the subject enrolls again, and that enrollment still needs a second person.
    """

    def handler() -> StaffMfaResetDTO:
        subject_id = identity_service.resolve_user_id(session, user_id)
        revoked = staff_mfa.reset(session, actor_user_id=actor_user_id, subject_user_id=subject_id, reason=body.reason)
        return StaffMfaResetDTO(user_id=identity_service.user_public_id(session, subject_id), factors_revoked=revoked)

    return run_command(
        request,
        session,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=handler,
        resource_type="staff_mfa_factor",
    )
