/**
 * ADR-0025 screens: the saved request's summary in every state (loading, empty, error, active, expired, booked) and
 * the edit form. SYNTHETIC data only.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TripIntentDTO } from "../../api/v2/tripIntents.api";
import { TripIntentEditor, TripIntentFitNotes, TripIntentSummary, editProblems, intentEditForm } from "./TripIntentPanel";

function intent(overrides: Partial<TripIntentDTO> = {}): TripIntentDTO {
  const start = new Date(Date.now() + 26 * 3600 * 1000);
  const end = new Date(start.getTime() + 2 * 3600 * 1000);
  return {
    id: "tin_synthetic",
    service_type: "passenger",
    status: "active",
    version: 2,
    expired: false,
    current_version: {
      version_no: 2,
      terms_version: 1,
      origin: { stop: null, district: { id: "dst_a", name_uz: "Toshkent" }, lat: 41.3, lng: 69.2, address: null },
      destination: { stop: null, district: { id: "dst_b", name_uz: "Qarshi" }, lat: 38.8, lng: 65.8, address: null },
      window_start: start.toISOString(),
      window_end: end.toISOString(),
      quantity: 3,
      price_basis: "per_seat",
      unit_price_minor: 19_000_000,
      total_minor: 57_000_000,
      currency: "UZS",
      parcel: null,
      created_at: start.toISOString(),
    },
    booking_id: null,
    booking_cancelled: false,
    can_reopen: false,
    open_offers: 0,
    offers: [],
    created_at: start.toISOString(),
    updated_at: start.toISOString(),
    ...overrides,
  } as TripIntentDTO;
}

const handlers = () => ({ onEdit: vi.fn(), onNew: vi.fn(), onReopen: vi.fn(), onRetry: vi.fn(), onSelect: vi.fn() });
const text = (el: HTMLElement) => (el.textContent ?? "").replace(/\s/g, " ");

describe("TripIntentSummary", () => {
  it("shows a skeleton while loading, and an honest empty state that says the request is private", () => {
    const { container, rerender } = render(
      <TripIntentSummary intent={null} others={[]} loading error={null} {...handlers()} />,
    );
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
    const h = handlers();
    rerender(<TripIntentSummary intent={null} others={[]} loading={false} error={null} {...h} />);
    expect(text(container)).toContain("boshqalarga ko'rinmaydi");
    fireEvent.click(screen.getByText("Yangi safar/jo'natma"));
    expect(h.onNew).toHaveBeenCalled();
  });

  it("offers a retry when the request could not be read", () => {
    const h = handlers();
    render(<TripIntentSummary intent={null} others={[]} loading={false} error="Tarmoq yo'q" {...h} />);
    fireEvent.click(screen.getByText("Qayta urinish"));
    expect(h.onRetry).toHaveBeenCalled();
  });

  it("reads as one line with the unit-explicit price and the two actions", () => {
    const h = handlers();
    const { container } = render(<TripIntentSummary intent={intent()} others={[]} loading={false} error={null} {...h} />);
    expect(screen.getByTestId("intent-summary").textContent).toMatch(/^Toshkent → Qarshi · .+ · 3 kishi$/);
    expect(text(container)).toContain("3 kishi × 190 000 so'm = 570 000 so'm");
    fireEvent.click(screen.getByText("Tahrirlash"));
    expect(h.onEdit).toHaveBeenCalled();
  });

  it("asks for a new time when the window has passed instead of moving it", () => {
    const { container } = render(
      <TripIntentSummary intent={intent({ expired: true })} others={[]} loading={false} error={null} {...handlers()} />,
    );
    expect(text(container)).toContain("avtomatik o'zgartirilmaydi");
    expect(screen.getByText("Vaqtni yangilash")).toBeTruthy();
  });

  it("after a cancelled booking only an explicit 'search again' restarts, the old offers stay closed", () => {
    const h = handlers();
    const booked = intent({ status: "booked", booking_id: "bkg_x", booking_cancelled: true, can_reopen: true });
    const { container } = render(<TripIntentSummary intent={booked} others={[]} loading={false} error={null} {...h} />);
    expect(text(container)).toContain("Eski takliflar qayta ochilmaydi");
    expect(screen.queryByText("Tahrirlash")).toBeNull();
    fireEvent.click(screen.getByText("Qayta qidirish"));
    expect(h.onReopen).toHaveBeenCalled();
  });

  it("lists the client's other live requests without merging them", () => {
    const h = handlers();
    const other = intent({
      id: "tin_other",
      service_type: "parcel",
      current_version: { ...intent().current_version, quantity: 1, parcel: null },
    });
    render(<TripIntentSummary intent={intent()} others={[intent(), other]} loading={false} error={null} {...h} />);
    fireEvent.click(screen.getByText(/1 jo'natma$/));
    expect(h.onSelect).toHaveBeenCalledWith(other);
  });
});

describe("TripIntentFitNotes", () => {
  it("says when everything matches and lists the differences otherwise", () => {
    const fit = {
      listing_id: "lst",
      intent_version_no: 1,
      service_match: true,
      expired: false,
      time: { status: "inside", minutes_outside: 0 },
      availability: { status: "ok", requested: 3, available: 3 },
      origin: { status: "same_stop" },
      destination: { status: "same_stop" },
      price: {},
      blockers: [],
    };
    const { container, rerender } = render(<TripIntentFitNotes fit={fit as never} loading={false} />);
    expect(text(container)).toContain("mos");
    rerender(
      <TripIntentFitNotes
        fit={{ ...fit, availability: { status: "insufficient", requested: 3, available: 2 } } as never}
        loading={false}
      />,
    );
    expect(text(container)).toContain("2 ta bo'sh o'rin");
  });
});

describe("TripIntentEditor", () => {
  it("starts from the saved values, warns about open offers and refuses a past window", () => {
    const onSave = vi.fn();
    const saved = intent({ open_offers: 2 });
    const { container } = render(
      <TripIntentEditor intent={saved} busy={false} onSave={onSave} onChangeRoute={vi.fn()} onClose={vi.fn()} />,
    );
    expect(text(container)).toContain("2 ta ochiq taklif");
    fireEvent.click(screen.getByText("Saqlash"));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ quantity: 3, price: "190000" }));
    const past = { ...intentEditForm(saved), windowStart: "2020-01-01T10:00", windowEnd: "2020-01-01T12:00" };
    expect(editProblems(past)).toContain("Vaqt o'tib ketgan - kelajakdagi vaqtni tanlang.");
  });
});
