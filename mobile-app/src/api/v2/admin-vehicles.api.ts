/**
 * Staff vehicle verification and driver eligibility (T3, T3a, I5).
 *
 * A new v2 vehicle is born `pending`; until staff approve it the driver cannot open a trip (`VEHICLE_NOT_ELIGIBLE`).
 * Every command carries an Idempotency-Key the caller keeps for one user action, and `expected_version` from the row
 * it was shown, so a stale screen answers `VERSION_CONFLICT` instead of overwriting someone else's decision.
 * Paths are written out in full so tests/test_mobile_v2_client_contract.py can check them.
 */
import { newIdempotencyKey, v2AdminRequest, v2AdminRequestFull, type Schemas } from "./http";

export type VehicleDTO = Schemas["VehicleDTO"];
export type DriverEligibilityDTO = Schemas["DriverEligibilityDTO"];

/**
 * `GET /admin/vehicles` rows. Written here until the integrator regenerates `v2.ts`; afterwards these become
 * `Schemas["AdminVehicleDTO"]` / `Schemas["AdminVehicleOwnerDTO"]` (same fields, app/modules/trips/schemas.py).
 */
export type AdminVehicleOwner = {
  user_id: string;
  is_driver: boolean;
  account_active: boolean;
  driver_verification_status: string | null;
  eligible: boolean;
  reasons: string[];
  blocked_reason: string | null;
  /** `expected_version` for the eligibility command; null when the owner no longer has the driver role. */
  eligibility_version: number | null;
  active_trip_count: number;
};

export type AdminVehicle = VehicleDTO & {
  verification_reason: string | null;
  verified_at: string | null;
  updated_at: string;
  owner: AdminVehicleOwner;
};

export type AdminVehicleStatus = "pending" | "approved" | "rejected" | "blocked";

export type AdminVehiclePage = { items: AdminVehicle[]; nextCursor: string | null };

/** The verification queue, oldest first. `status` omitted: every status. */
export async function adminVehicles(params: { status?: AdminVehicleStatus; cursor?: string | null; limit?: number } = {}): Promise<AdminVehiclePage> {
  const result = await v2AdminRequestFull<AdminVehicle[]>("/admin/vehicles", {
    query: { status: params.status, cursor: params.cursor ?? undefined, limit: params.limit },
  });
  const meta = result.meta as { next_cursor?: string | null } | null | undefined;
  return { items: result.data, nextCursor: meta?.next_cursor ?? null };
}

/** Approve (from pending/rejected) or reject (from pending/approved). A reject needs a reason; the server refuses one without. */
export function adminVerifyVehicle(
  vehicleId: string,
  body: { decision: "approve" | "reject"; expected_version: number; reason?: string | null },
  idempotencyKey: string = newIdempotencyKey(),
) {
  return v2AdminRequest<VehicleDTO>(`/admin/vehicles/${encodeURIComponent(vehicleId)}/verify`, {
    method: "POST",
    body: { decision: body.decision, expected_version: body.expected_version, reason: body.reason ?? null },
    idempotencyKey,
  });
}

/**
 * Block or unblock a driver's *new* business (D16): active trips, tracking and support go on. `reason` is 3-500
 * characters and lands in the audit trail.
 */
export function adminSetDriverEligibility(
  userId: string,
  body: { action: "block" | "unblock"; expected_version: number; reason: string },
  idempotencyKey: string = newIdempotencyKey(),
) {
  return v2AdminRequest<DriverEligibilityDTO>(`/admin/drivers/${encodeURIComponent(userId)}/eligibility`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}
