/**
 * Staff platform configuration (design "Elchi Admin" → Platforma sozlamalari): feature flags (F2-F4), corridors
 * (G7-G11, ADR-0028 launch gate), the parcel prohibited-items policy (R5.2), parcel size categories (Q140), the outbox
 * queue (N8/N9) and system state (§10.8 provider quota, O8 legacy orders).
 *
 * The server decides: capabilities only hide buttons it would refuse anyway, and every production refusal (Q48 gate,
 * Q5 approval reference, Q1 locked flag, Q87 support phone, no confirmed road) is shown in plain words, never swallowed.
 * Flags change only through this admin API (Q72). Turning on `passenger_enabled` or `card_payments_enabled` is
 * offered to super_admin only (Q5); `driver_listing_enabled` is archived (Q138) and offers no change. Every change
 * goes through a confirmation; the Idempotency-Key is created when that confirmation opens and is reused when the
 * server asks for an MFA step-up (`useStepUp`) and the command is replayed.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  activeParcelPolicy,
  adminConfirmParcelPolicy,
  adminCorridors,
  adminCreateCorridor,
  adminCreateParcelPolicy,
  adminFeatureFlagHistory,
  adminFeatureFlags,
  adminLegacyOrder,
  adminOutbox,
  adminParcelPolicies,
  adminParcelCategoryVersions,
  adminCreateParcelCategoryVersion,
  adminConfirmParcelCategoryVersion,
  adminPatchCorridor,
  adminProviderQuota,
  adminQ47Violations,
  adminRegions,
  adminRetryOutbox,
  adminSetFeatureFlag,
  type CorridorAdminDTO,
  type CorridorPatch,
  type CorridorRolloutState,
  type FeatureFlagKey,
  type FlagChangeDTO,
  type FlagScopeType,
  type FlagValueDTO,
  type LegacyOrderViewDTO,
  type OutboxEventAdminDTO,
  type ParcelCategoryItemInput,
  type ParcelCategoryVersionDTO,
  type ParcelPolicyDTO,
  type ParcelPolicyItemCreate,
  type ParcelPolicyVersionDTO,
  type ProviderQuotaDTO,
  type Q47ViolationDTO,
  type RegionDTO,
} from "../api/v2/admin-platform.api";
import { capabilities } from "../api/v2/ops.api";
import { translate } from "../i18n";
import { useT } from "../i18n/react";
import { ApiError } from "../types/api";
import { formatAdminDate } from "../utils/date";
import { formatUzs } from "../utils/money";
import { v2ErrorMessage } from "../utils/v2Errors";
import {
  COUNTRY_SCOPE_REF,
  FLAG_KEYS,
  FLAG_META,
  POLICY_CATEGORIES,
  SCOPE_PRECEDENCE,
  corridorReasonLabel,
  corridorRefusalMessage,
  describeResolution,
  flagBadge,
  flagHint,
  flagLabel,
  flagRefusalMessage,
  mayOfferFlagValue,
  policyCategoryLabel,
  policyItemProblem,
  policyRefusalMessage,
  policyStatusLabel,
  policySummary,
  quotaStateLabel,
  resolveFlag,
  rolloutLabel,
  rolloutTone,
  scopeLabel,
  scopeRefProblem,
} from "./adminPlatform";
import { Badge, Btn, Card, Chips, Empty, Field, Loading, Note, Section, Select, Tabs, useConfirmedCommand } from "./adminMoneyUi";

export type AdminPlatformTab = "flags" | "corridors" | "policy" | "categories" | "outbox" | "system";
type Tab = AdminPlatformTab;

const TABS: Tab[] = ["flags", "corridors", "policy", "categories", "outbox", "system"];

/** Capabilities that unlock the mutating controls of each tab (the server checks them again). */
export const PLATFORM_CAPABILITIES = {
  view: "ops.view",
  flags: "ops.feature_flag_manage",
  corridors: "ops.corridor_manage",
  policy: "platform.policy_manage",
  outbox: "ops.booking_command",
} as const;

type Caps = { has: (capability: string) => boolean; superAdmin: boolean };

function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {children}
    </p>
  );
}

function toInt(value: string): number | null {
  if (!value.trim()) return null;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

function onOff(enabled: boolean): string {
  return enabled ? translate("admin.platform.on") : translate("admin.platform.off");
}

function useLoad<R>(load: () => Promise<R>, deps: unknown[]) {
  const [data, setData] = useState<R | null>(null);
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
  const t = useT();
  const [items, setItems] = useState<FlagChangeDTO[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const more = (after: string | null) =>
    adminFeatureFlagHistory(flagKey, { cursor: after, limit: 20 })
      .then((page) => {
        setItems((prev) => [...(after ? (prev ?? []) : []), ...page.items]);
        setCursor(page.nextCursor);
      })
      .catch((cause) => setError(v2ErrorMessage(cause)));
  useEffect(() => {
    void more(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flagKey]);
  if (error) return <ErrorText>{error}</ErrorText>;
  if (items === null) return <Loading />;
  if (items.length === 0) return <Empty>{t("admin.platform.historyEmpty")}</Empty>;
  return (
    <div className="space-y-1">
      {items.map((row) => (
        <p key={`${row.scope_type}-${row.scope_ref}-${row.version}-${row.changed_at}`} className="rounded-[8px] bg-muted/50 px-2 py-1 text-xs">
          {[
            formatAdminDate(row.changed_at),
            `${scopeLabel(row.scope_type)} ${row.scope_ref}`,
            `v${row.version}`,
            `${row.old_enabled === null || row.old_enabled === undefined ? t("admin.platform.new") : onOff(row.old_enabled)} → ${onOff(row.new_enabled)}`,
            row.actor ?? t("admin.money.system"),
            row.reason,
          ].join(" · ")}
          {row.approval_reference ? ` · ${t("admin.platform.approvalShort", { ref: row.approval_reference })}` : ""}
        </p>
      ))}
      {cursor && <Btn onClick={() => void more(cursor)}>{t("admin.money.more")}</Btn>}
    </div>
  );
}

type FlagDraft = { scope: FlagScopeType; ref: string; enabled: boolean; reason: string; approval: string };

function FlagsTab({ caps }: { caps: Caps }) {
  const t = useT();
  const flags = useLoad(() => adminFeatureFlags(), []);
  const corridors = useLoad(() => adminCorridors({ limit: 100 }).then((page) => page.items), []);
  const [corridorId, setCorridorId] = useState("");
  const [historyOf, setHistoryOf] = useState<FeatureFlagKey | null>(null);
  const [editing, setEditing] = useState<FeatureFlagKey | null>(null);
  const [draft, setDraft] = useState<FlagDraft>({ scope: "country", ref: COUNTRY_SCOPE_REF, enabled: false, reason: "", approval: "" });
  const action = useConfirmedCommand({
    confirmLabel: t("admin.money.iConfirm"),
    explain: (cause) => {
      if (cause instanceof ApiError && cause.code === "VERSION_CONFLICT") flags.reload();
      return flagRefusalMessage(cause);
    },
  });
  const ctx = { canManage: caps.has(PLATFORM_CAPABILITIES.flags), superAdmin: caps.superAdmin };
  const rows = flags.data ?? [];
  const corridor = (corridors.data ?? []).find((c) => c.id === corridorId) ?? null;
  const context = corridor ? { corridorRef: corridor.id, regionRefs: [corridor.origin_region.code, corridor.destination_region.code] } : {};
  const corridorName = (id: string) => (corridors.data ?? []).find((c) => c.id === id)?.name ?? id;

  function startEdit(key: FeatureFlagKey, row?: FlagValueDTO) {
    setEditing(key);
    const canEnable = mayOfferFlagValue(key, true, ctx);
    setDraft(
      row
        ? { scope: row.scope_type, ref: row.scope_ref, enabled: !row.enabled, reason: "", approval: row.approval_reference ?? "" }
        : { scope: "corridor", ref: corridorId, enabled: canEnable, reason: "", approval: "" },
    );
  }

  function submit(key: FeatureFlagKey) {
    const meta = FLAG_META[key];
    const existing = rows.find((r) => r.flag_key === key && r.scope_type === draft.scope && r.scope_ref === draft.ref.trim());
    const expected = existing ? existing.version : null;
    const lines = [
      `${flagLabel(key)} · ${scopeLabel(draft.scope)} «${draft.scope === "corridor" ? corridorName(draft.ref.trim()) : draft.ref.trim()}» · ${
        existing ? onOff(existing.enabled) : t("admin.platform.new")
      } → ${onOff(draft.enabled)}`,
      t("admin.finance.reasonLine", { reason: draft.reason.trim() }),
    ];
    if (draft.approval.trim()) lines.push(t("admin.platform.approvalLine", { ref: draft.approval.trim() }));
    if (draft.enabled && meta.q48Gated) lines.push(t("admin.platform.q48Refusal"));
    if (draft.enabled && meta.needsApprovalReference) lines.push(t("admin.platform.q5Line"));
    action.ask({
      title: t("admin.platform.confirmFlag"),
      lines,
      tone: draft.enabled ? "primary" : "danger",
      work: async (idempotencyKey) => {
        await adminSetFeatureFlag(
          key,
          draft.scope,
          draft.ref.trim(),
          { enabled: draft.enabled, reason: draft.reason.trim(), approval_reference: draft.approval.trim() || null, expected_version: expected },
          idempotencyKey,
        );
        setEditing(null);
        flags.reload();
      },
    });
  }

  const refProblem = scopeRefProblem(draft.scope, draft.ref);
  return (
    <div className="space-y-4">
      <Note>{t("admin.platform.flagsNote")}</Note>
      <div className="max-w-md">
        <Select
          label={t("admin.platform.effectiveCorridor")}
          value={corridorId}
          onChange={setCorridorId}
          options={[["", t("admin.platform.countryOnly")], ...(corridors.data ?? []).map((c): [string, string] => [c.id, `${c.name} (${rolloutLabel(c.rollout_state)})`])]}
        />
      </div>
      {flags.error && <ErrorText>{flags.error}</ErrorText>}
      {!flags.data && !flags.error && <Loading />}
      {flags.data && (
        <div className="grid gap-3 lg:grid-cols-2">
          {FLAG_KEYS.map((key) => {
            const meta = FLAG_META[key];
            const own = SCOPE_PRECEDENCE.flatMap((scope) => rows.filter((r) => r.flag_key === key && r.scope_type === scope));
            const country = resolveFlag(rows, key, {});
            const scoped = corridor ? resolveFlag(rows, key, context) : null;
            const badge = flagBadge(key, (scoped ?? country).enabled);
            const valueOptions: Array<["on" | "off", string]> = [
              ...(mayOfferFlagValue(key, true, ctx) ? [["on", t("admin.platform.onCap")] as ["on", string]] : []),
              ["off", t("admin.platform.offCap")],
            ];
            return (
              <Card
                key={key}
                label={flagLabel(key)}
                title={
                  <>
                    {flagLabel(key)} <span className="font-mono text-xs font-normal text-muted-foreground">({key})</span>
                  </>
                }
                badge={<Badge tone={badge.tone}>{badge.text}</Badge>}
              >
                {!meta.deprecated && (
                  <p className="text-xs text-secondary-foreground">
                    {t("admin.platform.countryValue", { value: onOff(country.enabled) })}
                    {scoped && corridor && ` · ${corridor.name}: ${onOff(scoped.enabled)} (${describeResolution(scoped)})`}
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  {flagHint(key)}
                  {!meta.deprecated && ` ${t("admin.platform.defaultIs", { value: onOff(meta.defaultValue) })}`}
                </p>
                {!meta.deprecated && own.length === 0 && <Empty>{t("admin.platform.noRows")}</Empty>}
                {own.map((row) => (
                  <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-border p-2 text-xs">
                    <span className="min-w-0 break-words">
                      {`${scopeLabel(row.scope_type)} «${row.scope_type === "corridor" ? corridorName(row.scope_ref) : row.scope_ref}» · ${onOff(row.enabled)} · v${row.version} · ${
                        row.updated_by ?? t("admin.money.system")
                      } · ${formatAdminDate(row.updated_at)}`}
                      {row.approval_reference ? ` · ${t("admin.platform.approvalShort", { ref: row.approval_reference })}` : ""}
                    </span>
                    {mayOfferFlagValue(key, !row.enabled, ctx) && (
                      <Btn tone={row.enabled ? "danger" : "neutral"} disabled={action.busy} onClick={() => startEdit(key, row)}>
                        {row.enabled ? t("admin.platform.turnOff") : t("admin.platform.turnOn")}
                      </Btn>
                    )}
                  </div>
                ))}
                {meta.superAdminToEnable && ctx.canManage && !ctx.superAdmin && <p className="text-xs text-muted-foreground">{t("admin.platform.enableSuperOnly")}</p>}
                <div className="flex flex-wrap gap-2">
                  {mayOfferFlagValue(key, false, ctx) && (
                    <Btn disabled={action.busy} onClick={() => startEdit(key)}>
                      {t("admin.platform.addScope")}
                    </Btn>
                  )}
                  <Btn onClick={() => setHistoryOf(historyOf === key ? null : key)}>{historyOf === key ? t("admin.platform.closeHistory") : t("admin.platform.history")}</Btn>
                </div>
                {historyOf === key && <FlagHistory flagKey={key} />}
                {editing === key && (
                  <div className="grid gap-2 rounded-[12px] border border-dashed border-border p-3 md:grid-cols-2">
                    <Select
                      label={t("admin.platform.scopeType")}
                      value={draft.scope}
                      onChange={(v) => setDraft({ ...draft, scope: v, ref: v === "country" ? COUNTRY_SCOPE_REF : "" })}
                      options={SCOPE_PRECEDENCE.map((s): [FlagScopeType, string] => [s, scopeLabel(s)])}
                    />
                    {draft.scope === "corridor" ? (
                      <Select
                        label={t("admin.platform.corridor")}
                        value={draft.ref}
                        onChange={(v) => setDraft({ ...draft, ref: v })}
                        options={[["", t("admin.money.choose")], ...(corridors.data ?? []).map((c): [string, string] => [c.id, c.name])]}
                      />
                    ) : (
                      <Field label={t("admin.platform.scopeRef")} value={draft.ref} onChange={(v) => setDraft({ ...draft, ref: v })} hint={draft.ref ? (refProblem ?? undefined) : undefined} />
                    )}
                    <Select
                      label={t("admin.platform.newValue")}
                      value={draft.enabled && valueOptions.some(([v]) => v === "on") ? "on" : "off"}
                      onChange={(v) => setDraft({ ...draft, enabled: v === "on" })}
                      options={valueOptions}
                    />
                    <Field label={t("admin.money.reasonAudit")} value={draft.reason} onChange={(v) => setDraft({ ...draft, reason: v })} />
                    {meta.needsApprovalReference && (
                      <Field label={t("admin.platform.approvalDoc")} value={draft.approval} onChange={(v) => setDraft({ ...draft, approval: v })} hint={t("admin.platform.approvalHint")} />
                    )}
                    <div className="flex items-end gap-2 md:col-span-2">
                      <Btn tone="primary" disabled={action.busy || !draft.reason.trim() || Boolean(refProblem)} onClick={() => submit(key)}>
                        {t("admin.platform.continue")}
                      </Btn>
                      <Btn onClick={() => setEditing(null)}>{t("common.close")}</Btn>
                    </div>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
      {action.view}
    </div>
  );
}

// --- corridors -----------------------------------------------------------------------------------------------------

function Q47Banner({ rows, error }: { rows: Q47ViolationDTO[] | null; error: string | null }) {
  const t = useT();
  if (error) return <ErrorText>{t("admin.platform.q47Check", { error })}</ErrorText>;
  if (rows === null) return <Loading />;
  if (rows.length === 0) return <Note tone="success">{t("admin.platform.q47Ok")}</Note>;
  return (
    <div role="alert" className="space-y-1 rounded-[12px] border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      <p className="font-semibold">{t("admin.platform.q47BrokenCount", { count: rows.length })}</p>
      {rows.map((row) => (
        <p key={row.corridor_id}>
          {t("admin.platform.q47Row", {
            name: row.name,
            state: rolloutLabel(row.rollout_state),
            reasons: row.reasons.map(corridorReasonLabel).join("; "),
          })}
        </p>
      ))}
    </div>
  );
}

function CorridorDetail({ corridor, caps, onChanged }: { corridor: CorridorAdminDTO; caps: Caps; onChanged: (c: CorridorAdminDTO) => void }) {
  const t = useT();
  const [name, setName] = useState(corridor.name);
  const [radius, setRadius] = useState(String(corridor.config.search_radius_m));
  const [detourMin, setDetourMin] = useState(String(corridor.config.default_max_detour_minutes));
  const [detourM, setDetourM] = useState(String(corridor.config.default_max_detour_m));
  const [target, setTarget] = useState<"" | CorridorRolloutState>("");
  const [reason, setReason] = useState("");
  const patch = useConfirmedCommand({ explain: corridorRefusalMessage, confirmLabel: t("admin.money.iConfirm") });
  const canManage = caps.has(PLATFORM_CAPABILITIES.corridors);

  function savePatch() {
    const body: CorridorPatch = { expected_version: corridor.version, reason: reason.trim() };
    const lines: string[] = [];
    if (name.trim() && name.trim() !== corridor.name) {
      body.name = name.trim();
      lines.push(t("admin.platform.nameLine", { name: body.name }));
    }
    const r = toInt(radius);
    if (r !== null && r !== corridor.config.search_radius_m) {
      body.search_radius_m = r;
      lines.push(t("admin.platform.radiusLine", { value: r }));
    }
    const dm = toInt(detourMin);
    if (dm !== null && dm !== corridor.config.default_max_detour_minutes) {
      body.default_max_detour_minutes = dm;
      lines.push(t("admin.platform.detourMinLine", { value: dm }));
    }
    const dd = toInt(detourM);
    if (dd !== null && dd !== corridor.config.default_max_detour_m) {
      body.default_max_detour_m = dd;
      lines.push(t("admin.platform.detourMLine", { value: dd }));
    }
    if (target) {
      body.rollout_state = target;
      lines.push(t("admin.platform.stateLine", { from: rolloutLabel(corridor.rollout_state), to: rolloutLabel(target) }));
      if (target === "pilot" || target === "active") lines.push(t("admin.platform.q47ServerCheck"));
    }
    if (lines.length === 0) return;
    lines.push(t("admin.finance.reasonLine", { reason: reason.trim() }));
    patch.ask({
      title: t("admin.platform.confirmCorridor", { name: corridor.name }),
      lines,
      tone: target === "closed" ? "danger" : "primary",
      work: async (key) => {
        onChanged(await adminPatchCorridor(corridor.id, body, key));
        setTarget("");
        setReason("");
      },
    });
  }

  return (
    <div className="space-y-4 rounded-[14px] border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-bold text-foreground">{corridor.name}</h3>
          <p className="text-sm text-muted-foreground">
            {corridor.origin_region.name_uz} → {corridor.destination_region.name_uz} ·{" "}
            {t("admin.platform.corridorRow", { state: rolloutLabel(corridor.rollout_state), version: corridor.version })}
          </p>
        </div>
        <Badge tone={rolloutTone(corridor.rollout_state)}>{rolloutLabel(corridor.rollout_state)}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("admin.platform.corridorInfo", {
          services: corridor.enabled_services.length ? corridor.enabled_services.join(", ") : t("admin.platform.noServices"),
          revision: corridor.config.revision,
          time: formatAdminDate(corridor.updated_at),
        })}
      </p>

      {canManage && (
        <Section title={t("admin.platform.settingsAndState")}>
          <div className="grid gap-2 md:grid-cols-3">
            <Field label={t("admin.platform.name")} value={name} onChange={setName} />
            <Field label={t("admin.platform.radius")} value={radius} onChange={setRadius} hint="100–50 000" />
            <Field label={t("admin.platform.detourMin")} value={detourMin} onChange={setDetourMin} />
            <Field label={t("admin.platform.detourM")} value={detourM} onChange={setDetourM} />
            <Select
              label={t("admin.platform.newState")}
              value={target}
              onChange={(v) => setTarget(v as "" | CorridorRolloutState)}
              options={[["", t("admin.platform.unchanged")], ...ROLLOUT_NEXT(corridor.rollout_state).map((s): [string, string] => [s, rolloutLabel(s)])]}
            />
            <Field label={t("admin.money.reasonAudit")} value={reason} onChange={setReason} />
          </div>
          <Btn tone="primary" disabled={patch.busy || !reason.trim()} onClick={savePatch}>
            {t("admin.platform.saveCorridor")}
          </Btn>
          <p className="text-xs text-muted-foreground">{t("admin.platform.noRouter")}</p>
          {patch.view}
        </Section>
      )}

    </div>
  );
}

/** CORRIDOR_ROLLOUT    </div>
  );
}

/** CORRIDOR_ROLLOUT transitions (state_machines.py). */
function ROLLOUT_NEXT(state: CorridorRolloutState): CorridorRolloutState[] {
  const map: Record<CorridorRolloutState, CorridorRolloutState[]> = {
    draft: ["internal", "closed"],
    internal: ["draft", "pilot", "closed"],
    pilot: ["internal", "active", "closed"],
    active: ["pilot", "closed"],
    closed: [],
  };
  return map[state];
}

function CorridorsTab({ caps }: { caps: Caps }) {
  const t = useT();
  const [items, setItems] = useState<CorridorAdminDTO[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const q47 = useLoad(() => adminQ47Violations(), []);
  const regions = useLoad<RegionDTO[]>(() => adminRegions(), []);
  const [form, setForm] = useState({ name: "", origin: "", destination: "", radius: "3000", detourMin: "15", detourM: "5000" });
  const action = useConfirmedCommand({ explain: corridorRefusalMessage, confirmLabel: t("admin.money.iConfirm") });

  const load = (after: string | null) =>
    adminCorridors({ cursor: after, limit: 50 })
      .then((page) => {
        setItems((prev) => [...(after ? (prev ?? []) : []), ...page.items]);
        setCursor(page.nextCursor);
      })
      .catch((cause) => setError(v2ErrorMessage(cause)));
  useEffect(() => {
    void load(null);
  }, []);

  const current = (items ?? []).find((c) => c.id === selected) ?? null;
  const regionName = (id: string) => (regions.data ?? []).find((r) => r.id === id)?.name_uz ?? id;
  const nums = { radius: toInt(form.radius), detourMin: toInt(form.detourMin), detourM: toInt(form.detourM) };
  const formOk =
    form.name.trim() && form.origin && form.destination && form.origin !== form.destination && nums.radius !== null && nums.radius >= 100 && nums.detourMin !== null && nums.detourM !== null;

  function create() {
    action.ask({
      title: t("admin.platform.confirmNewCorridor"),
      lines: [
        `${form.name.trim()}: ${regionName(form.origin)} → ${regionName(form.destination)}`,
        t("admin.platform.newCorridorNums", { radius: String(nums.radius), min: String(nums.detourMin), m: String(nums.detourM) }),
        t("admin.platform.draftHidden"),
      ],
      work: async (key) => {
        const created = await adminCreateCorridor(
          {
            name: form.name.trim(),
            origin_region_id: form.origin,
            destination_region_id: form.destination,
            search_radius_m: nums.radius as number,
            default_max_detour_minutes: nums.detourMin as number,
            default_max_detour_m: nums.detourM as number,
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
      {items !== null && items.length === 0 && <Empty>{t("admin.platform.noCorridors")}</Empty>}
      {items !== null && items.length > 0 && (
        <div className="divide-y divide-border overflow-hidden rounded-[12px] border border-border bg-card">
          {items.map((c) => {
            const broken = (q47.data ?? []).some((v) => v.corridor_id === c.id);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelected(c.id)}
                aria-pressed={selected === c.id}
                className={`el-press flex w-full items-center justify-between gap-2 p-3 text-left text-sm ${selected === c.id ? "bg-accent" : ""}`}
              >
                <span className="min-w-0">
                  <span className="block font-semibold text-foreground">{c.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {t("admin.platform.corridorRow", { state: rolloutLabel(c.rollout_state), version: c.version })}
                    {broken && <span className="text-destructive"> · {t("admin.platform.q47Broken")}</span>}
                  </span>
                </span>
                <Badge tone={broken ? "err" : rolloutTone(c.rollout_state)}>{rolloutLabel(c.rollout_state)}</Badge>
              </button>
            );
          })}
        </div>
      )}
      {cursor && <Btn onClick={() => void load(cursor)}>{t("admin.money.more")}</Btn>}
      {current && (
        <CorridorDetail
          key={`${current.id}-${current.version}`}
          corridor={current}
          caps={caps}
          onChanged={(next) => {
            setItems((prev) => (prev ?? []).map((c) => (c.id === next.id ? next : c)));
            q47.reload();
          }}
        />
      )}
      {caps.has(PLATFORM_CAPABILITIES.corridors) && (
        <Section title={t("admin.platform.newCorridor")}>
          <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
            <div className="grid gap-2 md:grid-cols-3">
              <Field label={t("admin.platform.corridorName")} value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
              <Select label={t("admin.platform.fromRegion")} value={form.origin} onChange={(v) => setForm({ ...form, origin: v })} options={[["", t("admin.money.choose")], ...(regions.data ?? []).map((r): [string, string] => [r.id, r.name_uz])]} />
              <Select label={t("admin.platform.toRegion")} value={form.destination} onChange={(v) => setForm({ ...form, destination: v })} options={[["", t("admin.money.choose")], ...(regions.data ?? []).map((r): [string, string] => [r.id, r.name_uz])]} />
              <Field label={t("admin.platform.radius")} value={form.radius} onChange={(v) => setForm({ ...form, radius: v })} />
              <Field label={t("admin.platform.detourMin")} value={form.detourMin} onChange={(v) => setForm({ ...form, detourMin: v })} />
              <Field label={t("admin.platform.detourM")} value={form.detourM} onChange={(v) => setForm({ ...form, detourM: v })} />
            </div>
            <Btn tone="primary" disabled={action.busy || !formOk} onClick={create}>
              {t("admin.platform.createCorridor")}
            </Btn>
            {action.view}
          </div>
        </Section>
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
  const t = useT();
  const versions = useLoad<ParcelPolicyVersionDTO[]>(() => adminParcelPolicies(), []);
  const active = useLoad<ParcelPolicyDTO>(() => activeParcelPolicy(), []);
  const [label, setLabel] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [items, setItems] = useState<ParcelPolicyItemCreate[]>([]);
  const [item, setItem] = useState<ParcelPolicyItemCreate>(EMPTY_ITEM);
  const action = useConfirmedCommand({ explain: policyRefusalMessage, confirmLabel: t("admin.money.iConfirm") });
  const canManage = caps.has(PLATFORM_CAPABILITIES.policy);
  const itemProblem = policyItemProblem(item);

  function confirmVersion(v: ParcelPolicyVersionDTO) {
    action.ask({
      title: t("admin.platform.confirmPolicy", { label: v.label }),
      lines: [
        t("admin.platform.policyMeta", { count: v.item_count, author: v.created_by ?? t("admin.money.unknown"), approver: t("admin.money.notYet") }),
        t("admin.platform.policyReplaces"),
        t("admin.platform.authorCannot"),
      ],
      work: async (key) => {
        await adminConfirmParcelPolicy(v.id, v.version, key);
        versions.reload();
        active.reload();
      },
    });
  }

  function createDraft() {
    action.ask({
      title: t("admin.platform.confirmPolicyDraft"),
      lines: [t("admin.platform.draftItems", { label: label.trim(), count: items.length }), t("admin.platform.draftWaits")],
      work: async (key) => {
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
      {versions.data && <Note tone={versions.data.some((v) => v.status === "active") ? "info" : "warning"}>{policySummary(versions.data)}</Note>}
      {versions.data && versions.data.length === 0 && <Empty>{t("admin.platform.noVersions")}</Empty>}
      {versions.data && versions.data.length > 0 && (
        <div className="divide-y divide-border overflow-hidden rounded-[12px] border border-border bg-card">
          {versions.data.map((v) => (
            <div key={v.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <div className="min-w-0">
                <p className="font-semibold">
                  {v.label} · {policyStatusLabel(v.status)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("admin.platform.policyMeta", {
                    count: v.item_count,
                    author: v.created_by ?? t("admin.money.unknown"),
                    approver: v.confirmed_by ? `${v.confirmed_by} (${formatAdminDate(v.confirmed_at)})` : t("admin.money.notYet"),
                  })}
                  {v.effective_from ? ` · ${t("admin.platform.effectiveFrom", { time: formatAdminDate(v.effective_from) })}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={v.status === "active" ? "ok" : "gray"}>{v.status === "active" ? t("admin.platform.inForce") : v.status === "draft" ? t("status.draft") : t("admin.platform.superseded")}</Badge>
                {v.status === "draft" && canManage && (
                  <Btn tone="primary" disabled={action.busy} onClick={() => confirmVersion(v)}>
                    {t("admin.platform.approve")}
                  </Btn>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {canManage && <p className="text-xs text-muted-foreground">{t("admin.platform.authorCannot")}</p>}

      <Section title={t("admin.platform.senderList")}>
        {active.error && <ErrorText>{active.error}</ErrorText>}
        {active.data && <p className="text-xs text-muted-foreground">{active.data.notice}</p>}
        {active.data && !active.data.approved && <Empty>{t("admin.platform.noApprovedList")}</Empty>}
        {(active.data?.items ?? []).map((i) => (
          <p key={i.code} className="rounded-[8px] bg-muted/50 px-2 py-1 text-sm">
            <b>{i.title}</b> · {policyCategoryLabel(i.category)} · {i.description}
            {i.legal_basis ? ` · ${t("admin.platform.basisShort", { value: i.legal_basis })}` : ""}
            {i.source_ref ? ` · ${t("admin.platform.sourceShort", { value: i.source_ref })}` : ""}
          </p>
        ))}
      </Section>

      {canManage && (
        <Section title={t("admin.platform.newVersion")}>
          <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
            <div className="grid gap-2 md:grid-cols-2">
              <Field label={t("admin.platform.versionName")} value={label} onChange={setLabel} placeholder="2026-09" />
              <Field label={t("admin.platform.sourceNote")} value={sourceNote} onChange={setSourceNote} />
            </div>
            {items.map((i, index) => (
              <div key={`${i.code}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] bg-muted/50 px-2 py-1 text-sm">
                <span>
                  {i.code} · {policyCategoryLabel(i.category)} · {i.title_uz}
                </span>
                <Btn tone="danger" onClick={() => setItems(items.filter((_, j) => j !== index))}>
                  {t("admin.platform.remove")}
                </Btn>
              </div>
            ))}
            <div className="grid gap-2 md:grid-cols-3">
              <Field label={t("admin.platform.itemCode")} value={item.code} onChange={(v) => setItem({ ...item, code: v })} />
              <Select
                label={t("admin.platform.category")}
                value={item.category}
                onChange={(v) => setItem({ ...item, category: v as ParcelPolicyItemCreate["category"] })}
                options={POLICY_CATEGORIES.map((c): [string, string] => [c, policyCategoryLabel(c)])}
              />
              <Select
                label={t("admin.platform.appliesTo")}
                value={item.applies_to}
                onChange={(v) => setItem({ ...item, applies_to: v as ParcelPolicyItemCreate["applies_to"] })}
                options={[
                  ["parcel", t("admin.money.parcelCap")],
                  ["passenger_baggage", t("admin.platform.baggage")],
                  ["all", t("admin.money.all")],
                ]}
              />
              <Field label={t("admin.platform.itemName")} value={item.title_uz} onChange={(v) => setItem({ ...item, title_uz: v })} />
              <Field label={t("admin.platform.itemDescription")} value={item.description_uz} onChange={(v) => setItem({ ...item, description_uz: v })} />
              <Field label={t("admin.platform.legalBasis")} value={item.legal_basis ?? ""} onChange={(v) => setItem({ ...item, legal_basis: v })} />
              <Field label={t("admin.platform.source")} value={item.source_ref ?? ""} onChange={(v) => setItem({ ...item, source_ref: v })} />
              <Field label={t("admin.platform.sourceChecked")} value={item.source_checked_on ?? ""} onChange={(v) => setItem({ ...item, source_checked_on: v })} placeholder="2026-09-24" />
            </div>
            <p className={`text-xs ${item.code && itemProblem ? "text-destructive" : "text-muted-foreground"}`}>
              {item.code && itemProblem ? itemProblem : t("admin.platform.prohibitedNeedsBasis")}
            </p>
            <div className="flex flex-wrap gap-2">
              <Btn
                disabled={Boolean(itemProblem)}
                onClick={() => {
                  setItems([...items, item]);
                  setItem(EMPTY_ITEM);
                }}
              >
                {t("admin.platform.addItem")}
              </Btn>
              <Btn tone="primary" disabled={action.busy || label.trim().length < 2 || items.length === 0} onClick={createDraft}>
                {t("admin.platform.saveDraft")}
              </Btn>
            </div>
          </div>
        </Section>
      )}
      {action.view}
    </div>
  );
}

// --- parcel size categories (Q140, ADR-0026) -------------------------------------------------------------------------

type CategoryForm = { code: string; name_uz: string; name_ru: string; icon_key: string; length: string; width: string; height: string; weightKg: string };
const EMPTY_CATEGORY: CategoryForm = { code: "", name_uz: "", name_ru: "", icon_key: "box_small", length: "", width: "", height: "", weightKg: "" };
const CATEGORY_ICONS = ["envelope", "box_small", "box_medium", "box_large", "bag"] as const;

function iconLabel(icon: string): string {
  return (CATEGORY_ICONS as readonly string[]).includes(icon) ? translate(`admin.platform.icon.${icon as (typeof CATEGORY_ICONS)[number]}`) : icon;
}

function kg(grams: number): string {
  return String(grams / 1000).replace(".", ",");
}

/** The typed row as the API item, or the reason it cannot be one. Volume is the box volume (1 cm³ = 1 ml). */
export function categoryItemFromForm(form: CategoryForm): ParcelCategoryItemInput | string {
  const [l, w, h] = [form.length, form.width, form.height].map((v) => Number(v));
  const grams = Math.round(Number(form.weightKg.replace(",", ".")) * 1000);
  if (!/^[a-z][a-z0-9_]{1,39}$/.test(form.code.trim())) return translate("admin.platform.catErr.code");
  if (form.name_uz.trim().length < 2) return translate("admin.platform.catErr.name");
  if (![l, w, h].every((v) => Number.isInteger(v) && v > 0)) return translate("admin.platform.catErr.size");
  if (!Number.isFinite(grams) || grams <= 0) return translate("admin.platform.catErr.weight");
  return {
    code: form.code.trim(), name_uz: form.name_uz.trim(), name_ru: form.name_ru.trim() || null, icon_key: form.icon_key,
    max_length_cm: l, max_width_cm: w, max_height_cm: h, max_volume_ml: l * w * h, max_weight_g: grams,
  };
}

function CategoryTable({ items }: { items: ParcelCategoryVersionDTO["items"] }) {
  const t = useT();
  if (!items || items.length === 0) return <Empty>{t("admin.platform.noCategories")}</Empty>;
  return (
    <div className="overflow-x-auto rounded-[10px] border border-border">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2">{t("admin.platform.code")}</th>
            <th className="px-3 py-2">{t("admin.platform.name")}</th>
            <th className="px-3 py-2">{t("admin.platform.label")}</th>
            <th className="px-3 py-2">{t("admin.platform.size")}</th>
            <th className="px-3 py-2">{t("admin.platform.weight")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.id} className="border-t border-border">
              <td className="px-3 py-2 font-mono text-xs">{i.code}</td>
              <td className="px-3 py-2">{i.name_uz}</td>
              <td className="px-3 py-2">{iconLabel(i.icon_key)}</td>
              <td className="px-3 py-2">{t("admin.platform.sizeValue", { l: i.max_length_cm, w: i.max_width_cm, h: i.max_height_cm })}</td>
              <td className="px-3 py-2">{t("admin.platform.weightValue", { kg: kg(i.max_weight_g) })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoriesTab({ caps }: { caps: Caps }) {
  const t = useT();
  const versions = useLoad<ParcelCategoryVersionDTO[]>(() => adminParcelCategoryVersions(), []);
  const [label, setLabel] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [synthetic, setSynthetic] = useState(true);
  const [items, setItems] = useState<ParcelCategoryItemInput[]>([]);
  const [form, setForm] = useState<CategoryForm>(EMPTY_CATEGORY);
  const action = useConfirmedCommand({ explain: policyRefusalMessage, confirmLabel: t("admin.money.iConfirm") });
  const canManage = caps.has(PLATFORM_CAPABILITIES.policy);
  const candidate = categoryItemFromForm(form);
  const active = (versions.data ?? []).find((v) => v.status === "active");

  function confirmVersion(v: ParcelCategoryVersionDTO) {
    action.ask({
      title: t("admin.platform.confirmCatalog", { label: v.label }),
      lines: [
        t("admin.platform.catalogMeta", { count: (v.items ?? []).length, author: v.created_by ?? t("admin.money.unknown") }),
        v.synthetic ? t("admin.platform.syntheticRefused") : t("admin.platform.catalogShown"),
        t("admin.platform.catalogKept"),
      ],
      work: async (key) => {
        await adminConfirmParcelCategoryVersion(v.id, v.version, key);
        versions.reload();
      },
    });
  }

  function createDraft() {
    action.ask({
      title: t("admin.platform.confirmCatalogDraft"),
      lines: [t("admin.platform.catalogDraftLine", { label: label.trim(), count: items.length, synthetic: synthetic ? t("admin.platform.syntheticTag") : "" }), t("admin.platform.catalogDraftWaits")],
      work: async (key) => {
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
        <Note tone={active && !active.synthetic ? "info" : "warning"}>
          {!active
            ? t("admin.platform.noCatalog")
            : active.synthetic
              ? t("admin.platform.syntheticInForce", { name: active.label })
              : t("admin.platform.catalogInForce", { name: active.label, version: active.version })}
        </Note>
      )}
      {active && <CategoryTable items={active.items} />}
      {versions.data && versions.data.length === 0 && <Empty>{t("admin.platform.noCatalogVersions")}</Empty>}
      {(versions.data ?? [])
        .filter((v) => v.status !== "active")
        .map((v) => (
          <Card
            key={v.id}
            title={`${v.label}${v.synthetic ? ` · ${t("admin.platform.syntheticTag")}` : ""}`}
            badge={<Badge tone="gray">{v.status === "draft" ? t("status.draft") : t("admin.platform.superseded")}</Badge>}
          >
            <p className="text-xs text-muted-foreground">
              {t("admin.platform.policyMeta", {
                count: (v.items ?? []).length,
                author: v.created_by ?? t("admin.money.unknown"),
                approver: v.confirmed_by ? `${v.confirmed_by} (${formatAdminDate(v.confirmed_at)})` : t("admin.money.notYet"),
              })}
            </p>
            <CategoryTable items={v.items} />
            {v.status === "draft" && canManage && (
              <Btn tone="primary" disabled={action.busy} onClick={() => confirmVersion(v)}>
                {t("admin.platform.approve")}
              </Btn>
            )}
          </Card>
        ))}

      {canManage && (
        <Section title={t("admin.platform.newCatalog")} sub={t("admin.platform.catalogHint")}>
          <div className="space-y-2 rounded-[14px] border border-dashed border-border p-4">
            <div className="grid gap-2 md:grid-cols-2">
              <Field label={t("admin.platform.versionName")} value={label} onChange={setLabel} placeholder="2026-09" />
              <Field label={t("admin.platform.sourceNote")} value={sourceNote} onChange={setSourceNote} />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={synthetic} onChange={(event) => setSynthetic(event.target.checked)} />
              {t("admin.platform.synthetic")}
            </label>
            {items.map((i, index) => (
              <div key={`${i.code}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] bg-muted/50 px-2 py-1 text-sm">
                <span>
                  {i.code} · {i.name_uz} · {t("admin.platform.sizeValue", { l: i.max_length_cm, w: i.max_width_cm, h: i.max_height_cm })} ·{" "}
                  {t("admin.platform.weightValue", { kg: kg(i.max_weight_g) })}
                </span>
                <Btn tone="danger" onClick={() => setItems(items.filter((_, j) => j !== index))}>
                  {t("admin.platform.remove")}
                </Btn>
              </div>
            ))}
            <div className="grid gap-2 md:grid-cols-4">
              <Field label={t("admin.platform.code")} value={form.code} onChange={(v) => setForm({ ...form, code: v })} placeholder="small_box" />
              <Field label={t("admin.platform.nameUz")} value={form.name_uz} onChange={(v) => setForm({ ...form, name_uz: v })} />
              <Field label={t("admin.platform.nameRu")} value={form.name_ru} onChange={(v) => setForm({ ...form, name_ru: v })} />
              <Select label={t("admin.platform.label")} value={form.icon_key} onChange={(v) => setForm({ ...form, icon_key: v })} options={CATEGORY_ICONS.map((i): [string, string] => [i, iconLabel(i)])} />
              <Field label={t("admin.platform.length")} value={form.length} onChange={(v) => setForm({ ...form, length: v })} />
              <Field label={t("admin.platform.width")} value={form.width} onChange={(v) => setForm({ ...form, width: v })} />
              <Field label={t("admin.platform.height")} value={form.height} onChange={(v) => setForm({ ...form, height: v })} />
              <Field label={t("admin.platform.maxWeight")} value={form.weightKg} onChange={(v) => setForm({ ...form, weightKg: v })} />
            </div>
            {form.code && typeof candidate === "string" && <p className="text-xs text-destructive">{candidate}</p>}
            <div className="flex flex-wrap gap-2">
              <Btn
                disabled={typeof candidate === "string"}
                onClick={() => {
                  if (typeof candidate !== "string") {
                    setItems([...items, candidate]);
                    setForm(EMPTY_CATEGORY);
                  }
                }}
              >
                {t("admin.platform.addCategory")}
              </Btn>
              <Btn tone="primary" disabled={action.busy || label.trim().length < 2 || items.length === 0} onClick={createDraft}>
                {t("admin.platform.saveDraft")}
              </Btn>
            </div>
          </div>
        </Section>
      )}
      {action.view}
    </div>
  );
}

// --- outbox ---------------------------------------------------------------------------------------------------------

function OutboxTab({ caps }: { caps: Caps }) {
  const t = useT();
  const [state, setState] = useState<"failed" | "dead">("failed");
  const [items, setItems] = useState<OutboxEventAdminDTO[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const action = useConfirmedCommand({ confirmLabel: t("admin.money.iConfirm") });

  const load = (after: string | null) =>
    adminOutbox({ state, cursor: after, limit: 50 })
      .then((page) => {
        setItems((prev) => [...(after ? (prev ?? []) : []), ...page.items]);
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
      title: t("admin.platform.confirmResend"),
      lines: [`${event.event_type} · ${event.aggregate_type} ${event.aggregate_id} · ${t("admin.platform.attempts", { count: event.attempts })}`, t("admin.finance.reasonLine", { reason })],
      work: async (key) => {
        await adminRetryOutbox(event.id, reason, key);
        void load(null);
      },
    });
  }

  return (
    <div className="space-y-3">
      <Chips
        label={t("admin.money.status")}
        value={state}
        onChange={setState}
        options={[
          ["failed", t("admin.platform.outbox.failed")],
          ["dead", t("admin.platform.outbox.dead")],
        ]}
      />
      {error && <ErrorText>{error}</ErrorText>}
      {items === null && !error && <Loading />}
      {items !== null && items.length === 0 && <Empty>{t("admin.platform.noEvents")}</Empty>}
      {(items ?? []).map((event) => (
        <Card
          key={event.id}
          title={`${event.event_type} · ${event.aggregate_id} (v${event.aggregate_version})`}
          badge={event.dead_lettered_at ? <Badge tone="err">{t("admin.platform.outbox.deadBadge")}</Badge> : <Badge tone="warn">{t("admin.platform.outbox.failedBadge")}</Badge>}
        >
          <p className="text-xs text-muted-foreground">
            {event.dead_lettered_at
              ? t("admin.platform.outboxMeta", { time: formatAdminDate(event.occurred_at), count: event.attempts })
              : t("admin.platform.outboxMetaRetry", { time: formatAdminDate(event.occurred_at), count: event.attempts, next: formatAdminDate(event.next_attempt_at) })}
          </p>
          {event.last_error && <p className="break-words text-xs text-destructive">{t("admin.platform.lastError", { error: event.last_error })}</p>}
          <div className="flex flex-wrap gap-2">
            <Btn onClick={() => setOpen(open === event.id ? null : event.id)}>{open === event.id ? t("admin.platform.closePayload") : t("admin.platform.payload")}</Btn>
          </div>
          {open === event.id && <pre className="overflow-x-auto rounded-[10px] bg-muted p-2 text-xs">{JSON.stringify(event.payload, null, 2)}</pre>}
          {caps.has(PLATFORM_CAPABILITIES.outbox) && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[220px] flex-1">
                <Field label={t("admin.platform.resendReason")} value={reasons[event.id] ?? ""} onChange={(v) => setReasons({ ...reasons, [event.id]: v })} hint={t("admin.platform.min3")} />
              </div>
              <Btn tone="primary" disabled={action.busy || (reasons[event.id] ?? "").trim().length < 3} onClick={() => retry(event)}>
                {t("admin.platform.resend")}
              </Btn>
            </div>
          )}
        </Card>
      ))}
      {cursor && <Btn onClick={() => void load(cursor)}>{t("admin.money.more")}</Btn>}
      {action.view}
    </div>
  );
}

// --- system state ---------------------------------------------------------------------------------------------------

function legacyFlagLabel(flag: string): string {
  if (flag === "unknown_time") return translate("admin.platform.legacyFlag.unknown_time");
  if (flag === "unknown_dimensions") return translate("admin.platform.legacyFlag.unknown_dimensions");
  return flag;
}

/** O8: one v1 order, read-only (Q4). Nothing here can change it; the database refuses writes to the projection. */
export function AdminLegacyOrderDetail({ legacyOrderNumber, onClose }: { legacyOrderNumber: string; onClose?: () => void }) {
  const t = useT();
  const order = useLoad<LegacyOrderViewDTO>(() => adminLegacyOrder(legacyOrderNumber), [legacyOrderNumber]);
  return (
    <div className="space-y-2 rounded-[14px] border border-border bg-card p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold">{t("admin.platform.legacyTitle", { number: legacyOrderNumber })}</p>
        {onClose && <Btn onClick={onClose}>{t("common.close")}</Btn>}
      </div>
      {order.error && <ErrorText>{order.error}</ErrorText>}
      {!order.data && !order.error && <Loading />}
      {order.data && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 md:grid-cols-4">
          <dt className="text-muted-foreground">{t("admin.money.status")}</dt>
          <dd>{order.data.status}</dd>
          <dt className="text-muted-foreground">{t("admin.finance.direction")}</dt>
          <dd className="break-words">{order.data.route_summary}</dd>
          <dt className="text-muted-foreground">{t("admin.platform.finalPrice")}</dt>
          <dd>{order.data.final_price_minor === null || order.data.final_price_minor === undefined ? t("admin.promo.unset") : formatUzs(order.data.final_price_minor / 100)}</dd>
          <dt className="text-muted-foreground">{t("admin.platform.legacyFee")}</dt>
          <dd>
            {order.data.legacy_calculated_fee_minor === null || order.data.legacy_calculated_fee_minor === undefined
              ? t("common.none")
              : t("admin.platform.legacyFeeValue", { amount: formatUzs(order.data.legacy_calculated_fee_minor / 100) })}
          </dd>
          <dt className="text-muted-foreground">{t("admin.platform.created")}</dt>
          <dd>{formatAdminDate(order.data.created_at)}</dd>
          <dt className="text-muted-foreground">{t("admin.platform.updated")}</dt>
          <dd>{formatAdminDate(order.data.updated_at)}</dd>
          <dt className="text-muted-foreground">{t("admin.platform.marks")}</dt>
          <dd>{(order.data.flags ?? []).length ? (order.data.flags ?? []).map(legacyFlagLabel).join(", ") : "-"}</dd>
        </dl>
      )}
      <p className="text-xs text-muted-foreground">{t("admin.platform.readOnlyQ4")}</p>
    </div>
  );
}

function SystemTab() {
  const t = useT();
  const [day, setDay] = useState("");
  const quota = useLoad<ProviderQuotaDTO[]>(() => adminProviderQuota(day || undefined), [day]);
  const [lookup, setLookup] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  return (
    <div className="space-y-5">
      <Section title={t("admin.platform.quotaTitle")}>
        <div className="max-w-xs">
          <Field label={t("admin.platform.day")} value={day} onChange={setDay} />
        </div>
        {quota.error && <ErrorText>{quota.error}</ErrorText>}
        {!quota.data && !quota.error && <Loading />}
        {quota.data && quota.data.length === 0 && <Note>{t("admin.platform.noPaidCalls")}</Note>}
        {(quota.data ?? []).map((q) => (
          <p
            key={`${q.provider}-${q.day}`}
            className={`rounded-[8px] px-2 py-1 text-sm ${q.state === "ok" ? "bg-muted/50" : q.state === "warn" ? "bg-warning/10 text-warning" : "bg-destructive/10 text-destructive"}`}
          >
            {t("admin.platform.quotaRow", {
              provider: q.provider,
              day: q.day,
              calls: q.calls,
              credits: q.credits,
              limit: q.limit,
              percent: Math.round(q.ratio * 100),
              state: quotaStateLabel(q.state),
              failures: q.failures,
            })}
            {q.estimated ? ` · ${t("admin.platform.estimated")}` : ""}
          </p>
        ))}
      </Section>
      <Section title={t("admin.platform.v1Lookup")}>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-60">
            <Field label={t("admin.platform.orderNumber")} value={lookup} onChange={setLookup} />
          </div>
          <Btn disabled={!lookup.trim()} onClick={() => setShown(lookup.trim())}>
            {t("admin.platform.view")}
          </Btn>
        </div>
        {shown && <AdminLegacyOrderDetail legacyOrderNumber={shown} onClose={() => setShown(null)} />}
      </Section>
    </div>
  );
}

// --- panel ----------------------------------------------------------------------------------------------------------

export type AdminPlatformPanelProps = {
  /** Initial sub-tab (default: flags). */
  initialTab?: Tab;
};

export function AdminPlatformPanel({ initialTab = "flags" }: AdminPlatformPanelProps = {}) {
  const t = useT();
  const [tab, setTab] = useState<Tab>(initialTab);
  const [caps, setCaps] = useState<{ list: string[]; roles: string[] } | null>(null);
  useEffect(() => {
    capabilities()
      .then((dto) => setCaps({ list: dto.capabilities as string[], roles: (dto.roles ?? []) as string[] }))
      .catch(() => setCaps({ list: [], roles: [] }));
  }, []);
  const has = useMemo<Caps>(
    () => ({ has: (capability: string) => (caps?.list ?? []).includes(capability), superAdmin: (caps?.roles ?? []).includes("super_admin") }),
    [caps],
  );
  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-lg font-bold text-foreground">{t("admin.platform.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("admin.platform.subtitle")}</p>
      </header>
      <Tabs value={tab} onChange={setTab} options={TABS.map((id): [Tab, string] => [id, t(`admin.platform.tab.${id}`)])} />
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
    </section>
  );
}
