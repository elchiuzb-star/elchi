/**
 * Staff wallet lookup by driver (DESIGN-ADMIN-DIFF 11b.3): `GET /api/v2/admin/wallets?q=` — name, phone, `usr_` or
 * `wal_` text in, matching driver wallets out. Used only to fill the "Hamyon" field of a new ledger adjustment, so
 * a finance person never has to copy a `wal_…` id by hand.
 *
 * Contract (ADMIN-BACKEND-CONTRACT.md §5.5): capability `finance.reports`; `q` 3–64 chars (name fragment, phone digits,
 * full `usr_…` or `wal_…`); rows `{id, driver{id, display_name}, driver_full_name, driver_phone, currency,
 * posted_balance_minor, held_minor, available_minor}`. The read is audited server side (`wallet_lookup_viewed`).
 * Until the generated types carry it, the row is read defensively: an unknown shape degrades to "type the wal_ id
 * yourself", never to a wrong wallet.
 */
import { v2AdminRequest } from "./http";

export type WalletLookupRow = {
  /** `wal_…` */
  id: string;
  driverId: string | null;
  driverName: string | null;
  phone: string | null;
  /** Posted minus held, tiyin; null when the server did not send it. */
  availableMinor: number | null;
};

export const WALLET_LOOKUP_MIN_QUERY = 3;

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** One server row -> the fields the picker shows; null when the row has no usable wallet id. */
export function toWalletLookupRow(raw: unknown): WalletLookupRow | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  const id = text(row.wallet_id) ?? text(row.id);
  if (!id || !id.startsWith("wal_")) return null;
  const driver = (typeof row.driver === "object" && row.driver !== null ? row.driver : {}) as Record<string, unknown>;
  return {
    id,
    driverId: text(driver.id) ?? text(row.driver_id) ?? text(row.user_id),
    driverName: text(row.driver_full_name) ?? text(driver.display_name) ?? text(driver.full_name) ?? text(row.driver_name),
    phone: text(row.driver_phone) ?? text(driver.phone) ?? text(row.phone),
    availableMinor: typeof row.available_minor === "number" ? row.available_minor : null,
  };
}

export async function searchWallets(q: string, limit = 10): Promise<WalletLookupRow[]> {
  const data = await v2AdminRequest<unknown>("/admin/wallets", { query: { q, limit } });
  const rows = Array.isArray(data) ? data : [];
  return rows.map(toWalletLookupRow).filter((row): row is WalletLookupRow => row !== null);
}
