"""Wave 9: the staff MFA routes (I6-I11, ADR-0021 §13a) as a contract.

Wave 8 wrote the MFA service and switched enforcement on inside ``require_capability``; there was no way for a
staff member to enroll a factor or to prove one, so enforcement could never honestly be turned on. These are
the promises of the routes that close that gap - checked without a database, so they also hold for a reader of
the OpenAPI document:

* nothing but the one-time enrollment response may carry a secret;
* the state a staff member sees must say *why* enforcement is off, instead of implying MFA is protecting them;
* a recovery code answers with "you may enroll again", never with an approval.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.contracts.dto import Envelope
from app.contracts.enums import Capability
from app.main import app
from app.modules.identity import mfa
from app.modules.identity.schemas import (
    StaffMfaCodeCommand,
    StaffMfaEnrollmentDTO,
    StaffMfaFactorDTO,
    StaffMfaRecoveryDTO,
    StaffMfaResetCommand,
    StaffMfaResetDTO,
    StaffMfaStateDTO,
    StaffMfaStepUpDTO,
)

MFA_ROUTES = {
    ("GET", "/api/v2/me/mfa"),
    ("POST", "/api/v2/me/mfa/enroll"),
    ("POST", "/api/v2/me/mfa/step-up"),
    ("POST", "/api/v2/me/mfa/recovery"),
    ("POST", "/api/v2/admin/staff/{user_id}/mfa/activate"),
    ("POST", "/api/v2/admin/staff/{user_id}/mfa/reset"),
}

SECRET_WORDS = ("secret", "cipher", "code_hash", "provisioning")


def _routes() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method != "HEAD"
    }


def test_every_mfa_route_is_mounted_with_a_response_model() -> None:
    routes = _routes()
    for key in MFA_ROUTES:
        assert key in routes, key
        assert routes[key].response_model is not None, key


def test_only_the_one_time_enrollment_response_carries_a_secret() -> None:
    for dto in (StaffMfaStateDTO, StaffMfaStepUpDTO, StaffMfaRecoveryDTO, StaffMfaFactorDTO, StaffMfaResetDTO):
        leaked = [name for name in dto.model_fields if any(word in name for word in SECRET_WORDS)]
        assert leaked == [], (dto.__name__, leaked)
    assert {"secret", "provisioning_uri", "recovery_codes"} <= set(StaffMfaEnrollmentDTO.model_fields)


def test_state_explains_why_enforcement_is_off_instead_of_claiming_protection() -> None:
    fields = StaffMfaStateDTO.model_fields
    # "enforced" alone would read as "MFA is on"; the pilot runs audit-only and with one super_admin, and the
    # screen has to be able to say so (spec §9.2 spirit: no protection that is not actually there).
    for name in ("mode", "enforced", "active_super_admin_count", "pending_activation"):
        assert name in fields, name
    assert fields["active_super_admin_count"].annotation is int


def test_recovery_answers_with_enrollment_not_with_approval() -> None:
    fields = set(StaffMfaRecoveryDTO.model_fields)
    assert "enrollment_allowed" in fields and "factor_revoked" in fields
    # Q17/Q49: a recovery code is never a second approver and never a step-up.
    assert not {"stepped_up_at", "approved", "capabilities"} & fields


def test_step_up_response_states_when_it_stops_being_fresh() -> None:
    assert {"stepped_up_at", "expires_at"} == set(StaffMfaStepUpDTO.model_fields)
    assert int(mfa.STEP_UP_MAX_AGE.total_seconds()) == 300


def test_commands_accept_a_code_and_a_reset_reason_only() -> None:
    assert set(StaffMfaCodeCommand.model_fields) == {"code"}
    assert set(StaffMfaResetCommand.model_fields) == {"reason"}


def test_the_capability_that_approves_a_factor_is_super_admin_only() -> None:
    from app.contracts.enums import STAFF_ROLE_CAPABILITIES, Role

    for role, caps in STAFF_ROLE_CAPABILITIES.items():
        assert (Capability.STAFF_MFA_APPROVE in caps) is (role is Role.SUPER_ADMIN), role


def test_failed_code_attempts_are_capped() -> None:
    assert mfa.MAX_FAILED_ATTEMPTS == 5
    assert mfa.FAILED_ATTEMPT_WINDOW.total_seconds() == 900


def test_envelope_is_the_v2_envelope() -> None:
    routes = _routes()
    assert routes[("GET", "/api/v2/me/mfa")].response_model is Envelope[StaffMfaStateDTO]
