/**
 * Pure rules behind the staff platform panel (`AdminPlatformPanel.tsx`). No I/O, no React.
 *
 * Flag resolution mirrors `app/modules/geo/flags.py` (ADR-0008): cohort > corridor > region > country, no row ->
 * production default, conflicting rows on one level -> the safe default (Q26). The server stays the authority: this
 * copy only explains to an operator which row wins where; it never decides whether a change is allowed.
 */
import type { CorridorRolloutState, FeatureFlagKey, FlagScopeType, FlagValueDTO } from "../api/v2/admin-platform.api";
import { translate } from "../i18n";
import { ApiError } from "../types/api";

export type FlagMeta = {
  /** Value when no row matches (every environment; flags.py PRODUCTION_FLAG_DEFAULTS). */
  defaultValue: boolean;
  /** Production can only hold this value (Q1: wallet_required). */
  lockedInProduction: boolean | null;
  /** Production enable needs super_admin + approval reference (Q5, K7). */
  needsApprovalReference: boolean;
  /** v2 service flag behind the Q48 launch gate (Q56). */
  q48Gated: boolean;
  /**
   * Turning it ON is super_admin-only (Q5 passenger, card payments): the "Yoqish…" control is hidden from other
   * roles (DESIGN-ADMIN-DIFF 13a.3). Turning it off stays with `ops.feature_flag_manage`.
   */
  superAdminToEnable: boolean;
  /** Q138: the driver listing was removed; the flag is shown as "eskirgan" and offers no change (13a.2). */
  deprecated: boolean;
};

export const FLAG_KEYS: FeatureFlagKey[] = [
  "passenger_enabled",
  "parcel_enabled",
  "driver_listing_enabled",
  "corridor_matching_enabled",
  "tracking_enabled",
  "card_payments_enabled",
  "wallet_required",
  "promotions_enabled",
];

export const FLAG_META: Record<FeatureFlagKey, FlagMeta> = {
  passenger_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: true, q48Gated: true, superAdminToEnable: true, deprecated: false },
  parcel_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true, superAdminToEnable: false, deprecated: false },
  driver_listing_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true, superAdminToEnable: false, deprecated: true },
  corridor_matching_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true, superAdminToEnable: false, deprecated: false },
  tracking_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true, superAdminToEnable: false, deprecated: false },
  card_payments_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: true, q48Gated: true, superAdminToEnable: true, deprecated: false },
  wallet_required: { defaultValue: true, lockedInProduction: true, needsApprovalReference: false, q48Gated: false, superAdminToEnable: false, deprecated: false },
  promotions_enabled: { defaultValue: false, lockedInProduction: null, needsApprovalReference: true, q48Gated: false, superAdminToEnable: false, deprecated: false },
};

/** The flag's name for people ("Pochta (v2)"); the raw key is shown next to it. */
export function flagLabel(key: FeatureFlagKey): string {
  return translate(`admin.flag.${key}`);
}

export function flagHint(key: FeatureFlagKey): string {
  return translate(`admin.flag.hint.${key}`);
}

/**
 * Whether this role may be offered a change of the flag to `enabled` (Q5, Q72, Q138). The server stays the authority:
 * it refuses an enable without super_admin + approval reference in production anyway; this only hides the button.
 */
export function mayOfferFlagValue(key: FeatureFlagKey, enabled: boolean, ctx: { canManage: boolean; superAdmin: boolean }): boolean {
  const meta = FLAG_META[key];
  if (!ctx.canManage || meta.deprecated) return false;
  if (enabled && meta.superAdminToEnable && !ctx.superAdmin) return false;
  return true;
}

/** Badge of a flag card: "yoqiq" / "o'chiq" / "eskirgan" (13a.1). */
export function flagBadge(key: FeatureFlagKey, enabled: boolean): { text: string; tone: "ok" | "gray" | "warn" } {
  if (FLAG_META[key].deprecated) return { text: translate("admin.flag.deprecated"), tone: "warn" };
  return enabled ? { text: translate("admin.platform.on"), tone: "ok" } : { text: translate("admin.platform.off"), tone: "gray" };
}

export const SCOPE_PRECEDENCE: FlagScopeType[] = ["cohort", "corridor", "region", "country"];

export function scopeLabel(scope: FlagScopeType): string {
  return translate(`admin.platform.scope.${scope}`);
}

export const COUNTRY_SCOPE_REF = "UZ";

export type FlagContext = { cohortRefs?: string[]; corridorRef?: string | null; regionRefs?: string[] };

export type FlagResolution = {
  enabled: boolean;
  /** Which level decided; null = no row matched, the default applies. */
  sourceScope: FlagScopeType | null;
  sourceRef: string | null;
  /** Two rows on the winning level disagree -> the safe default (Q26). */
  conflict: boolean;
};

function refsFor(scope: FlagScopeType, ctx: FlagContext): string[] {
  if (scope === "cohort") return ctx.cohortRefs ?? [];
  if (scope === "corridor") return ctx.corridorRef ? [ctx.corridorRef] : [];
  if (scope === "region") return ctx.regionRefs ?? [];
  return [COUNTRY_SCOPE_REF];
}

/** Effective value of one flag for a context (non-locked environments; production locks `wallet_required`). */
export function resolveFlag(rows: FlagValueDTO[], key: FeatureFlagKey, ctx: FlagContext): FlagResolution {
  const relevant = rows.filter((row) => row.flag_key === key);
  for (const scope of SCOPE_PRECEDENCE) {
    const refs = refsFor(scope, ctx);
    if (refs.length === 0) continue;
    const matching = relevant
      .filter((row) => row.scope_type === scope && refs.includes(row.scope_ref))
      .sort((a, b) => a.scope_ref.localeCompare(b.scope_ref));
    if (matching.length === 0) continue;
    const values = new Set(matching.map((row) => row.enabled));
    if (values.size === 1) return { enabled: matching[0].enabled, sourceScope: scope, sourceRef: matching[0].scope_ref, conflict: false };
    return { enabled: FLAG_META[key].defaultValue, sourceScope: scope, sourceRef: null, conflict: true };
  }
  return { enabled: FLAG_META[key].defaultValue, sourceScope: null, sourceRef: null, conflict: false };
}

export function describeResolution(resolution: FlagResolution): string {
  if (resolution.conflict) return translate("admin.platform.resConflict", { scope: scopeLabel(resolution.sourceScope as FlagScopeType) });
  if (!resolution.sourceScope) return translate("admin.platform.resDefault");
  return `${scopeLabel(resolution.sourceScope)}: ${resolution.sourceRef}`;
}

/** Same syntax check as `flags.validate_scope_ref`; returns an Uzbek hint or null when the ref looks valid. */
export function scopeRefProblem(scope: FlagScopeType, ref: string): string | null {
  const value = ref.trim();
  if (scope === "country") return value === COUNTRY_SCOPE_REF ? null : translate("admin.platform.ref.country");
  if (scope === "region") return /^[A-Z]{2}-[A-Z0-9]{1,3}$/.test(value) ? null : translate("admin.platform.ref.region");
  if (scope === "cohort") return /^[a-z0-9][a-z0-9_-]{1,63}$/.test(value) ? null : translate("admin.platform.ref.cohort");
  return value.startsWith("cor_") && value.length === 30 ? null : translate("admin.platform.ref.corridor");
}

function details(error: ApiError): Record<string, unknown> {
  return typeof error.details === "object" && error.details !== null ? (error.details as Record<string, unknown>) : {};
}

/**
 * The server's refusal of a flag change, in words that say what to do next. Returns null for errors that are not
 * specific to flags (the caller then shows the generic v2 message).
 */
export function flagRefusalMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const d = details(error);
  switch (error.code) {
    case "PRODUCTION_INVARIANTS_FAILED":
      return translate("admin.platform.err.q48", { reason: d.reason ? ` (${String(d.reason)})` : "" });
    case "APPROVAL_REFERENCE_REQUIRED":
      return translate("admin.platform.err.approval");
    case "FLAG_LOCKED_IN_ENVIRONMENT":
      return translate("admin.platform.err.locked", { value: d.locked_value === true ? translate("admin.platform.on") : translate("admin.platform.off") });
    case "FORBIDDEN":
      if (d.required_role === "super_admin") return translate("admin.platform.err.superAdmin");
      if (d.capability) return translate("admin.platform.err.noFlagCap");
      return null;
    case "VALIDATION_ERROR":
      if (d.reason === "support_contact_not_configured") return translate("admin.platform.err.supportPhone");
      if (d.field === "scope_ref") return translate("admin.platform.err.scopeRef");
      return null;
    case "VERSION_CONFLICT":
      return translate("admin.platform.err.flagVersion");
    default:
      return null;
  }
}

// --- corridors --------------------------------------------------------------------------------------------------------

export function rolloutLabel(state: CorridorRolloutState): string {
  return translate(`admin.platform.rollout.${state}`);
}

export function rolloutTone(state: CorridorRolloutState): "ok" | "blue" | "gray" | "warn" {
  return state === "active" ? "ok" : state === "pilot" ? "blue" : state === "internal" ? "warn" : "gray";
}

/** CORRIDOR_ROLLOUT transitions (state_machines.py). */
export const ROLLOUT_TRANSITIONS: Record<CorridorRolloutState, CorridorRolloutState[]> = {
  draft: ["internal", "closed"],
  internal: ["draft", "pilot", "closed"],
  pilot: ["internal", "active", "closed"],
  active: ["pilot", "closed"],
  closed: [],
};

const CORRIDOR_REASONS = [
  "needs_confirmed_road",
  "active_bookings",
] as const;

export function corridorReasonLabel(reason: string): string {
  return (CORRIDOR_REASONS as readonly string[]).includes(reason)
    ? translate(`admin.platform.corridorReason.${reason as (typeof CORRIDOR_REASONS)[number]}`)
    : reason;
}

/** Rollout guard refusal (INVALID_STATE_TRANSITION with a reason) in words; null for anything else. */
export function corridorRefusalMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const d = details(error);
  if (error.code === "INVALID_STATE_TRANSITION" && typeof d.reason === "string") {
    return translate("admin.platform.err.refused", { reason: corridorReasonLabel(d.reason) });
  }
  if (error.code === "VERSION_CONFLICT") return translate("admin.platform.err.recordVersion");
  return null;
}

// --- parcel policy ----------------------------------------------------------------------------------------------------

export function policyStatusLabel(status: string): string {
  if (status === "draft") return translate("admin.platform.draftNoEffect");
  if (status === "active") return translate("admin.platform.inForce");
  if (status === "superseded") return translate("admin.platform.superseded");
  return status;
}

export const POLICY_CATEGORIES = ["prohibited", "restricted", "business_declined"] as const;

export function policyCategoryLabel(category: string): string {
  return (POLICY_CATEGORIES as readonly string[]).includes(category)
    ? translate(`admin.platform.cat.${category as (typeof POLICY_CATEGORIES)[number]}`)
    : category;
}

/**
 * What the list header says. An empty or unconfirmed list is never "everything is allowed": with no active version
 * new parcel listings and bookings are closed (R5.2).
 */
export function policySummary(versions: Array<{ status: string; item_count: number }>): string {
  const active = versions.find((v) => v.status === "active");
  if (!active) return translate("admin.platform.noPolicy");
  return translate("admin.platform.policyCount", { count: active.item_count });
}

/** R5.2 / DB check: a `prohibited` item names its legal basis and source. */
export function policyItemProblem(item: {
  code: string; category: string; title_uz: string; description_uz: string; legal_basis?: string | null; source_ref?: string | null;
}): string | null {
  if (item.code.trim().length < 2) return translate("admin.platform.item.code");
  if (item.title_uz.trim().length < 2) return translate("admin.platform.item.title");
  if (item.description_uz.trim().length < 2) return translate("admin.platform.item.description");
  if (item.category === "prohibited" && (!(item.legal_basis ?? "").trim() || !(item.source_ref ?? "").trim())) {
    return translate("admin.platform.prohibitedNeedsBasis");
  }
  return null;
}

export function policyRefusalMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const d = details(error);
  if (error.code === "FORBIDDEN" && d.reason === "author_cannot_confirm_own_policy") return translate("admin.platform.err.author");
  if (d.reason === "prohibited_item_needs_legal_basis_and_source") return translate("admin.platform.prohibitedNeedsBasis");
  if (d.reason === "label_exists") return translate("admin.platform.err.labelExists");
  if (d.reason === "empty_policy") return translate("admin.platform.err.emptyPolicy");
  return null;
}

// --- outbox / system --------------------------------------------------------------------------------------------------

export function quotaStateLabel(state: string): string {
  if (state === "ok" || state === "warn" || state === "restrict") return translate(`admin.platform.quota.${state}`);
  return state;
}
