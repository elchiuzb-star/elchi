/**
 * Xodimlar (DESIGN-ADMIN-DIFF §22). Staff accounts only - client and driver accounts are managed in their own
 * flows (Q3). Reading the list is operator/admin/super_admin on the server; the shell hides the panel from the
 * operator (design) and from finance (server 403). Every change is super_admin.
 *
 * A staff member signs in with a username and a password (`/auth/staff-login`), so creating one here asks for
 * both (ADMIN-BACKEND-CONTRACT §2): an account created without them could not log in. There is no OTP invite.
 */
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Eye, EyeOff, KeyRound, Lock, Pencil, Plus, RefreshCw, Search, Shield, Unlock, UserRound } from "./ui/icons";

import { setStaffCredentials, STAFF_PASSWORD_MAX, STAFF_PASSWORD_MIN, STAFF_USERNAME_MAX, STAFF_USERNAME_MIN } from "../api/admin.api";
import {
  blockStaffUser,
  createStaffUser,
  getAdminUserDetail,
  getAdminUsers,
  unblockStaffUser,
  updateStaffUser,
} from "../api/admin-users.api";
import type { MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type {
  AdminStaffUser,
  AdminStaffUserCreatePayload,
  AdminStaffUserFilters,
  AdminStaffUserUpdatePayload,
  AssignableStaffRole,
} from "../types/admin-user";
import type { AuthUser } from "../types/auth";
import { adminRoleBadgeClass, adminRoleLabel, adminStatusLabel, adminUserErrorMessage, adminUserStatusClass, yesNo } from "../utils/adminUserLabels";
import { formatDateTime } from "../utils/v2Format";

const emptyCreate: AdminStaffUserCreatePayload = { phone: "+998", role: "operator", full_name: "", username: "", password: "" };

const ASSIGNABLE_ROLES: AssignableStaffRole[] = ["operator", "admin", "finance"];

/** Same policy as the server (`StaffLogin`, contract §2): lowercase `a-z 0-9 . _ -`, 3-64 characters. */
const USERNAME_PATTERN = /^[a-z0-9._-]+$/;

/** The first problem with a username/password pair, as a dictionary key; `null` when both are acceptable. */
export function staffCredentialProblem(username: string, password: string, options: { requireBoth: boolean }): MessageKey | null {
  const name = username.trim().toLowerCase();
  if (options.requireBoth && (!name || !password)) return "admin.staff.credBoth";
  if (!options.requireBoth && !name && !password) return "admin.staff.credOne";
  if (name && (name.length < STAFF_USERNAME_MIN || name.length > STAFF_USERNAME_MAX || !USERNAME_PATTERN.test(name))) return "admin.staff.usernameRule";
  if (password) {
    const bytes = new TextEncoder().encode(password).length;
    if (password.length < STAFF_PASSWORD_MIN || password.length > STAFF_PASSWORD_MAX || bytes > STAFF_PASSWORD_MAX) return "admin.staff.passwordRule";
  }
  return null;
}

function Badge({ children, className }: { children: string; className: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${className}`}>{children}</span>;
}

function Button(props: { children: ReactNode; onClick?: () => void; disabled?: boolean; tone?: "primary" | "danger" | "neutral" }) {
  const tone = props.tone ?? "primary";
  const className =
    tone === "danger"
      ? "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25"
      : tone === "neutral"
        ? "border-border bg-card text-secondary-foreground hover:bg-slate-50"
        : "border-primary bg-primary text-primary-foreground hover:bg-primary";
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function TextField(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  autoComplete?: string;
  hint?: string;
  trailing?: ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <span className="relative">
        <input
          value={props.value}
          type={props.type ?? "text"}
          placeholder={props.placeholder}
          autoComplete={props.autoComplete}
          onChange={(event) => props.onChange(event.target.value)}
          className={`h-10 w-full rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100 ${props.trailing ? "pr-11" : ""}`}
        />
        {props.trailing}
      </span>
      {props.hint && <span className="text-xs font-normal text-muted-foreground">{props.hint}</span>}
    </label>
  );
}

function PasswordField(props: { label: string; value: string; onChange: (value: string) => void; hint?: string }) {
  const t = useT();
  const [show, setShow] = useState(false);
  return (
    <TextField
      label={props.label}
      value={props.value}
      onChange={props.onChange}
      type={show ? "text" : "password"}
      autoComplete="new-password"
      hint={props.hint}
      trailing={(
        <button
          type="button"
          onClick={() => setShow((value) => !value)}
          aria-label={t(show ? "admin.login.hidePassword" : "admin.login.showPassword")}
          className="absolute right-1.5 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-[8px] text-muted-foreground hover:bg-muted"
        >
          {show ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      )}
    />
  );
}

function SelectField<T extends string>(props: { label: string; value: T; onChange: (value: T) => void; options: Array<{ value: T; label: string }> }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <select
        value={props.value}
        onChange={(event) => props.onChange(event.target.value as T)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
      >
        {props.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function Modal(props: { title: string; children: ReactNode; onClose: () => void }) {
  const t = useT();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div role="dialog" aria-modal="true" aria-label={props.title} className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-[12px] bg-card shadow-xl">
        <div className="flex items-center justify-between border-b border-muted px-5 py-4">
          <h2 className="text-lg font-bold">{props.title}</h2>
          <button type="button" onClick={props.onClose} className="el-press rounded-[10px] px-2 py-1 text-sm font-semibold text-muted-foreground hover:bg-muted">{t("common.close")}</button>
        </div>
        <div className="p-5">{props.children}</div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <p><span className="text-muted-foreground">{label}:</span> {children}</p>;
}

export function AdminUsersPanel({ user, initialSearch }: { user: AuthUser; initialSearch?: string }) {
  const t = useT();
  const isSuperAdmin = user.role === "super_admin";
  const [items, setItems] = useState<AdminStaffUser[]>([]);
  const [filters, setFilters] = useState<AdminStaffUserFilters>({ limit: 20, page: 1, search: initialSearch || undefined });
  const [searchInput, setSearchInput] = useState(initialSearch ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createProblem, setCreateProblem] = useState<string | null>(null);
  const [editUser, setEditUser] = useState<AdminStaffUser | null>(null);
  const [credUser, setCredUser] = useState<AdminStaffUser | null>(null);
  const [credForm, setCredForm] = useState({ username: "", password: "" });
  const [credProblem, setCredProblem] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminStaffUser | null>(null);
  const [statusTarget, setStatusTarget] = useState<{ user: AdminStaffUser; action: "block" | "unblock" } | null>(null);
  const [reason, setReason] = useState("");
  const [createForm, setCreateForm] = useState<AdminStaffUserCreatePayload>(emptyCreate);
  const [editForm, setEditForm] = useState<AdminStaffUserUpdatePayload>({});

  const roleOptions = ASSIGNABLE_ROLES.map((role) => ({ value: role, label: adminRoleLabel(role) }));

  useEffect(() => {
    const handle = window.setTimeout(() => setFilters((current) => (
      (current.search ?? "") === searchInput ? current : { ...current, search: searchInput, page: 1 }
    )), 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const data = await getAdminUsers(filters);
      setItems(data.items ?? []);
    } catch (err) {
      setError(adminUserErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const summary = useMemo(() => ({
    total: items.length,
    operators: items.filter((item) => item.role === "operator").length,
    admins: items.filter((item) => item.role === "admin").length,
    superAdmins: items.filter((item) => item.role === "super_admin").length,
    finance: items.filter((item) => item.role === "finance").length,
    blocked: items.filter((item) => item.status === "blocked").length,
  }), [items]);

  async function run(action: () => Promise<unknown>, done?: MessageKey) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
      if (done) setMessage(t(done));
      await load();
    } catch (err) {
      setError(adminUserErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function openDetail(staffUser: AdminStaffUser) {
    setError(null);
    try {
      setDetail(await getAdminUserDetail(staffUser.id));
    } catch (err) {
      setError(adminUserErrorMessage(err));
    }
  }

  function beginEdit(staffUser: AdminStaffUser) {
    setEditUser(staffUser);
    setEditForm({
      full_name: staffUser.full_name ?? "",
      role: staffUser.role === "super_admin" ? undefined : staffUser.role,
      status: staffUser.status === "blocked" || staffUser.status === "inactive" ? staffUser.status : "active",
    });
  }

  function beginCredentials(staffUser: AdminStaffUser) {
    setCredUser(staffUser);
    setCredForm({ username: staffUser.username ?? "", password: "" });
    setCredProblem(null);
  }

  function submitCreate() {
    const problem = staffCredentialProblem(createForm.username ?? "", createForm.password ?? "", { requireBoth: true });
    if (problem) {
      setCreateProblem(t(problem));
      return;
    }
    setCreateProblem(null);
    void run(async () => {
      await createStaffUser({
        ...createForm,
        full_name: createForm.full_name?.trim() || null,
        username: createForm.username?.trim().toLowerCase(),
      });
      setCreateForm(emptyCreate);
      setCreateOpen(false);
    }, "admin.staff.created");
  }

  function submitCredentials() {
    if (!credUser) return;
    const username = credForm.username.trim().toLowerCase();
    const changedName = username && username !== (credUser.username ?? "") ? username : "";
    const problem = staffCredentialProblem(changedName, credForm.password, { requireBoth: false });
    if (problem) {
      setCredProblem(t(problem));
      return;
    }
    setCredProblem(null);
    void run(async () => {
      await setStaffCredentials(credUser.id, {
        ...(changedName ? { username: changedName } : {}),
        ...(credForm.password ? { password: credForm.password } : {}),
      });
      setCredUser(null);
    }, "admin.staff.credSaved");
  }

  // super_admin manages operator/admin/finance and its own sign-in; another super_admin is out of reach (contract §2).
  const canSetCredentials = (target: AdminStaffUser) => isSuperAdmin && (target.role !== "super_admin" || target.id === user.id);

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.users")}</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t("admin.staff.subtitle")}</p>
          {!isSuperAdmin && <p className="mt-1 text-xs font-semibold text-warning">{t("admin.staff.readOnly")}</p>}
        </div>
        <div className="flex gap-2">
          <Button tone="neutral" disabled={busy} onClick={() => void load()}><RefreshCw size={16} /> {t("support.refresh")}</Button>
          {isSuperAdmin && <Button onClick={() => { setCreateOpen(true); setCreateProblem(null); }}><Plus size={16} /> {t("admin.staff.create")}</Button>}
        </div>
      </div>

      {error && <div role="alert" className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">{error}</div>}
      {message && <div className="rounded-[12px] border border-success/25 bg-success/12 px-4 py-3 text-sm font-semibold text-success">{message}</div>}

      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        {([
          ["common.total", summary.total, ""],
          ["admin.staff.operators", summary.operators, ""],
          ["admin.staff.admins", summary.admins, ""],
          ["admin.staff.superAdmins", summary.superAdmins, ""],
          ["admin.role.finance", summary.finance, ""],
          ["admin.common.blocked", summary.blocked, "text-destructive"],
        ] as Array<[MessageKey, number, string]>).map(([label, value, tone]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <p className="text-xs font-semibold text-muted-foreground">{t(label)}</p>
            <p className={`mt-2 text-2xl font-bold ${tone || "text-foreground"}`}>{value}</p>
          </div>
        ))}
      </div>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[1.5fr_1fr_1fr_1fr_1fr_1fr]">
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("location.search")}
            <span className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t("admin.staff.searchPh")}
                className="h-10 w-full rounded-[10px] border border-border bg-card pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
              />
            </span>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.staff.role")}
            <select value={filters.role ?? ""} onChange={(event) => setFilters({ ...filters, role: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm">
              <option value="">{t("admin.common.all")}</option>
              {(["operator", "admin", "super_admin", "finance"] as const).map((role) => <option key={role} value={role}>{adminRoleLabel(role)}</option>)}
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.common.status")}
            <select value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm">
              <option value="">{t("admin.common.all")}</option>
              <option value="active">{t("admin.common.active")}</option>
              <option value="blocked">{t("admin.common.blocked")}</option>
              <option value="inactive">{t("admin.common.inactive")}</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.clients.phoneCheck")}
            <select value={filters.is_phone_verified ?? ""} onChange={(event) => setFilters({ ...filters, is_phone_verified: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm">
              <option value="">{t("admin.common.all")}</option>
              <option value="verified">{t("admin.common.verified")}</option>
              <option value="unverified">{t("admin.common.unverified")}</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.staff.startDate")}
            <input
              type="date"
              value={filters.created_from ?? ""}
              onChange={(event) => setFilters({ ...filters, created_from: event.target.value || undefined, page: 1 })}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm"
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.staff.endDate")}
            <input
              type="date"
              value={filters.created_to ?? ""}
              onChange={(event) => setFilters({ ...filters, created_to: event.target.value || undefined, page: 1 })}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm"
            />
          </label>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
              <tr>
                {([
                  "admin.staff.colUser",
                  "admin.common.phone",
                  "admin.staff.role",
                  "admin.common.status",
                  "admin.staff.colPhoneVerified",
                  "admin.staff.colLastLogin",
                ] as MessageKey[]).map((key) => <th key={key} className="px-4 py-3">{t(key)}</th>)}
                <th className="px-4 py-3"><span className="sr-only">{t("admin.common.viewEdit")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {items.map((staffUser) => (
                <tr key={staffUser.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-foreground">{staffUser.full_name || t("admin.clients.noName")}</div>
                    <div className="text-xs text-muted-foreground">{staffUser.username ? `@${staffUser.username}` : `ID ${staffUser.id}`}</div>
                  </td>
                  <td className="px-4 py-3">{staffUser.phone}</td>
                  <td className="px-4 py-3"><Badge className={adminRoleBadgeClass(staffUser.role)}>{adminRoleLabel(staffUser.role)}</Badge></td>
                  <td className="px-4 py-3"><Badge className={adminUserStatusClass(staffUser.status)}>{adminStatusLabel(staffUser.status)}</Badge></td>
                  <td className="px-4 py-3">{yesNo(staffUser.is_phone_verified)}</td>
                  <td className="px-4 py-3">{formatDateTime(staffUser.last_login_at)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-semibold">
                    <button type="button" onClick={() => void openDetail(staffUser)} className="el-press text-primary hover:underline">{t("admin.common.view")}</button>
                    {isSuperAdmin && staffUser.role !== "super_admin" && (
                      <>
                        <span className="px-1.5 text-muted-foreground">·</span>
                        <button type="button" onClick={() => beginEdit(staffUser)} className="el-press text-primary hover:underline">{t("admin.common.edit")}</button>
                        <span className="px-1.5 text-muted-foreground">·</span>
                        {staffUser.status === "blocked" ? (
                          <button type="button" onClick={() => { setStatusTarget({ user: staffUser, action: "unblock" }); setReason(""); }} className="el-press text-success hover:underline">{t("blockReport.unblock")}</button>
                        ) : (
                          <button type="button" onClick={() => { setStatusTarget({ user: staffUser, action: "block" }); setReason(""); }} className="el-press text-destructive hover:underline">{t("blockReport.block")}</button>
                        )}
                      </>
                    )}
                    {canSetCredentials(staffUser) && (
                      <>
                        <span className="px-1.5 text-muted-foreground">·</span>
                        <button type="button" onClick={() => beginCredentials(staffUser)} className="el-press text-primary hover:underline">{t("admin.staff.credentials")}</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={7} className="px-4 py-10 text-center text-muted-foreground">{busy ? t("common.loading") : t("admin.staff.empty")}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {createOpen && (
        <Modal title={t("admin.staff.create")} onClose={() => setCreateOpen(false)}>
          <div className="grid gap-4">
            <TextField label={t("admin.common.phone")} value={createForm.phone} onChange={(phone) => setCreateForm({ ...createForm, phone })} autoComplete="off" />
            <TextField label={t("admin.staff.fullName")} value={createForm.full_name ?? ""} onChange={(full_name) => setCreateForm({ ...createForm, full_name })} autoComplete="off" />
            <SelectField label={t("admin.staff.role")} value={createForm.role} onChange={(role) => setCreateForm({ ...createForm, role })} options={roleOptions} />
            <TextField label={t("admin.login.username")} value={createForm.username ?? ""} onChange={(username) => setCreateForm({ ...createForm, username })} autoComplete="off" hint={t("admin.staff.usernameRule")} />
            <PasswordField label={t("admin.login.password")} value={createForm.password ?? ""} onChange={(password) => setCreateForm({ ...createForm, password })} hint={t("admin.staff.passwordRule")} />
            {createProblem && <p role="alert" className="rounded-[10px] bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{createProblem}</p>}
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setCreateOpen(false)}>{t("common.cancel")}</Button>
              <Button disabled={busy} onClick={submitCreate}><Plus size={16} /> {t("admin.staff.createCta")}</Button>
            </div>
          </div>
        </Modal>
      )}

      {editUser && (
        <Modal title={t("admin.staff.editTitle")} onClose={() => setEditUser(null)}>
          <div className="grid gap-4">
            <TextField label={t("admin.staff.fullName")} value={editForm.full_name ?? ""} onChange={(full_name) => setEditForm({ ...editForm, full_name })} />
            {editForm.role && (
              <SelectField label={t("admin.staff.role")} value={editForm.role} onChange={(role) => setEditForm({ ...editForm, role })} options={roleOptions} />
            )}
            <SelectField
              label={t("admin.common.status")}
              value={(editForm.status ?? "active") as "active" | "blocked" | "inactive"}
              onChange={(status) => setEditForm({ ...editForm, status })}
              options={[
                { value: "active", label: t("admin.common.active") },
                { value: "blocked", label: t("admin.common.blocked") },
                { value: "inactive", label: t("admin.common.inactive") },
              ]}
            />
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setEditUser(null)}>{t("common.cancel")}</Button>
              <Button disabled={busy} onClick={() => void run(async () => { await updateStaffUser(editUser.id, editForm); setEditUser(null); })}><Pencil size={16} /> {t("common.save")}</Button>
            </div>
          </div>
        </Modal>
      )}

      {credUser && (
        <Modal title={t("admin.staff.credTitle")} onClose={() => setCredUser(null)}>
          <div className="grid gap-4">
            <p className="text-sm text-secondary-foreground">{credUser.full_name || credUser.phone} · {adminRoleLabel(credUser.role)}</p>
            <TextField label={t("admin.login.username")} value={credForm.username} onChange={(username) => setCredForm({ ...credForm, username })} autoComplete="off" hint={t("admin.staff.usernameRule")} />
            <PasswordField label={t("admin.staff.newPassword")} value={credForm.password} onChange={(password) => setCredForm({ ...credForm, password })} hint={t("admin.staff.passwordRule")} />
            <p className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-xs font-medium text-warning">{t("admin.staff.credHint")}</p>
            {credProblem && <p role="alert" className="rounded-[10px] bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{credProblem}</p>}
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setCredUser(null)}>{t("common.cancel")}</Button>
              <Button disabled={busy} onClick={submitCredentials}><KeyRound size={16} /> {t("common.save")}</Button>
            </div>
          </div>
        </Modal>
      )}

      {statusTarget && (
        <Modal title={t(statusTarget.action === "block" ? "admin.staff.blockTitle" : "admin.staff.unblockTitle")} onClose={() => setStatusTarget(null)}>
          <div className="grid gap-4">
            <p className="text-sm text-secondary-foreground">{statusTarget.user.phone} · {adminRoleLabel(statusTarget.user.role)}</p>
            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              {t("admin.common.reasonMin3")} *
              <textarea value={reason} rows={3} onChange={(event) => setReason(event.target.value)} className="min-h-[84px] rounded-[10px] border border-border bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100" />
            </label>
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setStatusTarget(null)}>{t("common.cancel")}</Button>
              <Button
                tone={statusTarget.action === "block" ? "danger" : "primary"}
                disabled={busy || reason.trim().length < 3}
                onClick={() => void run(async () => {
                  if (statusTarget.action === "block") await blockStaffUser(statusTarget.user.id, reason.trim());
                  else await unblockStaffUser(statusTarget.user.id, reason.trim());
                  setStatusTarget(null);
                })}
              >
                {statusTarget.action === "block" ? <Lock size={16} /> : <Unlock size={16} />}
                {t(statusTarget.action === "block" ? "blockReport.block" : "blockReport.unblock")}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {detail && (
        <div role="dialog" aria-modal="true" aria-label={t("admin.staff.detailTitle")} className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-border bg-card shadow-xl">
          <div className="flex items-center justify-between border-b border-muted px-5 py-4">
            <h2 className="text-lg font-bold">{t("admin.staff.detailTitle")}</h2>
            <button type="button" onClick={() => setDetail(null)} className="el-press rounded-[10px] px-2 py-1 text-sm font-semibold text-muted-foreground hover:bg-muted">{t("common.close")}</button>
          </div>
          <div className="grid gap-4 p-5">
            <div className="rounded-[12px] border border-border p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-primary"><UserRound size={20} /></div>
                <div>
                  <div className="font-bold">{detail.full_name || t("admin.clients.noName")}</div>
                  <div className="text-sm text-muted-foreground">{detail.phone}</div>
                </div>
              </div>
              <div className="mt-4 grid gap-2 text-sm">
                <Row label={t("admin.staff.role")}>{adminRoleLabel(detail.role)}</Row>
                <Row label={t("admin.common.status")}>{adminStatusLabel(detail.status)}</Row>
                <Row label={t("admin.login.username")}>{detail.username || "-"}</Row>
                <Row label={t("admin.staff.hasPassword")}>{detail.has_password === undefined ? "-" : yesNo(detail.has_password)}</Row>
                {detail.public_id && <Row label={t("admin.common.id")}><span className="font-mono text-xs">{detail.public_id}</span></Row>}
                <Row label={t("admin.staff.colPhoneVerified")}>{yesNo(detail.is_phone_verified)}</Row>
                <Row label={t("admin.common.created")}>{formatDateTime(detail.created_at)}</Row>
                <Row label={t("admin.staff.colLastLogin")}>{formatDateTime(detail.last_login_at)}</Row>
              </div>
            </div>
            <div className="rounded-[12px] border border-border p-4">
              <div className="flex items-center gap-2 font-bold"><Shield size={17} /> {t("admin.staff.permissionsTitle")}</div>
              <p className="mt-2 text-sm text-secondary-foreground">{t("admin.staff.permissionsText")}</p>
            </div>
            <div className="rounded-[12px] border border-border p-4 text-sm text-secondary-foreground">{t("admin.staff.auditHint")}</div>
          </div>
        </div>
      )}
    </div>
  );
}
