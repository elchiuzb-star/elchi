import { useEffect, useMemo, useState } from "react";
import { Eye, RefreshCw, Search, X } from "./ui/icons";

import { listAdminAuditLogs, type AdminRecord } from "../api/admin.api";
import type { MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type { AuthRole, AuthUser } from "../types/auth";
import { adminErrorMessage, adminRoleLabel } from "../utils/adminUserLabels";
import { formatDateTime } from "../utils/v2Format";

/** `AUDIT_LOG_ROLES` (admin_audit_logs.py): admin and super_admin; the shell hides the panel from everyone else. */
export function canReadAuditLog(role: string): boolean {
  return role === "admin" || role === "super_admin";
}

const ACTOR_ROLES = ["client", "driver", "operator", "admin", "super_admin", "finance", "system"] as const;

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
  const role = adminRoleLabel(row.actor_role ? String(row.actor_role) : null);
  if (!actor) return role;
  return [text(actor.full_name), text(actor.phone)].filter((item) => item !== "-").join(" · ") || role;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-56 overflow-auto rounded-[10px] bg-foreground p-3 text-xs leading-5 text-muted">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

export function AdminAuditLogsPanel({ user }: { user: AuthUser }) {
  const t = useT();
  const [rows, setRows] = useState<AdminRecord[]>([]);
  const [filters, setFilters] = useState<Filters>({ page: 1, limit: 100 });
  const [draftSearch, setDraftSearch] = useState("");
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminRecord | null>(null);
  const canView = canReadAuditLog(user.role);

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
      setError(adminErrorMessage(err, "admin.audit.loadFailed"));
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
      <div className="rounded-[12px] border border-warning/28 bg-warning/14 p-4 text-sm font-semibold text-warning">
        {t("admin.audit.noAccess")}
      </div>
    );
  }

  const selectClass = "h-10 rounded-[10px] border border-border bg-card px-3 text-sm";
  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.audit")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.audit.subtitle")}</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={busy} className="el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border border-border bg-card px-4 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw size={16} /> {t("support.refresh")}
        </button>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {([
          ["admin.audit.total", summary.total],
          ["admin.audit.loaded", summary.loaded],
          ["admin.audit.rolesOnPage", summary.roles],
        ] as Array<[MessageKey, number]>).map(([label, value]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <p className="text-xs font-semibold text-muted-foreground">{t(label)}</p>
            <p className="mt-2 text-2xl font-bold text-foreground">{value}</p>
          </div>
        ))}
      </section>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">{error}</div>}

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[1.5fr_1fr_1fr_1fr]">
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("location.search")}
            <span className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={draftSearch}
                onChange={(event) => setDraftSearch(event.target.value)}
                placeholder={t("admin.audit.searchPh")}
                className="h-10 w-full rounded-[10px] border border-border bg-card pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
              />
            </span>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.staff.role")}
            <select
              value={filters.actor_role ?? ""}
              onChange={(event) => setFilters({
                ...filters,
                actor_role: (event.target.value || undefined) as Filters["actor_role"],
                page: 1,
              })}
              className={selectClass}
            >
              <option value="">{t("admin.common.all")}</option>
              {ACTOR_ROLES.map((role) => <option key={role} value={role}>{adminRoleLabel(role)}</option>)}
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.audit.objectType")}
            <input
              value={filters.entity_type ?? ""}
              onChange={(event) => setFilters({ ...filters, entity_type: event.target.value || undefined, page: 1 })}
              placeholder={t("admin.common.all")}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm outline-none focus:border-primary"
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.audit.action")}
            <input
              value={filters.action ?? ""}
              onChange={(event) => setFilters({ ...filters, action: event.target.value || undefined, page: 1 })}
              placeholder={t("admin.common.all")}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm outline-none focus:border-primary"
            />
          </label>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
              <tr>
                {([
                  "admin.common.id",
                  "admin.audit.actor",
                  "admin.staff.role",
                  "admin.audit.action",
                  "admin.audit.object",
                  "common.reason",
                  "admin.audit.ip",
                  "admin.common.created",
                ] as MessageKey[]).map((key) => (
                  <th key={key} className="px-4 py-3 font-semibold">{t(key)}</th>
                ))}
                <th className="px-4 py-3"><span className="sr-only">{t("admin.common.view")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !rows.length ? Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={9} className="px-4 py-3"><div className="h-8 animate-pulse rounded bg-background" /></td></tr>
              )) : rows.length ? rows.map((row) => (
                <tr key={String(row.id)} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-semibold text-secondary-foreground">{text(row.id)}</td>
                  <td className="px-4 py-3">{actorLabel(row)}</td>
                  <td className="px-4 py-3">{adminRoleLabel(row.actor_role ? String(row.actor_role) : null)}</td>
                  <td className="px-4 py-3 font-mono text-xs font-semibold text-foreground">{text(row.action)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{text(row.entity_type)} #{text(row.entity_id)}</td>
                  <td className="px-4 py-3">{text(row.reason)}</td>
                  <td className="px-4 py-3">{text(row.ip_address)}</td>
                  <td className="whitespace-nowrap px-4 py-3">{formatDateTime(String(row.created_at ?? ""))}</td>
                  <td className="px-4 py-3">
                    <button type="button" onClick={() => setDetail(row)} className="el-press inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline"><Eye size={15} /> {t("admin.common.view")}</button>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-muted-foreground">{t("admin.audit.empty")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm text-secondary-foreground">
          <span>{t("admin.common.pageOf", { page: filters.page, pages: totalPages || 1, total })}</span>
          <div className="flex gap-2">
            <button type="button" disabled={busy || filters.page <= 1} onClick={() => setFilters({ ...filters, page: Math.max(1, filters.page - 1) })} className="el-press h-9 rounded-[10px] border border-border px-3 font-semibold disabled:opacity-50">{t("admin.common.prev")}</button>
            <button type="button" disabled={busy || filters.page >= (totalPages || 1)} onClick={() => setFilters({ ...filters, page: filters.page + 1 })} className="el-press h-9 rounded-[10px] border border-border px-3 font-semibold disabled:opacity-50">{t("admin.common.next")}</button>
          </div>
        </footer>
      </section>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
          <section role="dialog" aria-modal="true" aria-label={t("admin.audit.detailTitle", { id: text(detail.id) })} className="w-full max-w-3xl rounded-[12px] bg-card shadow-xl">
            <header className="flex items-start justify-between gap-4 border-b border-muted px-5 py-4">
              <div>
                <h2 className="text-lg font-bold">{t("admin.audit.detailTitle", { id: text(detail.id) })}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{text(detail.action)} · {formatDateTime(String(detail.created_at ?? ""))}</p>
              </div>
              <button type="button" onClick={() => setDetail(null)} aria-label={t("common.close")} className="el-press rounded-[10px] p-2 text-muted-foreground hover:bg-muted"><X size={18} /></button>
            </header>
            <div className="grid max-h-[75vh] gap-4 overflow-y-auto p-5 md:grid-cols-2">
              <div className="rounded-[10px] border border-border p-4 text-sm">
                <p><span className="font-semibold text-muted-foreground">{t("admin.audit.actor")}:</span> {actorLabel(detail)} · {adminRoleLabel(detail.actor_role ? String(detail.actor_role) : null)}</p>
                <p className="mt-2"><span className="font-semibold text-muted-foreground">{t("admin.audit.object")}:</span> {text(detail.entity_type)} #{text(detail.entity_id)}</p>
                <p className="mt-2"><span className="font-semibold text-muted-foreground">{t("common.reason")}:</span> {text(detail.reason)}</p>
                <p className="mt-2"><span className="font-semibold text-muted-foreground">{t("admin.audit.ip")}:</span> {text(detail.ip_address)}</p>
                <p className="mt-2 break-words"><span className="font-semibold text-muted-foreground">{t("admin.audit.userAgent")}:</span> {text(detail.user_agent)}</p>
              </div>
              <div className="rounded-[10px] border border-warning/28 bg-warning/14 p-4 text-sm font-semibold text-warning">
                {t("admin.audit.readOnlyNote")}
              </div>
              <div>
                <p className="mb-2 text-sm font-bold text-foreground">{t("admin.audit.oldValue")}</p>
                <JsonBlock value={detail.old_value} />
              </div>
              <div>
                <p className="mb-2 text-sm font-bold text-foreground">{t("admin.audit.newValue")}</p>
                <JsonBlock value={detail.new_value} />
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
