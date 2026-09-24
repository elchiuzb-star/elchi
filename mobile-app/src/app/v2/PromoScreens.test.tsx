/**
 * Referral stage 5 screens: what a client and a driver may read, and that consent is never implied.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NO_CONSENT, type ConsentChoice } from "../promo";
import { AcceptConsentPanel, PromoMoneyCard } from "./PromoScreens";

const client = {
  view: "client" as const,
  fare_minor: 20_000_000,
  passenger_discount_minor: 500_000,
  cash_due_minor: 19_500_000,
  currency: "UZS" as const,
};
const driver = {
  view: "driver" as const,
  fare_minor: 20_000_000,
  passenger_discount_minor: 500_000,
  cash_to_collect_minor: 19_500_000,
  base_commission_minor: 2_000_000,
  passenger_discount_covered_minor: 500_000,
  driver_credit_minor: 300_000,
  commission_charged_minor: 1_200_000,
  driver_keeps_minor: 18_300_000,
  currency: "UZS" as const,
};

describe("PromoMoneyCard", () => {
  it("shows the client the fare, the bonus and the cash - and nothing about the commission (Q16)", () => {
    const { container } = render(<PromoMoneyCard promo={client} />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/195[\s ]000/);
    expect(text).not.toMatch(/Komissiya|kredit|Balansingizdan|Sizda qoladi/);
  });

  it("shows the driver the cash to collect, the charge and what stays (synthetic example)", () => {
    const { container } = render(<PromoMoneyCard promo={driver} />);
    const text = (container.textContent ?? "").replace(/ /g, " ");
    expect(text).toContain("195 000");
    expect(text).toContain("12 000");
    expect(text).toContain("183 000");
  });

  it("renders nothing for a booking without a discount", () => {
    const { container } = render(<PromoMoneyCard promo={null} />);
    expect(container.textContent).toBe("");
  });
});

describe("AcceptConsentPanel", () => {
  it("starts unticked and reports only an explicit tick", () => {
    let choice: ConsentChoice = NO_CONSENT;
    const onChoice = vi.fn((next: ConsentChoice) => {
      choice = next;
    });
    const { rerender } = render(<AcceptConsentPanel quote={client} choice={choice} onChoice={onChoice} />);
    rerender(<AcceptConsentPanel quote={client} choice={choice} onChoice={onChoice} />);
    const box = screen.getByRole("checkbox");
    expect(box).not.toBeChecked();
    expect(choice.useBonus).toBe(false);
    fireEvent.click(box);
    expect(choice.useBonus).toBe(true);
  });
});

describe("stage 5 screens", () => {
  it("draws the referral QR on the device from exactly the given link, without any request", async () => {
    const { ReferralQr } = await import("./PromoScreens");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.reject(new Error("no network")));
    const { container } = render(<ReferralQr url="https://example.invalid/r/AB2CD3EF" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-label")).toBe("Taklif havolasining QR kodi");
    expect(container.querySelector("path")?.getAttribute("d")?.length ?? 0).toBeGreaterThan(100);
    expect(container.innerHTML).not.toMatch(/<img|http:\/\/|chart\.googleapis|api\.qrserver/);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("explains a missing discount in plain words", async () => {
    const { NoDiscountNote } = await import("./PromoScreens");
    const { container } = render(<NoDiscountNote reason="bonus_expired" />);
    expect(container.textContent).toMatch(/Nega chegirma yo'q\?.*muddati tugagan/);
    const empty = render(<NoDiscountNote reason={null} />);
    expect(empty.container.textContent).toBe("");
  });

  it("asks only the author of a stale offer to confirm again, with the numbers shown now", async () => {
    const { StaleConfirmation } = await import("./PromoScreens");
    const valid = render(
      <StaleConfirmation threadId="pth_x" side="client" version={{ id: "prv_x", promo_confirmation: "valid", promo_quote: client }} onDone={() => undefined} />,
    );
    expect(valid.container.textContent).toBe("");
    const stale = render(
      <StaleConfirmation threadId="pth_x" side="client" version={{ id: "prv_x", promo_confirmation: "stale", promo_quote: client }} onDone={() => undefined} />,
    );
    const text = (stale.container.textContent ?? "").replace(/ /g, " ");
    expect(text).toMatch(/qayta tasdiqlang/);
    expect(text).toContain("195 000");
    expect(text).toMatch(/Taklifning o'zi o'zgarmaydi/);
    expect(screen.getByRole("button", { name: "Shu hisobga roziman" })).toBeTruthy();
  });
});
