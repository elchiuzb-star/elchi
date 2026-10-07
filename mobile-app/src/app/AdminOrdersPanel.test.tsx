/**
 * v1 orders (§16): Q10 gating (operator reads, admin+ acts), the translated table and drawer, and the reason that
 * the status / cancel modals require. SYNTHETIC data only.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLocale } from "../i18n";
import type { AdminOrder } from "../types/admin-order";
import type { AuthUser } from "../types/auth";

const api = vi.hoisted(() => ({
  getAdminOrders: vi.fn(),
  getAdminOrderDetail: vi.fn(),
  getEligibleDriversForOrder: vi.fn(),
  manualUpdateOrderStatus: vi.fn(),
  manualAssignDriver: vi.fn(),
  cancelAdminOrder: vi.fn(),
}));

vi.mock("../api/admin-orders.api", () => api);
vi.mock("../api/cities.api", () => ({ getCities: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/districts.api", () => ({ getDistricts: vi.fn().mockResolvedValue([]) }));
vi.mock("../components/maps/ReadOnlyOrderMap", () => ({ ReadOnlyOrderMap: () => <div data-testid="map" /> }));

import { AdminOrdersPanel, canMutateOrders } from "./AdminOrdersPanel";

function order(overrides: Partial<AdminOrder> = {}): AdminOrder {
  return {
    id: 20931,
    order_number: "EL-20931",
    status: "bidding",
    from_city: { id: 1, name_uz: "Toshkent" },
    to_city: { id: 2, name_uz: "Samarqand" },
    client: { id: 5, phone: "+998901234567", full_name: "Sintetik Mijoz" },
    sender_phone: "+998901234567",
    bids_count: 3,
    final_price: 120000,
    suggested_price: 110000,
    payment_method: "cash",
    payment_status: "unpaid",
    pickup_lat: 41.3,
    pickup_lng: 69.2,
    pickup_address: "Chilonzor 9",
    created_at: "2026-09-26T04:12:00Z",
    updated_at: "2026-09-26T05:00:00Z",
    ...overrides,
  } as AdminOrder;
}

function staff(role: string): AuthUser {
  return { id: 1, phone: "+998900000001", full_name: "Xodim", role: role as AuthUser["role"], status: "active", is_phone_verified: true };
}

beforeEach(() => {
  setLocale("uz");
  Object.values(api).forEach((mock) => mock.mockReset());
  api.getAdminOrders.mockResolvedValue({ items: [order()], pagination: { page: 1, limit: 20, total: 1564, total_pages: 79 } });
  api.getAdminOrderDetail.mockResolvedValue(order());
  api.getEligibleDriversForOrder.mockResolvedValue([]);
});

describe("canMutateOrders (Q10)", () => {
  it("is admin and super_admin only", () => {
    expect(canMutateOrders("operator")).toBe(false);
    expect(canMutateOrders("finance")).toBe(false);
    expect(canMutateOrders("admin")).toBe(true);
    expect(canMutateOrders("super_admin")).toBe(true);
  });
});

describe("AdminOrdersPanel", () => {
  it("renders the design copy in Uzbek, with no English left", async () => {
    render(<AdminOrdersPanel user={staff("admin")} />);
    expect(await screen.findByText("EL-20931")).toBeInTheDocument();
    expect(screen.queryByText(/\(v1\)/)).toBeNull();
    expect(screen.getByText("Sahifa 1 / 79 · jami 1564")).toBeInTheDocument();
    expect(screen.getByText("3 ta")).toBeInTheDocument();
    expect(screen.getByText("Biriktirilmagan")).toBeInTheDocument();
    expect(screen.getByText("jo'natuvchi: +998901234567")).toBeInTheDocument();
    for (const english of ["Orders", "Manage", "Not assigned", "bids", "Created at", "No orders found"]) {
      expect(screen.queryByText(new RegExp(`^${english}$`))).toBeNull();
    }
  });

  it("gives the operator a read-only drawer (no force status / assign / cancel)", async () => {
    render(<AdminOrdersPanel user={staff("operator")} />);
    fireEvent.click(await screen.findByRole("button", { name: /Boshqarish/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByTestId("orders-readonly")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Holatni o'zgartirish" })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: "Buyurtmani bekor qilish" })).toBeNull();
    expect(api.getEligibleDriversForOrder).not.toHaveBeenCalled();
  });

  it("lets an admin change the status only with a reason", async () => {
    api.manualUpdateOrderStatus.mockResolvedValue(order({ status: "accepted" }));
    render(<AdminOrdersPanel user={staff("admin")} />);
    fireEvent.click(await screen.findByRole("button", { name: /Boshqarish/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Olib ketish va yetkazish nuqtalari")).toBeInTheDocument();
    expect(within(drawer).getByText("Chilonzor 9 · 41.3, 69.2")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Holatni o'zgartirish" }));
    const save = screen.getByRole("button", { name: "Saqlash" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Sabab kiritish shart"), { target: { value: "Operator tekshirdi" } });
    fireEvent.click(save);
    expect(api.manualUpdateOrderStatus).toHaveBeenCalledWith(20931, { status: "published", reason: "Operator tekshirdi" });
  });

  it("asks before cancelling, with Ortga as the way back", async () => {
    render(<AdminOrdersPanel user={staff("super_admin")} />);
    fireEvent.click(await screen.findByRole("button", { name: /Boshqarish/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Buyurtmani bekor qilish" }));
    expect(screen.getByText("Bu amal mijoz va haydovchiga ta'sir qilishi mumkin. Davom etilsinmi?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ortga" }));
    expect(api.cancelAdminOrder).not.toHaveBeenCalled();
  });

  it("speaks Russian", async () => {
    setLocale("ru");
    render(<AdminOrdersPanel user={staff("admin")} />);
    expect(await screen.findByText("Не назначен")).toBeInTheDocument();
    expect(screen.getByText("Не назначен")).toBeInTheDocument();
    setLocale("uz");
  });
});
