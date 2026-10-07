/**
 * Corridor price references (G12-G14, Q42/Q53/Q90).
 *
 * ELCHI is a two-sided auction: the price is what a client and a driver agree on. A corridor band is therefore
 * a **reference**, not a tariff - it feeds the ranking and puts an advisory warning on an unusual offer, and
 * that is all. This screen exists because that reference had no operator surface at all: the rows could only be
 * created with SQL, and `enforced` - the one setting that still refuses a price - could not be set from
 * anywhere.
 *
 * So the screen is built around making the difference impossible to miss: an advisory reference is the default
 * and reads as advice, and turning a band into a hard limit is a separate, explained switch.
 *
 * Scope: a band is corridor-wide (a loose safety range for the whole direction) - ELCHI works point A -> point B
 * and has no stops, so there is no narrower band to create or show (ADR-0028, Q160).
 *
 * Q52: editing is admin+ (`ops.corridor_manage`). Without that capability the form is not rendered at all - the
 * operator reads the table and the history, and the button names the version a save would create ("Yangilash (v3)").
 */
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw, ShieldAlert } from "./ui/icons";

import {
  listCorridors,
  listPriceBands,
  priceBandHistory,
  setPriceBand,
  type CorridorDTO,
  type PriceBandChangeDTO,
  type PriceBandDTO,
  type PriceBandUpsert,
} from "../api/v2/ops.api";
import { capabilities, type CapabilitiesDTO } from "../api/v2/ops.api";
import { translate, type MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import { formatDateTime } from "../utils/v2Format";
import { v2ErrorMessage, warningMessage } from "../utils/v2Errors";
import { Badge, Note, hasCap } from "./adminMarketKit";

type ServiceType = "passenger" | "parcel";

const SERVICE_KEY: Record<ServiceType, MessageKey> = {
  passenger: "admin.mk.passenger",
  parcel: "admin.mk.cargo",
};

const SERVICE_OPTION_KEY: Record<ServiceType, MessageKey> = {
  passenger: "admin.bands.passengerPerSeat",
  parcel: "admin.bands.parcelTotal",
};

function serviceLabel(value: string): string {
  return value in SERVICE_KEY ? translate(SERVICE_KEY[value as ServiceType]) : value;
}

/** Q52: editing a price reference is admin+ (`ops.corridor_manage`); everybody else reads the table and history. */
export function canEditPriceBands(caps: CapabilitiesDTO | null): boolean {
  return hasCap(caps as { capabilities?: readonly string[] } | null, "ops.corridor_manage");
}

function soum(minor: number): string {
  return new Intl.NumberFormat("uz-UZ").format(Math.round(minor / 100));
}

function toMinor(value: string): number {
  const parsed = Math.round(Number(value.replace(/\s/g, "")));
  return Number.isFinite(parsed) && parsed > 0 ? parsed * 100 : 0;
}

const FIELD = "h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100 disabled:bg-muted/50";

export function AdminPriceBandsPanel() {
  const t = useT();
  const [corridors, setCorridors] = useState<CorridorDTO[]>([]);
  const [corridorId, setCorridorId] = useState("");
  const [bands, setBands] = useState<PriceBandDTO[]>([]);
  const [history, setHistory] = useState<PriceBandChangeDTO[]>([]);
  const [caps, setCaps] = useState<CapabilitiesDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [form, setForm] = useState({
    service_type: "passenger" as ServiceType,
    floor: "",
    ceiling: "",
    is_active: true,
    enforced: false,
    reason: "",
  });
  const canEdit = canEditPriceBands(caps);

  useEffect(() => {
    capabilities().then(setCaps).catch(() => setCaps(null));
    void (async () => {
      try {
        const rows = await listCorridors();
        setCorridors(rows);
        if (rows.length && !corridorId) setCorridorId(rows[0].id);
      } catch (err) {
        setError(v2ErrorMessage(err));
      }
    })();
  }, []);

  async function reload(id = corridorId) {
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const [rows, changes] = await Promise.all([listPriceBands(id), priceBandHistory(id, { limit: 20 })]);
      setBands(rows);
      setHistory(changes);
    } catch (err) {
      setError(v2ErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void reload(corridorId);
  }, [corridorId]);

  /** The corridor-wide band for the service type being edited, if there is one - it carries the version. */
  const current = useMemo(
    () => bands.find((band) => band.service_type === form.service_type) ?? null,
    [bands, form.service_type],
  );

  useEffect(() => {
    setForm((previous) => ({
      ...previous,
      floor: current ? String(Math.round(current.floor_minor / 100)) : "",
      ceiling: current ? String(Math.round(current.ceiling_minor / 100)) : "",
      is_active: current ? current.is_active : true,
      enforced: current ? current.enforced : false,
      reason: "",
    }));
  }, [current?.version, form.service_type]);

  const floorMinor = toMinor(form.floor);
  const ceilingMinor = toMinor(form.ceiling);
  const canSave =
    canEdit && Boolean(corridorId) && floorMinor > 0 && ceilingMinor >= floorMinor && form.reason.trim().length > 0 && !busy;
  const nextVersion = (current?.version ?? 0) + 1;

  async function save() {
    setBusy(true);
    setError(null);
    setWarnings([]);
    try {
      const result = await setPriceBand(corridorId, form.service_type, {
        expected_version: current?.version ?? null,
        floor_minor: floorMinor,
        ceiling_minor: ceilingMinor,
        is_active: form.is_active,
        enforced: form.enforced,
        reason: form.reason.trim(),
      } as PriceBandUpsert);
      setWarnings(result.warnings.map((warning) => warningMessage(warning.code)));
      await reload();
    } catch (err) {
      setError(v2ErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="grid gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">{t("admin.bands.title")}</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{t("admin.bands.subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={() => void reload()}
          disabled={busy}
          className="el-press inline-flex h-10 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground disabled:opacity-50"
        >
          <RefreshCw size={16} /> {t("support.refresh")}
        </button>
      </header>

      {error && (
        <p role="alert" className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
          {error}
        </p>
      )}
      {warnings.map((warning) => (
        <p
          key={warning}
          className="flex items-start gap-2 rounded-[12px] border border-warning/28 bg-warning/14 px-4 py-3 text-sm text-warning"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          {warning}
        </p>
      ))}

      <label className="grid max-w-sm gap-1.5 text-sm font-medium text-secondary-foreground">
        {t("admin.mk.corridor")}
        <select value={corridorId} onChange={(event) => setCorridorId(event.target.value)} className={FIELD}>
          {corridors.map((corridor) => (
            <option key={corridor.id} value={corridor.id}>
              {corridor.name}
            </option>
          ))}
        </select>
      </label>

      <div className={`grid gap-4 ${canEdit ? "lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]" : ""}`}>
        {canEdit ? (
          <form
            className="grid content-start gap-3 rounded-[12px] border border-border bg-card p-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (canSave) void save();
            }}
          >
            <p className="text-sm font-semibold text-foreground">
              {current ? t("admin.bands.formCurrent", { version: current.version }) : t("admin.bands.formNew")}
            </p>

            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              {t("admin.bands.serviceType")}
              <select
                value={form.service_type}
                onChange={(event) => setForm({ ...form, service_type: event.target.value as ServiceType })}
                className={FIELD}
              >
                {(Object.keys(SERVICE_OPTION_KEY) as ServiceType[]).map((value) => (
                  <option key={value} value={value}>
                    {t(SERVICE_OPTION_KEY[value])}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                {t("admin.bands.min")}
                <input value={form.floor} onChange={(event) => setForm({ ...form, floor: event.target.value })} inputMode="numeric" className={FIELD} />
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                {t("admin.bands.max")}
                <input value={form.ceiling} onChange={(event) => setForm({ ...form, ceiling: event.target.value })} inputMode="numeric" className={FIELD} />
              </label>
            </div>
            {ceilingMinor > 0 && ceilingMinor < floorMinor && (
              <p className="text-xs font-medium text-destructive">{t("admin.bands.maxBelowMin")}</p>
            )}

            <label className="flex items-start gap-2 text-sm text-secondary-foreground">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => setForm({ ...form, is_active: event.target.checked })}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                {t("admin.bands.active")}
                <span className="block text-xs text-muted-foreground">{t("admin.bands.activeHint")}</span>
              </span>
            </label>

            {/* Q90: the one switch that can refuse a negotiated price. It is deliberately loud. */}
            <label
              className={`flex items-start gap-2 rounded-[10px] border p-3 text-sm ${
                form.enforced ? "border-destructive/40 bg-destructive/10 text-destructive" : "border-border bg-slate-50 text-secondary-foreground"
              }`}
            >
              <input
                type="checkbox"
                checked={form.enforced}
                onChange={(event) => setForm({ ...form, enforced: event.target.checked })}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                <span className="flex items-center gap-1.5 font-semibold">
                  <ShieldAlert size={15} /> {t("admin.bands.enforced")}
                </span>
                <span className="mt-1 block text-xs leading-5 text-destructive">{t("admin.bands.enforcedHint")}</span>
              </span>
            </label>

            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              {t("admin.bands.reasonVisible")} *
              <input value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} className={FIELD} />
            </label>

            <button
              type="submit"
              disabled={!canSave}
              className="el-press inline-flex h-10 items-center justify-center rounded-[10px] bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? t("admin.bands.saving") : current ? t("admin.bands.saveVersion", { version: nextVersion }) : t("admin.bands.createVersion", { version: nextVersion })}
            </button>
          </form>
        ) : caps ? (
          <Note>{t("admin.bands.readOnly")}</Note>
        ) : null}

        <div className="grid content-start gap-4">
          <div className="overflow-x-auto rounded-[12px] border border-border bg-card">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">{t("admin.mk.service")}</th>
                  <th className="px-3 py-2">{t("admin.bands.scope")}</th>
                  <th className="px-3 py-2">{t("admin.bands.range")}</th>
                  <th className="px-3 py-2">{t("admin.mk.status")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-muted">
                {bands.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">
                      {t("admin.bands.empty")}
                    </td>
                  </tr>
                )}
                {bands.map((band) => (
                  <tr key={band.service_type}>
                    <td className="px-3 py-2 font-medium text-foreground">{serviceLabel(band.service_type)}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {t("admin.bands.wholeCorridor")}
                    </td>
                    <td className="px-3 py-2 text-foreground">
                      {t(band.price_basis === "per_seat" ? "admin.bands.rangePerSeat" : "admin.bands.rangeTotal", {
                        min: soum(band.floor_minor),
                        max: soum(band.ceiling_minor),
                      })}
                    </td>
                    <td className="px-3 py-2">
                      {!band.is_active ? (
                        <Badge>{t("admin.bands.disabled")}</Badge>
                      ) : band.enforced ? (
                        <Badge tone="err">{t("admin.bands.enforcedBadge")}</Badge>
                      ) : (
                        <Badge tone="blue">{t("admin.bands.advisory")}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="rounded-[12px] border border-border bg-card p-4">
            <p className="text-sm font-semibold text-foreground">{t("admin.bands.history")}</p>
            {history.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">{t("admin.bands.noHistory")}</p>
            ) : (
              <ul className="mt-2 grid gap-2 text-sm text-secondary-foreground">
                {history.map((change, index) => (
                  <li key={index} className="border-b border-muted pb-2 last:border-0 last:pb-0">
                    <span className="font-medium text-foreground">
                      {t("admin.bands.historyTitle", {
                        service: serviceLabel(change.service_type),
                        version: change.version,
                        min: soum(change.new_floor_minor),
                        max: soum(change.new_ceiling_minor),
                      })}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {formatDateTime(change.changed_at)} · {change.actor ?? "—"} · {change.reason}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
