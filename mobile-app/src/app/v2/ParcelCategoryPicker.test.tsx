/** Q140 (ADR-0026): the sender picks a server category; no catalog means nothing to pick and an honest reason. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/marketplace.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/v2/marketplace.api")>();
  return { ...actual, parcelCategories: vi.fn() };
});

import * as marketplace from "../../api/v2/marketplace.api";
import { ParcelCategoryLine, ParcelCategoryPicker, categoryLimitsText } from "./ParcelCategoryPicker";

const m = <T,>(fn: T) => fn as unknown as ReturnType<typeof vi.fn>;

const small = {
  id: "pct_1", code: "small_box", name_uz: "Kichik quti", name_ru: null, icon_key: "box_small",
  max_length_cm: 30, max_width_cm: 20, max_height_cm: 20, max_weight_g: 5_000, max_volume_ml: 12_000, display_order: 10,
};

beforeEach(() => vi.clearAllMocks());

describe("ParcelCategoryPicker", () => {
  it("lists the server categories with their limits and returns the picked one", async () => {
    m(marketplace.parcelCategories).mockResolvedValue({ confirmed: true, synthetic: true, items: [small] });
    const picked = vi.fn();
    render(<ParcelCategoryPicker value="" onChange={picked} />);
    const option = await screen.findByRole("radio", { name: /Kichik quti/ });
    expect(option.textContent).toContain(categoryLimitsText(small));
    fireEvent.click(option);
    expect(picked).toHaveBeenCalledWith(small);
    expect(screen.getByText(/Sinov katalogi|Тестовый каталог/)).toBeTruthy();  // synthetic demo values are marked
    expect(screen.queryByRole("textbox")).toBeNull();  // no numeric dimension or weight input
  });

  it("says why nothing can be picked when no catalog is confirmed", async () => {
    m(marketplace.parcelCategories).mockResolvedValue({ confirmed: false, synthetic: false, items: [] });
    render(<ParcelCategoryPicker value="" onChange={vi.fn()} />);
    expect(await screen.findByText(/tasdiqlanmagan|не утверждён/)).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("shows the agreed category line on booking screens", () => {
    render(<ParcelCategoryLine category={small} />);
    expect(screen.getByTestId("parcel-category-line").textContent).toContain("Kichik quti");
  });
});
