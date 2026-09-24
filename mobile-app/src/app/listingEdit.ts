/**
 * The owner's controls on a listing: pause, resume and a versioned edit (L3/L5/L6).
 *
 * Q20 is the rule that makes this worth a module: on a live listing, a change of route, window, quantity or price
 * basis expires every open offer on it, while a new unit price, comment or expiry does not. The owner has to be
 * told that *before* sending, so the diff is computed here - the same way the server classifies it - and the
 * screen asks for a second tap only when the edit is material.
 */

export interface EditableListing {
  status: string;
  kind: string;
  unit_price_minor: number;
  comment?: string | null;
  departure_window_start: string;
  departure_window_end: string;
}

/** What the edit form holds: soum as typed, and `datetime-local` text for the window. */
export interface ListingEditForm {
  price: string;
  comment: string;
  windowStart: string;
  windowEnd: string;
}

export interface ListingPatchPlan {
  /** Only the fields that change; `expected_version` is added by the caller. */
  body: {
    unit_price_minor?: number;
    comment?: string | null;
    departure_window_start?: string;
    departure_window_end?: string;
  };
  /** Q20: this edit expires the open offers of a live listing. */
  material: boolean;
  /** Nothing would change - the send button stays off. */
  empty: boolean;
  /** Something typed cannot be sent as it is (a half-typed date, a window that ends before it starts). */
  invalid: string | null;
}

/** `marketplace.service.LIVE_STATUSES`: where offers exist that an edit could expire. */
const LIVE: readonly string[] = ["published", "paused"];
/** `EDITABLE_STATUSES` */
const EDITABLE: readonly string[] = ["draft", "published", "paused"];

export function ownerListingActions(status: string): { canPause: boolean; canResume: boolean; canEdit: boolean } {
  return { canPause: status === "published", canResume: status === "paused", canEdit: EDITABLE.includes(status) };
}

/**
 * A trip offer's window is derived from its trip's planned stop times - an invented one would be refused at the
 * first proposal - so only a client request lets its owner move the window.
 */
export function windowEditable(listing: Pick<EditableListing, "kind">): boolean {
  return listing.kind === "request";
}

function soumToMinor(value: string): number {
  const parsed = Number(value.replace(/\s/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) * 100 : 0;
}

function toIso(local: string): string | null {
  if (!local) return null;
  const parsed = new Date(local);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/** `datetime-local` text for an ISO instant, in the device's wall clock. */
export function isoToLocalInput(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function formFromListing(listing: EditableListing): ListingEditForm {
  return {
    price: String(Math.round(listing.unit_price_minor / 100)),
    comment: listing.comment ?? "",
    windowStart: isoToLocalInput(listing.departure_window_start),
    windowEnd: isoToLocalInput(listing.departure_window_end),
  };
}

export function planListingPatch(listing: EditableListing, form: ListingEditForm, now: number = Date.now()): ListingPatchPlan {
  const body: ListingPatchPlan["body"] = {};
  let material = false;
  let invalid: string | null = null;

  const price = soumToMinor(form.price);
  if (price <= 0) invalid = "price";
  else if (price !== listing.unit_price_minor) body.unit_price_minor = price;

  const comment = form.comment.trim();
  if (comment !== (listing.comment ?? "").trim()) body.comment = comment || null;

  if (windowEditable(listing)) {
    const start = toIso(form.windowStart);
    const end = toIso(form.windowEnd);
    if (!start || !end) invalid = invalid ?? "window_incomplete";
    else if (new Date(end).getTime() <= new Date(start).getTime()) invalid = invalid ?? "window_order";
    else if (new Date(end).getTime() <= now) invalid = invalid ?? "window_past";
    else {
      const moved = new Date(start).getTime() !== new Date(listing.departure_window_start).getTime()
        || new Date(end).getTime() !== new Date(listing.departure_window_end).getTime();
      if (moved) {
        // The server compares the pair and needs both ends to validate the order, so both travel together.
        body.departure_window_start = start;
        body.departure_window_end = end;
        material = LIVE.includes(listing.status);
      }
    }
  }

  return { body, material, empty: Object.keys(body).length === 0, invalid };
}
