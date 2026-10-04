/**
 * ADR-0026 (Q141): the operator queue of booking-bound complaint chats.
 *
 * Staff see who wrote (client or driver of which booking), the conversation, who owns it and whether it is open. They
 * answer, take it on, or close it. None of that refunds, releases a fee, grants a bonus or records fraud - money and
 * sanctions stay with the finance commands and the internal dispute record, which this panel does not touch.
 *
 * Users no longer open disputes (Q141): this chat is where they write, from «Yordam / shikoyat» on the booking page
 * (Q146). The thread DTO carries ids only for the assignee and no route (contract: still BLOCKED), so the header
 * shows the assignee id and the system line the booking id.
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
import { translateDynamic, type MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import { formatDateTime } from "../utils/v2Format";
import { Badge, Chips, ErrorLine, Note, PanelHead, countText, hasCap, type BadgeTone } from "./adminMarketKit";
import { Inbox, Loader2, RefreshCw } from "./ui/icons";

const STAFF_STATUS_TONE: Record<string, BadgeTone> = { waiting: "gray", assigned: "warn", answered: "blue", closed: "gray" };

function staffStatusLabel(status: string): string {
  return translateDynamic(`admin.threads.status.${status}`) ?? status;
}

const AUTHOR_KEY: Record<string, MessageKey> = {
  operator: "support.operator",
  system: "admin.threads.author.system",
  client: "admin.mk.client",
  driver: "admin.mk.driver",
  me: "admin.threads.me",
};

type Filter = "unassigned" | "me" | "open" | "closed";

const FILTER_KEY: Record<Filter, MessageKey> = {
  unassigned: "admin.threads.filter.queue",
  me: "admin.threads.filter.mine",
  open: "admin.threads.filter.open",
  closed: "admin.threads.filter.closed",
};

export function threadQuery(filter: Filter): { status: "open" | "closed"; assigned?: "me" | "unassigned" } {
  if (filter === "closed") return { status: "closed" };
  if (filter === "open") return { status: "open" };
  return { status: "open", assigned: filter };
}

const LIMIT = 50;

export function AdminSupportThreadsPanel() {
  const t = useT();
  const [caps, setCaps] = useState<CapabilitiesDTO | null>(null);
  const [filter, setFilter] = useState<Filter>("unassigned");
  const [rows, setRows] = useState<SupportThreadAdminDTO[] | null>(null);
  const [queueCount, setQueueCount] = useState<string | null>(null);
  const [selected, setSelected] = useState<SupportThreadAdminDTO | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const canAct = hasCap(caps as { capabilities?: readonly string[] } | null, "ops.trust_review");

  const load = useCallback(() => {
    setRows(null);
    setError(null);
    listSupportThreadsAdmin({ ...threadQuery(filter), limit: LIMIT })
      .then((list) => {
        setRows(list);
        if (filter === "unassigned") setQueueCount(countText(list.length, LIMIT));
      })
      .catch((cause) => {
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

  const side = (value: string) => (value === "client" ? t("admin.mk.client") : t("admin.mk.driver"));

  return (
    <div className="grid gap-4">
      <PanelHead title={t("admin.threads.title")} sub={t("admin.threads.subtitle")} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Chips
              label={t("admin.mk.status")}
              value={filter}
              onChange={setFilter}
              items={(["unassigned", "me", "open", "closed"] as Filter[]).map((value) => ({
                value,
                label: value === "unassigned" && queueCount ? t("admin.threads.filter.queueCount", { count: queueCount }) : t(FILTER_KEY[value]),
              }))}
            />
            <button type="button" onClick={load} aria-label={t("support.refresh")} className="ml-auto text-slate-500">
              <RefreshCw size={16} />
            </button>
          </div>
          {rows === null ? (
            <Loader2 size={16} className="animate-spin text-slate-400" aria-busy="true" />
          ) : rows.length === 0 ? (
            <div className="rounded-[12px] border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
              <Inbox size={18} className="mx-auto mb-2 text-slate-400" />
              {t("admin.threads.empty")}
            </div>
          ) : (
            rows.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => void open(row.id)}
                className={`w-full rounded-[12px] border p-3 text-left text-sm ${selected?.id === row.id ? "border-primary bg-accent" : "border-border bg-card"}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0 font-semibold">{side(row.requester_side)} · {row.booking_id}</span>
                  <Badge tone={STAFF_STATUS_TONE[row.staff_status] ?? "gray"}>{staffStatusLabel(row.staff_status)}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("admin.threads.rowMeta", { count: row.message_count, time: formatDateTime(row.created_at) })}
                  {row.carried_over_from_dispute ? ` · ${t("admin.threads.migrated")}` : ""}
                </p>
              </button>
            ))
          )}
        </div>
        <div className="space-y-3">
          <ErrorLine error={error} />
          {!selected ? (
            <p className="text-sm text-muted-foreground">{t("admin.threads.pick")}</p>
          ) : (
            <div className="space-y-3 rounded-[14px] border border-border bg-card p-4">
              <div className="text-sm">
                <p className="font-semibold">
                  {side(selected.requester_side)} · {selected.booking_id}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("admin.threads.header", {
                    status: staffStatusLabel(selected.staff_status),
                    name: selected.assigned_to ?? t("admin.threads.nobody"),
                  })}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{selected.requester_user_id}</p>
              </div>
              <Note tone="warn">{t("admin.threads.noMoneyNote")}</Note>
              <div className="max-h-[420px] space-y-2 overflow-y-auto">
                <p className="rounded-[10px] bg-muted px-3 py-1.5 text-center text-xs text-muted-foreground">
                  {t("admin.threads.systemLine", { booking: selected.booking_id })}
                </p>
                {(selected.messages ?? []).map((message) => (
                  <div
                    key={message.id}
                    className={`rounded-[10px] px-3 py-2 text-sm ${
                      message.staff_only
                        ? "border border-warning/30 bg-warning/10"
                        : message.author === "operator" || message.author === "me"
                          ? "bg-accent"
                          : message.author === "system"
                            ? "bg-muted text-xs"
                            : "bg-background"
                    }`}
                  >
                    <p className="text-[11px] font-semibold text-muted-foreground">
                      {AUTHOR_KEY[message.author] ? t(AUTHOR_KEY[message.author]) : message.author} · {formatDateTime(message.created_at)}
                      {message.has_files ? ` · ${t("admin.threads.hasFile")}` : ""}
                      {message.staff_only ? ` · ${t("admin.threads.staffOnly")}` : ""}
                    </p>
                    <p className="whitespace-pre-wrap break-words">{message.text}</p>
                    {(selected.files ?? []).filter((file) => file.message_id === message.id).map((file) => (
                      <div key={file.ref} className="mt-1.5 flex items-center justify-between gap-2 rounded-[8px] bg-muted/60 px-2 py-1 text-xs">
                        <span className="min-w-0 truncate">{file.name}</span>
                        <button type="button" onClick={() => void openFile(file.ref)} className="shrink-0 font-semibold text-primary">
                          {t("admin.mk.view")}
                        </button>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              {selected.status === "open" && canAct ? (
                <div className="space-y-2">
                  <label className="grid gap-1 text-sm font-medium text-secondary-foreground">
                    {t("admin.threads.reply")}
                    <textarea
                      aria-label={t("admin.threads.reply")}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      className="h-20 w-full rounded-[10px] border border-border bg-card px-3 py-2 text-sm"
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={busy || !draft.trim()} onClick={() => void command("reply", draft.trim())}
                            className="h-9 rounded-[10px] bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">
                      {t("admin.threads.send")}
                    </button>
                    {!selected.assigned_to && (
                      <button type="button" disabled={busy} onClick={() => void command("assign")}
                              className="h-9 rounded-[10px] border border-border px-3 text-sm font-semibold">
                        {t("admin.threads.take")}
                      </button>
                    )}
                    <button type="button" disabled={busy} onClick={() => void command("close", draft.trim() || undefined)}
                            className="h-9 rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 text-sm font-semibold text-destructive">
                      {t("common.close")}
                    </button>
                  </div>
                </div>
              ) : selected.status === "open" ? (
                <p className="text-xs text-muted-foreground">{t("admin.threads.noRole")}</p>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
