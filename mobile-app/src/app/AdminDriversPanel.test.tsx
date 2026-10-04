/**
 * Haydovchilar (§17): operator may only correct the vehicle (Q94), admin+ gets approve/reject/block/unblock, the
 * Buyurtmalar tab reads `/admin/drivers/{id}/orders`, and documents carry their state in words. SYNTHETIC data.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLocale } from "../i18n";
import type { AdminDriver } from "../types/admin-driver";
import type { AuthUser } from "../types/auth";

const api = vi.hoisted(() => ({
  approveDriver: vi.fn(),
  blockDriver: vi.fn(),
  getAdminDriverDetail: vi.fn(),
  getAdminDriverOrders: vi.fn(),
  getAdminDrivers: vi.fn(),
  rejectDriver: vi.fn(),
  unblockDriver: vi.fn(),
  updateDriverVehicle: vi.fn(),
}));
vi.mock("../api/admin-drivers.api", () => api);
vi.mock("../api/cities.api", () => ({ getCities: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/districts.api", () => ({ getDistricts: vi.fn().mockResolvedValue([]) }));

import { AdminDriversPanel, parseDriverTarget } from "./AdminDriversPanel";

function driver(overrides: Partial<AdminDriver> = {}): AdminDriver {
  return {
    id: 120,
    full_name: "Jasur Sintetik",
    phone: "+998907771122",
    verification_status: "blocked",
    is_available: false,
    car_model: "Cobalt",
    car_color: "oq",
    plate_number: "01A452KA",
    documents_count: 3,
    required_documents_count: 5,
    active_routes_count: 1,
    total_routes_count: 2,
    documents: [{ document_type: "passport", status: "approved", file_url: "https://example.invalid/p.jpg" }, { document_type: "license", status: "rejected", rejection_reason: "rasm xira" }],
    routes: [],
    created_at: "2026-09-24T08:00:00Z",
    updated_at: "2026-09-26T08:00:00Z",
    ...overrides,
  } as AdminDriver;
}

function staff(role: string): AuthUser {
  return { id: 1, phone: "+998900000001", role: role as AuthUser["role"], status: "active", is_phone_verified: true };
}

beforeEach(() => {
  setLocale("uz");
  Object.values(api).forEach((mock) => mock.mockReset());
  api.getAdminDrivers.mockResolvedValue({ items: [driver()], pagination: { page: 1, limit: 20, total: 1, total_pages: 1 } });
  api.getAdminDriverDetail.mockResolvedValue(driver());
  api.getAdminDriverOrders.mockResolvedValue([{ id: 9, order_number: "EL-9", status: "delivered", final_price: 90000, created_at: "2026-09-20T08:00:00Z" }]);
});

describe("parseDriverTarget", () => {
  it("reads id:<n> as open-this-driver and anything else as search text", () => {
    expect(parseDriverTarget("id:120")).toEqual({ openId: 120, search: "" });
    expect(parseDriverTarget("+998901112233")).toEqual({ openId: null, search: "+998901112233" });
    expect(parseDriverTarget(undefined)).toEqual({ openId: null, search: "" });
  });
});

describe("AdminDriversPanel", () => {
  it("opens the driver from the overview and offers the admin Blokdan chiqarish with a reason", async () => {
    api.unblockDriver.mockResolvedValue({ v2_eligibility_blocked: true });
    render(<AdminDriversPanel user={staff("admin")} initialSearch="id:120" />);
    const drawer = await screen.findByRole("dialog", { name: "Jasur Sintetik" });
    fireEvent.click(within(drawer).getByRole("button", { name: /Blokdan chiqarish/ }));
    const modal = screen.getByRole("dialog", { name: "Haydovchini blokdan chiqarish" });
    fireEvent.change(within(modal).getByLabelText(/Sabab/), { target: { value: "Hujjatlar tiklandi" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Blokdan chiqarish" }));
    await waitFor(() => expect(api.unblockDriver).toHaveBeenCalledWith(120, { reason: "Hujjatlar tiklandi" }));
    expect(await screen.findByText(/v2 ruxsat bloki hali amal qiladi/)).toBeInTheDocument();
  });

  it("gives the operator only the vehicle correction", async () => {
    render(<AdminDriversPanel user={staff("operator")} initialSearch="id:120" />);
    const drawer = await screen.findByRole("dialog", { name: "Jasur Sintetik" });
    expect(within(drawer).getByRole("button", { name: /Avtomobilni o'zgartirish/ })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Blokdan chiqarish/ })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: /Tasdiqlash/ })).toBeNull();
  });

  it("shows document states and the driver's orders", async () => {
    render(<AdminDriversPanel user={staff("admin")} initialSearch="id:120" />);
    const drawer = await screen.findByRole("dialog", { name: "Jasur Sintetik" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Hujjatlar" }));
    expect(within(drawer).getByText("Sabab: rasm xira")).toBeInTheDocument();
    expect(within(drawer).getAllByText("Yuklanmagan").length).toBe(3);
    fireEvent.click(within(drawer).getByRole("button", { name: "Buyurtmalar" }));
    expect(await within(drawer).findByText("EL-9")).toBeInTheDocument();
    expect(api.getAdminDriverOrders).toHaveBeenCalledWith(120);
  });
});
