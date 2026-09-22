/** Staff MFA (ADR-0021, I6-I11) for the admin panel.
 *
 * The secret and the recovery codes come back exactly once, from `enroll`. They are held in React state for as
 * long as the screen shows them and never written to storage - a second factor kept next to the password it
 * protects is not a second factor.
 */
import { newIdempotencyKey, v2AdminRequest, type Schemas } from "./http";

export type StaffMfaStateDTO = Schemas["StaffMfaStateDTO"];
export type StaffMfaEnrollmentDTO = Schemas["StaffMfaEnrollmentDTO"];
export type StaffMfaStepUpDTO = Schemas["StaffMfaStepUpDTO"];
export type StaffMfaRecoveryDTO = Schemas["StaffMfaRecoveryDTO"];
export type StaffMfaFactorDTO = Schemas["StaffMfaFactorDTO"];
export type StaffMfaResetDTO = Schemas["StaffMfaResetDTO"];

export function mfaState() {
  return v2AdminRequest<StaffMfaStateDTO>("/me/mfa");
}

/** Starts an enrollment. The factor stays pending until a *different* super_admin activates it. */
export function enrollMfa() {
  return v2AdminRequest<StaffMfaEnrollmentDTO>("/me/mfa/enroll", {
    method: "POST",
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Proves the factor for the next few minutes of money and flag commands (`step_up_max_age_seconds`). */
export function stepUp(code: string) {
  return v2AdminRequest<StaffMfaStepUpDTO>("/me/mfa/step-up", {
    method: "POST",
    body: { code },
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Spends one recovery code: it restores the ability to enroll, and nothing else (Q17/Q49). */
export function useRecoveryCode(code: string) {
  return v2AdminRequest<StaffMfaRecoveryDTO>("/me/mfa/recovery", {
    method: "POST",
    body: { code },
    idempotencyKey: newIdempotencyKey(),
  });
}

/** `staff.mfa_approve` (super_admin): confirm one live code from somebody else's authenticator. */
export function activateStaffMfa(userId: string, code: string) {
  return v2AdminRequest<StaffMfaFactorDTO>(`/admin/staff/${encodeURIComponent(userId)}/mfa/activate`, {
    method: "POST",
    body: { code },
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Lost phone: revoke somebody else's factor and their unused recovery codes. Grants nothing. */
export function resetStaffMfa(userId: string, reason: string) {
  return v2AdminRequest<StaffMfaResetDTO>(`/admin/staff/${encodeURIComponent(userId)}/mfa/reset`, {
    method: "POST",
    body: { reason },
    idempotencyKey: newIdempotencyKey(),
  });
}
