/**
 * Bildirishnomalar (DESIGN-ADMIN-DIFF §24): the signed-in staff member's own v1 inbox. Every staff role reads it,
 * finance included (ADMIN-BACKEND-CONTRACT §1.2). The design's staff categories (top-up, no-show, escalation...)
 * need staff notification producers that do not exist yet (§24.3, BLOCKED) - this lists what the server has.
 */
import { useEffect, useState } from "react";
import { Bell, CheckCheck, RefreshCw } from "./ui/icons";

import {
  getAdminNotifications,
  markAdminNotificationRead,
  markAllAdminNotificationsRead,
  type AdminNotification,
} from "../api/admin-notifications.api";
import { useT } from "../i18n/react";
import { adminErrorMessage } from "../utils/adminUserLabels";
import { formatDateTime } from "../utils/v2Format";

type Filter = "" | "unread" | "read";

export function AdminNotificationsPanel() {
  const t = useT();
  const [items, setItems] = useState<AdminNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [filter, setFilter] = useState<Filter>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const [data, unread] = await Promise.all([
        getAdminNotifications({ is_read: filter, limit: 50 }),
        filter === "unread" ? Promise.resolve(null) : getAdminNotifications({ is_read: "unread", limit: 50 }).catch(() => null),
      ]);
      setItems(data.items ?? []);
      const unreadItems = filter === "unread" ? data : unread;
      setUnreadCount(unreadItems ? (unreadItems.pagination?.total ?? unreadItems.items?.length ?? 0) : null);
    } catch (err) {
      setError(adminErrorMessage(err, "admin.inbox.loadFailed"));
      setItems([]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(adminErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const chips: Array<{ value: Filter; label: string }> = [
    { value: "", label: t("admin.common.all") },
    { value: "unread", label: unreadCount === null ? t("admin.inbox.unread") : t("admin.inbox.unreadCount", { count: unreadCount }) },
    { value: "read", label: t("admin.inbox.read") },
  ];

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-2xl font-bold text-foreground">{t("notifications.title")}</h2>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => void load()} disabled={busy} className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50">
            <RefreshCw size={16} /> {t("support.refresh")}
          </button>
          <button type="button" onClick={() => void run(markAllAdminNotificationsRead)} disabled={busy || items.length === 0 || unreadCount === 0} className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-blue-200 bg-accent px-3 text-sm font-semibold text-primary hover:brightness-95 disabled:opacity-50">
            <CheckCheck size={16} /> {t("admin.inbox.readAll")}
          </button>
        </div>
      </div>

      <div role="tablist" aria-label={t("notifications.title")} className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.value || "all"}
            type="button"
            role="tab"
            aria-selected={filter === chip.value}
            onClick={() => setFilter(chip.value)}
            className={`el-press rounded-full border px-3 py-1.5 text-sm font-semibold ${filter === chip.value ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-secondary-foreground hover:bg-slate-50"}`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {error && <div className="rounded-[12px] border border-warning/28 bg-warning/14 px-4 py-3 text-sm font-semibold text-warning">{error}</div>}
      <section className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="divide-y divide-muted">
          {items.map((item) => (
            <div key={item.id} className={`flex min-w-0 flex-wrap items-start justify-between gap-4 p-4 ${item.is_read ? "bg-card" : "bg-accent/50"}`}>
              <div className="flex min-w-0 flex-1 gap-3">
                <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-background text-secondary-foreground"><Bell size={17} /></div>
                <div className="min-w-0">
                  <p className="font-bold">{item.title || t("admin.inbox.untitled")}</p>
                  {item.message && <p className="mt-1 break-words text-sm text-secondary-foreground">{item.message}</p>}
                  <p className="mt-2 text-xs text-muted-foreground">
                    {formatDateTime(item.created_at)}
                    {item.order_id ? ` · ${t("admin.inbox.orderRef", { id: item.order_id })}` : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${item.is_read ? "border-border bg-slate-50 text-secondary-foreground" : "border-destructive/25 bg-destructive/10 text-destructive"}`}>
                  {t(item.is_read ? "admin.inbox.read" : "admin.inbox.unread")}
                </span>
                {!item.is_read && (
                  <button type="button" onClick={() => void run(() => markAdminNotificationRead(item.id))} className="el-press rounded-[10px] border border-border bg-card px-3 py-1.5 text-xs font-semibold text-secondary-foreground hover:bg-slate-50">
                    {t("admin.inbox.markRead")}
                  </button>
                )}
              </div>
            </div>
          ))}
          {items.length === 0 && <div className="p-10 text-center text-sm text-muted-foreground">{busy ? t("common.loading") : t("admin.inbox.empty")}</div>}
        </div>
      </section>
    </div>
  );
}
