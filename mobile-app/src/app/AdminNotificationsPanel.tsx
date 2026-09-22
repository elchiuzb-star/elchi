import { useEffect, useState } from "react";
import { Bell, CheckCheck, RefreshCw } from "./ui/icons";

import {
  getAdminNotifications,
  markAdminNotificationRead,
  markAllAdminNotificationsRead,
  type AdminNotification,
} from "../api/admin-notifications.api";
import { formatAdminDate } from "../utils/date";

export function AdminNotificationsPanel() {
  const [items, setItems] = useState<AdminNotification[]>([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const data = await getAdminNotifications({ is_read: filter, limit: 50 });
      setItems(data.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bildirishnomalarni yuklab bo'lmadi");
      setItems([]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, [filter]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bildirishnoma amali bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">Backenddagi buyurtma va tizim hodisalaridan kelgan xodim bildirishnomalari.</p>
        <div className="flex flex-wrap gap-2">
          <select value={filter} onChange={(event) => setFilter(event.target.value)} className="h-9 rounded-[10px] border border-border px-3 text-sm">
            <option value="">Barchasi</option>
            <option value="unread">O'qilmagan</option>
            <option value="read">O'qilgan</option>
          </select>
          <button onClick={() => void load()} disabled={busy} className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50">
            <RefreshCw size={16} /> Yangilash
          </button>
          <button onClick={() => void run(markAllAdminNotificationsRead)} disabled={busy || items.length === 0} className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-primary bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary disabled:opacity-50">
            <CheckCheck size={16} /> Mark all read
          </button>
        </div>
      </div>
      {error && <div className="rounded-[12px] border border-warning/28 bg-warning/14 px-4 py-3 text-sm font-semibold text-warning">{error}</div>}
      <section className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="divide-y divide-muted">
          {items.map((item) => (
            <div key={item.id} className={`flex min-w-0 flex-wrap items-start justify-between gap-4 p-4 ${item.is_read ? "bg-card" : "bg-accent/50"}`}>
              <div className="flex min-w-0 flex-1 gap-3">
                <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-background text-secondary-foreground"><Bell size={17} /></div>
                <div className="min-w-0">
                  <p className="font-bold">{item.title || item.type || "Bildirishnoma"}</p>
                  <p className="mt-1 break-words text-sm text-secondary-foreground">{item.message || "Xabar yo'q"}</p>
                  <p className="mt-2 text-xs text-muted-foreground">{formatAdminDate(item.created_at)}{item.order_id ? ` · Order #${item.order_id}` : ""}</p>
                </div>
              </div>
              {!item.is_read && (
                <button onClick={() => void run(() => markAdminNotificationRead(item.id))} className="el-press rounded-[10px] border border-border bg-card px-3 py-1.5 text-xs font-semibold text-secondary-foreground hover:bg-slate-50">
                  Mark read
                </button>
              )}
            </div>
          ))}
          {items.length === 0 && <div className="p-10 text-center text-sm text-muted-foreground">No notifications found.</div>}
        </div>
      </section>
    </div>
  );
}
