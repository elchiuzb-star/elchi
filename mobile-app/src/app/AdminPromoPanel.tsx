/**
 * Promotions administration (referral stage 5, ADR-0023 §19): campaigns, budget, review queue, reconciliation.
 *
 * The server decides who may do what: capabilities come from the staff session, and every decision (campaign
 * command, budget change, review decision) needs a fresh MFA step-up there. When the server answers
 * `step_up_required`, this panel asks for the authenticator code and retries - it never marks anything as verified
 * on its own. A large budget change needs a *second, different* finance person: the requester cannot approve it.
 * There is no "grant a bonus" button anywhere: rewards only come from qualification (Q115, Q122).
 */
import { useEffect, useState } from "react";

import { stepUp } from "../api/v2/mfa.api";
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
import { ApiError } from "../types/api";
import { v2ErrorMessage } from "../utils/v2Errors";
import { ShieldAlert } from "./ui/icons";
import { formatUzs } from "../utils/money";

type BudgetKind = "allocate" | "reduce_allocation" | "funding_loss";
// G14: a reduction stops at spent + obligations; a funding loss (evidence required) may leave a shortfall
const BUDGET_KIND: Record<BudgetKind, string> = {
  allocate: "Ajratish", reduce_allocation: "Kamaytirish", funding_loss: "Moliyalashtirish yo'qoldi",
};

type Tab = "campaigns" | "budget" | "reviews" | "reconciliation";

const TABS: Array<[Tab, string]> = [
  ["campaigns", "Kampaniyalar"],
  ["budget", "Byudjet so'rovlari"],
  ["reviews", "Tekshiruv navbati"],
  ["reconciliation", "Solishtirish"],
];

const KINDS: Array<[string, string]> = [
  ["referral_client_client", "Mijoz → mijoz"],
  ["referral_driver_driver", "Haydovchi → haydovchi"],
  ["referral_driver_client", "Haydovchi → mijoz"],
];

function soum(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "belgilanmagan";
  return formatUzs(minor / 100);
}

const REVIEW_KINDS: Record<string, string> = {
  identity_match: "Telefon mosligi (qayta berilgan raqam ehtimoli)",
  qualification_risk: "Shart bajarilishida xavf belgisi",
  post_grant_recheck: "Mukofotdan keyin o'zgargan dalil",
  party_not_active: "Ishtirokchi faol emas",
  reinstate_unfulfilled: "Tiklash bajarilmadi (byudjet yetmadi)",
  cancel_fault: "Bekor qilish sababi aniqlanmagan (har ega alohida)",
  restoration_uncovered: "Siyosat qamramagan holat: sarflangan bonus yoki kredit",
};

// Q127/Q129: what "approve" and "reject" mean for the review kinds whose decision moves promo value (or none).
const DECISION_HINTS: Record<string, string> = {
  cancel_fault:
    "Tasdiqlash — bekor qilish bu egasining aybi emas: berilgan muhlat qoladi. Rad etish — egasining o'z sababi: faqat sarflanmagan muhlat qaytariladi.",
  restoration_uncovered:
    "Qaror faqat qayd qilinadi: hech narsa berilmaydi va olinmaydi. Tiklash uchun alohida tasdiqlangan qoida kerak.",
};

const STATUS: Record<string, string> = {
  draft: "qoralama", active: "faol", paused: "pauza", closed: "yopilgan", open: "ochiq", under_review: "tekshirilmoqda",
  approved: "tasdiqlangan", rejected: "rad etilgan", pending: "kutilmoqda", posted: "o'tkazilgan", withdrawn: "qaytarib olingan",
};

const REASONS: Record<string, string> = {
  split_shipment: "jo'natma bo'lib yuborilganga o'xshaydi",
  cash_time_unverified: "to'lov vaqti aniq emas",
  identity_match: "telefon avvalgi akkauntga mos",
  party_not_active: "ishtirokchi faol emas",
  evidence_changed_after_grant: "mukofotdan keyin dalil o'zgardi",
  budget_exhausted: "byudjet yetmadi",
  fault_undetermined: "bekor qilish sababi belgilanmagan",
  holder_client: "egasi: mijoz (bonus)",
  holder_driver: "egasi: haydovchi (kredit)",
  commission_reversed: "komissiya qaytarildi",
  dispute_resolved: "nizo hal qilindi",
};

function label(map: Record<string, string>, value: string): string {
  return map[value] ?? value;
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

function isStepUp(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.code === "FORBIDDEN" &&
    typeof error.details === "object" &&
    error.details !== null &&
    (error.details as { reason?: string }).reason === "step_up_required"
  );
}

function Btn(props: { children: string; onClick: () => void; disabled?: boolean; tone?: "primary" | "danger" | "neutral" }) {
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

function Input(props: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; hint?: string }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      <input
        value={props.value}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-foreground outline-none"
      />
      {props.hint && <span className="text-xs text-muted-foreground">{props.hint}</span>}
    </label>
  );
}

/** Runs a staff command; on `step_up_required` asks for the authenticator code, proves it, and retries once. */
function useStaffAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needCode, setNeedCode] = useState<null | (() => Promise<void>)>(null);
  const [code, setCode] = useState("");

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (cause) {
      if (isStepUp(cause)) {
        setNeedCode(() => work);
        setError("Bu amal uchun autentifikator kodi kerak (MFA).");
      } else {
        setError(v2ErrorMessage(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  async function prove() {
    if (!needCode) return;
    setBusy(true);
    setError(null);
    try {
      const proved = await stepUp(code.trim());
      if (!proved) throw new Error("Kod tasdiqlanmadi");
      const retry = needCode;
      setNeedCode(null);
      setCode("");
      await retry();
    } catch (cause) {
      setError(v2ErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const prompt = needCode ? (
    <div className="flex flex-wrap items-end gap-2 rounded-[12px] border border-warning/30 bg-warning/8 p-3">
      <ShieldAlert size={18} color="var(--warning)" />
      <Input label="Autentifikator kodi" value={code} onChange={setCode} placeholder="123456" />
      <Btn tone="primary" disabled={busy || code.trim().length < 6} onClick={() => void prove()}>
        Tasdiqlash va davom etish
      </Btn>
      <p className="w-full text-xs text-muted-foreground">
        Faol MFA faktori bo'lmasa bu amal yopiq qoladi: uni «Xavfsizlik (MFA)» bo'limida ulang (boshqa super admin tasdiqlaydi).
      </p>
    </div>
  ) : null;
  return { busy, error, act, prompt };
}

// --- campaigns ----------------------------------------------------------------------------------------------------

const EMPTY_VERSION = {
  referrer_reward: "", referee_reward: "", referrer_instrument: "passenger_bonus", referee_instrument: "passenger_bonus",
  milestones: "", min_distinct_clients: "", enrollment_limit: "", qualification_days: "", validity_days: "",
  review_sla_hours: "", grace_days: "", share_bps: "", per_booking: "", p_cap: "", h_cap: "", cost_fixed: "",
  cost_bps: "", min_margin: "", approval_reference: "",
};

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

function CampaignDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [campaign, setCampaign] = useState<CampaignDTO | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [versionNo, setVersionNo] = useState("");
  const [form, setForm] = useState(EMPTY_VERSION);
  const [showForm, setShowForm] = useState(false);
  const [budget, setBudget] = useState({ kind: "allocate" as BudgetKind, amount: "", reason: "", evidence: "" });
  const staff = useStaffAction();

  const load = () => {
    setLoadError(null);
    adminCampaign(id).then(setCampaign).catch((cause) => setLoadError(v2ErrorMessage(cause)));
  };
  useEffect(load, [id]);

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!campaign) return <p className="text-sm text-muted-foreground">Yuklanmoqda...</p>;
  const command = (fn: typeof adminPauseCampaign, extra: { version_no?: number } = {}) =>
    staff.act(async () => {
      const next = await fn(campaign.id, { expected_version: campaign.version, reason: reason.trim(), ...extra });
      setCampaign(next);
      setReason("");
      onChanged();
    });
  const b = campaign.budget;
  return (
    <div className="space-y-4 rounded-[14px] border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold text-foreground">{campaign.name}</h3>
        <span className="text-sm text-muted-foreground">
          {label(STATUS, campaign.status)} · {campaign.service_type === "parcel" ? "pochta" : "yo'lovchi"} · faol versiya {campaign.active_version_no ?? "yo'q"}
        </span>
      </div>
      {campaign.processing_suspended_at && (
        <p className="rounded-[10px] bg-warning/10 px-3 py-2 text-sm text-warning">
          Ishlov to'xtatilgan: {campaign.processing_suspend_reason}. Hech narsa berilmaydi, bo'shatilmaydi va o'chirilmaydi.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
        {[
          ["Ajratilgan", b.allocated_minor], ["Va'da qilingan", b.promised_minor], ["Berilgan (sarflanmagan)", b.granted_minor],
          ["Sarflangan", b.consumed_minor], ["Bo'shatilgan", b.released_minor], ["Yangi uchun bo'sh", b.available_for_new_minor],
          ["Kamomad", b.shortfall_minor], ["Kamaytirish mumkin (B − S − L)", b.reducible_minor ?? 0],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-[10px] bg-muted/50 p-2">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="font-semibold text-foreground">{soum(value as number)}</p>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Versiyalar (o'zgarmas)</p>
        {(campaign.versions ?? []).length === 0 && <p className="text-sm text-muted-foreground">Hali versiya yo'q.</p>}
        {(campaign.versions ?? []).map((v) => (
          <div key={v.version_no} className="rounded-[10px] border border-border p-2 text-sm">
            <p className="font-semibold">
              v{v.version_no}: taklif qiluvchi {soum(v.referrer_reward_minor)}, taklif qilingan {soum(v.referee_reward_minor)} · M{" "}
              {soum(v.min_margin_minor)}
            </p>
            {v.missing_for_activation.length > 0 ? (
              <p className="text-xs text-destructive">Aktivlashtirish uchun yetishmaydi: {v.missing_for_activation.join(", ")}</p>
            ) : (
              <p className="text-xs text-success">Barcha qiymatlar belgilangan</p>
            )}
          </div>
        ))}
        <Btn onClick={() => setShowForm(!showForm)}>{showForm ? "Formani yopish" : "Yangi versiya qo'shish"}</Btn>
        {showForm && (
          <div className="grid gap-2 rounded-[12px] border border-border p-3 md:grid-cols-3">
            <p className="md:col-span-3 text-xs text-muted-foreground">
              Bo'sh maydon «belgilanmagan» bo'lib qoladi va aktivlashtirishni to'xtatadi — hech qachon nol deb o'qilmaydi.
              Summa, byudjet, O va M simulyatsiyadan keyin tasdiqlanadi.
            </p>
            {([
              ["referrer_reward", "Taklif qiluvchi mukofoti (so'm)"], ["referee_reward", "Taklif qilingan mukofoti (so'm)"],
              ["milestones", "Bosqichlar (haydovchi: safar soni, vergul bilan; mijoz: bo'sh = bitta bosqich)"], ["min_distinct_clients", "Min. turli mijozlar"],
              ["enrollment_limit", "Ishtirokchilar limiti"], ["qualification_days", "Shart muddati (kun)"],
              ["validity_days", "Bonus amal muddati (kun)"], ["review_sla_hours", "Tekshiruv SLA (soat)"],
              ["grace_days", "Tiklash grace (kun)"], ["share_bps", "Chegirma ulushi (bps)"],
              ["per_booking", "Bron uchun chegirma cap (so'm)"], ["p_cap", "Bonus cap (so'm)"], ["h_cap", "Kredit cap (so'm)"],
              ["cost_fixed", "O: qat'iy xarajat (so'm)"], ["cost_bps", "O: foiz (bps)"], ["min_margin", "M: min. marja (so'm)"],
              ["approval_reference", "Tasdiq hujjati raqami"],
            ] as Array<[keyof typeof EMPTY_VERSION, string]>).map(([key, label]) => (
              <Input key={key} label={label} value={form[key]} onChange={(value) => setForm({ ...form, [key]: value })} />
            ))}
            <div className="md:col-span-3">
              <Btn
                tone="primary"
                disabled={staff.busy}
                onClick={() =>
                  void staff.act(async () => {
                    setCampaign(await adminAddVersion(campaign.id, versionBody(form)));
                    setForm(EMPTY_VERSION);
                    setShowForm(false);
                  })
                }
              >
                Versiyani saqlash
              </Btn>
            </div>
          </div>
        )}
      </div>

      <Combinations campaign={campaign} staff={staff} onChanged={setCampaign} />

      <div className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Holatni o'zgartirish</p>
        <Input label="Sabab (audit)" value={reason} onChange={setReason} />
        <div className="flex flex-wrap gap-2">
          <Input label="Aktivlashtiriladigan versiya" value={versionNo} onChange={setVersionNo} placeholder="1" />
          <Btn tone="primary" disabled={staff.busy || !reason.trim() || !toInt(versionNo)}
            onClick={() => void command(adminActivateCampaign, { version_no: toInt(versionNo) ?? undefined })}>
            Aktivlashtirish
          </Btn>
          <Btn disabled={staff.busy || !reason.trim()} onClick={() => void command(adminPauseCampaign)}>Pauza</Btn>
          <Btn disabled={staff.busy || !reason.trim()} onClick={() => void command(adminResumeCampaign)}>Davom ettirish</Btn>
          <Btn tone="danger" disabled={staff.busy || !reason.trim()} onClick={() => void command(adminCloseCampaign)}>Yopish</Btn>
          <Btn disabled={staff.busy || !reason.trim()}
            onClick={() => void staff.act(async () => setCampaign(await (campaign.processing_suspended_at
              ? adminResumeProcessing(campaign.id, reason.trim())
              : adminSuspendProcessing(campaign.id, reason.trim()))))}>
            {campaign.processing_suspended_at ? "Ishlovni tiklash" : "Ishlovni to'xtatish"}
          </Btn>
        </div>
        <p className="text-xs text-muted-foreground">
          Pauza faqat yangi ishtirokchilarni to'xtatadi: berilgan bonuslar sarflanaveradi, va'dalar saqlanadi.
        </p>
      </div>

      <div className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Byudjet o'zgarishi</p>
        <div className="grid gap-2 md:grid-cols-4">
          <label className="flex min-w-0 flex-col gap-1 text-sm">
            <span className="font-medium text-secondary-foreground">Turi</span>
            <select value={budget.kind} onChange={(event) => setBudget({ ...budget, kind: event.target.value as typeof budget.kind })}
              className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3">
              <option value="allocate">Ajratish</option>
              <option value="reduce_allocation">Kamaytirish</option>
              <option value="funding_loss">Moliyalashtirish yo'qoldi</option>
            </select>
          </label>
          <Input label="Summa (so'm)" value={budget.amount} onChange={(v) => setBudget({ ...budget, amount: v })} />
          <Input label="Sabab" value={budget.reason} onChange={(v) => setBudget({ ...budget, reason: v })} />
          <Input label="Dalil (hujjat raqami)" value={budget.evidence} onChange={(v) => setBudget({ ...budget, evidence: v })} />
        </div>
        <Btn tone="primary" disabled={staff.busy || !toMinor(budget.amount) || !budget.reason.trim()
          || (budget.kind === "funding_loss" && !budget.evidence.trim())}
          onClick={() => void staff.act(async () => {
            await adminRequestBudget(campaign.id, {
              kind: budget.kind, amount_minor: toMinor(budget.amount) as number, reason: budget.reason.trim(),
              evidence_reference: budget.evidence.trim() || null,
            });
            setBudget({ kind: "allocate", amount: "", reason: "", evidence: "" });
            load();
          })}>
          So'rov yuborish
        </Btn>
        <p className="text-xs text-muted-foreground">
          Katta summa ikkinchi, boshqa moliya xodimi tasdiqlaguncha kutadi — so'rovchi o'zi tasdiqlay olmaydi.
        </p>
      </div>
      {staff.error && <p className="text-sm text-destructive">{staff.error}</p>}
      {staff.prompt}
    </div>
  );
}

function CampaignsTab() {
  const [rows, setRows] = useState<CampaignDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState({ kind: KINDS[0][0], service_type: "passenger" as "passenger" | "parcel", name: "" });
  const staff = useStaffAction();
  const load = () => {
    setError(null);
    adminCampaigns().then(setRows).catch((cause) => setError(v2ErrorMessage(cause)));
  };
  useEffect(load, []);
  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows === null && !error && <p className="text-sm text-muted-foreground">Yuklanmoqda...</p>}
      {rows !== null && rows.length === 0 && <p className="text-sm text-muted-foreground">Kampaniya yo'q.</p>}
      <div className="grid gap-2">
        {(rows ?? []).map((row) => (
          <button key={row.id} type="button" onClick={() => setSelected(row.id)}
            className={`el-press rounded-[12px] border p-3 text-left text-sm ${selected === row.id ? "border-primary" : "border-border"} bg-card`}>
            <span className="font-semibold">{row.name}</span> · {label(STATUS, row.status)} · {row.service_type === "parcel" ? "pochta" : "yo'lovchi"} · bo'sh:{" "}
            {soum(row.budget.available_for_new_minor)}
          </button>
        ))}
      </div>
      {selected && <CampaignDetail id={selected} onChanged={load} />}
      <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
        <p className="text-sm font-semibold">Yangi kampaniya (qoralama)</p>
        <div className="grid gap-2 md:grid-cols-3">
          <label className="flex min-w-0 flex-col gap-1 text-sm">
            <span className="font-medium text-secondary-foreground">Turi</span>
            <select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value })}
              className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3">
              {KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-sm">
            <span className="font-medium text-secondary-foreground">Xizmat</span>
            <select value={draft.service_type} onChange={(event) => setDraft({ ...draft, service_type: event.target.value as "passenger" | "parcel" })}
              className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3">
              <option value="passenger">Yo'lovchi</option>
              <option value="parcel">Pochta</option>
            </select>
          </label>
          <Input label="Nomi" value={draft.name} onChange={(v) => setDraft({ ...draft, name: v })} />
        </div>
        <Btn tone="primary" disabled={staff.busy || !draft.name.trim()}
          onClick={() => void staff.act(async () => {
            const created = await adminCreateCampaign({ ...draft, name: draft.name.trim() });
            setDraft({ ...draft, name: "" });
            load();
            setSelected(created.id);
          })}>
          Qoralama yaratish
        </Btn>
        {staff.error && <p className="text-sm text-destructive">{staff.error}</p>}
        {staff.prompt}
      </div>
    </div>
  );
}

// --- budget -------------------------------------------------------------------------------------------------------

function BudgetTab() {
  const [rows, setRows] = useState<BudgetRequestDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const staff = useStaffAction();
  const load = () => {
    setError(null);
    adminBudgetRequests().then(setRows).catch((cause) => setError(v2ErrorMessage(cause)));
  };
  useEffect(load, []);
  return (
    <div className="space-y-3">
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows === null && !error && <p className="text-sm text-muted-foreground">Yuklanmoqda...</p>}
      {rows !== null && rows.length === 0 && <p className="text-sm text-muted-foreground">So'rovlar yo'q.</p>}
      {(rows ?? []).map((row) => (
        <div key={row.id} className="space-y-2 rounded-[12px] border border-border bg-card p-3 text-sm">
          <p className="font-semibold">
            {BUDGET_KIND[row.kind as BudgetKind] ?? row.kind} · {soum(row.amount_minor)} · {label(STATUS, row.status)}
            {row.needs_second_approver ? " · ikkinchi tasdiq kerak" : ""}
          </p>
          <p className="text-muted-foreground">{row.reason}{row.evidence_reference ? ` (dalil: ${row.evidence_reference})` : ""}</p>
          {row.status === "pending" && (
            row.requested_by_me ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">Siz so'ragansiz — boshqa xodim tasdiqlaydi.</span>
                <Btn disabled={staff.busy} onClick={() => void staff.act(async () => { await adminWithdrawBudget(row.id, row.version); load(); })}>
                  Qaytarib olish
                </Btn>
              </div>
            ) : (
              <div className="flex flex-wrap items-end gap-2">
                <Input label="Izoh / rad sababi" value={reasons[row.id] ?? ""} onChange={(v) => setReasons({ ...reasons, [row.id]: v })} />
                <Btn tone="primary" disabled={staff.busy}
                  onClick={() => void staff.act(async () => { await adminApproveBudget(row.id, row.version, reasons[row.id]); load(); })}>
                  Tasdiqlash
                </Btn>
                <Btn tone="danger" disabled={staff.busy || !(reasons[row.id] ?? "").trim()}
                  onClick={() => void staff.act(async () => { await adminRejectBudget(row.id, row.version, (reasons[row.id] ?? "").trim()); load(); })}>
                  Rad etish
                </Btn>
              </div>
            )
          )}
        </div>
      ))}
      {staff.error && <p className="text-sm text-destructive">{staff.error}</p>}
      {staff.prompt}
    </div>
  );
}

// --- reviews ------------------------------------------------------------------------------------------------------

/**
 * Q123: which campaigns may fund one booking together (P from one, H from the other). Nothing is combined without a
 * row here; the cost basis is chosen explicitly (no default), and revoking stops only new bookings.
 */
function Combinations({
  campaign,
  staff,
  onChanged,
}: {
  campaign: CampaignDTO;
  staff: ReturnType<typeof useStaffAction>;
  onChanged: (next: CampaignDTO) => void;
}) {
  const [others, setOthers] = useState<CampaignDTO[]>([]);
  const [other, setOther] = useState("");
  const [basis, setBasis] = useState<"" | "shared" | "additive">("");
  const [reason, setReason] = useState("");
  useEffect(() => {
    adminCampaigns().then((rows) => setOthers(rows.filter((row) => row.id !== campaign.id))).catch(() => setOthers([]));
  }, [campaign.id]);
  const names = new Map(others.map((row) => [row.id, row.name]));
  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold text-foreground">Boshqa kampaniya bilan birga ishlashi</p>
      <p className="text-xs text-muted-foreground">
        Bir bronda mijoz bonusi bitta kampaniyadan, haydovchi krediti bitta kampaniyadan bo'ladi. Ikki turli kampaniya
        faqat shu yerda tasdiqlangan juftlik bo'lsa birga ishlaydi.
      </p>
      {(campaign.combinations ?? []).length === 0 && <p className="text-sm text-muted-foreground">Tasdiqlangan juftlik yo'q.</p>}
      {(campaign.combinations ?? []).map((row) => {
        const partner = row.campaign_ids.find((cid) => cid !== campaign.id) ?? "";
        return (
          <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-border p-2 text-sm">
            <span className="min-w-0 break-words">
              {names.get(partner) ?? partner} · {row.cost_basis === "shared" ? "umumiy xarajat" : "alohida xarajatlar"} ·{" "}
              {row.status === "active" ? "faol" : "bekor qilingan"}
            </span>
            {row.status === "active" && (
              <Btn tone="danger" disabled={staff.busy || !reason.trim()}
                onClick={() => void staff.act(async () => {
                  await adminRevokeCombination(row.id, row.version, reason.trim());
                  onChanged(await adminCampaign(campaign.id));
                  setReason("");
                })}>
                Bekor qilish
              </Btn>
            )}
          </div>
        );
      })}
      <div className="grid gap-2 md:grid-cols-3">
        <label className="flex min-w-0 flex-col gap-1 text-sm">
          <span className="font-medium text-secondary-foreground">Ikkinchi kampaniya</span>
          <select value={other} onChange={(event) => setOther(event.target.value)} className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3">
            <option value="">Tanlang</option>
            {others.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-sm">
          <span className="font-medium text-secondary-foreground">Xarajat asosi (O)</span>
          <select value={basis} onChange={(event) => setBasis(event.target.value as typeof basis)} className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3">
            <option value="">Tanlang — standart yo'q</option>
            <option value="shared">Umumiy: bir xil bron xarajati (kattasi olinadi)</option>
            <option value="additive">Alohida: har kampaniyaning o'z xarajati (qo'shiladi)</option>
          </select>
        </label>
        <Input label="Sabab (audit)" value={reason} onChange={setReason} />
      </div>
      <Btn tone="primary" disabled={staff.busy || !other || !basis || !reason.trim()}
        onClick={() => void staff.act(async () => {
          onChanged(await adminApproveCombination(campaign.id, { other_campaign_id: other, cost_basis: basis as "shared" | "additive", reason: reason.trim() }));
          setOther("");
          setBasis("");
          setReason("");
        })}>
        Juftlikni tasdiqlash
      </Btn>
    </div>
  );
}

function ReviewsTab() {
  const [rows, setRows] = useState<ReviewDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const staff = useStaffAction();
  const load = () => {
    setError(null);
    adminReviews(true).then(setRows).catch((cause) => setError(v2ErrorMessage(cause)));
  };
  useEffect(load, []);
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Operator tekshiruvni boshlaydi va izoh yozadi; qarorni vakolatli admin qabul qiladi. Tasdiq mukofot yaratmaydi va
        taklif qiluvchini almashtirmaydi — keyingi ishlov shartlarni qayta tekshiradi.
      </p>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows === null && !error && <p className="text-sm text-muted-foreground">Yuklanmoqda...</p>}
      {rows !== null && rows.length === 0 && <p className="text-sm text-muted-foreground">Ochiq tekshiruv yo'q.</p>}
      {(rows ?? []).map((row) => (
        <div key={row.id} className="space-y-2 rounded-[12px] border border-border bg-card p-3 text-sm">
          <p className="font-semibold">
            {label(REVIEW_KINDS, row.kind)} · {label(STATUS, row.status)}
            {row.escalated_at ? " · muddati o'tgan (eskalatsiya)" : ""}
          </p>
          <p className="text-muted-foreground">Sabab: {row.reason_codes.map((code) => label(REASONS, code)).join(", ") || "-"}</p>
          <p className="text-xs text-muted-foreground">
            Dalil: {row.evidence.map((item) => `${String(item.table)}#${String(item.id)}`).join(", ") || "-"}
          </p>
          {DECISION_HINTS[row.kind] && <p className="rounded-[8px] bg-muted/60 px-2 py-1.5 text-xs text-secondary-foreground">{DECISION_HINTS[row.kind]}</p>}
          <Input label="Izoh" value={notes[row.id] ?? ""} onChange={(v) => setNotes({ ...notes, [row.id]: v })} />
          <div className="flex flex-wrap gap-2">
            {row.status === "open" && (
              <Btn disabled={staff.busy} onClick={() => void staff.act(async () => { await adminStartReview(row.id, notes[row.id]); load(); })}>
                Tekshiruvni boshlash
              </Btn>
            )}
            <Btn tone="primary" disabled={staff.busy || !(notes[row.id] ?? "").trim()}
              onClick={() => void staff.act(async () => { await adminDecideReview(row.id, "approve", (notes[row.id] ?? "").trim(), row.version); load(); })}>
              Tasdiqlash
            </Btn>
            <Btn tone="danger" disabled={staff.busy || !(notes[row.id] ?? "").trim()}
              onClick={() => void staff.act(async () => { await adminDecideReview(row.id, "reject", (notes[row.id] ?? "").trim(), row.version); load(); })}>
              Rad etish
            </Btn>
          </div>
        </div>
      ))}
      {staff.error && <p className="text-sm text-destructive">{staff.error}</p>}
      {staff.prompt}
    </div>
  );
}

function ReconciliationTab() {
  const [rows, setRows] = useState<ReconciliationIssueDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    setError(null);
    adminReconciliation().then(setRows).catch((cause) => setError(v2ErrorMessage(cause)));
  };
  useEffect(load, []);
  return (
    <div className="space-y-3">
      <Btn onClick={load}>Qayta tekshirish</Btn>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows !== null && rows.length === 0 && (
        <p className="text-sm text-success">Promo ledger, byudjet, majburiyatlar va bonuslar bir-biriga mos.</p>
      )}
      {(rows ?? []).map((row, index) => (
        <pre key={index} className="overflow-x-auto rounded-[10px] bg-muted p-2 text-xs">{row.kind}: {JSON.stringify(row.detail)}</pre>
      ))}
    </div>
  );
}

export function AdminPromoPanel() {
  const [tab, setTab] = useState<Tab>("campaigns");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" onClick={() => setTab(id)}
            className={`el-press h-9 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-semibold ${tab === id ? "bg-primary text-primary-foreground" : "bg-muted text-secondary-foreground"}`}>
            {label}
          </button>
        ))}
      </div>
      <p className="rounded-[12px] bg-accent px-3 py-2 text-xs text-primary">
        Production'da `promotions_enabled` o'chiq: kampaniyalar bu yerda tayyorlanadi, lekin foydalanuvchilarga ochilmaydi.
        Mukofot summalari, byudjet, O/M va HMAC saqlash muddati hali tasdiqlanmagan.
      </p>
      {tab === "campaigns" && <CampaignsTab />}
      {tab === "budget" && <BudgetTab />}
      {tab === "reviews" && <ReviewsTab />}
      {tab === "reconciliation" && <ReconciliationTab />}
    </div>
  );
}
