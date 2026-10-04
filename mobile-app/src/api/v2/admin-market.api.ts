/**
 * Admin v2 lookups added for the "Elchi Admin" design (chunk B): queue counts, one booking for the `bk` drawer and
 * the staff searches that replace raw id inputs. Contract: elchi-dev/ADMIN-BACKEND-CONTRACT.md §4, §5.
 *
 * Types come from the generated `Schemas` (`generated/v2.ts`).
 * Every call uses the admin session. Searches that return names or phones are audited by the server, never here.
 */
import { v2AdminRequest, type Schemas } from "./http";

export type StaffBookingDTO = Schemas["BookingDTO"];

/** §4.1: one row per queue. `capped` means the real number is at least `cap` - the screen shows "200+". */
export type OpsQueueCountDTO = Schemas["OpsQueueCountDTO"];

export function opsQueueSummary(params: { corridor_id?: string } = {}) {
  return v2AdminRequest<OpsQueueCountDTO[]>("/admin/ops/queues/summary", { query: params });
}

/** "14", or "200+" when the server stopped counting at its cap. */
export function queueCountText(row: OpsQueueCountDTO | undefined): string | null {
  if (!row) return null;
  return row.capped ? `${row.cap}+` : String(row.count);
}

/**
 * §5.3: the `bk` drawer reads one booking through the participant path; staff holding `ops.view` get the staff view
 * (party names and phones, commission status), audited by the server as surface B1.
 */
export function staffBooking(bookingId: string) {
  return v2AdminRequest<StaffBookingDTO>(`/bookings/${encodeURIComponent(bookingId)}`);
}

/** §5.3: a full `bkg_...` id or ≥ 4 characters from the start of the code. Newest first. */
export function searchAdminBookings(q: string, limit = 10) {
  return v2AdminRequest<StaffBookingDTO[]>("/admin/bookings/search", { query: { q, limit } });
}

/** §5.2. */
export type AdminUserSearchDTO = Schemas["AdminUserSearchDTO"];

export function searchAdminUsers(q: string, params: { role?: string; limit?: number } = {}) {
  return v2AdminRequest<AdminUserSearchDTO[]>("/admin/users/search", { query: { q, role: params.role, limit: params.limit ?? 20 } });
}

/** §5.4. No phone or plate, so no audit row. */
export type AdminTripSearchDTO = Schemas["AdminTripSearchDTO"];

export function searchAdminTrips(q: string, limit = 20) {
  return v2AdminRequest<AdminTripSearchDTO[]>("/admin/trips/search", { query: { q, limit } });
}

/** The minimum query length per search, mirrored from the contract so the box does not send what the server refuses. */
export const SEARCH_MIN = { users: 3, bookings: 4, trips: 4 } as const;
