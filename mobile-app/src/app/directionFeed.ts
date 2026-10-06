/**
 * ADR-0027: the rules of the driver's direction screens, kept out of React so they are testable without a browser
 * (the way `feedGroups.ts` and `auction.ts` are).
 *
 * The server already says how each request meets the driver (`fit`); this module only cuts the page into the three
 * answers the screen draws apart - a request the trip already reaches on time, one that a first offer would plan a
 * trip around, and one at another time, which can only become a time proposal the client then agrees to or not.
 */
import { ApiError } from "../types/api";
import type { Schemas } from "../api/v2/http";

type DirectionRequestItem = Schemas["DirectionRequestItemDTO"];
type DirectionEnd = Schemas["DirectionEndDTO"];

export type FeedDay = "today" | "tomorrow" | "week";

export interface DirectionGroups {
  fits: DirectionRequestItem[];
  fresh: DirectionRequestItem[];
  otherTime: DirectionRequestItem[];
}

/** The server's order is kept inside each group (it sorts by time already). */
export function groupDirectionItems(items: DirectionRequestItem[]): DirectionGroups {
  return {
    fits: items.filter((item) => item.fit === "fits_trip"),
    fresh: items.filter((item) => item.fit === "no_trip"),
    otherTime: items.filter((item) => item.fit === "time_differs"),
  };
}

const TASHKENT_OFFSET_MS = 5 * 3600 * 1000; // UTC+5, no daylight saving

/** The Tashkent calendar day(s) the chips mean, as an ISO range the API accepts (offset included). */
export function feedRange(day: FeedDay, now: Date = new Date()): { date_from: string; date_to: string } {
  const local = new Date(now.getTime() + TASHKENT_OFFSET_MS);
  const midnightUtc = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()) - TASHKENT_OFFSET_MS;
  const dayMs = 24 * 3600 * 1000;
  const start = day === "tomorrow" ? midnightUtc + dayMs : now.getTime();
  const end = day === "today" ? midnightUtc + dayMs : day === "tomorrow" ? midnightUtc + 2 * dayMs : now.getTime() + 7 * dayMs;
  return { date_from: new Date(start).toISOString(), date_to: new Date(end).toISOString() };
}

/** "HH:MM" in Tashkent. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const local = new Date(new Date(iso).getTime() + TASHKENT_OFFSET_MS);
  return `${String(local.getUTCHours()).padStart(2, "0")}:${String(local.getUTCMinutes()).padStart(2, "0")}`;
}

/** An end's name for a card: the district when there is one, else the region (a city without districts). */
export function directionEndName(end: DirectionEnd, ru = false): string {
  if (end.district_id) return (ru && end.district_name_ru) || end.district_name_uz || "-";
  return (ru && end.region_name_ru) || end.region_name_uz;
}

/** `409 TIME_WINDOW_CONFLICT` with the car's real ETA: the screen offers to send exactly that time instead - unless the
 * server says no time proposal can work (Q157: more than 3 h earlier or 12 h later than the client asked). */
export function timeProposalEta(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== "TIME_WINDOW_CONFLICT") return null;
  const details = (error.details ?? {}) as { eta?: unknown; time_proposal_possible?: unknown; reason?: unknown };
  if (details.time_proposal_possible === false || details.reason === "time_proposal_too_far") return null;
  return typeof details.eta === "string" ? details.eta : null;
}

/** Q157: the server's limits when the car's time is too far from the client's - for an honest sentence. */
export function timeProposalTooFar(error: unknown): { early: number; late: number } | null {
  if (!(error instanceof ApiError) || error.code !== "TIME_WINDOW_CONFLICT") return null;
  const details = (error.details ?? {}) as { time_proposal_possible?: unknown; reason?: unknown; max_early_minutes?: unknown; max_late_minutes?: unknown };
  if (details.time_proposal_possible !== false && details.reason !== "time_proposal_too_far") return null;
  const hours = (value: unknown, fallback: number) => (typeof value === "number" ? Math.round(value / 60) : fallback);
  return { early: hours(details.max_early_minutes, 3), late: hours(details.max_late_minutes, 12) };
}

/** `409 ROUTE_MISMATCH` on create: no ELCHI road serves these two ends yet - a product answer, said as such. */
export function isNoRoad(error: unknown): boolean {
  return error instanceof ApiError && error.code === "ROUTE_MISMATCH";
}

/** `400 VALIDATION_ERROR` with `direction_exists`: the same two ends are already one of the driver's directions. */
export function isDuplicateDirection(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.code !== "VALIDATION_ERROR") return false;
  return (error.details as { reason?: unknown } | undefined)?.reason === "direction_exists";
}

/** `409 BOOKING_CUTOFF_PASSED` / `pickup_passed`: the car is already past this pickup (Q154). */
export function isPickupPassed(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.code !== "BOOKING_CUTOFF_PASSED") return false;
  return (error.details as { reason?: unknown } | undefined)?.reason === "pickup_passed";
}

/** The direction the feed opens on: the one already chosen while it is still live, else the first active one. */
export function pickDirection(list: ReadonlyArray<{ id: string; status: string }>, current: string): string {
  if (list.some((direction) => direction.id === current && direction.status !== "archived")) return current;
  return list.find((direction) => direction.status === "active")?.id ?? list.find((direction) => direction.status !== "archived")?.id ?? "";
}

/** "06.10 22:04" in Tashkent - when the time of day is the point (an ETA, a departure, a time proposal). */
export function dayClock(iso: string | null | undefined): string {
  if (!iso) return "-";
  const local = new Date(new Date(iso).getTime() + TASHKENT_OFFSET_MS);
  const day = `${String(local.getUTCDate()).padStart(2, "0")}.${String(local.getUTCMonth() + 1).padStart(2, "0")}`;
  return `${day} ${clockTime(iso)}`;
}
