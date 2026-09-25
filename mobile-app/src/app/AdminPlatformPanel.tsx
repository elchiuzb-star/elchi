/**
 * Staff platform configuration: feature flags (F2-F4), corridors and stops (G7-G11, Q27/Q47), the parcel
 * prohibited-items policy (R5.2), the outbox queue (N8/N9) and system state (§10.8 provider quota, O8 legacy orders).
 *
 * The server decides: capabilities only hide buttons it would refuse anyway, and every production refusal (Q48 gate,
 * Q5 approval reference, Q1 locked flag, Q87 support phone, Q47 stops) is shown in plain words, never swallowed.
 * Every change goes through a confirmation that restates what will happen; the Idempotency-Key is created when that
 * confirmation opens and is reused if the server asks for an MFA step-up and the command is retried.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  activeParcelPolicy,
  adminConfirmParcelPolicy,
  adminCorridors,
  adminCreateCorridor,
  adminCreateParcelPolicy,
  adminCreateStop,
  adminDistricts,
  adminFeatureFlagHistory,
  adminFeatureFlags,
  adminLegacyOrder,
  adminOutbox,
  adminParcelPolicies,
  adminParcelCategoryVersions,
  adminCreateParcelCategoryVersion,
  adminConfirmParcelCategoryVersion,
  type ParcelCategoryVersionDTO,
  type ParcelCategoryItemInput,
  adminPatchCorridor,
  adminPatchStop,
  adminProviderQuota,
  adminQ47Violations,
  adminRegions,
  adminRetryOutbox,
  adminSetFeatureFlag,
  adminCorridorStops,
  type AdminStopDTO,
  type CorridorAdminDTO,
  type CorridorPatch,
  type CorridorRolloutState,
  type DistrictDTO,
  type FeatureFlagKey,
  type FlagChangeDTO,
  type FlagScopeType,
  type FlagValueDTO,
  type LegacyOrderViewDTO,
  type OutboxEventAdminDTO,
  type ParcelPolicyDTO,
  type ParcelPolicyItemCreate,
  type ParcelPolicyVersionDTO,
  type ProviderQuotaDTO,
  type Q47ViolationDTO,
  type RegionDTO,
  type StopDTO,
  type StopPatch,
} from "../api/v2/admin-platform.api";
import { newIdempotencyKey } from "../api/v2/http";
import { stepUp } from "../api/v2/mfa.api";
import { capabilities } from "../api/v2/ops.api";
import { ApiError } from "../types/api";
import { formatAdminDate } from "../utils/date";
import { formatUzs } from "../utils/money";
import { v2ErrorMessage } from "../utils/v2Errors";
import {
  COUNTRY_SCOPE_REF,
  FLAG_KEYS,
  FLAG_META,
  POLICY_CATEGORY_LABELS,
  POLICY_STATUS_LABELS,
  QUOTA_STATE_LABELS,
  ROLLOUT_LABELS,
  ROLLOUT_TRANSITIONS,
  SCOPE_LABELS,
  SCOPE_PRECEDENCE,
  corridorReasonLabel,
  corridorRefusalMessage,
  describeResolution,
  flagRefusalMessage,
  policyItemProblem,
  policyRefusalMessage,
  policySummary,
  resolveFlag,
  scopeRefProblem,
  stopHasEvidence,
} from "./adminPlatform";
import { ShieldAlert } from "./ui/icons";

export type AdminPlatformTab = "flags" | "corridors" | "policy" | "categories" | "outbox" | "system";
type Tab = AdminPlatformTab;

const TABS: Array<[Tab, string]> = [
  ["flags", "Flaglar"],
  ["corridors", "Koridor va bekatlar"],
  ["policy", "Pochta siyosati"],
  ["categories", "Pochta o'lchamlari"],
  ["outbox", "Outbox"],
  ["system", "Tizim holati"],
];

/** Capabilities that unlock the mutating controls of each tab (the server checks them again). */
export const PLATFORM_CAPABILITIES = {
  view: "ops.view",
  flags: "ops.feature_flag_manage",
  corridors: "ops.corridor_manage",
  policy: "platform.policy_manage",
  outbox: "ops.booking_command",
} as const;

type Caps = { has: (capability: string) => boolean };

// --- small building blocks ------------------------------------------------------------------------------------------

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

function Field(props: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; hint?: string; type?: string }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      <input
        aria-label={props.label}
        type={props.type ?? "text"}
        value={props.value}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3 text-foreground outline-none"
      />
      {props.hint && <span className="text-xs text-muted-foreground">{props.hint}</span>}
    </label>
  );
}

function Select(props: { label: string; value: string; onChange: (v: string) => void; options: Array<[string, string]> }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      <select
        aria-label={props.label}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3"
      >
        {props.options.map(([value, text]) => (
          <option key={value} value={value}>{text}</option>
        ))}
      </select>
    </label>
  );
}

function Loading() {
  return <p className="text-sm text-muted-foreground">Yuklanmoqda...</p>;
}

function ErrorText({ children }: { children: ReactNode }) {
  return <p role="alert" className="text-sm text-destructive">{children}</p>;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function toInt(value: string): number | null {
  if (!value.trim()) return null;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 ? n : null;
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

type Pending = { title: string; lines: string[]; tone?: "primary" | "danger"; run: (idempotencyKey: string) => Promise<void> };

/**
 * One confirmed staff command at a time: `ask()` opens the confirmation with a fresh Idempotency-Key, `confirm`
 * runs it, a `step_up_required` answer asks for the authenticator code and retries with the *same* key.
 */
function useConfirmedAction(explain: (error: unknown) => string | null = () => null) {
  const [pending, setPending] = useState<(Pending & { key: string }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState<null | (() => Promise<void>)>(null);
  const [code, setCode] = useState("");

  function message(cause: unknown): string {
    return explain(cause) ?? v2ErrorMessage(cause);
  }

  function ask(next: Pending) {
    setError(null);
    setRetry(null);
    setPending({ ...next, key: newIdempotencyKey() });
  }

  async function confirm() {
    if (!pending) return;
    const { run, key } = pending;
    const work = () => run(key);
    setPending(null);
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (cause) {
      if (isStepUp(cause)) {
        setRetry(() => work);
        setError("Bu amal uchun autentifikator kodi kerak (MFA).");
      } else {
        setError(message(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  async function prove() {
    if (!retry) return;
    setBusy(true);
    setError(null);
    try {
      const proved = await stepUp(code.trim());
      if (!proved) throw new Error("Kod tasdiqlanmadi");
      const again = retry;
      setRetry(null);
      setCode("");
      await again();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  const view = (
    <>
      {pending && (
        <div role="dialog" aria-label="Tasdiqlash" className="space-y-2 rounded-[12px] border border-primary/40 bg-accent p-3 text-sm">
          <p className="font-semibold text-foreground">{pending.title}</p>
          <ul className="list-disc space-y-0.5 pl-5 text-secondary-foreground">
            {pending.lines.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Btn tone={pending.tone ?? "primary"} onClick={() => void confirm()}>Tasdiqlayman</Btn>
            <Btn onClick={() => setPending(null)}>Bekor qilish</Btn>
          </div>
        </div>
      )}
      {error && <ErrorText>{error}</ErrorText>}
      {retry && (
        <div className="flex flex-wrap items-end gap-2 rounded-[12px] border border-warning/30 bg-warning/8 p-3">
          <ShieldAlert size={18} color="var(--warning)" />
          <Field label="Autentifikator kodi" value={code} onChange={setCode} placeholder="123456" />
          <Btn tone="primary" disabled={busy || code.trim().length < 6} onClick={() => void prove()}>
            Tasdiqlash va davom etish
          </Btn>
        </div>
      )}
    </>
  );
  return { ask, busy: busy || pending !== null, view };
}

function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setError(null);
    load()
      .then((value) => alive && setData(value))
      .catch((cause) => alive && setError(v2ErrorMessage(cause)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((n) => n + 1), setData };
}

// --- flags ----------------------------------------------------------------------------------------------------------

function FlagHistory({ flagKey }: { flagKey: FeatureFlagKey }) {
  const [items, setItems] = useState<FlagChangeDTO[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const more = (after: string | null) =>
    adminFeatureFlagHistory(flagKey, { cursor: after, limit: 20 })
      .then((page) => {
        setItems((prev) => [...(after ? prev ?? [] : []), ...page.items]);
        setCursor(page.nextCursor);
      })
      .catch((cause) => setError(v2ErrorMessage(cause)));
  useEffect(() => {
    void more(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flagKey]);
  if (error) return <ErrorText>{error}</ErrorText>;
  if (items === null) return <Loading />;
  if (items.length === 0) return <Empty>Tarix bo'sh: bu flag hali o'zgartirilmagan.</Empty>;
  return (
    <div className="space-y-1">
      {items.map((row) => (
        <p key={`${row.scope_type}-${row.scope_ref}-${row.version}-${row.changed_at}`} className="rounded-[8px] bg-muted/50 px-2 py-1 text-xs">
          {formatAdminDate(row.changed_at)} · {SCOPE_LABELS[row.scope_type]} {row.scope_ref} · v{row.version} ·{" "}
          {row.old_enabled === null || row.old_enabled === undefined ? "yangi" : row.old_enabled ? "yoqiq" : "o'chiq"} →{" "}
          <b>{row.new_enabled ? "yoqiq" : "o'chiq"}</b> · {row.actor ?? "tizim"} · {row.reason}
          {row.approval_reference ? ` · tasdiq: ${row.approval_reference}` : ""}
        </p>
      ))}
      {cursor && <Btn onClick={() => void more(cursor)}>Ko'proq</Btn>}
    </div>
  );
}

type FlagDraft = { scope: FlagScopeType; ref: string; enabled: boolean; reason: string; approval: string; expected: number | null };

function FlagsTab({ caps }: { caps: Caps }) {
  const flags = useLoad(() => adminFeatureFlags(), []);
  const corridors = useLoad(() => adminCorridors({ limit: 100 }).then((page) => page.items), []);
  const [corridorId, setCorridorId] = useState("");
  const [historyOf, setHistoryOf] = useState<FeatureFlagKey | null>(null);
  const [editing, setEditing] = useState<FeatureFlagKey | null>(null);
  const [draft, setDraft] = useState<FlagDraft>({ scope: "country", ref: COUNTRY_SCOPE_REF, enabled: false, reason: "", approval: "", expected: null });
  const action = useConfirmedAction((cause) => {
    if (cause instanceof ApiError && cause.code === "VERSION_CONFLICT") flags.reload();
    return flagRefusalMessage(cause);
  });
  const canEdit = caps.has(PLATFORM_CAPABILITIES.flags);
  const rows = flags.data ?? [];
  const corridor = (corridors.data ?? []).find((c) => c.id === corridorId) ?? null;
  const context = corridor
    ? { corridorRef: corridor.id, regionRefs: [corridor.origin_region.code, corridor.destination_region.code] }
    : {};

  function startEdit(key: FeatureFlagKey, row?: FlagValueDTO) {
    setEditing(key);
    setDraft(
      row
        ? { scope: row.scope_type, ref: row.scope_ref, enabled: !row.enabled, reason: "", approval: row.approval_reference ?? "", expected: row.version }
        : { scope: "corridor", ref: corridorId, enabled: true, reason: "", approval: "", expected: null },
    );
  }

  function submit(key: FeatureFlagKey) {
    const meta = FLAG_META[key];
    const existing = rows.find((r) => r.flag_key === key && r.scope_type === draft.scope && r.scope_ref === draft.ref.trim());
    const expected = existing ? existing.version : null;
    const lines = [
      `${meta.label}: ${SCOPE_LABELS[draft.scope]} «${draft.ref.trim()}» → ${draft.enabled ? "YOQISH" : "o'chirish"}`,
      `Sabab (audit): ${draft.reason.trim()}`,
    ];
    if (draft.approval.trim()) lines.push(`Tasdiq hujjati: ${draft.approval.trim()}`);
    if (draft.enabled && meta.q48Gated) lines.push("Production'da Q48 ishga tushirish sharti o'tmagan bo'lsa server rad etadi.");
    if (draft.enabled && meta.needsApprovalReference) lines.push("Production'da faqat super_admin va tasdiq hujjati bilan yoqiladi (Q5).");
    action.ask({
      title: "Flag qiymatini o'zgartirishni tasdiqlang",
      lines,
      tone: draft.enabled ? "primary" : "danger",
      run: async (key2) => {
        await adminSetFeatureFlag(
          key,
          draft.scope,
          draft.ref.trim(),
          { enabled: draft.enabled, reason: draft.reason.trim(), approval_reference: draft.approval.trim() || null, expected_version: expected },
          key2,
        );
        setEditing(null);
        flags.reload();
      },
    });
  }

  const refProblem = scopeRefProblem(draft.scope, draft.ref);
  return (
    <div className="space-y-4">
      <p className="rounded-[12px] bg-accent px-3 py-2 text-xs text-primary">
        Ustunlik: kohorta → koridor → hudud → mamlakat. Qator bo'lmasa standart qiymat; bir darajada ziddiyatli qatorlar
        bo'lsa xavfsiz standart (Q26). Production'da v2 xizmat flaglari Q48 sharti o'tmaguncha yoqilmaydi (Q56) va faqat
        shu panel/API orqali o'zgaradi (Q72).
      </p>
      <Select
        label="Samarali qiymatni ko'rish uchun koridor"
        value={corridorId}
        onChange={setCorridorId}
        options={[["", "Faqat mamlakat (UZ)"], ...(corridors.data ?? []).map((c): [string, string] => [c.id, `${c.name} (${ROLLOUT_LABELS[c.rollout_state]})`])]}
      />
      {flags.error && <ErrorText>{flags.error}</ErrorText>}
      {!flags.data && !flags.error && <Loading />}
      {flags.data && FLAG_KEYS.map((key) => {
        const meta = FLAG_META[key];
        const own = SCOPE_PRECEDENCE.flatMap((scope) => rows.filter((r) => r.flag_key === key && r.scope_type === scope));
        const country = resolveFlag(rows, key, {});
        const scoped = corridor ? resolveFlag(rows, key, context) : null;
        return (
          <section key={key} aria-label={meta.label} className="space-y-2 rounded-[14px] border border-border bg-card p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-semibold text-foreground">{meta.label} <span className="text-xs text-muted-foreground">({key})</span></p>
              <p className="text-sm">
                Mamlakat: <b>{country.enabled ? "yoqiq" : "o'chiq"}</b>
                {scoped && <> · {corridor?.name}: <b>{scoped.enabled ? "yoqiq" : "o'chiq"}</b> ({describeResolution(scoped)})</>}
              </p>
            </div>
            <p className="text-xs text-muted-foreground">{meta.hint} Standart: {meta.defaultValue ? "yoqiq" : "o'chiq"}.</p>
            {own.length === 0 && <Empty>Saqlangan qator yo'q — hamma joyda standart qiymat.</Empty>}
            {own.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-border p-2 text-sm">
                <span className="min-w-0 break-words">
                  {SCOPE_LABELS[row.scope_type]} «{row.scope_ref}» · <b>{row.enabled ? "yoqiq" : "o'chiq"}</b> · v{row.version} ·{" "}
                  {row.updated_by ?? "tizim"} · {formatAdminDate(row.updated_at)}
                  {row.approval_reference ? ` · tasdiq: ${row.approval_reference}` : ""}
                </span>
                {canEdit && (
                  <Btn disabled={action.busy} onClick={() => startEdit(key, row)}>{row.enabled ? "O'chirish…" : "Yoqish…"}</Btn>
                )}
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              {canEdit && <Btn disabled={action.busy} onClick={() => startEdit(key)}>Yangi doira qo'shish…</Btn>}
              <Btn onClick={() => setHistoryOf(historyOf === key ? null : key)}>{historyOf === key ? "Tarixni yopish" : "Tarix"}</Btn>
            </div>
            {historyOf === key && <FlagHistory flagKey={key} />}
            {editing === key && (
              <div className="grid gap-2 rounded-[12px] border border-dashed border-border p-3 md:grid-cols-3">
                <Select
                  label="Doira turi"
                  value={draft.scope}
                  onChange={(v) => setDraft({ ...draft, scope: v as FlagScopeType, ref: v === "country" ? COUNTRY_SCOPE_REF : "" })}
                  options={SCOPE_PRECEDENCE.map((s): [string, string] => [s, SCOPE_LABELS[s]])}
                />
                {draft.scope === "corridor" ? (
                  <Select
                    label="Koridor"
                    value={draft.ref}
                    onChange={(v) => setDraft({ ...draft, ref: v })}
                    options={[["", "Tanlang"], ...(corridors.data ?? []).map((c): [string, string] => [c.id, c.name])]}
                  />
                ) : (
                  <Field label="Doira qiymati" value={draft.ref} onChange={(v) => setDraft({ ...draft, ref: v })}
                    hint={draft.ref ? refProblem ?? undefined : undefined} />
                )}
                <Select
                  label="Yangi qiymat"
                  value={draft.enabled ? "on" : "off"}
                  onChange={(v) => setDraft({ ...draft, enabled: v === "on" })}
                  options={[["on", "Yoqiq"], ["off", "O'chiq"]]}
                />
                <Field label="Sabab (audit)" value={draft.reason} onChange={(v) => setDraft({ ...draft, reason: v })} />
                {meta.needsApprovalReference && (
                  <Field label="Tasdiq hujjati" value={draft.approval} onChange={(v) => setDraft({ ...draft, approval: v })}
                    hint="Production'da yoqish uchun majburiy (Q5)." />
                )}
                <div className="flex items-end gap-2">
                  <Btn tone="primary" disabled={action.busy || !draft.reason.trim() || Boolean(refProblem)} onClick={() => submit(key)}>
                    Davom etish
                  </Btn>
                  <Btn onClick={() => setEditing(null)}>Yopish</Btn>
                </div>
              </div>
            )}
          </section>
        );
      })}
      {action.view}
    </div>
  );
}

// --- corridors and stops --------------------------------------------------------------------------------------------

function Q47Banner({ rows, error }: { rows: Q47ViolationDTO[] | null; error: string | null }) {
  if (error) return <ErrorText>Q47 tekshiruvi: {error}</ErrorText>;
  if (rows === null) return <Loading />;
  if (rows.length === 0) {
    return <p className="rounded-[12px] bg-success/10 px-3 py-2 text-sm text-success">Q47: barcha pilot/faol koridorlarda ≥ 2 faol bekat va dalil bor.</p>;
  }
  return (
    <div role="alert" className="space-y-1 rounded-[12px] border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      <p className="font-semibold">Q47 buzilgan koridorlar: {rows.length}</p>
      {rows.map((row) => (
        <p key={row.corridor_id}>
          {row.name} ({ROLLOUT_LABELS[row.rollout_state]}) · faol bekatlar: {row.active_stops} ·{" "}
          {row.reasons.map(corridorReasonLabel).join("; ")}
          {row.stops_missing_evidence.length > 0 && ` · dalilsiz: ${row.stops_missing_evidence.join(", ")}`}
        </p>
      ))}
    </div>
  );
}

function StopEditor({
  stop, caps, onSaved,
}: { stop: { id: string; version: number; meeting_note?: string | null; meeting_photo_file_id?: string | null; is_active: boolean; sequence_hint: number }; caps: Caps; onSaved: (s: AdminStopDTO) => void }) {
  const [note, setNote] = useState(stop.meeting_note ?? "");
  const [photo, setPhoto] = useState(stop.meeting_photo_file_id ?? "");
  const [active, setActive] = useState(stop.is_active);
  const [seq, setSeq] = useState(String(stop.sequence_hint));
  const action = useConfirmedAction(corridorRefusalMessage);
  if (!caps.has(PLATFORM_CAPABILITIES.corridors)) return null;

  function save() {
    const body: StopPatch = { expected_version: stop.version };
    const lines: string[] = [];
    if (note.trim() !== (stop.meeting_note ?? "").trim()) { body.meeting_note = note.trim() || null; lines.push(`Uchrashuv izohi: ${note.trim() || "(bo'sh)"}`); }
    if (photo.trim() !== (stop.meeting_photo_file_id ?? "")) { body.meeting_photo_file_id = photo.trim() || null; lines.push(`Foto fayl: ${photo.trim() || "(yo'q)"}`); }
    if (active !== stop.is_active) { body.is_active = active; lines.push(active ? "Bekat faollashtiriladi" : "Bekat o'chiriladi"); }
    const seqValue = toInt(seq);
    if (seqValue !== null && seqValue !== stop.sequence_hint) { body.sequence_hint = seqValue; lines.push(`Tartib: ${seqValue}`); }
    if (lines.length === 0) return;
    if (!stopHasEvidence({ meeting_note: body.meeting_note ?? note, meeting_photo_file_id: body.meeting_photo_file_id ?? (photo || null) }) && active) {
      lines.push("Diqqat: dalilsiz faol bekat pilot/faol koridorda Q47 ni buzadi — server rad etadi.");
    }
    action.ask({
      title: `Bekat ${stop.id} ni o'zgartirishni tasdiqlang`,
      lines,
      run: async (key) => onSaved(await adminPatchStop(stop.id, body, key)),
    });
  }

  return (
    <div className="grid gap-2 md:grid-cols-4">
      <Field label="Uchrashuv izohi" value={note} onChange={setNote} />
      <Field label="Foto fayl id" value={photo} onChange={setPhoto} hint="Yuklangan bekat rasmi id'si" />
      <Select label="Holat" value={active ? "on" : "off"} onChange={(v) => setActive(v === "on")} options={[["on", "Faol"], ["off", "Nofaol"]]} />
      <Field label="Tartib" value={seq} onChange={setSeq} />
      <div className="md:col-span-4">
        <Btn tone="primary" disabled={action.busy} onClick={save}>Bekatni saqlash…</Btn>
        {action.view}
      </div>
    </div>
  );
}

function CorridorDetail({ corridor, caps, onChanged }: { corridor: CorridorAdminDTO; caps: Caps; onChanged: (c: CorridorAdminDTO) => void }) {
  const [name, setName] = useState(corridor.name);
  const [radius, setRadius] = useState(String(corridor.config.search_radius_m));
  const [detourMin, setDetourMin] = useState(String(corridor.config.default_max_detour_minutes));
  const [detourM, setDetourM] = useState(String(corridor.config.default_max_detour_m));
  const [target, setTarget] = useState<"" | CorridorRolloutState>("");
  const [reason, setReason] = useState("");
  const [stopForm, setStopForm] = useState({ name_uz: "", name_ru: "", district_id: "", lat: "", lng: "", seq: "0", note: "", photo: "", active: false });
  const [districts, setDistricts] = useState<DistrictDTO[]>([]);
  const allStops = useLoad<AdminStopDTO[]>(() => adminCorridorStops(corridor.id), [corridor.id]);
  const patch = useConfirmedAction(corridorRefusalMessage);
  const create = useConfirmedAction(corridorRefusalMessage);
  const canManage = caps.has(PLATFORM_CAPABILITIES.corridors);

  useEffect(() => {
    Promise.all([adminDistricts(corridor.origin_region.id), adminDistricts(corridor.destination_region.id)])
      .then(([a, b]) => setDistricts([...a, ...b.filter((d) => !a.some((x) => x.id === d.id))]))
      .catch(() => setDistricts([]));
  }, [corridor.origin_region.id, corridor.destination_region.id]);

  function remember(stop: AdminStopDTO) {
    void stop;
    allStops.reload();
  }

  function savePatch() {
    const body: CorridorPatch = { expected_version: corridor.version, reason: reason.trim() };
    const lines: string[] = [];
    if (name.trim() && name.trim() !== corridor.name) { body.name = name.trim(); lines.push(`Nomi: ${body.name}`); }
    const r = toInt(radius);
    if (r !== null && r !== corridor.config.search_radius_m) { body.search_radius_m = r; lines.push(`Qidiruv radiusi: ${r} m`); }
    const dm = toInt(detourMin);
    if (dm !== null && dm !== corridor.config.default_max_detour_minutes) { body.default_max_detour_minutes = dm; lines.push(`Maks. detour: ${dm} daq`); }
    const dd = toInt(detourM);
    if (dd !== null && dd !== corridor.config.default_max_detour_m) { body.default_max_detour_m = dd; lines.push(`Maks. detour: ${dd} m`); }
    if (target) {
      body.rollout_state = target;
      lines.push(`Holat: ${ROLLOUT_LABELS[corridor.rollout_state]} → ${ROLLOUT_LABELS[target]}`);
      if (target === "pilot" || target === "active") lines.push("Server Q27/Q47 ni tekshiradi: ≥ 2 faol bekat, har birida izoh yoki foto.");
    }
    if (lines.length === 0) return;
    lines.push(`Sabab (audit): ${reason.trim()}`);
    patch.ask({
      title: `«${corridor.name}» koridorini o'zgartirishni tasdiqlang`,
      lines,
      tone: target === "closed" ? "danger" : "primary",
      run: async (key) => {
        onChanged(await adminPatchCorridor(corridor.id, body, key));
        setTarget("");
        setReason("");
      },
    });
  }

  function addStop() {
    const lat = Number(stopForm.lat);
    const lng = Number(stopForm.lng);
    const lines = [
      `${stopForm.name_uz.trim()} (${districts.find((d) => d.id === stopForm.district_id)?.name_uz ?? stopForm.district_id})`,
      `Nuqta: ${lat}, ${lng}`,
      stopForm.active ? "Darhol faol" : "Nofaol holda yaratiladi",
      stopHasEvidence({ meeting_note: stopForm.note, meeting_photo_file_id: stopForm.photo || null })
        ? "Dalil bor (izoh yoki foto)"
        : "Dalil yo'q — pilot/faol koridorda faol bekat bo'la olmaydi (Q27/Q47)",
    ];
    create.ask({
      title: `«${corridor.name}» ga bekat qo'shishni tasdiqlang`,
      lines,
      run: async (key) => {
        const stop = await adminCreateStop(
          corridor.id,
          {
            name_uz: stopForm.name_uz.trim(),
            name_ru: stopForm.name_ru.trim() || null,
            district_id: stopForm.district_id,
            point: { lat, lng },
            sequence_hint: toInt(stopForm.seq) ?? 0,
            is_active: stopForm.active,
            meeting_note: stopForm.note.trim() || null,
            meeting_photo_file_id: stopForm.photo.trim() || null,
          },
          key,
        );
        remember(stop);
        setStopForm({ name_uz: "", name_ru: "", district_id: "", lat: "", lng: "", seq: "0", note: "", photo: "", active: false });
      },
    });
  }

  const pointOk = Number.isFinite(Number(stopForm.lat)) && Number.isFinite(Number(stopForm.lng)) && stopForm.lat.trim() !== "" && stopForm.lng.trim() !== ""
    && Math.abs(Number(stopForm.lat)) <= 90 && Math.abs(Number(stopForm.lng)) <= 180;

  return (
    <div className="space-y-4 rounded-[14px] border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold text-foreground">{corridor.name}</h3>
        <span className="text-sm text-muted-foreground">
          {corridor.origin_region.name_uz} → {corridor.destination_region.name_uz} · {ROLLOUT_LABELS[corridor.rollout_state]} · {corridor.stops_count} ta bekat · v{corridor.version}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Xizmatlar: {corridor.enabled_services.length ? corridor.enabled_services.join(", ") : "yoqilmagan"} (flaglar bo'yicha) · konfiguratsiya
        reviziyasi {corridor.config.revision} · yangilangan {formatAdminDate(corridor.updated_at)}
      </p>

      {canManage && (
        <div className="space-y-2">
          <p className="text-sm font-semibold">Sozlamalar va holat</p>
          <div className="grid gap-2 md:grid-cols-4">
            <Field label="Nomi" value={name} onChange={setName} />
            <Field label="Qidiruv radiusi (m)" value={radius} onChange={setRadius} hint="100–50 000" />
            <Field label="Maks. detour (daqiqa)" value={detourMin} onChange={setDetourMin} />
            <Field label="Maks. detour (m)" value={detourM} onChange={setDetourM} />
            <Select
              label="Yangi holat"
              value={target}
              onChange={(v) => setTarget(v as "" | CorridorRolloutState)}
              options={[["", "O'zgarmaydi"], ...ROLLOUT_TRANSITIONS[corridor.rollout_state].map((s): [string, string] => [s, ROLLOUT_LABELS[s]])]}
            />
            <Field label="Sabab (audit)" value={reason} onChange={setReason} />
          </div>
          <Btn tone="primary" disabled={patch.busy || !reason.trim()} onClick={savePatch}>Koridorni saqlash…</Btn>
          <p className="text-xs text-muted-foreground">Production'da marshrut provayderi yo'q: detour moslash ishlamaydi, faqat bekat mosliklari (Q46).</p>
          {patch.view}
        </div>
      )}

      <div className="space-y-2">
        <p className="text-sm font-semibold">Bekatlar (hammasi, nofaollari ham)</p>
        {allStops.error && <Empty>Bekatlar o'qilmadi: {allStops.error}</Empty>}
        {!allStops.data && !allStops.error && <Loading />}
        {allStops.data && allStops.data.length === 0 && <Empty>Bu koridorda hali bekat yo'q.</Empty>}
        {(allStops.data ?? []).map((stop) => (
          <div key={stop.id} className="space-y-2 rounded-[12px] border border-border p-3 text-sm">
            <p className="font-semibold">
              {stop.name_uz} · {stop.district.name_uz} · {stop.is_active ? "faol" : "nofaol"} · v{stop.version} ·{" "}
              {stopHasEvidence(stop) ? "dalil bor" : "dalil yo'q"}
            </p>
            <p className="text-xs text-muted-foreground">
              {stop.point.lat.toFixed(5)}, {stop.point.lng.toFixed(5)} · tartib {stop.sequence_hint} · {stop.id}
            </p>
            {canManage && <StopEditor key={`${stop.id}-${stop.version}`} stop={stop} caps={caps} onSaved={remember} />}
          </div>
        ))}
      </div>

      {canManage && (
        <>
          <div className="space-y-2 rounded-[12px] border border-dashed border-border p-3">
            <p className="text-sm font-semibold">Yangi bekat</p>
            <div className="grid gap-2 md:grid-cols-3">
              <Field label="Nomi (uz)" value={stopForm.name_uz} onChange={(v) => setStopForm({ ...stopForm, name_uz: v })} />
              <Field label="Nomi (ru)" value={stopForm.name_ru} onChange={(v) => setStopForm({ ...stopForm, name_ru: v })} />
              <Select label="Tuman" value={stopForm.district_id} onChange={(v) => setStopForm({ ...stopForm, district_id: v })}
                options={[["", "Tanlang"], ...districts.map((d): [string, string] => [d.id, `${d.region.name_uz}: ${d.name_uz}`])]} />
              <Field label="Kenglik (lat)" value={stopForm.lat} onChange={(v) => setStopForm({ ...stopForm, lat: v })} />
              <Field label="Uzunlik (lng)" value={stopForm.lng} onChange={(v) => setStopForm({ ...stopForm, lng: v })} />
              <Field label="Tartib" value={stopForm.seq} onChange={(v) => setStopForm({ ...stopForm, seq: v })} />
              <Field label="Uchrashuv izohi (dalil)" value={stopForm.note} onChange={(v) => setStopForm({ ...stopForm, note: v })} />
              <Field label="Foto fayl id (dalil)" value={stopForm.photo} onChange={(v) => setStopForm({ ...stopForm, photo: v })} />
              <Select label="Holat" value={stopForm.active ? "on" : "off"} onChange={(v) => setStopForm({ ...stopForm, active: v === "on" })}
                options={[["off", "Nofaol"], ["on", "Faol"]]} />
            </div>
            <Btn tone="primary" disabled={create.busy || !stopForm.name_uz.trim() || !stopForm.district_id || !pointOk} onClick={addStop}>
              Bekat qo'shish…
            </Btn>
            {create.view}
          </div>
        </>
      )}
    </div>
  );
}

function CorridorsTab({ caps }: { caps: Caps }) {
  const [items, setItems] = useState<CorridorAdminDTO[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const q47 = useLoad(() => adminQ47Violations(), []);
  const regions = useLoad<RegionDTO[]>(() => adminRegions(), []);
  const [form, setForm] = useState({ name: "", origin: "", destination: "", radius: "3000", detourMin: "15", detourM: "5000" });
  const action = useConfirmedAction(corridorRefusalMessage);

  const load = (after: string | null) =>
    adminCorridors({ cursor: after, limit: 50 })
      .then((page) => {
        setItems((prev) => [...(after ? prev ?? [] : []), ...page.items]);
        setCursor(page.nextCursor);
      })
      .catch((cause) => setError(v2ErrorMessage(cause)));
  useEffect(() => {
    void load(null);
  }, []);

  const current = (items ?? []).find((c) => c.id === selected) ?? null;
  const regionName = (id: string) => (regions.data ?? []).find((r) => r.id === id)?.name_uz ?? id;
  const nums = { radius: toInt(form.radius), detourMin: toInt(form.detourMin), detourM: toInt(form.detourM) };
  const formOk = form.name.trim() && form.origin && form.destination && form.origin !== form.destination
    && nums.radius !== null && nums.radius >= 100 && nums.detourMin !== null && nums.detourM !== null;

  function create() {
    action.ask({
      title: "Yangi koridor (qoralama) yaratishni tasdiqlang",
      lines: [
        `${form.name.trim()}: ${regionName(form.origin)} → ${regionName(form.destination)}`,
        `Qidiruv radiusi ${nums.radius} m, detour ${nums.detourMin} daq / ${nums.detourM} m`,
        "Qoralama hech kimga ko'rinmaydi; ichki sinov uchun kamida 1 faol bekat kerak.",
      ],
      run: async (key) => {
        const created = await adminCreateCorridor(
          {
            name: form.name.trim(), origin_region_id: form.origin, destination_region_id: form.destination,
            search_radius_m: nums.radius as number, default_max_detour_minutes: nums.detourMin as number, default_max_detour_m: nums.detourM as number,
          },
          key,
        );
        setItems((prev) => [created, ...(prev ?? [])]);
        setSelected(created.id);
        setForm({ ...form, name: "" });
      },
    });
  }

  return (
    <div className="space-y-4">
      <Q47Banner rows={q47.data} error={q47.error} />
      {error && <ErrorText>{error}</ErrorText>}
      {items === null && !error && <Loading />}
      {items !== null && items.length === 0 && <Empty>Koridor yo'q.</Empty>}
      <div className="grid gap-2">
        {(items ?? []).map((c) => (
          <button key={c.id} type="button" onClick={() => setSelected(c.id)}
            className={`el-press rounded-[12px] border bg-card p-3 text-left text-sm ${selected === c.id ? "border-primary" : "border-border"}`}>
            <span className="font-semibold">{c.name}</span> · {ROLLOUT_LABELS[c.rollout_state]} · {c.stops_count} ta bekat
            {(q47.data ?? []).some((v) => v.corridor_id === c.id) && <span className="text-destructive"> · Q47 buzilgan</span>}
          </button>
        ))}
        {cursor && <Btn onClick={() => void load(cursor)}>Ko'proq</Btn>}
      </div>
      {current && (
        <CorridorDetail key={`${current.id}-${current.version}`} corridor={current} caps={caps}
          onChanged={(next) => { setItems((prev) => (prev ?? []).map((c) => (c.id === next.id ? next : c))); q47.reload(); }} />
      )}
      {caps.has(PLATFORM_CAPABILITIES.corridors) && (
        <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
          <p className="text-sm font-semibold">Yangi koridor</p>
          <div className="grid gap-2 md:grid-cols-3">
            <Field label="Koridor nomi" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
            <Select label="Qayerdan (hudud)" value={form.origin} onChange={(v) => setForm({ ...form, origin: v })}
              options={[["", "Tanlang"], ...(regions.data ?? []).map((r): [string, string] => [r.id, r.name_uz])]} />
            <Select label="Qayerga (hudud)" value={form.destination} onChange={(v) => setForm({ ...form, destination: v })}
              options={[["", "Tanlang"], ...(regions.data ?? []).map((r): [string, string] => [r.id, r.name_uz])]} />
            <Field label="Qidiruv radiusi (m)" value={form.radius} onChange={(v) => setForm({ ...form, radius: v })} />
            <Field label="Maks. detour (daqiqa)" value={form.detourMin} onChange={(v) => setForm({ ...form, detourMin: v })} />
            <Field label="Maks. detour (m)" value={form.detourM} onChange={(v) => setForm({ ...form, detourM: v })} />
          </div>
          <Btn tone="primary" disabled={action.busy || !formOk} onClick={create}>Koridor yaratish…</Btn>
          {action.view}
        </div>
      )}
    </div>
  );
}

// --- parcel policy --------------------------------------------------------------------------------------------------

const EMPTY_ITEM: ParcelPolicyItemCreate = {
  code: "", category: "prohibited", applies_to: "parcel", title_uz: "", description_uz: "",
  legal_basis: "", source_ref: "", source_checked_on: "",
};

function PolicyTab({ caps }: { caps: Caps }) {
  const versions = useLoad<ParcelPolicyVersionDTO[]>(() => adminParcelPolicies(), []);
  const active = useLoad<ParcelPolicyDTO>(() => activeParcelPolicy(), []);
  const [label, setLabel] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [items, setItems] = useState<ParcelPolicyItemCreate[]>([]);
  const [item, setItem] = useState<ParcelPolicyItemCreate>(EMPTY_ITEM);
  const action = useConfirmedAction(policyRefusalMessage);
  const canManage = caps.has(PLATFORM_CAPABILITIES.policy);
  const itemProblem = policyItemProblem(item);

  function confirmVersion(v: ParcelPolicyVersionDTO) {
    action.ask({
      title: `«${v.label}» ro'yxatini tasdiqlash`,
      lines: [
        `${v.item_count} ta band; muallif: ${v.created_by ?? "noma'lum"}`,
        "Tasdiqlangach amaldagi versiya almashtiriladi va jo'natuvchilarga shu ro'yxat ko'rsatiladi.",
        "Muallif o'z qoralamasini tasdiqlay olmaydi — ikkinchi super_admin kerak.",
      ],
      run: async (key) => {
        await adminConfirmParcelPolicy(v.id, v.version, key);
        versions.reload();
        active.reload();
      },
    });
  }

  function createDraft() {
    action.ask({
      title: "Yangi ro'yxat qoralamasini yaratishni tasdiqlang",
      lines: [`«${label.trim()}»: ${items.length} ta band`, "Qoralama hech kimga amal qilmaydi — boshqa super_admin tasdiqlaguncha."],
      run: async (key) => {
        await adminCreateParcelPolicy(
          {
            label: label.trim(),
            source_note: sourceNote.trim() || null,
            items: items.map((i) => ({
              ...i,
              legal_basis: i.legal_basis?.trim() || null,
              source_ref: i.source_ref?.trim() || null,
              source_checked_on: i.source_checked_on?.trim() || null,
            })),
          },
          key,
        );
        setLabel("");
        setSourceNote("");
        setItems([]);
        versions.reload();
      },
    });
  }

  return (
    <div className="space-y-4">
      {versions.error && <ErrorText>{versions.error}</ErrorText>}
      {!versions.data && !versions.error && <Loading />}
      {versions.data && (
        <p className={`rounded-[12px] px-3 py-2 text-sm ${versions.data.some((v) => v.status === "active") ? "bg-accent text-primary" : "bg-warning/10 text-warning"}`}>
          {policySummary(versions.data)}
        </p>
      )}
      {versions.data && versions.data.length === 0 && <Empty>Hali hech qanday versiya yaratilmagan.</Empty>}
      {(versions.data ?? []).map((v) => (
        <div key={v.id} className="space-y-1 rounded-[12px] border border-border bg-card p-3 text-sm">
          <p className="font-semibold">{v.label} · {POLICY_STATUS_LABELS[v.status] ?? v.status} · {v.item_count} ta band</p>
          <p className="text-xs text-muted-foreground">
            Muallif: {v.created_by ?? "noma'lum"} · Tasdiqlagan: {v.confirmed_by ? `${v.confirmed_by} (${formatAdminDate(v.confirmed_at)})` : "hali yo'q"}
            {v.effective_from ? ` · amalda: ${formatAdminDate(v.effective_from)}` : ""}
          </p>
          {v.status === "draft" && canManage && (
            <Btn tone="primary" disabled={action.busy} onClick={() => confirmVersion(v)}>Tasdiqlash…</Btn>
          )}
        </div>
      ))}

      <div className="space-y-2">
        <p className="text-sm font-semibold">Jo'natuvchilar ko'radigan ro'yxat</p>
        {active.error && <ErrorText>{active.error}</ErrorText>}
        {active.data && <p className="text-xs text-muted-foreground">{active.data.notice}</p>}
        {active.data && !active.data.approved && (
          <Empty>Tasdiqlangan ro'yxat yo'q — yangi pochta e'lonlari yopiq.</Empty>
        )}
        {(active.data?.items ?? []).map((i) => (
          <p key={i.code} className="rounded-[8px] bg-muted/50 px-2 py-1 text-sm">
            <b>{i.title}</b> · {POLICY_CATEGORY_LABELS[i.category] ?? i.category} · {i.description}
            {i.legal_basis ? ` · asos: ${i.legal_basis}` : ""}{i.source_ref ? ` · manba: ${i.source_ref}` : ""}
          </p>
        ))}
      </div>

      {canManage && (
        <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
          <p className="text-sm font-semibold">Yangi versiya (qoralama)</p>
          <div className="grid gap-2 md:grid-cols-2">
            <Field label="Versiya nomi" value={label} onChange={setLabel} placeholder="2026-09" />
            <Field label="Manba izohi" value={sourceNote} onChange={setSourceNote} />
          </div>
          {items.map((i, index) => (
            <div key={`${i.code}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] bg-muted/50 px-2 py-1 text-sm">
              <span>{i.code} · {POLICY_CATEGORY_LABELS[i.category]} · {i.title_uz}</span>
              <Btn tone="danger" onClick={() => setItems(items.filter((_, j) => j !== index))}>Olib tashlash</Btn>
            </div>
          ))}
          <div className="grid gap-2 md:grid-cols-4">
            <Field label="Band kodi" value={item.code} onChange={(v) => setItem({ ...item, code: v })} />
            <Select label="Toifa" value={item.category} onChange={(v) => setItem({ ...item, category: v as ParcelPolicyItemCreate["category"] })}
              options={Object.entries(POLICY_CATEGORY_LABELS)} />
            <Select label="Qo'llanadi" value={item.applies_to} onChange={(v) => setItem({ ...item, applies_to: v as ParcelPolicyItemCreate["applies_to"] })}
              options={[["parcel", "Pochta"], ["passenger_baggage", "Yo'lovchi bagaji"], ["all", "Hammasi"]]} />
            <Field label="Band nomi" value={item.title_uz} onChange={(v) => setItem({ ...item, title_uz: v })} />
            <Field label="Band tavsifi" value={item.description_uz} onChange={(v) => setItem({ ...item, description_uz: v })} />
            <Field label="Huquqiy asos" value={item.legal_basis ?? ""} onChange={(v) => setItem({ ...item, legal_basis: v })} />
            <Field label="Manba" value={item.source_ref ?? ""} onChange={(v) => setItem({ ...item, source_ref: v })} />
            <Field label="Manba tekshirilgan sana" value={item.source_checked_on ?? ""} onChange={(v) => setItem({ ...item, source_checked_on: v })} placeholder="2026-09-24" />
          </div>
          {item.code && itemProblem && <p className="text-xs text-destructive">{itemProblem}</p>}
          <div className="flex flex-wrap gap-2">
            <Btn disabled={Boolean(itemProblem)} onClick={() => { setItems([...items, item]); setItem(EMPTY_ITEM); }}>Bandni qo'shish</Btn>
            <Btn tone="primary" disabled={action.busy || label.trim().length < 2 || items.length === 0} onClick={createDraft}>
              Qoralamani saqlash…
            </Btn>
          </div>
        </div>
      )}
      {action.view}
    </div>
  );
}

// --- parcel size categories (Q140, ADR-0026) -------------------------------------------------------------------------

type CategoryForm = { code: string; name_uz: string; name_ru: string; icon_key: string; length: string; width: string; height: string; weightKg: string };
const EMPTY_CATEGORY: CategoryForm = { code: "", name_uz: "", name_ru: "", icon_key: "box_small", length: "", width: "", height: "", weightKg: "" };
const CATEGORY_ICONS: Array<[string, string]> = [["envelope", "Konvert"], ["box_small", "Kichik quti"], ["box_medium", "O'rta quti"], ["box_large", "Katta quti"], ["bag", "Sumka"]];
const CATEGORY_STATUS: Record<string, string> = { draft: "Qoralama", active: "Amalda", superseded: "Almashtirilgan" };

/** The typed row as the API item, or the reason it cannot be one. Volume is the box volume (1 cm³ = 1 ml). */
export function categoryItemFromForm(form: CategoryForm): ParcelCategoryItemInput | string {
  const [l, w, h] = [form.length, form.width, form.height].map((v) => Number(v));
  const grams = Math.round(Number(form.weightKg.replace(",", ".")) * 1000);
  if (!/^[a-z][a-z0-9_]{1,39}$/.test(form.code.trim())) return "Kod: lotin kichik harf, raqam, _ (2-40)";
  if (form.name_uz.trim().length < 2) return "Nomi (uz) kerak";
  if (![l, w, h].every((v) => Number.isInteger(v) && v > 0)) return "O'lchamlar butun sm, 0 dan katta";
  if (!Number.isFinite(grams) || grams <= 0) return "Og'irlik chegarasi 0 dan katta";
  return {
    code: form.code.trim(), name_uz: form.name_uz.trim(), name_ru: form.name_ru.trim() || null, icon_key: form.icon_key,
    max_length_cm: l, max_width_cm: w, max_height_cm: h, max_volume_ml: l * w * h, max_weight_g: grams,
  };
}

function CategoriesTab({ caps }: { caps: Caps }) {
  const versions = useLoad<ParcelCategoryVersionDTO[]>(() => adminParcelCategoryVersions(), []);
  const [label, setLabel] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [synthetic, setSynthetic] = useState(true);
  const [items, setItems] = useState<ParcelCategoryItemInput[]>([]);
  const [form, setForm] = useState<CategoryForm>(EMPTY_CATEGORY);
  const action = useConfirmedAction(policyRefusalMessage);
  const canManage = caps.has(PLATFORM_CAPABILITIES.policy);
  const candidate = categoryItemFromForm(form);
  const active = (versions.data ?? []).find((v) => v.status === "active");

  function confirmVersion(v: ParcelCategoryVersionDTO) {
    action.ask({
      title: `«${v.label}» katalogini tasdiqlash`,
      lines: [
        `${(v.items ?? []).length} ta toifa; muallif: ${v.created_by}`,
        v.synthetic ? "Bu SINTETIK katalog - production uni rad etadi." : "Tasdiqlangach jo'natuvchilar shu toifalarni ko'radi.",
        "Mavjud bronlar o'z kelishilgan toifasini saqlaydi. Kim faollashtirgani audit jurnaliga yoziladi.",
      ],
      run: async (key) => {
        await adminConfirmParcelCategoryVersion(v.id, v.version, key);
        versions.reload();
      },
    });
  }

  function createDraft() {
    action.ask({
      title: "Katalog qoralamasini saqlash",
      lines: [`«${label.trim()}»: ${items.length} ta toifa${synthetic ? " · sintetik" : ""}`, "Qoralama hech kimga amal qilmaydi - faollashtirilguncha."],
      run: async (key) => {
        await adminCreateParcelCategoryVersion({ label: label.trim(), source_note: sourceNote.trim() || null, synthetic, items }, key);
        setLabel("");
        setSourceNote("");
        setItems([]);
        versions.reload();
      },
    });
  }

  return (
    <div className="space-y-4">
      {versions.error && <ErrorText>{versions.error}</ErrorText>}
      {!versions.data && !versions.error && <Loading />}
      {versions.data && (
        <p className={`rounded-[12px] px-3 py-2 text-sm ${active && !active.synthetic ? "bg-accent text-primary" : "bg-warning/10 text-warning"}`}>
          {!active
            ? "Tasdiqlangan katalog yo'q - yangi pochta so'rovlari yopiq."
            : active.synthetic
              ? `Amalda: «${active.label}» - SINTETIK (demo qiymatlar, tasdiqlangan tarif emas; production'da yopiq).`
              : `Amalda: «${active.label}» (v${active.version}).`}
        </p>
      )}
      {versions.data && versions.data.length === 0 && <Empty>Hali hech qanday katalog versiyasi yo'q.</Empty>}
      {(versions.data ?? []).map((v) => (
        <div key={v.id} className="space-y-1 rounded-[12px] border border-border bg-card p-3 text-sm">
          <p className="font-semibold">{v.label} · {CATEGORY_STATUS[v.status] ?? v.status}{v.synthetic ? " · sintetik" : ""}</p>
          <p className="text-xs text-muted-foreground">
            Muallif: {v.created_by} · Tasdiqlagan: {v.confirmed_by ? `${v.confirmed_by} (${formatAdminDate(v.confirmed_at)})` : "hali yo'q"}
          </p>
          {(v.items ?? []).map((i) => (
            <p key={i.id} className="rounded-[8px] bg-muted/50 px-2 py-1 text-xs">
              <b>{i.name_uz}</b> ({i.code}) · {i.max_length_cm}×{i.max_width_cm}×{i.max_height_cm} sm · {i.max_weight_g / 1000} kg
            </p>
          ))}
          {v.status === "draft" && canManage && <Btn tone="primary" disabled={action.busy} onClick={() => confirmVersion(v)}>Tasdiqlash…</Btn>}
        </div>
      ))}

      {canManage && (
        <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
          <p className="text-sm font-semibold">Yangi katalog (qoralama)</p>
          <p className="text-xs text-muted-foreground">Qiymatlar tasdiqlangan manbadan kiritiladi. Demo qiymat bo'lsa «sintetik» belgisi qolsin.</p>
          <div className="grid gap-2 md:grid-cols-2">
            <Field label="Versiya nomi" value={label} onChange={setLabel} placeholder="2026-09" />
            <Field label="Manba izohi" value={sourceNote} onChange={setSourceNote} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={synthetic} onChange={(event) => setSynthetic(event.target.checked)} />
            Sintetik (demo/test qiymatlar)
          </label>
          {items.map((i, index) => (
            <div key={`${i.code}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] bg-muted/50 px-2 py-1 text-sm">
              <span>{i.code} · {i.name_uz} · {i.max_length_cm}×{i.max_width_cm}×{i.max_height_cm} sm · {i.max_weight_g / 1000} kg</span>
              <Btn tone="danger" onClick={() => setItems(items.filter((_, j) => j !== index))}>Olib tashlash</Btn>
            </div>
          ))}
          <div className="grid gap-2 md:grid-cols-4">
            <Field label="Kod" value={form.code} onChange={(v) => setForm({ ...form, code: v })} placeholder="small_box" />
            <Field label="Nomi (uz)" value={form.name_uz} onChange={(v) => setForm({ ...form, name_uz: v })} />
            <Field label="Nomi (ru)" value={form.name_ru} onChange={(v) => setForm({ ...form, name_ru: v })} />
            <Select label="Belgi" value={form.icon_key} onChange={(v) => setForm({ ...form, icon_key: v })} options={CATEGORY_ICONS} />
            <Field label="Uzunlik, sm" value={form.length} onChange={(v) => setForm({ ...form, length: v })} />
            <Field label="Kenglik, sm" value={form.width} onChange={(v) => setForm({ ...form, width: v })} />
            <Field label="Balandlik, sm" value={form.height} onChange={(v) => setForm({ ...form, height: v })} />
            <Field label="Og'irlik chegarasi, kg" value={form.weightKg} onChange={(v) => setForm({ ...form, weightKg: v })} />
          </div>
          {form.code && typeof candidate === "string" && <p className="text-xs text-destructive">{candidate}</p>}
          <div className="flex flex-wrap gap-2">
            <Btn disabled={typeof candidate === "string"} onClick={() => { if (typeof candidate !== "string") { setItems([...items, candidate]); setForm(EMPTY_CATEGORY); } }}>
              Toifani qo'shish
            </Btn>
            <Btn tone="primary" disabled={action.busy || label.trim().length < 2 || items.length === 0} onClick={createDraft}>Qoralamani saqlash…</Btn>
          </div>
        </div>
      )}
      {action.view}
    </div>
  );
}

// --- outbox ---------------------------------------------------------------------------------------------------------

function OutboxTab({ caps }: { caps: Caps }) {
  const [state, setState] = useState<"failed" | "dead">("failed");
  const [items, setItems] = useState<OutboxEventAdminDTO[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const action = useConfirmedAction();

  const load = (after: string | null) =>
    adminOutbox({ state, cursor: after, limit: 50 })
      .then((page) => {
        setItems((prev) => [...(after ? prev ?? [] : []), ...page.items]);
        setCursor(page.nextCursor);
      })
      .catch((cause) => setError(v2ErrorMessage(cause)));
  useEffect(() => {
    setItems(null);
    setError(null);
    void load(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  function retry(event: OutboxEventAdminDTO) {
    const reason = (reasons[event.id] ?? "").trim();
    action.ask({
      title: "Hodisani qayta yuborishni tasdiqlang",
      lines: [`${event.event_type} · ${event.aggregate_type} ${event.aggregate_id} · ${event.attempts} urinish`, `Sabab (audit): ${reason}`],
      run: async (key) => {
        await adminRetryOutbox(event.id, reason, key);
        void load(null);
      },
    });
  }

  return (
    <div className="space-y-3">
      <Select label="Holat" value={state} onChange={(v) => setState(v as "failed" | "dead")}
        options={[["failed", "Xato (qayta uriniladi)"], ["dead", "To'xtagan (dead letter)"]]} />
      {error && <ErrorText>{error}</ErrorText>}
      {items === null && !error && <Loading />}
      {items !== null && items.length === 0 && <Empty>Bu holatda hodisa yo'q.</Empty>}
      {(items ?? []).map((event) => (
        <div key={event.id} className="space-y-2 rounded-[12px] border border-border bg-card p-3 text-sm">
          <p className="font-semibold">{event.event_type} · {event.aggregate_type} {event.aggregate_id} (v{event.aggregate_version})</p>
          <p className="text-xs text-muted-foreground">
            {formatAdminDate(event.occurred_at)} · urinishlar: {event.attempts} · keyingisi: {formatAdminDate(event.next_attempt_at)}
            {event.dead_lettered_at ? ` · to'xtatilgan: ${formatAdminDate(event.dead_lettered_at)}` : ""}
          </p>
          {event.last_error && <p className="break-words text-xs text-destructive">{event.last_error}</p>}
          <Btn onClick={() => setOpen(open === event.id ? null : event.id)}>{open === event.id ? "Payloadni yopish" : "Payload"}</Btn>
          {open === event.id && <pre className="overflow-x-auto rounded-[10px] bg-muted p-2 text-xs">{JSON.stringify(event.payload, null, 2)}</pre>}
          {caps.has(PLATFORM_CAPABILITIES.outbox) && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Qayta yuborish sababi" value={reasons[event.id] ?? ""} onChange={(v) => setReasons({ ...reasons, [event.id]: v })} />
              <Btn tone="primary" disabled={action.busy || (reasons[event.id] ?? "").trim().length < 3} onClick={() => retry(event)}>
                Qayta yuborish…
              </Btn>
            </div>
          )}
        </div>
      ))}
      {cursor && <Btn onClick={() => void load(cursor)}>Ko'proq</Btn>}
      {action.view}
    </div>
  );
}

// --- system state ---------------------------------------------------------------------------------------------------

/** O8: one v1 order, read-only (Q4). Nothing here can change it; the database refuses writes to the projection. */
export function AdminLegacyOrderDetail({ legacyOrderNumber, onClose }: { legacyOrderNumber: string; onClose?: () => void }) {
  const order = useLoad<LegacyOrderViewDTO>(() => adminLegacyOrder(legacyOrderNumber), [legacyOrderNumber]);
  return (
    <div className="space-y-2 rounded-[14px] border border-border bg-card p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold">v1 buyurtma {legacyOrderNumber}</p>
        {onClose && <Btn onClick={onClose}>Yopish</Btn>}
      </div>
      {order.error && <ErrorText>{order.error}</ErrorText>}
      {!order.data && !order.error && <Loading />}
      {order.data && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">Holat</dt><dd>{order.data.status}</dd>
          <dt className="text-muted-foreground">Yo'nalish</dt><dd className="break-words">{order.data.route_summary}</dd>
          <dt className="text-muted-foreground">Yakuniy narx</dt>
          <dd>{order.data.final_price_minor === null || order.data.final_price_minor === undefined ? "belgilanmagan" : formatUzs(order.data.final_price_minor / 100)}</dd>
          <dt className="text-muted-foreground">Legacy hisoblangan haq</dt>
          <dd>
            {order.data.legacy_calculated_fee_minor === null || order.data.legacy_calculated_fee_minor === undefined
              ? "yo'q"
              : `${formatUzs(order.data.legacy_calculated_fee_minor / 100)} (hisoblangan, undirilgan emas)`}
          </dd>
          <dt className="text-muted-foreground">Yaratilgan</dt><dd>{formatAdminDate(order.data.created_at)}</dd>
          <dt className="text-muted-foreground">Yangilangan</dt><dd>{formatAdminDate(order.data.updated_at)}</dd>
          <dt className="text-muted-foreground">Belgilar</dt>
          <dd>{(order.data.flags ?? []).length ? (order.data.flags ?? []).map((f) => (f === "unknown_time" ? "vaqti noma'lum" : f === "unknown_dimensions" ? "o'lchami noma'lum" : f)).join(", ") : "-"}</dd>
        </dl>
      )}
      <p className="text-xs text-muted-foreground">Faqat o'qish uchun (Q4): v1 buyurtmalar v2 dan o'zgartirilmaydi.</p>
    </div>
  );
}

function SystemTab() {
  const [day, setDay] = useState("");
  const quota = useLoad<ProviderQuotaDTO[]>(() => adminProviderQuota(day || undefined), [day]);
  const [lookup, setLookup] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-sm font-semibold">Xarita/marshrut provayderi kvotasi</p>
        <Field label="Kun (YYYY-MM-DD, bo'sh = bugun)" value={day} onChange={setDay} />
        {quota.error && <ErrorText>{quota.error}</ErrorText>}
        {!quota.data && !quota.error && <Loading />}
        {quota.data && quota.data.length === 0 && (
          <Empty>Bu kunda pullik provayder chaqiruvi bo'lmagan (production'da marshrut provayderi o'chiq, Q24). Bu «noma'lum» degani emas.</Empty>
        )}
        {(quota.data ?? []).map((q) => (
          <p key={`${q.provider}-${q.day}`} className={`rounded-[8px] px-2 py-1 text-sm ${q.state === "ok" ? "bg-muted/50" : q.state === "warn" ? "bg-warning/10 text-warning" : "bg-destructive/10 text-destructive"}`}>
            {q.provider} · {q.day} · {q.calls} chaqiruv · {q.credits} kredit / {q.limit} · {Math.round(q.ratio * 100)}% ·{" "}
            {QUOTA_STATE_LABELS[q.state] ?? q.state} · xatolar: {q.failures}{q.estimated ? " · taxminiy" : ""}
          </p>
        ))}
      </div>
      <div className="space-y-2">
        <p className="text-sm font-semibold">v1 buyurtmani raqam bo'yicha ko'rish</p>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Buyurtma raqami" value={lookup} onChange={setLookup} />
          <Btn disabled={!lookup.trim()} onClick={() => setShown(lookup.trim())}>Ko'rish</Btn>
        </div>
        {shown && <AdminLegacyOrderDetail legacyOrderNumber={shown} onClose={() => setShown(null)} />}
      </div>
    </div>
  );
}

// --- panel ----------------------------------------------------------------------------------------------------------

export type AdminPlatformPanelProps = {
  /** Initial sub-tab (default: flags). */
  initialTab?: Tab;
};

export function AdminPlatformPanel({ initialTab = "flags" }: AdminPlatformPanelProps = {}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [caps, setCaps] = useState<string[] | null>(null);
  useEffect(() => {
    capabilities()
      .then((dto) => setCaps(dto.capabilities as string[]))
      .catch(() => setCaps([]));
  }, []);
  const has = useMemo<Caps>(() => ({ has: (capability: string) => (caps ?? []).includes(capability) }), [caps]);
  return (
    <div className="space-y-4">
      <div role="tablist" className="flex items-center gap-2 overflow-x-auto pb-1">
        {TABS.map(([id, text]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`el-press h-9 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-semibold ${tab === id ? "bg-primary text-primary-foreground" : "bg-muted text-secondary-foreground"}`}>
            {text}
          </button>
        ))}
      </div>
      {caps === null ? (
        <Loading />
      ) : (
        <>
          {tab === "flags" && <FlagsTab caps={has} />}
          {tab === "corridors" && <CorridorsTab caps={has} />}
          {tab === "policy" && <PolicyTab caps={has} />}
          {tab === "categories" && <CategoriesTab caps={has} />}
          {tab === "outbox" && <OutboxTab caps={has} />}
          {tab === "system" && <SystemTab />}
        </>
      )}
    </div>
  );
}
