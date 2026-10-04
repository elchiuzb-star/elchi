/**
 * Finance staff panel (Q17, Q49, Q55, Q69, Q70, Q2, Q28, §9.2; design "Elchi Admin" → Moliya): top-ups, ledger
 * adjustments, reconciliation and reports, commission policy.
 *
 * Honesty rules shown on screen, not only in code:
 * - a pending top-up or its screenshot is a *request*, not money; money exists after an approval against a bank
 *   statement or cashier receipt (large amounts: a second, different finance person);
 * - "calculated commission" is a hold, not received money, and the four finance reports are different kinds of
 *   money: they are never added into one "Jami" (designer question 11c.3 — each kind keeps its own total);
 * - a Q48/Q70 production refusal (`503 PRODUCTION_INVARIANTS_FAILED`) is shown as the launch gate it is.
 *
 * Who sees what (Q2, Q49, Q69): Top-uplar only with `finance.topup_approve` (finance, super_admin); adjustments
 * are approved by a *different* person with `finance.adjustment_approve`, the requester only withdraws; creating
 * one needs `finance.adjustment`; commission policy is managed by super_admin only. The server decides every
 * permission; the panel hides what it would refuse, asks for a confirmation before every money command, keeps one
 * Idempotency-Key per confirmed action and asks for the MFA code when the server wants a step-up (ADR-0021).
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
import { adminCorridors, type CorridorAdminDTO } from "../api/v2/admin-platform.api";
import { WALLET_LOOKUP_MIN_QUERY, searchWallets, type WalletLookupRow } from "../api/v2/admin-wallets.api";
import { capabilities as loadCapabilities } from "../api/v2/ops.api";
import { useT } from "../i18n/react";
import { formatDate, formatDateTime, formatMinor } from "../utils/v2Format";
import {
  Badge,
  Btn,
  Card,
  Chips,
  Empty,
  Field,
  Loading,
  Note,
  Section,
  Select,
  Tabs,
  refName,
  useConfirmedCommand,
} from "./adminMoneyUi";
import {
  CAP,
  adjustmentActions,
  adjustmentStatusLabel,
  daysBefore,
  financeErrorMessage,
  isCalmRefusal,
  isPostedTransaction,
  moneyKindLabel,
  parseSoumToMinor,
  reportMeta,
  sourceTypeLabel,
  tashkentLocalToIso,
  tashkentToday,
  topupActions,
  topupMethodLabel,
  topupStatusLabel,
  topupStatusTone,
  visibleFinanceTabs,
  type Capabilities,
  type FinanceReportKey,
  type FinanceTab,
} from "./finance";

type T = ReturnType<typeof useT>;

function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useT();
  if (!error) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="alert">
      <Note tone={isCalmRefusal(error) ? "warning" : "danger"}>{financeErrorMessage(error)}</Note>
      {onRetry && !isCalmRefusal(error) && <Btn onClick={onRetry}>{t("common.retry")}</Btn>}
    </div>
  );
}

function moneyCommand() {
  return { explain: financeErrorMessage, calm: isCalmRefusal };
}

/** Loads a cursor page and appends the next one on demand. */
function usePaged<R>(load: (cursor: string | null) => Promise<Page<R>>, deps: unknown[]) {
  const [items, setItems] = useState<R[] | null>(null);
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

function useRead<R>(load: () => Promise<R>, deps: unknown[]) {
  const [data, setData] = useState<R | null>(null);
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

function MoreButton({ list }: { list: { hasMore: boolean; busy: boolean; more: () => void } }) {
  const t = useT();
  if (!list.hasMore) return null;
  return (
    <Btn disabled={list.busy} onClick={list.more}>
      {t("admin.money.more")}
    </Btn>
  );
}

/** "3 soat" / "2 kun" from seconds, for the adjustment age badge. */
function ageText(t: T, seconds: number): string {
  if (seconds >= 2 * 86400) return t("admin.money.days", { count: Math.floor(seconds / 86400) });
  if (seconds >= 3600) return t("admin.money.hours", { count: Math.floor(seconds / 3600) });
  return t("admin.money.minutes", { count: Math.max(1, Math.floor(seconds / 60)) });
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

function Overlay({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const t = useT();
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto bg-foreground/40 p-4" role="presentation">
      <section role="dialog" aria-modal="true" aria-label={title} className="my-8 w-full max-w-2xl space-y-3 rounded-[14px] border border-border bg-card p-5 shadow-xl">
        <header className="flex items-start justify-between gap-3">
          <h3 className="text-base font-bold text-foreground">{title}</h3>
          <Btn onClick={onClose}>{t("common.close")}</Btn>
        </header>
        {children}
      </section>
    </div>
  );
}

/** Design overlay `topup`: the approve form, its confirmation ("{amount} {name} hamyoniga qo'shilsinmi?") and reject. */
function TopupReview({ topup, meId, caps, onClose, onChanged }: {
  topup: TopupAdminDTO; meId: string | null; caps: Capabilities; onClose: () => void; onChanged: (message: string) => void;
}) {
  const t = useT();
  const actions = topupActions(topup, meId, caps);
  const [form, setForm] = useState<ApproveForm>(() => initialApproveForm(topup));
  const [reason, setReason] = useState("");
  const money = useConfirmedCommand(moneyCommand());
  const received = parseSoumToMinor(form.amount);
  const receivedAt = tashkentLocalToIso(form.received_at);
  const differs = received !== null && received !== topup.amount_minor;
  const driver = refName(topup.driver);

  const approve = () =>
    money.ask({
      title: actions.secondStep
        ? t("admin.finance.confirmTopupSecond", { amount: formatMinor(received), name: driver })
        : t("admin.finance.confirmTopup", { amount: formatMinor(received), name: driver }),
      lines: [
        t("admin.finance.sourceLine", { source: sourceTypeLabel(form.source_type).toLowerCase(), reference: form.source_reference.trim() }),
        actions.secondStep ? t("admin.finance.secondStepNote") : t("admin.finance.largeNeedsSecond"),
      ],
      work: async (key) => {
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
        onChanged(
          next.status === "approved"
            ? t("admin.finance.topupApproved", { amount: formatMinor(next.evidence.received_amount_minor ?? received) })
            : t("admin.finance.topupFirstDone"),
        );
      },
    });

  const reject = () =>
    money.ask({
      title: t("admin.finance.confirmTopupReject"),
      lines: [t("admin.finance.reasonLine", { reason: reason.trim() })],
      tone: "danger",
      work: async (key) => {
        await rejectTopup(topup.id, { expected_version: topup.version, reason: reason.trim() }, key);
        onChanged(t("admin.finance.topupRejected"));
      },
    });

  return (
    <Overlay title={t("admin.finance.topupModalTitle", { amount: formatMinor(topup.amount_minor) })} onClose={onClose}>
      <Note tone="warning">{t("admin.finance.notMoneyYet")}</Note>
      {actions.approve && (
        <div className="grid gap-2 md:grid-cols-2">
          <Select
            label={t("admin.finance.sourceType")}
            value={form.source_type}
            onChange={(v) => setForm({ ...form, source_type: v })}
            options={[
              ["bank_statement", t("admin.finance.source.bank_statement")],
              ["cashier_receipt", t("admin.finance.source.cashier_receipt")],
            ]}
          />
          <Field label={t("admin.finance.docNumber")} value={form.source_reference} onChange={(v) => setForm({ ...form, source_reference: v })} />
          <Field
            label={t("admin.finance.receivedAmount")}
            value={form.amount}
            inputMode="decimal"
            onChange={(v) => setForm({ ...form, amount: v })}
            hint={differs ? t("admin.finance.amountDiffers", { amount: formatMinor(topup.amount_minor) }) : undefined}
          />
          <Field
            label={t("admin.finance.receivedAt")}
            type="datetime-local"
            value={form.received_at}
            onChange={(v) => setForm({ ...form, received_at: v })}
          />
          <div className="md:col-span-2">
            <Field label={t("bookingCancel.commentLabel")} value={form.note} onChange={(v) => setForm({ ...form, note: v })} />
          </div>
          {actions.secondStep && <p className="text-xs text-muted-foreground md:col-span-2">{t("admin.finance.secondStepNote")}</p>}
          <div className="md:col-span-2">
            <Btn tone="primary" disabled={money.busy || received === null || !receivedAt || !form.source_reference.trim()} onClick={approve}>
              {t("common.confirm")}
            </Btn>
          </div>
        </div>
      )}
      {actions.note && <p className="text-xs text-muted-foreground">{actions.note}</p>}
      {actions.reject && (
        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
          <div className="min-w-[240px] flex-1">
            <Field label={t("admin.finance.rejectReason")} value={reason} onChange={setReason} />
          </div>
          <Btn tone="danger" disabled={money.busy || !reason.trim()} onClick={reject}>
            {t("admin.money.reject")}
          </Btn>
        </div>
      )}
      {money.view}
    </Overlay>
  );
}

function TopupRow({ topup, meId, caps, onReview }: { topup: TopupAdminDTO; meId: string | null; caps: Capabilities; onReview: () => void }) {
  const t = useT();
  const actions = topupActions(topup, meId, caps);
  const ev = topup.evidence;
  const open = topup.status === "pending" || topup.status === "awaiting_second_approval";
  return (
    <Card
      testId={`topup-${topup.id}`}
      highlight={topup.status === "pending"}
      title={[formatMinor(topup.amount_minor), topupMethodLabel(topup.method), topupStatusLabel(topup.status)].join(" · ")}
      badge={<Badge tone={topupStatusTone(topup.status)}>{topupStatusLabel(topup.status)}</Badge>}
    >
      <p className="break-words text-xs text-muted-foreground">
        {t("admin.finance.topupMeta", { name: refName(topup.driver), time: formatDateTime(topup.created_at) })}
      </p>
      {topup.first_approver?.id && (
        <p className="break-words text-xs text-muted-foreground">{t("admin.finance.firstApprover", { name: refName(topup.first_approver) })}</p>
      )}
      {topup.second_approver?.id && (
        <p className="break-words text-xs text-muted-foreground">{t("admin.finance.secondApprover", { name: refName(topup.second_approver) })}</p>
      )}
      <p className="break-words text-xs text-secondary-foreground">
        {t("admin.finance.topupClaim", { payer: ev.payer_reference ?? "-", note: ev.note ?? "-", file: ev.evidence_file_id ?? "-" })}
      </p>
      {ev.source_reference && (
        <p className="break-words text-xs text-secondary-foreground">
          {t("admin.finance.confirmedSource", {
            source: sourceTypeLabel(ev.source_type).toLowerCase(),
            reference: ev.source_reference,
            amount: formatMinor(ev.received_amount_minor),
          })}
        </p>
      )}
      {open && (
        <p className="text-xs text-warning">
          {topup.status === "pending" ? t("admin.finance.notMoneyYet") : t("admin.finance.firstNotYetMoney")}
        </p>
      )}
      {actions.note && <p className="text-xs text-muted-foreground">{actions.note}</p>}
      {(actions.approve || actions.reject) && <Btn onClick={onReview}>{t("admin.finance.review")}</Btn>}
    </Card>
  );
}

function useCount(load: () => Promise<Page<unknown>>, deps: unknown[]): string | null {
  const [count, setCount] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    load()
      .then((page) => alive && setCount(`${page.items.length}${page.nextCursor ? "+" : ""}`))
      .catch(() => alive && setCount(null));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return count;
}

function TopupsTab({ meId, caps }: { meId: string | null; caps: Capabilities }) {
  const t = useT();
  const [status, setStatus] = useState<TopupStatus | "all">("pending");
  const [tick, setTick] = useState(0);
  const list = usePaged<TopupAdminDTO>(
    (cursor) => listTopups({ status: status === "all" ? undefined : status, cursor, limit: 50 }),
    [status, tick],
  );
  const pendingCount = useCount(() => listTopups({ status: "pending", limit: 100 }), [tick]);
  const secondCount = useCount(() => listTopups({ status: "awaiting_second_approval", limit: 100 }), [tick]);
  const [flash, setFlash] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<TopupAdminDTO | null>(null);
  const withCount = (text: string, count: string | null) => (count && count !== "0" ? `${text} · ${count}` : text);
  return (
    <div className="space-y-3">
      <Note tone="warning">{t("admin.finance.topupsNote")}</Note>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Chips
          label={t("admin.money.status")}
          value={status}
          onChange={setStatus}
          options={[
            ["pending", withCount(t("status.pending"), pendingCount)],
            ["awaiting_second_approval", withCount(t("admin.finance.status.second"), secondCount)],
            ["approved", t("status.approved")],
            ["rejected", t("status.rejected")],
            ["all", t("admin.money.all")],
          ]}
        />
        <Btn onClick={() => setTick((n) => n + 1)}>{t("support.refresh")}</Btn>
      </div>
      {flash && <Note tone="success">{flash}</Note>}
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.items === null && !list.error && <Loading />}
      {list.items !== null && list.items.length === 0 && <Empty>{t("admin.finance.noTopups")}</Empty>}
      <div className="grid gap-2">
        {(list.items ?? []).map((topup) => (
          <TopupRow key={`${topup.id}:${topup.version}`} topup={topup} meId={meId} caps={caps} onReview={() => setReviewing(topup)} />
        ))}
      </div>
      <MoreButton list={list} />
      {reviewing && (
        <TopupReview
          topup={reviewing}
          meId={meId}
          caps={caps}
          onClose={() => setReviewing(null)}
          onChanged={(message) => {
            setReviewing(null);
            setFlash(message);
            setTick((n) => n + 1);
          }}
        />
      )}
    </div>
  );
}

// --- adjustments --------------------------------------------------------------------------------------------------

function AdjustmentRow({ row, meId, caps, onChanged }: { row: LedgerAdjustmentDTO; meId: string | null; caps: Capabilities; onChanged: (message: string) => void }) {
  const t = useT();
  const actions = adjustmentActions(row, meId, caps);
  const [text, setText] = useState("");
  const money = useConfirmedCommand(moneyCommand());
  const direction = row.direction === "credit" ? t("admin.finance.creditPlus") : t("admin.finance.debitMinus");
  const what = t("admin.finance.adjWhat", { direction, amount: formatMinor(row.amount_minor), wallet: row.wallet_id });
  const pending = row.status === "pending_second_approval";
  return (
    <Card
      testId={`adjustment-${row.id}`}
      title={`${direction} ${formatMinor(row.amount_minor)} · ${adjustmentStatusLabel(row.status)}`}
      badge={
        pending && row.pending_age_seconds != null ? (
          <Badge tone="warn">{t("admin.finance.waitingFor", { age: ageText(t, row.pending_age_seconds) })}</Badge>
        ) : (
          <Badge tone={row.status === "posted" ? "ok" : row.status === "rejected" ? "err" : pending ? "warn" : "gray"}>
            {adjustmentStatusLabel(row.status)}
          </Badge>
        )
      }
    >
      <p className="break-words text-xs text-muted-foreground">
        {t("admin.finance.adjMeta", { wallet: row.wallet_id, name: refName(row.requested_by) })} · {formatDateTime(row.created_at)}
      </p>
      <p className="break-words text-secondary-foreground">{t("admin.finance.reasonLine", { reason: row.reason })}</p>
      {row.approved_by?.id && <p className="text-xs text-muted-foreground">{t("admin.finance.approvedBy", { name: refName(row.approved_by) })}</p>}
      {row.rejected_by?.id && <p className="text-xs text-muted-foreground">{t("admin.finance.rejectedBy", { name: refName(row.rejected_by) })}</p>}
      {row.reject_reason && <p className="text-xs text-destructive">{t("admin.finance.rejectReasonLine", { reason: row.reject_reason })}</p>}
      {row.transaction && (
        <p className="break-words text-xs text-muted-foreground">{t("admin.finance.ledgerLine", { id: row.transaction.id, reference: row.transaction.reference })}</p>
      )}
      {actions.note && <p className="text-xs text-muted-foreground">{actions.note}</p>}
      {(actions.approve || actions.reject || actions.withdraw) && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <Field label={actions.withdraw ? t("bookingCancel.commentLabel") : t("admin.finance.noteOrReject")} value={text} onChange={setText} />
          </div>
          {actions.approve && (
            <Btn
              tone="primary"
              disabled={money.busy}
              onClick={() =>
                money.ask({
                  title: t("admin.finance.confirmAdjApprove"),
                  lines: [what],
                  work: async (key) => {
                    const tx = await approveAdjustment(row.id, { expected_version: row.version, note: text.trim() || null }, key);
                    onChanged(t("admin.finance.adjApproved", { id: tx.id }));
                  },
                })
              }
            >
              {t("common.confirm")}
            </Btn>
          )}
          {actions.reject && (
            <Btn
              tone="danger"
              disabled={money.busy || !text.trim()}
              onClick={() =>
                money.ask({
                  title: t("admin.finance.confirmAdjReject"),
                  lines: [what, t("admin.finance.reasonLine", { reason: text.trim() })],
                  tone: "danger",
                  work: async (key) => {
                    await rejectAdjustment(row.id, { expected_version: row.version, reason: text.trim() }, key);
                    onChanged(t("admin.finance.adjRejected"));
                  },
                })
              }
            >
              {t("admin.money.reject")}
            </Btn>
          )}
          {actions.withdraw && (
            <Btn
              disabled={money.busy}
              onClick={() =>
                money.ask({
                  title: t("admin.finance.confirmAdjWithdraw"),
                  lines: [what],
                  work: async (key) => {
                    await withdrawAdjustment(row.id, { expected_version: row.version, reason: text.trim() || null }, key);
                    onChanged(t("admin.finance.adjWithdrawn"));
                  },
                })
              }
            >
              {t("admin.promo.withdraw")}
            </Btn>
          )}
        </div>
      )}
      {money.view}
    </Card>
  );
}

/**
 * "Hamyon": search by driver (name, phone, usr_/wal_) via `/admin/wallets?q=`, or type the `wal_…` id. A typed id
 * is used as is; a search only fills it in. When the lookup endpoint is missing the field still works by id.
 */
function WalletPicker({ value, onChange }: { value: string; onChange: (walletId: string) => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<WalletLookupRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [picked, setPicked] = useState<WalletLookupRow | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < WALLET_LOOKUP_MIN_QUERY || q.startsWith("wal_")) {
      setRows(null);
      return;
    }
    let alive = true;
    const timer = window.setTimeout(() => {
      searchWallets(q)
        .then((found) => {
          if (!alive) return;
          setRows(found);
          setFailed(false);
        })
        .catch(() => {
          if (!alive) return;
          setRows(null);
          setFailed(true);
        });
    }, 300);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  return (
    <div className="space-y-1">
      <Field
        label={t("admin.finance.wallet")}
        value={query}
        placeholder={t("admin.finance.walletSearch")}
        onChange={(v) => {
          setPicked(null);
          setQuery(v);
          onChange(v.trim().startsWith("wal_") ? v.trim() : "");
        }}
        hint={
          picked
            ? t("admin.finance.walletPicked", { wallet: picked.id, name: picked.driverName ?? picked.driverId ?? "-" })
            : failed
              ? t("admin.finance.walletLookupUnavailable")
              : undefined
        }
      />
      {rows !== null && !picked && (
        <div className="max-h-48 overflow-y-auto rounded-[10px] border border-border bg-card" role="listbox" aria-label={t("admin.finance.wallet")}>
          {rows.length === 0 && <p className="px-3 py-2 text-xs text-muted-foreground">{t("admin.finance.walletNone")}</p>}
          {rows.map((row) => (
            <button
              key={row.id}
              type="button"
              role="option"
              aria-selected={value === row.id}
              onClick={() => {
                setPicked(row);
                setQuery(`${row.driverName ?? row.driverId ?? ""} (${row.id})`);
                onChange(row.id);
              }}
              className="block w-full px-3 py-2 text-left text-sm hover:bg-muted"
            >
              {row.driverName ?? row.driverId ?? "-"} · {row.phone ?? ""} · <span className="font-mono text-xs">{row.id}</span>
              {row.availableMinor !== null && <span className="text-xs text-muted-foreground"> · {t("admin.finance.walletAvailable", { amount: formatMinor(row.availableMinor) })}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const EMPTY_ADJUSTMENT = { wallet_id: "", direction: "credit" as "credit" | "debit", amount: "", reason: "", booking_id: "", reversal_of: "" };

function NewAdjustment({ onChanged }: { onChanged: () => void }) {
  const t = useT();
  const [form, setForm] = useState(EMPTY_ADJUSTMENT);
  const [walletKey, setWalletKey] = useState(0);
  const [extra, setExtra] = useState(false);
  const money = useConfirmedCommand(moneyCommand());
  const amount = parseSoumToMinor(form.amount);
  const ready = form.wallet_id.trim().startsWith("wal_") && amount !== null && form.reason.trim();
  const direction = form.direction === "credit" ? t("admin.finance.creditPlus") : t("admin.finance.debitMinus");
  return (
    <Section title={t("admin.finance.newAdjustment")} sub={t("admin.finance.newAdjustmentHint")}>
      <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
        <div className="grid gap-2 md:grid-cols-2">
          <WalletPicker key={walletKey} value={form.wallet_id} onChange={(wallet_id) => setForm((f) => ({ ...f, wallet_id }))} />
          <Select
            label={t("admin.finance.direction")}
            value={form.direction}
            onChange={(v) => setForm({ ...form, direction: v })}
            options={[
              ["credit", t("admin.finance.creditAdd")],
              ["debit", t("admin.finance.debitSubtract")],
            ]}
          />
          <Field label={t("income.amountLabel")} value={form.amount} inputMode="decimal" onChange={(v) => setForm({ ...form, amount: v })} />
          <Field label={t("admin.finance.bookingOptional")} value={form.booking_id} placeholder="bkg_..." onChange={(v) => setForm({ ...form, booking_id: v })} />
          <div className="md:col-span-2">
            <Field label={t("admin.money.reasonAudit")} area value={form.reason} onChange={(v) => setForm({ ...form, reason: v })} />
          </div>
          <div className="md:col-span-2">
            <button type="button" className="text-xs font-semibold text-primary" onClick={() => setExtra(!extra)} aria-expanded={extra}>
              {t("admin.finance.extra")}
            </button>
            {extra && (
              <div className="mt-2">
                <Field
                  label={t("admin.finance.reversalOf")}
                  value={form.reversal_of}
                  placeholder="ltx_..."
                  onChange={(v) => setForm({ ...form, reversal_of: v })}
                />
              </div>
            )}
          </div>
        </div>
        <Btn
          tone="primary"
          disabled={money.busy || !ready}
          onClick={() =>
            money.ask({
              title: t("admin.finance.confirmAdjCreate", { direction, amount: formatMinor(amount), wallet: form.wallet_id.trim() }),
              lines: [t("admin.finance.reasonLine", { reason: form.reason.trim() }), t("admin.finance.largeNeedsSecond")],
              work: async (key) => {
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
                    ? t("admin.finance.adjPostedNow", { id: (result as LedgerTransactionDTO).id })
                    : t("admin.finance.adjWaitsSecond"),
                );
                setForm(EMPTY_ADJUSTMENT);
                setWalletKey((n) => n + 1);
                onChanged();
              },
            })
          }
        >
          {t("admin.finance.sendRequest")}
        </Btn>
        {money.view}
      </div>
    </Section>
  );
}

function AdjustmentsTab({ meId, caps }: { meId: string | null; caps: Capabilities }) {
  const t = useT();
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
      {!caps.has(CAP.adjustmentApprove) && !caps.has(CAP.adjustment) && <Note>{t("admin.finance.adjReadOnly")}</Note>}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Chips
          label={t("admin.money.status")}
          value={status}
          onChange={setStatus}
          options={[
            ["pending", t("admin.finance.status.second")],
            ["approved", t("admin.finance.status.posted")],
            ["rejected", t("status.rejected")],
            ["withdrawn", t("status.withdrawn")],
            ["all", t("admin.money.all")],
          ]}
        />
        <Btn onClick={list.reload}>{t("support.refresh")}</Btn>
      </div>
      {flash && <Note tone="success">{flash}</Note>}
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.items === null && !list.error && <Loading />}
      {list.items !== null && list.items.length === 0 && <Empty>{t("admin.finance.noAdjustments")}</Empty>}
      <div className="grid gap-2">
        {(list.items ?? []).map((row) => (
          <AdjustmentRow key={`${row.id}:${row.version}`} row={row} meId={meId} caps={caps} onChanged={changed} />
        ))}
      </div>
      <MoreButton list={list} />
      {/* Q49/Q69: the form exists only for finance / super_admin (`finance.adjustment`). */}
      {caps.has(CAP.adjustment) && <NewAdjustment onChanged={list.reload} />}
    </div>
  );
}

// --- reconciliation and reports -----------------------------------------------------------------------------------

const RECON_SECTIONS: Array<[keyof ReconciliationDTO, "mismatches" | "unbalanced" | "overdraft" | "orphans"]> = [
  ["mismatches", "mismatches"],
  ["unbalanced_transactions", "unbalanced"],
  ["overdraft_wallets", "overdraft"],
  ["orphan_postings", "orphans"],
];

function Reconciliation() {
  const t = useT();
  const [date, setDate] = useState(tashkentToday());
  const recon = useRead<ReconciliationDTO>(() => financeReconciliation(date || undefined), [date]);
  const data = recon.data;
  const issues = data
    ? RECON_SECTIONS.map(([key, label]) => [t(`admin.finance.recon.${label}`), (data[key] as unknown as Array<Record<string, unknown>> | undefined) ?? []] as const)
    : [];
  const clean = data !== null && issues.every(([, rows]) => rows.length === 0);
  return (
    <Section title={t("admin.finance.dailyRecon")}>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("publicShare.date")} type="date" value={date} onChange={setDate} />
        <Btn onClick={recon.reload}>{t("support.refresh")}</Btn>
      </div>
      <ErrorNote error={recon.error} />
      {recon.busy && <Loading />}
      {data && (
        <>
          <p className="text-sm text-secondary-foreground">{t("admin.finance.walletsChecked", { date: formatDate(data.date), count: data.wallets_checked })}</p>
          {clean ? (
            <Note tone="success">{t("admin.finance.reconOk")}</Note>
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
    </Section>
  );
}

type ReportRow = { key: FinanceReportKey; data: FinanceReportDTO | null; error: unknown };

/**
 * The four finance reports as one table (design 11c.2): Hisobot · Turi · Summa · Soni. There is deliberately no
 * "Jami" footer adding them together (11c.3): each row is already the total of its own kind of money.
 */
function FinanceReports({ from, to }: { from: string; to: string }) {
  const t = useT();
  const metas = reportMeta();
  const [rows, setRows] = useState<ReportRow[] | null>(null);
  const [open, setOpen] = useState<FinanceReportKey | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setRows(null);
    Promise.all(
      metas.map((meta) =>
        financeReport(meta.key, { from, to }).then(
          (data): ReportRow => ({ key: meta.key, data, error: null }),
          (error: unknown): ReportRow => ({ key: meta.key, data: null, error }),
        ),
      ),
    ).then((result) => alive && setRows(result));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to, tick]);
  const firstError = rows?.find((row) => row.error)?.error;
  return (
    <Section title={t("admin.finance.reports")}>
      {rows === null && <Loading />}
      <ErrorNote error={firstError} onRetry={() => setTick((n) => n + 1)} />
      {rows && (
        <div className="overflow-x-auto rounded-[12px] border border-border">
          <table className="w-full min-w-[560px] border-collapse text-left text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">{t("admin.finance.report")}</th>
                <th className="px-3 py-2">{t("admin.finance.moneyKind")}</th>
                <th className="px-3 py-2">{t("admin.money.amount")}</th>
                <th className="px-3 py-2">{t("admin.money.count")}</th>
              </tr>
            </thead>
            <tbody>
              {metas.map((meta) => {
                const row = rows.find((r) => r.key === meta.key);
                const data = row?.data ?? null;
                return [
                  <tr key={meta.key} className="border-t border-border" data-testid={`report-${meta.key}`}>
                    <td className="px-3 py-2">
                      <button type="button" className="text-left font-semibold text-foreground underline-offset-2 hover:underline" onClick={() => setOpen(open === meta.key ? null : meta.key)} aria-expanded={open === meta.key}>
                        {meta.title}
                      </button>
                      <p className="text-xs text-muted-foreground">{meta.hint}</p>
                    </td>
                    <td className="px-3 py-2 text-xs text-secondary-foreground">{moneyKindLabel(meta.kind)}</td>
                    <td className="px-3 py-2 font-semibold">{data ? formatMinor(data.totals.amount_minor) : "-"}</td>
                    <td className="px-3 py-2">{data ? data.totals.count : "-"}</td>
                  </tr>,
                  open === meta.key && data ? (
                    <tr key={`${meta.key}-days`} className="bg-muted/30">
                      <td colSpan={4} className="px-3 py-2">
                        {data.rows.length === 0 ? (
                          <Empty>{t("admin.finance.noRows")}</Empty>
                        ) : (
                          <table className="w-full text-xs">
                            <tbody>
                              {data.rows.map((day) => (
                                <tr key={`${day.date}:${day.corridor ?? ""}`}>
                                  <td className="py-0.5 pr-3">{formatDate(day.date)}</td>
                                  <td className="py-0.5 pr-3">{day.corridor ?? ""}</td>
                                  <td className="py-0.5 pr-3">{formatMinor(day.amount_minor)}</td>
                                  <td className="py-0.5">{day.count}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">{t("admin.finance.noGrandTotal")}</p>
    </Section>
  );
}

function SplitSignals({ from, to }: { from: string; to: string }) {
  const t = useT();
  const result = useRead<SplitAdjustmentSignalDTO[]>(() => splitAdjustmentSignals({ from, to }), [from, to]);
  return (
    <Section title={t("admin.finance.splitTitle")} sub={t("admin.finance.splitHint")}>
      <ErrorNote error={result.error} onRetry={result.reload} />
      {result.busy && <Loading />}
      {result.data && result.data.length === 0 && <Empty>{t("admin.finance.noSignals")}</Empty>}
      {(result.data ?? []).map((signal) => (
        <p key={`${signal.wallet_id}:${signal.window_start}`} className="break-words rounded-[10px] bg-muted/50 p-2 text-sm">
          {t("admin.finance.splitRow", {
            wallet: signal.wallet_id,
            name: refName(signal.requested_by),
            count: signal.count,
            amount: formatMinor(signal.amount_minor),
            from: formatDateTime(signal.window_start),
            to: formatDateTime(signal.window_end),
          })}{" "}
          · {signal.adjustment_ids.join(", ")}
        </p>
      ))}
    </Section>
  );
}

const PROMO_VALUES: Array<[string, "promoBookings" | "clientBonus" | "driverCredit" | "netCommission" | "liability" | "inReview"]> = [
  ["promo_bookings", "promoBookings"],
  ["passenger_bonus_minor", "clientBonus"],
  ["driver_credit_minor", "driverCredit"],
  ["net_commission_captured_minor", "netCommission"],
  ["outstanding_liability_minor", "liability"],
  ["pending_review_minor", "inReview"],
];

function PromoReport({ from, to }: { from: string; to: string }) {
  const t = useT();
  const [groupBy, setGroupBy] = useState<PromoReportGroupBy>("service");
  const result = useRead<PromoReportDTO>(() => promoReport({ from, to, group_by: groupBy }), [from, to, groupBy]);
  const data = result.data;
  return (
    <Section title={t("admin.finance.promoReport")} sub={t("admin.finance.promoReportHint")}>
      <Chips
        label={t("admin.finance.groupBy")}
        value={groupBy}
        onChange={setGroupBy}
        options={[
          ["service", t("admin.finance.group.service")],
          ["corridor", t("admin.finance.group.corridor")],
          ["campaign_version", t("admin.finance.group.campaignVersion")],
          ["cohort", t("admin.finance.group.cohort")],
        ]}
      />
      <ErrorNote error={result.error} onRetry={result.reload} />
      {result.busy && <Loading />}
      {data && data.rows.length === 0 && <Empty>{t("admin.finance.noPromoRows")}</Empty>}
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto rounded-[12px] border border-border">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">{t("admin.finance.colGroup")}</th>
                {PROMO_VALUES.map(([field, key]) => (
                  <th key={field} className="px-3 py-2">
                    {t(`admin.finance.promoCol.${key}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.key} className="border-t border-border">
                  <td className="px-3 py-2">{row.key}</td>
                  {PROMO_VALUES.map(([field]) => {
                    const value = (row.values as Record<string, number | null | undefined>)[field];
                    return (
                      <td key={field} className="px-3 py-2">
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
          <p className="text-sm font-semibold text-foreground">{t("admin.finance.budgetsAt", { time: formatDateTime(data.generated_at) })}</p>
          {data.budgets.map((budget) => (
            <p key={budget.campaign_id} className="break-words rounded-[10px] bg-muted/50 p-2 text-sm">
              {t("admin.finance.budgetRow", {
                campaign: budget.campaign_id,
                status: budget.status,
                allocated: formatMinor(budget.allocated_minor),
                consumed: formatMinor(budget.consumed_minor),
                liability: formatMinor(budget.outstanding_liability_minor),
                free: formatMinor(budget.available_for_new_minor),
              })}
              {budget.shortfall_minor > 0 ? ` · ${t("admin.promo.shortfall")} ${formatMinor(budget.shortfall_minor)}` : ""}
            </p>
          ))}
        </div>
      )}
    </Section>
  );
}

function ReportsTab({ caps }: { caps: Capabilities }) {
  const t = useT();
  const today = tashkentToday();
  const [from, setFrom] = useState(daysBefore(today, 30));
  const [to, setTo] = useState(today);
  const range = from && to ? { from, to } : null;
  return (
    <div className="space-y-5">
      <Reconciliation />
      <div className="flex flex-wrap items-start gap-2">
        <Field label={t("admin.finance.periodStart")} type="date" value={from} onChange={setFrom} />
        <Field label={t("admin.finance.periodEnd")} type="date" value={to} onChange={setTo} hint={t("admin.finance.max366")} />
      </div>
      {range && <FinanceReports {...range} />}
      {range && <SplitSignals {...range} />}
      {range && caps.has(CAP.promoView) && <PromoReport {...range} />}
    </div>
  );
}

// --- commission policies ------------------------------------------------------------------------------------------

function scopeText(t: T, policy: CommissionPolicyDTO, corridors: CorridorAdminDTO[]): string {
  const service =
    policy.scope.service_type === "passenger"
      ? t("admin.money.passenger")
      : policy.scope.service_type === "parcel"
        ? t("admin.money.parcel")
        : null;
  const corridor = policy.scope.corridor_id
    ? (corridors.find((c) => c.id === policy.scope.corridor_id)?.name ?? policy.scope.corridor_id)
    : null;
  const parts = [corridor, service].filter(Boolean);
  return parts.length ? parts.join(", ") : t("admin.finance.scope.country");
}

function PolicyRow({ policy, canManage, corridors, onChanged }: { policy: CommissionPolicyDTO; canManage: boolean; corridors: CorridorAdminDTO[]; onChanged: (message: string) => void }) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [endAt, setEndAt] = useState("");
  const money = useConfirmedCommand(moneyCommand());
  const endIso = tashkentLocalToIso(endAt);
  const ended = policy.effective_to !== null && policy.effective_to !== undefined && new Date(policy.effective_to).getTime() <= Date.now();
  const kind = policy.kind === "campaign" ? t("admin.finance.kind.campaign", { name: policy.campaign_name ?? "" }) : t("admin.finance.kind.standard");
  return (
    <Card
      testId={`policy-${policy.id}`}
      title={`${policy.fee_percent}% (${policy.fee_bps} bps) · ${kind} · ${scopeText(t, policy, corridors)}`}
      badge={<Badge tone={policy.is_active_now ? "ok" : "gray"}>{policy.is_active_now ? t("admin.finance.inEffect") : t("admin.finance.notInEffect")}</Badge>}
    >
      <p className="break-words text-xs text-muted-foreground">
        {t("admin.finance.policyMeta", {
          from: formatDateTime(policy.effective_from),
          to: policy.effective_to ? formatDateTime(policy.effective_to) : t("admin.finance.openEnded"),
          who: policy.created_by?.id ? refName(policy.created_by) : t("admin.finance.seedAuthor"),
        })}
      </p>
      <p className="break-words text-secondary-foreground">{t("admin.finance.reasonLine", { reason: policy.reason })}</p>
      {!policy.is_confirmed && <Note tone="warning">{t("admin.finance.seedUnconfirmed")}</Note>}
      {/* Q2: only super_admin (finance.commission_policy_manage) ends or confirms a policy. */}
      {canManage && (!policy.is_confirmed || !ended) && (
        <div className="grid gap-2 md:grid-cols-2">
          <Field label={t("admin.money.reasonAudit")} value={reason} onChange={setReason} />
          {!ended && <Field label={t("admin.finance.endAt")} type="datetime-local" value={endAt} onChange={setEndAt} />}
          <div className="flex flex-wrap items-end gap-2 md:col-span-2">
            {!policy.is_confirmed && (
              <Btn
                tone="primary"
                disabled={money.busy || !reason.trim()}
                onClick={() =>
                  money.ask({
                    title: t("admin.finance.confirmRateQ", { percent: `${policy.fee_percent}%` }),
                    lines: [t("admin.finance.reasonLine", { reason: reason.trim() })],
                    work: async (key) => {
                      await confirmCommissionPolicy(policy.id, { expected_version: policy.version, reason: reason.trim() }, key);
                      onChanged(t("admin.finance.rateConfirmed"));
                    },
                  })
                }
              >
                {t("admin.finance.confirmRate")}
              </Btn>
            )}
            {!ended && (
              <Btn
                tone="danger"
                disabled={money.busy || !reason.trim() || !endIso}
                onClick={() =>
                  money.ask({
                    title: t("admin.finance.confirmEndQ", { time: endAt.replace("T", " ") }),
                    lines: [t("admin.finance.snapshotKept"), t("admin.finance.reasonLine", { reason: reason.trim() })],
                    tone: "danger",
                    work: async (key) => {
                      await endCommissionPolicy(policy.id, { expected_version: policy.version, effective_to: endIso as string, reason: reason.trim() }, key);
                      onChanged(t("admin.finance.endSet"));
                    },
                  })
                }
              >
                {t("admin.finance.end")}
              </Btn>
            )}
          </div>
        </div>
      )}
      {money.view}
    </Card>
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

function NewPolicy({ corridors, onChanged }: { corridors: CorridorAdminDTO[]; onChanged: () => void }) {
  const t = useT();
  const [form, setForm] = useState(EMPTY_POLICY);
  const money = useConfirmedCommand(moneyCommand());
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
    <Section title={t("admin.finance.newPolicy")} sub={t("admin.finance.newPolicyHint")}>
      <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
        <div className="grid gap-2 md:grid-cols-2">
          <Select
            label={t("admin.finance.type")}
            value={form.kind}
            onChange={(v) => setForm({ ...form, kind: v })}
            options={[
              ["standard", t("admin.finance.standardCap")],
              ["campaign", t("admin.finance.campaignTimed")],
            ]}
          />
          <Select
            label={t("admin.money.service")}
            value={form.service_type}
            onChange={(v) => setForm({ ...form, service_type: v })}
            options={[
              ["", t("admin.money.all")],
              ["passenger", t("admin.money.passengerCap")],
              ["parcel", t("admin.money.parcelCap")],
            ]}
          />
          {corridors.length > 0 ? (
            <Select
              label={t("admin.finance.corridorOptional")}
              value={form.corridor_id}
              onChange={(v) => setForm({ ...form, corridor_id: v })}
              options={[["", t("admin.finance.scope.countryCap")], ...corridors.map((c): [string, string] => [c.id, c.name])]}
            />
          ) : (
            <Field label={t("admin.finance.corridorOptional")} value={form.corridor_id} placeholder="cor_..." onChange={(v) => setForm({ ...form, corridor_id: v })} />
          )}
          <Field label={t("admin.finance.rateBps")} value={form.fee_bps} inputMode="numeric" onChange={(v) => setForm({ ...form, fee_bps: v })} />
          <Field label={t("admin.finance.startsAt")} type="datetime-local" value={form.from} onChange={(v) => setForm({ ...form, from: v })} />
          <Field
            label={t("admin.finance.endsAt")}
            type="datetime-local"
            value={form.to}
            onChange={(v) => setForm({ ...form, to: v })}
            hint={campaign ? t("admin.finance.requiredForCampaign") : t("admin.finance.optional")}
          />
          {campaign && <Field label={t("admin.finance.campaignName")} value={form.campaign_name} onChange={(v) => setForm({ ...form, campaign_name: v })} />}
          <div className={campaign ? "" : "md:col-span-2"}>
            <Field label={t("admin.money.reasonAudit")} value={form.reason} onChange={(v) => setForm({ ...form, reason: v })} />
          </div>
        </div>
        <Btn
          tone="primary"
          disabled={money.busy || !valid}
          onClick={() =>
            money.ask({
              title: t("admin.finance.confirmPolicyCreate", {
                kind: campaign ? t("admin.finance.kind.campaign", { name: form.campaign_name.trim() }) : t("admin.finance.kind.standard"),
                bps: String(bps),
                from: form.from.replace("T", " "),
              }),
              lines: [t("admin.finance.reasonLine", { reason: form.reason.trim() }), t("admin.finance.snapshotKept")],
              work: async (key) => {
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
                money.setDone(t("admin.finance.policyCreated"));
                setForm(EMPTY_POLICY);
                onChanged();
              },
            })
          }
        >
          {t("admin.finance.createPolicy")}
        </Btn>
        {money.view}
      </div>
    </Section>
  );
}

function PoliciesTab({ caps }: { caps: Capabilities }) {
  const t = useT();
  const [onlyActive, setOnlyActive] = useState(false);
  const list = usePaged<CommissionPolicyDTO>(
    (cursor) => listCommissionPolicies({ active_at: onlyActive ? new Date().toISOString() : undefined, cursor, limit: 50 }),
    [onlyActive],
  );
  const [corridors, setCorridors] = useState<CorridorAdminDTO[]>([]);
  useEffect(() => {
    adminCorridors({ limit: 100 })
      .then((page) => setCorridors(page.items))
      .catch(() => setCorridors([]));
  }, []);
  const [flash, setFlash] = useState<string | null>(null);
  const changed = (message?: string) => {
    setFlash(message ?? null);
    list.reload();
  };
  const canManage = caps.has(CAP.policyManage);
  return (
    <div className="space-y-3">
      <Note tone="info">{canManage ? t("admin.finance.policyNote") : t("admin.finance.policyReadOnly")}</Note>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-secondary-foreground">
          <input type="checkbox" checked={onlyActive} onChange={(event) => setOnlyActive(event.target.checked)} />
          {t("admin.finance.onlyCurrent")}
        </label>
        <Btn onClick={list.reload}>{t("support.refresh")}</Btn>
      </div>
      {flash && <Note tone="success">{flash}</Note>}
      <ErrorNote error={list.error} onRetry={list.reload} />
      {list.items === null && !list.error && <Loading />}
      {list.items !== null && list.items.length === 0 && <Empty>{t("admin.finance.noPolicies")}</Empty>}
      <div className="grid gap-2 lg:grid-cols-2">
        {(list.items ?? []).map((policy) => (
          <PolicyRow key={`${policy.id}:${policy.version}`} policy={policy} canManage={canManage} corridors={corridors} onChanged={changed} />
        ))}
      </div>
      <MoreButton list={list} />
      {canManage && <NewPolicy corridors={corridors} onChanged={list.reload} />}
    </div>
  );
}

// --- the panel ----------------------------------------------------------------------------------------------------

/** Props stay empty (AdminApp mounts `<AdminFinancePanel />`); the panel reads its own capabilities. */
export function AdminFinancePanel() {
  const t = useT();
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<FinanceTab | null>(null);

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

  const visible = useMemo(() => (caps ? visibleFinanceTabs(caps) : []), [caps]);
  const current = tab && visible.includes(tab) ? tab : (visible[0] ?? null);

  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-lg font-bold text-foreground">{t("admin.finance.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("admin.finance.subtitle")}</p>
      </header>
      <ErrorNote error={error} onRetry={load} />
      {!caps && !error && <Loading />}
      {caps && visible.length === 0 && <Note>{t("admin.finance.noAccess")}</Note>}
      {caps && visible.length > 0 && (
        <>
          <Tabs value={current} onChange={setTab} options={visible.map((id): [FinanceTab, string] => [id, t(`admin.finance.tab.${id}`)])} />
          {current === "topups" && <TopupsTab meId={meId} caps={caps} />}
          {current === "adjustments" && <AdjustmentsTab meId={meId} caps={caps} />}
          {current === "reports" && <ReportsTab caps={caps} />}
          {current === "policies" && <PoliciesTab caps={caps} />}
        </>
      )}
    </section>
  );
}
