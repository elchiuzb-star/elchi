/**
 * Haydovchilar (§17): operator may only correct the vehicle (Q94), admin+ gets approve/reject/block/unblock, the
 * Buyurtmalar tab reads `/admin/drivers/{id}/orders`, documents carry their state in words, and the driver's v2 car
 * is verified on the same tab as the documents (the list marks drivers whose car waits). SYNTHETIC data.
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

const vehiclesApi = vi.hoisted(() => ({ adminVehicles: vi.fn(), adminVerifyVehicle: vi.fn(), adminSetDriverEligibility: vi.fn() }));
vi.mock("../api/v2/admin-vehicles.api", () => vehiclesApi);
const caps = vi.hoisted(() => ({ capabilities: vi.fn() }));
vi.mock("../api/v2/ops.api", async (importOriginal) => ({ ...(await importOriginal<object>()), capabilities: caps.capabilities }));
const ADMIN_CAPS = { roles: ["admin"], capabilities: ["ops.view", "ops.driver_eligibility_manage"], driver_eligibility: null };

const PENDING_CAR = {
  id: "veh_synthetic1",
  plate_number: "01A452KA",
  plate_masked: "01A***KA",
  make_model: "Cobalt",
  color: "oq",
  seat_capacity: 4,
  baggage_capacity_ml: null,
  cargo_max_weight_g: null,
  cargo_max_volume_ml: null,
  document_file_ids: [],
  verification_status: "pending",
  version: 2,
  created_at: "2026-09-24T08:00:00Z",
  verification_reason: null,
  verified_at: null,
  updated_at: "2026-09-24T08:00:00Z",
  owner: {
    user_id: "usr_synthetic120",
    is_driver: true,
    account_active: true,
    driver_verification_status: "approved",
    eligible: true,
    reasons: [],
    blocked_reason: null,
    eligibility_version: 1,
    active_trip_count: 0,
  },
};

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
    user_public_id: "usr_synthetic120",
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
  Object.values(vehiclesApi).forEach((mock) => mock.mockReset());
  vehiclesApi.adminVehicles.mockResolvedValue({ items: [], nextCursor: null });
  caps.capabilities.mockReset();
  caps.capabilities.mockResolvedValue(ADMIN_CAPS);
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
    // v3 §15.3: the correction lives on the vehicle block of «Hujjatlar va avtomobil».
    fireEvent.click(within(drawer).getByRole("button", { name: "Hujjatlar va avtomobil" }));
    expect(await within(drawer).findByRole("button", { name: /Avtomobilni o'zgartirish/ })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Blokdan chiqarish/ })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: /Tasdiqlash/ })).toBeNull();
  });

  it("shows document states and the driver's orders", async () => {
    render(<AdminDriversPanel user={staff("admin")} initialSearch="id:120" />);
    const drawer = await screen.findByRole("dialog", { name: "Jasur Sintetik" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Hujjatlar va avtomobil" }));
    expect(within(drawer).getByText("Sabab: rasm xira")).toBeInTheDocument();
    expect(within(drawer).getAllByText("Yuklanmagan").length).toBe(3);
    fireEvent.click(within(drawer).getByRole("button", { name: "Buyurtmalar" }));
    expect(await within(drawer).findByText("EL-9")).toBeInTheDocument();
    expect(api.getAdminDriverOrders).toHaveBeenCalledWith(120);
  });

  it("verifies the car on the documents tab, asking only for this driver's vehicles", async () => {
    vehiclesApi.adminVehicles.mockResolvedValue({ items: [PENDING_CAR], nextCursor: null });
    vehiclesApi.adminVerifyVehicle.mockResolvedValue({});
    render(<AdminDriversPanel user={staff("admin")} initialSearch="id:120" />);
    const drawer = await screen.findByRole("dialog", { name: "Jasur Sintetik" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Hujjatlar va avtomobil" }));
    expect(await within(drawer).findByText(/Cobalt · oq · 01A452KA/)).toBeInTheDocument();
    expect(vehiclesApi.adminVehicles).toHaveBeenCalledWith({ owner_user_id: "usr_synthetic120", limit: 50 });
    // The passport card and the car live on the same tab.
    expect(within(drawer).getByText("Pasport")).toBeInTheDocument();
    const card = within(drawer).getByTestId("vehicle-card");
    fireEvent.click(within(card).getByRole("button", { name: "Tasdiqlash" }));
    fireEvent.click(within(card).getByRole("button", { name: "Ha, tasdiqlayman" }));
    await waitFor(() =>
      expect(vehiclesApi.adminVerifyVehicle).toHaveBeenCalledWith(
        "veh_synthetic1",
        { decision: "approve", expected_version: 2, reason: null },
        expect.any(String),
      ),
    );
  });

  it("marks drivers whose car waits for a decision and finds them by plate", async () => {
    vehiclesApi.adminVehicles.mockResolvedValue({ items: [PENDING_CAR], nextCursor: null });
    render(<AdminDriversPanel user={staff("admin")} />);
    expect(await screen.findByText("Avtomobil tasdig'ini kutayotgan haydovchilar: 1")).toBeInTheDocument();
    expect(vehiclesApi.adminVehicles).toHaveBeenCalledWith({ status: "pending", limit: 50 });
    expect(await screen.findByText("Avtomobil kutmoqda")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Cobalt · 01A452KA/ }));
    expect((screen.getByDisplayValue("01A452KA") as HTMLInputElement).value).toBe("01A452KA");
  });

  it("asks an operator's browser nothing about cars and explains why on the card", async () => {
    caps.capabilities.mockResolvedValue({ roles: ["operator"], capabilities: ["ops.view"], driver_eligibility: null });
    render(<AdminDriversPanel user={staff("operator")} initialSearch="id:120" />);
    const drawer = await screen.findByRole("dialog", { name: "Jasur Sintetik" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Hujjatlar va avtomobil" }));
    expect(await within(drawer).findByText(/faqat admin va undan yuqori/)).toBeInTheDocument();
    expect(vehiclesApi.adminVehicles).not.toHaveBeenCalled();
    expect(screen.queryByText(/Avtomobil tasdig'ini kutayotgan/)).toBeNull();
  });
});
