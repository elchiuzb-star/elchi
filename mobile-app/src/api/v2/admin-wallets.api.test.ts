import { describe, expect, it } from "vitest";

import { toWalletLookupRow } from "./admin-wallets.api";

describe("toWalletLookupRow (ADMIN-BACKEND-CONTRACT §5.5)", () => {
  it("reads the contract row", () => {
    expect(
      toWalletLookupRow({
        id: "wal_x", driver: { id: "usr_d", display_name: "Ali" }, driver_full_name: "Ali Valiyev", driver_phone: "+998900000000",
        currency: "UZS", posted_balance_minor: 5_000_000, held_minor: 120_000, available_minor: 4_880_000,
      }),
    ).toEqual({ id: "wal_x", driverId: "usr_d", driverName: "Ali Valiyev", phone: "+998900000000", availableMinor: 4_880_000 });
  });

  it("refuses a row without a wallet id rather than guessing", () => {
    expect(toWalletLookupRow({ id: "usr_d" })).toBeNull();
    expect(toWalletLookupRow(null)).toBeNull();
  });
});
