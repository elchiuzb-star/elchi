/**
 * Corridor price references: Q52 gating (editing is admin+, `ops.corridor_manage`), the next version on the button,
 * and the design's range and badge wording. SYNTHETIC data; the API wrappers are mocked.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/v2/ops.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/v2/ops.api")>();
  return {
    ...actual,
    capabilities: vi.fn(),
    listCorridors: vi.fn(),
    listPriceBands: vi.fn(),
    priceBandHistory: vi.fn(),
    setPriceBand: vi.fn(),
  };
});

import * as ops from "../api/v2/ops.api";
import { AdminPriceBandsPanel } from "./AdminPriceBandsPanel";

const m = <T,>(fn: T) => fn as unknown as ReturnType<typeof vi.fn>;

const band = {
  corridor_id: "cor_1", service_type: "parcel", price_basis: "total", floor_minor: 8_000_000, ceiling_minor: 18_000_000,
  currency: "UZS", is_active: true, enforced: false, reason: "pilot", updated_at: "2026-09-26T05:00:00Z", version: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  m(ops.listCorridors).mockResolvedValue([{ id: "cor_1", name: "Toshkent – Samarqand" }]);
  m(ops.listPriceBands).mockResolvedValue([band]);
  m(ops.priceBandHistory).mockResolvedValue([
    { service_type: "parcel", version: 2, new_floor_minor: 8_000_000, new_ceiling_minor: 18_000_000, new_is_active: true,
      reason: "Mavsumiy narxlar", actor: "admin", changed_at: "2026-09-26T05:00:00Z" },
  ]);
});

describe("AdminPriceBandsPanel", () => {
  it("is read-only for the operator (Q52): table and history, no form", async () => {
    m(ops.capabilities).mockResolvedValue({ roles: ["operator"], capabilities: ["ops.view", "ops.booking_command"], driver_eligibility: null });
    render(<AdminPriceBandsPanel />);
    expect(await screen.findByText("80 000 – 180 000 so'm · jami")).toBeInTheDocument();
    expect(await screen.findByText(/faqat admin va undan yuqori/)).toBeInTheDocument();
    expect(screen.getByText("Maslahat")).toBeInTheDocument();
    expect(screen.getByText("Yuk · 80 000 – 180 000 so'm")).toBeInTheDocument();
    expect(screen.queryByText("Quyi chegara (so'm)")).toBeNull();
    expect(screen.queryAllByRole("button", { name: "Yangilash" }).filter((node) => node.getAttribute("type") === "submit")).toHaveLength(0);
  });

  it("lets admin+ save the next version with a reason", async () => {
    m(ops.capabilities).mockResolvedValue({ roles: ["admin"], capabilities: ["ops.view", "ops.corridor_manage"], driver_eligibility: null });
    m(ops.setPriceBand).mockResolvedValue({ data: { ...band, version: 3 }, warnings: [], meta: null });
    render(<AdminPriceBandsPanel />);
    fireEvent.change(await screen.findByDisplayValue("Yo'lovchi (bir o'rin narxi)"), { target: { value: "parcel" } });
    const save = (await screen.findAllByRole("button", { name: "Yangilash" })).find((node) => node.getAttribute("type") === "submit") as HTMLElement;
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Sabab \(auditda ko'rinadi\)/), { target: { value: "Mavsumiy narxlar yangilandi" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(ops.setPriceBand).toHaveBeenCalledWith("cor_1", "parcel", expect.objectContaining({
        expected_version: 2, floor_minor: 8_000_000, ceiling_minor: 18_000_000, enforced: false, reason: "Mavsumiy narxlar yangilandi",
      })),
    );
  });
});
