/**
 * The driver's commission estimate before a bid is sent (W11 `GET /commission/quote`).
 *
 * Driver-only by construction: the client never sees commission (Q16), and this module is only ever called from
 * driver screens. The number is an estimate under today's policy - nothing is held until a booking is accepted,
 * the booking snapshots the policy of that moment (AC43), and a commission is never money received (§9).
 */

/**
 * The total the server would put on this bid (`marketplace.rules.compute_total_minor`): `per_seat` multiplies by
 * the quantity, `total` is already the whole price. Zero when there is nothing to quote yet.
 */
export function bidTotalMinor(priceBasis: string, unitPriceMinor: number, quantity: number): number {
  if (!Number.isInteger(unitPriceMinor) || unitPriceMinor <= 0) return 0;
  if (priceBasis === "per_seat") {
    return Number.isInteger(quantity) && quantity > 0 ? unitPriceMinor * quantity : 0;
  }
  return unitPriceMinor;
}

/** Basis points as a percentage for a sentence: 1000 -> "10", 750 -> "7.5". */
export function bpsPercent(bps: number): string {
  if (!Number.isFinite(bps)) return "-";
  const percent = bps / 100;
  return Number.isInteger(percent) ? String(percent) : percent.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}
