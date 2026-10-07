/**
 * Chunk A system and v1 panels: Profil (Q2 commission lock, finance), Bosh sahifa (finance variant, v2 tiles),
 * Mijozlar (reason on block), Bildirishnomalar (chips), Xavfsizlik (QR, staff picker), and the label helpers.
 * SYNTHETIC data only; every API wrapper is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLocale } from "../i18n";
import type { AuthUser } from "../types/auth";

const settings = vi.hoisted(() => ({ getAdminSystemSettings: vi.fn(), updateDriverCommission: vi.fn() }));
const overview = vi.hoisted(() => ({ getAdminOverview: vi.fn(), getV2QueueCounts: vi.fn(), getFinanceMoney: vi.fn() }));
const clients = vi.hoisted(() => ({ getAdminClients: vi.fn(), getAdminClientDetail: vi.fn(), blockAdminClient: vi.fn(), unblockAdminClient: vi.fn() }));
const inbox = vi.hoisted(() => ({ getAdminNotifications: vi.fn(), markAdminNotificationRead: vi.fn(), markAllAdminNotificationsRead: vi.fn() }));
const mfa = vi.hoisted(() => ({
  mfaState: vi.fn(),
  enrollMfa: vi.fn(),
  stepUp: vi.fn(),
  useRecoveryCode: vi.fn(),
  activateStaffMfa: vi.fn(),
  resetStaffMfa: vi.fn(),
}));
const users = vi.hoisted(() => ({ getAdminUsers: vi.fn() }));

vi.mock("../api/admin-settings.api", () => settings);
vi.mock("../api/admin-overview.api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...overview }));
vi.mock("../api/admin-clients.api", () => clients);
vi.mock("../api/admin-notifications.api", () => inbox);
vi.mock("../api/v2/mfa.api", () => mfa);
vi.mock("../api/admin-users.api", () => users);
vi.mock("../api/v2/ops.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  capabilities: vi.fn().mockResolvedValue({ capabilities: ["staff.mfa_approve"], roles: ["super_admin"], driver_eligibility: null }),
}));

import { AdminProfilePanel, canEditCommission } from "./AdminProfilePanel";
import { AdminOverviewPanel } from "./AdminOverviewPanel";
import { AdminClientsPanel } from "./AdminClientsPanel";
import { AdminNotificationsPanel } from "./AdminNotificationsPanel";
import { AdminSecurityPanel } from "./AdminSecurityPanel";
import { adminOrderStatusLabel, adminRoleLabel, adminStatusLabel } from "../utils/adminUserLabels";
import { driverDocumentLabel, getDriverVerificationLabel } from "../utils/driverStatus";
import { canSeeSection } from "./AdminApp";

function staff(role: string): AuthUser {
  return { id: 3, phone: "+998900000003", full_name: "Sintetik Xodim", role: role as AuthUser["role"], status: "active", is_phone_verified: true };
}

beforeEach(() => {
  setLocale("uz");
  for (const group of [settings, overview, clients, inbox, mfa, users]) Object.values(group).forEach((mock) => mock.mockReset());
  settings.getAdminSystemSettings.mockResolvedValue({ driver_commission_percent: 8, driver_commission_rate: 0.08, is_default: false });
});

describe("label helpers", () => {
  it("say roles, statuses and order states in both languages", () => {
    expect(adminRoleLabel("finance")).toBe("Moliya");
    expect(adminRoleLabel("super_admin")).toBe("Super administrator");
    expect(adminStatusLabel("active")).toBe("Faol");
    expect(adminOrderStatusLabel("in_transit")).toBe("Yetkazish jarayonida");
    expect(driverDocumentLabel("car_photo")).toBe("Avtomobil rasmi");
    expect(getDriverVerificationLabel("pending")).toBe("Ko'rib chiqish kutilmoqda");
    setLocale("ru");
    expect(adminRoleLabel("finance")).toBe("Финансы");
    expect(adminStatusLabel("blocked")).toBe("Заблокирован");
    expect(adminOrderStatusLabel("disputed")).toBe("Спорный");
    setLocale("uz");
    expect(adminRoleLabel("mystery_role")).toBe("mystery_role");
  });
});

describe("AdminProfilePanel (Q2)", () => {
  it("only super_admin edits the commission", () => {
    expect(canEditCommission("super_admin")).toBe(true);
    expect(canEditCommission("admin")).toBe(false);
  });

  it("shows the admin a locked field with the Q2 hint and no save button", async () => {
    render(<AdminProfilePanel user={staff("admin")} onUserUpdate={vi.fn()} onLogout={vi.fn()} />);
    const block = await screen.findByTestId("commission-block");
    await waitFor(() => expect(within(block).getByLabelText(/Foiz/)).toHaveValue(8));
    expect(within(block).getByLabelText(/Foiz/)).toBeDisabled();
    expect(within(block).getByText("Faqat yangi buyurtmalarga qo'llanadi.")).toBeInTheDocument();
    expect(within(block).queryByRole("button", { name: /Saqlash/ })).toBeNull();
    expect(screen.queryByText(/OTP/)).toBeNull();
  });

  it("lets super_admin save the percent", async () => {
    settings.updateDriverCommission.mockResolvedValue({ driver_commission_percent: 9 });
    render(<AdminProfilePanel user={staff("super_admin")} onUserUpdate={vi.fn()} onLogout={vi.fn()} />);
    const block = await screen.findByTestId("commission-block");
    await waitFor(() => expect(within(block).getByLabelText(/Foiz/)).toHaveValue(8));
    fireEvent.change(within(block).getByLabelText(/Foiz/), { target: { value: "9" } });
    fireEvent.click(within(block).getByRole("button", { name: /Saqlash/ }));
    await waitFor(() => expect(settings.updateDriverCommission).toHaveBeenCalledWith(9));
  });

  it("does not draw or load the commission for finance", () => {
    render(<AdminProfilePanel user={staff("finance")} onUserUpdate={vi.fn()} onLogout={vi.fn()} />);
    expect(screen.queryByTestId("commission-block")).toBeNull();
    expect(settings.getAdminSystemSettings).not.toHaveBeenCalled();
  });
});

describe("AdminOverviewPanel", () => {
  it("gives finance the note and the money queue only, without reading v1", async () => {
    overview.getV2QueueCounts.mockResolvedValue({ counts: { finance_review: { count: 200, capped: true } }, failed: false });
    overview.getFinanceMoney.mockResolvedValue({ from: "2026-09-05", to: "2026-10-04", tiles: [{ report: "commission_revenue", amountMinor: 1_234_500, count: 7, todayMinor: 50_000 }] });
    const onNavigate = vi.fn();
    render(<AdminOverviewPanel user={staff("finance")} onNavigate={onNavigate} canSee={(section) => canSeeSection("finance", section)} />);
    const tile = await screen.findByTestId("v2-tile-finance_review");
    expect(tile).toHaveTextContent("Moliya ko'rigi");
    expect(tile).toHaveTextContent("200+");
    expect(screen.getByText("Moliyaviy hisobot")).toBeInTheDocument();
    const money = await screen.findByTestId("finance-money");
    expect(money).toHaveTextContent("Balansdan undirilgan komissiya");
    expect(money).toHaveTextContent("12 345 so'm");
    expect(overview.getAdminOverview).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Buyurtmalarni boshqarish/ })).toBeNull();
    fireEvent.click(tile);
    expect(onNavigate).toHaveBeenCalledWith("opsQueues");
  });

  it("renames the today tile to a calculated share, never profit", async () => {
    overview.getV2QueueCounts.mockResolvedValue({ counts: {}, failed: false });
    overview.getAdminOverview.mockResolvedValue({
      orders: [], drivers: [], cities: [], districts: [], tariffs: [], disputes: [], warnings: [],
      finance: {
        pricedOrders: 0, completedOrders: 0, activePricedOrders: 0, totalOrderAmount: 0, systemProfit: 0, driverIncome: 0,
        completedOrderAmount: 0, completedSystemProfit: 0, completedDriverIncome: 0, activeOrderAmount: 0, activeSystemProfit: 0,
        todayOrderAmount: 0, todaySystemProfit: 0, averageOrderAmount: 0, averageSystemProfit: 0,
      },
      stats: {
        totalOrders: 0, publishedOrders: 0, activeDeliveries: 0, deliveredToday: 0, confirmedOrders: 0, pendingDrivers: 0,
        approvedDrivers: 0, openDisputes: 0, activeCities: 0, districtIssues: 0, activeTariffs: 0, missingTariffs: 0,
      },
    });
    render(<AdminOverviewPanel user={staff("admin")} onNavigate={vi.fn()} />);
    expect(await screen.findByText("Bugungi hisoblangan ulush")).toBeInTheDocument();
    expect(screen.queryByText(/foydasi/)).toBeNull();
    expect(screen.getByText("Navbatlar, tekshiruvlar va moliya.")).toBeInTheDocument();
    // v3 dashboard (§2.2-§2.3): accrued, never income
    expect(screen.getByTestId("overview-dashboard")).toBeInTheDocument();
    expect(screen.getByText("mln so'm · hisoblangan, tushum emas")).toBeInTheDocument();
    expect(screen.getByText(/^Hisoblangan tizim ulushi · /)).toBeInTheDocument();
  });
});

describe("AdminClientsPanel", () => {
  it("blocks only with a reason of at least 3 characters and says the status in words", async () => {
    const client = { id: 88, phone: "+998901234567", full_name: null, role: "client", status: "active", is_phone_verified: true, orders_count: 2, active_orders_count: 0, completed_orders_count: 2, cancelled_orders_count: 0 };
    clients.getAdminClients.mockResolvedValue({ items: [client] });
    clients.blockAdminClient.mockResolvedValue({ ...client, status: "blocked" });
    render(<AdminClientsPanel user={staff("admin")} />);
    expect(await screen.findByText("Ism yo'q")).toBeInTheDocument();
    expect(screen.getAllByText("Faol").some((node) => node.tagName === "SPAN")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Bloklash" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Bloklash" });
    fireEvent.change(within(dialog).getByLabelText(/Sabab/), { target: { value: "ab" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/Sabab/), { target: { value: "Spam buyurtmalar" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(clients.blockAdminClient).toHaveBeenCalledWith(88, "Spam buyurtmalar"));
  });

  it("is read-only for the operator", async () => {
    clients.getAdminClients.mockResolvedValue({ items: [{ id: 1, phone: "+998900000000", role: "client", status: "active", is_phone_verified: true, orders_count: 0, active_orders_count: 0, completed_orders_count: 0, cancelled_orders_count: 0 }] });
    render(<AdminClientsPanel user={staff("operator")} />);
    await screen.findByText("+998900000000");
    expect(screen.queryByRole("button", { name: "Bloklash" })).toBeNull();
  });
});

describe("AdminNotificationsPanel", () => {
  it("filters with chips and counts the unread", async () => {
    inbox.getAdminNotifications.mockImplementation(async (params: { is_read?: string }) =>
      params.is_read === "unread"
        ? { items: [{ id: 2, title: "Yangi", is_read: false }], pagination: { page: 1, limit: 50, total: 3, total_pages: 1 } }
        : { items: [{ id: 1, title: "Sintetik xabar", message: "matn", order_id: 5, is_read: true, created_at: "2026-09-26T04:12:00Z" }] });
    render(<AdminNotificationsPanel />);
    expect(await screen.findByText("Sintetik xabar")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "O'qilmagan · 3" })).toBeInTheDocument();
    expect(screen.getByText(/Buyurtma #5/)).toBeInTheDocument();
    expect(screen.queryByText(/Order #|No notifications|Mark/)).toBeNull();
  });
});

describe("AdminSecurityPanel", () => {
  const state = {
    enrolled: true, active: false, pending_activation: true, enforced: false, mode: "audit_only", active_super_admin_count: 2,
    stepped_up_at: null, recovery_codes_remaining: 10, failed_attempts_in_window: 0, max_failed_attempts: 5, step_up_max_age_seconds: 300,
  };

  it("draws the provisioning URI as a QR code and picks the other staff member by name", async () => {
    mfa.mfaState.mockResolvedValue(state);
    mfa.enrollMfa.mockResolvedValue({ secret: "JBSWY3DPSYNTH", provisioning_uri: "otpauth://totp/Elchi:synthetic?secret=JBSWY3DPSYNTH", recovery_codes: ["AAAA1111"] });
    users.getAdminUsers.mockResolvedValue({ items: [{ id: 12, phone: "+998900000012", full_name: "Moliya Sintetik", role: "finance", status: "active", is_phone_verified: true, public_id: "usr_synthfin" }] });
    mfa.activateStaffMfa.mockResolvedValue({ status: "active" });
    render(<AdminSecurityPanel />);
    expect(await screen.findByText("Omil tasdiqlanmagan: boshqa super_admin bitta jonli kodni tasdiqlashi kerak.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Yangi qurilmaga ulash/ }));
    expect(await screen.findByRole("img", { name: "Autentifikator uchun QR kod" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Ism yoki telefon (yoki usr_...)"), { target: { value: "Moliya" } });
    fireEvent.focus(screen.getByPlaceholderText("Ism yoki telefon (yoki usr_...)"));
    fireEvent.click(await screen.findByText("Moliya Sintetik"));
    expect(screen.getByText("usr_synthfin")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Jonli kod"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Faollashtirish" }));
    await waitFor(() => expect(mfa.activateStaffMfa).toHaveBeenCalledWith("usr_synthfin", "123456"));
  });
});
