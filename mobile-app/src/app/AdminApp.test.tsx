/**
 * The admin shell: password sign-in (no OTP), the role matrix (DESIGN-ADMIN-DIFF §2 + AGENTS rules), the grouped
 * sidebar and the header. SYNTHETIC data only; the API wrappers are mocked so the test proves what is called.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../types/api";
import { setLocale } from "../i18n";

const api = vi.hoisted(() => ({
  staffLogin: vi.fn(),
  getAdminMe: vi.fn(),
  listAdminDisputes: vi.fn(),
  searchAdminUsers: vi.fn(),
  searchAdminBookings: vi.fn(),
  searchAdminTrips: vi.fn(),
}));

vi.mock("../api/admin.api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("../api/v2/ops.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  capabilities: vi.fn().mockResolvedValue({ capabilities: ["ops.view"], roles: [], driver_eligibility: null }),
}));
// The panels are other chunks' (or other tests') business; the shell test only needs to know which one mounts.
vi.mock("./AdminOverviewPanel", () => ({ AdminOverviewPanel: () => <div data-testid="panel-overview" /> }));
vi.mock("./AdminOrdersPanel", () => ({ AdminOrdersPanel: () => <div data-testid="panel-orders" /> }));
vi.mock("./AdminDriversPanel", () => ({ AdminDriversPanel: (props: { initialSearch?: string }) => <div data-testid="panel-drivers">{props.initialSearch}</div> }));
vi.mock("./AdminClientsPanel", () => ({ AdminClientsPanel: () => <div data-testid="panel-clients" /> }));
vi.mock("./AdminCitiesPanel", () => ({ AdminCitiesPanel: () => <div data-testid="panel-cities" /> }));
vi.mock("./AdminTariffsPanel", () => ({ AdminTariffsPanel: () => <div data-testid="panel-tariffs" /> }));
vi.mock("./AdminUsersPanel", () => ({ AdminUsersPanel: () => <div data-testid="panel-users" /> }));
vi.mock("./AdminNotificationsPanel", () => ({ AdminNotificationsPanel: () => <div data-testid="panel-notifications" /> }));
vi.mock("./AdminProfilePanel", () => ({ AdminProfilePanel: () => <div data-testid="panel-profile" /> }));
vi.mock("./AdminAuditLogsPanel", () => ({ AdminAuditLogsPanel: () => <div data-testid="panel-audit" /> }));
vi.mock("./AdminSecurityPanel", () => ({ AdminSecurityPanel: () => <div data-testid="panel-security" /> }));
vi.mock("./AdminOpsPanel", () => ({
  AdminDisputesV2Panel: () => <div data-testid="panel-disputesV2" />,
  AdminLegacyOrdersPanel: () => <div data-testid="panel-legacyOrders" />,
  AdminMetricsPanel: () => <div data-testid="panel-metrics" />,
  AdminOpsQueuesPanel: () => <div data-testid="panel-opsQueues" />,
  AdminSupportPanel: () => <div data-testid="panel-support" />,
}));
vi.mock("./AdminPriceBandsPanel", () => ({ AdminPriceBandsPanel: () => <div data-testid="panel-priceBands" /> }));
vi.mock("./AdminPromoPanel", () => ({ AdminPromoPanel: () => <div data-testid="panel-promotions" /> }));
vi.mock("./AdminVehiclesPanel", () => ({ AdminVehiclesPanel: () => <div data-testid="panel-vehicles" /> }));
vi.mock("./AdminFinancePanel", () => ({ AdminFinancePanel: () => <div data-testid="panel-finance" /> }));
vi.mock("./AdminPlatformPanel", () => ({ AdminPlatformPanel: () => <div data-testid="panel-platform" /> }));
vi.mock("./AdminTrustPanel", () => ({ AdminTrustPanel: () => <div data-testid="panel-trustOps" /> }));
vi.mock("./AdminSupportThreadsPanel", () => ({ AdminSupportThreadsPanel: () => <div data-testid="panel-supportThreads" /> }));

import AdminApp, { ALL_SECTIONS, canSeeSection, staffLoginErrorMessage, visibleNavGroups, type Section } from "./AdminApp";

function staff(role: string, overrides: Record<string, unknown> = {}) {
  return { id: 7, phone: "+998900000007", full_name: "Sintetik Xodim", role, status: "active", is_phone_verified: true, ...overrides };
}

function signIn(role: string) {
  const user = staff(role);
  localStorage.setItem("elchi_admin_access_token", "access-synthetic");
  localStorage.setItem("elchi_admin_refresh_token", "refresh-synthetic");
  localStorage.setItem("elchi_admin_user", JSON.stringify(user));
  api.getAdminMe.mockResolvedValue(user);
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "";
  setLocale("uz");
  Object.values(api).forEach((mock) => mock.mockReset());
  api.listAdminDisputes.mockResolvedValue({ items: [] });
});

afterEach(() => {
  setLocale("uz");
});

const visible = (role: string) => ALL_SECTIONS.filter((section) => canSeeSection(role, section));

describe("role matrix (§2: design HIDE and the rules)", () => {
  it("admin and super_admin see every panel", () => {
    expect(visible("admin")).toEqual(ALL_SECTIONS);
    expect(visible("super_admin")).toEqual(ALL_SECTIONS);
    // ADR-0027 added «Yo'nalishlar» (driverDirections) to the market group.
    expect(ALL_SECTIONS).toHaveLength(25);
  });

  it("operator does not see Moliya, Xodimlar or Audit jurnali", () => {
    const hidden = ALL_SECTIONS.filter((section) => !canSeeSection("operator", section));
    expect(hidden.sort()).toEqual(["audit", "finance", "users"]);
  });

  it("finance sees only the money, v2 ops and system panels it can read", () => {
    expect(visible("finance").sort()).toEqual(
      (["overview", "opsQueues", "trustOps", "finance", "promotions", "legacyOrders", "metrics", "security", "notifications", "profile"] as Section[]).sort(),
    );
  });

  it("a marketplace account sees nothing", () => {
    expect(visible("client")).toEqual([]);
    expect(visible("driver")).toEqual([]);
  });

  it("keeps the design's seven groups and order, dropping a group with nothing left", () => {
    expect(visibleNavGroups("admin").map((group) => group.id)).toEqual(["home", "market", "trust", "finance", "catalog", "legacy", "system"]);
    expect(visibleNavGroups("finance").map((group) => group.id)).toEqual(["home", "market", "finance", "legacy", "system"]);
  });
});

describe("staff sign-in", () => {
  it("asks for a login and a password, never for a phone or an OTP", () => {
    render(<AdminApp />);
    expect(screen.getByLabelText("Login")).toBeInTheDocument();
    expect(screen.getByLabelText("Parol")).toHaveAttribute("type", "password");
    expect(screen.queryByText(/OTP/i)).toBeNull();
    expect(screen.queryByText(/Telefon/)).toBeNull();
  });

  it("toggles the password visibility", () => {
    render(<AdminApp />);
    fireEvent.click(screen.getByRole("button", { name: "Parolni ko'rsatish" }));
    expect(screen.getByLabelText("Parol")).toHaveAttribute("type", "text");
  });

  it("says both fields are needed before calling the server", () => {
    render(<AdminApp />);
    fireEvent.click(screen.getByRole("button", { name: "Kirish" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Login va parolni to'liq kiriting");
    expect(api.staffLogin).not.toHaveBeenCalled();
  });

  it("shows one generic sentence for wrong credentials", async () => {
    api.staffLogin.mockRejectedValue(new ApiError(401, { code: "INVALID_CREDENTIALS", message: "Invalid username or password" }));
    render(<AdminApp />);
    fireEvent.change(screen.getByLabelText("Login"), { target: { value: "dev.nobody" } });
    fireEvent.change(screen.getByLabelText("Parol"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Kirish" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Login yoki parol noto'g'ri");
    expect(api.staffLogin).toHaveBeenCalledWith({ username: "dev.nobody", password: "wrong-password" });
  });

  it("maps a validation refusal to the same generic sentence", () => {
    expect(staffLoginErrorMessage(new ApiError(422, { code: "VALIDATION_ERROR", message: "x" }))).toBe("Login yoki parol noto'g'ri");
  });

  it("signs a finance user in and opens the shell with finance's menu", async () => {
    const user = staff("finance", { full_name: "Moliya Sintetik" });
    api.staffLogin.mockResolvedValue({ access_token: "a", refresh_token: "r", token_type: "bearer", user });
    api.getAdminMe.mockResolvedValue(user);
    render(<AdminApp />);
    fireEvent.change(screen.getByLabelText("Login"), { target: { value: "dev.finance" } });
    fireEvent.change(screen.getByLabelText("Parol"), { target: { value: "synthetic-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Kirish" }));
    const nav = await screen.findByRole("navigation");
    expect(within(nav).getByRole("button", { name: "Moliya" })).toBeInTheDocument();
    expect(within(nav).queryByRole("button", { name: "Buyurtmalar (v1)" })).toBeNull();
    expect(within(nav).queryByRole("button", { name: "Xodimlar" })).toBeNull();
    expect(screen.getByTestId("sidebar-role")).toHaveTextContent("Moliya");
    expect(screen.getByTestId("header-identity")).toHaveTextContent("Moliya Sintetik · Moliya");
    expect(localStorage.getItem("elchi_admin_access_token")).toBe("a");
  });

  it("speaks Russian when the reader chose it", () => {
    setLocale("ru");
    render(<AdminApp />);
    expect(screen.getByText("Панель управления")).toBeInTheDocument();
    expect(screen.getByLabelText("Логин")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Войти" })).toBeInTheDocument();
  });
});

describe("shell", () => {
  it("shows the operator's grouped menu without Moliya / Xodimlar / Audit and labels the role in words", async () => {
    signIn("operator");
    render(<AdminApp />);
    const nav = screen.getByRole("navigation");
    for (const group of ["Bozor (v2)", "Ishonch", "Katalog va sozlamalar", "Legacy (v1)", "Tizim"]) {
      expect(within(nav).getByText(group)).toBeInTheDocument();
    }
    expect(within(nav).queryByRole("button", { name: "Moliya" })).toBeNull();
    expect(within(nav).queryByRole("button", { name: "Audit jurnali" })).toBeNull();
    expect(within(nav).getByRole("button", { name: "Buyurtmalar (v1)" })).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-role")).toHaveTextContent("Operator");
    await waitFor(() => expect(api.getAdminMe).toHaveBeenCalled());
  });

  it("does not open a hidden panel from the address bar", () => {
    window.location.hash = "#audit";
    signIn("operator");
    render(<AdminApp />);
    expect(screen.getByTestId("panel-overview")).toBeInTheDocument();
    expect(screen.queryByTestId("panel-audit")).toBeNull();
  });

  it("navigates, and the header refresh remounts the panel", async () => {
    signIn("admin");
    render(<AdminApp />);
    fireEvent.click(within(screen.getByRole("navigation")).getByRole("button", { name: "Nizolar (v1)" }));
    expect(await screen.findByText("Faqat o'qish jadvali. v1 nizoni hal qilish UI'da yo'q.")).toBeInTheDocument();
    expect(api.listAdminDisputes).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getAllByRole("button", { name: /Yangilash/ })[0]);
    await waitFor(() => expect(api.listAdminDisputes).toHaveBeenCalledTimes(2));
  });

  it("signs out from the header", () => {
    signIn("super_admin");
    render(<AdminApp />);
    fireEvent.click(screen.getByRole("button", { name: /Chiqish/ }));
    expect(screen.getByLabelText("Login")).toBeInTheDocument();
    expect(localStorage.getItem("elchi_admin_access_token")).toBeNull();
  });

  it("v1 disputes show status and reason in words and filter the loaded table", async () => {
    signIn("admin");
    api.listAdminDisputes.mockResolvedValue({
      items: [
        { id: 31, order_number: "EL-1", reason: "damaged", status: "open", opened_by: "+998900000001", created_at: "2026-09-25T13:30:00Z" },
        { id: 30, order_number: "EL-2", reason: "delayed", status: "resolved", opened_by: "+998900000002", created_at: "2026-09-12T06:00:00Z" },
      ],
    });
    window.location.hash = "#disputes";
    render(<AdminApp />);
    expect(await screen.findByText("Shikastlangan")).toBeInTheDocument();
    expect(screen.getByText("Ochiq")).toBeInTheDocument();
    expect(screen.getByText("Hal qilingan")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("ID, buyurtma yoki sabab"), { target: { value: "EL-2" } });
    expect(screen.queryByText("Shikastlangan")).toBeNull();
    expect(screen.getByText("Kechikdi")).toBeInTheDocument();
  });

  it("global search opens a found driver in the drivers panel", async () => {
    signIn("admin");
    api.searchAdminUsers.mockResolvedValue([{ id: "usr_synth1", role: "driver", roles: ["driver"], full_name: "Ali Sintetik", phone: "+998901112233", status: "active", created_at: "2026-09-30T10:00:00Z" }]);
    api.searchAdminBookings.mockResolvedValue([]);
    api.searchAdminTrips.mockResolvedValue([]);
    render(<AdminApp />);
    const input = await screen.findByPlaceholderText("Ism, telefon, bron yoki safar kodi");
    fireEvent.change(input, { target: { value: "Ali" } });
    fireEvent.click(await screen.findByText("Ali Sintetik"));
    expect(await screen.findByTestId("panel-drivers")).toHaveTextContent("+998901112233");
  });

  it("global search says when the server has no search yet", async () => {
    signIn("admin");
    const missing = new ApiError(404, { code: "NOT_FOUND", message: "Not Found" });
    api.searchAdminUsers.mockRejectedValue(missing);
    api.searchAdminBookings.mockRejectedValue(missing);
    api.searchAdminTrips.mockRejectedValue(missing);
    render(<AdminApp />);
    fireEvent.change(await screen.findByPlaceholderText("Ism, telefon, bron yoki safar kodi"), { target: { value: "bkg_7q2x" } });
    expect(await screen.findByText("Qidiruv serverda hali mavjud emas")).toBeInTheDocument();
  });
});
