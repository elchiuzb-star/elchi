/**
 * Xodimlar (§22, contract §1.3/§2): finance in the list and the role options, staff creation with a username and
 * an initial password, the credentials reset, and super_admin-only changes. SYNTHETIC data only.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLocale } from "../i18n";
import { ApiError } from "../types/api";
import type { AdminStaffUser } from "../types/admin-user";
import type { AuthUser } from "../types/auth";

const users = vi.hoisted(() => ({
  getAdminUsers: vi.fn(),
  getAdminUserDetail: vi.fn(),
  createStaffUser: vi.fn(),
  updateStaffUser: vi.fn(),
  blockStaffUser: vi.fn(),
  unblockStaffUser: vi.fn(),
}));
const admin = vi.hoisted(() => ({ setStaffCredentials: vi.fn() }));

vi.mock("../api/admin-users.api", () => users);
vi.mock("../api/admin.api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...admin }));

import { AdminUsersPanel, staffCredentialProblem } from "./AdminUsersPanel";

function staffRow(overrides: Partial<AdminStaffUser> = {}): AdminStaffUser {
  return {
    id: 12,
    phone: "+998900000012",
    full_name: "Moliya Sintetik",
    role: "finance",
    status: "active",
    is_phone_verified: true,
    username: "fin.synth",
    public_id: "usr_synthfin",
    has_password: true,
    last_login_at: "2026-09-26T04:10:00Z",
    ...overrides,
  };
}

function me(role: string): AuthUser {
  return { id: 1, phone: "+998900000001", full_name: "Super", role: role as AuthUser["role"], status: "active", is_phone_verified: true };
}

beforeEach(() => {
  setLocale("uz");
  Object.values(users).forEach((mock) => mock.mockReset());
  admin.setStaffCredentials.mockReset();
  users.getAdminUsers.mockResolvedValue({
    items: [staffRow(), staffRow({ id: 13, role: "operator", full_name: "Operator Sintetik", username: "op.synth" })],
  });
});

describe("staffCredentialProblem", () => {
  it("follows the server policy", () => {
    expect(staffCredentialProblem("", "", { requireBoth: true })).toBe("admin.staff.credBoth");
    expect(staffCredentialProblem("ab", "long-enough", { requireBoth: true })).toBe("admin.staff.usernameRule");
    expect(staffCredentialProblem("Ali Valiyev", "long-enough", { requireBoth: true })).toBe("admin.staff.usernameRule");
    expect(staffCredentialProblem("ali.op", "short", { requireBoth: true })).toBe("admin.staff.passwordRule");
    expect(staffCredentialProblem("ali.op", "x".repeat(73), { requireBoth: true })).toBe("admin.staff.passwordRule");
    expect(staffCredentialProblem("ali.op", "long-enough", { requireBoth: true })).toBeNull();
    expect(staffCredentialProblem("", "", { requireBoth: false })).toBe("admin.staff.credOne");
    expect(staffCredentialProblem("", "new-password-1", { requireBoth: false })).toBeNull();
  });
});

describe("AdminUsersPanel", () => {
  it("counts finance staff and shows the role in words", async () => {
    render(<AdminUsersPanel user={me("admin")} />);
    expect(await screen.findByText("Moliya Sintetik")).toBeInTheDocument();
    expect(screen.getByText("@fin.synth")).toBeInTheDocument();
    // admin reads, never changes
    expect(screen.getByText("Faqat ko'rish rejimi. Xodimlarni o'zgartirish uchun super administrator roli kerak.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Xodim yaratish/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Tahrirlash" })).toBeNull();
  });

  it("creates a finance user with a username and a password", async () => {
    users.createStaffUser.mockResolvedValue(staffRow({ id: 14 }));
    render(<AdminUsersPanel user={me("super_admin")} />);
    await screen.findByText("Moliya Sintetik");
    fireEvent.click(screen.getByRole("button", { name: /Xodim yaratish/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Telefon"), { target: { value: "+998901234567" } });
    fireEvent.change(within(dialog).getByLabelText("To'liq ism"), { target: { value: "Yangi Moliya" } });
    fireEvent.change(within(dialog).getByLabelText("Rol"), { target: { value: "finance" } });
    fireEvent.change(within(dialog).getByLabelText(/^Login/), { target: { value: "New.Fin" } });
    fireEvent.change(within(dialog).getByLabelText(/^Parol/, { selector: "input" }), { target: { value: "short" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Yaratish/ }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Parol: 8–72 belgi.");
    expect(users.createStaffUser).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Parol/, { selector: "input" }), { target: { value: "Synthetic-Pass-1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Yaratish/ }));
    expect(users.createStaffUser).toHaveBeenCalledWith({
      phone: "+998901234567",
      role: "finance",
      full_name: "Yangi Moliya",
      username: "new.fin",
      password: "Synthetic-Pass-1",
    });
    expect(await screen.findByText("Xodim yaratildi. U shu login va parol bilan darhol kira oladi.")).toBeInTheDocument();
  });

  it("says a taken username in words", async () => {
    users.createStaffUser.mockRejectedValue(new ApiError(409, { code: "USERNAME_TAKEN", message: "taken" }));
    render(<AdminUsersPanel user={me("super_admin")} />);
    await screen.findByText("Moliya Sintetik");
    fireEvent.click(screen.getByRole("button", { name: /Xodim yaratish/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Login/), { target: { value: "fin.synth" } });
    fireEvent.change(within(dialog).getByLabelText(/^Parol/, { selector: "input" }), { target: { value: "Synthetic-Pass-1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Yaratish/ }));
    expect(await screen.findByText("Bu login band. Boshqasini tanlang.")).toBeInTheDocument();
  });

  it("resets only the password through the credentials endpoint", async () => {
    admin.setStaffCredentials.mockResolvedValue(staffRow());
    render(<AdminUsersPanel user={me("super_admin")} />);
    await screen.findByText("Moliya Sintetik");
    fireEvent.click(screen.getAllByRole("button", { name: "Kirish ma'lumotlari" })[0]);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Yangi parol/, { selector: "input" }), { target: { value: "Fresh-Pass-2026" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Saqlash/ }));
    expect(admin.setStaffCredentials).toHaveBeenCalledWith(12, { password: "Fresh-Pass-2026" });
  });
});
