import { useEffect, useMemo, useState } from "react";
import { Eye, RefreshCw, Search, X } from "lucide-react";

import { listAdminAuditLogs, type AdminRecord } from "../api/admin.api";
import type { AuthRole, AuthUser } from "../types/auth";
import { formatAdminDate } from "../utils/date";

type Filters = {
  search?: string;
  actor_role?: AuthRole | "system" | "";
  entity_type?: string;
  action?: string;
  page: number;
  limit: number;
};

function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") {
    const item = value as AdminRecord;
    return String(item.full_name ?? item.phone ?? item.role ?? item.id ?? "-");
  }
  return String(value);
}

function actorLabel(row: AdminRecord): string {
  const actor = row.actor as AdminRecord | null | undefined;
  const role = text(row.actor_role);
  if (!actor) return role;
  return [text(actor.full_name), text(actor.phone), role].filter((item) => item !== "-").join(" / ") || role;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-56 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

export function AdminAuditLogsPanel({ user }: { user: AuthUser }) {
  const [rows, setRows] = useState<AdminRecord[]>([]);
  const [filters, setFilters] = useState<Filters>({ page: 1, limit: 100 });
  const [draftSearch, setDraftSearch] = useState("");
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminRecord | null>(null);
  const canView = user.role === "admin" || user.role === "super_admin";

  async function load(nextFilters = filters) {
    if (!canView) return;
    setBusy(true);
    setError(null);
    try {
      const response = await listAdminAuditLogs(nextFilters);
      setRows(response.items ?? []);
      setTotal(response.pagination?.total ?? response.items.length);
      setTotalPages(response.pagination?.total_pages ?? 1);
    } catch (err) {
      setRows([]);
      setError(err instanceof Error ? err.message : "Audit loglarni yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, [filters, canView]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((filters.search ?? "") !== draftSearch) setFilters((current) => ({ ...current, search: draftSearch, page: 1 }));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draftSearch]);

  const summary = useMemo(() => {
    const roles = new Set(rows.map((row) => text(row.actor_role)).filter((item) => item !== "-"));
    return { loaded: rows.length, roles: roles.size, total };
  }, [rows, total]);

  if (!canView) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-800">
        Audit jurnali administrator va super administrator rollari uchun mavjud.
      </div>
    );
  }

  return (
    <div className="grid min-w-0 gap-5">
      <section className="grid gap-3 md:grid-cols-3">
        {[
          ["Jami audit yozuvlari", summary.total],
          ["Yuklangan yozuvlar", summary.loaded],
          ["Sahifadagi rollar", summary.roles],
        ].map(([label, value]) => (
          <div key={label as string} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase text-slate-500">{label}</p>
            <p className="mt-2 text-2xl font-bold text-slate-950">{value}</p>
          </div>
        ))}
      </section>

      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">{error}</div>}

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 xl:grid-cols-[1.5fr_1fr_1fr_1fr_auto]">
          <label className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={draftSearch}
              onChange={(event) => setDraftSearch(event.target.value)}
              placeholder="Amal, obyekt, sabab, telefon yoki ism"
              className="h-10 w-full rounded-md border border-slate-200 pl-9 pr-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>
          <select
            value={filters.actor_role ?? ""}
            onChange={(event) => setFilters({
              ...filters,
              actor_role: (event.target.value || undefined) as Filters["actor_role"],
              page: 1,
            })}
            className="h-10 rounded-md border border-slate-200 px-3 text-sm"
          >
            <option value="">Barcha rollar</option>
            {["client", "driver", "operator", "admin", "super_admin", "system"].map((role) => <option key={role} value={role}>{role}</option>)}
          </select>
          <input
            value={filters.entity_type ?? ""}
            onChange={(event) => setFilters({ ...filters, entity_type: event.target.value || undefined, page: 1 })}
            placeholder="Obyekt turi"
            className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-500"
          />
          <input
            value={filters.action ?? ""}
            onChange={(event) => setFilters({ ...filters, action: event.target.value || undefined, page: 1 })}
            placeholder="Amal"
            className="h-10 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-500"
          />
          <button onClick={() => void load()} disabled={busy} className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            <RefreshCw size={16} /> Yangilash
          </button>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1160px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                {["ID", "Bajaruvchi", "Rol", "Amal", "Obyekt", "Sabab", "IP", "Yaratilgan", "Amallar"].map((label) => (
                  <th key={label} className="px-4 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {busy && !rows.length ? Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={9} className="px-4 py-3"><div className="h-8 animate-pulse rounded bg-slate-100" /></td></tr>
              )) : rows.length ? rows.map((row) => (
                <tr key={String(row.id)} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-semibold text-slate-700">#{text(row.id)}</td>
                  <td className="px-4 py-3">{actorLabel(row)}</td>
                  <td className="px-4 py-3">{text(row.actor_role)}</td>
                  <td className="px-4 py-3 font-semibold text-slate-950">{text(row.action)}</td>
                  <td className="px-4 py-3">{text(row.entity_type)} #{text(row.entity_id)}</td>
                  <td className="px-4 py-3">{text(row.reason)}</td>
                  <td className="px-4 py-3">{text(row.ip_address)}</td>
                  <td className="px-4 py-3">{formatAdminDate(String(row.created_at ?? ""))}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => setDetail(row)} className="rounded-md border border-slate-200 p-2 text-slate-600 hover:bg-white" title="Tafsilotlarni ko'rish"><Eye size={16} /></button>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-slate-500">Audit yozuvlari topilmadi</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
          <span>Sahifa {filters.page} / {totalPages || 1} · jami {total}</span>
          <div className="flex gap-2">
            <button disabled={busy || filters.page <= 1} onClick={() => setFilters({ ...filters, page: Math.max(1, filters.page - 1) })} className="h-9 rounded-md border border-slate-200 px-3 font-semibold disabled:opacity-50">Oldingi</button>
            <button disabled={busy || filters.page >= (totalPages || 1)} onClick={() => setFilters({ ...filters, page: filters.page + 1 })} className="h-9 rounded-md border border-slate-200 px-3 font-semibold disabled:opacity-50">Keyingi</button>
          </div>
        </footer>
      </section>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
          <section className="w-full max-w-3xl rounded-lg bg-white shadow-xl">
            <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="text-lg font-bold">Audit tafsilotlari #{text(detail.id)}</h2>
                <p className="mt-1 text-sm text-slate-500">{text(detail.action)} · {formatAdminDate(String(detail.created_at ?? ""))}</p>
              </div>
              <button onClick={() => setDetail(null)} className="rounded-md p-2 text-slate-500 hover:bg-slate-100"><X size={18} /></button>
            </header>
            <div className="grid max-h-[75vh] gap-4 overflow-y-auto p-5 md:grid-cols-2">
              <div className="rounded-md border border-slate-200 p-4 text-sm">
                <p><span className="font-semibold text-slate-500">Bajaruvchi:</span> {actorLabel(detail)}</p>
                <p className="mt-2"><span className="font-semibold text-slate-500">Obyekt:</span> {text(detail.entity_type)} #{text(detail.entity_id)}</p>
                <p className="mt-2"><span className="font-semibold text-slate-500">Sabab:</span> {text(detail.reason)}</p>
                <p className="mt-2"><span className="font-semibold text-slate-500">IP:</span> {text(detail.ip_address)}</p>
                <p className="mt-2"><span className="font-semibold text-slate-500">User agent:</span> {text(detail.user_agent)}</p>
              </div>
              <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-800">
                Audit yozuvlari read-only: panel orqali o'zgartirish yoki o'chirish amali mavjud emas, backend esa update/delete'ni bloklaydi.
              </div>
              <div>
                <p className="mb-2 text-sm font-bold text-slate-950">Old value</p>
                <JsonBlock value={detail.old_value} />
              </div>
              <div>
                <p className="mb-2 text-sm font-bold text-slate-950">New value</p>
                <JsonBlock value={detail.new_value} />
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
