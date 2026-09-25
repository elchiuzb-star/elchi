/**
 * ADR-0026 (Q141): the operator queue of booking-bound complaint chats.
 *
 * Staff see who wrote (client or driver of which booking), the conversation, who owns it and whether it is open. They
 * answer, take it on, or close it. None of that refunds, releases a fee, grants a bonus or records fraud - money and
 * sanctions stay with the finance commands and the internal dispute record, which this panel does not touch.
 */
import { useCallback, useEffect, useState } from "react";

import {
  getSupportThreadAdmin,
  listSupportThreadsAdmin,
  supportThreadCommand,
  supportThreadFileLink,
  type SupportThreadAdminDTO,
} from "../api/v2/admin-trust.api";
import { apiOriginUrl } from "../api/http";
import { newIdempotencyKey } from "../api/v2/http";
import { capabilities, type CapabilitiesDTO } from "../api/v2/ops.api";
import { formatDateTime } from "../utils/v2Format";
import { v2ErrorMessage } from "../utils/v2Errors";
import { Inbox, Loader2, RefreshCw } from "./ui/icons";

const STAFF_STATUS: Record<string, string> = {
  waiting: "Navbatda (hech kim olmagan)",
  assigned: "Operatorda",
  answered: "Javob berilgan",
  closed: "Yopilgan",
};

type Filter = "unassigned" | "me" | "open" | "closed";

export function threadQuery(filter: Filter): { status: "open" | "closed"; assigned?: "me" | "unassigned" } {
  if (filter === "closed") return { status: "closed" };
  if (filter === "open") return { status: "open" };
  return { status: "open", assigned: filter };
}

export function AdminSupportThreadsPanel() {
  const [caps, setCaps] = useState<CapabilitiesDTO | null>(null);
  const [filter, setFilter] = useState<Filter>("unassigned");
  const [rows, setRows] = useState<SupportThreadAdminDTO[] | null>(null);
  const [selected, setSelected] = useState<SupportThreadAdminDTO | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const canAct = Boolean(caps?.capabilities?.includes("ops.trust_review" as never));

  const load = useCallback(() => {
    setRows(null);
    setError(null);
    listSupportThreadsAdmin({ ...threadQuery(filter), limit: 50 }).then(setRows).catch((cause) => {
      setRows([]);
      setError(cause);
    });
  }, [filter]);

  useEffect(() => {
    capabilities().then(setCaps).catch(() => setCaps(null));
  }, []);
  useEffect(load, [load]);

  async function open(threadId: string) {
    setError(null);
    try {
      setSelected(await getSupportThreadAdmin(threadId));
      setDraft("");
    } catch (cause) {
      setError(cause);
    }
  }

  /** The link is asked for only when a person clicks - each open is checked and audited by the server. */
  async function openFile(ref: string) {
    if (!selected) return;
    setError(null);
    try {
      const link = await supportThreadFileLink(selected.id, ref);
      window.open(apiOriginUrl(link.url), "_blank", "noopener,noreferrer");
    } catch (cause) {
      setError(cause);
    }
  }

  async function command(name: "assign" | "reply" | "close", text?: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const next = await supportThreadCommand(selected.id, name, { expected_version: selected.version, text: text ?? null },
                                              newIdempotencyKey());
      setSelected(next);
      setDraft("");
      load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {(["unassigned", "me", "open", "closed"] as Filter[]).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilter(value)}
              className={`h-8 rounded-full px-3 text-sm font-semibold ${filter === value ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}
            >
              {{ unassigned: "Navbat", me: "Menda", open: "Barcha ochiq", closed: "Yopilgan" }[value]}
            </button>
          ))}
          <button type="button" onClick={load} aria-label="Yangilash" className="ml-auto text-slate-500">
            <RefreshCw size={16} />
          </button>
        </div>
        {rows === null ? (
          <Loader2 size={16} className="animate-spin text-slate-400" aria-busy="true" />
        ) : rows.length === 0 ? (
          <div className="rounded-[12px] border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
            <Inbox size={18} className="mx-auto mb-2 text-slate-400" />
            Murojaat yo'q
          </div>
        ) : (
          rows.map((row) => (
            <button
              key={row.id}
              type="button"
              onClick={() => void open(row.id)}
              className={`w-full rounded-[12px] border p-3 text-left text-sm ${selected?.id === row.id ? "border-primary bg-accent" : "border-border bg-card"}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{row.requester_side === "client" ? "Mijoz" : "Haydovchi"} · {row.booking_id}</span>
                <span className="text-xs text-muted-foreground">{STAFF_STATUS[row.staff_status] ?? row.staff_status}</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {row.requester_user_id} · {row.message_count} ta xabar · {formatDateTime(row.created_at)}
                {row.carried_over_from_dispute ? " · eski nizodan ko'chirilgan" : ""}
              </p>
            </button>
          ))
        )}
      </div>
      <div className="space-y-3">
        {error ? <p role="alert" className="rounded-[10px] bg-destructive/10 px-3 py-2 text-sm text-destructive">{v2ErrorMessage(error)}</p> : null}
        {!selected ? (
          <p className="text-sm text-muted-foreground">Murojaatni tanlang.</p>
        ) : (
          <div className="space-y-3 rounded-[14px] border border-border bg-card p-4">
            <div className="text-sm">
              <p className="font-semibold">
                {selected.requester_side === "client" ? "Mijoz" : "Haydovchi"} {selected.requester_user_id} · bron {selected.booking_id}
              </p>
              <p className="text-xs text-muted-foreground">
                Holat: {selected.status === "open" ? "ochiq" : "yopiq"} · mas'ul: {selected.assigned_to ?? "hech kim"} ·
                {" "}{STAFF_STATUS[selected.staff_status] ?? selected.staff_status}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Bu yozishma pul qaytarmaydi, komissiyani bekor qilmaydi va bonus bermaydi - buning uchun moliya buyruqlari bor.
              </p>
            </div>
            <div className="max-h-[420px] space-y-2 overflow-y-auto">
              {(selected.messages ?? []).map((message) => (
                <div key={message.id} className={`rounded-[10px] px-3 py-2 text-sm ${message.author === "operator" ? "bg-accent" : message.author === "system" ? "bg-muted text-xs" : "bg-background"}`}>
                  <p className="text-[11px] font-semibold text-muted-foreground">
                    {{ operator: "Operator", system: "Tizim", client: "Mijoz", driver: "Haydovchi", me: "Men" }[message.author]} ·{" "}
                    {formatDateTime(message.created_at)}{message.has_files ? " · fayl bor" : ""}
                    {message.staff_only ? " · faqat xodimga (so'rovchiga ko'rinmaydi)" : ""}
                  </p>
                  <p className="whitespace-pre-wrap break-words">{message.text}</p>
                  {(selected.files ?? []).filter((file) => file.message_id === message.id).map((file) => (
                    <div key={file.ref} className="mt-1.5 flex items-center justify-between gap-2 rounded-[8px] bg-muted/60 px-2 py-1 text-xs">
                      <span className="min-w-0 truncate">{file.name}</span>
                      <button type="button" onClick={() => void openFile(file.ref)} className="shrink-0 font-semibold text-primary">
                        Ko'rish
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            {selected.status === "open" && canAct ? (
              <div className="space-y-2">
                <textarea
                  aria-label="Javob"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  className="h-20 w-full rounded-[10px] border border-border bg-card px-3 py-2 text-sm"
                />
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={busy || !draft.trim()} onClick={() => void command("reply", draft.trim())}
                          className="h-9 rounded-[10px] bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">
                    Javob yuborish
                  </button>
                  {!selected.assigned_to && (
                    <button type="button" disabled={busy} onClick={() => void command("assign")}
                            className="h-9 rounded-[10px] border border-border px-3 text-sm font-semibold">
                      O'zimga olish
                    </button>
                  )}
                  <button type="button" disabled={busy} onClick={() => void command("close", draft.trim() || undefined)}
                          className="h-9 rounded-[10px] border border-destructive/40 px-3 text-sm font-semibold text-destructive">
                    Yopish
                  </button>
                </div>
              </div>
            ) : selected.status === "open" ? (
              <p className="text-xs text-muted-foreground">Javob berish uchun ops.trust_review huquqi kerak.</p>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
