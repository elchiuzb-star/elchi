/**
 * Vehicle verification queue and driver eligibility (T3, T3a, I5; D16).
 *
 * A new v2 vehicle is born `pending` and no trip can use it until staff approve it here. The server decides who may
 * act (`ops.driver_eligibility_manage`); this panel only shows what the server returned and never marks anything
 * approved on its own. Each decision is confirmed first and sent with the row's `version`, so a screen that went
 * stale gets `VERSION_CONFLICT` instead of overwriting another staff member's decision.
 *
 * What the panel deliberately does not claim: approving the car does not verify the driver's own profile (that is the
 * v1 «Haydovchilar» section), and an eligibility block stops only new business - active trips, tracking and support
 * go on. Document files are counted, not opened: there is no signed-link viewer yet.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  adminSetDriverEligibility,
  adminVehicles,
  adminVerifyVehicle,
  type AdminVehicle,
  type AdminVehicleStatus,
} from "../api/v2/admin-vehicles.api";
import { newIdempotencyKey } from "../api/v2/http";
import { v2ErrorMessage } from "../utils/v2Errors";
import { formatDateTime } from "../utils/v2Format";

type Filter = AdminVehicleStatus | "all";

const FILTERS: Array<[Filter, string]> = [
  ["pending", "Kutilmoqda"],
  ["approved", "Tasdiqlangan"],
  ["rejected", "Rad etilgan"],
  ["blocked", "Bloklangan"],
  ["all", "Hammasi"],
];

const STATUS: Record<string, string> = {
  pending: "tasdiq kutilmoqda",
  approved: "tasdiqlangan",
  rejected: "rad etilgan",
  blocked: "bloklangan",
};

const DRIVER_STATUS: Record<string, string> = {
  pending: "profil tekshirilmagan",
  approved: "profil tasdiqlangan",
  rejected: "profil rad etilgan",
  blocked: "profil bloklangan",
};

const REASONS: Record<string, string> = {
  not_verified: "haydovchi profili tasdiqlanmagan",
  eligibility_blocked: "yangi ish bloklangan",
  document_expired: "hujjat muddati tugagan",
  account_inactive: "akkaunt faol emas",
  driver_profile_missing: "haydovchi profili yo'q",
};

// Mirrors app/modules/trips/rules.py VEHICLE_DECISIONS: approve from pending/rejected, reject from pending/approved.
const CAN_APPROVE = new Set(["pending", "rejected"]);
const CAN_REJECT = new Set(["pending", "approved"]);
const PAGE_SIZE = 20;

function label(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "-";
  return map[value] ?? value;
}

function kg(grams: number | null | undefined): string {
  return grams === null || grams === undefined ? "ko'rsatilmagan" : `${(grams / 1000).toLocaleString("uz-UZ")} kg`;
}

function litres(ml: number | null | undefined): string {
  return ml === null || ml === undefined ? "ko'rsatilmagan" : `${(ml / 1000).toLocaleString("uz-UZ")} l`;
}

function Btn(props: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "primary" | "danger" | "neutral";
}) {
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

type Pending = { kind: "approve" | "reject" | "block" | "unblock"; key: string };

const CONFIRM_TITLE: Record<Pending["kind"], string> = {
  approve: "Avtomobilni tasdiqlaysizmi?",
  reject: "Avtomobilni rad etasizmi?",
  block: "Haydovchining yangi ishini bloklaysizmi?",
  unblock: "Haydovchidan blokni olasizmi?",
};

const CONFIRM_HINT: Record<Pending["kind"], string> = {
  approve: "Tasdiqlangan avtomobil bilan haydovchi safar ochishi mumkin (haydovchining o'zi ham tasdiqlangan bo'lsa).",
  reject: "Mavjud safarlar bekor qilinmaydi — faqat bu avtomobil bilan yangi safar va bron to'xtaydi.",
  block: "Faqat yangi bron, e'lon va safar to'xtaydi. Faol safar, kuzatuv va yordam davom etadi.",
  unblock: "Blok olinadi; boshqa sabablar (masalan, tasdiqlanmagan profil) bo'lsa haydovchi baribir yangi ish ololmaydi.",
};

function VehicleCard({ vehicle, onChanged }: { vehicle: AdminVehicle; onChanged: () => void }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owner = vehicle.owner;
  const blocked = Boolean(owner.blocked_reason);

  function open(kind: Pending["kind"]) {
    // One idempotency key per user action: a retry of the same confirmation replays the first answer.
    setPending({ kind, key: newIdempotencyKey() });
    setReason("");
    setError(null);
  }

  const reasonRequired = pending !== null && pending.kind !== "approve";
  const reasonTooShort = reasonRequired && reason.trim().length < 3;

  async function confirm() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      if (pending.kind === "approve" || pending.kind === "reject") {
        await adminVerifyVehicle(
          vehicle.id,
          { decision: pending.kind, expected_version: vehicle.version, reason: reason.trim() || null },
          pending.key,
        );
      } else {
        await adminSetDriverEligibility(
          owner.user_id,
          { action: pending.kind, expected_version: owner.eligibility_version as number, reason: reason.trim() },
          pending.key,
        );
      }
      setPending(null);
      setReason("");
      onChanged();
    } catch (cause) {
      setError(v2ErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-[14px] border border-border bg-card p-4 text-sm" data-testid="vehicle-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="min-w-0 break-words text-base font-bold text-foreground">
          {vehicle.make_model} · {vehicle.color} · {vehicle.plate_number}
        </p>
        <span className="text-xs text-muted-foreground">{label(STATUS, vehicle.verification_status)}</span>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          ["O'rinlar (haydovchisiz)", String(vehicle.seat_capacity)],
          ["Bagaj hajmi", litres(vehicle.baggage_capacity_ml)],
          ["Yuk og'irligi", kg(vehicle.cargo_max_weight_g)],
          ["Yuk hajmi", litres(vehicle.cargo_max_volume_ml)],
        ].map(([name, value]) => (
          <div key={name} className="rounded-[10px] bg-muted/50 p-2">
            <p className="text-xs text-muted-foreground">{name}</p>
            <p className="font-semibold text-foreground">{value}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Ro'yxatga olingan: {formatDateTime(vehicle.created_at)} · Hujjatlar: {vehicle.document_file_ids.length} ta fayl
        (ko'rish havolasi hali yo'q)
        {vehicle.verified_at ? ` · Oxirgi qaror: ${formatDateTime(vehicle.verified_at)}` : ""}
      </p>
      {vehicle.verification_reason && (
        <p className="rounded-[8px] bg-muted/60 px-2 py-1.5 text-xs text-secondary-foreground">
          Qaror sababi: {vehicle.verification_reason}
        </p>
      )}

      <div className="space-y-1 rounded-[10px] border border-border p-3">
        <p className="font-semibold text-foreground">Haydovchi: {owner.user_id}</p>
        {owner.is_driver ? (
          <>
            <p className="text-muted-foreground">
              {label(DRIVER_STATUS, owner.driver_verification_status)} ·{" "}
              {owner.eligible ? "yangi ish olishi mumkin" : "yangi ish ololmaydi"} · faol safarlar: {owner.active_trip_count}
              {owner.account_active ? "" : " · akkaunt faol emas"}
            </p>
            {!owner.eligible && owner.reasons.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Sabab: {owner.reasons.map((code) => label(REASONS, code)).join(", ")}
              </p>
            )}
            {owner.reasons.includes("not_verified") && (
              <p className="text-xs text-warning">
                Avtomobil tasdig'i haydovchi profilini tasdiqlamaydi — profil «Haydovchilar» bo'limida tekshiriladi.
              </p>
            )}
            {blocked && <p className="text-xs text-destructive">Blok sababi: {owner.blocked_reason}</p>}
          </>
        ) : (
          <p className="text-muted-foreground">Bu akkauntda endi haydovchi roli yo'q — ruxsatni boshqarib bo'lmaydi.</p>
        )}
      </div>

      {pending === null ? (
        <div className="flex flex-wrap gap-2">
          {CAN_APPROVE.has(vehicle.verification_status) && (
            <Btn tone="primary" disabled={busy} onClick={() => open("approve")}>
              Tasdiqlash
            </Btn>
          )}
          {CAN_REJECT.has(vehicle.verification_status) && (
            <Btn tone="danger" disabled={busy} onClick={() => open("reject")}>
              Rad etish
            </Btn>
          )}
          {owner.is_driver && owner.eligibility_version !== null && (
            <Btn disabled={busy} onClick={() => open(blocked ? "unblock" : "block")}>
              {blocked ? "Blokni olish" : "Yangi ishini bloklash"}
            </Btn>
          )}
        </div>
      ) : (
        <div className="space-y-2 rounded-[12px] border border-warning/30 bg-warning/8 p-3" role="dialog" aria-label={CONFIRM_TITLE[pending.kind]}>
          <p className="font-semibold text-foreground">{CONFIRM_TITLE[pending.kind]}</p>
          <p className="text-xs text-muted-foreground">{CONFIRM_HINT[pending.kind]}</p>
          <label className="flex min-w-0 flex-col gap-1">
            <span className="font-medium text-secondary-foreground">
              {reasonRequired ? "Sabab (majburiy, audit uchun)" : "Izoh (ixtiyoriy)"}
            </span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-foreground outline-none"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Btn tone={pending.kind === "approve" || pending.kind === "unblock" ? "primary" : "danger"} disabled={busy || reasonTooShort} onClick={() => void confirm()}>
              {busy ? "Yuborilmoqda..." : "Ha, tasdiqlayman"}
            </Btn>
            <Btn disabled={busy} onClick={() => setPending(null)}>
              Bekor qilish
            </Btn>
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

export function AdminVehiclesPanel() {
  const [filter, setFilter] = useState<Filter>("pending");
  const [rows, setRows] = useState<AdminVehicle[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const request = useRef(0);

  const load = useCallback(() => {
    const ticket = ++request.current;
    setRows(null);
    setError(null);
    setNextCursor(null);
    adminVehicles({ status: filter === "all" ? undefined : filter, limit: PAGE_SIZE })
      .then((page) => {
        if (ticket !== request.current) return; // a newer filter won
        setRows(page.items);
        setNextCursor(page.nextCursor);
      })
      .catch((cause) => {
        if (ticket === request.current) setError(v2ErrorMessage(cause));
      });
  }, [filter]);

  useEffect(load, [load]);

  async function loadMore() {
    if (!nextCursor) return;
    const ticket = request.current;
    setLoadingMore(true);
    try {
      const page = await adminVehicles({ status: filter === "all" ? undefined : filter, cursor: nextCursor, limit: PAGE_SIZE });
      if (ticket !== request.current) return;
      setRows((current) => [...(current ?? []), ...page.items]);
      setNextCursor(page.nextCursor);
    } catch (cause) {
      if (ticket === request.current) setError(v2ErrorMessage(cause));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {FILTERS.map(([id, name]) => (
          <button
            key={id}
            type="button"
            onClick={() => setFilter(id)}
            aria-pressed={filter === id}
            className={`el-press h-9 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-semibold ${filter === id ? "bg-primary text-primary-foreground" : "bg-muted text-secondary-foreground"}`}
          >
            {name}
          </button>
        ))}
      </div>
      <p className="rounded-[12px] bg-accent px-3 py-2 text-xs text-primary">
        Yangi avtomobil «kutilmoqda» holatida tug'iladi va tasdiqlanmaguncha safar ochib bo'lmaydi. Eng eski so'rov birinchi.
      </p>
      {error && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-destructive">{error}</p>
          <Btn onClick={load}>Qayta urinish</Btn>
        </div>
      )}
      {rows === null && !error && (
        <p className="text-sm text-muted-foreground" aria-busy="true">
          Yuklanmoqda...
        </p>
      )}
      {rows !== null && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {filter === "pending" ? "Tasdiq kutayotgan avtomobil yo'q." : "Bu holatda avtomobil yo'q."}
        </p>
      )}
      <div className="grid gap-3">
        {(rows ?? []).map((vehicle) => (
          <VehicleCard key={vehicle.id} vehicle={vehicle} onChanged={load} />
        ))}
      </div>
      {nextCursor && (
        <Btn disabled={loadingMore} onClick={() => void loadMore()}>
          {loadingMore ? "Yuklanmoqda..." : "Yana ko'rsatish"}
        </Btn>
      )}
    </div>
  );
}
