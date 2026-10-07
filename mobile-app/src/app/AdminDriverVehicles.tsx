/**
 * A driver's v2 vehicles and their verification, shown on the driver card next to the v1 documents (T3, T3a, I5; D16).
 *
 * The car is verified where the driver is verified: the «Haydovchilar» card shows the profile documents and, right
 * under them, the cars this driver registered. There is no separate vehicle section any more; the drivers list marks
 * who has a car waiting (`usePendingVehicles`).
 *
 * A new v2 vehicle is born `pending` and no trip can use it until staff approve it here. The server decides who may
 * act (`ops.driver_eligibility_manage`, admin+): an operator sees a note instead of buttons the server would refuse.
 * Each decision is confirmed first and sent with the row's `version`, so a screen that went stale gets
 * `VERSION_CONFLICT` instead of overwriting another staff member's decision.
 *
 * What this block deliberately does not claim: approving the car does not verify the driver's profile (that is the
 * card's own «Tasdiqlash»), and an eligibility block stops only new business - active trips, tracking and support go
 * on. Document files open only where the server handed out a link; a bare storage id is listed, not guessed into a URL.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  adminSetDriverEligibility,
  adminVehicles,
  adminVerifyVehicle,
  type AdminVehicle,
} from "../api/v2/admin-vehicles.api";
import { apiOriginUrl } from "../api/http";
import { newIdempotencyKey } from "../api/v2/http";
import { capabilities, type CapabilitiesDTO } from "../api/v2/ops.api";
import { translate, translateDynamic, type MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import { v2ErrorMessage } from "../utils/v2Errors";
import { formatDate, formatDateTime } from "../utils/v2Format";
import { Badge, Btn, Note, hasCap, type BadgeTone } from "./adminMarketKit";
import { X } from "./ui/icons";

const STATUS_TONE: Record<string, BadgeTone> = { pending: "warn", approved: "ok", rejected: "err", blocked: "err" };

// Mirrors app/modules/trips/rules.py VEHICLE_DECISIONS: approve from pending/rejected, reject from pending/approved.
const CAN_APPROVE = new Set(["pending", "rejected"]);
const CAN_REJECT = new Set(["pending", "approved"]);
// One driver has one or two cars (Q94); a pending queue larger than this is listed as "at least".
const PAGE_SIZE = 50;

function statusLabel(status: string): string {
  return translateDynamic(`admin.vehicles.status.${status}`) ?? status;
}

function profileLabel(status: string | null | undefined): string {
  if (!status) return "-";
  return translateDynamic(`admin.vehicles.profile.${status}`) ?? status;
}

function reasonLabel(code: string): string {
  return translateDynamic(`admin.vehicles.reason.${code}`) ?? code;
}

function kg(grams: number | null | undefined): string {
  return grams === null || grams === undefined ? translate("admin.vehicles.notGiven") : (grams / 1000).toLocaleString("uz-UZ");
}

function litres(ml: number | null | undefined): string {
  return ml === null || ml === undefined ? translate("admin.vehicles.notGiven") : (ml / 1000).toLocaleString("uz-UZ");
}

type Pending = { kind: "approve" | "reject" | "block" | "unblock"; key: string };

const CONFIRM_TITLE: Record<Pending["kind"], MessageKey> = {
  approve: "admin.vehicles.confirmApprove",
  reject: "admin.vehicles.confirmReject",
  block: "admin.vehicles.confirmBlock",
  unblock: "admin.vehicles.confirmUnblock",
};

const CONFIRM_HINT: Record<Pending["kind"], MessageKey> = {
  approve: "admin.vehicles.hintApprove",
  reject: "admin.vehicles.hintReject",
  block: "admin.vehicles.hintBlock",
  unblock: "admin.vehicles.hintUnblock",
};

/** A document reference the browser can open: an absolute or a server-relative signed link. Bare storage ids are not. */
export function documentLink(ref: string): string | null {
  if (/^https?:\/\//i.test(ref)) return ref;
  if (ref.startsWith("/api/") && /[?&]sig=/.test(ref)) return apiOriginUrl(ref);
  return null;
}

function isImage(ref: string): boolean {
  return /\.(png|jpe?g|webp|gif)(\?|$)/i.test(ref);
}

/** The design's `doc` overlay: one vehicle's files, previewed where a link exists. */
function DocumentsModal({ vehicle, onClose }: { vehicle: AdminVehicle; onClose: () => void }) {
  const t = useT();
  const files = vehicle.document_file_ids;
  const [index, setIndex] = useState(0);
  const ref = files[index] ?? "";
  const link = ref ? documentLink(ref) : null;
  const name = ref.split("?")[0].split("/").pop() || ref;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-foreground/60 p-4" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={t("admin.vehicles.docTitle", { name })}
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-[12px] border border-border bg-card shadow-2xl"
      >
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <h3 className="min-w-0 break-words text-base font-bold text-foreground">{t("admin.vehicles.docTitle", { name })}</h3>
          <button type="button" onClick={onClose} aria-label={t("common.close")} className="el-press rounded-[10px] p-2 text-muted-foreground hover:bg-muted">
            <X size={18} />
          </button>
        </header>
        <div className="min-h-0 flex-1 space-y-3 overflow-auto bg-background p-4">
          {files.length > 1 ? (
            <div className="flex flex-wrap gap-2">
              {files.map((file, position) => (
                <Btn key={file} tone={position === index ? "primary" : "neutral"} onClick={() => setIndex(position)}>
                  {t("admin.vehicles.docN", { n: position + 1 })}
                </Btn>
              ))}
            </div>
          ) : null}
          {!link ? (
            <Note>
              {t("admin.vehicles.docNoLink")}
              <span className="mt-1 block break-all font-mono text-xs">{ref}</span>
            </Note>
          ) : isImage(link) ? (
            <img src={link} alt={name} className="mx-auto max-h-[70vh] max-w-full rounded-[10px] bg-card object-contain" />
          ) : (
            <iframe src={link} title={name} className="h-[70vh] w-full rounded-[10px] border border-border bg-card" />
          )}
        </div>
        <footer className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">
          {link ? (
            <a
              href={link}
              target="_blank"
              rel="noreferrer noopener"
              className="el-press inline-flex h-9 items-center rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground"
            >
              {t("admin.vehicles.openNewTab")}
            </a>
          ) : null}
          <Btn onClick={onClose}>{t("common.close")}</Btn>
        </footer>
      </section>
    </div>
  );
}

function VehicleCard({
  vehicle,
  canManage,
  onChanged,
  onChangeVehicle,
}: {
  vehicle: AdminVehicle;
  canManage: boolean;
  /** v3 §15.3: «Avtomobilni o'zgartirish» sits on the card; it opens the v1 vehicle correction (Q94). */
  onChangeVehicle?: () => void;
  onChanged: () => void;
}) {
  const t = useT();
  const [pending, setPending] = useState<Pending | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docs, setDocs] = useState(false);
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

  const eligibility = owner.eligible ? t("admin.vehicles.mayTakeNew") : t("admin.vehicles.mayNotTakeNew");

  return (
    <div
      className={`space-y-3 rounded-[14px] border-2 border-primary bg-card p-4 text-sm ${vehicle.verification_status === "pending" ? "ring-2 ring-primary/10" : ""}`}
      data-testid="vehicle-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 break-words text-base font-bold text-foreground">
          {vehicle.make_model} · {vehicle.color} · {vehicle.plate_number}
        </p>
        <Badge tone={STATUS_TONE[vehicle.verification_status] ?? "gray"}>{statusLabel(vehicle.verification_status)}</Badge>
      </div>
      <p className="font-medium text-foreground">{`${t("driverProfileForm.passengerSeats")}: ${vehicle.seat_capacity}`}</p>
      <p className="text-xs text-secondary-foreground">
        {t("admin.vehicles.capacity", {
          seats: vehicle.seat_capacity,
          luggage: litres(vehicle.baggage_capacity_ml),
          kg: kg(vehicle.cargo_max_weight_g),
          litres: litres(vehicle.cargo_max_volume_ml),
        })}
      </p>
      <p className="text-xs text-muted-foreground">
        {t("admin.v3.drivers.registeredOn", { date: formatDate(vehicle.created_at) })}
        {vehicle.verified_at ? ` · ${t("admin.vehicles.lastDecision", { date: formatDateTime(vehicle.verified_at) })}` : ""}
      </p>
      {vehicle.verification_reason && (
        <p className="rounded-[8px] bg-muted/60 px-2 py-1.5 text-xs text-secondary-foreground">
          {t("admin.vehicles.decisionReason", { reason: vehicle.verification_reason })}
        </p>
      )}

      <div className="space-y-1 rounded-[10px] border border-border p-3">
        {owner.is_driver ? (
          <>
            <p className="text-secondary-foreground">
              {t("admin.vehicles.ownerLine", {
                profile: profileLabel(owner.driver_verification_status),
                eligibility,
                count: owner.active_trip_count,
              })}
              {owner.account_active ? "" : ` · ${t("admin.vehicles.accountInactive")}`}
            </p>
            {!owner.eligible && owner.reasons.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {t("admin.vehicles.reasonLine", { reasons: owner.reasons.map(reasonLabel).join(", ") })}
              </p>
            )}
            {blocked && <p className="text-xs text-destructive">{t("admin.vehicles.blockReason", { reason: owner.blocked_reason ?? "" })}</p>}
          </>
        ) : (
          <p className="text-muted-foreground">
            {t("admin.vehicles.ownerNoDriver")}
          </p>
        )}
      </div>
      {owner.reasons.includes("not_verified") || owner.driver_verification_status !== "approved" ? (
        <p className="text-xs text-warning">{t("admin.vehicles.notProfile")}</p>
      ) : null}

      {pending === null ? (
        <div className="flex flex-wrap gap-2">
          {onChangeVehicle ? <Btn onClick={onChangeVehicle}>{t("admin.drivers.changeVehicle")}</Btn> : null}
          {vehicle.document_file_ids.length > 0 ? <Btn onClick={() => setDocs(true)}>{t("admin.vehicles.viewDocs")}</Btn> : null}
          {canManage && CAN_APPROVE.has(vehicle.verification_status) && (
            <Btn tone="primary" disabled={busy} onClick={() => open("approve")}>
              {t("common.confirm")}
            </Btn>
          )}
          {canManage && CAN_REJECT.has(vehicle.verification_status) && (
            <Btn tone="danger" disabled={busy} onClick={() => open("reject")}>
              {t("admin.mk.reject")}
            </Btn>
          )}
          {canManage && owner.is_driver && owner.eligibility_version !== null && (
            <Btn disabled={busy} onClick={() => open(blocked ? "unblock" : "block")}>
              {blocked ? t("admin.vehicles.unblockNew") : t("admin.vehicles.blockNew")}
            </Btn>
          )}
        </div>
      ) : (
        <div className="space-y-2 rounded-[12px] border border-warning/30 bg-warning/8 p-3" role="dialog" aria-label={t(CONFIRM_TITLE[pending.kind])}>
          <p className="font-semibold text-foreground">{t(CONFIRM_TITLE[pending.kind])}</p>
          <p className="text-xs text-muted-foreground">{t(CONFIRM_HINT[pending.kind])}</p>
          <label className="flex min-w-0 flex-col gap-1">
            <span className="font-medium text-secondary-foreground">
              {reasonRequired ? t("admin.vehicles.reasonRequired") : t("admin.vehicles.noteOptional")}
            </span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-foreground outline-none"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Btn
              tone={pending.kind === "approve" || pending.kind === "unblock" ? "primary" : "danger"}
              disabled={busy || reasonTooShort}
              onClick={() => void confirm()}
            >
              {busy ? t("admin.vehicles.sending") : t("admin.mk.yesConfirm")}
            </Btn>
            <Btn disabled={busy} onClick={() => setPending(null)}>
              {t("common.cancel")}
            </Btn>
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {docs ? <DocumentsModal vehicle={vehicle} onClose={() => setDocs(false)} /> : null}
    </div>
  );
}

/** The vehicles block of one driver's card. `ownerUserId` is the driver's `usr_` id (v1 `user_public_id`). */
export function DriverVehicles({ ownerUserId, onChangeVehicle }: { ownerUserId: string | null | undefined; onChangeVehicle?: () => void }) {
  const t = useT();
  const [rows, setRows] = useState<AdminVehicle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // undefined: still asking; null: the capability call failed (the list call then shows the server's own answer).
  const [caps, setCaps] = useState<CapabilitiesDTO | null | undefined>(undefined);
  const request = useRef(0);
  const canManage = hasCap(caps as { capabilities?: readonly string[] } | null, "ops.driver_eligibility_manage");
  // The server reads and decides vehicles with one capability (trips/api.py T3a); without it there is nothing to show.
  const noAccess = Boolean(caps) && !canManage;

  useEffect(() => {
    capabilities().then(setCaps).catch(() => setCaps(null));
  }, []);

  const load = useCallback(() => {
    if (caps === undefined || noAccess || !ownerUserId) return;
    const ticket = ++request.current;
    setRows(null);
    setError(null);
    adminVehicles({ owner_user_id: ownerUserId, limit: PAGE_SIZE })
      .then((page) => {
        if (ticket === request.current) setRows(page.items);
      })
      .catch((cause) => {
        if (ticket === request.current) setError(v2ErrorMessage(cause));
      });
  }, [caps, noAccess, ownerUserId]);

  useEffect(load, [load]);

  return (
    <section className="grid gap-3" aria-label={t("admin.vehicles.title")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-bold text-foreground">{t("admin.vehicles.title")}</h3>
          <p className="text-xs text-muted-foreground">{t("admin.vehicles.subtitle")}</p>
        </div>
        {/* No v2 card to carry the button (no car yet, no access, still loading): the v1 correction stays reachable. */}
        {onChangeVehicle && !(rows && rows.length > 0) ? <Btn onClick={onChangeVehicle}>{t("admin.drivers.changeVehicle")}</Btn> : null}
      </div>
      {!ownerUserId ? <Note>{t("admin.vehicles.noOwner")}</Note> : null}
      {ownerUserId && noAccess ? <Note>{t("admin.vehicles.noAccess")}</Note> : null}
      {error && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-destructive">{error}</p>
          <Btn onClick={load}>{t("common.retry")}</Btn>
        </div>
      )}
      {ownerUserId && rows === null && !error && !noAccess && (
        <p className="text-sm text-muted-foreground" aria-busy="true">
          {t("common.loading")}
        </p>
      )}
      {rows !== null && rows.length === 0 && <p className="text-sm text-muted-foreground">{t("admin.vehicles.empty")}</p>}
      {(rows ?? []).map((vehicle, index) => (
        <VehicleCard key={vehicle.id} vehicle={vehicle} canManage={canManage} onChanged={load} onChangeVehicle={index === 0 ? onChangeVehicle : undefined} />
      ))}
    </section>
  );
}

/**
 * Cars waiting for a decision, for the drivers list: which drivers to open first. Empty (and no request) for staff
 * without the capability; a failed read is an empty list - the card itself still shows the server's answer.
 */
export function usePendingVehicles(refreshKey: unknown): { vehicles: AdminVehicle[]; more: boolean } {
  const [state, setState] = useState<{ vehicles: AdminVehicle[]; more: boolean }>({ vehicles: [], more: false });
  useEffect(() => {
    let alive = true;
    capabilities()
      .then((caps) => {
        if (!hasCap(caps as { capabilities?: readonly string[] } | null, "ops.driver_eligibility_manage")) return null;
        return adminVehicles({ status: "pending", limit: PAGE_SIZE });
      })
      .then((page) => {
        if (alive && page) setState({ vehicles: page.items, more: Boolean(page.nextCursor) });
      })
      .catch(() => {
        if (alive) setState({ vehicles: [], more: false });
      });
    return () => {
      alive = false;
    };
  }, [refreshKey]);
  return state;
}
