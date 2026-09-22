"""Identity DTOs (API_V2_CONTRACT §1: I1-I3, I5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.dto import ContractModel, UtcDateTime, VersionedCommand
from app.contracts.enums import Capability, Role


class MeDTO(ContractModel):
    id: str = Field(description="Opaque user id (usr_...).")
    phone: str
    full_name: str | None
    primary_role: Role = Field(description="Legacy users.role; unchanged by v2 (ADR-0007).")
    roles: list[Role]
    status: str
    created_at: UtcDateTime


class DriverEligibilitySummaryDTO(ContractModel):
    verification_status: str | None
    eligible: bool
    reasons: list[str]
    has_active_obligations: bool


class CapabilitiesDTO(ContractModel):
    roles: list[Role]
    capabilities: list[Capability]
    driver_eligibility: DriverEligibilitySummaryDTO | None = Field(
        description="Present when the account has the driver role."
    )


class RoleActivateRequest(ContractModel):
    role: Literal["client", "driver"]


class DriverEligibilityCommand(VersionedCommand):
    action: Literal["block", "unblock"]
    reason: str = Field(min_length=3, max_length=500)


class DriverEligibilityDTO(ContractModel):
    user_id: str
    eligible: bool
    blocked_reason: str | None
    active_trip_ids: list[str]
    version: int = Field(description="Eligibility version: 1 + number of block and unblock events.")


# --- Staff MFA (I6-I11, ADR-0021; API_V2_CONTRACT §13a) ---------------------------------------------------


class StaffMfaStateDTO(ContractModel):
    """What the staff member's own security screen shows. Never carries a secret, a code or a hash."""

    enrolled: bool = Field(description="A pending or active factor exists.")
    active: bool = Field(description="An activated factor exists; step-up is possible.")
    pending_activation: bool = Field(description="An enrollment is waiting for a different super_admin.")
    mode: str = Field(description="Rollout stage: audit_only | enforce_privileged | enforce_all.")
    enforced: bool = Field(
        description="False while a missing or stale factor is only recorded (audit-only, or a single "
        "active super_admin - enforcing then would lock the platform's only operator out)."
    )
    active_super_admin_count: int = Field(
        description="Why enforcement may still be off: it needs at least two active super_admins."
    )
    stepped_up_at: UtcDateTime | None
    step_up_fresh: bool
    step_up_max_age_seconds: int
    recovery_codes_remaining: int
    failed_attempts_in_window: int = Field(description="Submitted codes that did not match, in the window.")
    max_failed_attempts: int


class StaffMfaEnrollmentDTO(ContractModel):
    """Returned exactly once. The secret and the recovery codes are never readable again."""

    factor_id: str
    secret: str = Field(description="Base32 TOTP secret; shown once, stored only sealed.")
    provisioning_uri: str = Field(description="otpauth:// URI for an authenticator app.")
    recovery_codes: list[str] = Field(description="One-time codes; shown once. They restore enrollment, never approval.")
    activation_required: bool = Field(
        default=True, description="A different super_admin must confirm one live code before the factor works."
    )


class StaffMfaCodeCommand(ContractModel):
    code: str = Field(min_length=4, max_length=32, description="TOTP digits, or a recovery code on the recovery route.")


class StaffMfaStepUpDTO(ContractModel):
    stepped_up_at: UtcDateTime
    expires_at: UtcDateTime = Field(description="After this the next money or flag command asks again.")


class StaffMfaRecoveryDTO(ContractModel):
    enrollment_allowed: bool = Field(description="Always true on success: the code buys a new enrollment, nothing else.")
    recovery_codes_remaining: int
    factor_revoked: bool = Field(description="The previous factor is revoked, so the account is not left half-protected.")


class StaffMfaFactorDTO(ContractModel):
    user_id: str
    status: str = Field(description="pending | active | revoked")
    activated_at: UtcDateTime | None
    version: int


class StaffMfaResetCommand(ContractModel):
    reason: str = Field(min_length=3, max_length=500)


class StaffMfaResetDTO(ContractModel):
    user_id: str
    factors_revoked: int
    recovery_codes_invalidated: bool = True
