/**
 * Finance staff panel (Q17, Q49, Q55, Q69, Q70, Q2, Q28, §9.2): top-ups, ledger adjustments, commission policy,
 * reconciliation and reports.
 *
 * Honesty rules shown on screen, not only in code:
 * - a pending top-up or its screenshot is a *request*, not money; money exists after an approval against a bank
 *   statement or cashier receipt (large amounts: a second, different finance person);
 * - "calculated commission" is a hold, not received money;
 * - a Q48/Q70 production refusal (`503 PRODUCTION_INVARIANTS_FAILED`) is shown as the launch gate it is.
 *
 * The server decides every permission. The panel hides buttons the current capabilities (`/me/capabilities`) or
 * the two-person rule would refuse, asks for a confirmation before every money command, keeps one Idempotency-Key
 * per confirmed action (a retry replays, never posts twice) and asks for the MFA code when the server wants a
 * step-up.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  approveAdjustment,
  approveTopup,
  confirmCommissionPolicy,
  createAdjustment,
  createCommissionPolicy,
  endCommissionPolicy,
  financeMe,
  financeReconciliation,
  financeReport,
  listAdjustments,
  listCommissionPolicies,
  listTopups,
  promoReport,
  rejectAdjustment,
  rejectTopup,
  splitAdjustmentSignals,
  withdrawAdjustment,
  type AdjustmentStatusFilter,
  type CommissionPolicyDTO,
  type CommissionPolicyKind,
  type FinanceReportDTO,
  type FinanceReportName,
  type LedgerAdjustmentDTO,
  type LedgerTransactionDTO,
  type Page,
  type PromoReportDTO,
  type PromoReportGroupBy,
  type ReconciliationDTO,
  type SplitAdjustmentSignalDTO,
  type TopupAdminDTO,
  type TopupStatus,
} from "../api/v2/admin-finance.api";
import { newIdempotencyKey } from "../api/v2/http";
import { stepUp } from "../api/v2/mfa.api";
import { capabilities as loadCapabilities } from "../api/v2/ops.api";
import { formatDate, formatDateTime, formatMinor } from "../utils/v2Format";
import {
  ADJUSTMENT_STATUS,
  CAP,
  REPORTS,
  TOPUP_STATUS,
  adjustmentActions,
  daysBefore,
  financeErrorMessage,
  isGateRefusal,
  isPostedTransaction,
  isStepUp,
  label,
  parseSoumToMinor,
  tashkentLocalToIso,
  tashkentToday,
  topupActions,
  type Capabilities,
} from "./finance";
import { ShieldAlert } from "./ui/icons";

// --- small building blocks ----------------------------------------------------------------------------------------

function Btn(props: { children: ReactNode; onClick: () => void; disabled?: boolean; tone?: "primary" | "danger" | "neutral" }) {
  const tone = props.tone ?? "neutral";
  const cls =
    tone === "primary"
      ? "border-primary bg-primary text-primary-foreground"
      : tone === "danger"
        ? "border-destructive/25 bg-destructive/10 text-destructive"
        : "border-border bg-card text-secondary-foreground";
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-9 items-center justify-center rounded-[10px] border px-3 text-sm font-semibold ${cls} disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function Field(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  type?: "text" | "date" | "datetime-local";
  inputMode?: "numeric" | "decimal" | "text";
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      <input
        type={props.type ?? "text"}
        inputMode={props.inputMode}
        value={props.value}
        placeholder={props.placeholder}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3 text-foreground outline-none"
      />
      {props.hint && <span className="text-xs text-muted-foreground">{props.hint}</span>}
    </label>
  );
}

function Select<T extends string>(props: { label: string; value: T; onChange: (v: T) => void; options: Array<[T, string]> }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      <select
        value={props.value}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value as T)}
        className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3"
      >
        {props.options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function Loading() {
  return (
    <p className="text-sm text-muted-foreground" aria-busy="true">
      Yuklanmoqda...
    </p>
  );
}

function Note({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "warning" | "success" | "danger" }) {
  const cls =
    tone === "warning"
      ? "bg-warning/10 text-warning"
      : tone === "success"
        ? "bg-success/10 text-success"
        : tone === "danger"
          ? "bg-destructive/10 text-destructive"
          : "bg-muted/60 text-secondary-foreground";
  return <p className={`rounded-[10px] px-3 py-2 text-sm ${cls}`}>{children}</p>;
}

function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="alert">
      <Note tone={isGateRefusal(error) ? "warning" : "danger"}>{financeErrorMessage(error)}</Note>
      {onRetry && <Btn onClick={onRetry}>Qayta urinish</Btn>}
    </div>
  );
}

/** Loads a cursor page and appends the next one on demand. */
function usePaged<T>(load: (cursor: string | null) => Promise<Page<T>>, deps: unknown[]) {
  const [items, setItems] = useState<T[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loader = useCallback(load, deps);

  const reload = useCallback(() => {
    setBusy(true);
    setError(null);
    setItems(null);
    loader(null)
      .then((page) => {
        setItems(page.items);
        setCursor(page.nextCursor);
      })
      .catch(setError)
      .finally(() => setBusy(false));
  }, [loader]);

  const more = () => {
    if (!cursor) return;
    setBusy(true);
    loader(cursor)
      .then((page) => {
        setItems((prev) => [...(prev ?? []), ...page.items]);
        setCursor(page.nextCursor);
      })
      .catch(setError)
      .finally(() => setBusy(false));
  };

  useEffect(reload, [reload]);
  return { items, error, busy, reload, more, hasMore: cursor !== null };
}

type Pending = { text: string; key: string; work: (key: string) => Promise<void> };

/**
 * One money command: confirm first, then run with an Idempotency-Key minted at confirmation and kept for every retry
 * of *this* action (step-up retry and the error "Qayta urinish" replay the same key).
 */
function useMoneyAction() {
  const [pending, setPending] = useState<Pending | null>(null);
  const [running, setRunning] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [needCode, setNeedCode] = useState(false);
  const [code, setCode] = useState("");
  const [done, setDone] = useState<string | null>(null);

  function ask(text: string, work: (key: string) => Promise<void>) {
    setError(null);
    setDone(null);
    setNeedCode(false);
    setPending({ text, key: newIdempotencyKey(), work });
  }

  async function run(action: Pending) {
    setBusy(true);
    setError(null);
    setRunning(action);
    try {
      await action.work(action.key);
      setRunning(null);
    } catch (cause) {
      if (isStepUp(cause)) setNeedCode(true);
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  function confirm() {
    if (!pending) return;
    const action = pending;
    setPending(null);
    void run(action);
  }

  async function prove() {
    if (!running) return;
    setBusy(true);
    setError(null);
    try {
      await stepUp(code.trim());
      setNeedCode(false);
      setCode("");
    } catch (cause) {
      setError(cause);
      setBusy(false);
      return;
    }
    await run(running);
  }

  const view = (
    <>
      {pending && (
        <div className="space-y-2 rounded-[12px] border border-warning/40 bg-warning/8 p-3" role="dialog" aria-label="Tasdiqlash">
          <p className="text-sm font-semibold text-foreground">{pending.text}</p>
          <div className="flex flex-wrap gap-2">
            <Btn tone="primary" disabled={busy} onClick={confirm}>
              Ha, bajarish
            </Btn>
            <Btn disabled={busy} onClick={() => setPending(null)}>
              Bekor qilish
            </Btn>
          </div>
        </div>
      )}
      {done && <Note tone="success">{done}</Note>}
      {error !== null && !needCode && (
        <div className="flex flex-wrap items-center gap-2" role="alert">
          <Note tone={isGateRefusal(error) ? "warning" : "danger"}>{financeErrorMessage(error)}</Note>
          {running && !isGateRefusal(error) && (
            <Btn disabled={busy} onClick={() => void run(running)}>
              Qayta urinish
            </Btn>
          )}
        </div>
      )}
      {needCode && running && (
        <div className="flex flex-wrap items-end gap-2 rounded-[12px] border border-warning/30 bg-warning/8 p-3">
          <ShieldAlert size={18} color="var(--warning)" />
          <Field label="Autentifikator kodi" value={code} onChange={setCode} placeholder="123456" inputMode="numeric" />
          <Btn tone="primary" disabled={busy || code.trim().length < 6} onClick={() => void prove()}>
            Tasdiqlash va davom etish
          </Btn>
          <p className="w-full text-xs text-muted-foreground">
            Pul amallari uchun yaqinda tasdiqlangan MFA kerak. Faol MFA faktori bo'lmasa uni «Xavfsizlik (MFA)» bo'limida
            ulang.
          </p>
          {error !== null && !isStepUp(error) && <p className="w-full text-sm text-destructive">{financeErrorMessage(error)}</p>}
        </div>
      )}
    </>
  );
  return { ask, busy, view, setDone };
}

// --- top-ups ------------------------------------------------------------------------------------------------------

type ApproveForm = { source_type: "bank_statement" | "cashier_receipt"; source_reference: string; amount: string; received_at: string; note: string };

function minorToSoumText(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "";
  const major = Math.trunc(minor / 100);
  const rest = minor % 100;
  return rest === 0 ? String(major) : `${major},${String(rest).padStart(2, "0")}`;
}

function isoToTashkentLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() + 5 * 3600 * 1000).toISOString().slice(0, 16);
}

function initialApproveForm(topup: TopupAdminDTO): ApproveForm {
  const ev = topup.evidence;
  // Second step: the second approver repeats the first approval's source and amount (the server compares them).
  return {
    source_type: ev.source_type ?? "bank_statement",
    source_reference: ev.source_reference ?? "",
    amount: minorToSoumText(ev.received_amount_minor),
    received_at: isoToTashkentLocal(ev.received_at),
    note: "",
  };
}

function TopupRow({ topup, meId, caps, onChanged }: { topup: TopupAdminDTO; meId: string | null; caps: Capabilities; onChanged: (message?: string) => void }) {
  const actions = topupActions(topup, meId, caps);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ApproveForm>(() => initialApproveForm(topup));
  const [reason, setReason] = useState("");
  const money = useMoneyAction();
  const received = parseSoumToMinor(form.amount);
  const receivedAt = tashkentLocalToIso(form.received_at);
  const ev = topup.evidence;
  const differs = received !== null && received !== topup.amount_minor;

  const approve = () =>
    money.ask(
      actions.secondStep
        ? `Ikkinchi tasdiq: ${formatMinor(received)} haydovchi hamyoniga o'tadi. Manba: ${form.source_reference.trim()}. Davom etasizmi?`
        : `${formatMinor(received)} bank/kassa hujjati «${form.source_reference.trim()}» bilan tasdiqlanadi. Katta summa bo'lsa ikkinchi xodim tasdig'ini kutadi. Davom etasizmi?`,
      async (key) => {
        const next = await approveTopup(
          topup.id,
          {
            expected_version: topup.version,
            source_type: form.source_type,
            source_reference: form.source_reference.trim(),
            received_amount_minor: received as number,
            received_at: receivedAt as string,
            note: form.note.trim() || null,
          },
          key,
        );
        setOpen(false);
        onChanged(
          next.status === "approved"
            ? `Tasdiqlandi: ${formatMinor(next.evidence.received_amount_minor ?? received)} haydovchi balansiga o'tdi.`
            : "Birinchi tasdiq yozildi. Katta summa: boshqa moliya xodimi ikkinchi marta tasdiqlamaguncha balansga o'tmaydi.",
        );
      },
    );

  const reject = () =>
    money.ask(`Top-up so'rovi rad etiladi (sabab: «${reason.trim()}»). Haydovchi balansi o'zgarmaydi. Davom etasizmi?`, async (key) => {
      await rejectTopup(topup.id, { expected_version: topup.version, reason: reason.trim() }, key);
      setOpen(false);
      onChanged("Top-up so'rovi rad etildi.");
    });

  return (
    <div className="space-y-2 rounded-[12px] border border-border bg-card p-3 text-sm" data-testid={`topup-${topup.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold text-foreground">
          {formatMinor(topup.amount_minor)} · {topup.method === "bank_transfer" ? "bank o'tkazmasi" : "kassa"} ·{" "}
          {label(TOPUP_STATUS, topup.status)}
        </p>
        <span className="text-xs text-muted-foreground">{formatDateTime(topup.created_at)}</span>
      </div>
      <p className="break-words text-xs text-muted-foreground">
        Haydovchi: {topup.driver.id ?? "-"} · So'rov: {topup.id}
        {topup.first_approver?.id ? ` · 1-tasdiq: ${topup.first_approver.id}` : ""}
        {topup.second_approver?.id ? ` · 2-tasdiq: ${topup.second_approver.id}` : ""}
      </p>
      {(topup.status === "pending" || topup.status === "awaiting_second_approval") && (
        <p className="text-xs text-warning">
          {topup.status === "pending"
            ? "Bu haydovchining so'rovi — hali pul emas. Skrinshot yoki to'lovchi izohi to'lov dalili hisoblanmaydi: bank ko'chirmasi yoki kassa kvitansiyasini tekshiring."
            : "Birinchi tasdiq bor, lekin pul hali balansga o'tmagan."}
        </p>
      )}
      <p className="break-words text-xs text-secondary-foreground">
        Haydovchi ko'rsatgan: to'lovchi {ev.payer_reference ?? "-"}
        {ev.note ? ` · izoh: ${ev.note}` : ""}
        {ev.evidence_file_id ? ` · fayl: ${ev.evidence_file_id}` : ""}
        {ev.source_reference ? ` · tasdiqlangan manba: ${ev.source_type === "cashier_receipt" ? "kassa" : "bank"} ${ev.source_reference}` : ""}
        {ev.received_amount_minor !== null ? ` · qabul qilingan: ${formatMinor(ev.received_amount_minor)}` : ""}
      </p>
      {actions.note && <p className="text-xs text-muted-foreground">{actions.note}</p>}
      {(actions.approve || actions.reject) && !open && (
        <Btn onClick={() => setOpen(true)}>Ko'rib chiqish</Btn>
      )}
      {open && (
        <div className="space-y-3 rounded-[12px] border border-border p-3">
          {actions.approve && (
            <div className="grid gap-2 md:grid-cols-2">
              <Select
                label="Manba turi"
                value={form.source_type}
                onChange={(v) => setForm({ ...form, source_type: v })}
                options={[
                  ["bank_statement", "Bank ko'chirmasi"],
                  ["cashier_receipt", "Kassa kvitansiyasi"],
                ]}
              />
              <Field label="Hujjat raqami" value={form.source_reference} onChange={(v) => setForm({ ...form, source_reference: v })} />
              <Field
                label="Haqiqatda qabul qilingan summa (so'm)"
                value={form.amount}
                inputMode="decimal"
                onChange={(v) => setForm({ ...form, amount: v })}
                hint={differs ? `So'ralgan summadan (${formatMinor(topup.amount_minor)}) farq qiladi — hujjatdagi summani kiriting.` : undefined}
              />
              <Field
                label="Qabul qilingan vaqt (Toshkent)"
                type="datetime-local"
                value={form.received_at}
                onChange={(v) => setForm({ ...form, received_at: v })}
              />
              <div className="md:col-span-2">
                <Field label="Izoh (ixtiyoriy)" value={form.note} onChange={(v) => setForm({ ...form, note: v })} />
              </div>
              {actions.secondStep && (
                <p className="md:col-span-2 text-xs text-muted-foreground">
                  Ikkinchi tasdiq: manba turi, hujjat raqami va summa birinchi tasdiqdagisi bilan bir xil bo'lishi shart.
                </p>
              )}
              <div className="md:col-span-2">
                <Btn
                  tone="primary"
                  disabled={money.busy || received === null || !receivedAt || !form.source_reference.trim()}
                  onClick={approve}
                >
                  Tasdiqlash
                </Btn>
              </div>
            </div>
          )}
          {actions.reject && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Rad etish sababi" value={reason} onChange={setReason} />
              <Btn tone="danger" disabled={money.busy || !reason.trim()} onClick={reject}>
                Rad etish
              </Btn>
            </div>
          )}
          <Btn onClick={() => setOpen(false)}>Yopish</Btn>
        </div>
      )}
      {money.view}
    </div>
  );
}

function TopupsTab({ meId, caps }: { meId: string | null; caps: Capabilities }) {
  const [status, setStatus] = useState<TopupStatus | "all">("pending");
  const list = usePaged<TopupAdminDTO>(
    (cursor) => listTopups({ status: status === "all" ? undefined : status, cursor, limit: 50 }),
    [status],
  );
  const [flash, setFlash] = useState<string | null>(null);
  const changed = (message?: string) => {
    setFlash(message ?? null);
    list.reload();
  };
  return (
    <div className="space-y-3">
      <Note>
        Haydovchi hamyoni — komissiya uchun oldindan to'lov. So'rov va skrinshot pul emas: balans faqat hujjat bilan
        tasdiqlangandan keyin o'zgaradi. Katta summani ikki turli moliya xodimi tasdiqlaydi.
      </Note>
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label="Holat"
          value={status}
          onChange={setStatus}
          options={[
            ["pending", "Kutilmoqda"],
            ["awaiting_second_approval", "Ikkinchi tasdiq kutilmoqda"],
            ["approved", "Tasdiqlangan"],
            ["rejected", "Rad etilgan"],
            ["all", "Hammasi"],
          ]}
        />
        <Btn onClick={list.reload}>Yangilash</Btn>
      </div>
      {flash && <Note tone="success">{flash}</Note>}
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.items === null && !list.error && <Loading />}
      {list.items !== null && list.items.length === 0 && <p className="text-sm text-muted-foreground">Bu holatda top-up so'rovi yo'q.</p>}
      {(list.items ?? []).map((topup) => (
        <TopupRow key={`${topup.id}:${topup.version}`} topup={topup} meId={meId} caps={caps} onChanged={changed} />
      ))}
      {list.hasMore && (
        <Btn disabled={list.busy} onClick={list.more}>
          Ko'proq
        </Btn>
      )}
    </div>
  );
}

// --- adjustments --------------------------------------------------------------------------------------------------

function AdjustmentRow({ row, meId, caps, onChanged }: { row: LedgerAdjustmentDTO; meId: string | null; caps: Capabilities; onChanged: (message?: string) => void }) {
  const actions = adjustmentActions(row, meId, caps);
  const [text, setText] = useState("");
  const money = useMoneyAction();
  const what = `${row.direction === "credit" ? "hamyonga qo'shish" : "hamyondan ayirish"} ${formatMinor(row.amount_minor)} (${row.wallet_id})`;
  return (
    <div className="space-y-2 rounded-[12px] border border-border bg-card p-3 text-sm" data-testid={`adjustment-${row.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold text-foreground">
          {row.direction === "credit" ? "Kredit (+)" : "Debit (−)"} {formatMinor(row.amount_minor)} · {label(ADJUSTMENT_STATUS, row.status)}
        </p>
        <span className="text-xs text-muted-foreground">{formatDateTime(row.created_at)}</span>
      </div>
      <p className="break-words text-xs text-muted-foreground">
        Hamyon: {row.wallet_id} · So'rovchi: {row.requested_by.id ?? "-"}
        {row.approved_by?.id ? ` · tasdiqladi: ${row.approved_by.id}` : ""}
        {row.rejected_by?.id ? ` · rad etdi: ${row.rejected_by.id}` : ""}
        {row.pending_age_seconds != null ? ` · kutmoqda: ${Math.floor(row.pending_age_seconds / 3600)} soat` : ""}
      </p>
      <p className="text-secondary-foreground">Sabab: {row.reason}</p>
      {row.reject_reason && <p className="text-xs text-destructive">Rad sababi: {row.reject_reason}</p>}
      {row.transaction && <p className="text-xs text-muted-foreground">Ledger: {row.transaction.id} ({row.transaction.reference})</p>}
      {actions.note && <p className="text-xs text-muted-foreground">{actions.note}</p>}
      {(actions.approve || actions.reject || actions.withdraw) && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={actions.withdraw ? "Izoh (ixtiyoriy)" : "Izoh / rad sababi"} value={text} onChange={setText} />
          {actions.approve && (
            <Btn
              tone="primary"
              disabled={money.busy}
              onClick={() =>
                money.ask(`Ikkinchi tasdiq: ${what} ledger'ga yoziladi. Davom etasizmi?`, async (key) => {
                  const tx = await approveAdjustment(row.id, { expected_version: row.version, note: text.trim() || null }, key);
                  onChanged(`Tasdiqlandi va ledger'ga o'tkazildi: ${tx.id}`);
                })
              }
            >
              Tasdiqlash
            </Btn>
          )}
          {actions.reject && (
            <Btn
              tone="danger"
              disabled={money.busy || !text.trim()}
              onClick={() =>
                money.ask(`So'rov rad etiladi: ${what}. Davom etasizmi?`, async (key) => {
                  await rejectAdjustment(row.id, { expected_version: row.version, reason: text.trim() }, key);
                  onChanged("Tuzatish so'rovi rad etildi.");
                })
              }
            >
              Rad etish
            </Btn>
          )}
          {actions.withdraw && (
            <Btn
              disabled={money.busy}
              onClick={() =>
                money.ask(`O'z so'rovingizni qaytarib olasiz: ${what}. Davom etasizmi?`, async (key) => {
                  await withdrawAdjustment(row.id, { expected_version: row.version, reason: text.trim() || null }, key);
                  onChanged("So'rov qaytarib olindi.");
                })
              }
            >
              Qaytarib olish
            </Btn>
          )}
        </div>
      )}
      {money.view}
    </div>
  );
}

const EMPTY_ADJUSTMENT = { wallet_id: "", direction: "credit" as "credit" | "debit", amount: "", reason: "", booking_id: "", reversal_of: "" };

function NewAdjustment({ onChanged }: { onChanged: () => void }) {
  const [form, setForm] = useState(EMPTY_ADJUSTMENT);
  const money = useMoneyAction();
  const amount = parseSoumToMinor(form.amount);
  const ready = form.wallet_id.trim() && amount !== null && form.reason.trim();
  return (
    <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
      <p className="text-sm font-semibold text-foreground">Yangi tuzatish</p>
      <p className="text-xs text-muted-foreground">
        Kichik summa darhol o'tadi; katta summa boshqa moliya xodimining tasdig'ini kutadi. Har yozuv aniq sabab bilan
        audit'ga tushadi. Hamyon ID «wal_...» ko'rinishida (tuzatishlar ro'yxatidan yoki haydovchi kartasidan).
      </p>
      <div className="grid gap-2 md:grid-cols-3">
        <Field label="Hamyon ID" value={form.wallet_id} placeholder="wal_..." onChange={(v) => setForm({ ...form, wallet_id: v })} />
        <Select
          label="Yo'nalish"
          value={form.direction}
          onChange={(v) => setForm({ ...form, direction: v })}
          options={[
            ["credit", "Kredit: hamyonga qo'shish"],
            ["debit", "Debit: hamyondan ayirish"],
          ]}
        />
        <Field label="Summa (so'm)" value={form.amount} inputMode="decimal" onChange={(v) => setForm({ ...form, amount: v })} />
        <div className="md:col-span-3">
          <Field label="Sabab (audit)" value={form.reason} onChange={(v) => setForm({ ...form, reason: v })} />
        </div>
        <Field label="Bron ID (ixtiyoriy)" value={form.booking_id} placeholder="bkg_..." onChange={(v) => setForm({ ...form, booking_id: v })} />
        <Field
          label="Qaytariladigan ledger yozuvi (ixtiyoriy)"
          value={form.reversal_of}
          placeholder="ltx_..."
          onChange={(v) => setForm({ ...form, reversal_of: v })}
        />
      </div>
      <Btn
        tone="primary"
        disabled={money.busy || !ready}
        onClick={() =>
          money.ask(
            `${form.direction === "credit" ? "Kredit" : "Debit"} ${formatMinor(amount)} → ${form.wallet_id.trim()}. Sabab: «${form.reason.trim()}». Davom etasizmi?`,
            async (key) => {
              const result = await createAdjustment(
                {
                  wallet_id: form.wallet_id.trim(),
                  direction: form.direction,
                  amount_minor: amount as number,
                  reason: form.reason.trim(),
                  booking_id: form.booking_id.trim() || null,
                  reversal_of_transaction_id: form.reversal_of.trim() || null,
                },
                key,
              );
              money.setDone(
                isPostedTransaction(result)
                  ? `Darhol o'tkazildi: ${(result as LedgerTransactionDTO).id}`
                  : "Katta summa: so'rov yaratildi, boshqa moliya xodimi tasdiqlamaguncha balans o'zgarmaydi.",
              );
              setForm(EMPTY_ADJUSTMENT);
              onChanged();
            },
          )
        }
      >
        So'rov yuborish
      </Btn>
      {money.view}
    </div>
  );
}

function AdjustmentsTab({ meId, caps }: { meId: string | null; caps: Capabilities }) {
  const [status, setStatus] = useState<AdjustmentStatusFilter | "all">("pending");
  const list = usePaged<LedgerAdjustmentDTO>(
    (cursor) => listAdjustments({ status: status === "all" ? undefined : status, cursor, limit: 50 }),
    [status],
  );
  const [flash, setFlash] = useState<string | null>(null);
  const changed = (message?: string) => {
    setFlash(message ?? null);
    list.reload();
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label="Holat"
          value={status}
          onChange={setStatus}
          options={[
            ["pending", "Ikkinchi tasdiq kutilmoqda"],
            ["approved", "O'tkazilgan"],
            ["rejected", "Rad etilgan"],
            ["withdrawn", "Qaytarib olingan"],
            ["all", "Hammasi"],
          ]}
        />
        <Btn onClick={list.reload}>Yangilash</Btn>
      </div>
      {flash && <Note tone="success">{flash}</Note>}
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.items === null && !list.error && <Loading />}
      {list.items !== null && list.items.length === 0 && <p className="text-sm text-muted-foreground">Tuzatish so'rovi yo'q.</p>}
      {(list.items ?? []).map((row) => (
        <AdjustmentRow key={`${row.id}:${row.version}`} row={row} meId={meId} caps={caps} onChanged={changed} />
      ))}
      {list.hasMore && (
        <Btn disabled={list.busy} onClick={list.more}>
          Ko'proq
        </Btn>
      )}
      {caps.has(CAP.adjustment) && <NewAdjustment onChanged={list.reload} />}
    </div>
  );
}

// --- commission policies ------------------------------------------------------------------------------------------

function scopeText(policy: CommissionPolicyDTO): string {
  const service = policy.scope.service_type === "passenger" ? "yo'lovchi" : policy.scope.service_type === "parcel" ? "pochta" : null;
  const parts = [policy.scope.corridor_id ? `koridor ${policy.scope.corridor_id}` : null, service].filter(Boolean);
  return parts.length ? parts.join(", ") : "global";
}

function PolicyRow({ policy, canManage, onChanged }: { policy: CommissionPolicyDTO; canManage: boolean; onChanged: (message?: string) => void }) {
  const [reason, setReason] = useState("");
  const [endAt, setEndAt] = useState("");
  const money = useMoneyAction();
  const endIso = tashkentLocalToIso(endAt);
  const ended = policy.effective_to !== null && policy.effective_to !== undefined && new Date(policy.effective_to).getTime() <= Date.now();
  return (
    <div className="space-y-2 rounded-[12px] border border-border bg-card p-3 text-sm" data-testid={`policy-${policy.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold text-foreground">
          {policy.fee_percent}% ({policy.fee_bps} bps) · {policy.kind === "campaign" ? `kampaniya «${policy.campaign_name ?? ""}»` : "standart"} ·{" "}
          {scopeText(policy)}
        </p>
        <span className={`text-xs ${policy.is_active_now ? "text-success" : "text-muted-foreground"}`}>
          {policy.is_active_now ? "hozir amal qiladi" : "amal qilmaydi"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        {formatDateTime(policy.effective_from)} — {policy.effective_to ? formatDateTime(policy.effective_to) : "muddatsiz"} · {policy.id}
        {policy.created_by?.id ? ` · yaratdi: ${policy.created_by.id}` : " · migratsiya seed'i"}
      </p>
      <p className="text-secondary-foreground">Sabab: {policy.reason}</p>
      {!policy.is_confirmed && (
        <Note tone="warning">
          Migratsiya seed stavkasi tasdiqlanmagan (Q28): production'da v2 narx hisobi va komissiya hold'i bloklangan,
          super admin stavkani tasdiqlaguncha yoki yangisini yaratguncha.
        </Note>
      )}
      {canManage && (!policy.is_confirmed || !ended) && (
        <div className="grid gap-2 md:grid-cols-3">
          <Field label="Sabab (audit)" value={reason} onChange={setReason} />
          {!ended && <Field label="Tugash vaqti (Toshkent)" type="datetime-local" value={endAt} onChange={setEndAt} />}
          <div className="flex flex-wrap items-end gap-2">
            {!policy.is_confirmed && (
              <Btn
                tone="primary"
                disabled={money.busy || !reason.trim()}
                onClick={() =>
                  money.ask(`Seed stavka ${policy.fee_percent}% tasdiqlanadi va production'da ishlatiladi. Davom etasizmi?`, async (key) => {
                    await confirmCommissionPolicy(policy.id, { expected_version: policy.version, reason: reason.trim() }, key);
                    onChanged("Stavka tasdiqlandi.");
                  })
                }
              >
                Stavkani tasdiqlash
              </Btn>
            )}
            {!ended && (
              <Btn
                tone="danger"
                disabled={money.busy || !reason.trim() || !endIso}
                onClick={() =>
                  money.ask(`Siyosat ${endAt.replace("T", " ")} da tugaydi. Mavjud bronlar o'z snapshot'ini saqlaydi. Davom etasizmi?`, async (key) => {
                    await endCommissionPolicy(policy.id, { expected_version: policy.version, effective_to: endIso as string, reason: reason.trim() }, key);
                    onChanged("Tugash vaqti belgilandi.");
                  })
                }
              >
                Tugatish
              </Btn>
            )}
          </div>
        </div>
      )}
      {money.view}
    </div>
  );
}

const EMPTY_POLICY = {
  kind: "standard" as CommissionPolicyKind,
  service_type: "" as "" | "passenger" | "parcel",
  corridor_id: "",
  fee_bps: "",
  from: "",
  to: "",
  campaign_name: "",
  reason: "",
};

function NewPolicy({ onChanged }: { onChanged: () => void }) {
  const [form, setForm] = useState(EMPTY_POLICY);
  const money = useMoneyAction();
  const bps = /^\d{1,5}$/.test(form.fee_bps.trim()) ? Number(form.fee_bps.trim()) : null;
  const fromIso = tashkentLocalToIso(form.from);
  const toIso = form.to ? tashkentLocalToIso(form.to) : null;
  const campaign = form.kind === "campaign";
  const valid =
    bps !== null &&
    bps <= 10000 &&
    (campaign || bps > 0) &&
    fromIso !== null &&
    (!form.to || toIso !== null) &&
    (!campaign || (toIso !== null && form.campaign_name.trim())) &&
    form.reason.trim();
  return (
    <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
      <p className="text-sm font-semibold text-foreground">Yangi siyosat</p>
      <p className="text-xs text-muted-foreground">
        Stavka butun bps'da (100 bps = 1%). 0% faqat aniq muddatli kampaniya sifatida (Q1). Siyosat o'tgan vaqtdan
        boshlanmaydi; bronlar yaratilgan paytdagi stavkani saqlaydi.
      </p>
      <div className="grid gap-2 md:grid-cols-3">
        <Select
          label="Turi"
          value={form.kind}
          onChange={(v) => setForm({ ...form, kind: v })}
          options={[
            ["standard", "Standart"],
            ["campaign", "Kampaniya (muddatli)"],
          ]}
        />
        <Select
          label="Xizmat"
          value={form.service_type}
          onChange={(v) => setForm({ ...form, service_type: v })}
          options={[
            ["", "Barchasi"],
            ["passenger", "Yo'lovchi"],
            ["parcel", "Pochta"],
          ]}
        />
        <Field label="Koridor ID (ixtiyoriy)" value={form.corridor_id} placeholder="cor_..." onChange={(v) => setForm({ ...form, corridor_id: v })} />
        <Field label="Stavka (bps)" value={form.fee_bps} inputMode="numeric" onChange={(v) => setForm({ ...form, fee_bps: v })} />
        <Field label="Boshlanishi (Toshkent)" type="datetime-local" value={form.from} onChange={(v) => setForm({ ...form, from: v })} />
        <Field
          label={campaign ? "Tugashi (majburiy)" : "Tugashi (ixtiyoriy)"}
          type="datetime-local"
          value={form.to}
          onChange={(v) => setForm({ ...form, to: v })}
        />
        {campaign && (
          <Field label="Kampaniya nomi" value={form.campaign_name} onChange={(v) => setForm({ ...form, campaign_name: v })} />
        )}
        <div className={campaign ? "md:col-span-2" : "md:col-span-3"}>
          <Field label="Sabab (audit)" value={form.reason} onChange={(v) => setForm({ ...form, reason: v })} />
        </div>
      </div>
      <Btn
        tone="primary"
        disabled={money.busy || !valid}
        onClick={() =>
          money.ask(`Yangi ${campaign ? "kampaniya" : "standart"} siyosat: ${bps} bps, ${form.from.replace("T", " ")} dan. Davom etasizmi?`, async (key) => {
            await createCommissionPolicy(
              {
                kind: form.kind,
                fee_bps: bps as number,
                effective_from: fromIso as string,
                effective_to: toIso,
                campaign_name: campaign ? form.campaign_name.trim() : null,
                reason: form.reason.trim(),
                scope: { service_type: form.service_type || null, corridor_id: form.corridor_id.trim() || null },
              },
              key,
            );
            money.setDone("Siyosat yaratildi.");
            setForm(EMPTY_POLICY);
            onChanged();
          })
        }
      >
        Siyosat yaratish
      </Btn>
      {money.view}
    </div>
  );
}

function PoliciesTab({ caps }: { caps: Capabilities }) {
  const [onlyActive, setOnlyActive] = useState(false);
  const list = usePaged<CommissionPolicyDTO>(
    (cursor) => listCommissionPolicies({ active_at: onlyActive ? new Date().toISOString() : undefined, cursor, limit: 50 }),
    [onlyActive],
  );
  const [flash, setFlash] = useState<string | null>(null);
  const changed = (message?: string) => {
    setFlash(message ?? null);
    list.reload();
  };
  const canManage = caps.has(CAP.policyManage);
  return (
    <div className="space-y-3">
      <Note>
        {canManage
          ? "Komissiya siyosatini faqat super admin yaratadi va o'zgartiradi (Q2). Mijozga komissiya ko'rsatilmaydi."
          : "Faqat o'qish: komissiya siyosatini super admin boshqaradi (Q2)."}
      </Note>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-secondary-foreground">
          <input type="checkbox" checked={onlyActive} onChange={(event) => setOnlyActive(event.target.checked)} />
          Faqat hozir amal qiladiganlar
        </label>
        <Btn onClick={list.reload}>Yangilash</Btn>
      </div>
      {flash && <Note tone="success">{flash}</Note>}
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.items === null && !list.error && <Loading />}
      {list.items !== null && list.items.length === 0 && <p className="text-sm text-muted-foreground">Siyosat yo'q.</p>}
      {(list.items ?? []).map((policy) => (
        <PolicyRow key={`${policy.id}:${policy.version}`} policy={policy} canManage={canManage} onChanged={changed} />
      ))}
      {list.hasMore && (
        <Btn disabled={list.busy} onClick={list.more}>
          Ko'proq
        </Btn>
      )}
      {canManage && <NewPolicy onChanged={list.reload} />}
    </div>
  );
}

// --- reconciliation and reports -----------------------------------------------------------------------------------

function useRead<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loader = useCallback(load, deps);
  const reload = useCallback(() => {
    setBusy(true);
    setError(null);
    setData(null);
    loader()
      .then(setData)
      .catch(setError)
      .finally(() => setBusy(false));
  }, [loader]);
  useEffect(reload, [reload]);
  return { data, error, busy, reload };
}

const RECON_SECTIONS: Array<[keyof ReconciliationDTO, string]> = [
  ["mismatches", "Balans keshi ledger bilan mos emas"],
  ["unbalanced_transactions", "Debit ≠ kredit bo'lgan tranzaksiyalar"],
  ["overdraft_wallets", "Manfiy balansli hamyonlar"],
  ["orphan_postings", "Manbasiz ledger yozuvlari (Q55)"],
];

function Reconciliation() {
  const [date, setDate] = useState(tashkentToday());
  const recon = useRead<ReconciliationDTO>(() => financeReconciliation(date || undefined), [date]);
  const data = recon.data;
  const issues = data ? RECON_SECTIONS.map(([key, text]) => [text, (data[key] as unknown as Array<Record<string, unknown>> | undefined) ?? []] as const) : [];
  const clean = data !== null && issues.every(([, rows]) => rows.length === 0);
  return (
    <section className="space-y-2 rounded-[14px] border border-border bg-card p-4">
      <h3 className="text-base font-bold text-foreground">Kunlik solishtiruv</h3>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Sana" type="date" value={date} onChange={setDate} />
        <Btn onClick={recon.reload}>Yangilash</Btn>
      </div>
      <ErrorNote error={recon.error} />
      {recon.busy && <Loading />}
      {data && (
        <>
          <p className="text-sm text-secondary-foreground">
            {formatDate(data.date)}: {data.wallets_checked} ta hamyon tekshirilgan.
          </p>
          {clean ? (
            <Note tone="success">Ledger, balanslar va manbalar mos — tafovut topilmadi.</Note>
          ) : (
            issues
              .filter(([, rows]) => rows.length > 0)
              .map(([text, rows]) => (
                <div key={text} className="space-y-1">
                  <p className="text-sm font-semibold text-destructive">
                    {text}: {rows.length}
                  </p>
                  {rows.map((row, index) => (
                    <pre key={index} className="overflow-x-auto rounded-[10px] bg-muted p-2 text-xs">
                      {JSON.stringify(row)}
                    </pre>
                  ))}
                </div>
              ))
          )}
        </>
      )}
    </section>
  );
}

function FinanceReports({ from, to }: { from: string; to: string }) {
  const [report, setReport] = useState<FinanceReportName>("commission_revenue");
  const result = useRead<FinanceReportDTO>(() => financeReport(report, { from, to }), [report, from, to]);
  const meta = REPORTS.find(([key]) => key === report);
  return (
    <section className="space-y-2 rounded-[14px] border border-border bg-card p-4">
      <h3 className="text-base font-bold text-foreground">Moliya hisobotlari</h3>
      <Select label="Hisobot" value={report} onChange={setReport} options={REPORTS.map(([key, text]) => [key as FinanceReportName, text])} />
      {meta && <p className="text-xs text-muted-foreground">{meta[2]}</p>}
      <ErrorNote error={result.error} onRetry={result.reload} />
      {result.busy && <Loading />}
      {result.data && result.data.rows.length === 0 && <p className="text-sm text-muted-foreground">Bu davrda yozuv yo'q.</p>}
      {result.data && result.data.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-3">Sana</th>
                <th className="py-1 pr-3">Summa</th>
                <th className="py-1">Soni</th>
              </tr>
            </thead>
            <tbody>
              {result.data.rows.map((row) => (
                <tr key={`${row.date}:${row.corridor ?? ""}`} className="border-t border-border">
                  <td className="py-1 pr-3">{formatDate(row.date)}</td>
                  <td className="py-1 pr-3">{formatMinor(row.amount_minor)}</td>
                  <td className="py-1">{row.count}</td>
                </tr>
              ))}
              <tr className="border-t border-border font-semibold">
                <td className="py-1 pr-3">Jami</td>
                <td className="py-1 pr-3">{formatMinor(result.data.totals.amount_minor)}</td>
                <td className="py-1">{result.data.totals.count}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SplitSignals({ from, to }: { from: string; to: string }) {
  const result = useRead<SplitAdjustmentSignalDTO[]>(() => splitAdjustmentSignals({ from, to }), [from, to]);
  return (
    <section className="space-y-2 rounded-[14px] border border-border bg-card p-4">
      <h3 className="text-base font-bold text-foreground">Bo'lingan tuzatishlar belgisi</h3>
      <p className="text-xs text-muted-foreground">
        Ikki kishilik tasdiq chegarasidan qochish uchun bo'lingan bo'lishi mumkin bo'lgan kichik tuzatishlar (Q30). Bu
        ayblov emas — ko'rib chiqish uchun belgi.
      </p>
      <ErrorNote error={result.error} onRetry={result.reload} />
      {result.busy && <Loading />}
      {result.data && result.data.length === 0 && <p className="text-sm text-muted-foreground">Belgi yo'q.</p>}
      {(result.data ?? []).map((signal) => (
        <p key={`${signal.wallet_id}:${signal.window_start}`} className="break-words rounded-[10px] bg-muted/50 p-2 text-sm">
          {signal.wallet_id} · so'rovchi {signal.requested_by.id ?? "-"} · {signal.count} ta, jami {formatMinor(signal.amount_minor)} ·{" "}
          {formatDateTime(signal.window_start)} — {formatDateTime(signal.window_end)} · {signal.adjustment_ids.join(", ")}
        </p>
      ))}
    </section>
  );
}

const PROMO_VALUES: Array<[string, string]> = [
  ["promo_bookings", "Promo bronlar"],
  ["passenger_bonus_minor", "Mijoz bonusi (P)"],
  ["driver_credit_minor", "Haydovchi krediti (H)"],
  ["net_commission_captured_minor", "Undirilgan sof komissiya"],
  ["outstanding_liability_minor", "Ochiq majburiyat"],
  ["pending_review_minor", "Tekshiruvda"],
];

function PromoReport({ from, to }: { from: string; to: string }) {
  const [groupBy, setGroupBy] = useState<PromoReportGroupBy>("service");
  const result = useRead<PromoReportDTO>(() => promoReport({ from, to, group_by: groupBy }), [from, to, groupBy]);
  const data = result.data;
  return (
    <section className="space-y-2 rounded-[14px] border border-border bg-card p-4">
      <h3 className="text-base font-bold text-foreground">Promo hisobot</h3>
      <p className="text-xs text-muted-foreground">
        Faqat haqiqiy yozuvlar (simulyatsiya emas). Bonus va kredit — chegirma huquqi, pul emas; undirilgan komissiya
        alohida ko'rsatiladi.
      </p>
      <Select
        label="Guruhlash"
        value={groupBy}
        onChange={setGroupBy}
        options={[
          ["service", "Xizmat"],
          ["corridor", "Koridor"],
          ["campaign_version", "Kampaniya versiyasi"],
          ["cohort", "Kogorta"],
        ]}
      />
      <ErrorNote error={result.error} onRetry={result.reload} />
      {result.busy && <Loading />}
      {data && data.rows.length === 0 && <p className="text-sm text-muted-foreground">Bu davrda promo yozuvi yo'q.</p>}
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-3">Guruh</th>
                {PROMO_VALUES.map(([, text]) => (
                  <th key={text} className="py-1 pr-3">
                    {text}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.key} className="border-t border-border">
                  <td className="py-1 pr-3">{row.key}</td>
                  {PROMO_VALUES.map(([field]) => {
                    const value = (row.values as Record<string, number | null | undefined>)[field];
                    return (
                      <td key={field} className="py-1 pr-3">
                        {value == null ? "-" : field.endsWith("_minor") ? formatMinor(value) : value}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.budgets.length > 0 && (
        <div className="space-y-1">
          <p className="text-sm font-semibold text-foreground">Byudjetlar ({formatDateTime(data.generated_at)} holatiga)</p>
          {data.budgets.map((budget) => (
            <p key={budget.campaign_id} className="break-words rounded-[10px] bg-muted/50 p-2 text-sm">
              {budget.campaign_id} · {budget.status} · ajratilgan {formatMinor(budget.allocated_minor)} · sarflangan{" "}
              {formatMinor(budget.consumed_minor)} · majburiyat {formatMinor(budget.outstanding_liability_minor)} · yangi uchun{" "}
              {formatMinor(budget.available_for_new_minor)}
              {budget.shortfall_minor > 0 ? ` · kamomad ${formatMinor(budget.shortfall_minor)}` : ""}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

function ReportsTab({ caps }: { caps: Capabilities }) {
  const today = tashkentToday();
  const [from, setFrom] = useState(daysBefore(today, 30));
  const [to, setTo] = useState(today);
  const range = from && to ? { from, to } : null;
  return (
    <div className="space-y-4">
      <Reconciliation />
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Davr boshi" type="date" value={from} onChange={setFrom} />
        <Field label="Davr oxiri" type="date" value={to} onChange={setTo} hint="Ko'pi bilan 366 kun" />
      </div>
      {range && <FinanceReports {...range} />}
      {range && <SplitSignals {...range} />}
      {range && caps.has(CAP.promoView) && <PromoReport {...range} />}
    </div>
  );
}

// --- the panel ----------------------------------------------------------------------------------------------------

type Tab = "topups" | "adjustments" | "policies" | "reports";

const TABS: Array<[Tab, string, string]> = [
  ["topups", "Top-uplar", CAP.reports],
  ["adjustments", "Tuzatishlar", CAP.reports],
  ["policies", "Komissiya siyosati", CAP.policyView],
  ["reports", "Solishtiruv va hisobotlar", CAP.reports],
];

export function AdminFinancePanel() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab | null>(null);

  const load = useCallback(() => {
    setError(null);
    setCaps(null);
    Promise.all([loadCapabilities(), financeMe().catch(() => null)])
      .then(([dto, me]) => {
        setCaps(new Set<string>(dto.capabilities));
        setMeId(me?.id ?? null);
      })
      .catch(setError);
  }, []);
  useEffect(load, [load]);

  const visible = useMemo(() => (caps ? TABS.filter(([, , cap]) => caps.has(cap)) : []), [caps]);
  const current = tab && visible.some(([id]) => id === tab) ? tab : (visible[0]?.[0] ?? null);

  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-lg font-bold text-foreground">Moliya</h2>
        <p className="text-sm text-muted-foreground">
          Top-up tasdiqlash, ledger tuzatishlari, komissiya siyosati va solishtiruv. Har pul amali tasdiq so'raydi va
          audit'ga yoziladi.
        </p>
      </header>
      <ErrorNote error={error} onRetry={load} />
      {!caps && !error && <Loading />}
      {caps && visible.length === 0 && <Note>Moliya bo'limi uchun ruxsatingiz yo'q.</Note>}
      {caps && visible.length > 0 && (
        <>
          <div className="flex items-center gap-2 overflow-x-auto pb-1" role="tablist">
            {visible.map(([id, text]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={current === id}
                onClick={() => setTab(id)}
                className={`el-press h-9 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-semibold ${current === id ? "bg-primary text-primary-foreground" : "bg-muted text-secondary-foreground"}`}
              >
                {text}
              </button>
            ))}
          </div>
          {current === "topups" && <TopupsTab meId={meId} caps={caps} />}
          {current === "adjustments" && <AdjustmentsTab meId={meId} caps={caps} />}
          {current === "policies" && <PoliciesTab caps={caps} />}
          {current === "reports" && <ReportsTab caps={caps} />}
        </>
      )}
    </section>
  );
}
