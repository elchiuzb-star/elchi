/**
 * Pure rules behind the staff platform panel (`AdminPlatformPanel.tsx`). No I/O, no React.
 *
 * Flag resolution mirrors `app/modules/geo/flags.py` (ADR-0008): cohort > corridor > region > country, no row ->
 * production default, conflicting rows on one level -> the safe default (Q26). The server stays the authority: this
 * copy only explains to an operator which row wins where; it never decides whether a change is allowed.
 */
import type { CorridorRolloutState, FeatureFlagKey, FlagScopeType, FlagValueDTO } from "../api/v2/admin-platform.api";
import { ApiError } from "../types/api";

export type FlagMeta = {
  label: string;
  hint: string;
  /** Value when no row matches (every environment; flags.py PRODUCTION_FLAG_DEFAULTS). */
  defaultValue: boolean;
  /** Production can only hold this value (Q1: wallet_required). */
  lockedInProduction: boolean | null;
  /** Production enable needs super_admin + approval reference (Q5, K7). */
  needsApprovalReference: boolean;
  /** v2 service flag behind the Q48 launch gate (Q56). */
  q48Gated: boolean;
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
  passenger_enabled: {
    label: "Yo'lovchi xizmati",
    hint: "Production'da huquqiy tekshiruvgacha o'chiq (K7/Q5). Yoqish: super_admin, tasdiq hujjati, support telefoni (Q87) va Q48.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: true, q48Gated: true,
  },
  parcel_enabled: {
    label: "Pochta (v2)", hint: "Koridor bo'yicha yoqiladi (Q5); production'da Q48 o'tmaguncha yoqilmaydi.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true,
  },
  driver_listing_enabled: {
    label: "Haydovchi e'lonlari", hint: "Production'da Q48 o'tmaguncha yoqilmaydi.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true,
  },
  corridor_matching_enabled: {
    label: "Koridor bo'yicha moslash", hint: "Production'da Q48 o'tmaguncha yoqilmaydi.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true,
  },
  tracking_enabled: {
    label: "Jonli kuzatuv", hint: "Production'da Q48 o'tmaguncha yoqilmaydi.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: false, q48Gated: true,
  },
  card_payments_enabled: {
    label: "Karta to'lovlari", hint: "Yoqish: super_admin, tasdiq hujjati va Q48.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: true, q48Gated: true,
  },
  wallet_required: {
    label: "Balans tekshiruvi", hint: "Production'da doim yoqiq (Q1). Boshqa muhitda o'chirish komissiyani nolga tushirmaydi.",
    defaultValue: true, lockedInProduction: true, needsApprovalReference: false, q48Gated: false,
  },
  promotions_enabled: {
    label: "Referral va bonuslar", hint: "Production'da o'chiq (Q101). Yoqish: super_admin va tasdiq hujjati.",
    defaultValue: false, lockedInProduction: null, needsApprovalReference: true, q48Gated: false,
  },
};

export const SCOPE_PRECEDENCE: FlagScopeType[] = ["cohort", "corridor", "region", "country"];

export const SCOPE_LABELS: Record<FlagScopeType, string> = {
  cohort: "Kohorta",
  corridor: "Koridor",
  region: "Hudud",
  country: "Mamlakat",
};

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
  if (resolution.conflict) {
    return `${SCOPE_LABELS[resolution.sourceScope as FlagScopeType]} darajasida ziddiyatli qatorlar — xavfsiz standart (Q26)`;
  }
  if (!resolution.sourceScope) return "Qator yo'q — standart qiymat";
  return `${SCOPE_LABELS[resolution.sourceScope]}: ${resolution.sourceRef}`;
}

/** Same syntax check as `flags.validate_scope_ref`; returns an Uzbek hint or null when the ref looks valid. */
export function scopeRefProblem(scope: FlagScopeType, ref: string): string | null {
  const value = ref.trim();
  if (scope === "country") return value === COUNTRY_SCOPE_REF ? null : "Mamlakat doirasi faqat «UZ».";
  if (scope === "region") return /^[A-Z]{2}-[A-Z0-9]{1,3}$/.test(value) ? null : "Hudud kodi, masalan «UZ-SA».";
  if (scope === "cohort") return /^[a-z0-9][a-z0-9_-]{1,63}$/.test(value) ? null : "Kohorta: kichik lotin harflari, raqam, «_» yoki «-».";
  return value.startsWith("cor_") && value.length === 30 ? null : "Koridor id'si «cor_…» ko'rinishida.";
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
      return (
        "Production'da rad etildi: Q48 ishga tushirish sharti o'tmagan" +
        (d.reason ? ` (${String(d.reason)})` : "") +
        ". DB rollari, balans himoyasi, ledger manbalari va seed stavka tasdig'i yopilmaguncha v2 xizmatlari yoqilmaydi (Q56)."
      );
    case "APPROVAL_REFERENCE_REQUIRED":
      return "Production'da bu flag faqat huquqiy/biznes tasdiq hujjati raqami bilan yoqiladi (Q5). «Tasdiq hujjati» maydonini to'ldiring.";
    case "FLAG_LOCKED_IN_ENVIRONMENT":
      return `Bu muhitda flag qulflangan: qiymati faqat ${d.locked_value === true ? "yoqiq" : "o'chiq"} bo'la oladi (Q1).`;
    case "FORBIDDEN":
      if (d.required_role === "super_admin") return "Production'da bu flagni faqat super_admin yoqa oladi (Q5).";
      if (d.capability) return "Sizda flaglarni o'zgartirish huquqi yo'q (ops.feature_flag_manage).";
      return null;
    case "VALIDATION_ERROR":
      if (d.reason === "support_contact_not_configured") {
        return "Yo'lovchi xizmatini yoqishdan oldin javob beriladigan support telefoni va ish vaqti kiritilishi shart (Q87).";
      }
      if (d.field === "scope_ref") return "Doira qiymati noto'g'ri yoki mavjud emas.";
      return null;
    case "VERSION_CONFLICT":
      return "Boshqa xodim bu qatorni hozirgina o'zgartirdi. Ro'yxat yangilandi — qarorni qayta ko'rib chiqing.";
    default:
      return null;
  }
}

// --- corridors --------------------------------------------------------------------------------------------------------

export const ROLLOUT_LABELS: Record<CorridorRolloutState, string> = {
  draft: "Qoralama",
  internal: "Ichki sinov",
  pilot: "Pilot",
  active: "Faol",
  closed: "Yopilgan",
};

/** CORRIDOR_ROLLOUT transitions (state_machines.py). */
export const ROLLOUT_TRANSITIONS: Record<CorridorRolloutState, CorridorRolloutState[]> = {
  draft: ["internal", "closed"],
  internal: ["draft", "pilot", "closed"],
  pilot: ["internal", "active", "closed"],
  active: ["pilot", "closed"],
  closed: [],
};

export const CORRIDOR_REASON_LABELS: Record<string, string> = {
  needs_two_active_stops: "kamida 2 ta faol bekat kerak (Q47)",
  stops_missing_meeting_evidence: "bekatlarda uchrashuv izohi yoki foto dalil yo'q (Q27)",
  needs_active_stop: "ichki sinov uchun kamida 1 ta faol bekat kerak",
  active_bookings: "koridorda faol bronlar bor",
  stop_used_by_confirmed_route: "bekat tasdiqlangan marshrutda ishlatilmoqda",
};

export function corridorReasonLabel(reason: string): string {
  return CORRIDOR_REASON_LABELS[reason] ?? reason;
}

/** Rollout/stop guard refusal (INVALID_STATE_TRANSITION with a reason) in words; null for anything else. */
export function corridorRefusalMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const d = details(error);
  if (error.code === "INVALID_STATE_TRANSITION" && typeof d.reason === "string") {
    const stops = Array.isArray(d.stop_ids) && d.stop_ids.length ? ` Bekatlar: ${(d.stop_ids as string[]).join(", ")}.` : "";
    return `Rad etildi: ${corridorReasonLabel(d.reason)}.${stops}`;
  }
  if (error.code === "VERSION_CONFLICT") return "Boshqa xodim bu yozuvni o'zgartirdi. Yangilab, qayta urinib ko'ring.";
  return null;
}

/** Q27: a stop carries evidence when it has a non-blank meeting note or a photo. */
export function stopHasEvidence(stop: { meeting_note?: string | null; meeting_photo_file_id?: string | null }): boolean {
  return Boolean((stop.meeting_note ?? "").trim() || stop.meeting_photo_file_id);
}

// --- parcel policy ----------------------------------------------------------------------------------------------------

export const POLICY_STATUS_LABELS: Record<string, string> = {
  draft: "Qoralama — hech kimga amal qilmaydi",
  active: "Amalda",
  superseded: "Almashtirilgan",
};

export const POLICY_CATEGORY_LABELS: Record<string, string> = {
  prohibited: "Taqiqlangan (qonun)",
  restricted: "Cheklangan",
  business_declined: "Platforma qabul qilmaydi",
};

/**
 * What the list header says. An empty or unconfirmed list is never "everything is allowed": with no active version
 * new parcel listings and bookings are closed (R5.2).
 */
export function policySummary(versions: Array<{ status: string; item_count: number }>): string {
  const active = versions.find((v) => v.status === "active");
  if (!active) {
    return "Tasdiqlangan ro'yxat yo'q: yangi pochta e'lonlari va bronlari yopiq. Bu «hammasi mumkin» degani emas.";
  }
  return `Amaldagi ro'yxatda ${active.item_count} ta band.`;
}

/** R5.2 / DB check: a `prohibited` item names its legal basis and source. */
export function policyItemProblem(item: {
  code: string; category: string; title_uz: string; description_uz: string; legal_basis?: string | null; source_ref?: string | null;
}): string | null {
  if (item.code.trim().length < 2) return "Kod kamida 2 belgi.";
  if (item.title_uz.trim().length < 2) return "Nomi kamida 2 belgi.";
  if (item.description_uz.trim().length < 2) return "Tavsif kamida 2 belgi.";
  if (item.category === "prohibited" && (!(item.legal_basis ?? "").trim() || !(item.source_ref ?? "").trim())) {
    return "Taqiqlangan band uchun huquqiy asos va manba majburiy.";
  }
  return null;
}

export function policyRefusalMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const d = details(error);
  if (error.code === "FORBIDDEN" && d.reason === "author_cannot_confirm_own_policy") {
    return "Muallif o'z qoralamasini tasdiqlay olmaydi — boshqa super_admin tasdiqlashi kerak.";
  }
  if (d.reason === "prohibited_item_needs_legal_basis_and_source") return "Taqiqlangan band uchun huquqiy asos va manba majburiy.";
  if (d.reason === "label_exists") return "Bunday nomli versiya allaqachon bor.";
  if (d.reason === "empty_policy") return "Ro'yxatda kamida bitta band bo'lishi kerak.";
  return null;
}

// --- outbox / system --------------------------------------------------------------------------------------------------

export const QUOTA_STATE_LABELS: Record<string, string> = {
  ok: "Me'yorda",
  warn: "Ogohlantirish (≥70%)",
  restrict: "Cheklangan (≥85%)",
};
