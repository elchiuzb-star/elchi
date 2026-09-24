/**
 * T4 decisions on the client side (ADR-0023 §18.1, Q123-Q129) and the stage-5 texts: why no discount, the amendment
 * cash explanation, the referral progress, the driver's confirmation of its own numbers. SYNTHETIC amounts only.
 */
import { describe, expect, it } from "vitest";

import { proofCodeHint } from "./proofCodes";
import {
  NO_DISCOUNT_TEXT,
  amendmentCashNote,
  counterpartyMustReconfirm,
  driverAckRequested,
  noDiscountText,
  progressRows,
} from "./promo";

describe("why there is no discount", () => {
  it("has a plain sentence for every server category and nothing about rates, limits or checks", () => {
    const reasons = ["service_not_eligible", "bonus_expired", "bonus_reserved", "bonus_on_hold", "no_campaign",
      "client_update_required", "trip_terms"];
    expect(Object.keys(NO_DISCOUNT_TEXT).sort()).toEqual([...reasons].sort());
    for (const reason of reasons) {
      const text = noDiscountText(reason) ?? "";
      expect(text.length).toBeGreaterThan(10);
      expect(text).not.toMatch(/komissiya|foiz|bps|firibgar|risk|marja|formula|\d/i);
    }
    expect(noDiscountText(null)).toBeNull();
    expect(noDiscountText("something_new")).toBeNull();
  });
});

describe("amendment cash (Q125)", () => {
  const before = { fare_minor: 20_000_000, passenger_discount_minor: 500_000, cash_due_minor: 19_500_000 };

  it("says out loud when a lower fare still raises the cash", () => {
    const after = { fare_minor: 19_900_000, passenger_discount_minor: 300_000, cash_due_minor: 19_600_000 };
    expect(amendmentCashNote(before, after)).toMatch(/narx kamaygan bo'lsa ham, naqd to'lovingiz oshadi/);
  });

  it("explains a smaller discount on a lower fare and a discount that never grows on a higher one", () => {
    expect(amendmentCashNote(before, { fare_minor: 8_000_000, passenger_discount_minor: 400_000, cash_due_minor: 7_600_000 }))
      .toMatch(/bonus chegirmasi ham kamaydi/);
    expect(amendmentCashNote(before, { fare_minor: 25_000_000, passenger_discount_minor: 500_000, cash_due_minor: 24_500_000 }))
      .toMatch(/yangi bonus ishlatilmaydi/);
    expect(amendmentCashNote(before, before)).toBeNull();
  });
});

describe("referral progress (stage 5)", () => {
  it("never counts a service that is still being checked as done", () => {
    const rows = progressRows({ unit: "service", required: 2, done: 0, in_review: 1, remaining: 1, milestones: [] });
    expect(rows.map((r) => [r.label, r.value])).toEqual([
      ["Bajarilgan", "0 / 2 xizmat"],
      ["Tekshiruvda", "1 xizmat"],
      ["Qolgan", "1 xizmat"],
    ]);
    expect(rows[1].hint).toMatch(/hali bajarilgan hisoblanmaydi/);
    const trips = progressRows({ unit: "distinct_trip", required: 10, done: 5, in_review: 2, remaining: 3, milestones: [] });
    expect(trips[0].value).toBe("5 / 10 safar");
  });
});

describe("driver and counterparty confirmations (Q125, Q126)", () => {
  it("reads the driver's own numbers from the server's request, and only for the driver", () => {
    const asked = { code: "PROMO_CONSENT_REQUIRED", details: { party: "driver", cash_to_collect_minor: 7_600_000, commission_charged_minor: 400_000 } };
    expect(driverAckRequested(asked)).toEqual({ cash_to_collect_minor: 7_600_000, commission_charged_minor: 400_000 });
    expect(driverAckRequested({ code: "PROMO_CONSENT_REQUIRED", details: { cash_due_minor: 1 } })).toBeNull();
    expect(driverAckRequested({ code: "PROMO_QUOTE_STALE", details: { party: "driver" } })).toBeNull();
  });

  it("tells the acting person when only the other side can fix a stale confirmation", () => {
    expect(counterpartyMustReconfirm({ code: "PROMO_QUOTE_STALE", details: { reasons: ["counterparty_confirmation_stale"] } })).toBe(true);
    expect(counterpartyMustReconfirm({ code: "PROMO_QUOTE_STALE", details: { reasons: ["counterparty_client_outdated"] } })).toBe(true);
    expect(counterpartyMustReconfirm({ code: "PROMO_QUOTE_STALE", details: { reasons: ["passenger_bonus_changed"] } })).toBe(false);
    expect(counterpartyMustReconfirm({ code: "VERSION_CONFLICT", details: { reasons: ["counterparty_client_outdated"] } })).toBe(false);
  });
});

describe("proof code hints", () => {
  it("never tells a passenger to hand over a parcel", () => {
    expect(proofCodeHint("boarding_code")).not.toMatch(/posilka|jo'natma/i);
    expect(proofCodeHint("boarding_code")).toMatch(/Mashinaga/);
    expect(proofCodeHint("pickup_code")).toMatch(/posilkani topshirayotganda/);
    expect(proofCodeHint("delivery_code")).toMatch(/qabul qiluvchiga/);
  });
});
