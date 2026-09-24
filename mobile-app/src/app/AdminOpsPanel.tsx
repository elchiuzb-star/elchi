/**
 * A9 operator screens inside the admin panel: the v2 queues, disputes and the KPI/SLO view.
 *
 * What the panel promises is what the server actually allows (spec §9):
 * * decision buttons appear only for the capabilities `/me/capabilities` really returns - an operator reviews a
 *   dispute and writes a note, admin+ decides it (Q78);
 * * closing a payment dispute asks for the cash outcome, because the server refuses to leave a contested receipt
 *   unanswered;
 * * KPI show the count pair, mark a small sample and list the metrics this system does not measure at all;
 * * an SLO indicator that is not measured says so instead of showing a number (§19.3, §20.4).
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Archive, BarChart3, Inbox, Loader2, RefreshCw } from "./ui/icons";

import {
  OPS_QUEUES,
  capabilities,
  disputeCommand,
  kpi as loadKpi,
  listDisputes,
  listLegacyOrders,
  listTrustReviews,
  opsQueue,
  slo as loadSlo,
  ticketCommand,
  trustReviewCommand,
  type CapabilitiesDTO,
  type DisputeDTO,
  type KpiDTO,
  type LegacyOrderViewDTO,
  type OpsQueue,
  type OpsQueueItemDTO,
  type SloDTO,
  type TrustReviewDTO,
} from "../api/v2/ops.api";
import { listSupportTicketsAdmin, type SupportTicketAdminDTO } from "../api/v2/admin-trust.api";
import { formatDateTime, formatMinor } from "../utils/v2Format";
import { v2ErrorMessage } from "../utils/v2Errors";
import { ConfirmButton } from "./AdminTrustPanel";

const QUEUE_LABEL: Record<string, string> = {
  awaiting_confirmation: "Tasdiq kutilmoqda",
  no_show_review: "Kelmadi ko'rigi",
  custody_case: "Yuk saqlovda",
  hold_escalation: "Hold eskalatsiyasi",
  finance_review: "Moliya ko'rigi",
  dispute: "Nizolar",
  support_ticket: "Murojaatlar",
  trust_review: "Ishonch navbati",
};

const DISPUTE_STATUS_LABEL: Record<string, string> = {
  open: "Ochiq",
  under_review: "Ko'rikda",
  resolved: "Hal qilingan",
  rejected: "Rad etilgan",
};

const RESOLUTION_CODES: Array<[string, string]> = [
  ["service_confirmed", "Xizmat ko'rsatilgan"],
  ["service_not_provided", "Xizmat ko'rsatilmagan"],
  ["paid_confirmed", "To'lov tasdiqlandi"],
  ["unpaid_confirmed", "To'lanmagani tasdiqlandi"],
  ["commission_adjusted", "Komissiya tuzatildi"],
  ["no_action", "Chora ko'rilmadi"],
  ["other", "Boshqa"],
];

function Spinner() {
  return <Loader2 size={16} className="animate-spin text-slate-400" />;
}

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
      {v2ErrorMessage(error)}
    </p>
  );
}

function useLoader<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(true);
  const [nonce, setNonce] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    run()
      .then((value) => !cancelled && setData(value))
      .catch((cause) => !cancelled && setError(cause))
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [run, nonce]);

  return { data, error, busy, reload: () => setNonce((value) => value + 1) };
}

// --- queues -------------------------------------------------------------------------------------------------

export function AdminOpsQueuesPanel({ onOpenItem }: { onOpenItem?: (item: OpsQueueItemDTO) => void } = {}) {
  const [queue, setQueue] = useState<OpsQueue>("finance_review");
  const items = useLoader<OpsQueueItemDTO[]>(() => opsQueue(queue, { limit: 50 }), [queue]);

  return (
    <section className="grid gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Operator navbatlari</h2>
          <p className="text-sm text-muted-foreground">Har navbat o'z modulidan o'qiladi; bu yerda alohida jadval yo'q.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={queue}
            onChange={(event) => setQueue(event.target.value as OpsQueue)}
            className="h-9 rounded-[10px] border border-border bg-card px-3 text-sm"
          >
            {OPS_QUEUES.map((value) => (
              <option key={value} value={value}>
                {QUEUE_LABEL[value] ?? value}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={items.reload}
            className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground"
          >
            <RefreshCw size={14} /> Yangilash
          </button>
        </div>
      </header>

      <ErrorLine error={items.error} />
      <div className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <table className="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-semibold">Ob'ekt</th>
              <th className="px-4 py-3 font-semibold">ID</th>
              <th className="px-4 py-3 font-semibold">Koridor</th>
              <th className="px-4 py-3 font-semibold">Yoshi</th>
              <th className="px-4 py-3 font-semibold">Tavsif</th>
              <th className="px-4 py-3 font-semibold" />
            </tr>
          </thead>
          <tbody className="divide-y divide-muted">
            {items.busy ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                  <Spinner />
                </td>
              </tr>
            ) : (items.data ?? []).length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                  <Inbox size={18} className="mx-auto mb-2 text-slate-400" />
                  Navbat bo'sh
                </td>
              </tr>
            ) : (
              (items.data ?? []).map((item) => (
                <tr key={`${item.item_type}-${item.item_id}`} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-secondary-foreground">{item.item_type}</td>
                  <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{item.item_id}</td>
                  <td className="px-4 py-3 text-secondary-foreground">{item.corridor ?? "-"}</td>
                  <td className="px-4 py-3 text-secondary-foreground">{item.age_minutes} daq</td>
                  <td className="px-4 py-3 text-secondary-foreground">{item.summary}</td>
                  <td className="px-4 py-3">
                    {onOpenItem ? (
                      <button
                        type="button"
                        onClick={() => onOpenItem(item)}
                        className="el-press inline-flex h-8 items-center rounded-[10px] border border-border bg-card px-3 text-xs font-semibold text-secondary-foreground"
                      >
                        Ochish
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// --- disputes -----------------------------------------------------------------------------------------------

function DisputeRow({ dispute, canDecide, onDone }: { dispute: DisputeDTO; canDecide: boolean; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState("service_confirmed");
  const [cashOutcome, setCashOutcome] = useState<"" | "paid" | "unpaid">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run(command: "start-review" | "resolve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await disputeCommand(dispute.id, command, {
        expected_version: dispute.version,
        resolution_code: command === "resolve" ? (resolution as never) : null,
        resolution_text: note.trim() || null,
        reason: command === "reject" ? note.trim() || null : null,
        cash_outcome: cashOutcome ? (cashOutcome as never) : null,
      });
      setOpen(false);
      onDone();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{dispute.id}</td>
        <td className="px-4 py-3 text-secondary-foreground">{dispute.type}</td>
        <td className="px-4 py-3">
          <span className="inline-flex rounded-full border border-border bg-slate-50 px-2.5 py-1 text-xs font-semibold text-secondary-foreground">
            {DISPUTE_STATUS_LABEL[dispute.status] ?? dispute.status}
          </span>
        </td>
        <td className="px-4 py-3 text-secondary-foreground">{formatDateTime(dispute.created_at)}</td>
        <td className="px-4 py-3 text-secondary-foreground">
          {dispute.escalated ? <span className="font-semibold text-warning">eskalatsiya</span> : "-"}
        </td>
        <td className="px-4 py-3">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="el-press inline-flex h-8 items-center rounded-[10px] border border-border bg-card px-3 text-xs font-semibold text-secondary-foreground"
          >
            {open ? "Yopish" : "Ko'rish"}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-3">
              <p className="text-sm text-secondary-foreground">{dispute.description}</p>
              <ErrorLine error={error} />
              <label className="grid gap-1 text-sm font-medium text-secondary-foreground">
                Izoh / qaror matni
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  className="h-20 rounded-[10px] border border-border bg-card px-3 py-2 text-sm"
                />
              </label>
              <div className="flex flex-wrap items-end gap-3">
                <button
                  type="button"
                  disabled={busy || !["open"].includes(dispute.status)}
                  onClick={() => void run("start-review")}
                  className="el-press inline-flex h-9 items-center rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground disabled:opacity-50"
                >
                  Ko'rikka olish
                </button>
                {canDecide ? (
                  <>
                    <label className="grid gap-1 text-xs font-medium text-secondary-foreground">
                      Qaror kodi
                      <select
                        value={resolution}
                        onChange={(event) => setResolution(event.target.value)}
                        className="h-9 rounded-[10px] border border-border bg-card px-2 text-sm"
                      >
                        {RESOLUTION_CODES.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="grid gap-1 text-xs font-medium text-secondary-foreground">
                      Naqd natijasi (to'lov nizosida majburiy)
                      <select
                        value={cashOutcome}
                        onChange={(event) => setCashOutcome(event.target.value as "" | "paid" | "unpaid")}
                        className="h-9 rounded-[10px] border border-border bg-card px-2 text-sm"
                      >
                        <option value="">-</option>
                        <option value="paid">To'langan</option>
                        <option value="unpaid">To'lanmagan</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void run("resolve")}
                      className="el-press inline-flex h-9 items-center rounded-[10px] border border-primary bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50"
                    >
                      Hal qilish
                    </button>
                    <button
                      type="button"
                      disabled={busy || !note.trim()}
                      onClick={() => void run("reject")}
                      className="el-press inline-flex h-9 items-center rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 text-sm font-semibold text-destructive disabled:opacity-50"
                    >
                      Rad etish
                    </button>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Nizo qarorini admin yoki super admin qabul qiladi; siz ko'rikka olib, izoh yozasiz.
                  </p>
                )}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function AdminDisputesV2Panel({ focusId }: { focusId?: string | null } = {}) {
  const [onlyOpen, setOnlyOpen] = useState(!focusId);
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const disputes = useLoader<DisputeDTO[]>(
    () => listDisputes({ status: onlyOpen ? "open" : undefined, limit: 50 }),
    [onlyOpen],
  );
  const rows = (disputes.data ?? []).filter((dispute) => !focusId || dispute.id === focusId);
  const canDecide = Boolean(caps.data?.capabilities?.includes("ops.dispute_decide" as never));

  return (
    <section className="grid gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Nizolar (v2)</h2>
          <p className="text-sm text-muted-foreground">
            {canDecide ? "Siz nizo qarorini qabul qila olasiz." : "Operator ko'rikka oladi va izoh yozadi (qaror - admin+)."}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {focusId ? <span className="font-mono text-xs text-muted-foreground">{focusId}</span> : null}
          <label className="flex items-center gap-2 text-sm text-secondary-foreground">
            <input type="checkbox" checked={onlyOpen} onChange={(event) => setOnlyOpen(event.target.checked)} />
            Faqat ochiqlar
          </label>
        </div>
      </header>

      <ErrorLine error={disputes.error} />
      <div className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-semibold">ID</th>
              <th className="px-4 py-3 font-semibold">Turi</th>
              <th className="px-4 py-3 font-semibold">Holati</th>
              <th className="px-4 py-3 font-semibold">Ochilgan</th>
              <th className="px-4 py-3 font-semibold">Eskalatsiya</th>
              <th className="px-4 py-3 font-semibold" />
            </tr>
          </thead>
          <tbody className="divide-y divide-muted">
            {disputes.busy ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center">
                  <Spinner />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                  Nizo yo'q
                </td>
              </tr>
            ) : (
              rows.map((dispute) => (
                <DisputeRow key={dispute.id} dispute={dispute} canDecide={canDecide} onDone={disputes.reload} />
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// --- tickets and trust reviews -------------------------------------------------------------------------------

const TICKET_STATUS_LABEL: Record<string, string> = {
  open: "Ochiq",
  acknowledged: "Qabul qilindi",
  resolved: "Hal qilindi",
};

const TRUST_STATUS_LABEL: Record<string, string> = {
  open: "Ochiq",
  under_review: "Ko'rikda",
  dismissed: "Rad etilgan",
  actioned: "Chora ko'rilgan",
};

const TRUST_SIGNAL_LABEL: Record<string, string> = {
  contact_filter_strikes: "Aloqa filtri strike'lari",
  quick_cancel_after_chat: "Chatdan keyin tez bekor qilish",
  repeated_pair_cancellations: "Bir juftlikning takroriy bekor qilishlari",
};

const TRUST_DECISION_LABEL: Record<string, string> = {
  no_violation: "Qoidabuzarlik yo'q",
  warning_issued: "Ogohlantirish berildi",
  escalated_to_admin: "Adminga yuborildi",
};

/**
 * S17. Acknowledging promises no response time (§16, Q87); resolving needs a written note. Both need
 * `ops.trust_review`; without it the row is read-only.
 */
function TicketRow({ ticket, canAct, onDone }: { ticket: SupportTicketAdminDTO; canAct: boolean; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");

  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{ticket.id}</td>
        <td className="px-4 py-3">
          {ticket.kind === "sos" ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-destructive/25 bg-destructive/10 px-2.5 py-1 text-xs font-semibold text-destructive">
              <AlertTriangle size={12} /> SOS{(ticket.press_count ?? 1) > 1 ? ` × ${ticket.press_count}` : ""}
            </span>
          ) : (
            "murojaat"
          )}
        </td>
        <td className="px-4 py-3 text-secondary-foreground">{TICKET_STATUS_LABEL[ticket.status] ?? ticket.status}</td>
        <td className="px-4 py-3 text-secondary-foreground">{ticket.message}</td>
        <td className="px-4 py-3 text-secondary-foreground">{formatDateTime(ticket.created_at)}</td>
        <td className="px-4 py-3">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="el-press inline-flex h-8 items-center rounded-[10px] border border-border bg-card px-3 text-xs font-semibold text-secondary-foreground"
          >
            {open ? "Yopish" : "Ko'rish"}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-3 text-sm">
              <p className="text-secondary-foreground">
                Foydalanuvchi: <span className="font-mono text-xs">{ticket.user_id}</span>
                {ticket.booking_id ? (
                  <>
                    {" "}
                    · bron: <span className="font-mono text-xs">{ticket.booking_id}</span>
                  </>
                ) : null}
                {ticket.trip_id ? (
                  <>
                    {" "}
                    · safar: <span className="font-mono text-xs">{ticket.trip_id}</span>
                  </>
                ) : null}
              </p>
              {ticket.live ? (
                <p className="text-xs text-muted-foreground">
                  Oxirgi joylashuv yangiligi: {ticket.live.freshness}
                  {ticket.live.last_captured_at ? ` (${formatDateTime(ticket.live.last_captured_at)})` : ""}
                </p>
              ) : null}
              {!canAct ? (
                <p className="text-muted-foreground">Murojaatni qayta ishlash sizning rolingizda yo'q.</p>
              ) : ticket.status === "resolved" ? null : (
                <>
                  <label className="grid gap-1 font-medium text-secondary-foreground">
                    Hal qilish izohi (hal qilishda majburiy)
                    <textarea
                      aria-label="Murojaat izohi"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      className="h-20 rounded-[10px] border border-border bg-card px-3 py-2 text-sm"
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {ticket.status === "open" ? (
                      <ConfirmButton
                        label="Qabul qilish"
                        question="Murojaat qabul qilindi deb belgilanadi (javob vaqti va'da qilinmaydi). Davom etasizmi?"
                        onConfirm={async () => {
                          await ticketCommand(ticket.id, "acknowledge", {
                            expected_version: ticket.version,
                            note: note.trim() || null,
                          });
                          onDone();
                        }}
                      />
                    ) : null}
                    <ConfirmButton
                      label="Hal qilish"
                      tone="primary"
                      disabled={!note.trim()}
                      question="Murojaat hal qilindi deb yopiladi. Davom etasizmi?"
                      onConfirm={async () => {
                        await ticketCommand(ticket.id, "resolve", { expected_version: ticket.version, note: note.trim() });
                        setNote("");
                        onDone();
                      }}
                    />
                  </div>
                </>
              )}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * S19 (Q45). No automatic penalty: the operator starts a review, dismisses (no violation) or acts (a warning to
 * the user, or an escalation to an admin who decides eligibility separately). Every command needs a note.
 */
function TrustReviewRow({ review, canAct, onDone }: { review: TrustReviewDTO; canAct: boolean; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<"warning_issued" | "escalated_to_admin">("warning_issued");
  const terminal = review.status === "dismissed" || review.status === "actioned";

  async function run(command: "start-review" | "dismiss" | "action") {
    await trustReviewCommand(review.id, command, {
      expected_version: review.version,
      note: note.trim(),
      decision: command === "action" ? decision : command === "dismiss" ? "no_violation" : null,
    });
    setNote("");
    onDone();
  }

  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{review.id}</td>
        <td className="px-4 py-3 text-secondary-foreground">{TRUST_SIGNAL_LABEL[review.signal_type] ?? review.signal_type}</td>
        <td className="px-4 py-3 text-secondary-foreground">{review.signal_count}</td>
        <td className="px-4 py-3 text-secondary-foreground">{TRUST_STATUS_LABEL[review.status] ?? review.status}</td>
        <td className="px-4 py-3 text-secondary-foreground">{formatDateTime(review.last_signal_at)}</td>
        <td className="px-4 py-3">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="el-press inline-flex h-8 items-center rounded-[10px] border border-border bg-card px-3 text-xs font-semibold text-secondary-foreground"
          >
            {open ? "Yopish" : "Ko'rish"}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-3 text-sm">
              <p className="text-secondary-foreground">
                Foydalanuvchi: <span className="font-mono text-xs">{review.subject_user_id}</span>
                {review.decision ? ` · qaror: ${TRUST_DECISION_LABEL[review.decision] ?? review.decision}` : ""}
              </p>
              <p className="text-xs text-muted-foreground">
                Dalil:{" "}
                {Object.entries(review.evidence ?? {})
                  .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`)
                  .join(" · ") || "-"}
              </p>
              {!canAct ? (
                <p className="text-muted-foreground">Ishonch navbatini qayta ishlash sizning rolingizda yo'q.</p>
              ) : terminal ? null : (
                <>
                  <label className="grid gap-1 font-medium text-secondary-foreground">
                    Izoh (majburiy, audit jurnaliga yoziladi)
                    <textarea
                      aria-label="Ko'rik izohi"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      className="h-20 rounded-[10px] border border-border bg-card px-3 py-2 text-sm"
                    />
                  </label>
                  <div className="flex flex-wrap items-end gap-2">
                    {review.status === "open" ? (
                      <ConfirmButton
                        label="Ko'rikka olish"
                        disabled={!note.trim()}
                        question="Signal ko'rikka olinadi. Davom etasizmi?"
                        onConfirm={() => run("start-review")}
                      />
                    ) : null}
                    <ConfirmButton
                      label="Qoidabuzarlik yo'q"
                      disabled={!note.trim()}
                      question="Signal qoidabuzarliksiz yopiladi. Davom etasizmi?"
                      onConfirm={() => run("dismiss")}
                    />
                    <label className="grid gap-1 text-xs font-medium text-secondary-foreground">
                      Chora
                      <select
                        aria-label="Chora"
                        value={decision}
                        onChange={(event) => setDecision(event.target.value as "warning_issued" | "escalated_to_admin")}
                        className="h-9 rounded-[10px] border border-border bg-card px-2 text-sm"
                      >
                        <option value="warning_issued">Ogohlantirish berish</option>
                        <option value="escalated_to_admin">Adminga yuborish</option>
                      </select>
                    </label>
                    <ConfirmButton
                      label="Chora ko'rish"
                      tone="primary"
                      disabled={!note.trim()}
                      question={
                        decision === "warning_issued"
                          ? "Foydalanuvchiga ogohlantirish yuboriladi (jarima yo'q). Davom etasizmi?"
                          : "Signal adminga yuboriladi; blok qarorini admin alohida qabul qiladi. Davom etasizmi?"
                      }
                      onConfirm={() => run("action")}
                    />
                  </div>
                </>
              )}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function AdminSupportPanel() {
  const [reviewStatus, setReviewStatus] = useState("open");
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const tickets = useLoader<SupportTicketAdminDTO[]>(() => listSupportTicketsAdmin({ limit: 50 }), []);
  const reviews = useLoader<TrustReviewDTO[]>(
    () => listTrustReviews({ status: reviewStatus || undefined, limit: 50 }),
    [reviewStatus],
  );
  const canAct = Boolean(caps.data?.capabilities?.includes("ops.trust_review" as never));

  return (
    <section className="grid gap-6">
      <div className="grid gap-3">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-foreground">Murojaatlar va SOS</h2>
          <button
            type="button"
            onClick={tickets.reload}
            className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground"
          >
            <RefreshCw size={14} /> Yangilash
          </button>
        </header>
        <p className="text-sm text-muted-foreground">
          Qabul qilish javob vaqtini va'da qilmaydi; support faqat ilova ichida (Q87).
        </p>
        <ErrorLine error={caps.error} />
        <ErrorLine error={tickets.error} />
        <div className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
          <table className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-semibold">ID</th>
                <th className="px-4 py-3 font-semibold">Turi</th>
                <th className="px-4 py-3 font-semibold">Holati</th>
                <th className="px-4 py-3 font-semibold">Xabar</th>
                <th className="px-4 py-3 font-semibold">Kelgan</th>
                <th className="px-4 py-3 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {tickets.busy ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center">
                    <Spinner />
                  </td>
                </tr>
              ) : (tickets.data ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    Murojaat yo'q
                  </td>
                </tr>
              ) : (
                (tickets.data ?? []).map((ticket) => (
                  <TicketRow key={ticket.id} ticket={ticket} canAct={canAct} onDone={tickets.reload} />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-3">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-foreground">Ishonch navbati (Q45)</h2>
            <p className="text-sm text-muted-foreground">Avtomatik jazo yo'q: operator ko'rib chiqadi.</p>
          </div>
          <select
            aria-label="Ishonch navbati holati"
            value={reviewStatus}
            onChange={(event) => setReviewStatus(event.target.value)}
            className="h-9 rounded-[10px] border border-border bg-card px-3 text-sm"
          >
            <option value="">Barchasi</option>
            {Object.entries(TRUST_STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </header>
        <ErrorLine error={reviews.error} />
        <div className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
          <table className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-semibold">ID</th>
                <th className="px-4 py-3 font-semibold">Signal</th>
                <th className="px-4 py-3 font-semibold">Soni</th>
                <th className="px-4 py-3 font-semibold">Holati</th>
                <th className="px-4 py-3 font-semibold">Oxirgi signal</th>
                <th className="px-4 py-3 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {reviews.busy ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center">
                    <Spinner />
                  </td>
                </tr>
              ) : (reviews.data ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    Navbat bo'sh
                  </td>
                </tr>
              ) : (
                (reviews.data ?? []).map((review) => (
                  <TrustReviewRow key={review.id} review={review} canAct={canAct} onDone={reviews.reload} />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

// --- metrics ------------------------------------------------------------------------------------------------

const KPI_LABEL: Record<string, string> = {
  listings_published: "E'lon qilingan so'rovlar",
  listing_to_booking: "E'londan bronga",
  offer_within_target: "30 daqiqada taklif",
  booking_completion: "Bron bajarilishi",
  driver_fault_cancel: "Haydovchi aybli bekor qilish",
  repeat_client: "Takroriy mijoz",
};

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

/** Latency indicators are seconds, ratios are percentages: the unit follows the indicator's own name (§19.3). */
function sloValue(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return name.endsWith("_seconds") ? `${value.toFixed(2)} s` : percent(value);
}

export function AdminMetricsPanel() {
  const kpi = useLoader<KpiDTO>(() => loadKpi({}), []);
  const slo = useLoader<SloDTO>(() => loadSlo({}), []);

  return (
    <section className="grid gap-6">
      <div className="grid gap-3">
        <header className="flex items-center gap-2">
          <BarChart3 size={18} className="text-slate-400" />
          <h2 className="text-lg font-bold text-foreground">KPI</h2>
          {kpi.data ? (
            <span className="text-sm text-muted-foreground">
              {kpi.data.date_from} - {kpi.data.date_to}
            </span>
          ) : null}
        </header>
        <ErrorLine error={kpi.error} />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(kpi.data?.metrics ?? []).map((metric) => (
            <div key={metric.metric} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
              <p className="text-sm font-medium text-muted-foreground">{KPI_LABEL[metric.metric] ?? metric.metric}</p>
              <p className="mt-2 text-2xl font-bold text-foreground">
                {metric.value === null || metric.value === undefined ? `${metric.numerator}` : percent(metric.value)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {metric.numerator} / {metric.denominator}
                {metric.target ? ` · maqsad ${percent(metric.target)}` : ""}
              </p>
              {metric.small_sample ? (
                <p className="mt-2 rounded bg-warning/14 px-2 py-1 text-xs font-medium text-warning">
                  Kichik namuna - foizga tayanmang
                </p>
              ) : null}
            </div>
          ))}
          {kpi.busy ? <Spinner /> : null}
          {!kpi.busy && (kpi.data?.metrics ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">Hozircha hisoblangan kun yo'q (worker kunlik hisoblaydi).</p>
          ) : null}
        </div>
        {(kpi.data?.missing_metrics ?? []).length ? (
          <p className="rounded-[10px] border border-border bg-slate-50 px-3 py-2 text-xs text-secondary-foreground">
            O'lchanmaydigan ko'rsatkichlar (nol sifatida ko'rsatilmaydi): {(kpi.data?.missing_metrics ?? []).join(", ")}
          </p>
        ) : null}
      </div>

      <div className="grid gap-3">
        <h2 className="text-lg font-bold text-foreground">SLO</h2>
        <ErrorLine error={slo.error} />
        <div className="grid gap-3 md:grid-cols-3">
          {(slo.data?.indicators ?? []).map((indicator) => (
            <div key={indicator.name} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
              <p className="text-sm font-medium text-muted-foreground">{indicator.name}</p>
              <p className="mt-2 text-2xl font-bold text-foreground">
                {indicator.measured ? sloValue(indicator.name, indicator.value) : "o'lchanmaydi"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {indicator.measured ? `n = ${indicator.sample_size}` : indicator.note}
                {indicator.target ? ` · maqsad ${sloValue(indicator.name, indicator.target)}` : ""}
              </p>
            </div>
          ))}
          {slo.busy ? <Spinner /> : null}
        </div>
      </div>
    </section>
  );
}


// --- O8 legacy (v1) orders, read-only -------------------------------------------------------------------------

const LEGACY_STATUSES = [
  "draft", "published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed", "paid_manual",
  "cancelled", "disputed",
];

function legacyFlagLabel(flag: string): string {
  if (flag === "unknown_time") return "vaqt oynasi saqlanmagan";
  if (flag === "unknown_dimensions") return "yuk o'lchamlari saqlanmagan";
  return flag;
}

/**
 * A10b's wave 5 projection (O8) in the operator panel. Read-only on purpose: a v1 order is finished in v1 (Q4),
 * so this screen has no action at all and says why, instead of offering a button the server refuses with
 * 409 LEGACY_OBJECT_READ_ONLY. The commission column is what v1 *calculated*, never money that was collected
 * (§9.2, §18.2), and the flags name what v1 never stored instead of showing an invented value.
 */
export function AdminLegacyOrdersPanel() {
  const [status, setStatus] = useState<string>("");
  const orders = useLoader<LegacyOrderViewDTO[]>(
    () => listLegacyOrders({ status: status || undefined, limit: 50 }),
    [status],
  );

  return (
    <section className="grid gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <Archive size={18} className="text-slate-400" />
        <h2 className="text-lg font-bold text-foreground">Legacy (v1) buyurtmalar</h2>
        <span className="rounded bg-background px-2 py-1 text-xs font-medium text-secondary-foreground">faqat o'qish</span>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded-[10px] border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">Barcha holatlar</option>
          {LEGACY_STATUSES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {orders.busy ? <Spinner /> : null}
      </header>
      <p className="text-sm text-muted-foreground">
        Bu buyurtmalar v1 lifecycle'ida yakunlanadi. v2 ularni faqat o'qiydi: bu yerda holat o'zgartirish yoki
        haydovchi tayinlash imkoni yo'q - kerak bo'lsa v1 "Buyurtmalar" bo'limidan foydalaning.
      </p>
      <ErrorLine error={orders.error} />
      <div className="overflow-x-auto rounded-[12px] border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Buyurtma</th>
              <th className="px-3 py-2">Holat</th>
              <th className="px-3 py-2">Yo'nalish</th>
              <th className="px-3 py-2">Yakuniy narx</th>
              <th className="px-3 py-2">Hisoblangan komissiya</th>
              <th className="px-3 py-2">Ma'lumot yo'q</th>
              <th className="px-3 py-2">Yaratilgan</th>
            </tr>
          </thead>
          <tbody>
            {(orders.data ?? []).map((order) => (
              <tr key={order.legacy_order_number} className="border-t border-muted">
                <td className="px-3 py-2 font-medium text-foreground">{order.legacy_order_number}</td>
                <td className="px-3 py-2 text-secondary-foreground">{order.status}</td>
                <td className="px-3 py-2 text-secondary-foreground">{order.route_summary}</td>
                <td className="px-3 py-2 text-secondary-foreground">{formatMinor(order.final_price_minor, order.currency)}</td>
                <td className="px-3 py-2 text-secondary-foreground">
                  {formatMinor(order.legacy_calculated_fee_minor, order.currency)}
                  <span className="ml-1 text-xs text-slate-400">(undirilmagan)</span>
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {(order.flags ?? []).map(legacyFlagLabel).join(", ") || "-"}
                </td>
                <td className="px-3 py-2 text-muted-foreground">{formatDateTime(order.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!orders.busy && (orders.data ?? []).length === 0 ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">Bu filtrda v1 buyurtma yo'q.</p>
        ) : null}
      </div>
    </section>
  );
}
