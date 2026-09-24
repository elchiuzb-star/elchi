/**
 * S9-S11: block a person and report a problem, plus the person's own block list and reports.
 *
 * Blocking is silent (§8.1): the other side is never told and no reason is asked. A report changes nothing by
 * itself - an operator reviews it; the screen never promises an outcome or a response time (§5.2). The free text
 * goes through the server contact filter (Q43): what the server masked comes back as warnings and is shown.
 */
import { useState } from "react";

import {
  blockUser,
  createReport,
  listBlocks,
  listMyReports,
  unblockUser,
  type BlockDTO,
  type ReportDTO,
  type ReportReasonCode,
  type ReportStatus,
  type ReportSubjectType,
} from "../../api/v2/safety.api";
import { newIdempotencyKey, type ApiWarning } from "../../api/v2/http";
import { translate } from "../../i18n";
import type { MessageKey } from "../../i18n/messages";
import { formatDateTime } from "../../utils/v2Format";
import { v2ErrorMessage, warningMessage } from "../../utils/v2Errors";
import { Badge, Card, ErrorNote, Field, InlineButton, Loading, PrimaryButton, SelectField, WarningNote } from "../ui/mobile";
import { useAsync } from "./useAsync";

/** A `[code, label]` pair whose label is looked up on every read, so it follows a language switch. */
function reasonEntry(code: ReportReasonCode): [ReportReasonCode, string] {
  const entry: [ReportReasonCode, string] = [code, ""];
  return Object.defineProperty(entry, 1, {
    get: () => translate(`blockReport.reason.${code}` as MessageKey),
    enumerable: true,
  });
}

/** Exactly the backend `ReportReasonCode` enum, in its order. */
export const REPORT_REASONS: Array<[ReportReasonCode, string]> = [
  reasonEntry("off_platform_contact"),
  reasonEntry("fraud_suspicion"),
  reasonEntry("unsafe_behaviour"),
  reasonEntry("no_show"),
  reasonEntry("price_pressure"),
  reasonEntry("prohibited_item"),
  reasonEntry("harassment"),
  reasonEntry("other"),
];

const SUBJECT_LABEL: Record<ReportSubjectType, string> = {
  get user() { return translate("blockReport.subject.user"); },
  get listing() { return translate("blockReport.subject.listing"); },
  get booking() { return translate("blockReport.subject.booking"); },
  get chat_message() { return translate("blockReport.subject.chat_message"); },
};

const STATUS_LABEL: Record<ReportStatus, [string, "progress" | "ok" | "neutral"]> = {
  get open(): [string, "progress"] { return [translate("blockReport.status.open"), "progress"]; },
  get under_review(): [string, "progress"] { return [translate("blockReport.status.under_review"), "progress"]; },
  get dismissed(): [string, "neutral"] { return [translate("blockReport.status.dismissed"), "neutral"]; },
  get actioned(): [string, "ok"] { return [translate("blockReport.status.actioned"), "ok"]; },
};

export function reasonLabel(code: string): string {
  return REPORT_REASONS.find(([value]) => value === code)?.[1] ?? code;
}

// --- block ---------------------------------------------------------------------------------------------------------

export function BlockPanel(props: {
  /** The person the current screen is about; omit to show only the block list. */
  targetUserId?: string;
  onBlocked?: (block: BlockDTO) => void;
  onUnblocked?: (userId: string) => void;
  /** How to name a blocked person; the list only carries public ids, so the host screen may know better. */
  labelFor?: (userId: string) => string;
}) {
  const blocks = useAsync<BlockDTO[]>(() => listBlocks(), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key, setKey] = useState(newIdempotencyKey);

  const list = blocks.data ?? [];
  const targetBlocked = props.targetUserId ? list.some((item) => item.user_id === props.targetUserId) : false;

  async function block() {
    if (!props.targetUserId) return;
    setBusy(true);
    setError(null);
    try {
      const row = await blockUser(props.targetUserId, key);
      setKey(newIdempotencyKey());
      blocks.setData([...list.filter((item) => item.user_id !== row.user_id), row]);
      props.onBlocked?.(row);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function unblock(userId: string) {
    setBusy(true);
    setError(null);
    try {
      await unblockUser(userId);
      blocks.setData(list.filter((item) => item.user_id !== userId));
      props.onUnblocked?.(userId);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <strong className="text-[15px]">{translate("blockReport.blockTitle")}</strong>
      <p className="text-[12px] leading-5 text-muted-foreground">{translate("blockReport.blockNote")}</p>
      {props.targetUserId && !blocks.loading && (
        targetBlocked ? (
          <InlineButton disabled={busy} onClick={() => unblock(props.targetUserId!)}>{translate("blockReport.unblock")}</InlineButton>
        ) : (
          <InlineButton tone="danger" disabled={busy} onClick={block}>{translate("blockReport.block")}</InlineButton>
        )
      )}
      <ErrorNote message={error ? v2ErrorMessage(error) : null} />
      {blocks.loading ? (
        <Loading />
      ) : blocks.error && !blocks.data ? (
        <ErrorNote message={v2ErrorMessage(blocks.error)} onRetry={blocks.reload} />
      ) : list.length === 0 ? (
        <p className="text-[13px] text-muted-foreground" data-testid="blocks-empty">{translate("blockReport.blocksEmpty")}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="blocks-list">
          {list.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-2 rounded-[10px] bg-background px-3 py-2">
              <span className="min-w-0 text-[13px]">
                <span className="block truncate font-medium text-foreground">{props.labelFor?.(item.user_id) ?? item.user_id}</span>
                <span className="text-[11px] text-muted-foreground">{formatDateTime(item.created_at)}</span>
              </span>
              <InlineButton disabled={busy} onClick={() => unblock(item.user_id)}>{translate("blockReport.unblockShort")}</InlineButton>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --- report --------------------------------------------------------------------------------------------------------

export function ReportForm(props: {
  subjectType: ReportSubjectType;
  subjectId: string;
  onReported?: (report: ReportDTO) => void;
}) {
  const [reason, setReason] = useState<ReportReasonCode | "">("");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState<ReportDTO | null>(null);
  const [warnings, setWarnings] = useState<ApiWarning[]>([]);
  // One key per report the person is writing; a retry of the same submit replays the first answer (ADR-0005).
  const [key, setKey] = useState(newIdempotencyKey);

  async function submit() {
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createReport(
        { subject_type: props.subjectType, subject_id: props.subjectId, reason_code: reason, details: details.trim() || null },
        key,
      );
      setSent(result.data);
      setWarnings(result.warnings);
      setKey(newIdempotencyKey());
      props.onReported?.(result.data);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <Card>
        <strong className="text-[15px]">{translate("blockReport.sentTitle")}</strong>
        {warnings.map((warning) => (
          <WarningNote key={warning.code}>{warningMessage(warning.code)}</WarningNote>
        ))}
        {sent.details ? (
          <p className="text-[13px] text-muted-foreground" data-testid="report-details">{translate("blockReport.savedText", { details: sent.details })}</p>
        ) : null}
        <p className="text-[12px] leading-5 text-muted-foreground">{translate("blockReport.sentNote")}</p>
        <InlineButton
          onClick={() => {
            setSent(null);
            setWarnings([]);
            setReason("");
            setDetails("");
          }}
        >
          {translate("blockReport.reportAgain")}
        </InlineButton>
      </Card>
    );
  }

  return (
    <Card>
      <strong className="text-[15px]">{translate("blockReport.formTitle", { subject: SUBJECT_LABEL[props.subjectType] })}</strong>
      <SelectField label={translate("common.reason")} value={reason} onChange={(value) => setReason(value as ReportReasonCode | "")}>
        <option value="">{translate("blockReport.chooseReason")}</option>
        {REPORT_REASONS.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </SelectField>
      <Field
        label={translate("blockReport.detailsLabel")}
        multiline
        value={details}
        onChange={(value) => setDetails(value.slice(0, 2000))}
        hint={translate("blockReport.detailsHint")}
      />
      <ErrorNote message={error ? v2ErrorMessage(error) : null} />
      <PrimaryButton disabled={!reason || busy} busy={busy} onClick={submit}>{translate("common.send")}</PrimaryButton>
    </Card>
  );
}

export function MyReportsList() {
  const [cursor, setCursor] = useState<string | null>(null);
  const [extra, setExtra] = useState<ReportDTO[]>([]);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreError, setMoreError] = useState<unknown>(null);
  const page = useAsync(() => listMyReports(), []);

  const nextFrom = (meta: unknown) => (meta as { next_cursor?: string | null } | null)?.next_cursor ?? null;
  const next = cursor ?? (page.data ? nextFrom(page.data.meta) : null);

  async function loadMore() {
    if (!next) return;
    setMoreBusy(true);
    setMoreError(null);
    try {
      const result = await listMyReports(next);
      setExtra((current) => [...current, ...result.data]);
      setCursor(nextFrom(result.meta) ?? "");
    } catch (cause) {
      setMoreError(cause);
    } finally {
      setMoreBusy(false);
    }
  }

  if (page.loading) return <Loading />;
  if (page.error && !page.data) return <ErrorNote message={v2ErrorMessage(page.error)} onRetry={page.reload} />;
  const rows = [...(page.data?.data ?? []), ...extra];
  return (
    <Card>
      <strong className="text-[15px]">{translate("blockReport.myReportsTitle")}</strong>
      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground" data-testid="reports-empty">{translate("blockReport.myReportsEmpty")}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="reports-list">
          {rows.map((row) => {
            const [label, tone] = STATUS_LABEL[row.status] ?? [row.status, "neutral"];
            return (
              <li key={row.id} className="rounded-[10px] bg-background px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-foreground">{reasonLabel(row.reason_code)}</span>
                  <Badge text={label} tone={tone} />
                </div>
                <p className="text-[11px] text-muted-foreground">
                  {SUBJECT_LABEL[row.subject_type] ?? row.subject_type} · {formatDateTime(row.created_at)}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      <ErrorNote message={moreError ? v2ErrorMessage(moreError) : null} />
      {next ? <InlineButton disabled={moreBusy} onClick={loadMore}>{translate("blockReport.loadMore")}</InlineButton> : null}
    </Card>
  );
}

/**
 * Everything on one screen: block the person (when `targetUserId` is given), report the subject (when `subject` is
 * given) and the person's own reports.
 */
export function BlockAndReportPanel(props: {
  targetUserId?: string;
  subject?: { type: ReportSubjectType; id: string };
  onBlocked?: (block: BlockDTO) => void;
  onUnblocked?: (userId: string) => void;
  onReported?: (report: ReportDTO) => void;
  labelFor?: (userId: string) => string;
  showMyReports?: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      {props.subject ? (
        <ReportForm subjectType={props.subject.type} subjectId={props.subject.id} onReported={props.onReported} />
      ) : null}
      <BlockPanel targetUserId={props.targetUserId} onBlocked={props.onBlocked} onUnblocked={props.onUnblocked} labelFor={props.labelFor} />
      {props.showMyReports !== false ? <MyReportsList /> : null}
    </div>
  );
}
