/**
 * Staff trust & operations actions (A12 S9-S20, B12/B13, N10, K9, O7) inside the admin panel.
 *
 * What the panel promises is what the server allows:
 * * a button appears only for a capability `/me/capabilities` really returns - an operator does not see "cancel"
 *   (`ops.booking_cancel`, admin+, Q10) and finance alone sees "finalize fee" (Q17); anything else the server
 *   refuses is shown with the server's own reason, never hidden behind a pretend success;
 * * every command is confirmed first and carries one idempotency key per confirmed action (ADR-0005);
 * * a cancellation names its cause or leaves it undetermined for review - it is never assumed (Q129);
 * * fraud signals and reports are questions for a human: nothing here blocks, fines or down-ranks anybody (§17.3);
 * * the proposal thread is read-only (Q100) and hiding a booking chat message needs a written reason;
 * * contacts appear only where the API returned them; the tracking view is audited and shows the freshness of the
 *   last trusted point, never a "GPS active" claim (Q86, §10.5);
 * * a listing on behalf of someone needs the real owner and a consent reference (§20.2) - the server stores the
 *   operator as `created_by_operator`.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

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
import { newIdempotencyKey, type ApiWarning, type Schemas } from "../api/v2/http";
import { capabilities, type CapabilitiesDTO } from "../api/v2/ops.api";
import { formatDateTime, formatMinor } from "../utils/v2Format";
import { v2ErrorMessage, warningMessage } from "../utils/v2Errors";
import { Inbox, Loader2, RefreshCw } from "./ui/icons";

type FaultSide = Schemas["FaultSide"];
type ProofKind = Schemas["ProofKind"];

export type TrustTab = "bookings" | "reports" | "fraud" | "strikes" | "chat" | "tracking" | "on_behalf";

const TABS: Array<[TrustTab, string]> = [
  ["bookings", "Bronlar"],
  ["reports", "Shikoyatlar"],
  ["fraud", "Firibgarlik signallari"],
  ["strikes", "Strike'lar"],
  ["chat", "Yozishmalar"],
  ["tracking", "Safar kuzatuvi"],
  ["on_behalf", "Nomidan e'lon"],
];

// --- small shared pieces ------------------------------------------------------------------------------------------

function Spinner() {
  return <Loader2 size={16} className="animate-spin text-slate-400" />;
}

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
      {v2ErrorMessage(error)}
    </p>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
      <Inbox size={18} className="mx-auto mb-2 text-slate-400" />
      {children}
    </div>
  );
}

function useLoader<T>(loader: () => Promise<T>, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(enabled);
  const [nonce, setNonce] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  useEffect(() => {
    if (!enabled) {
      setBusy(false);
      return;
    }
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
  }, [run, nonce, enabled]);

  return { data, error, busy, reload: () => setNonce((value) => value + 1) };
}

const INPUT = "h-9 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground";
const TEXTAREA = "h-20 rounded-[10px] border border-border bg-card px-3 py-2 text-sm text-foreground";

type Tone = "primary" | "danger" | "neutral";

function toneClass(tone: Tone): string {
  if (tone === "primary") return "border-primary bg-primary text-primary-foreground";
  if (tone === "danger") return "border-destructive/25 bg-destructive/10 text-destructive";
  return "border-border bg-card text-secondary-foreground";
}

function Btn(props: { children: ReactNode; onClick: () => void; disabled?: boolean; tone?: Tone }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-9 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold ${toneClass(props.tone ?? "neutral")} disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

/**
 * A command button that asks first. The idempotency key is minted when the confirmation opens and kept for a
 * retry of the same confirmation, so a double click or a network retry cannot act twice.
 */
export function ConfirmButton(props: {
  label: string;
  question: string;
  onConfirm: (idempotencyKey: string) => Promise<void>;
  disabled?: boolean;
  tone?: Tone;
}) {
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
      setError(cause);
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
          {error ? "Qayta urinish" : "Ha, bajarish"}
        </Btn>
        <Btn
          disabled={busy}
          onClick={() => {
            setKey(null);
            setError(null);
          }}
        >
          Bekor qilish
        </Btn>
      </div>
    </div>
  );
}

function StatusChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex rounded-full border border-border bg-slate-50 px-2.5 py-1 text-xs font-semibold text-secondary-foreground">
      {children}
    </span>
  );
}

function Field(props: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="grid gap-1 text-sm font-medium text-secondary-foreground">
      {props.label}
      {props.children}
      {props.hint ? <span className="text-xs font-normal text-muted-foreground">{props.hint}</span> : null}
    </label>
  );
}

function evidenceText(evidence: Record<string, number | string[]>): string {
  const parts = Object.entries(evidence ?? {}).map(([key, value]) =>
    Array.isArray(value) ? `${key}: ${value.join(", ")}` : `${key}: ${value}`,
  );
  return parts.join(" · ") || "-";
}

function has(caps: CapabilitiesDTO | null, capability: string): boolean {
  return Boolean(caps?.capabilities?.includes(capability as never));
}

// --- bookings (B12/B13) -----------------------------------------------------------------------------------------

const QUEUE_LABEL: Record<AdminBookingQueue, string> = {
  awaiting_confirmation: "Tasdiq kutilmoqda",
  no_show_review: "Kelmadi ko'rigi",
  custody_case: "Yuk saqlovda",
  hold_escalation: "Hold eskalatsiyasi",
  finance_review: "Moliya ko'rigi",
};

const COMMAND_LABEL: Record<OperatorBookingCommand, string> = {
  confirm_no_show: "Kelmaganini tasdiqlash",
  reject_no_show: "Kelmadi xabarini rad etish",
  complete_with_evidence: "Dalil bilan yakunlash",
  drop_off: "Yo'lovchi tushirildi",
  require_return: "Qaytarishni talab qilish",
  return_to_sender: "Jo'natuvchiga qaytarildi",
  resolve_custody_case: "Saqlov holatini yopish",
  finalize_fee: "Komissiyani yakunlash",
  cancel: "Bronni bekor qilish",
  reissue_proof_code: "Kodni qayta berish",
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
  finalize_fee: "finance.fee_finalize",
  cancel: "ops.booking_cancel",
};

const FAULT_LABEL: Array<["" | FaultSide, string]> = [
  ["", "Aniqlanmagan — tekshiruvga yuboriladi"],
  ["client", "Mijoz sababli"],
  ["driver", "Haydovchi sababli"],
  ["platform", "Platforma sababli"],
  ["none", "Hech kim aybdor emas (asosli bekor)"],
];

const PROOF_LABEL: Array<[ProofKind, string]> = [
  ["boarding_code", "Chiqish kodi"],
  ["pickup_code", "Olib ketish kodi"],
  ["delivery_code", "Topshirish kodi"],
  ["return_code", "Qaytarish kodi"],
];

/** Which commands make sense for this booking right now. The server still has the last word. */
export function applicableCommands(booking: AdminBookingDTO): OperatorBookingCommand[] {
  const out: OperatorBookingCommand[] = [];
  if (booking.no_show_review?.status === "pending") out.push("confirm_no_show", "reject_no_show");
  out.push("complete_with_evidence");
  if (booking.service_type === "passenger") out.push("drop_off");
  if (booking.service_type === "parcel") out.push("require_return", "return_to_sender", "resolve_custody_case");
  if (booking.commission_status === "held") out.push("finalize_fee");
  out.push("reissue_proof_code", "cancel");
  return out;
}

function stopText(stop: AdminBookingDTO["pickup"]): string {
  const district = stop.point?.district;
  const districtName = typeof district === "string" ? district : district?.name_uz;
  return stop.stop?.name_uz ?? stop.point?.address ?? districtName ?? "-";
}

function MessagesList(props: {
  messages: ChatMessageAdminDTO[];
  canHide: boolean;
  onHidden?: () => void;
}) {
  if (props.messages.length === 0) return <Empty>Xabar yo'q</Empty>;
  return (
    <ul className="grid gap-2">
      {props.messages.map((message) => (
        <MessageItem key={message.id} message={message} canHide={props.canHide} onHidden={props.onHidden} />
      ))}
    </ul>
  );
}

function MessageItem({ message, canHide, onHidden }: { message: ChatMessageAdminDTO; canHide: boolean; onHidden?: () => void }) {
  const [reason, setReason] = useState("");
  const hidden = message.moderation_status === "hidden_by_staff";
  const filtered = Object.entries(message.contact_filter_categories ?? {});
  return (
    <li className="grid gap-2 rounded-[10px] border border-border bg-card px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <StatusChip>{message.author_side}</StatusChip>
        <span className="font-mono">{message.author_user_id}</span>
        <span>{formatDateTime(message.created_at)}</span>
        {hidden ? <span className="font-semibold text-warning">yashirilgan</span> : null}
      </div>
      <p className="text-secondary-foreground">
        {message.text ?? (message.quick_reply_code ? `Tezkor javob: ${message.quick_reply_code}` : "-")}
      </p>
      {filtered.length ? (
        <p className="text-xs text-muted-foreground">
          Filtr mosligi: {filtered.map(([category, count]) => `${category} × ${count}`).join(", ")}
        </p>
      ) : null}
      {canHide && !hidden && onHidden ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Yashirish sababi (kamida 3 belgi)">
            <input value={reason} onChange={(event) => setReason(event.target.value)} className={INPUT} />
          </Field>
          <ConfirmButton
            label="Yashirish"
            tone="danger"
            disabled={reason.trim().length < 3}
            question="Xabar ikkala tomondan yashiriladi va audit jurnaliga yoziladi. Davom etasizmi?"
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
  const messages = useLoader<ChatMessageAdminDTO[]>(() => adminBookingMessages(bookingId, { limit: 50 }), [bookingId]);
  return (
    <div className="grid gap-2">
      <p className="text-xs text-muted-foreground">Xodim ko'rishi audit jurnaliga yoziladi.</p>
      <ErrorLine error={messages.error} />
      {messages.busy ? <Spinner /> : <MessagesList messages={messages.data ?? []} canHide={canHide} onHidden={messages.reload} />}
    </div>
  );
}

function BookingDetail({ booking, caps, onDone }: { booking: AdminBookingDTO; caps: CapabilitiesDTO | null; onDone: () => void }) {
  const allowed = applicableCommands(booking).filter((command) => has(caps, COMMAND_CAPABILITY[command]));
  const [command, setCommand] = useState<OperatorBookingCommand | "">(allowed[0] ?? "");
  const [reason, setReason] = useState("");
  const [fault, setFault] = useState<"" | FaultSide>("");
  const [proofKind, setProofKind] = useState<ProofKind>("boarding_code");
  const [feeMode, setFeeMode] = useState<"capture" | "release">("capture");
  const [evidence, setEvidence] = useState("");
  const [showChat, setShowChat] = useState(false);
  const [warnings, setWarnings] = useState<ApiWarning[]>([]);
  const canCancel = has(caps, "ops.booking_cancel");

  async function send(key: string) {
    if (!command) return;
    const result = await adminBookingCommand(
      booking.id,
      command,
      {
        expected_version: booking.version,
        reason: reason.trim(),
        cancel_fault_side: command === "cancel" && fault ? fault : null,
        proof_kind: command === "reissue_proof_code" ? proofKind : null,
        fee_decision: command === "finalize_fee" ? { mode: feeMode } : null,
        evidence_file_ids:
          command === "complete_with_evidence"
            ? evidence.split(",").map((part) => part.trim()).filter(Boolean).slice(0, 10)
            : [],
      },
      key,
    );
    setWarnings(result.warnings);
    setReason("");
    onDone();
  }

  return (
    <div className="grid gap-3">
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Yo'nalish</dt>
          <dd className="text-secondary-foreground">
            {stopText(booking.pickup)} → {stopText(booking.dropoff)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Safar</dt>
          <dd className="font-mono text-xs text-secondary-foreground">{booking.trip_id}</dd>
        </div>
        {booking.client ? (
          <div>
            <dt className="text-xs text-muted-foreground">Mijoz</dt>
            <dd className="text-secondary-foreground">
              {booking.client.display_name}
              {booking.client.contact_phone ? ` · ${booking.client.contact_phone}` : ""}
            </dd>
          </div>
        ) : null}
        {booking.driver ? (
          <div>
            <dt className="text-xs text-muted-foreground">Haydovchi</dt>
            <dd className="text-secondary-foreground">
              {booking.driver.display_name}
              {booking.driver.contact_phone ? ` · ${booking.driver.contact_phone}` : ""}
              {booking.driver.vehicle
                ? ` · ${booking.driver.vehicle.plate_number ?? booking.driver.vehicle.plate_masked ?? ""}`
                : ""}
            </dd>
          </div>
        ) : null}
        {booking.no_show_review ? (
          <div>
            <dt className="text-xs text-muted-foreground">Kelmadi ko'rigi</dt>
            <dd className="text-secondary-foreground">
              {booking.no_show_review.status} · {formatDateTime(booking.no_show_review.reported_at)}
            </dd>
          </div>
        ) : null}
        {booking.custody_case ? (
          <div>
            <dt className="text-xs text-muted-foreground">Saqlov holati</dt>
            <dd className="text-secondary-foreground">
              {booking.custody_case.status} · {booking.custody_case.reason_code}
            </dd>
          </div>
        ) : null}
        {booking.cancelled ? (
          <div>
            <dt className="text-xs text-muted-foreground">Bekor qilingan</dt>
            <dd className="text-secondary-foreground">
              {booking.cancelled.by_side} · {booking.cancelled.fault_side ?? "sabab aniqlanmagan"} ·{" "}
              {formatDateTime(booking.cancelled.at)}
            </dd>
          </div>
        ) : null}
      </dl>

      {warnings.length ? (
        <p className="rounded-[10px] border border-warning/30 bg-warning/8 px-3 py-2 text-sm text-foreground">
          {warnings.map((warning) => warningMessage(warning.code)).join(" · ")}
        </p>
      ) : null}

      {allowed.length === 0 ? (
        <p className="text-sm text-muted-foreground">Bu bron uchun sizning rolingizda buyruq yo'q.</p>
      ) : (
        <div className="grid gap-3 rounded-[12px] border border-border bg-card p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Buyruq">
              <select
                aria-label="Buyruq"
                value={command}
                onChange={(event) => setCommand(event.target.value as OperatorBookingCommand)}
                className={INPUT}
              >
                {allowed.map((value) => (
                  <option key={value} value={value}>
                    {COMMAND_LABEL[value]}
                  </option>
                ))}
              </select>
            </Field>
            {command === "cancel" ? (
              <Field label="Bekor qilish sababi kimda (Q129)">
                <select
                  aria-label="Bekor qilish sababi kimda"
                  value={fault}
                  onChange={(event) => setFault(event.target.value as "" | FaultSide)}
                  className={INPUT}
                >
                  {FAULT_LABEL.map(([value, label]) => (
                    <option key={value || "undetermined"} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {command === "reissue_proof_code" ? (
              <Field label="Kod turi">
                <select
                  aria-label="Kod turi"
                  value={proofKind}
                  onChange={(event) => setProofKind(event.target.value as ProofKind)}
                  className={INPUT}
                >
                  {PROOF_LABEL.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {command === "finalize_fee" ? (
              <Field label="Komissiya qarori">
                <select
                  aria-label="Komissiya qarori"
                  value={feeMode}
                  onChange={(event) => setFeeMode(event.target.value as "capture" | "release")}
                  className={INPUT}
                >
                  <option value="capture">Undirish (hold'dagi summa)</option>
                  <option value="release">Bo'shatish</option>
                </select>
              </Field>
            ) : null}
            {command === "complete_with_evidence" ? (
              <Field label="Dalil fayllari (vergul bilan, ixtiyoriy)">
                <input value={evidence} onChange={(event) => setEvidence(event.target.value)} className={INPUT} />
              </Field>
            ) : null}
          </div>
          <Field label="Sabab (majburiy, audit jurnaliga yoziladi)">
            <textarea aria-label="Sabab" value={reason} onChange={(event) => setReason(event.target.value)} className={TEXTAREA} />
          </Field>
          {command ? (
            <ConfirmButton
              label={COMMAND_LABEL[command]}
              tone={command === "cancel" ? "danger" : "primary"}
              disabled={!reason.trim()}
              question={
                command === "cancel"
                  ? `Bron bekor qilinadi. Sabab: ${FAULT_LABEL.find(([value]) => value === fault)?.[1] ?? ""}. Davom etasizmi?`
                  : `«${COMMAND_LABEL[command]}» bajarilsinmi?`
              }
              onConfirm={send}
            />
          ) : null}
        </div>
      )}
      {!canCancel ? (
        <p className="text-xs text-muted-foreground">Bronni bekor qilish — faqat admin va undan yuqori (Q10).</p>
      ) : null}

      <div className="grid gap-2">
        <Btn onClick={() => setShowChat((value) => !value)}>{showChat ? "Yozishmani yopish" : "Bron yozishmasi"}</Btn>
        {showChat ? <BookingMessages bookingId={booking.id} canHide={has(caps, "ops.trust_review")} /> : null}
      </div>
    </div>
  );
}

function BookingsTab({ caps }: { caps: CapabilitiesDTO | null }) {
  const [queue, setQueue] = useState<AdminBookingQueue>("awaiting_confirmation");
  const [openId, setOpenId] = useState<string | null>(null);
  const bookings = useLoader<AdminBookingDTO[]>(() => listAdminBookings({ queue, limit: 50 }), [queue]);
  const rows = bookings.data ?? [];

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Navbat"
          value={queue}
          onChange={(event) => setQueue(event.target.value as AdminBookingQueue)}
          className={INPUT}
        >
          {ADMIN_BOOKING_QUEUES.map((value) => (
            <option key={value} value={value}>
              {QUEUE_LABEL[value]}
            </option>
          ))}
        </select>
        <Btn onClick={bookings.reload}>
          <RefreshCw size={14} /> Yangilash
        </Btn>
      </div>
      <ErrorLine error={bookings.error} />
      {bookings.busy ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <Empty>Bu navbatda bron yo'q</Empty>
      ) : (
        <ul className="grid gap-2">
          {rows.map((booking) => (
            <li key={booking.id} className="grid gap-3 rounded-[12px] border border-border bg-card p-3 shadow-sm">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="font-mono text-xs text-secondary-foreground">{booking.id}</span>
                <StatusChip>{booking.service_type === "passenger" ? "Yo'lovchi" : "Pochta"}</StatusChip>
                <StatusChip>{booking.service_status}</StatusChip>
                <span className="text-muted-foreground">komissiya: {booking.commission_status}</span>
                <span className="font-semibold text-foreground">{formatMinor(booking.total_minor, booking.currency)}</span>
                <span className="text-muted-foreground">{formatDateTime(booking.created_at)}</span>
                <span className="ml-auto">
                  <Btn onClick={() => setOpenId(openId === booking.id ? null : booking.id)}>
                    {openId === booking.id ? "Yopish" : "Ochish"}
                  </Btn>
                </span>
              </div>
              {openId === booking.id ? <BookingDetail booking={booking} caps={caps} onDone={bookings.reload} /> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- reports and fraud signals (S12, S12b) -----------------------------------------------------------------------

const REVIEW_STATUS_LABEL: Record<string, string> = {
  open: "Ochiq",
  under_review: "Ko'rikda",
  dismissed: "Rad etilgan",
  actioned: "Chora ko'rilgan",
  confirmed: "Tasdiqlangan",
};

const REPORT_REASON_LABEL: Record<string, string> = {
  off_platform_contact: "Platformadan tashqari aloqa",
  fraud_suspicion: "Firibgarlik shubhasi",
  unsafe_behaviour: "Xavfli xatti-harakat",
  no_show: "Kelmadi",
  price_pressure: "Narx bosimi",
  prohibited_item: "Taqiqlangan buyum",
  harassment: "Bezovta qilish",
  other: "Boshqa",
};

const FRAUD_TYPE_LABEL: Record<string, string> = {
  shared_device_accounts: "Bir qurilmada bir nechta akkaunt",
  self_dealing_device: "O'zi bilan bitim (bir qurilma)",
  repeated_pair_bookings: "Bir juftlikning takroriy bronlari",
};

function StatusFilter(props: { value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <select aria-label="Holat" value={props.value} onChange={(event) => props.onChange(event.target.value)} className={INPUT}>
      <option value="">Barchasi</option>
      {props.options.map((value) => (
        <option key={value} value={value}>
          {REVIEW_STATUS_LABEL[value] ?? value}
        </option>
      ))}
    </select>
  );
}

function ReportItem({ report, canReview, onDone, onStrikes }: {
  report: ReportDTO;
  canReview: boolean;
  onDone: () => void;
  onStrikes?: (userId: string) => void;
}) {
  const [note, setNote] = useState("");
  const terminal = report.status === "dismissed" || report.status === "actioned";

  function action(status: "under_review" | "dismissed" | "actioned", label: string, tone: Tone) {
    return (
      <ConfirmButton
        key={status}
        label={label}
        tone={tone}
        question={`Shikoyat holati «${REVIEW_STATUS_LABEL[status]}» bo'ladi. Hech bir akkaunt o'zgarmaydi. Davom etasizmi?`}
        onConfirm={async (key) => {
          await reviewReport(report.id, { expected_version: report.version, status, note: note.trim() || null }, key);
          setNote("");
          onDone();
        }}
      />
    );
  }

  return (
    <li className="grid gap-2 rounded-[12px] border border-border bg-card p-3 text-sm shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-secondary-foreground">{report.id}</span>
        <StatusChip>{REVIEW_STATUS_LABEL[report.status] ?? report.status}</StatusChip>
        <span className="font-semibold text-foreground">{REPORT_REASON_LABEL[report.reason_code] ?? report.reason_code}</span>
        <span className="text-muted-foreground">
          {report.subject_type}: <span className="font-mono text-xs">{report.subject_id}</span>
        </span>
        <span className="text-muted-foreground">{formatDateTime(report.created_at)}</span>
        {report.subject_type === "user" && onStrikes ? (
          <Btn onClick={() => onStrikes(report.subject_id)}>Strike'lar</Btn>
        ) : null}
      </div>
      {report.details ? <p className="text-secondary-foreground">{report.details}</p> : null}
      {canReview && !terminal ? (
        <div className="grid gap-2">
          <Field label="Izoh (ixtiyoriy)">
            <textarea aria-label="Izoh" value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {report.status === "open" ? action("under_review", "Ko'rikka olish", "neutral") : null}
            {action("dismissed", "Rad etish", "neutral")}
            {action("actioned", "Chora ko'rildi", "primary")}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function ReportsTab({ caps, onStrikes }: { caps: CapabilitiesDTO | null; onStrikes: (userId: string) => void }) {
  const [status, setStatus] = useState("open");
  const reports = useLoader<ReportDTO[]>(() => listReports({ status: status || undefined, limit: 50 }), [status]);
  const canReview = has(caps, "ops.trust_review");
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">Shikoyat qarori faqat qayd qilinadi: bron yoki reyting o'zgarmaydi.</p>
      <div className="flex flex-wrap items-center gap-2">
        <StatusFilter value={status} onChange={setStatus} options={["open", "under_review", "dismissed", "actioned"]} />
        <Btn onClick={reports.reload}>
          <RefreshCw size={14} /> Yangilash
        </Btn>
      </div>
      <ErrorLine error={reports.error} />
      {reports.busy ? (
        <Spinner />
      ) : (reports.data ?? []).length === 0 ? (
        <Empty>Shikoyat yo'q</Empty>
      ) : (
        <ul className="grid gap-2">
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
  const [note, setNote] = useState("");
  const terminal = signal.status === "dismissed" || signal.status === "confirmed";

  function action(status: "under_review" | "dismissed" | "confirmed", label: string, tone: Tone) {
    return (
      <ConfirmButton
        key={status}
        label={label}
        tone={tone}
        question={`Signal holati «${REVIEW_STATUS_LABEL[status]}» bo'ladi. Bu hech kimni avtomatik bloklamaydi. Davom etasizmi?`}
        onConfirm={async (key) => {
          await reviewFraudSignal(signal.id, { expected_version: signal.version, status, note: note.trim() || null }, key);
          setNote("");
          onDone();
        }}
      />
    );
  }

  return (
    <li className="grid gap-2 rounded-[12px] border border-border bg-card p-3 text-sm shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-secondary-foreground">{signal.id}</span>
        <StatusChip>{REVIEW_STATUS_LABEL[signal.status] ?? signal.status}</StatusChip>
        <span className="font-semibold text-foreground">{FRAUD_TYPE_LABEL[signal.signal_type] ?? signal.signal_type}</span>
        <span className="font-mono text-xs text-muted-foreground">{signal.subject_user_id}</span>
        <span className="text-muted-foreground">{formatDateTime(signal.detected_at)}</span>
        <Btn onClick={() => onStrikes(signal.subject_user_id)}>Strike'lar</Btn>
      </div>
      <p className="text-xs text-muted-foreground">Dalil: {evidenceText(signal.evidence)}</p>
      {canReview && !terminal ? (
        <div className="grid gap-2">
          <Field label="Izoh (ixtiyoriy)">
            <textarea aria-label="Izoh" value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {signal.status === "open" ? action("under_review", "Ko'rikka olish", "neutral") : null}
            {action("dismissed", "Asossiz", "neutral")}
            {action("confirmed", "Tasdiqlash", "danger")}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function FraudTab({ caps, onStrikes }: { caps: CapabilitiesDTO | null; onStrikes: (userId: string) => void }) {
  const [status, setStatus] = useState("open");
  const signals = useLoader<FraudSignalDTO[]>(() => listFraudSignals({ status: status || undefined, limit: 50 }), [status]);
  const canReview = has(caps, "ops.trust_review");
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        Signal — odam uchun savol, hukm emas: hech bir signal hech kimni bloklamagan, undirmagan yoki pastga tushirmagan.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <StatusFilter value={status} onChange={setStatus} options={["open", "under_review", "dismissed", "confirmed"]} />
        <Btn onClick={signals.reload}>
          <RefreshCw size={14} /> Yangilash
        </Btn>
      </div>
      <ErrorLine error={signals.error} />
      {signals.busy ? (
        <Spinner />
      ) : (signals.data ?? []).length === 0 ? (
        <Empty>Signal yo'q</Empty>
      ) : (
        <ul className="grid gap-2">
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
  const [input, setInput] = useState(initialUserId);
  const [userId, setUserId] = useState(initialUserId);
  const strikes = useLoader<UserStrikesDTO>(() => userStrikes(userId), [userId], Boolean(userId));

  useEffect(() => {
    setInput(initialUserId);
    setUserId(initialUserId);
  }, [initialUserId]);

  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        Pilotda jarima yo'q: strike'lar operator navbatiga signal beradi. Chatdagi 6 xonali kodlar strike emas (Q85).
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Foydalanuvchi ID">
          <input aria-label="Foydalanuvchi ID" value={input} onChange={(event) => setInput(event.target.value)} className={INPUT} />
        </Field>
        <Btn tone="primary" disabled={!input.trim()} onClick={() => setUserId(input.trim())}>
          Ko'rish
        </Btn>
      </div>
      <ErrorLine error={strikes.error} />
      {!userId ? null : strikes.busy ? (
        <Spinner />
      ) : strikes.data ? (
        <div className="grid gap-2">
          <p className="text-sm text-foreground">
            Oxirgi {strikes.data.window_days} kunda: <strong>{strikes.data.strikes_in_window}</strong> ta strike
          </p>
          {strikes.data.strikes.length === 0 ? (
            <Empty>Strike yo'q</Empty>
          ) : (
            <ul className="grid gap-1">
              {strikes.data.strikes.map((strike, index) => (
                <li key={`${strike.occurred_at}-${index}`} className="rounded-[10px] border border-border bg-card px-3 py-2 text-sm">
                  {formatDateTime(strike.occurred_at)} · {strike.subject_type} · {strike.reason_code}
                  {strike.categories.length ? ` · ${strike.categories.join(", ")}` : ""}
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
      <p className="text-sm text-muted-foreground">
        Taklif yozishmasi faqat o'qiladi (Q100). Har ko'rish audit jurnaliga yoziladi.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Yozishma turi">
          <select
            aria-label="Yozishma turi"
            value={kind}
            onChange={(event) => setKind(event.target.value as "booking" | "proposal")}
            className={INPUT}
          >
            <option value="booking">Bron chati</option>
            <option value="proposal">Taklif yozishmasi</option>
          </select>
        </Field>
        <Field label={kind === "booking" ? "Bron ID" : "Taklif oqimi ID"}>
          <input aria-label="Yozishma ID" value={input} onChange={(event) => setInput(event.target.value)} className={INPUT} />
        </Field>
        <Btn tone="primary" disabled={!input.trim()} onClick={() => setTarget({ kind, id: input.trim() })}>
          Ochish
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

const FRESHNESS_LABEL: Record<string, string> = {
  fresh: "Yangi (≤ 30 s)",
  delayed: "Kechikmoqda (31–120 s)",
  lost: "Aloqa uzilgan (> 120 s)",
  no_data: "Ma'lumot yo'q",
};

function TrackingTab() {
  const [input, setInput] = useState("");
  const [tripId, setTripId] = useState("");
  const tracking = useLoader<TripTrackingAdminDTO>(() => adminTripTracking(tripId), [tripId], Boolean(tripId));
  const data = tracking.data;
  const point = data?.last_point;

  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        Kuzatuv oynasi yopiq bo'lsa ham oxirgi nuqta xizmat vazifasi uchun ko'rsatiladi; har ko'rish audit jurnaliga
        yoziladi (Q86).
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Safar ID">
          <input aria-label="Safar ID" value={input} onChange={(event) => setInput(event.target.value)} className={INPUT} />
        </Field>
        <Btn tone="primary" disabled={!input.trim()} onClick={() => setTripId(input.trim())}>
          Ko'rish
        </Btn>
      </div>
      <ErrorLine error={tracking.error} />
      {!tripId ? null : tracking.busy ? (
        <Spinner />
      ) : data ? (
        <dl className="grid gap-2 rounded-[12px] border border-border bg-card p-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Oxirgi ishonchli nuqta yangiligi</dt>
            <dd className="font-semibold text-foreground">{FRESHNESS_LABEL[data.freshness] ?? data.freshness}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Kuzatuv sessiyasi</dt>
            <dd className="text-secondary-foreground">
              {data.active_session ? `ochiq (${formatDateTime(data.session_started_at)} dan)` : "yopiq"}
            </dd>
          </div>
          {point ? (
            <>
              <div>
                <dt className="text-xs text-muted-foreground">Koordinata</dt>
                <dd className="font-mono text-xs text-secondary-foreground">
                  {point.lat.toFixed(5)}, {point.lng.toFixed(5)} (±{point.accuracy_m} m
                  {point.low_accuracy ? ", past aniqlik" : ""})
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Olingan / qabul qilingan</dt>
                <dd className="text-secondary-foreground">
                  {formatDateTime(point.captured_at)} / {formatDateTime(point.received_at)}
                </dd>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Ishonchli nuqta yo'q.</p>
          )}
        </dl>
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
  kind: "request" as "request" | "trip_offer",
  service: "passenger" as "passenger" | "parcel",
  tripId: "",
  originStop: "",
  destinationStop: "",
  start: "",
  end: "",
  basis: "per_seat" as "per_seat" | "total",
  price: "",
  seats: "1",
  parcelType: "box" as (typeof PARCEL_TYPES)[number],
  weightKg: "",
  comment: "",
};

export function onBehalfBody(form: typeof EMPTY_FORM): ListingOnBehalfBody | null {
  const start = tashkentIso(form.start);
  const end = tashkentIso(form.end);
  const price = Math.round(Number(form.price.replace(/\s/g, "")));
  const seats = Math.round(Number(form.seats));
  if (!form.owner.trim() || form.consent.trim().length < 3 || !start || !end || !(price > 0)) return null;
  if (!form.originStop.trim() || !form.destinationStop.trim()) return null;
  if (form.service === "passenger" && !(seats >= 1 && seats <= 8)) return null;
  const weight = form.weightKg.trim() ? Math.round(Number(form.weightKg) * 1000) : null;
  return {
    owner_user_id: form.owner.trim(),
    consent_reference: form.consent.trim(),
    kind: form.kind,
    service_type: form.service,
    trip_id: form.kind === "trip_offer" && form.tripId.trim() ? form.tripId.trim() : null,
    origin_stop_id: form.originStop.trim(),
    destination_stop_id: form.destinationStop.trim(),
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
        ? { parcel_type: form.parcelType, weight_g: weight && weight > 0 ? weight : null, fragile: false }
        : null,
  };
}

function OnBehalfTab({ caps }: { caps: CapabilitiesDTO | null }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [created, setCreated] = useState<{ listing: AdminListingDTO; warnings: ApiWarning[] } | null>(null);
  const body = onBehalfBody(form);
  const set = <K extends keyof typeof EMPTY_FORM>(key: K, value: (typeof EMPTY_FORM)[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  if (!has(caps, "ops.booking_command")) {
    return <Empty>Boshqa foydalanuvchi nomidan e'lon yaratish sizning rolingizda yo'q.</Empty>;
  }

  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        E'lon egasi — haqiqiy foydalanuvchi; siz audit'da «operator yaratgan» deb yozilasiz. Egasining roziligi
        (qo'ng'iroq yoki murojaat raqami) majburiy (§20.2).
      </p>
      {created ? (
        <div className="rounded-[12px] border border-success/30 bg-success/10 px-3 py-2 text-sm text-foreground">
          E'lon yaratildi: <span className="font-mono">{created.listing.id}</span> ({created.listing.status})
          {created.warnings.length ? (
            <p className="mt-1 text-xs">{created.warnings.map((warning) => warningMessage(warning.code)).join(" · ")}</p>
          ) : null}
        </div>
      ) : null}
      <div className="grid gap-3 rounded-[12px] border border-border bg-card p-3 sm:grid-cols-2">
        <Field label="Egasi (foydalanuvchi ID) *">
          <input aria-label="Egasi" value={form.owner} onChange={(event) => set("owner", event.target.value)} className={INPUT} />
        </Field>
        <Field label="Rozilik dalili *" hint="Masalan: murojaat raqami yoki qo'ng'iroq yozuvi; kamida 3 belgi.">
          <input
            aria-label="Rozilik dalili"
            required
            value={form.consent}
            onChange={(event) => set("consent", event.target.value)}
            className={INPUT}
          />
        </Field>
        <Field label="E'lon turi">
          <select value={form.kind} onChange={(event) => set("kind", event.target.value as "request" | "trip_offer")} className={INPUT}>
            <option value="request">So'rov (mijoz)</option>
            <option value="trip_offer">Safar taklifi (haydovchi)</option>
          </select>
        </Field>
        <Field label="Xizmat">
          <select value={form.service} onChange={(event) => set("service", event.target.value as "passenger" | "parcel")} className={INPUT}>
            <option value="passenger">Yo'lovchi</option>
            <option value="parcel">Pochta</option>
          </select>
        </Field>
        {form.kind === "trip_offer" ? (
          <Field label="Safar ID">
            <input value={form.tripId} onChange={(event) => set("tripId", event.target.value)} className={INPUT} />
          </Field>
        ) : null}
        <Field label="Jo'nash bekati ID *">
          <input aria-label="Jo'nash bekati" value={form.originStop} onChange={(event) => set("originStop", event.target.value)} className={INPUT} />
        </Field>
        <Field label="Borish bekati ID *">
          <input
            aria-label="Borish bekati"
            value={form.destinationStop}
            onChange={(event) => set("destinationStop", event.target.value)}
            className={INPUT}
          />
        </Field>
        <Field label="Jo'nash oynasi boshi (Toshkent) *">
          <input aria-label="Oyna boshi" type="datetime-local" value={form.start} onChange={(event) => set("start", event.target.value)} className={INPUT} />
        </Field>
        <Field label="Jo'nash oynasi oxiri (Toshkent) *">
          <input aria-label="Oyna oxiri" type="datetime-local" value={form.end} onChange={(event) => set("end", event.target.value)} className={INPUT} />
        </Field>
        {form.service === "passenger" ? (
          <>
            <Field label="Narx asosi">
              <select value={form.basis} onChange={(event) => set("basis", event.target.value as "per_seat" | "total")} className={INPUT}>
                <option value="per_seat">Bir o'rin uchun</option>
                <option value="total">Jami</option>
              </select>
            </Field>
            <Field label="O'rinlar soni">
              <input aria-label="O'rinlar" inputMode="numeric" value={form.seats} onChange={(event) => set("seats", event.target.value)} className={INPUT} />
            </Field>
          </>
        ) : (
          <>
            <Field label="Jo'natma turi">
              <select
                value={form.parcelType}
                onChange={(event) => set("parcelType", event.target.value as (typeof PARCEL_TYPES)[number])}
                className={INPUT}
              >
                {PARCEL_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Og'irligi (kg, ixtiyoriy)">
              <input inputMode="decimal" value={form.weightKg} onChange={(event) => set("weightKg", event.target.value)} className={INPUT} />
            </Field>
          </>
        )}
        <Field label="Narx (so'm) *">
          <input aria-label="Narx" inputMode="numeric" value={form.price} onChange={(event) => set("price", event.target.value)} className={INPUT} />
        </Field>
        <Field label="Izoh" hint="Telefon va boshqa aloqa ma'lumotlari server tomonidan maskalanadi (Q43).">
          <input value={form.comment} onChange={(event) => set("comment", event.target.value)} className={INPUT} />
        </Field>
      </div>
      <ConfirmButton
        label="E'lon yaratish"
        tone="primary"
        disabled={!body}
        question="E'lon egasi nomidan yaratiladi va audit jurnaliga yoziladi. Egasining roziligi olinganini tasdiqlaysizmi?"
        onConfirm={async (key) => {
          if (!body) return;
          const result = await createListingOnBehalf(body, key);
          setCreated({ listing: result.data, warnings: result.warnings });
          setForm(EMPTY_FORM);
        }}
      />
    </div>
  );
}

// --- the panel ---------------------------------------------------------------------------------------------------

export function AdminTrustPanel({ initialTab = "bookings" }: { initialTab?: TrustTab } = {}) {
  const [tab, setTab] = useState<TrustTab>(initialTab);
  const [strikeUser, setStrikeUser] = useState("");
  const caps = useLoader<CapabilitiesDTO>(() => capabilities(), []);

  function openStrikes(userId: string) {
    setStrikeUser(userId);
    setTab("strikes");
  }

  return (
    <section className="grid gap-4">
      <header className="grid gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Ishonch va operatsiyalar</h2>
          <p className="text-sm text-muted-foreground">
            Tugmalar faqat rolingiz ruxsat bergan amallar uchun ko'rinadi; server rad etsa, sababi ko'rsatiladi.
          </p>
        </div>
        <nav className="flex flex-wrap gap-2" role="tablist">
          {TABS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={tab === value}
              onClick={() => setTab(value)}
              className={`el-press inline-flex h-9 items-center rounded-[10px] border px-3 text-sm font-semibold ${
                tab === value ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-secondary-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      <ErrorLine error={caps.error} />
      {caps.busy ? (
        <Spinner />
      ) : (
        <>
          {tab === "bookings" ? <BookingsTab caps={caps.data} /> : null}
          {tab === "reports" ? <ReportsTab caps={caps.data} onStrikes={openStrikes} /> : null}
          {tab === "fraud" ? <FraudTab caps={caps.data} onStrikes={openStrikes} /> : null}
          {tab === "strikes" ? <StrikesTab initialUserId={strikeUser} /> : null}
          {tab === "chat" ? <ChatTab caps={caps.data} /> : null}
          {tab === "tracking" ? <TrackingTab /> : null}
          {tab === "on_behalf" ? <OnBehalfTab caps={caps.data} /> : null}
        </>
      )}
    </section>
  );
}
