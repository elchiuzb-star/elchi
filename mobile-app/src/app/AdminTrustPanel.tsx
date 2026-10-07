/**
 * Staff trust & operations actions (A12 S9-S20, B12/B13, N10, K9, O7) inside the admin panel.
 *
 * What the panel promises is what the server allows:
 * * a button appears only for a capability `/me/capabilities` really returns - an operator does not see "cancel"
 *   (`ops.booking_cancel`, admin+, Q10) and finance alone sees "finalize fee" (Q17); a finance user sees only the
 *   finance-review queue and none of the trust tabs it cannot act on; anything else the server refuses is shown
 *   with the server's own reason, never hidden behind a pretend success;
 * * every command is confirmed first and carries one idempotency key per confirmed action (ADR-0005); a money
 *   command the server wants proven (ADR-0021 step-up) asks for the authenticator code and is replayed with the
 *   same key;
 * * a cancellation names its cause or leaves it undetermined for review - it is never assumed (Q129);
 * * fraud signals and reports are questions for a human: nothing here blocks, fines or down-ranks anybody (§17.3);
 * * the proposal thread is read-only (Q100) and hiding a booking chat message needs a written reason;
 * * contacts appear only where the API returned them; the tracking view is audited and shows the freshness of the
 *   last trusted point, never a "GPS active" claim (Q86, §10.5);
 * * a listing on behalf of someone needs the real owner and a consent reference (§20.2) - the server stores the
 *   operator as `created_by_operator`.
 */
import { useEffect, useState } from "react";

import {
  ADMIN_BOOKING_QUEUES,
  adminBookingCommand,
  adminBookingMessages,
  adminProposalMessages,
  adminTripTracking,
  createListingOnBehalf,
  hideChatMessage,
  listAdminBookings,
  listFraudSignals,
  listReports,
  reviewFraudSignal,
  reviewReport,
  userStrikes,
  type AdminBookingDTO,
  type AdminBookingQueue,
  type AdminListingDTO,
  type ChatMessageAdminDTO,
  type FraudSignalDTO,
  type ListingOnBehalfBody,
  type OperatorBookingCommand,
  type ReportDTO,
  type TripTrackingAdminDTO,
  type UserStrikesDTO,
} from "../api/v2/admin-trust.api";
import {
  SEARCH_MIN,
  searchAdminBookings,
  searchAdminTrips,
  searchAdminUsers,
  staffBooking,
} from "../api/v2/admin-market.api";
import { newIdempotencyKey, type ApiWarning, type Schemas } from "../api/v2/http";
import { capabilities, type CapabilitiesDTO } from "../api/v2/ops.api";
import { parcelCategories, type ParcelCategoryDTO } from "../api/v2/marketplace.api";
import { adminDistricts, adminRegions, type DistrictDTO, type RegionDTO } from "../api/v2/admin-platform.api";
import { translate, translateDynamic, type MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import { ApiError } from "../types/api";
import { formatDateTime, formatMinor } from "../utils/v2Format";
import { v2ErrorMessage, warningMessage } from "../utils/v2Errors";
import {
  Badge,
  Btn,
  Chips,
  Empty,
  ErrorLine,
  Field,
  INPUT,
  Kv,
  LookupField,
  Note,
  Spinner,
  TEXTAREA,
  countText,
  hasCap,
  useLoader,
  type BadgeTone,
  type BtnTone,
  type LookupOption,
} from "./adminMarketKit";
import { RefreshCw, X } from "./ui/icons";
import { isStepUpCancelled, useStepUp, type StepUpController } from "./useStepUp";
import { VehicleMap } from "./v2/LiveTrackingMap";

type FaultSide = Schemas["FaultSide"];
type ProofKind = Schemas["ProofKind"];

export type TrustTab = "bookings" | "reports" | "fraud" | "strikes" | "chat" | "tracking" | "on_behalf";

const TABS: Array<[TrustTab, MessageKey]> = [
  ["bookings", "admin.trust.tab.bookings"],
  ["reports", "admin.trust.tab.reports"],
  ["fraud", "admin.trust.tab.fraud"],
  ["strikes", "admin.trust.tab.strikes"],
  ["chat", "admin.trust.tab.chat"],
  ["tracking", "admin.trust.tab.tracking"],
  ["on_behalf", "admin.trust.tab.onBehalf"],
];

/**
 * Which tabs a role can work in (§2 matrix, 5a.7). Finance holds `ops.view` and `finance.fee_finalize` only, so the
 * report, fraud, strike, chat and on-behalf tabs - all `ops.trust_review` / `ops.booking_command` work - are hidden.
 */
export function visibleTrustTabs(caps: CapabilitiesDTO | null): TrustTab[] {
  return TABS.map(([tab]) => tab).filter((tab) => {
    if (tab === "bookings") return has(caps, "ops.booking_command") || has(caps, "finance.fee_finalize");
    if (tab === "tracking") return has(caps, "ops.view");
    if (tab === "on_behalf") return has(caps, "ops.booking_command");
    return has(caps, "ops.trust_review");
  });
}

/** The booking queues a role may open: finance sees only the finance-review queue (§2, 5a.7). */
export function visibleBookingQueues(caps: CapabilitiesDTO | null): AdminBookingQueue[] {
  if (has(caps, "ops.booking_command")) return ADMIN_BOOKING_QUEUES;
  if (has(caps, "finance.fee_finalize")) return ["finance_review"];
  return [];
}

// --- small shared pieces ------------------------------------------------------------------------------------------

function has(caps: CapabilitiesDTO | null, capability: string): boolean {
  return hasCap(caps as { capabilities?: readonly string[] } | null, capability);
}

/**
 * A command button that asks first. The idempotency key is minted when the confirmation opens and kept for a
 * retry of the same confirmation, so a double click or a network retry cannot act twice. When the work goes through
 * `useStepUp` and the person closes the code prompt, the confirmation closes quietly - nothing was executed.
 */
export function ConfirmButton(props: {
  label: string;
  question: string;
  onConfirm: (idempotencyKey: string) => Promise<void>;
  disabled?: boolean;
  tone?: BtnTone;
}) {
  const t = useT();
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function confirm() {
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      await props.onConfirm(key);
      setKey(null);
    } catch (cause) {
      if (isStepUpCancelled(cause)) setKey(null);
      else setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (!key) {
    return (
      <Btn tone={props.tone} disabled={props.disabled} onClick={() => setKey(newIdempotencyKey())}>
        {props.label}
      </Btn>
    );
  }
  return (
    <div className="grid w-full gap-2 rounded-[12px] border border-warning/30 bg-warning/8 p-3">
      <p className="text-sm font-medium text-foreground">{props.question}</p>
      <ErrorLine error={error} />
      <div className="flex flex-wrap gap-2">
        <Btn tone={props.tone === "danger" ? "danger" : "primary"} disabled={busy} onClick={() => void confirm()}>
          {busy ? <Spinner /> : null}
          {error ? t("common.retry") : t("admin.mk.yesRun")}
        </Btn>
        <Btn
          disabled={busy}
          onClick={() => {
            setKey(null);
            setError(null);
          }}
        >
          {t("common.cancel")}
        </Btn>
      </div>
    </div>
  );
}

function evidenceText(evidence: Record<string, number | string | string[]>): string {
  const parts = Object.entries(evidence ?? {}).map(([key, value]) =>
    Array.isArray(value) ? `${key}: ${value.join(", ")}` : `${key}: ${value}`,
  );
  return parts.join(" · ") || "-";
}

/** The searches behind the lookup fields. Module-level so their identity never changes between renders. */
async function lookupUsers(query: string): Promise<LookupOption[]> {
  const rows = await searchAdminUsers(query, { limit: 10 });
  return rows.map((row) => ({
    id: row.id,
    title: row.full_name || row.phone || row.id,
    sub: [translateDynamic(`admin.mk.role.${row.role}`) ?? row.role, row.phone].filter(Boolean).join(" · "),
  }));
}

/** The code part of `bkg_7q2x` / `trp_...` must be at least 4 characters (contract §5.3/§5.4); shorter is not sent. */
function codePart(query: string, prefix: string): string {
  return query.toLowerCase().startsWith(prefix) ? query.slice(prefix.length) : query;
}

async function lookupBookings(query: string): Promise<LookupOption[]> {
  if (codePart(query, "bkg_").length < SEARCH_MIN.bookings) return [];
  const rows = await searchAdminBookings(query, 10);
  return rows.map((row) => ({
    id: row.id,
    title: `${placeText(row.pickup)} → ${placeText(row.dropoff)}`,
    sub: [serviceLabel(row.service_type), formatDateTime(row.created_at)].join(" · "),
  }));
}

async function lookupTrips(query: string): Promise<LookupOption[]> {
  if (!query.startsWith("usr_") && codePart(query, "trp_").length < SEARCH_MIN.trips) return [];
  const rows = await searchAdminTrips(query, 10);
  return rows.map((row) => ({
    id: row.id,
    title: [row.driver_display_name, row.planned_start_at ? formatDateTime(row.planned_start_at) : null].filter(Boolean).join(" · ") || row.id,
    sub: translateDynamic(`admin.trust.tripStatus.${row.status}`) ?? row.status,
  }));
}

// --- bookings (B12/B13) -----------------------------------------------------------------------------------------

export const BOOKING_QUEUE_KEY: Record<AdminBookingQueue, MessageKey> = {
  awaiting_confirmation: "admin.queue.awaiting_confirmation",
  no_show_review: "admin.queue.no_show_review",
  custody_case: "admin.queue.custody_case",
  hold_escalation: "admin.queue.hold_escalation",
  finance_review: "admin.queue.finance_review",
};

const COMMAND_KEY: Record<OperatorBookingCommand, MessageKey> = {
  confirm_no_show: "admin.trust.cmd.confirm_no_show",
  reject_no_show: "admin.trust.cmd.reject_no_show",
  complete_with_evidence: "admin.trust.cmd.complete_with_evidence",
  drop_off: "admin.trust.cmd.drop_off",
  require_return: "admin.trust.cmd.require_return",
  return_to_sender: "admin.trust.cmd.return_to_sender",
  resolve_custody_case: "admin.trust.cmd.resolve_custody_case",
  finalize_fee: "admin.trust.cmd.finalize_fee",
  cancel: "admin.trust.cmd.cancel",
  reissue_proof_code: "admin.trust.cmd.reissue_proof_code",
  mark_delivered: "admin.trust.cmd.mark_delivered",
};

/** The server's `OPERATOR_COMMAND_CAPABILITY`, mirrored only to hide what would be refused anyway. */
export const COMMAND_CAPABILITY: Record<OperatorBookingCommand, string> = {
  confirm_no_show: "ops.booking_command",
  reject_no_show: "ops.booking_command",
  complete_with_evidence: "ops.booking_command",
  drop_off: "ops.booking_command",
  require_return: "ops.booking_command",
  return_to_sender: "ops.booking_command",
  resolve_custody_case: "ops.booking_command",
  reissue_proof_code: "ops.booking_command",
  mark_delivered: "ops.booking_command",
  finalize_fee: "finance.fee_finalize",
  cancel: "ops.booking_cancel",
};

const FAULT_KEY: Array<["" | FaultSide, MessageKey]> = [
  ["", "admin.trust.fault.undetermined"],
  ["client", "admin.trust.fault.client"],
  ["driver", "admin.trust.fault.driver"],
  ["platform", "admin.trust.fault.platform"],
  ["none", "admin.trust.fault.none"],
];

// ADR-0026 (Q139): only the passenger boarding code is still issued; parcel codes are retired.
const PROOF_KEY: Array<[ProofKind, MessageKey]> = [["boarding_code", "admin.trust.proof.boarding_code"]];

/** Which commands make sense for this booking right now. The server still has the last word. */
export function applicableCommands(booking: AdminBookingDTO): OperatorBookingCommand[] {
  const out: OperatorBookingCommand[] = [];
  if (booking.no_show_review?.status === "pending") out.push("confirm_no_show", "reject_no_show");
  out.push("complete_with_evidence");
  if (booking.service_type === "passenger") out.push("drop_off");
  // ADR-0026 (Q139): a parcel's outcome is recorded here - delivered (with a reason) or the return flow.
  if (booking.service_type === "parcel") out.push("mark_delivered", "require_return", "return_to_sender", "resolve_custody_case");
  if (booking.commission_status === "held") out.push("finalize_fee");
  if (booking.service_type === "passenger") out.push("reissue_proof_code");
  out.push("cancel");
  return out;
}

/**
 * A booking end as a place (ADR-0028: ELCHI is point A -> point B): the district and the address the person
 * marked.
 */
export function placeText(end: AdminBookingDTO["pickup"]): string {
  const district = end.point?.district;
  const districtName = typeof district === "string" ? district : district?.name_uz;
  const point = [districtName, end.point?.address].filter(Boolean).join(", ");
  return point || "-";
}

export function serviceLabel(service: string | null | undefined): string {
  if (service === "passenger") return translate("admin.mk.passenger");
  if (service === "parcel") return translate("admin.mk.parcel");
  return service ?? "-";
}

/** `status.*` holds the words the client app already uses for a booking's service status. */
export function serviceStatusLabel(status: string): string {
  return translateDynamic(`status.${status}`) ?? status;
}

const SERVICE_STATUS_TONE: Record<string, BadgeTone> = {
  awaiting_pickup: "warn",
  completed: "ok",
  delivered: "ok",
  cancelled: "err",
  no_show: "err",
  in_transit: "blue",
  picked_up: "blue",
  onboard: "blue",
};

export function commissionLabel(status: string): string {
  return translateDynamic(`admin.trust.commission.${status}`) ?? status;
}

const COMMISSION_TONE: Record<string, BadgeTone> = {
  held: "gray",
  captured: "ok",
  released: "blue",
  exempt: "gray",
  reversed: "warn",
  partially_reversed: "warn",
};

function sideLabel(side: string): string {
  return translateDynamic(`admin.trust.side.${side}`) ?? side;
}

function MessagesList(props: { messages: ChatMessageAdminDTO[]; canHide: boolean; onHidden?: () => void }) {
  const t = useT();
  if (props.messages.length === 0) return <Empty>{t("admin.trust.noMessages")}</Empty>;
  return (
    <ul className="grid gap-2">
      {props.messages.map((message) => (
        <MessageItem key={message.id} message={message} canHide={props.canHide} onHidden={props.onHidden} />
      ))}
    </ul>
  );
}

function MessageItem({ message, canHide, onHidden }: { message: ChatMessageAdminDTO; canHide: boolean; onHidden?: () => void }) {
  const t = useT();
  const [reason, setReason] = useState("");
  const hidden = message.moderation_status === "hidden_by_staff";
  const filtered = Object.entries(message.contact_filter_categories ?? {});
  return (
    <li className="grid gap-2 rounded-[10px] border border-border bg-card px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge>{sideLabel(message.author_side)}</Badge>
        <span className="font-mono">{message.author_user_id}</span>
        <span>{formatDateTime(message.created_at)}</span>
      </div>
      <p className="text-secondary-foreground">
        {message.text ?? (message.quick_reply_code ? t("admin.trust.quickReply", { code: message.quick_reply_code }) : "-")}
      </p>
      {hidden ? (
        <p className="text-xs font-semibold text-warning">
          {t("admin.trust.hiddenMessage", { category: filtered.map(([category]) => category).join(", ") || "-" })}
        </p>
      ) : filtered.length ? (
        <p className="text-xs text-muted-foreground">
          {t("admin.trust.filterMatch", { categories: filtered.map(([category, count]) => `${category} × ${count}`).join(", ") })}
        </p>
      ) : null}
      {canHide && !hidden && onHidden ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t("admin.trust.hideReason")}>
            <input value={reason} onChange={(event) => setReason(event.target.value)} className={INPUT} />
          </Field>
          <ConfirmButton
            label={t("admin.trust.hide")}
            tone="danger"
            disabled={reason.trim().length < 3}
            question={t("admin.trust.hideConfirm")}
            onConfirm={async (key) => {
              await hideChatMessage(message.id, { reason: reason.trim() }, key);
              setReason("");
              onHidden();
            }}
          />
        </div>
      ) : null}
    </li>
  );
}

function BookingMessages({ bookingId, canHide }: { bookingId: string; canHide: boolean }) {
  const t = useT();
  const messages = useLoader<ChatMessageAdminDTO[]>(() => adminBookingMessages(bookingId, { limit: 50 }), [bookingId]);
  return (
    <div className="grid gap-2">
      <div>
        <p className="text-sm font-semibold text-foreground">{t("admin.trust.chatTitle")}</p>
        <p className="text-xs text-muted-foreground">{t("admin.trust.chatAudited")}</p>
      </div>
      <ErrorLine error={messages.error} />
      {messages.busy ? <Spinner /> : <MessagesList messages={messages.data ?? []} canHide={canHide} onHidden={messages.reload} />}
    </div>
  );
}

function partyText(party: { display_name?: string | null; contact_phone?: string | null } | null | undefined, extra?: string | null): string {
  if (!party) return "—";
  return [party.display_name, party.contact_phone, extra].filter(Boolean).join(" · ") || "—";
}

function noShowText(booking: AdminBookingDTO): string {
  const review = booking.no_show_review;
  if (!review) return "—";
  const time = formatDateTime(review.reported_at);
  if (review.status === "pending") return translate("admin.trust.noShowPending", { time });
  return `${translateDynamic(`admin.trust.noShow.${review.status}`) ?? review.status} · ${time}`;
}

/** The booking's facts as the design's key-value grid (5a.3, 4.6). Names and phones only where the staff DTO has them. */
export function BookingFacts({ booking, compact = false }: { booking: AdminBookingDTO; compact?: boolean }) {
  const t = useT();
  const plate = booking.driver?.vehicle ? booking.driver.vehicle.plate_number ?? booking.driver.vehicle.plate_masked ?? null : null;
  const rows: Array<[string, string]> = [];
  if (!compact) {
    rows.push([t("admin.mk.pickupPlace"), placeText(booking.pickup)]);
    rows.push([t("admin.mk.dropoffPlace"), placeText(booking.dropoff)]);
    rows.push([t("admin.mk.trip"), booking.trip_id]);
  }
  rows.push([t("admin.mk.client"), partyText(booking.client)]);
  rows.push([t("admin.mk.driver"), partyText(booking.driver, plate)]);
  if (!compact || booking.no_show_review) rows.push([t("admin.trust.noShowReview"), noShowText(booking)]);
  rows.push([
    t("admin.trust.custody"),
    booking.custody_case
      ? `${translateDynamic(`admin.trust.custodyStatus.${booking.custody_case.status}`) ?? booking.custody_case.status} · ${booking.custody_case.reason_code}`
      : "—",
  ]);
  if (!compact) {
    rows.push([
      t("admin.trust.cancelled"),
      booking.cancelled
        ? [
            sideLabel(booking.cancelled.by_side),
            booking.cancelled.fault_side ? translate(FAULT_KEY.find(([value]) => value === booking.cancelled?.fault_side)?.[1] ?? "admin.trust.fault.undetermined") : t("admin.trust.faultUnknown"),
            formatDateTime(booking.cancelled.at),
          ].join(" · ")
        : "—",
    ]);
  }
  return <Kv rows={rows} cols={3} />;
}

/**
 * The command form for one booking (B13). Money commands go through `useStepUp`: `finalize_fee` needs a fresh MFA
 * proof once ADR-0021 is enforced (contract §3); the code is asked here and the command replayed with the same key.
 */
export function BookingDetail({
  booking,
  caps,
  onDone,
  showFacts = true,
  preferCommand,
}: {
  booking: AdminBookingDTO;
  caps: CapabilitiesDTO | null;
  onDone: () => void;
  showFacts?: boolean;
  /** Pre-selects this command when it is allowed (the finance-review queue opens on `finalize_fee`). */
  preferCommand?: OperatorBookingCommand;
}) {
  const t = useT();
  const stepUp: StepUpController = useStepUp();
  const allowed = applicableCommands(booking).filter((command) => has(caps, COMMAND_CAPABILITY[command]));
  const [command, setCommand] = useState<OperatorBookingCommand | "">(
    preferCommand && allowed.includes(preferCommand) ? preferCommand : allowed[0] ?? "",
  );
  const [reason, setReason] = useState("");
  const [fault, setFault] = useState<"" | FaultSide>("");
  const [proofKind, setProofKind] = useState<ProofKind>("boarding_code");
  const [feeMode, setFeeMode] = useState<"capture" | "release">("capture");
  const [evidence, setEvidence] = useState("");
  const [showChat, setShowChat] = useState(false);
  const [warnings, setWarnings] = useState<ApiWarning[]>([]);
  const canCancel = has(caps, "ops.booking_cancel");
  const canChat = has(caps, "ops.trust_review") || has(caps, "ops.booking_command");

  async function send(key: string) {
    if (!command) return;
    const body = {
      expected_version: booking.version,
      reason: reason.trim(),
      cancel_fault_side: command === "cancel" && fault ? fault : null,
      proof_kind: command === "reissue_proof_code" ? proofKind : null,
      fee_decision: command === "finalize_fee" ? { mode: feeMode } : null,
      evidence_file_ids:
        command === "complete_with_evidence"
          ? evidence.split(",").map((part) => part.trim()).filter(Boolean).slice(0, 10)
          : [],
    };
    const result = await stepUp.run(() => adminBookingCommand(booking.id, command, body, key));
    setWarnings(result.warnings);
    setReason("");
    onDone();
  }

  const commandLabel = command ? t(COMMAND_KEY[command]) : "";

  return (
    <div className="grid gap-3">
      {showFacts ? <BookingFacts booking={booking} /> : null}

      {warnings.length ? (
        <Note tone="warn">{warnings.map((warning) => warningMessage(warning.code)).join(" · ")}</Note>
      ) : null}

      {allowed.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("admin.trust.noCommands")}</p>
      ) : (
        <div className="grid gap-3 rounded-[12px] border border-border bg-card p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("admin.trust.command")}>
              <select
                aria-label={t("admin.trust.command")}
                value={command}
                onChange={(event) => setCommand(event.target.value as OperatorBookingCommand)}
                className={INPUT}
              >
                {allowed.map((value) => (
                  <option key={value} value={value}>
                    {t(COMMAND_KEY[value])}
                  </option>
                ))}
              </select>
            </Field>
            {command === "cancel" ? (
              <Field label={t("admin.trust.faultSide")}>
                <select
                  aria-label={t("admin.trust.faultSideShort")}
                  value={fault}
                  onChange={(event) => setFault(event.target.value as "" | FaultSide)}
                  className={INPUT}
                >
                  {FAULT_KEY.map(([value, key]) => (
                    <option key={value || "undetermined"} value={value}>
                      {t(key)}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {command === "reissue_proof_code" ? (
              <Field label={t("admin.trust.proofKind")}>
                <select
                  aria-label={t("admin.trust.proofKind")}
                  value={proofKind}
                  onChange={(event) => setProofKind(event.target.value as ProofKind)}
                  className={INPUT}
                >
                  {PROOF_KEY.map(([value, key]) => (
                    <option key={value} value={value}>
                      {t(key)}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {command === "finalize_fee" ? (
              <Field label={t("admin.trust.feeDecision")}>
                <select
                  aria-label={t("admin.trust.feeDecision")}
                  value={feeMode}
                  onChange={(event) => setFeeMode(event.target.value as "capture" | "release")}
                  className={INPUT}
                >
                  <option value="capture">{t("admin.trust.fee.capture")}</option>
                  <option value="release">{t("admin.trust.fee.release")}</option>
                </select>
              </Field>
            ) : null}
            {command === "complete_with_evidence" ? (
              <Field label={t("admin.trust.evidence")}>
                <input value={evidence} onChange={(event) => setEvidence(event.target.value)} className={INPUT} />
              </Field>
            ) : null}
          </div>
          <Field label={t("admin.mk.reasonRequiredAudit")}>
            <textarea aria-label={t("common.reason")} value={reason} onChange={(event) => setReason(event.target.value)} className={TEXTAREA} />
          </Field>
          {stepUp.prompt}
          {command ? (
            <ConfirmButton
              label={commandLabel}
              tone={command === "cancel" ? "danger" : "primary"}
              disabled={!reason.trim() || stepUp.waiting}
              question={
                command === "cancel"
                  ? t("admin.trust.confirmCancel", { fault: t(FAULT_KEY.find(([value]) => value === fault)?.[1] ?? "admin.trust.fault.undetermined") })
                  : t("admin.trust.confirmCommand", { command: commandLabel })
              }
              onConfirm={send}
            />
          ) : null}
        </div>
      )}
      {!canCancel && has(caps, "ops.booking_command") ? <p className="text-xs text-muted-foreground">{t("admin.trust.cancelAdminOnly")}</p> : null}

      {canChat ? (
        <div className="grid gap-2">
          <Btn onClick={() => setShowChat((value) => !value)}>{showChat ? t("admin.trust.chatHide") : t("admin.trust.chatTitle")}</Btn>
          {showChat ? <BookingMessages bookingId={booking.id} canHide={has(caps, "ops.trust_review")} /> : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The `bk` drawer (DESIGN-ADMIN-DIFF 4.5/4.6): one v2 booking opened from a queue, with its facts, the command form,
 * the MFA block when the server asks for it, and the booking chat. Loaded by id through the staff booking view.
 */
export function AdminBookingDrawer(props: {
  bookingId: string;
  summary?: string | null;
  /** The queue the booking was opened from; `finance_review` pre-selects «Komissiyani yakunlash». */
  queue?: string | null;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const t = useT();
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const booking = useLoader<AdminBookingDTO>(() => staffBooking(props.bookingId), [props.bookingId]);
  const data = booking.data;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.onClose]);

  const sub = data
    ? [
        `${placeText(data.pickup)} → ${placeText(data.dropoff)}`,
        props.summary || null,
        t("admin.trust.commissionLine", { status: commissionLabel(data.commission_status) }),
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

  return (
    <div className="fixed inset-0 z-[80] flex justify-end bg-foreground/40" onClick={props.onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={data ? `${props.bookingId} · ${serviceLabel(data.service_type)}` : props.bookingId}
        onClick={(event) => event.stopPropagation()}
        className="flex h-full w-full max-w-[560px] flex-col overflow-hidden border-l border-border bg-background shadow-2xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border bg-card px-5 py-4">
          <div className="min-w-0">
            <h3 className="break-words text-base font-bold text-foreground">
              <span className="font-mono">{props.bookingId}</span>
              {data ? ` · ${serviceLabel(data.service_type)}` : ""}
            </h3>
            {sub ? <p className="mt-1 text-xs text-muted-foreground">{sub}</p> : null}
          </div>
          <button type="button" onClick={props.onClose} aria-label={t("common.close")} className="el-press rounded-[10px] p-2 text-muted-foreground hover:bg-muted">
            <X size={18} />
          </button>
        </header>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-5">
          <ErrorLine error={caps.error ?? booking.error} />
          {booking.busy || caps.busy ? (
            <Spinner />
          ) : data ? (
            <>
              <div className="flex flex-wrap gap-2">
                <Badge tone={SERVICE_STATUS_TONE[data.service_status] ?? "gray"}>{serviceStatusLabel(data.service_status)}</Badge>
                <Badge tone={COMMISSION_TONE[data.commission_status] ?? "gray"}>{commissionLabel(data.commission_status)}</Badge>
                <span className="text-sm font-semibold text-foreground">{formatMinor(data.total_minor, data.currency)}</span>
              </div>
              <BookingFacts booking={data} />
              <BookingDetail
                booking={data}
                caps={caps.data}
                showFacts={false}
                preferCommand={props.queue === "finance_review" ? "finalize_fee" : undefined}
                onDone={() => {
                  booking.reload();
                  props.onChanged?.();
                }}
              />
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function BookingsTab({ caps }: { caps: CapabilitiesDTO | null }) {
  const t = useT();
  const queues = visibleBookingQueues(caps);
  const [queue, setQueue] = useState<AdminBookingQueue>(queues[0] ?? "awaiting_confirmation");
  const [openId, setOpenId] = useState<string | null>(null);
  const bookings = useLoader<AdminBookingDTO[]>(() => listAdminBookings({ queue, limit: 50 }), [queue]);
  const rows = bookings.data ?? [];

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Chips
          label={t("admin.trust.queue")}
          value={queue}
          onChange={(value) => {
            setQueue(value);
            setOpenId(null);
          }}
          items={queues.map((value) => ({
            value,
            label: t(BOOKING_QUEUE_KEY[value]),
            count: value === queue && !bookings.busy && !bookings.error ? countText(rows.length, 50) : null,
          }))}
        />
        <Btn onClick={bookings.reload}>
          <RefreshCw size={14} /> {t("support.refresh")}
        </Btn>
      </div>
      <ErrorLine error={bookings.error} />
      {bookings.busy ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <Empty>{t("admin.trust.queueEmpty")}</Empty>
      ) : (
        <div className="overflow-x-auto rounded-[12px] border border-border bg-card shadow-sm">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-3 font-semibold">{t("admin.mk.id")}</th>
                <th className="px-3 py-3 font-semibold">{t("admin.mk.service")}</th>
                <th className="px-3 py-3 font-semibold">{t("admin.trust.colServiceStatus")}</th>
                <th className="px-3 py-3 font-semibold">{t("admin.trust.colCommission")}</th>
                <th className="px-3 py-3 font-semibold">{t("common.total")}</th>
                <th className="px-3 py-3 font-semibold">{t("admin.trust.colTime")}</th>
                <th className="px-3 py-3 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {rows.map((booking) => (
                <BookingRow
                  key={booking.id}
                  booking={booking}
                  queue={queue}
                  open={openId === booking.id}
                  onToggle={() => setOpenId(openId === booking.id ? null : booking.id)}
                  caps={caps}
                  onDone={bookings.reload}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BookingRow(props: {
  booking: AdminBookingDTO;
  queue: AdminBookingQueue;
  open: boolean;
  onToggle: () => void;
  caps: CapabilitiesDTO | null;
  onDone: () => void;
}) {
  const t = useT();
  const { booking } = props;
  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-3 py-2 font-mono text-xs text-secondary-foreground">{booking.id}</td>
        <td className="px-3 py-2 text-secondary-foreground">{serviceLabel(booking.service_type)}</td>
        <td className="px-3 py-2">
          <Badge tone={SERVICE_STATUS_TONE[booking.service_status] ?? "gray"}>{serviceStatusLabel(booking.service_status)}</Badge>
        </td>
        <td className="px-3 py-2">
          <Badge tone={COMMISSION_TONE[booking.commission_status] ?? "gray"}>{commissionLabel(booking.commission_status)}</Badge>
        </td>
        <td className="px-3 py-2 font-semibold text-foreground">{formatMinor(booking.total_minor, booking.currency)}</td>
        <td className="px-3 py-2 text-muted-foreground">{formatDateTime(booking.created_at)}</td>
        <td className="px-3 py-2 text-right">
          <Btn onClick={props.onToggle}>{props.open ? t("common.close") : t("admin.mk.open")}</Btn>
        </td>
      </tr>
      {props.open ? (
        <tr className="bg-slate-50/60">
          <td colSpan={7} className="px-3 py-3">
            <BookingDetail
              booking={booking}
              caps={props.caps}
              onDone={props.onDone}
              preferCommand={props.queue === "finance_review" ? "finalize_fee" : undefined}
            />
          </td>
        </tr>
      ) : null}
    </>
  );
}

// --- reports and fraud signals (S12, S12b) -----------------------------------------------------------------------

const REVIEW_STATUS_KEY: Record<string, MessageKey> = {
  open: "admin.mk.open_",
  under_review: "admin.mk.underReview",
  dismissed: "status.rejected",
  actioned: "admin.mk.actioned",
  confirmed: "status.approved",
};

const REVIEW_STATUS_TONE: Record<string, BadgeTone> = {
  open: "warn",
  under_review: "blue",
  dismissed: "gray",
  actioned: "err",
  confirmed: "err",
};

function reviewStatusLabel(status: string): string {
  const key = REVIEW_STATUS_KEY[status];
  return key ? translate(key) : status;
}

function reportReasonLabel(code: string): string {
  return translateDynamic(`admin.trust.reason.${code}`) ?? code;
}

function fraudTypeLabel(type: string): string {
  return translateDynamic(`admin.trust.fraud.${type}`) ?? type;
}

function ReportItem({ report, canReview, onDone, onStrikes }: {
  report: ReportDTO;
  canReview: boolean;
  onDone: () => void;
  onStrikes?: (userId: string) => void;
}) {
  const t = useT();
  const [note, setNote] = useState("");
  const terminal = report.status === "dismissed" || report.status === "actioned";

  function action(status: "under_review" | "dismissed" | "actioned", label: string, tone: BtnTone) {
    return (
      <ConfirmButton
        key={status}
        label={label}
        tone={tone}
        question={t("admin.trust.reportConfirm", { status: reviewStatusLabel(status) })}
        onConfirm={async (key) => {
          await reviewReport(report.id, { expected_version: report.version, status, note: note.trim() || null }, key);
          setNote("");
          onDone();
        }}
      />
    );
  }

  return (
    <li className="grid content-start gap-2 rounded-[12px] border border-border bg-card p-3 text-sm shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 font-semibold text-foreground">
          <span className="font-mono text-xs text-secondary-foreground">{report.id}</span> · {reportReasonLabel(report.reason_code)}
        </p>
        <Badge tone={REVIEW_STATUS_TONE[report.status] ?? "gray"}>{reviewStatusLabel(report.status)}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("admin.trust.reportMeta", {
          object: `${translateDynamic(`admin.trust.subject.${report.subject_type}`) ?? report.subject_type} ${report.subject_id}`,
          time: formatDateTime(report.created_at),
        })}
      </p>
      {report.details ? <p className="text-secondary-foreground">{report.details}</p> : null}
      {report.subject_type === "user" && onStrikes ? (
        <div>
          <Btn onClick={() => onStrikes(report.subject_id)}>{t("admin.trust.tab.strikes")}</Btn>
        </div>
      ) : null}
      {canReview && !terminal ? (
        <div className="grid gap-2">
          <Field label={t("admin.trust.noteOptional")}>
            <textarea aria-label={t("listingOwner.commentLabel")} value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {report.status === "open" ? action("under_review", t("admin.mk.takeReview"), "soft") : null}
            {action("dismissed", t("admin.mk.reject"), "neutral")}
            {action("actioned", t("admin.trust.actioned"), "danger")}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function StatusChips(props: { value: string; onChange: (value: string) => void; options: string[] }) {
  const t = useT();
  return (
    <Chips
      label={t("admin.mk.status")}
      value={props.value}
      onChange={props.onChange}
      items={props.options.map((value) => ({ value, label: reviewStatusLabel(value) }))}
    />
  );
}

function ReportsTab({ caps, onStrikes }: { caps: CapabilitiesDTO | null; onStrikes: (userId: string) => void }) {
  const t = useT();
  const [status, setStatus] = useState("open");
  const reports = useLoader<ReportDTO[]>(() => listReports({ status: status || undefined, limit: 50 }), [status]);
  const canReview = has(caps, "ops.trust_review");
  return (
    <div className="grid gap-3">
      <Note>{t("admin.trust.reportsNote")}</Note>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusChips value={status} onChange={setStatus} options={["open", "under_review", "dismissed", "actioned"]} />
        <Btn onClick={reports.reload}>
          <RefreshCw size={14} /> {t("support.refresh")}
        </Btn>
      </div>
      <ErrorLine error={reports.error} />
      {reports.busy ? (
        <Spinner />
      ) : (reports.data ?? []).length === 0 ? (
        <Empty>{t("admin.trust.noReports")}</Empty>
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {(reports.data ?? []).map((report) => (
            <ReportItem key={report.id} report={report} canReview={canReview} onDone={reports.reload} onStrikes={onStrikes} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FraudItem({ signal, canReview, onDone, onStrikes }: {
  signal: FraudSignalDTO;
  canReview: boolean;
  onDone: () => void;
  onStrikes: (userId: string) => void;
}) {
  const t = useT();
  const [note, setNote] = useState("");
  const terminal = signal.status === "dismissed" || signal.status === "confirmed";

  function action(status: "under_review" | "dismissed" | "confirmed", label: string, tone: BtnTone) {
    return (
      <ConfirmButton
        key={status}
        label={label}
        tone={tone}
        question={t("admin.trust.fraudConfirm", { status: reviewStatusLabel(status) })}
        onConfirm={async (key) => {
          await reviewFraudSignal(signal.id, { expected_version: signal.version, status, note: note.trim() || null }, key);
          setNote("");
          onDone();
        }}
      />
    );
  }

  return (
    <li className="grid content-start gap-2 rounded-[12px] border border-border bg-card p-3 text-sm shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 font-semibold text-foreground">{fraudTypeLabel(signal.signal_type)}</p>
        <Badge tone={REVIEW_STATUS_TONE[signal.status] ?? "gray"}>{reviewStatusLabel(signal.status)}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        <span className="font-mono">{signal.id}</span> · <span className="font-mono">{signal.subject_user_id}</span> ·{" "}
        {formatDateTime(signal.detected_at)}
      </p>
      <p className="text-xs text-muted-foreground">{t("admin.trust.fraudEvidence", { refs: evidenceText(signal.evidence) })}</p>
      <div>
        <Btn onClick={() => onStrikes(signal.subject_user_id)}>{t("admin.trust.tab.strikes")}</Btn>
      </div>
      {canReview && !terminal ? (
        <div className="grid gap-2">
          <Field label={t("admin.trust.noteOptional")}>
            <textarea aria-label={t("listingOwner.commentLabel")} value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {signal.status === "open" ? action("under_review", t("admin.mk.takeReview"), "soft") : null}
            {action("dismissed", t("admin.trust.unfounded"), "neutral")}
            {action("confirmed", t("common.confirm"), "danger")}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function FraudTab({ caps, onStrikes }: { caps: CapabilitiesDTO | null; onStrikes: (userId: string) => void }) {
  const t = useT();
  const [status, setStatus] = useState("open");
  const signals = useLoader<FraudSignalDTO[]>(() => listFraudSignals({ status: status || undefined, limit: 50 }), [status]);
  const canReview = has(caps, "ops.trust_review");
  return (
    <div className="grid gap-3">
      <Note tone="warn">{t("admin.trust.fraudNote")}</Note>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusChips value={status} onChange={setStatus} options={["open", "under_review", "dismissed", "confirmed"]} />
        <Btn onClick={signals.reload}>
          <RefreshCw size={14} /> {t("support.refresh")}
        </Btn>
      </div>
      <ErrorLine error={signals.error} />
      {signals.busy ? (
        <Spinner />
      ) : (signals.data ?? []).length === 0 ? (
        <Empty>{t("admin.trust.noSignals")}</Empty>
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {(signals.data ?? []).map((signal) => (
            <FraudItem key={signal.id} signal={signal} canReview={canReview} onDone={signals.reload} onStrikes={onStrikes} />
          ))}
        </ul>
      )}
    </div>
  );
}

// --- strikes (S20, Q45/Q83/Q85) --------------------------------------------------------------------------------

function StrikesTab({ initialUserId }: { initialUserId: string }) {
  const t = useT();
  const [input, setInput] = useState(initialUserId);
  const [userId, setUserId] = useState(initialUserId);
  const strikes = useLoader<UserStrikesDTO>(() => userStrikes(userId), [userId], Boolean(userId));

  useEffect(() => {
    setInput(initialUserId);
    setUserId(initialUserId);
  }, [initialUserId]);

  return (
    <div className="grid gap-3">
      <Note>{t("admin.trust.strikesNote")}</Note>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[260px] flex-1 sm:max-w-sm">
          <LookupField
            label={t("admin.mk.user")}
            ariaLabel={t("admin.trust.userId")}
            value={input}
            onChange={setInput}
            search={lookupUsers}
            min={SEARCH_MIN.users}
          />
        </div>
        <Btn tone="soft" disabled={!input.trim()} onClick={() => setUserId(input.trim())}>
          {t("admin.mk.view")}
        </Btn>
      </div>
      <ErrorLine error={strikes.error} />
      {!userId ? null : strikes.busy ? (
        <Spinner />
      ) : strikes.data ? (
        <div className="grid gap-2">
          <p className="text-sm text-foreground">
            {t("admin.trust.strikesInWindow", { days: strikes.data.window_days, count: strikes.data.strikes_in_window })}
          </p>
          {strikes.data.strikes.length === 0 ? (
            <Empty>{t("admin.trust.noStrikes")}</Empty>
          ) : (
            <ul className="grid gap-1">
              {strikes.data.strikes.map((strike, index) => (
                <li
                  key={`${strike.occurred_at}-${index}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-border bg-card px-3 py-2 text-sm"
                >
                  <span className="min-w-0">
                    <span className="font-medium text-foreground">
                      {strike.reason_code} · {translateDynamic(`admin.trust.strikeSource.${strike.subject_type}`) ?? strike.subject_type}
                    </span>
                    {strike.categories.length ? <span className="text-xs text-muted-foreground"> · {strike.categories.join(", ")}</span> : null}
                    <span className="block text-xs text-muted-foreground">{formatDateTime(strike.occurred_at)}</span>
                  </span>
                  <Badge tone="warn">{t("admin.trust.strike")}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

// --- chat lookup (N10; proposal thread read-only, Q100) ----------------------------------------------------------

function ChatTab({ caps }: { caps: CapabilitiesDTO | null }) {
  const t = useT();
  const [kind, setKind] = useState<"booking" | "proposal">("booking");
  const [input, setInput] = useState("");
  const [target, setTarget] = useState<{ kind: "booking" | "proposal"; id: string } | null>(null);
  const messages = useLoader<ChatMessageAdminDTO[]>(
    () =>
      target!.kind === "booking"
        ? adminBookingMessages(target!.id, { limit: 50 })
        : adminProposalMessages(target!.id, { limit: 50 }),
    [target?.kind, target?.id],
    Boolean(target),
  );

  return (
    <div className="grid gap-3">
      <Note>{t("admin.trust.chatNote")}</Note>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("admin.trust.threadKind")}>
          <select
            aria-label={t("admin.trust.threadKind")}
            value={kind}
            onChange={(event) => setKind(event.target.value as "booking" | "proposal")}
            className={INPUT}
          >
            <option value="booking">{t("admin.trust.bookingChat")}</option>
            <option value="proposal">{t("admin.trust.proposalThread")}</option>
          </select>
        </Field>
        <div className="min-w-[240px] flex-1 sm:max-w-sm">
          {kind === "booking" ? (
            <LookupField
              label={t("admin.mk.booking")}
              ariaLabel={t("admin.trust.threadId")}
              value={input}
              onChange={setInput}
              search={lookupBookings}
              min={SEARCH_MIN.bookings}
            />
          ) : (
            <Field label={t("admin.trust.proposalThreadId")}>
              <input aria-label={t("admin.trust.threadId")} value={input} onChange={(event) => setInput(event.target.value)} className={INPUT} />
            </Field>
          )}
        </div>
        <Btn tone="soft" disabled={!input.trim()} onClick={() => setTarget({ kind, id: input.trim() })}>
          {t("admin.mk.open")}
        </Btn>
      </div>
      <ErrorLine error={messages.error} />
      {!target ? null : messages.busy ? (
        <Spinner />
      ) : (
        <MessagesList
          messages={messages.data ?? []}
          canHide={target.kind === "booking" && has(caps, "ops.trust_review")}
          onHidden={messages.reload}
        />
      )}
    </div>
  );
}

// --- trip tracking (K9, Q86) -------------------------------------------------------------------------------------

function freshnessLabel(freshness: string): string {
  return translateDynamic(`admin.trust.freshness.${freshness}`) ?? freshness;
}

function TrackingTab() {
  const t = useT();
  const [input, setInput] = useState("");
  const [tripId, setTripId] = useState("");
  const tracking = useLoader<TripTrackingAdminDTO>(() => adminTripTracking(tripId), [tripId], Boolean(tripId));
  const data = tracking.data;
  const point = data?.last_point;

  return (
    <div className="grid gap-3">
      <Note>{t("admin.trust.trackingNote")}</Note>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[240px] flex-1 sm:max-w-sm">
          <LookupField
            label={t("admin.mk.trip")}
            ariaLabel={t("admin.trust.tripId")}
            value={input}
            onChange={setInput}
            search={lookupTrips}
            min={SEARCH_MIN.trips}
          />
        </div>
        <Btn tone="soft" disabled={!input.trim()} onClick={() => setTripId(input.trim())}>
          {t("admin.mk.view")}
        </Btn>
      </div>
      <ErrorLine error={tracking.error} />
      {!tripId ? null : tracking.busy ? (
        <Spinner />
      ) : data ? (
        <>
          <Kv
            cols={2}
            rows={[
              [t("admin.trust.freshness"), <strong key="f">{freshnessLabel(data.freshness)}</strong>],
              [
                t("admin.trust.session"),
                data.active_session
                  ? t("admin.trust.sessionOpenSince", { time: formatDateTime(data.session_started_at) })
                  : t("admin.trust.sessionClosed"),
              ],
              [
                t("admin.trust.coordinate"),
                point ? (
                  <span key="c" className="font-mono text-xs">
                    {point.lat.toFixed(5)}, {point.lng.toFixed(5)} · ±{point.accuracy_m} m
                    {point.low_accuracy ? ` · ${t("admin.trust.lowAccuracy")}` : ""}
                  </span>
                ) : (
                  t("admin.trust.noPoint")
                ),
              ],
              [
                t("admin.trust.capturedReceived"),
                point ? `${formatDateTime(point.captured_at)} / ${formatDateTime(point.received_at)}` : "—",
              ],
            ]}
          />
          {point ? <VehicleMap point={point} live={data.freshness === "fresh"} /> : null}
          <p className="text-xs text-muted-foreground">{t("admin.trust.trailBlocked")}</p>
        </>
      ) : null}
    </div>
  );
}

// --- listing on behalf (O7, §20.2) -------------------------------------------------------------------------------

const PARCEL_TYPES = ["documents", "box", "bag", "electronics", "clothing", "other"] as const;

/** `datetime-local` value read as Tashkent wall time (the only timezone a listing accepts). */
export function tashkentIso(local: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local)) return null;
  return `${local}:00+05:00`;
}

const EMPTY_FORM = {
  owner: "",
  consent: "",
  kind: "request" as const,  // Q138 (ADR-0026): drivers publish no listings - on-behalf is a client request only
  service: "passenger" as "passenger" | "parcel",
  tripId: "",
  // 06.10.2026: an end is a place (region -> district, optional address)
  originRegion: "",
  originDistrict: "",
  originAddress: "",
  destRegion: "",
  destDistrict: "",
  destAddress: "",
  start: "",
  end: "",
  basis: "per_seat" as "per_seat" | "total",
  price: "",
  seats: "1",
  parcelType: "box" as (typeof PARCEL_TYPES)[number],
  categoryId: "",
  comment: "",
};

type PointEnd = NonNullable<ListingOnBehalfBody["origin_point"]>;

/** Why an end cannot be sent yet: nothing chosen, or the catalogue has no coordinate / no district for it. */
export type PlaceProblem = { problem: "incomplete" } | { problem: "no_centre" | "no_districts"; name: string };

/**
 * One end of the request as the Q88 `*_point` the server wants: the district centre (or the region centre where the
 * region itself is the unit, `requires_district === false` - Tashkent city), the district id and the typed address.
 *
 * Nothing is guessed: a district without a centre in the catalogue is refused in words, not sent as 0,0. For a
 * region that is its own unit the advisory `district_id` is the catalogue district nearest to the region centre,
 * the same way the client app resolves it.
 */
export function placeEnd(
  region: RegionDTO | undefined,
  districts: DistrictDTO[] | undefined,
  districtId: string,
  address: string,
): PointEnd | PlaceProblem {
  if (!region) return { problem: "incomplete" };
  const note = address.trim() || null;
  if (region.requires_district !== false) {
    if (!districts) return { problem: "incomplete" };
    if (districts.length === 0) return { problem: "no_districts", name: region.name_uz };
    const district = districts.find((item) => item.id === districtId);
    if (!district) return { problem: "incomplete" };
    if (district.center_lat == null || district.center_lng == null) return { problem: "no_centre", name: district.name_uz };
    return { lat: district.center_lat, lng: district.center_lng, district_id: district.id, address: note };
  }
  if (region.center_lat == null || region.center_lng == null) return { problem: "no_centre", name: region.name_uz };
  if (!districts) return { problem: "incomplete" };
  if (districts.length === 0) return { problem: "no_districts", name: region.name_uz };
  const lat = region.center_lat;
  const lng = region.center_lng;
  const distance = (item: DistrictDTO) =>
    item.center_lat == null || item.center_lng == null ? Infinity : (item.center_lat - lat) ** 2 + (item.center_lng - lng) ** 2;
  const nearest = [...districts].sort((a, b) => distance(a) - distance(b))[0];
  return { lat, lng, district_id: nearest.id, address: note };
}

function isPoint(end: PointEnd | PlaceProblem): end is PointEnd {
  return !("problem" in end);
}

export function onBehalfBody(
  form: typeof EMPTY_FORM,
  origin: PointEnd | PlaceProblem,
  destination: PointEnd | PlaceProblem,
): ListingOnBehalfBody | null {
  const start = tashkentIso(form.start);
  const end = tashkentIso(form.end);
  const price = Math.round(Number(form.price.replace(/\s/g, "")));
  const seats = Math.round(Number(form.seats));
  if (!form.owner.trim() || form.consent.trim().length < 3 || !start || !end || !(price > 0)) return null;
  if (!isPoint(origin) || !isPoint(destination)) return null;
  if (origin.lat === destination.lat && origin.lng === destination.lng) return null;  // the server refuses equal ends
  if (form.service === "passenger" && !(seats >= 1 && seats <= 8)) return null;
  if (form.service === "parcel" && !form.categoryId.trim()) return null;  // Q140: a size category, no typed weight
  return {
    owner_user_id: form.owner.trim(),
    consent_reference: form.consent.trim(),
    kind: form.kind,
    service_type: form.service,
    trip_id: null,
    origin_point: origin,
    destination_point: destination,
    departure_window_start: start,
    departure_window_end: end,
    price_basis: form.service === "parcel" ? "total" : form.basis,
    unit_price_minor: price * 100,
    currency: "UZS",
    payment_method: "cash",
    timezone: "Asia/Tashkent",
    comment: form.comment.trim() || null,
    passenger:
      form.service === "passenger"
        ? { seat_count: seats, adults: seats, children: 0, child_seat_required: false }
        : null,
    parcel:
      form.service === "parcel"
        ? { parcel_type: form.parcelType, category_id: form.categoryId.trim(), fragile: false }
        : null,
  };
}

/** `409 ROUTE_MISMATCH`: no ELCHI road joins the two places yet - a product answer, said as such. */
function explainOnBehalfError(cause: unknown): unknown {
  return cause instanceof ApiError && cause.code === "ROUTE_MISMATCH" ? translate("admin.trust.noRoute") : cause;
}

/** One end: region, then district (skipped where the region is its own unit), then an optional address line. */
function PlaceField(props: {
  label: string;
  regions: RegionDTO[];
  districts: DistrictDTO[] | undefined;
  regionId: string;
  districtId: string;
  address: string;
  resolved: PointEnd | PlaceProblem;
  onRegion: (id: string) => void;
  onDistrict: (id: string) => void;
  onAddress: (value: string) => void;
}) {
  const t = useT();
  const region = props.regions.find((item) => item.id === props.regionId);
  const needsDistrict = region?.requires_district !== false;
  const problem = isPoint(props.resolved) ? null : props.resolved;
  return (
    <fieldset className="grid gap-2 rounded-[10px] border border-border p-2 sm:col-span-2 sm:grid-cols-3">
      <legend className="px-1 text-sm font-medium text-secondary-foreground">{props.label}</legend>
      <Field label={t("admin.trust.placeRegion")}>
        <select
          aria-label={t("admin.trust.placeRegionAria", { end: props.label })}
          value={props.regionId}
          onChange={(event) => props.onRegion(event.target.value)}
          className={INPUT}
        >
          <option value="">{t("admin.trust.choose")}</option>
          {props.regions.map((item) => (
            <option key={item.id} value={item.id}>{item.name_uz}</option>
          ))}
        </select>
      </Field>
      {needsDistrict ? (
        <Field label={t("admin.trust.placeDistrict")}>
          <select
            aria-label={t("admin.trust.placeDistrictAria", { end: props.label })}
            value={props.districtId}
            disabled={!region || !props.districts}
            onChange={(event) => props.onDistrict(event.target.value)}
            className={INPUT}
          >
            <option value="">{t("admin.trust.choose")}</option>
            {(props.districts ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.name_uz}</option>
            ))}
          </select>
        </Field>
      ) : (
        <p className="self-end pb-2 text-xs text-muted-foreground">{t("admin.trust.placeCityUnit")}</p>
      )}
      <Field label={t("admin.trust.placeAddress")}>
        <input
          aria-label={t("admin.trust.placeAddressAria", { end: props.label })}
          value={props.address}
          maxLength={500}
          onChange={(event) => props.onAddress(event.target.value)}
          className={INPUT}
        />
      </Field>
      {problem && problem.problem !== "incomplete" ? (
        <p role="alert" className="text-xs font-medium text-destructive sm:col-span-3">
          {problem.problem === "no_centre"
            ? t("admin.trust.placeNoCentre", { name: problem.name })
            : t("admin.trust.placeNoDistricts", { name: problem.name })}
        </p>
      ) : null}
    </fieldset>
  );
}

function OnBehalfTab({ caps }: { caps: CapabilitiesDTO | null }) {
  const t = useT();
  const [form, setForm] = useState(EMPTY_FORM);
  const [categories, setCategories] = useState<ParcelCategoryDTO[]>([]);
  useEffect(() => {
    parcelCategories().then((catalog) => setCategories(catalog.items ?? [])).catch(() => setCategories([]));
  }, []);
  const [regions, setRegions] = useState<RegionDTO[]>([]);
  const [districtsByRegion, setDistrictsByRegion] = useState<Record<string, DistrictDTO[]>>({});
  useEffect(() => {
    adminRegions().then(setRegions).catch(() => setRegions([]));
  }, []);
  useEffect(() => {
    for (const regionId of [form.originRegion, form.destRegion]) {
      if (!regionId || districtsByRegion[regionId]) continue;
      adminDistricts(regionId)
        .then((rows) => setDistrictsByRegion((current) => ({ ...current, [regionId]: rows.filter((row) => row.is_active !== false) })))
        .catch(() => setDistrictsByRegion((current) => ({ ...current, [regionId]: [] })));
    }
  }, [form.originRegion, form.destRegion]);
  const regionOf = (id: string) => regions.find((item) => item.id === id);
  const origin = placeEnd(regionOf(form.originRegion), districtsByRegion[form.originRegion], form.originDistrict, form.originAddress);
  const destination = placeEnd(regionOf(form.destRegion), districtsByRegion[form.destRegion], form.destDistrict, form.destAddress);
  const [created, setCreated] = useState<{ listing: AdminListingDTO; warnings: ApiWarning[] } | null>(null);
  const body = onBehalfBody(form, origin, destination);
  const set = <K extends keyof typeof EMPTY_FORM>(key: K, value: (typeof EMPTY_FORM)[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  if (!has(caps, "ops.booking_command")) {
    return <Empty>{t("admin.trust.onBehalfNoRole")}</Empty>;
  }

  return (
    <div className="grid gap-3">
      <Note tone="info">{t("admin.trust.onBehalfNote")}</Note>
      {created ? (
        <Note tone="ok">
          {t("admin.trust.listingCreated", { id: created.listing.id, status: created.listing.status })}
          {created.warnings.length ? (
            <span className="mt-1 block text-xs">{created.warnings.map((warning) => warningMessage(warning.code)).join(" · ")}</span>
          ) : null}
        </Note>
      ) : null}
      <div className="grid gap-3 rounded-[12px] border border-border bg-card p-3 sm:grid-cols-2">
        <LookupField
          label={t("admin.trust.owner")}
          ariaLabel={t("admin.trust.ownerAria")}
          value={form.owner}
          onChange={(value) => set("owner", value)}
          search={lookupUsers}
          min={SEARCH_MIN.users}
        />
        <Field label={t("admin.trust.consent")} hint={t("admin.trust.consentHint")}>
          <input
            aria-label={t("admin.trust.consentAria")}
            required
            value={form.consent}
            onChange={(event) => set("consent", event.target.value)}
            className={INPUT}
          />
        </Field>
        <Field label={t("admin.mk.service")}>
          <select value={form.service} onChange={(event) => set("service", event.target.value as "passenger" | "parcel")} className={INPUT}>
            <option value="passenger">{t("admin.mk.passenger")}</option>
            <option value="parcel">{t("admin.mk.parcel")}</option>
          </select>
        </Field>
        {form.service === "parcel" ? (
          <Field label={t("admin.trust.sizeCategory")} hint={t("admin.trust.sizeCategoryHint")}>
            <select aria-label={t("admin.trust.sizeCategoryAria")} value={form.categoryId} onChange={(event) => set("categoryId", event.target.value)} className={INPUT}>
              <option value="">{t("admin.trust.choose")}</option>
              {categories.map((item) => (
                <option key={item.id} value={item.id}>{item.name_uz}</option>
              ))}
            </select>
          </Field>
        ) : (
          <div />
        )}
        <PlaceField
          label={t("admin.trust.originPlace")}
          regions={regions}
          districts={districtsByRegion[form.originRegion]}
          regionId={form.originRegion}
          districtId={form.originDistrict}
          address={form.originAddress}
          resolved={origin}
          onRegion={(id) => setForm((current) => ({ ...current, originRegion: id, originDistrict: "" }))}
          onDistrict={(id) => set("originDistrict", id)}
          onAddress={(value) => set("originAddress", value)}
        />
        <PlaceField
          label={t("admin.trust.destPlace")}
          regions={regions}
          districts={districtsByRegion[form.destRegion]}
          regionId={form.destRegion}
          districtId={form.destDistrict}
          address={form.destAddress}
          resolved={destination}
          onRegion={(id) => setForm((current) => ({ ...current, destRegion: id, destDistrict: "" }))}
          onDistrict={(id) => set("destDistrict", id)}
          onAddress={(value) => set("destAddress", value)}
        />
        <Field label={t("admin.trust.windowStart")}>
          <input aria-label={t("admin.trust.windowStartAria")} type="datetime-local" value={form.start} onChange={(event) => set("start", event.target.value)} className={INPUT} />
        </Field>
        <Field label={t("admin.trust.windowEnd")}>
          <input aria-label={t("admin.trust.windowEndAria")} type="datetime-local" value={form.end} onChange={(event) => set("end", event.target.value)} className={INPUT} />
        </Field>
        {form.service === "passenger" ? (
          <>
            <Field label={t("admin.trust.priceBasis")}>
              <select value={form.basis} onChange={(event) => set("basis", event.target.value as "per_seat" | "total")} className={INPUT}>
                <option value="per_seat">{t("admin.trust.perSeat")}</option>
                <option value="total">{t("common.total")}</option>
              </select>
            </Field>
            <Field label={t("admin.trust.seats")}>
              <input aria-label={t("admin.trust.seatsAria")} inputMode="numeric" value={form.seats} onChange={(event) => set("seats", event.target.value)} className={INPUT} />
            </Field>
          </>
        ) : (
          <Field label={t("admin.trust.parcelType")}>
            <select
              value={form.parcelType}
              onChange={(event) => set("parcelType", event.target.value as (typeof PARCEL_TYPES)[number])}
              className={INPUT}
            >
              {PARCEL_TYPES.map((value) => (
                <option key={value} value={value}>
                  {translateDynamic(`admin.trust.parcelTypeValue.${value}`) ?? value}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label={t("admin.trust.priceSoum")}>
          <input aria-label={t("admin.trust.priceAria")} inputMode="numeric" value={form.price} onChange={(event) => set("price", event.target.value)} className={INPUT} />
        </Field>
        <Field label={t("listingOwner.commentLabel")} hint={t("admin.trust.commentMasked")}>
          <input value={form.comment} onChange={(event) => set("comment", event.target.value)} className={INPUT} />
        </Field>
      </div>
      <ConfirmButton
        label={t("admin.trust.createListing")}
        tone="primary"
        disabled={!body}
        question={t("admin.trust.createListingConfirm")}
        onConfirm={async (key) => {
          if (!body) return;
          const result = await createListingOnBehalf(body, key).catch((cause: unknown) => {
            throw explainOnBehalfError(cause);
          });
          setCreated({ listing: result.data, warnings: result.warnings });
          setForm(EMPTY_FORM);
        }}
      />
    </div>
  );
}

// --- the panel ---------------------------------------------------------------------------------------------------

export function AdminTrustPanel({ initialTab = "bookings" }: { initialTab?: TrustTab } = {}) {
  const t = useT();
  const [tab, setTab] = useState<TrustTab>(initialTab);
  const [strikeUser, setStrikeUser] = useState("");
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);
  const tabs = caps.data ? visibleTrustTabs(caps.data) : [];
  const current = tabs.includes(tab) ? tab : tabs[0];

  function openStrikes(userId: string) {
    setStrikeUser(userId);
    setTab("strikes");
  }

  return (
    <section className="grid gap-4">
      <header className="grid gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">{t("admin.trust.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("admin.trust.subtitle")}</p>
        </div>
        <nav className="flex flex-wrap gap-2" role="tablist">
          {TABS.filter(([value]) => tabs.includes(value)).map(([value, key]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={current === value}
              onClick={() => setTab(value)}
              className={`el-press inline-flex h-9 items-center rounded-[10px] border px-3 text-sm font-semibold ${
                current === value ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-secondary-foreground"
              }`}
            >
              {t(key)}
            </button>
          ))}
        </nav>
      </header>
      <ErrorLine error={caps.error} />
      {caps.busy ? (
        <Spinner />
      ) : !current ? (
        caps.error ? null : <Empty>{t("admin.trust.noTabs")}</Empty>
      ) : (
        <>
          {current === "bookings" ? <BookingsTab caps={caps.data} /> : null}
          {current === "reports" ? <ReportsTab caps={caps.data} onStrikes={openStrikes} /> : null}
          {current === "fraud" ? <FraudTab caps={caps.data} onStrikes={openStrikes} /> : null}
          {current === "strikes" ? <StrikesTab initialUserId={strikeUser} /> : null}
          {current === "chat" ? <ChatTab caps={caps.data} /> : null}
          {current === "tracking" ? <TrackingTab /> : null}
          {current === "on_behalf" ? <OnBehalfTab caps={caps.data} /> : null}
        </>
      )}
    </section>
  );
}
