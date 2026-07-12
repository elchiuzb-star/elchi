import { useEffect, useState } from "react";
import { Bell, CheckCheck, RefreshCw } from "lucide-react";

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
        <p className="text-sm text-slate-500">Backenddagi buyurtma va tizim hodisalaridan kelgan xodim bildirishnomalari.</p>
        <div className="flex flex-wrap gap-2">
          <select value={filter} onChange={(event) => setFilter(event.target.value)} className="h-9 rounded-md border border-slate-200 px-3 text-sm">
            <option value="">Barchasi</option>
            <option value="unread">O'qilmagan</option>
            <option value="read">O'qilgan</option>
          </select>
          <button onClick={() => void load()} disabled={busy} className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            <RefreshCw size={16} /> Yangilash
          </button>
          <button onClick={() => void run(markAllAdminNotificationsRead)} disabled={busy || items.length === 0} className="inline-flex h-9 items-center gap-2 rounded-md border border-blue-600 bg-blue-600 px-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
            <CheckCheck size={16} /> Mark all read
          </button>
        </div>
      </div>
      {error && <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800">{error}</div>}
      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="divide-y divide-slate-100">
          {items.map((item) => (
            <div key={item.id} className={`flex min-w-0 flex-wrap items-start justify-between gap-4 p-4 ${item.is_read ? "bg-white" : "bg-blue-50/50"}`}>
              <div className="flex min-w-0 flex-1 gap-3">
                <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600"><Bell size={17} /></div>
                <div className="min-w-0">
                  <p className="font-bold">{item.title || item.type || "Bildirishnoma"}</p>
                  <p className="mt-1 break-words text-sm text-slate-600">{item.message || "Xabar yo'q"}</p>
                  <p className="mt-2 text-xs text-slate-500">{formatAdminDate(item.created_at)}{item.order_id ? ` · Order #${item.order_id}` : ""}</p>
                </div>
              </div>
              {!item.is_read && (
                <button onClick={() => void run(() => markAdminNotificationRead(item.id))} className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  Mark read
                </button>
              )}
            </div>
          ))}
          {items.length === 0 && <div className="p-10 text-center text-sm text-slate-500">No notifications found.</div>}
        </div>
      </section>
    </div>
  );
}
