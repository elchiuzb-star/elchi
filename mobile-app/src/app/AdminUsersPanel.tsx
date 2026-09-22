import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Eye, Lock, Pencil, Plus, RefreshCw, Search, Shield, Unlock, UserRound } from "./ui/icons";

import {
  blockStaffUser,
  createStaffUser,
  getAdminUserDetail,
  getAdminUsers,
  unblockStaffUser,
  updateStaffUser,
} from "../api/admin-users.api";
import type {
  AdminStaffUser,
  AdminStaffUserCreatePayload,
  AdminStaffUserFilters,
  AdminStaffUserUpdatePayload,
} from "../types/admin-user";
import type { AuthUser } from "../types/auth";
import { adminRoleLabel, adminStatusLabel, adminUserErrorMessage, adminUserStatusClass } from "../utils/adminUserLabels";
import { formatAdminDate } from "../utils/date";

const emptyCreate: AdminStaffUserCreatePayload = { phone: "+998", role: "operator", full_name: "" };

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
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function TextField(props: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <input
        value={props.value}
        type={props.type ?? "text"}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
      />
    </label>
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
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-lg rounded-[12px] bg-card shadow-xl">
        <div className="flex items-center justify-between border-b border-muted px-5 py-4">
          <h2 className="text-lg font-bold">{props.title}</h2>
          <button onClick={props.onClose} className="el-press rounded-[10px] px-2 py-1 text-sm font-semibold text-muted-foreground hover:bg-muted">Yopish</button>
        </div>
        <div className="p-5">{props.children}</div>
      </div>
    </div>
  );
}

export function AdminUsersPanel({ user }: { user: AuthUser }) {
  const isSuperAdmin = user.role === "super_admin";
  const [items, setItems] = useState<AdminStaffUser[]>([]);
  const [filters, setFilters] = useState<AdminStaffUserFilters>({ limit: 20, page: 1 });
  const [searchInput, setSearchInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editUser, setEditUser] = useState<AdminStaffUser | null>(null);
  const [detail, setDetail] = useState<AdminStaffUser | null>(null);
  const [statusTarget, setStatusTarget] = useState<{ user: AdminStaffUser; action: "block" | "unblock" } | null>(null);
  const [reason, setReason] = useState("");
  const [createForm, setCreateForm] = useState<AdminStaffUserCreatePayload>(emptyCreate);
  const [editForm, setEditForm] = useState<AdminStaffUserUpdatePayload>({});

  useEffect(() => {
    const handle = window.setTimeout(() => setFilters((current) => ({ ...current, search: searchInput, page: 1 })), 300);
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
  }, [filters]);

  const summary = useMemo(() => ({
    total: items.length,
    operators: items.filter((item) => item.role === "operator").length,
    admins: items.filter((item) => item.role === "admin").length,
    superAdmins: items.filter((item) => item.role === "super_admin").length,
    active: items.filter((item) => item.status === "active").length,
    blocked: items.filter((item) => item.status === "blocked").length,
  }), [items]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
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
      role: staffUser.role === "operator" || staffUser.role === "admin" ? staffUser.role : undefined,
      status: staffUser.status === "blocked" || staffUser.status === "inactive" ? staffUser.status : "active",
    });
  }

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">Faqat xodimlar kirishini boshqarish. Mijoz va haydovchi akkauntlari o'z oqimlarida boshqariladi.</p>
          {!isSuperAdmin && <p className="mt-1 text-xs font-semibold text-warning">Faqat ko'rish rejimi. Xodimlarni o'zgartirish uchun super administrator roli kerak.</p>}
        </div>
        <div className="flex gap-2">
          <Button tone="neutral" disabled={busy} onClick={() => void load()}><RefreshCw size={16} /> Yangilash</Button>
          {isSuperAdmin && <Button onClick={() => setCreateOpen(true)}><Plus size={16} /> Xodim yaratish</Button>}
        </div>
      </div>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">{error}</div>}

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[
          ["Jami", summary.total],
          ["Operatorlar", summary.operators],
          ["Administratorlar", summary.admins],
          ["Super administratorlar", summary.superAdmins],
          ["Faol", summary.active],
          ["Bloklangan", summary.blocked],
        ].map(([label, value]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase text-muted-foreground">{label}</p>
            <p className="mt-2 text-2xl font-bold text-foreground">{value}</p>
          </div>
        ))}
      </div>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 xl:grid-cols-[1.5fr_1fr_1fr_1fr_1fr_1fr]">
          <label className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Telefon yoki ism bo'yicha qidirish"
              className="h-10 w-full rounded-[10px] border border-border pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            />
          </label>
          <select value={filters.role ?? ""} onChange={(event) => setFilters({ ...filters, role: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border px-3 text-sm">
            <option value="">Barcha rollar</option>
            <option value="operator">Operator</option>
            <option value="admin">Admin</option>
            <option value="super_admin">Super administrator</option>
          </select>
          <select value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border px-3 text-sm">
            <option value="">Barcha holatlar</option>
            <option value="active">Faol</option>
            <option value="blocked">Bloklangan</option>
            <option value="inactive">Nofaol</option>
          </select>
          <select value={filters.is_phone_verified ?? ""} onChange={(event) => setFilters({ ...filters, is_phone_verified: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border px-3 text-sm">
            <option value="">Telefon tasdig'i</option>
            <option value="verified">Tasdiqlangan</option>
            <option value="unverified">Tasdiqlanmagan</option>
          </select>
          <input
            type="date"
            value={filters.created_from ?? ""}
            onChange={(event) => setFilters({ ...filters, created_from: event.target.value || undefined, page: 1 })}
            className="h-10 rounded-[10px] border border-border px-3 text-sm"
            aria-label="Boshlanish sanasi"
          />
          <input
            type="date"
            value={filters.created_to ?? ""}
            onChange={(event) => setFilters({ ...filters, created_to: event.target.value || undefined, page: 1 })}
            className="h-10 rounded-[10px] border border-border px-3 text-sm"
            aria-label="Tugash sanasi"
          />
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Foydalanuvchi</th>
                <th>Telefon</th>
                <th>Rol</th>
                <th>Holat</th>
                <th>Telefon tasdiqlangan</th>
                <th>Yaratilgan</th>
                <th>So'nggi kirish</th>
                <th className="px-4">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {items.map((staffUser) => (
                <tr key={staffUser.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-foreground">{staffUser.full_name || "Ism yo'q"}</div>
                    <div className="text-xs text-muted-foreground">ID {staffUser.id}</div>
                  </td>
                  <td>{staffUser.phone}</td>
                  <td>{adminRoleLabel(staffUser.role)}</td>
                  <td><Badge className={adminUserStatusClass(staffUser.status)}>{adminStatusLabel(staffUser.status)}</Badge></td>
                  <td>{staffUser.is_phone_verified ? "Ha" : "Yo'q"}</td>
                  <td>{formatAdminDate(staffUser.created_at)}</td>
                  <td>{formatAdminDate(staffUser.last_login_at)}</td>
                  <td className="px-4">
                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => void openDetail(staffUser)} className="el-press rounded-[10px] border border-border p-2 text-secondary-foreground hover:bg-card" title="Tafsilotlarni ko'rish"><Eye size={16} /></button>
                      {isSuperAdmin && (
                        <>
                          <button onClick={() => beginEdit(staffUser)} className="el-press rounded-[10px] border border-border p-2 text-secondary-foreground hover:bg-card" title="Xodimni tahrirlash"><Pencil size={16} /></button>
                          {staffUser.status === "blocked" ? (
                            <button onClick={() => { setStatusTarget({ user: staffUser, action: "unblock" }); setReason(""); }} className="el-press rounded-[10px] border border-success/25 p-2 text-success hover:bg-success/12" title="Blokdan chiqarish"><Unlock size={16} /></button>
                          ) : (
                            <button onClick={() => { setStatusTarget({ user: staffUser, action: "block" }); setReason(""); }} className="el-press rounded-[10px] border border-destructive/25 p-2 text-destructive hover:bg-destructive/10" title="Bloklash"><Lock size={16} /></button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-muted-foreground">Xodimlar topilmadi</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {createOpen && (
        <Modal title="Xodim yaratish" onClose={() => setCreateOpen(false)}>
          <div className="grid gap-4">
            <TextField label="Telefon" value={createForm.phone} onChange={(phone) => setCreateForm({ ...createForm, phone })} />
            <TextField label="To'liq ism" value={createForm.full_name ?? ""} onChange={(full_name) => setCreateForm({ ...createForm, full_name })} />
            <SelectField label="Rol" value={createForm.role} onChange={(role) => setCreateForm({ ...createForm, role })} options={[{ value: "operator", label: "Operator" }, { value: "admin", label: "Admin" }]} />
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setCreateOpen(false)}>Bekor qilish</Button>
              <Button disabled={busy} onClick={() => void run(async () => { await createStaffUser(createForm); setCreateForm(emptyCreate); setCreateOpen(false); })}><Plus size={16} /> Yaratish</Button>
            </div>
          </div>
        </Modal>
      )}

      {editUser && (
        <Modal title="Xodimni tahrirlash" onClose={() => setEditUser(null)}>
          <div className="grid gap-4">
            <TextField label="To'liq ism" value={editForm.full_name ?? ""} onChange={(full_name) => setEditForm({ ...editForm, full_name })} />
            <SelectField
              label="Rol"
              value={(editForm.role ?? "operator") as "operator" | "admin"}
              onChange={(role) => setEditForm({ ...editForm, role })}
              options={[{ value: "operator", label: "Operator" }, { value: "admin", label: "Admin" }]}
            />
            <SelectField
              label="Holat"
              value={(editForm.status ?? "active") as "active" | "blocked" | "inactive"}
              onChange={(status) => setEditForm({ ...editForm, status })}
              options={[{ value: "active", label: "Faol" }, { value: "blocked", label: "Bloklangan" }, { value: "inactive", label: "Nofaol" }]}
            />
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setEditUser(null)}>Bekor qilish</Button>
              <Button disabled={busy} onClick={() => void run(async () => { await updateStaffUser(editUser.id, editForm); setEditUser(null); })}><Pencil size={16} /> Saqlash</Button>
            </div>
          </div>
        </Modal>
      )}

      {statusTarget && (
        <Modal title={statusTarget.action === "block" ? "Xodimni bloklash" : "Xodimni blokdan chiqarish"} onClose={() => setStatusTarget(null)}>
          <div className="grid gap-4">
            <p className="text-sm text-secondary-foreground">{statusTarget.user.phone} · {adminRoleLabel(statusTarget.user.role)}</p>
            <TextField label="Sabab" value={reason} onChange={setReason} placeholder="Sabab kiritish shart" />
            <div className="flex justify-end gap-2">
              <Button tone="neutral" onClick={() => setStatusTarget(null)}>Bekor qilish</Button>
              <Button
                tone={statusTarget.action === "block" ? "danger" : "primary"}
                disabled={busy || reason.trim().length < 3}
                onClick={() => void run(async () => {
                  if (statusTarget.action === "block") await blockStaffUser(statusTarget.user.id, reason);
                  else await unblockStaffUser(statusTarget.user.id, reason);
                  setStatusTarget(null);
                })}
              >
                {statusTarget.action === "block" ? <Lock size={16} /> : <Unlock size={16} />}
                {statusTarget.action === "block" ? "Bloklash" : "Blokdan chiqarish"}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {detail && (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-border bg-card shadow-xl">
          <div className="flex items-center justify-between border-b border-muted px-5 py-4">
            <h2 className="text-lg font-bold">Xodim tafsilotlari</h2>
            <button onClick={() => setDetail(null)} className="el-press rounded-[10px] px-2 py-1 text-sm font-semibold text-muted-foreground hover:bg-muted">Yopish</button>
          </div>
          <div className="grid gap-4 p-5">
            <div className="rounded-[12px] border border-border p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-primary"><UserRound size={20} /></div>
                <div>
                  <div className="font-bold">{detail.full_name || "Ism yo'q"}</div>
                  <div className="text-sm text-muted-foreground">{detail.phone}</div>
                </div>
              </div>
              <div className="mt-4 grid gap-2 text-sm">
                <p><span className="text-muted-foreground">Rol:</span> {adminRoleLabel(detail.role)}</p>
                <p><span className="text-muted-foreground">Holat:</span> {adminStatusLabel(detail.status)}</p>
                <p><span className="text-muted-foreground">Telefon tasdiqlangan:</span> {detail.is_phone_verified ? "Ha" : "Yo'q"}</p>
                <p><span className="text-muted-foreground">Yaratilgan:</span> {formatAdminDate(detail.created_at)}</p>
                <p><span className="text-muted-foreground">So'nggi kirish:</span> {formatAdminDate(detail.last_login_at)}</p>
              </div>
            </div>
            <div className="rounded-[12px] border border-border p-4">
              <div className="flex items-center gap-2 font-bold"><Shield size={17} /> Rol va ruxsatlar</div>
              <p className="mt-2 text-sm text-secondary-foreground">Ruxsatlar backendda rol orqali boshqariladi. Super administratorlar xodimlarni boshqaradi; administrator va operatorlar biriktirilgan admin modullarida ishlaydi.</p>
            </div>
            <div className="rounded-[12px] border border-border p-4 text-sm text-secondary-foreground">Sessiyalar ko'rinishi kelajakdagi backend endpointi uchun ajratilgan.</div>
            <div className="rounded-[12px] border border-border p-4 text-sm text-secondary-foreground">Audit izi Audit jurnali sahifasida mavjud.</div>
          </div>
        </div>
      )}
    </div>
  );
}
