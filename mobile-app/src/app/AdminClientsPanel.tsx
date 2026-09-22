import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Eye, Lock, RefreshCw, Search, Unlock, UserRound, UsersRound } from "./ui/icons";

import { blockAdminClient, getAdminClientDetail, getAdminClients, unblockAdminClient } from "../api/admin-clients.api";
import type { AdminClient, AdminClientFilters } from "../types/admin-client";
import type { AuthUser } from "../types/auth";
import { formatAdminDate } from "../utils/date";

function Badge({ children, tone }: { children: string; tone: "green" | "red" | "amber" | "slate" }) {
  const classes = {
    green: "border-success/25 bg-success/12 text-success",
    red: "border-destructive/25 bg-destructive/10 text-destructive",
    amber: "border-warning/28 bg-warning/14 text-warning",
    slate: "border-border bg-slate-50 text-secondary-foreground",
  };
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${classes[tone]}`}>{children}</span>;
}

function statusTone(status: string): "green" | "red" | "amber" | "slate" {
  if (status === "active") return "green";
  if (status === "blocked") return "red";
  if (status === "inactive") return "amber";
  return "slate";
}

function Card({ label, value, icon }: { label: string; value: number; icon: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase text-muted-foreground">{label}</p>
        <span className="text-slate-400">{icon}</span>
      </div>
      <p className="mt-2 text-2xl font-bold text-foreground">{value}</p>
    </div>
  );
}

export function AdminClientsPanel({ user }: { user: AuthUser }) {
  const canMutate = user.role === "admin" || user.role === "super_admin";
  const [items, setItems] = useState<AdminClient[]>([]);
  const [filters, setFilters] = useState<AdminClientFilters>({ page: 1, limit: 20 });
  const [searchInput, setSearchInput] = useState("");
  const [detail, setDetail] = useState<AdminClient | null>(null);
  const [confirm, setConfirm] = useState<{ client: AdminClient; action: "block" | "unblock" } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => setFilters((current) => ({ ...current, search: searchInput, page: 1 })), 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const data = await getAdminClients(filters);
      setItems(data.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mijozlarni yuklab bo'lmadi");
      setItems([]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, [filters]);

  async function openDetail(client: AdminClient) {
    setError(null);
    try {
      setDetail(await getAdminClientDetail(client.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mijoz tafsilotlarini yuklab bo'lmadi");
    }
  }

  async function runClientStatus(client: AdminClient, action: "block" | "unblock") {
    setBusy(true);
    setError(null);
    try {
      const reason = action === "block" ? "Admin panel orqali mijoz bloklandi" : "Admin panel orqali mijoz blokdan chiqarildi";
      const updated = action === "block" ? await blockAdminClient(client.id, reason) : await unblockAdminClient(client.id, reason);
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setDetail((current) => (current?.id === updated.id ? updated : current));
      setConfirm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mijoz holatini o'zgartirib bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  const summary = useMemo(() => ({
    total: items.length,
    active: items.filter((item) => item.status === "active").length,
    blocked: items.filter((item) => item.status === "blocked").length,
    verified: items.filter((item) => item.is_phone_verified).length,
    withOrders: items.filter((item) => item.orders_count > 0).length,
    activeOrders: items.reduce((sum, item) => sum + item.active_orders_count, 0),
  }), [items]);

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">Mijozlar mobil ilova orqali ro'yxatdan o'tadi. Admin va super admin mijoz akkauntini bloklashi yoki blokdan chiqarishi mumkin.</p>
          {!canMutate && <p className="mt-1 text-xs font-semibold text-warning">Operator uchun faqat ko'rish rejimi.</p>}
        </div>
        <button
          onClick={() => void load()}
          disabled={busy}
          className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={16} /> Yangilash
        </button>
      </div>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">{error}</div>}

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Card label="Yuklangan mijozlar" value={summary.total} icon={<UsersRound size={18} />} />
        <Card label="Faol" value={summary.active} icon={<UserRound size={18} />} />
        <Card label="Bloklangan" value={summary.blocked} icon={<UserRound size={18} />} />
        <Card label="Telefon tasdiqlangan" value={summary.verified} icon={<UserRound size={18} />} />
        <Card label="Buyurtmasi bor" value={summary.withOrders} icon={<UsersRound size={18} />} />
        <Card label="Faol buyurtmalar" value={summary.activeOrders} icon={<UsersRound size={18} />} />
      </div>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 xl:grid-cols-[1.5fr_1fr_1fr]">
          <label className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Telefon yoki ism bo'yicha qidirish"
              className="h-10 w-full rounded-[10px] border border-border pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            />
          </label>
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
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Mijoz</th>
                <th>Telefon</th>
                <th>Holat</th>
                <th>Tasdiqlangan</th>
                <th>Buyurtmalar</th>
                <th>Faol buyurtmalar</th>
                <th>So'nggi buyurtma</th>
                <th>Yaratilgan</th>
                <th className="px-4">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {items.map((client) => (
                <tr key={client.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-foreground">{client.full_name || "Ism yo'q"}</div>
                    <div className="text-xs text-muted-foreground">ID {client.id}</div>
                  </td>
                  <td>{client.phone}</td>
                  <td><Badge tone={statusTone(client.status)}>{client.status}</Badge></td>
                  <td>{client.is_phone_verified ? "Ha" : "Yo'q"}</td>
                  <td>{client.orders_count}</td>
                  <td>{client.active_orders_count}</td>
                  <td>{formatAdminDate(client.last_order_at)}</td>
                  <td>{formatAdminDate(client.created_at)}</td>
                  <td className="px-4">
                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => void openDetail(client)} className="el-press rounded-[10px] border border-border p-2 text-secondary-foreground hover:bg-card" title="Tafsilotlarni ko'rish"><Eye size={16} /></button>
                      {canMutate && (client.status === "blocked" ? (
                        <button onClick={() => setConfirm({ client, action: "unblock" })} className="el-press rounded-[10px] border border-success/25 p-2 text-success hover:bg-success/12" title="Blokdan chiqarish"><Unlock size={16} /></button>
                      ) : (
                        <button onClick={() => setConfirm({ client, action: "block" })} className="el-press rounded-[10px] border border-destructive/25 p-2 text-destructive hover:bg-destructive/10" title="Bloklash"><Lock size={16} /></button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-muted-foreground">Mijozlar topilmadi</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {detail && (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-border bg-card shadow-xl">
          <div className="flex items-center justify-between border-b border-muted px-5 py-4">
            <h2 className="text-lg font-bold">Mijoz tafsilotlari</h2>
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
                <p><span className="text-muted-foreground">Holat:</span> {detail.status}</p>
                <p><span className="text-muted-foreground">Telefon tasdiqlangan:</span> {detail.is_phone_verified ? "Ha" : "Yo'q"}</p>
                <p><span className="text-muted-foreground">Jami buyurtmalar:</span> {detail.orders_count}</p>
                <p><span className="text-muted-foreground">Faol buyurtmalar:</span> {detail.active_orders_count}</p>
                <p><span className="text-muted-foreground">Yakunlangan buyurtmalar:</span> {detail.completed_orders_count}</p>
                <p><span className="text-muted-foreground">Bekor qilingan buyurtmalar:</span> {detail.cancelled_orders_count}</p>
                <p><span className="text-muted-foreground">So'nggi kirish:</span> {formatAdminDate(detail.last_login_at)}</p>
                <p><span className="text-muted-foreground">So'nggi buyurtma:</span> {formatAdminDate(detail.last_order_at)}</p>
                <p><span className="text-muted-foreground">Yaratilgan:</span> {formatAdminDate(detail.created_at)}</p>
              </div>
            </div>
            {canMutate && (
              <button
                onClick={() => setConfirm({ client: detail, action: detail.status === "blocked" ? "unblock" : "block" })}
                className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-4 text-sm font-semibold ${
                  detail.status === "blocked"
                    ? "border-success/25 bg-success/12 text-success hover:bg-success/25"
                    : "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25"
                }`}
              >
                {detail.status === "blocked" ? <Unlock size={16} /> : <Lock size={16} />}
                {detail.status === "blocked" ? "Blokdan chiqarish" : "Mijozni bloklash"}
              </button>
            )}
            <div className="rounded-[12px] border border-border p-4 text-sm text-secondary-foreground">
              Profil mijoz ilovasida yangilanadi, buyurtma amallari esa Buyurtmalar bo'limida bajariladi. Bloklangan mijoz tizimga kira olmaydi.
            </div>
          </div>
        </div>
      )}

      {confirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
          <section className="w-full max-w-md rounded-[12px] bg-card shadow-xl">
            <div className="border-b border-muted px-5 py-4">
              <h2 className="text-lg font-bold">{confirm.action === "block" ? "Mijozni bloklash" : "Mijozni blokdan chiqarish"}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{confirm.client.full_name || confirm.client.phone}</p>
            </div>
            <div className="grid gap-4 p-5">
              <p className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">
                {confirm.action === "block"
                  ? "Bloklangan mijoz tizimga kira olmaydi va yangi buyurtma yarata olmaydi. Mavjud buyurtmalar avtomatik bekor qilinmaydi."
                  : "Mijoz blokdan chiqarilgach tizimga qayta kira oladi."}
              </p>
              <div className="flex justify-end gap-2">
                <button onClick={() => setConfirm(null)} className="el-press h-10 rounded-[10px] border border-border px-4 text-sm font-semibold text-secondary-foreground hover:bg-slate-50">Bekor qilish</button>
                <button
                  disabled={busy}
                  onClick={() => void runClientStatus(confirm.client, confirm.action)}
                  className={`el-press inline-flex h-10 items-center gap-2 rounded-[10px] px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 ${confirm.action === "block" ? "bg-destructive hover:bg-destructive" : "bg-success hover:brightness-95"}`}
                >
                  {confirm.action === "block" ? <Lock size={16} /> : <Unlock size={16} />}
                  {confirm.action === "block" ? "Bloklash" : "Blokdan chiqarish"}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
