/**
 * Promotions administration (referral stage 5, ADR-0023 §19; design "Elchi Admin" → Referral va bonuslar):
 * campaigns, budget requests, review queue, reconciliation.
 *
 * Every button is gated by the staff capabilities (`/me/capabilities`, DESIGN-ADMIN-DIFF 12.1):
 * - campaign status, versions, combinations, new draft -> `promo.campaign_manage` (super_admin);
 * - budget request / approve / reject / withdraw -> `promo.budget_allocate` (finance, super_admin; Q105/Q114);
 *   the requester never approves their own large change, they can only withdraw it;
 * - review start -> `promo.fraud_review` (operator, admin, super_admin); review decision -> `promo.fraud_decide` (admin+).
 * Every status command asks for a confirmation; every decision may need an MFA step-up, which `useStepUp` asks for
 * and replays. There is no "grant a bonus" button anywhere (Q127/Q133): rewards only come from qualification.
 */
import { useEffect, useMemo, useState } from "react";

import {
  adminActivateCampaign,
  adminAddVersion,
  adminApproveCombination,
  adminApproveBudget,
  adminBudgetRequests,
  adminCampaign,
  adminCampaigns,
  adminCloseCampaign,
  adminCreateCampaign,
  adminDecideReview,
  adminPauseCampaign,
  adminReconciliation,
  adminRejectBudget,
  adminRequestBudget,
  adminResumeCampaign,
  adminResumeProcessing,
  adminReviews,
  adminRevokeCombination,
  adminStartReview,
  adminSuspendProcessing,
  adminWithdrawBudget,
  type BudgetRequestDTO,
  type CampaignDTO,
  type CampaignVersionCreate,
  type ReconciliationIssueDTO,
  type ReviewDTO,
} from "../api/v2/promo.api";
import { capabilities as loadCapabilities } from "../api/v2/ops.api";
import { translateDynamic } from "../i18n";
import { useT } from "../i18n/react";
import { formatDateTime } from "../utils/v2Format";
import { formatUzs } from "../utils/money";
import { v2ErrorMessage } from "../utils/v2Errors";
import { Badge, Btn, Card, Empty, Field, Loading, Note, Section, Select, Tabs, useConfirmedCommand, type BadgeTone } from "./adminMoneyUi";

type T = ReturnType<typeof useT>;
type Caps = ReadonlySet<string>;

/** Capabilities behind each control (app/contracts/enums.py STAFF_ROLE_CAPABILITIES). */
export const PROMO_CAP = {
  view: "promo.campaign_view",
  manage: "promo.campaign_manage",
  budget: "promo.budget_allocate",
  review: "promo.fraud_review",
  decide: "promo.fraud_decide",
} as const;

export type PromoTab = "campaigns" | "budget" | "reviews" | "reconciliation";

/** Tabs a role may open: the review queue is read with `promo.fraud_review` (the finance role does not have it). */
export function visiblePromoTabs(caps: Caps): PromoTab[] {
  const tabs: PromoTab[] = [];
  if (caps.has(PROMO_CAP.view)) tabs.push("campaigns", "budget");
  if (caps.has(PROMO_CAP.review)) tabs.push("reviews");
  if (caps.has(PROMO_CAP.view)) tabs.push("reconciliation");
  return tabs;
}

type BudgetKind = "allocate" | "reduce_allocation" | "funding_loss";

const KINDS = ["referral_client_client", "referral_driver_driver", "referral_driver_client"] as const;

function soum(t: T, minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return t("admin.promo.unset");
  return formatUzs(minor / 100);
}

function dyn(key: string, fallback: string): string {
  return translateDynamic(key) ?? fallback;
}

function statusLabel(status: string): string {
  return dyn(`admin.promo.status.${status}`, status);
}

function statusTone(status: string): BadgeTone {
  if (status === "active" || status === "approved" || status === "posted") return "ok";
  if (status === "pending" || status === "open" || status === "under_review" || status === "paused") return "warn";
  if (status === "rejected") return "err";
  return "gray";
}

function serviceLabel(t: T, service: string): string {
  return service === "parcel" ? t("admin.money.parcel") : t("admin.money.passenger");
}

function toMinor(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Math.round(Number(value.replace(/\s/g, "")));
  return Number.isFinite(parsed) && parsed >= 0 ? parsed * 100 : null;
}

function toInt(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Math.round(Number(value));
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function daysToSeconds(value: string): number | null {
  const n = toInt(value);
  return n === null ? null : n * 86400;
}

function useList<R>(load: () => Promise<R[]>) {
  const [rows, setRows] = useState<R[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = () => {
    setError(null);
    load()
      .then(setRows)
      .catch((cause) => setError(v2ErrorMessage(cause)));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, []);
  return { rows, error, reload };
}

// --- campaigns ----------------------------------------------------------------------------------------------------

const EMPTY_VERSION = {
  referrer_reward: "", referee_reward: "", referrer_instrument: "passenger_bonus", referee_instrument: "passenger_bonus",
  milestones: "", min_distinct_clients: "", enrollment_limit: "", qualification_days: "", validity_days: "",
  review_sla_hours: "", grace_days: "", share_bps: "", per_booking: "", p_cap: "", h_cap: "", cost_fixed: "",
  cost_bps: "", min_margin: "", approval_reference: "",
};

type VersionField = Exclude<keyof typeof EMPTY_VERSION, "referrer_instrument" | "referee_instrument">;

const VERSION_FIELDS: VersionField[] = [
  "referrer_reward", "referee_reward", "milestones", "min_distinct_clients", "enrollment_limit", "qualification_days",
  "validity_days", "review_sla_hours", "grace_days", "share_bps", "per_booking", "p_cap", "h_cap", "cost_fixed",
  "cost_bps", "min_margin", "approval_reference",
];

function versionBody(f: typeof EMPTY_VERSION): CampaignVersionCreate {
  // An empty field stays null: "not decided" blocks activation, it is never read as zero (Q105).
  return {
    referrer_reward_minor: toMinor(f.referrer_reward),
    referee_reward_minor: toMinor(f.referee_reward),
    referrer_instrument: f.referrer_instrument as CampaignVersionCreate["referrer_instrument"],
    referee_instrument: f.referee_instrument as CampaignVersionCreate["referee_instrument"],
    milestone_thresholds: f.milestones.trim()
      ? f.milestones.split(",").map((part) => Number(part.trim())).filter((n) => Number.isFinite(n) && n > 0)
      : [],
    min_distinct_clients: toInt(f.min_distinct_clients),
    enrollment_limit: toInt(f.enrollment_limit),
    qualification_window_s: daysToSeconds(f.qualification_days),
    reward_validity_s: daysToSeconds(f.validity_days),
    review_sla_s: toInt(f.review_sla_hours) === null ? null : (toInt(f.review_sla_hours) as number) * 3600,
    restoration_grace_s: daysToSeconds(f.grace_days),
    max_discount_share_bps: toInt(f.share_bps),
    max_discount_per_booking_minor: toMinor(f.per_booking),
    passenger_bonus_max_per_booking_minor: toMinor(f.p_cap),
    driver_credit_max_per_booking_minor: toMinor(f.h_cap),
    variable_cost_fixed_minor: toMinor(f.cost_fixed),
    variable_cost_bps: toInt(f.cost_bps),
    min_margin_minor: toMinor(f.min_margin),
    approval_reference: f.approval_reference.trim() || null,
  };
}

/** Design `A.kpis`: the eight budget positions of one campaign (Q132: reducible = max(0, B − S − L)). */
function BudgetKpis({ campaign }: { campaign: CampaignDTO }) {
  const t = useT();
  const b = campaign.budget;
  const items: Array<[string, number | null | undefined]> = [
    [t("admin.promo.allocated"), b.allocated_minor],
    [t("admin.promo.promised"), b.promised_minor],
    [t("admin.promo.granted"), b.granted_minor],
    [t("promo.bucket.consumed"), b.consumed_minor],
    [t("admin.promo.released"), b.released_minor],
    [t("admin.promo.freeForNew"), b.available_for_new_minor],
    [t("admin.promo.shortfall"), b.shortfall_minor],
    [t("admin.promo.reducible"), b.reducible_minor ?? 0],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-[10px] border border-border bg-card p-2">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="font-semibold text-foreground">{soum(t, value)}</p>
        </div>
      ))}
    </div>
  );
}

type StatusCommand = "activate" | "pause" | "resume" | "close" | "suspend" | "resumeProcessing";

function CampaignDetail({ id, caps, onChanged }: { id: string; caps: Caps; onChanged: () => void }) {
  const t = useT();
  const [campaign, setCampaign] = useState<CampaignDTO | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [versionNo, setVersionNo] = useState("");
  const [form, setForm] = useState(EMPTY_VERSION);
  const [showForm, setShowForm] = useState(false);
  const [budget, setBudget] = useState({ kind: "allocate" as BudgetKind, amount: "", reason: "", evidence: "" });
  const command = useConfirmedCommand();
  const canManage = caps.has(PROMO_CAP.manage);
  const canBudget = caps.has(PROMO_CAP.budget);

  const load = () => {
    setLoadError(null);
    adminCampaign(id).then(setCampaign).catch((cause) => setLoadError(v2ErrorMessage(cause)));
  };
  useEffect(load, [id]);

  if (loadError) return <p role="alert" className="text-sm text-destructive">{loadError}</p>;
  if (!campaign) return <Loading />;

  const runStatus = (which: StatusCommand) => {
    const body = { expected_version: campaign.version, reason: reason.trim() };
    const work: Record<StatusCommand, () => Promise<CampaignDTO>> = {
      activate: () => adminActivateCampaign(campaign.id, { ...body, version_no: toInt(versionNo) ?? undefined }),
      pause: () => adminPauseCampaign(campaign.id, body),
      resume: () => adminResumeCampaign(campaign.id, body),
      close: () => adminCloseCampaign(campaign.id, body),
      suspend: () => adminSuspendProcessing(campaign.id, reason.trim()),
      resumeProcessing: () => adminResumeProcessing(campaign.id, reason.trim()),
    };
    command.ask({
      title: t(`admin.promo.confirm.${which}`, { name: campaign.name, version: versionNo }),
      lines: [t("admin.finance.reasonLine", { reason: reason.trim() }), t(`admin.promo.effect.${which}`)],
      tone: which === "close" || which === "suspend" ? "danger" : "primary",
      work: async () => {
        setCampaign(await work[which]());
        setReason("");
        onChanged();
      },
    });
  };

  const suspended = Boolean(campaign.processing_suspended_at);
  return (
    <div className="space-y-4 rounded-[14px] border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-bold text-foreground">{campaign.name}</h3>
          <p className="text-sm text-muted-foreground">
            {t("admin.promo.campaignMeta", {
              status: statusLabel(campaign.status),
              service: serviceLabel(t, campaign.service_type),
              version: campaign.active_version_no ?? t("admin.money.notYet"),
            })}
          </p>
        </div>
        <Badge tone={statusTone(campaign.status)}>{statusLabel(campaign.status)}</Badge>
      </div>
      {suspended && <Note tone="warning">{t("admin.promo.suspendedNote", { reason: campaign.processing_suspend_reason ?? "-" })}</Note>}
      <BudgetKpis campaign={campaign} />

      <Section title={t("admin.promo.versions")}>
        {(campaign.versions ?? []).length === 0 && <Empty>{t("admin.promo.noVersions")}</Empty>}
        {(campaign.versions ?? []).map((v) => (
          <div key={v.version_no} className="rounded-[10px] border border-border p-2 text-sm">
            <p className="font-semibold">
              {t("admin.promo.versionRow", {
                no: v.version_no,
                referrer: soum(t, v.referrer_reward_minor),
                referee: soum(t, v.referee_reward_minor),
                margin: soum(t, v.min_margin_minor),
              })}
            </p>
            {v.missing_for_activation.length > 0 ? (
              <p className="text-xs text-destructive">{t("admin.promo.missing", { fields: v.missing_for_activation.join(", ") })}</p>
            ) : (
              <p className="text-xs text-success">{t("admin.promo.allSet")}</p>
            )}
          </div>
        ))}
        {canManage && <Btn onClick={() => setShowForm(!showForm)}>{showForm ? t("admin.promo.closeForm") : t("admin.promo.addVersion")}</Btn>}
        {canManage && showForm && (
          <div className="grid gap-2 rounded-[12px] border border-border p-3 md:grid-cols-3">
            <p className="text-xs text-muted-foreground md:col-span-3">{t("admin.promo.versionHint")}</p>
            {VERSION_FIELDS.map((key) => (
              <Field key={key} label={t(`admin.promo.vf.${key}`)} value={form[key]} onChange={(value) => setForm({ ...form, [key]: value })} />
            ))}
            <div className="md:col-span-3">
              <Btn
                tone="primary"
                disabled={command.busy}
                onClick={() =>
                  command.ask({
                    title: t("admin.promo.confirmVersion", { name: campaign.name }),
                    lines: [t("admin.promo.versionHint")],
                    work: async () => {
                      setCampaign(await adminAddVersion(campaign.id, versionBody(form)));
                      setForm(EMPTY_VERSION);
                      setShowForm(false);
                    },
                  })
                }
              >
                {t("admin.promo.saveVersion")}
              </Btn>
            </div>
          </div>
        )}
      </Section>

      <Combinations campaign={campaign} canManage={canManage} onChanged={setCampaign} />

      {canManage && (
        <Section title={t("admin.promo.changeStatus")} sub={t("admin.promo.pauseHint")}>
          <Field label={t("admin.money.reasonAudit")} value={reason} onChange={setReason} />
          <div className="flex flex-wrap items-end gap-2">
            <div className="w-40">
              <Field label={t("admin.promo.activateVersion")} value={versionNo} onChange={setVersionNo} placeholder="1" />
            </div>
            <Btn tone="primary" disabled={command.busy || !reason.trim() || !toInt(versionNo)} onClick={() => runStatus("activate")}>
              {t("admin.promo.activate")}
            </Btn>
            <Btn disabled={command.busy || !reason.trim()} onClick={() => runStatus("pause")}>
              {t("admin.promo.pause")}
            </Btn>
            <Btn disabled={command.busy || !reason.trim()} onClick={() => runStatus("resume")}>
              {t("admin.promo.resume")}
            </Btn>
            <Btn tone="danger" disabled={command.busy || !reason.trim()} onClick={() => runStatus("close")}>
              {t("common.close")}
            </Btn>
            <Btn disabled={command.busy || !reason.trim()} onClick={() => runStatus(suspended ? "resumeProcessing" : "suspend")}>
              {suspended ? t("admin.promo.resumeProcessing") : t("admin.promo.suspend")}
            </Btn>
          </div>
        </Section>
      )}

      {canBudget && (
        <Section title={t("admin.promo.budgetChange")} sub={t("admin.promo.budgetChangeHint")}>
          <div className="grid gap-2 md:grid-cols-4">
            <Select
              label={t("admin.finance.type")}
              value={budget.kind}
              onChange={(kind) => setBudget({ ...budget, kind })}
              options={[
                ["allocate", t("admin.promo.kind.allocate")],
                ["reduce_allocation", t("admin.promo.kind.reduce_allocation")],
                ["funding_loss", t("admin.promo.kind.funding_loss")],
              ]}
            />
            <Field label={t("income.amountLabel")} value={budget.amount} onChange={(v) => setBudget({ ...budget, amount: v })} />
            <Field label={t("common.reason")} value={budget.reason} onChange={(v) => setBudget({ ...budget, reason: v })} />
            <Field label={t("admin.promo.evidence")} value={budget.evidence} onChange={(v) => setBudget({ ...budget, evidence: v })} />
          </div>
          <Btn
            tone="primary"
            disabled={command.busy || !toMinor(budget.amount) || !budget.reason.trim() || (budget.kind === "funding_loss" && !budget.evidence.trim())}
            onClick={() =>
              command.ask({
                title: t("admin.promo.confirmBudgetRequest", { kind: t(`admin.promo.kind.${budget.kind}`), amount: soum(t, toMinor(budget.amount)) }),
                lines: [t("admin.finance.reasonLine", { reason: budget.reason.trim() }), t("admin.promo.budgetChangeHint")],
                work: async () => {
                  await adminRequestBudget(campaign.id, {
                    kind: budget.kind,
                    amount_minor: toMinor(budget.amount) as number,
                    reason: budget.reason.trim(),
                    evidence_reference: budget.evidence.trim() || null,
                  });
                  setBudget({ kind: "allocate", amount: "", reason: "", evidence: "" });
                  load();
                },
              })
            }
          >
            {t("admin.finance.sendRequest")}
          </Btn>
        </Section>
      )}
      {command.view}
    </div>
  );
}

function CampaignsTab({ caps }: { caps: Caps }) {
  const t = useT();
  const list = useList(adminCampaigns);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState({ kind: KINDS[0] as string, service_type: "passenger" as "passenger" | "parcel", name: "" });
  const command = useConfirmedCommand();
  return (
    <div className="space-y-4">
      {list.error && <p role="alert" className="text-sm text-destructive">{list.error}</p>}
      {list.rows === null && !list.error && <Loading />}
      {list.rows !== null && list.rows.length === 0 && <Empty>{t("admin.promo.noCampaigns")}</Empty>}
      {list.rows !== null && list.rows.length > 0 && (
        <div className="divide-y divide-border overflow-hidden rounded-[12px] border border-border bg-card">
          {list.rows.map((row) => (
            <button
              key={row.id}
              type="button"
              onClick={() => setSelected(row.id)}
              aria-pressed={selected === row.id}
              className={`el-press flex w-full items-center justify-between gap-2 p-3 text-left text-sm ${selected === row.id ? "bg-accent" : ""}`}
            >
              <span className="min-w-0">
                <span className="block font-semibold text-foreground">
                  {[row.name, statusLabel(row.status), serviceLabel(t, row.service_type)].join(" · ")}
                </span>
                <span className="block text-xs text-muted-foreground">{t("admin.promo.free", { amount: soum(t, row.budget.available_for_new_minor) })}</span>
              </span>
              <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>
            </button>
          ))}
        </div>
      )}
      {selected && <CampaignDetail key={selected} id={selected} caps={caps} onChanged={list.reload} />}
      {caps.has(PROMO_CAP.manage) && (
        <Section title={t("admin.promo.newDraft")}>
          <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
            <div className="grid gap-2 md:grid-cols-3">
              <Select
                label={t("admin.finance.type")}
                value={draft.kind}
                onChange={(kind) => setDraft({ ...draft, kind })}
                options={KINDS.map((kind): [string, string] => [kind, t(`admin.promo.campaignKind.${kind}`)])}
              />
              <Select
                label={t("admin.money.service")}
                value={draft.service_type}
                onChange={(service_type) => setDraft({ ...draft, service_type })}
                options={[
                  ["passenger", t("admin.money.passengerCap")],
                  ["parcel", t("admin.money.parcelCap")],
                ]}
              />
              <Field label={t("admin.promo.name")} value={draft.name} onChange={(v) => setDraft({ ...draft, name: v })} />
            </div>
            {draft.service_type === "parcel" && <Note tone="warning">{t("admin.promo.parcelOff")}</Note>}
            <Btn
              tone="primary"
              disabled={command.busy || !draft.name.trim()}
              onClick={() =>
                command.ask({
                  title: t("admin.promo.confirmDraft", { name: draft.name.trim() }),
                  lines: [t("admin.promo.draftNote")],
                  work: async () => {
                    const created = await adminCreateCampaign({ ...draft, name: draft.name.trim() });
                    setDraft({ ...draft, name: "" });
                    list.reload();
                    setSelected(created.id);
                  },
                })
              }
            >
              {t("admin.promo.createDraft")}
            </Btn>
            {command.view}
          </div>
        </Section>
      )}
    </div>
  );
}

/**
 * Q123: which campaigns may fund one booking together (P from one, H from the other). Nothing is combined without a
 * row here; the cost basis is chosen explicitly (no default), and revoking stops only new bookings.
 */
function Combinations({ campaign, canManage, onChanged }: { campaign: CampaignDTO; canManage: boolean; onChanged: (next: CampaignDTO) => void }) {
  const t = useT();
  const [others, setOthers] = useState<CampaignDTO[]>([]);
  const [other, setOther] = useState("");
  const [basis, setBasis] = useState<"" | "shared" | "additive">("");
  const [reason, setReason] = useState("");
  const command = useConfirmedCommand();
  useEffect(() => {
    adminCampaigns()
      .then((rows) => setOthers(rows.filter((row) => row.id !== campaign.id)))
      .catch(() => setOthers([]));
  }, [campaign.id]);
  const names = new Map(others.map((row) => [row.id, row.name]));
  return (
    <Section title={t("admin.promo.combinations")} sub={t("admin.promo.combinationsHint")}>
      {(campaign.combinations ?? []).length === 0 && <Empty>{t("admin.promo.noCombinations")}</Empty>}
      {(campaign.combinations ?? []).map((row) => {
        const partner = row.campaign_ids.find((cid) => cid !== campaign.id) ?? "";
        return (
          <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-border p-2 text-sm">
            <span className="min-w-0 break-words">
              {names.get(partner) ?? partner} · {row.cost_basis === "shared" ? t("admin.promo.basis.sharedShort") : t("admin.promo.basis.additiveShort")} ·{" "}
              {row.status === "active" ? t("admin.promo.status.active") : t("status.cancelled")}
            </span>
            {canManage && row.status === "active" && (
              <Btn
                tone="danger"
                disabled={command.busy || !reason.trim()}
                onClick={() =>
                  command.ask({
                    title: t("admin.promo.confirmRevoke", { name: names.get(partner) ?? partner }),
                    lines: [t("admin.finance.reasonLine", { reason: reason.trim() }), t("admin.promo.revokeEffect")],
                    tone: "danger",
                    work: async () => {
                      await adminRevokeCombination(row.id, row.version, reason.trim());
                      onChanged(await adminCampaign(campaign.id));
                      setReason("");
                    },
                  })
                }
              >
                {t("common.cancel")}
              </Btn>
            )}
          </div>
        );
      })}
      {canManage && (
        <>
          <div className="grid gap-2 md:grid-cols-3">
            <Select
              label={t("admin.promo.otherCampaign")}
              value={other}
              onChange={setOther}
              options={[["", t("admin.money.choose")], ...others.map((row): [string, string] => [row.id, row.name])]}
            />
            <Select
              label={t("admin.promo.costBasis")}
              value={basis}
              onChange={setBasis}
              options={[
                ["", t("admin.promo.basis.none")],
                ["shared", t("admin.promo.basis.shared")],
                ["additive", t("admin.promo.basis.additive")],
              ]}
            />
            <Field label={t("admin.money.reasonAudit")} value={reason} onChange={setReason} />
          </div>
          <Btn
            tone="primary"
            disabled={command.busy || !other || !basis || !reason.trim()}
            onClick={() =>
              command.ask({
                title: t("admin.promo.confirmCombination", { name: names.get(other) ?? other }),
                lines: [t("admin.finance.reasonLine", { reason: reason.trim() })],
                work: async () => {
                  onChanged(await adminApproveCombination(campaign.id, { other_campaign_id: other, cost_basis: basis as "shared" | "additive", reason: reason.trim() }));
                  setOther("");
                  setBasis("");
                  setReason("");
                },
              })
            }
          >
            {t("admin.promo.approveCombination")}
          </Btn>
        </>
      )}
      {command.view}
    </Section>
  );
}

// --- budget -------------------------------------------------------------------------------------------------------

function BudgetCard({ row, caps, campaignName, onChanged }: { row: BudgetRequestDTO; caps: Caps; campaignName: string; onChanged: () => void }) {
  const t = useT();
  const [note, setNote] = useState("");
  const command = useConfirmedCommand();
  const canBudget = caps.has(PROMO_CAP.budget);
  const kind = dyn(`admin.promo.kind.${row.kind}`, row.kind);
  const title =
    row.kind === "allocate" && row.needs_second_approver
      ? t("admin.promo.budgetAllocate", { amount: soum(t, row.amount_minor) })
      : `${kind} · ${soum(t, row.amount_minor)}`;
  const what = [kind, soum(t, row.amount_minor), campaignName].join(" · ");
  return (
    <Card title={title} badge={<Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>} testId={`budget-${row.id}`}>
      <p className="break-words text-xs text-muted-foreground">
        {t("admin.promo.budgetMetaNoName", { campaign: campaignName, evidence: row.evidence_reference ?? "-", time: formatDateTime(row.created_at) })}
      </p>
      <p className="break-words text-secondary-foreground">{t("admin.finance.reasonLine", { reason: row.reason })}</p>
      {row.status === "pending" && row.requested_by_me && (
        <>
          <p className="text-xs text-muted-foreground">{t("admin.promo.youRequested")}</p>
          {canBudget && (
            <Btn
              disabled={command.busy}
              onClick={() =>
                command.ask({
                  title: t("admin.promo.confirmWithdraw"),
                  lines: [what],
                  work: async () => {
                    await adminWithdrawBudget(row.id, row.version);
                    onChanged();
                  },
                })
              }
            >
              {t("admin.promo.withdraw")}
            </Btn>
          )}
        </>
      )}
      {/* Q114: the requester is never their own second approver; without promo.budget_allocate the row is read-only. */}
      {row.status === "pending" && !row.requested_by_me && canBudget && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[200px] flex-1">
            <Field label={t("admin.finance.noteOrReject")} value={note} onChange={setNote} />
          </div>
          <Btn
            tone="primary"
            disabled={command.busy}
            onClick={() =>
              command.ask({
                title: t("admin.promo.confirmBudgetApprove"),
                lines: [what],
                work: async () => {
                  await adminApproveBudget(row.id, row.version, note.trim() || undefined);
                  onChanged();
                },
              })
            }
          >
            {t("common.confirm")}
          </Btn>
          <Btn
            tone="danger"
            disabled={command.busy || !note.trim()}
            onClick={() =>
              command.ask({
                title: t("admin.promo.confirmBudgetReject"),
                lines: [what, t("admin.finance.reasonLine", { reason: note.trim() })],
                tone: "danger",
                work: async () => {
                  await adminRejectBudget(row.id, row.version, note.trim());
                  onChanged();
                },
              })
            }
          >
            {t("admin.money.reject")}
          </Btn>
        </div>
      )}
      {row.status === "pending" && !canBudget && <p className="text-xs text-muted-foreground">{t("admin.promo.budgetOnlyFinance")}</p>}
      {command.view}
    </Card>
  );
}

function BudgetTab({ caps }: { caps: Caps }) {
  const t = useT();
  const list = useList(() => adminBudgetRequests());
  const campaigns = useList(adminCampaigns);
  const names = useMemo(() => new Map((campaigns.rows ?? []).map((row) => [row.id, row.name])), [campaigns.rows]);
  return (
    <div className="space-y-3">
      {!caps.has(PROMO_CAP.budget) && <Note>{t("admin.promo.budgetReadOnly")}</Note>}
      {list.error && <p role="alert" className="text-sm text-destructive">{list.error}</p>}
      {list.rows === null && !list.error && <Loading />}
      {list.rows !== null && list.rows.length === 0 && <Empty>{t("admin.promo.noBudgetRequests")}</Empty>}
      <div className="grid gap-2 lg:grid-cols-2">
        {(list.rows ?? []).map((row) => (
          <BudgetCard key={`${row.id}:${row.version}`} row={row} caps={caps} campaignName={names.get(row.campaign_id) ?? row.campaign_id} onChanged={list.reload} />
        ))}
      </div>
    </div>
  );
}

// --- reviews ------------------------------------------------------------------------------------------------------

function ReviewCard({ row, caps, onChanged }: { row: ReviewDTO; caps: Caps; onChanged: () => void }) {
  const t = useT();
  const [note, setNote] = useState("");
  const command = useConfirmedCommand();
  const retired = row.kind === "qualification_path_retired";
  const kindText = dyn(`admin.promo.review.${row.kind}`, row.kind);
  const hint = translateDynamic(`admin.promo.decisionHint.${row.kind}`);
  const canStart = caps.has(PROMO_CAP.review) && row.status === "open";
  const canDecide = caps.has(PROMO_CAP.decide) && (row.status === "open" || row.status === "under_review");
  const reasons = row.reason_codes.map((code) => dyn(`admin.promo.reason.${code}`, code)).join(", ") || "-";
  const decide = (decision: "approve" | "reject") =>
    command.ask({
      title: decision === "approve" ? t("admin.promo.confirmReviewApprove", { kind: kindText }) : t("admin.promo.confirmReviewReject", { kind: kindText }),
      lines: [t("listingOwner.commentLabel") + ": " + note.trim(), t("admin.promo.decisionNotGrant")],
      tone: decision === "reject" ? "danger" : "primary",
      work: async () => {
        await adminDecideReview(row.id, decision, note.trim(), row.version);
        onChanged();
      },
    });
  return (
    <Card
      title={kindText}
      badge={
        row.escalated_at ? <Badge tone="err">{t("admin.promo.overdue")}</Badge> : <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>
      }
      testId={`review-${row.id}`}
    >
      {retired && <p className="text-xs text-secondary-foreground">{t("admin.promo.cannotReject")}</p>}
      <p className="break-words text-xs text-muted-foreground">
        {row.id}
        {row.due_at ? ` · ${t("admin.promo.dueAt", { time: formatDateTime(row.due_at) })}` : ""}
      </p>
      <p className="break-words text-muted-foreground">{t("admin.finance.reasonLine", { reason: reasons })}</p>
      <p className="break-words text-xs text-muted-foreground">
        {t("admin.promo.evidenceLine", { evidence: row.evidence.map((item) => `${String(item.table)}#${String(item.id)}`).join(", ") || "-" })}
      </p>
      {hint && <p className="rounded-[8px] bg-muted/60 px-2 py-1.5 text-xs text-secondary-foreground">{hint}</p>}
      {(canStart || canDecide) && <Field label={t("listingOwner.commentLabel")} value={note} onChange={setNote} />}
      <div className="flex flex-wrap gap-2">
        {canStart && (
          <Btn
            disabled={command.busy}
            onClick={() =>
              command.ask({
                title: t("admin.promo.confirmStart", { kind: kindText }),
                lines: note.trim() ? [t("listingOwner.commentLabel") + ": " + note.trim()] : [],
                work: async () => {
                  await adminStartReview(row.id, note.trim() || undefined);
                  onChanged();
                },
              })
            }
          >
            {t("admin.promo.startReview")}
          </Btn>
        )}
        {canDecide && (
          <Btn tone="primary" disabled={command.busy || !note.trim()} onClick={() => decide("approve")}>
            {t("common.confirm")}
          </Btn>
        )}
        {/* Q147: the retired parcel path is not the participant's breach - the server refuses "reject" for it */}
        {canDecide && !retired && (
          <Btn tone="danger" disabled={command.busy || !note.trim()} onClick={() => decide("reject")}>
            {t("admin.money.reject")}
          </Btn>
        )}
      </div>
      {!caps.has(PROMO_CAP.decide) && (row.status === "open" || row.status === "under_review") && (
        <p className="text-xs text-muted-foreground">{t("admin.promo.decideOnlyAdmin")}</p>
      )}
      {command.view}
    </Card>
  );
}

function ReviewsTab({ caps }: { caps: Caps }) {
  const t = useT();
  const list = useList(() => adminReviews(true));
  return (
    <div className="space-y-3">
      <Note>{t("admin.promo.reviewsNote")}</Note>
      {list.error && <p role="alert" className="text-sm text-destructive">{list.error}</p>}
      {list.rows === null && !list.error && <Loading />}
      {list.rows !== null && list.rows.length === 0 && <Empty>{t("admin.promo.noReviews")}</Empty>}
      <div className="grid gap-2 lg:grid-cols-2">
        {(list.rows ?? []).map((row) => (
          <ReviewCard key={`${row.id}:${row.version}`} row={row} caps={caps} onChanged={list.reload} />
        ))}
      </div>
    </div>
  );
}

function ReconciliationTab() {
  const t = useT();
  const list = useList<ReconciliationIssueDTO>(adminReconciliation);
  return (
    <div className="space-y-3">
      <Btn onClick={list.reload}>{t("admin.promo.recheck")}</Btn>
      {list.error && <p role="alert" className="text-sm text-destructive">{list.error}</p>}
      {list.rows === null && !list.error && <Loading />}
      {list.rows !== null && list.rows.length === 0 && <Note tone="success">{t("admin.promo.reconOk")}</Note>}
      {(list.rows ?? []).map((row, index) => (
        <pre key={index} className="overflow-x-auto rounded-[10px] bg-muted p-2 text-xs">
          {row.kind}: {JSON.stringify(row.detail)}
        </pre>
      ))}
    </div>
  );
}

/** Props stay empty (AdminApp mounts `<AdminPromoPanel />`); the panel reads its own capabilities. */
export function AdminPromoPanel() {
  const t = useT();
  const [caps, setCaps] = useState<Caps | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<PromoTab | null>(null);
  useEffect(() => {
    loadCapabilities()
      .then((dto) => setCaps(new Set<string>(dto.capabilities)))
      .catch((cause) => setError(v2ErrorMessage(cause)));
  }, []);
  const visible = caps ? visiblePromoTabs(caps) : [];
  const current = tab && visible.includes(tab) ? tab : (visible[0] ?? null);
  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-lg font-bold text-foreground">{t("admin.promo.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("admin.promo.subtitle")}</p>
      </header>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {!caps && !error && <Loading />}
      {caps && visible.length === 0 && <Note>{t("admin.promo.noAccess")}</Note>}
      {caps && visible.length > 0 && (
        <>
          <Tabs value={current} onChange={setTab} options={visible.map((id): [PromoTab, string] => [id, t(`admin.promo.tab.${id}`)])} />
          <Note tone="warning">{t("admin.promo.offNote")}</Note>
          {current === "campaigns" && <CampaignsTab caps={caps} />}
          {current === "budget" && <BudgetTab caps={caps} />}
          {current === "reviews" && <ReviewsTab caps={caps} />}
          {current === "reconciliation" && <ReconciliationTab />}
        </>
      )}
    </section>
  );
}
