/**
 * Mijozlar (v1, DESIGN-ADMIN-DIFF §18). Read for every staff role that can open it; block / unblock is admin+ and
 * always asks for a reason (at least 3 characters), which the server records in the audit row.
 */
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Lock, RefreshCw, Search, Unlock, UserRound } from "./ui/icons";

import { blockAdminClient, getAdminClientDetail, getAdminClients, unblockAdminClient } from "../api/admin-clients.api";
import type { MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type { AdminClient, AdminClientFilters } from "../types/admin-client";
import type { AuthUser } from "../types/auth";
import { adminErrorMessage, adminStatusLabel, adminUserStatusClass, yesNo } from "../utils/adminUserLabels";
import { formatDate, formatDateTime } from "../utils/v2Format";

export const CLIENT_REASON_MIN = 3;

export function canManageClients(role: string): boolean {
  return role === "admin" || role === "super_admin";
}

function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
      <p className={`mt-2 text-2xl font-bold ${tone ?? "text-foreground"}`}>{value}</p>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p><span className="text-muted-foreground">{label}:</span> {children}</p>
  );
}

export function AdminClientsPanel({ user, initialSearch }: { user: AuthUser; initialSearch?: string }) {
  const t = useT();
  const canMutate = canManageClients(user.role);
  const [items, setItems] = useState<AdminClient[]>([]);
  const [filters, setFilters] = useState<AdminClientFilters>({ page: 1, limit: 20, search: initialSearch || undefined });
  const [searchInput, setSearchInput] = useState(initialSearch ?? "");
  const [detail, setDetail] = useState<AdminClient | null>(null);
  const [confirm, setConfirm] = useState<{ client: AdminClient; action: "block" | "unblock" } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      const data = await getAdminClients(filters);
      setItems(data.items ?? []);
    } catch (err) {
      setError(adminErrorMessage(err, "admin.clients.loadFailed"));
      setItems([]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  async function openDetail(client: AdminClient) {
    setError(null);
    try {
      setDetail(await getAdminClientDetail(client.id));
    } catch (err) {
      setError(adminErrorMessage(err, "admin.clients.detailFailed"));
    }
  }

  function askStatus(client: AdminClient, action: "block" | "unblock") {
    setReason("");
    setConfirm({ client, action });
  }

  async function runClientStatus(client: AdminClient, action: "block" | "unblock", why: string) {
    setBusy(true);
    setError(null);
    try {
      const updated = action === "block" ? await blockAdminClient(client.id, why) : await unblockAdminClient(client.id, why);
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setDetail((current) => (current?.id === updated.id ? updated : current));
      setConfirm(null);
    } catch (err) {
      setError(adminErrorMessage(err));
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

  const blocking = confirm?.action === "block";

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.clients")}</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t("admin.clients.subtitle")}</p>
          {!canMutate && <p className="mt-1 text-xs font-semibold text-warning">{t("admin.clients.readOnly")}</p>}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={busy}
          className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={16} /> {t("support.refresh")}
        </button>
      </div>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">{error}</div>}

      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label={t("admin.clients.loaded")} value={summary.total} />
        <Kpi label={t("admin.common.active")} value={summary.active} />
        <Kpi label={t("admin.common.blocked")} value={summary.blocked} tone="text-destructive" />
        <Kpi label={t("admin.clients.phoneVerified")} value={summary.verified} />
        <Kpi label={t("admin.clients.withOrders")} value={summary.withOrders} />
        <Kpi label={t("admin.clients.activeOrders")} value={summary.activeOrders} />
      </div>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 xl:grid-cols-[1.5fr_1fr_1fr]">
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("location.search")}
            <span className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t("admin.clients.searchPh")}
                className="h-10 w-full rounded-[10px] border border-border bg-card pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
              />
            </span>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            {t("admin.common.status")}
            <select value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value || undefined, page: 1 })} className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm">
              <option value="">{t("admin.common.allStatuses")}</option>
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
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
              <tr>
                {([
                  "admin.common.client",
                  "admin.common.phone",
                  "admin.common.status",
                  "admin.common.verifiedShort",
                  "orders.title",
                  "admin.common.active",
                  "admin.clients.colLastOrder",
                  "admin.common.created",
                ] as MessageKey[]).map((key) => <th key={key} className="px-4 py-3">{t(key)}</th>)}
                <th className="px-4 py-3"><span className="sr-only">{t("admin.common.view")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {items.map((client) => (
                <tr key={client.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-foreground">{client.full_name || t("admin.clients.noName")}</div>
                    <div className="text-xs text-muted-foreground">ID {client.id}</div>
                  </td>
                  <td className="px-4 py-3">{client.phone}</td>
                  <td className="px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${adminUserStatusClass(client.status)}`}>{adminStatusLabel(client.status)}</span></td>
                  <td className="px-4 py-3">{yesNo(client.is_phone_verified)}</td>
                  <td className="px-4 py-3">{client.orders_count}</td>
                  <td className="px-4 py-3">{client.active_orders_count}</td>
                  <td className="px-4 py-3">{formatDate(client.last_order_at)}</td>
                  <td className="px-4 py-3">{formatDate(client.created_at)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-semibold">
                    <button type="button" onClick={() => void openDetail(client)} className="el-press text-primary hover:underline">{t("admin.common.view")}</button>
                    {canMutate && (
                      <>
                        <span className="px-1.5 text-muted-foreground">·</span>
                        {client.status === "blocked" ? (
                          <button type="button" onClick={() => askStatus(client, "unblock")} className="el-press text-success hover:underline">{t("blockReport.unblock")}</button>
                        ) : (
                          <button type="button" onClick={() => askStatus(client, "block")} className="el-press text-destructive hover:underline">{t("blockReport.block")}</button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-muted-foreground">{busy ? t("common.loading") : t("admin.clients.empty")}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {detail && (
        <div role="dialog" aria-modal="true" aria-label={t("admin.clients.detailTitle")} className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-border bg-card shadow-xl">
          <div className="flex items-center justify-between border-b border-muted px-5 py-4">
            <h2 className="text-lg font-bold">{t("admin.clients.detailTitle")}</h2>
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
                <Row label={t("admin.common.status")}>{adminStatusLabel(detail.status)}</Row>
                <Row label={t("admin.clients.phoneVerified")}>{yesNo(detail.is_phone_verified)}</Row>
                <Row label={t("admin.overview.totalOrders")}>{detail.orders_count}</Row>
                <Row label={t("admin.clients.activeOrders")}>{detail.active_orders_count}</Row>
                <Row label={t("admin.overview.completedOrders")}>{detail.completed_orders_count}</Row>
                <Row label={t("admin.drivers.cancelledOrders")}>{detail.cancelled_orders_count}</Row>
                <Row label={t("admin.staff.colLastLogin")}>{formatDateTime(detail.last_login_at)}</Row>
                <Row label={t("admin.clients.colLastOrder")}>{formatDateTime(detail.last_order_at)}</Row>
                <Row label={t("admin.common.created")}>{formatDateTime(detail.created_at)}</Row>
              </div>
            </div>
            {canMutate && (
              <button
                type="button"
                onClick={() => askStatus(detail, detail.status === "blocked" ? "unblock" : "block")}
                className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-4 text-sm font-semibold ${
                  detail.status === "blocked"
                    ? "border-success/25 bg-success/12 text-success hover:bg-success/25"
                    : "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25"
                }`}
              >
                {detail.status === "blocked" ? <Unlock size={16} /> : <Lock size={16} />}
                {detail.status === "blocked" ? t("blockReport.unblock") : t("admin.clients.blockTitle")}
              </button>
            )}
            <div className="rounded-[12px] border border-border p-4 text-sm text-secondary-foreground">{t("admin.clients.detailHint")}</div>
          </div>
        </div>
      )}

      {confirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
          <section role="dialog" aria-modal="true" aria-label={t(blocking ? "admin.clients.blockTitle" : "admin.clients.unblockTitle")} className="w-full max-w-md rounded-[12px] bg-card shadow-xl">
            <div className="border-b border-muted px-5 py-4">
              <h2 className="text-lg font-bold">{t(blocking ? "admin.clients.blockTitle" : "admin.clients.unblockTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{confirm.client.full_name || confirm.client.phone}</p>
            </div>
            <div className="grid gap-4 p-5">
              <p className="text-sm text-foreground">{t(blocking ? "admin.clients.blockText" : "admin.clients.unblockText")}</p>
              <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                {t("admin.common.reasonMin3")} *
                <textarea
                  value={reason}
                  rows={3}
                  onChange={(event) => setReason(event.target.value)}
                  className="min-h-[84px] rounded-[10px] border border-border bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
                />
              </label>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setConfirm(null)} className="el-press h-10 rounded-[10px] border border-border px-4 text-sm font-semibold text-secondary-foreground hover:bg-slate-50">{t("common.cancel")}</button>
                <button
                  type="button"
                  disabled={busy || reason.trim().length < CLIENT_REASON_MIN}
                  onClick={() => void runClientStatus(confirm.client, confirm.action, reason.trim())}
                  className={`el-press inline-flex h-10 items-center gap-2 rounded-[10px] px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 ${blocking ? "bg-destructive hover:bg-destructive" : "bg-success hover:brightness-95"}`}
                >
                  {blocking ? <Lock size={16} /> : <Unlock size={16} />}
                  {t(blocking ? "blockReport.block" : "blockReport.unblock")}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
