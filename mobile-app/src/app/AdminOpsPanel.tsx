/**
 * A9 operator screens inside the admin panel: the v2 queues, disputes, support/trust and the KPI/SLO view.
 *
 * What the panel promises is what the server actually allows (spec §9):
 * * decision buttons appear only for the capabilities `/me/capabilities` really returns - an operator reviews a
 *   dispute and writes a note, admin+ decides it (Q78); a finance user sees only the finance-review queue;
 * * a queue row that is a v2 booking opens the v2 booking drawer - never the v1 orders search, where a v2 id cannot
 *   match anything (DESIGN-ADMIN-DIFF 4.5);
 * * closing a payment dispute asks for the cash outcome, because the server refuses to leave a contested receipt
 *   unanswered; resolve and reject are confirmed first;
 * * disputes are an internal staff record: users no longer open them, they write in the booking chat (Q141);
 * * KPI show the count pair, mark a small sample and list the metrics this system does not measure at all;
 * * an SLO indicator that is not measured says so instead of showing a number (§19.3, §20.4).
 */
import { useState } from "react";

import {
  OPS_QUEUES,
  capabilities,
  disputeCommand,
  kpi as loadKpi,
  listCorridors,
  listDisputes,
  listLegacyOrders,
  listTrustReviews,
  opsQueue,
  slo as loadSlo,
  ticketCommand,
  trustReviewCommand,
  type CapabilitiesDTO,
  type CorridorDTO,
  type DisputeDTO,
  type KpiDTO,
  type LegacyOrderViewDTO,
  type OpsQueue,
  type OpsQueueItemDTO,
  type SloDTO,
  type TrustReviewDTO,
} from "../api/v2/ops.api";
import { listSupportTicketsAdmin, type SupportTicketAdminDTO } from "../api/v2/admin-trust.api";
import { opsQueueSummary, queueCountText, type OpsQueueCountDTO } from "../api/v2/admin-market.api";
import { translate, translateDynamic, type MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import { formatDateTime, formatMinor } from "../utils/v2Format";
import {
  Badge,
  Btn,
  Chips,
  ErrorLine,
  Field,
  INPUT,
  Kv,
  Note,
  PanelHead,
  Spinner,
  TEXTAREA,
  ageText,
  countText,
  hasCap,
  useLoader,
  type BadgeTone,
} from "./adminMarketKit";
import { AdminBookingDrawer, ConfirmButton, serviceStatusLabel } from "./AdminTrustPanel";
import { AlertTriangle, Archive, BarChart3, Inbox, RefreshCw } from "./ui/icons";

function has(caps: CapabilitiesDTO | null | undefined, capability: string): boolean {
  return hasCap(caps as { capabilities?: readonly string[] } | null, capability);
}

export const QUEUE_KEY: Record<string, MessageKey> = {
  awaiting_confirmation: "admin.queue.awaiting_confirmation",
  no_show_review: "admin.queue.no_show_review",
  custody_case: "admin.queue.custody_case",
  hold_escalation: "admin.queue.hold_escalation",
  finance_review: "admin.queue.finance_review",
  dispute: "admin.queue.dispute",
  support_ticket: "admin.queue.support_ticket",
  trust_review: "admin.queue.trust_review",
};

const BOOKING_QUEUES = new Set(["awaiting_confirmation", "no_show_review", "custody_case", "hold_escalation", "finance_review"]);

/**
 * The queue chips a role may open (§2, 4.2). Booking queues need `ops.booking_command`; finance holds only
 * `finance.fee_finalize` and so sees the finance-review queue alone; the trust queues need their own capability.
 */
export function visibleOpsQueues(caps: CapabilitiesDTO | null | undefined): OpsQueue[] {
  return OPS_QUEUES.filter((queue) => {
    if (queue === "finance_review") return has(caps, "ops.booking_command") || has(caps, "finance.fee_finalize");
    if (BOOKING_QUEUES.has(queue)) return has(caps, "ops.booking_command");
    if (queue === "dispute") return has(caps, "ops.dispute_resolve") || has(caps, "ops.dispute_decide");
    return has(caps, "ops.trust_review");
  });
}

/** "Bron (pochta)" / "Bron (yo'lovchi)"; the service comes from `service_type` (contract §4.2) or the summary's first word. */
export function queueObjectLabel(item: OpsQueueItemDTO): string {
  if (item.item_type === "booking") {
    const service = (item as { service_type?: string | null }).service_type ?? item.summary.split(" ")[0];
    if (service === "parcel") return translate("admin.queues.bookingParcel");
    if (service === "passenger") return translate("admin.queues.bookingPassenger");
    return translate("admin.mk.booking");
  }
  return translateDynamic(`admin.queues.object.${item.item_type}`) ?? item.item_type;
}

/**
 * The server's queue summary is a terse English line (`parcel awaiting_pickup x1`, `payment open escalated`). Known
 * words are put into the reader's language; anything unknown stays as the server wrote it.
 */
export function queueSummaryText(item: OpsQueueItemDTO): string {
  const words = item.summary.split(" ").filter(Boolean);
  if (words.length === 0) return "";
  const out = words.map((word) => {
    const quantity = /^x(\d+)$/.exec(word);
    if (quantity) return `× ${quantity[1]}`;
    return (
      translateDynamic(`admin.queues.word.${word}`) ??
      translateDynamic(`status.${word}`) ??
      translateDynamic(`admin.disputes2.type.${word}`) ??
      translateDynamic(`admin.support.signal.${word}`) ??
      word
    );
  });
  return out.join(" · ");
}

// --- queues -------------------------------------------------------------------------------------------------

export function AdminOpsQueuesPanel({ onOpenItem }: { onOpenItem?: (item: OpsQueueItemDTO) => void } = {}) {
  const t = useT();
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const visible = caps.data ? visibleOpsQueues(caps.data) : [];
  const [picked, setPicked] = useState<OpsQueue | null>(null);
  const queue: OpsQueue | null = picked && visible.includes(picked) ? picked : visible.includes("finance_review") ? "finance_review" : visible[0] ?? null;
  const items = useLoader<OpsQueueItemDTO[]>(() => opsQueue(queue as OpsQueue, { limit: 50 }), [queue], Boolean(queue));
  const summary = useLoader<OpsQueueCountDTO[]>(() => opsQueueSummary(), [], Boolean(caps.data));
  // Queue rows carry the corridor id; the design shows its name. Unknown ids stay as they are.
  const corridors = useLoader<CorridorDTO[]>(() => listCorridors(), []);
  const corridorName = (id: string | null | undefined) =>
    !id ? "-" : (corridors.data ?? []).find((corridor) => corridor.id === id)?.name ?? id;
  const [drawer, setDrawer] = useState<OpsQueueItemDTO | null>(null);

  function count(value: OpsQueue): string | null {
    const exact = queueCountText((summary.data ?? []).find((row) => row.queue === value));
    if (exact !== null) return exact;
    // Fallback while /summary is not deployed: the rows loaded for the selected queue, "50+" at the cap (3.5).
    return value === queue && items.data && !items.busy ? countText(items.data.length, 50) : null;
  }

  function open(item: OpsQueueItemDTO) {
    if (item.item_type === "booking") setDrawer(item);
    else onOpenItem?.(item);
  }

  const canOpen = (item: OpsQueueItemDTO) => item.item_type === "booking" || Boolean(onOpenItem);

  return (
    <section className="grid gap-4">
      <PanelHead
        title={t("admin.queues.title")}
        sub={t("admin.queues.subtitle")}
        actions={
          <Btn
            onClick={() => {
              items.reload();
              summary.reload();
            }}
          >
            <RefreshCw size={14} /> {t("support.refresh")}
          </Btn>
        }
      />
      <ErrorLine error={caps.error} />
      {caps.busy ? (
        <Spinner />
      ) : queue ? (
        <>
          <Chips
            label={t("admin.queues.picker")}
            value={queue}
            onChange={setPicked}
            items={visible.map((value) => ({ value, label: t(QUEUE_KEY[value]), count: count(value) }))}
          />
          <ErrorLine error={items.error} />
          <div className="overflow-x-auto rounded-[12px] border border-border bg-card shadow-sm">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-semibold">{t("admin.queues.colObject")}</th>
                  <th className="px-4 py-3 font-semibold">{t("admin.mk.id")}</th>
                  <th className="px-4 py-3 font-semibold">{t("admin.mk.corridor")}</th>
                  <th className="px-4 py-3 font-semibold">{t("admin.queues.colAge")}</th>
                  <th className="px-4 py-3 font-semibold">{t("admin.mk.description")}</th>
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
                      {t("admin.queues.empty")}
                    </td>
                  </tr>
                ) : (
                  (items.data ?? []).map((item) => (
                    <tr key={`${item.item_type}-${item.item_id}`} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-medium text-secondary-foreground">{queueObjectLabel(item)}</td>
                      <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{item.item_id}</td>
                      <td className="px-4 py-3 text-secondary-foreground">{corridorName(item.corridor)}</td>
                      <td className="px-4 py-3 text-secondary-foreground">{ageText(item.age_minutes)}</td>
                      <td className="px-4 py-3 text-secondary-foreground">{queueSummaryText(item)}</td>
                      <td className="px-4 py-3 text-right">
                        {canOpen(item) ? <Btn onClick={() => open(item)}>{t("admin.mk.open")}</Btn> : null}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <Note>{t("admin.queues.noQueues")}</Note>
      )}
      {drawer ? (
        <AdminBookingDrawer
          bookingId={drawer.item_id}
          summary={queueSummaryText(drawer)}
          queue={drawer.queue}
          onClose={() => setDrawer(null)}
          onChanged={() => {
            items.reload();
            summary.reload();
          }}
        />
      ) : null}
    </section>
  );
}

// --- disputes -----------------------------------------------------------------------------------------------

const DISPUTE_STATUS_TONE: Record<string, BadgeTone> = { open: "warn", under_review: "blue", resolved: "ok", rejected: "gray" };

const RESOLUTION_CODES = [
  "service_confirmed",
  "service_not_provided",
  "paid_confirmed",
  "unpaid_confirmed",
  "commission_adjusted",
  "no_action",
  "other",
] as const;

function resolutionLabel(code: string): string {
  return translateDynamic(`admin.disputes2.code.${code}`) ?? code;
}

function disputeStatusLabel(status: string): string {
  return translateDynamic(`admin.disputes2.status.${status}`) ?? status;
}

function disputeTypeLabel(type: string): string {
  return translateDynamic(`admin.disputes2.type.${type}`) ?? type;
}

function DisputeRow({ dispute, canDecide, onDone }: { dispute: DisputeDTO; canDecide: boolean; onDone: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState<string>("service_confirmed");
  const [cashOutcome, setCashOutcome] = useState<"" | "paid" | "unpaid">("");
  const decided = dispute.status === "resolved" || dispute.status === "rejected";

  async function run(command: "start-review" | "resolve" | "reject") {
    await disputeCommand(dispute.id, command, {
      expected_version: dispute.version,
      resolution_code: command === "resolve" ? (resolution as never) : null,
      resolution_text: note.trim() || null,
      reason: command === "reject" ? note.trim() || null : null,
      cash_outcome: cashOutcome ? (cashOutcome as never) : null,
    });
    setOpen(false);
    onDone();
  }

  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{dispute.id}</td>
        <td className="px-4 py-3 text-secondary-foreground">{disputeTypeLabel(dispute.type)}</td>
        <td className="px-4 py-3">
          <Badge tone={DISPUTE_STATUS_TONE[dispute.status] ?? "gray"}>{disputeStatusLabel(dispute.status)}</Badge>
        </td>
        <td className="px-4 py-3 text-secondary-foreground">{formatDateTime(dispute.created_at)}</td>
        <td className="px-4 py-3 text-secondary-foreground">
          {dispute.escalated ? <Badge tone="err">{t("admin.disputes2.escalated")}</Badge> : "-"}
        </td>
        <td className="px-4 py-3 text-right">
          <Btn onClick={() => setOpen((value) => !value)}>{open ? t("common.close") : t("admin.mk.view")}</Btn>
        </td>
      </tr>
      {open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-3">
              <Kv cols={1} rows={[[t("admin.mk.description"), dispute.description]]} />
              {decided ? null : (
                <>
                  <Field label={t("admin.disputes2.note")}>
                    <textarea aria-label={t("admin.disputes2.note")} value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA} />
                  </Field>
                  {canDecide ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label={t("admin.disputes2.code")}>
                        <select aria-label={t("admin.disputes2.code")} value={resolution} onChange={(event) => setResolution(event.target.value)} className={INPUT}>
                          {RESOLUTION_CODES.map((value) => (
                            <option key={value} value={value}>
                              {resolutionLabel(value)}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label={`${t("admin.disputes2.cash")}${dispute.type === "payment" ? " *" : ""}`}>
                        <select
                          aria-label={t("admin.disputes2.cash")}
                          value={cashOutcome}
                          onChange={(event) => setCashOutcome(event.target.value as "" | "paid" | "unpaid")}
                          className={INPUT}
                        >
                          <option value="">-</option>
                          <option value="paid">{t("admin.disputes2.cash.paid")}</option>
                          <option value="unpaid">{t("admin.disputes2.cash.unpaid")}</option>
                        </select>
                      </Field>
                    </div>
                  ) : null}
                  <div className="flex flex-wrap items-start gap-2">
                    {dispute.status === "open" ? (
                      <ConfirmButton
                        label={t("admin.mk.takeReview")}
                        tone="soft"
                        question={t("admin.disputes2.confirmReview")}
                        onConfirm={() => run("start-review")}
                      />
                    ) : null}
                    {canDecide ? (
                      <>
                        <ConfirmButton
                          label={t("admin.disputes2.resolve")}
                          tone="primary"
                          disabled={dispute.type === "payment" && !cashOutcome}
                          question={t("admin.disputes2.confirmResolve", { code: resolutionLabel(resolution) })}
                          onConfirm={() => run("resolve")}
                        />
                        <ConfirmButton
                          label={t("admin.mk.reject")}
                          tone="danger"
                          disabled={!note.trim()}
                          question={t("admin.disputes2.confirmReject")}
                          onConfirm={() => run("reject")}
                        />
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">{t("admin.disputes2.operatorHint")}</p>
                    )}
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

export function AdminDisputesV2Panel({ focusId }: { focusId?: string | null } = {}) {
  const t = useT();
  const [onlyOpen, setOnlyOpen] = useState(!focusId);
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const disputes = useLoader<DisputeDTO[]>(
    () => listDisputes({ status: onlyOpen ? "open" : undefined, limit: 50 }),
    [onlyOpen],
  );
  const rows = (disputes.data ?? []).filter((dispute) => !focusId || dispute.id === focusId);
  const canDecide = has(caps.data, "ops.dispute_decide");

  return (
    <section className="grid gap-4">
      <PanelHead
        title={t("admin.disputes2.title")}
        sub={canDecide ? t("admin.disputes2.subtitleDecider") : t("admin.disputes2.subtitleOperator")}
        actions={
          <>
            {focusId ? <span className="font-mono text-xs text-muted-foreground">{focusId}</span> : null}
            <label className="flex items-center gap-2 text-sm text-secondary-foreground">
              <input type="checkbox" checked={onlyOpen} onChange={(event) => setOnlyOpen(event.target.checked)} />
              {t("admin.disputes2.onlyOpen")}
            </label>
            <Btn onClick={disputes.reload}>
              <RefreshCw size={14} /> {t("support.refresh")}
            </Btn>
          </>
        }
      />

      <ErrorLine error={disputes.error} />
      <div className="overflow-x-auto rounded-[12px] border border-border bg-card shadow-sm">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-semibold">{t("admin.mk.id")}</th>
              <th className="px-4 py-3 font-semibold">{t("admin.mk.type")}</th>
              <th className="px-4 py-3 font-semibold">{t("admin.mk.statusOf")}</th>
              <th className="px-4 py-3 font-semibold">{t("admin.disputes2.colOpened")}</th>
              <th className="px-4 py-3 font-semibold">{t("admin.disputes2.colEscalation")}</th>
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
                  {t("admin.disputes2.empty")}
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

const TICKET_STATUS_TONE: Record<string, BadgeTone> = { open: "warn", acknowledged: "blue", resolved: "ok" };
const TRUST_STATUS_TONE: Record<string, BadgeTone> = { open: "warn", under_review: "blue", dismissed: "gray", actioned: "err" };

function ticketStatusLabel(status: string): string {
  return translateDynamic(`admin.support.status.${status}`) ?? status;
}

function trustStatusLabel(status: string): string {
  return translateDynamic(`admin.support.trustStatus.${status}`) ?? status;
}

function trustSignalLabel(signal: string): string {
  return translateDynamic(`admin.support.signal.${signal}`) ?? signal;
}

function trustDecisionLabel(decision: string): string {
  return translateDynamic(`admin.support.decision.${decision}`) ?? decision;
}

/** "Yangi (≤ 30 s)" / "Kechikmoqda (48 s)" - the freshness in words, with the age when the server gave one (9.2). */
export function ticketFreshnessText(live: SupportTicketAdminDTO["live"]): string {
  if (!live) return "—";
  const seconds = live.last_captured_at ? Math.max(0, Math.round((Date.now() - new Date(live.last_captured_at).getTime()) / 1000)) : null;
  if (live.freshness === "delayed" && seconds !== null) return translate("admin.support.freshnessLagging", { seconds });
  return translateDynamic(`admin.trust.freshness.${live.freshness}`) ?? live.freshness;
}

/**
 * S17. Acknowledging promises no response time (§16, Q87); resolving needs a written note. Both need
 * `ops.trust_review`; without it the row is read-only.
 */
function TicketRow({ ticket, canAct, onDone }: { ticket: SupportTicketAdminDTO; canAct: boolean; onDone: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");

  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-4 py-3 font-mono text-xs text-secondary-foreground">{ticket.id}</td>
        <td className="px-4 py-3">
          {ticket.kind === "sos" ? (
            <Badge tone="err">
              <AlertTriangle size={12} className="mr-1" />
              {(ticket.press_count ?? 1) > 1 ? t("admin.support.sosCount", { count: ticket.press_count ?? 1 }) : "SOS"}
            </Badge>
          ) : (
            t("admin.support.kindTicket")
          )}
        </td>
        <td className="px-4 py-3">
          <Badge tone={TICKET_STATUS_TONE[ticket.status] ?? "gray"}>{ticketStatusLabel(ticket.status)}</Badge>
        </td>
        <td className="px-4 py-3 text-secondary-foreground">{ticket.message}</td>
        <td className="px-4 py-3 text-secondary-foreground">{formatDateTime(ticket.created_at)}</td>
        <td className="px-4 py-3 text-right">
          <Btn onClick={() => setOpen((value) => !value)}>{open ? t("common.close") : t("admin.mk.view")}</Btn>
        </td>
      </tr>
      {open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-3 text-sm">
              <Kv
                cols={4}
                rows={[
                  [t("admin.mk.user"), <span key="u" className="font-mono text-xs">{ticket.user_id}</span>],
                  [t("admin.mk.booking"), ticket.booking_id ? <span key="b" className="font-mono text-xs">{ticket.booking_id}</span> : "—"],
                  [t("admin.mk.trip"), ticket.trip_id ? <span key="t" className="font-mono text-xs">{ticket.trip_id}</span> : "—"],
                  [t("admin.support.lastFreshness"), ticketFreshnessText(ticket.live)],
                ]}
              />
              {!canAct ? (
                <p className="text-muted-foreground">{t("admin.support.noRoleTicket")}</p>
              ) : ticket.status === "resolved" ? null : (
                <>
                  <Field label={t("admin.support.resolveNote")}>
                    <textarea
                      aria-label={t("admin.support.ticketNoteAria")}
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      className={TEXTAREA}
                    />
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    {ticket.status === "open" ? (
                      <ConfirmButton
                        label={t("admin.support.acknowledge")}
                        tone="soft"
                        question={t("admin.support.acknowledgeConfirm")}
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
                      label={t("admin.disputes2.resolve")}
                      tone="primary"
                      disabled={!note.trim()}
                      question={t("admin.support.resolveConfirm")}
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
  const t = useT();
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
        <td className="px-4 py-3 text-secondary-foreground">{trustSignalLabel(review.signal_type)}</td>
        <td className="px-4 py-3 text-secondary-foreground">{review.signal_count}</td>
        <td className="px-4 py-3">
          <Badge tone={TRUST_STATUS_TONE[review.status] ?? "gray"}>{trustStatusLabel(review.status)}</Badge>
        </td>
        <td className="px-4 py-3 text-secondary-foreground">{formatDateTime(review.last_signal_at)}</td>
        <td className="px-4 py-3 text-right">
          <Btn onClick={() => setOpen((value) => !value)}>{open ? t("common.close") : t("admin.mk.view")}</Btn>
        </td>
      </tr>
      {open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-3 text-sm">
              <p className="text-secondary-foreground">
                {t("admin.mk.user")}: <span className="font-mono text-xs">{review.subject_user_id}</span>
                {review.decision ? ` · ${t("admin.support.decisionLine", { decision: trustDecisionLabel(review.decision) })}` : ""}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("admin.trust.fraudEvidence", {
                  refs:
                    Object.entries(review.evidence ?? {})
                      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`)
                      .join(" · ") || "-",
                })}
              </p>
              {!canAct ? (
                <p className="text-muted-foreground">{t("admin.support.noRoleTrust")}</p>
              ) : terminal ? null : (
                <>
                  <Field label={t("admin.mk.noteRequiredAudit")}>
                    <textarea
                      aria-label={t("admin.support.reviewNoteAria")}
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      className={TEXTAREA}
                    />
                  </Field>
                  <div className="flex flex-wrap items-end gap-2">
                    {review.status === "open" ? (
                      <ConfirmButton
                        label={t("admin.mk.takeReview")}
                        tone="soft"
                        disabled={!note.trim()}
                        question={t("admin.support.reviewConfirm")}
                        onConfirm={() => run("start-review")}
                      />
                    ) : null}
                    <ConfirmButton
                      label={t("admin.support.noViolation")}
                      disabled={!note.trim()}
                      question={t("admin.support.dismissConfirm")}
                      onConfirm={() => run("dismiss")}
                    />
                    <Field label={t("admin.support.action")}>
                      <select
                        aria-label={t("admin.support.action")}
                        value={decision}
                        onChange={(event) => setDecision(event.target.value as "warning_issued" | "escalated_to_admin")}
                        className={INPUT}
                      >
                        <option value="warning_issued">{t("admin.support.issueWarning")}</option>
                        <option value="escalated_to_admin">{t("admin.support.escalate")}</option>
                      </select>
                    </Field>
                    <ConfirmButton
                      label={t("admin.support.takeAction")}
                      tone="danger"
                      disabled={!note.trim()}
                      question={decision === "warning_issued" ? t("admin.support.warnConfirm") : t("admin.support.escalateConfirm")}
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

const TRUST_STATUSES = ["open", "under_review", "dismissed", "actioned"] as const;

export function AdminSupportPanel() {
  const t = useT();
  const [reviewStatus, setReviewStatus] = useState("open");
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const tickets = useLoader<SupportTicketAdminDTO[]>(() => listSupportTicketsAdmin({ limit: 50 }), []);
  const reviews = useLoader<TrustReviewDTO[]>(
    () => listTrustReviews({ status: reviewStatus || undefined, limit: 50 }),
    [reviewStatus],
  );
  const canAct = has(caps.data, "ops.trust_review");

  return (
    <section className="grid gap-6">
      <div className="grid gap-3">
        <PanelHead
          title={t("admin.support.title")}
          sub={t("admin.support.subtitle")}
          actions={
            <Btn onClick={tickets.reload}>
              <RefreshCw size={14} /> {t("support.refresh")}
            </Btn>
          }
        />
        <ErrorLine error={caps.error} />
        <ErrorLine error={tickets.error} />
        <div className="overflow-x-auto rounded-[12px] border border-border bg-card shadow-sm">
          <table className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-semibold">{t("admin.mk.id")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.mk.type")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.mk.statusOf")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.support.colMessage")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.support.colReceived")}</th>
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
                    {t("admin.support.noTickets")}
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
        <PanelHead
          title={t("admin.support.trustTitle")}
          sub={t("admin.support.trustSubtitle")}
          actions={
            <select
              aria-label={t("admin.support.trustStatusAria")}
              value={reviewStatus}
              onChange={(event) => setReviewStatus(event.target.value)}
              className={INPUT}
            >
              <option value="">{t("admin.mk.all")}</option>
              {TRUST_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {trustStatusLabel(value)}
                </option>
              ))}
            </select>
          }
        />
        <ErrorLine error={reviews.error} />
        <div className="overflow-x-auto rounded-[12px] border border-border bg-card shadow-sm">
          <table className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-semibold">{t("admin.mk.id")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.support.colSignal")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.mk.count")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.mk.statusOf")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.support.colLastSignal")}</th>
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
                    {t("admin.queues.empty")}
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

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

/** Latency indicators are seconds, ratios are percentages: the unit follows the indicator's own name (§19.3). */
function sloValue(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return name.endsWith("_seconds") ? `${value.toFixed(2)} s` : percent(value);
}

function kpiLabel(metric: string): string {
  return translateDynamic(`admin.metrics.kpi.${metric}`) ?? metric;
}

function sloLabel(name: string): string {
  return translateDynamic(`admin.metrics.slo.${name}`) ?? name;
}

type Period = "7" | "30" | "90";

/** `YYYY-MM-DD` in Tashkent for `days` days back (inclusive of today), the range the KPI endpoints take. */
export function periodRange(days: number, now: Date = new Date()): { from: string; to: string } {
  const tashkent = (date: Date) => new Date(date.getTime() + 5 * 3600 * 1000).toISOString().slice(0, 10);
  const from = new Date(now.getTime() - (days - 1) * 24 * 3600 * 1000);
  return { from: tashkent(from), to: tashkent(now) };
}

export function AdminMetricsPanel() {
  const t = useT();
  const [period, setPeriod] = useState<Period>("7");
  const [corridorId, setCorridorId] = useState("");
  const corridors = useLoader<CorridorDTO[]>(() => listCorridors(), []);
  const range = periodRange(Number(period));
  const kpi = useLoader<KpiDTO>(
    () => loadKpi({ from: range.from, to: range.to, corridor_id: corridorId || undefined }),
    [period, corridorId],
  );
  const slo = useLoader<SloDTO>(() => loadSlo({ from: range.from, to: range.to }), [period]);

  return (
    <section className="grid gap-6">
      <PanelHead
        title={t("admin.metrics.title")}
        sub={t("admin.metrics.subtitle")}
        actions={
          <Btn
            onClick={() => {
              kpi.reload();
              slo.reload();
            }}
          >
            <RefreshCw size={14} /> {t("support.refresh")}
          </Btn>
        }
      />
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("admin.metrics.period")}>
          <select aria-label={t("admin.metrics.period")} value={period} onChange={(event) => setPeriod(event.target.value as Period)} className={INPUT}>
            <option value="7">{t("admin.metrics.last7")}</option>
            <option value="30">{t("admin.metrics.last30")}</option>
            <option value="90">{t("admin.metrics.last90")}</option>
          </select>
        </Field>
        <Field label={t("admin.mk.corridor")}>
          <select aria-label={t("admin.mk.corridor")} value={corridorId} onChange={(event) => setCorridorId(event.target.value)} className={INPUT}>
            <option value="">{t("admin.mk.all")}</option>
            {(corridors.data ?? []).map((corridor) => (
              <option key={corridor.id} value={corridor.id}>
                {corridor.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="grid gap-3">
        <header className="flex items-center gap-2">
          <BarChart3 size={18} className="text-slate-400" />
          <h3 className="text-base font-bold text-foreground">KPI</h3>
          {kpi.data ? (
            <span className="text-sm text-muted-foreground">
              {kpi.data.date_from} - {kpi.data.date_to}
            </span>
          ) : null}
        </header>
        <ErrorLine error={kpi.error} />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(kpi.data?.metrics ?? []).map((metric) => {
            const value = metric.value;
            const target = metric.target;
            // NICE 21.2: tint against the target; the cancel ratio is better when it is lower.
            const lowerIsBetter = metric.metric === "driver_fault_cancel";
            const tone =
              value === null || value === undefined || !target || metric.small_sample
                ? "text-foreground"
                : (lowerIsBetter ? value <= target : value >= target)
                  ? "text-success"
                  : "text-warning";
            return (
              <div key={metric.metric} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
                <p className="text-sm font-medium text-muted-foreground">{kpiLabel(metric.metric)}</p>
                <p className={`mt-2 text-2xl font-bold ${tone}`}>
                  {value === null || value === undefined ? `${metric.numerator}` : percent(value)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {target
                    ? t("admin.metrics.ratioTarget", { num: metric.numerator, den: metric.denominator, target: percent(target) })
                    : `${metric.numerator} / ${metric.denominator}`}
                </p>
                {metric.small_sample ? (
                  <p className="mt-2 rounded bg-warning/14 px-2 py-1 text-xs font-medium text-warning">{t("admin.metrics.smallSample")}</p>
                ) : null}
              </div>
            );
          })}
          {kpi.busy ? <Spinner /> : null}
          {!kpi.busy && (kpi.data?.metrics ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("admin.metrics.noDays")}</p>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground">{t("admin.metrics.chartBlocked")}</p>
        {(kpi.data?.missing_metrics ?? []).length ? (
          <Note>{t("admin.metrics.unmeasured", { list: (kpi.data?.missing_metrics ?? []).map(kpiLabel).join(", ") })}</Note>
        ) : null}
      </div>

      <div className="grid gap-3">
        <h3 className="text-base font-bold text-foreground">SLO</h3>
        <ErrorLine error={slo.error} />
        <div className="overflow-x-auto rounded-[12px] border border-border bg-card shadow-sm">
          <table className="w-full min-w-[560px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-semibold">SLO</th>
                <th className="px-4 py-3 font-semibold">{t("admin.metrics.colValue")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.metrics.colN")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.metrics.colTarget")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {slo.busy ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center">
                    <Spinner />
                  </td>
                </tr>
              ) : (
                (slo.data?.indicators ?? []).map((indicator) => (
                  <tr key={indicator.name}>
                    <td className="px-4 py-3 font-medium text-foreground">{sloLabel(indicator.name)}</td>
                    <td className="px-4 py-3 text-secondary-foreground">
                      {indicator.measured ? sloValue(indicator.name, indicator.value) : t("admin.metrics.notMeasured")}
                      {!indicator.measured && indicator.note ? <span className="block text-xs text-muted-foreground">{indicator.note}</span> : null}
                    </td>
                    <td className="px-4 py-3 text-secondary-foreground">{indicator.measured ? `n = ${indicator.sample_size}` : "—"}</td>
                    <td className="px-4 py-3 text-secondary-foreground">{indicator.target ? sloValue(indicator.name, indicator.target) : "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
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

const LEGACY_TONE: Record<string, BadgeTone> = {
  confirmed: "ok",
  paid_manual: "ok",
  delivered: "ok",
  cancelled: "err",
  disputed: "warn",
  in_transit: "blue",
  picked_up: "blue",
  accepted: "blue",
};

function legacyStatusLabel(status: string): string {
  return translateDynamic(`admin.legacy.status.${status}`) ?? serviceStatusLabel(status);
}

function legacyFlagLabel(flag: string): string {
  if (flag === "unknown_time") return translate("admin.legacy.unknownTime");
  if (flag === "unknown_dimensions") return translate("admin.legacy.unknownDims");
  return flag;
}

/**
 * A10b's wave 5 projection (O8) in the operator panel. Read-only on purpose: a v1 order is finished in v1 (Q4),
 * so this screen has no action at all and says why, instead of offering a button the server refuses with
 * 409 LEGACY_OBJECT_READ_ONLY. The commission column is what v1 *calculated*, never money that was collected
 * (§9.2, §18.2), and the flags name what v1 never stored instead of showing an invented value.
 */
export function AdminLegacyOrdersPanel() {
  const t = useT();
  const [status, setStatus] = useState<string>("");
  const orders = useLoader<LegacyOrderViewDTO[]>(
    () => listLegacyOrders({ status: status || undefined, limit: 50 }),
    [status],
  );

  return (
    <section className="grid gap-4">
      <PanelHead
        title={t("admin.legacy.title")}
        sub={t("admin.legacy.subtitle")}
        actions={
          <>
            <Archive size={18} className="text-slate-400" />
            <Badge>{t("admin.legacy.readOnly")}</Badge>
          </>
        }
      />
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("admin.mk.status")}>
          <select aria-label={t("admin.mk.status")} value={status} onChange={(event) => setStatus(event.target.value)} className={INPUT}>
            <option value="">{t("admin.mk.all")}</option>
            {LEGACY_STATUSES.map((value) => (
              <option key={value} value={value}>
                {legacyStatusLabel(value)}
              </option>
            ))}
          </select>
        </Field>
        {orders.busy ? <Spinner /> : null}
      </div>
      <ErrorLine error={orders.error} />
      <div className="overflow-x-auto rounded-[12px] border border-border bg-card">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2">{t("admin.legacy.colOrder")}</th>
              <th className="px-3 py-2">{t("admin.mk.status")}</th>
              <th className="px-3 py-2">{t("admin.mk.route")}</th>
              <th className="px-3 py-2">{t("admin.legacy.colFinalPrice")}</th>
              <th className="px-3 py-2">{t("admin.legacy.colCommission")}</th>
              <th className="px-3 py-2">{t("admin.legacy.colMissing")}</th>
              <th className="px-3 py-2">{t("admin.mk.created")}</th>
            </tr>
          </thead>
          <tbody>
            {(orders.data ?? []).map((order) => (
              <tr key={order.legacy_order_number} className="border-t border-muted">
                <td className="px-3 py-2 font-medium text-foreground">{order.legacy_order_number}</td>
                <td className="px-3 py-2">
                  <Badge tone={LEGACY_TONE[order.status] ?? "gray"}>{legacyStatusLabel(order.status)}</Badge>
                </td>
                <td className="px-3 py-2 text-secondary-foreground">{order.route_summary}</td>
                <td className="px-3 py-2 text-secondary-foreground">{formatMinor(order.final_price_minor, order.currency)}</td>
                <td className="px-3 py-2 text-secondary-foreground">{formatMinor(order.legacy_calculated_fee_minor, order.currency)}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {(order.flags ?? []).map(legacyFlagLabel).join(", ") || "-"}
                </td>
                <td className="px-3 py-2 text-muted-foreground">{formatDateTime(order.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!orders.busy && (orders.data ?? []).length === 0 ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">{t("admin.legacy.empty")}</p>
        ) : null}
      </div>
    </section>
  );
}
