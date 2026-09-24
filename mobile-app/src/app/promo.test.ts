import { beforeEach, describe, expect, it } from "vitest";

import {
  NO_CONSENT,
  actionKey,
  bucketRows,
  cashDueMinor,
  clientMoneyLines,
  codeFromPath,
  consentBody,
  disclosureText,
  driverMoneyLines,
  finishAction,
  forgetCode,
  needsRequote,
  normalizeCode,
  pendingCode,
  rememberCode,
  withPreview,
  type BookingPromoClientDTO,
  type BookingPromoDriverDTO,
  type ProposalPromoClientDTO,
} from "./promo";

const clientPromo: BookingPromoClientDTO = {
  view: "client",
  fare_minor: 20_000_000,
  passenger_discount_minor: 500_000,
  cash_due_minor: 19_500_000,
  currency: "UZS",
};
const driverPromo: BookingPromoDriverDTO = {
  view: "driver",
  fare_minor: 20_000_000,
  passenger_discount_minor: 500_000,
  cash_to_collect_minor: 19_500_000,
  base_commission_minor: 2_000_000,
  passenger_discount_covered_minor: 500_000,
  driver_credit_minor: 300_000,
  commission_charged_minor: 1_200_000,
  driver_keeps_minor: 18_300_000,
  currency: "UZS",
};
const preview: ProposalPromoClientDTO = { ...clientPromo };

describe("cash due", () => {
  it("is F_cash on a discounted booking and the fare otherwise", () => {
    expect(cashDueMinor({ total_minor: 20_000_000, promo: clientPromo })).toBe(19_500_000);
    expect(cashDueMinor({ total_minor: 20_000_000, promo: driverPromo })).toBe(19_500_000);
    expect(cashDueMinor({ total_minor: 20_000_000, promo: null })).toBe(20_000_000);
  });

  it("shows the client no commission line and the driver the synthetic example", () => {
    const client = clientMoneyLines(clientPromo).map((line) => line.label.toLowerCase());
    expect(client.join(" ")).not.toMatch(/komissiya|kredit|balans/);
    const driver = Object.fromEntries(driverMoneyLines(driverPromo).map((line) => [line.label, line.minor]));
    expect(driver["Mijozdan naqd olasiz"]).toBe(19_500_000);
    expect(driver["Balansingizdan yechiladi"]).toBe(1_200_000);
    expect(driver["Sizda qoladi"]).toBe(18_300_000);
  });
});

describe("consent", () => {
  it("is never pre-filled: nothing is sent until the person ticks it", () => {
    const shown = withPreview(NO_CONSENT, preview);
    expect(shown.useBonus).toBe(false);
    expect(consentBody(shown)).toBeUndefined();
    expect(consentBody({ ...shown, useBonus: true })).toEqual({ passenger_bonus_minor: 500_000, cash_due_minor: 19_500_000 });
  });

  it("drops the tick when the numbers change (a new price is a new agreement)", () => {
    const ticked = { useBonus: true, shown: preview };
    expect(withPreview(ticked, { ...preview }).useBonus).toBe(true);
    expect(withPreview(ticked, { ...preview, fare_minor: 8_000_000, cash_due_minor: 7_600_000, passenger_discount_minor: 400_000 }).useBonus).toBe(false);
    expect(withPreview(ticked, null)).toEqual({ useBonus: false, shown: null });
  });

  it("recognises the refusals that need a new quote", () => {
    expect(needsRequote({ code: "PROMO_QUOTE_STALE" })).toBe(true);
    expect(needsRequote({ code: "PROMO_CONSENT_REQUIRED" })).toBe(true);
    expect(needsRequote({ code: "VALIDATION_ERROR" })).toBe(false);
  });
});

describe("texts", () => {
  it("never promises a reward for signing up and says a bonus is not cash", () => {
    expect(disclosureText({ code: "not_cash", value: true })).toMatch(/pul emas/);
    expect(disclosureText({ code: "next_eligible_service", value: true })).toMatch(/ro'yxatdan o'tganingiz uchun emas/);
    expect(disclosureText({ code: "risk_check", value: 172800 })).toMatch(/2 kun/);
    expect(disclosureText({ code: "unknown", value: 1 })).toBeNull();
  });

  it("keeps the five states apart and calls none of them money", () => {
    const rows = bucketRows({
      instrument: "passenger_bonus", service_type: "passenger", available_minor: 1, reserved_minor: 2,
      under_review_minor: 3, consumed_minor: 4, expired_minor: 5, reversed_minor: 6, next_expiry_at: null, currency: "UZS",
    });
    expect(rows.map((row) => row.minor)).toEqual([1, 2, 3, 4, 11]);
    expect(rows.map((row) => row.label).join(" ").toLowerCase()).not.toMatch(/pul|yechib/);
  });
});

describe("referral code from a link", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("reads /r/<code> and normalises like the server", () => {
    expect(codeFromPath("/r/ab2c-d3ef")).toBe("AB2CD3EF");
    expect(codeFromPath("/r/short")).toBeNull();
    expect(codeFromPath("/login")).toBeNull();
    expect(normalizeCode(" ab2c d3ef ")).toBe("AB2CD3EF");
    expect(normalizeCode("AB2CD3E0")).toBeNull(); // 0 is not in the alphabet
  });

  it("survives login and is not replaced by a later link", () => {
    rememberCode("AB2CD3EF");
    rememberCode("ZZZZZZZZ");
    expect(pendingCode()).toBe("AB2CD3EF");
    forgetCode();
    expect(pendingCode()).toBeNull();
  });
});

describe("retries", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("reuses one key for one action until it finishes", () => {
    let n = 0;
    const make = () => `k${++n}`;
    expect(actionKey("accept:t1:v1", make)).toBe("k1");
    expect(actionKey("accept:t1:v1", make)).toBe("k1"); // timeout, double tap, app reopened
    finishAction("accept:t1:v1");
    expect(actionKey("accept:t1:v1", make)).toBe("k2");
  });
});
