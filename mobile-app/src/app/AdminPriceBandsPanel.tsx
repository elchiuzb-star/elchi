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
 * Scope: a band is either corridor-wide (a loose safety range for the whole direction) or for one exact stop
 * pair (the real range for that segment). The segment one wins when both exist (Q53).
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
import { v2ErrorMessage } from "../utils/v2Errors";

type ServiceType = "passenger" | "parcel";

const SERVICE_LABELS: Record<ServiceType, string> = {
  passenger: "Yo'lovchi",
  parcel: "Yuk",
};

function soum(minor: number): string {
  return new Intl.NumberFormat("uz-UZ").format(Math.round(minor / 100));
}

function toMinor(value: string): number {
  const parsed = Math.round(Number(value.replace(/\s/g, "")));
  return Number.isFinite(parsed) && parsed > 0 ? parsed * 100 : 0;
}

export function AdminPriceBandsPanel() {
  const [corridors, setCorridors] = useState<CorridorDTO[]>([]);
  const [corridorId, setCorridorId] = useState("");
  const [bands, setBands] = useState<PriceBandDTO[]>([]);
  const [history, setHistory] = useState<PriceBandChangeDTO[]>([]);
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

  useEffect(() => {
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
    () => bands.find((band) => band.service_type === form.service_type && !band.origin_stop_id) ?? null,
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
    Boolean(corridorId) && floorMinor > 0 && ceilingMinor >= floorMinor && form.reason.trim().length > 0 && !busy;

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
      setWarnings(result.warnings.map((warning) => warning.message || warning.code));
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
          <h2 className="text-lg font-bold text-foreground">Narx referensi</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Diapazon <strong>narx belgilamaydi</strong>. U saralashga kiradi va odatdan tashqari taklifga
            ogohlantirish qo&apos;yadi; narxni mijoz va haydovchi kelishadi. Faqat «qat&apos;iy chegara»
            yoqilgan diapazon taklifni rad etadi.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void reload()}
          disabled={busy}
          className="el-press inline-flex h-10 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground disabled:opacity-50"
        >
          <RefreshCw size={16} /> Yangilash
        </button>
      </header>

      {error && (
        <p className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
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
        Koridor
        <select
          value={corridorId}
          onChange={(event) => setCorridorId(event.target.value)}
          className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
        >
          {corridors.map((corridor) => (
            <option key={corridor.id} value={corridor.id}>
              {corridor.name}
            </option>
          ))}
        </select>
      </label>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <form
          className="grid gap-3 rounded-[12px] border border-border bg-card p-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSave) void save();
          }}
        >
          <p className="text-sm font-semibold text-foreground">
            Koridor bo&apos;yicha diapazon {current ? `(v${current.version})` : "(yangi)"}
          </p>

          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            Xizmat turi
            <select
              value={form.service_type}
              onChange={(event) => setForm({ ...form, service_type: event.target.value as ServiceType })}
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            >
              {(Object.keys(SERVICE_LABELS) as ServiceType[]).map((value) => (
                <option key={value} value={value}>
                  {SERVICE_LABELS[value]}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-muted-foreground">
              Yo&apos;lovchi — bir o&apos;rin narxi; yuk — yetkazish jami.
            </span>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              Quyi chegara (so&apos;m)
              <input
                value={form.floor}
                onChange={(event) => setForm({ ...form, floor: event.target.value })}
                inputMode="numeric"
                className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              Yuqori chegara (so&apos;m)
              <input
                value={form.ceiling}
                onChange={(event) => setForm({ ...form, ceiling: event.target.value })}
                inputMode="numeric"
                className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
              />
            </label>
          </div>
          {ceilingMinor > 0 && ceilingMinor < floorMinor && (
            <p className="text-xs font-medium text-destructive">Yuqori chegara quyi chegaradan kichik bo&apos;la olmaydi.</p>
          )}

          <label className="flex items-start gap-2 text-sm text-secondary-foreground">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(event) => setForm({ ...form, is_active: event.target.checked })}
              className="mt-0.5 h-4 w-4"
            />
            <span>
              Faol
              <span className="block text-xs text-muted-foreground">O&apos;chirilgan diapazon saralashga ham kirmaydi.</span>
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
                <ShieldAlert size={15} /> Qat&apos;iy chegara (taklifni rad etadi)
              </span>
              <span className="mt-1 block text-xs leading-5">
                Odatda <strong>o&apos;chiq</strong> bo&apos;ladi. Yoqilsa, bu diapazondan tashqari har qanday
                taklif va qarshi taklif <code>400 PRICE_OUT_OF_BAND</code> bilan rad etiladi — ya&apos;ni
                kelishuvning o&apos;zi bloklanadi. Faqat suiiste&apos;mol yoki xavfsizlik holati uchun.
              </span>
            </span>
          </label>

          <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
            Sabab
            <input
              value={form.reason}
              onChange={(event) => setForm({ ...form, reason: event.target.value })}
              placeholder="Auditda ko'rinadi"
              className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            />
          </label>

          <button
            type="submit"
            disabled={!canSave}
            className="el-press inline-flex h-10 items-center justify-center rounded-[10px] bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Saqlanmoqda..." : current ? "Yangilash" : "Yaratish"}
          </button>
        </form>

        <div className="grid gap-4">
          <div className="overflow-hidden rounded-[12px] border border-border bg-card">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Xizmat</th>
                  <th className="px-3 py-2">Doira</th>
                  <th className="px-3 py-2">Diapazon</th>
                  <th className="px-3 py-2">Holat</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-muted">
                {bands.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">
                      Bu koridorda diapazon yo&apos;q — taklif narxlari cheklanmaydi va saralashda narx
                      komponenti neytral (0.5) bo&apos;ladi.
                    </td>
                  </tr>
                )}
                {bands.map((band) => (
                  <tr key={`${band.service_type}-${band.origin_stop_id ?? "corridor"}`}>
                    <td className="px-3 py-2 font-medium text-foreground">{SERVICE_LABELS[band.service_type as ServiceType]}</td>
                    <td className="px-3 py-2 text-muted-foreground">{band.origin_stop_id ? "Segment" : "Butun koridor"}</td>
                    <td className="px-3 py-2 text-foreground">
                      {soum(band.floor_minor)} – {soum(band.ceiling_minor)} so&apos;m
                      <span className="block text-xs text-muted-foreground">
                        {band.price_basis === "per_seat" ? "bir o'rin uchun" : "jami"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {!band.is_active ? (
                        <span className="inline-flex rounded-full bg-muted px-2.5 py-1 text-xs font-semibold text-muted-foreground">
                          O&apos;chirilgan
                        </span>
                      ) : band.enforced ? (
                        <span className="inline-flex rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-semibold text-destructive">
                          Qat&apos;iy chegara
                        </span>
                      ) : (
                        <span className="inline-flex rounded-full bg-success/12 px-2.5 py-1 text-xs font-semibold text-success">
                          Maslahat
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="rounded-[12px] border border-border bg-card p-4">
            <p className="text-sm font-semibold text-foreground">O&apos;zgarishlar tarixi</p>
            {history.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">Hozircha o&apos;zgarish yo&apos;q.</p>
            ) : (
              <ul className="mt-2 grid gap-2 text-sm text-secondary-foreground">
                {history.map((change, index) => (
                  <li key={index} className="border-b border-muted pb-2 last:border-0 last:pb-0">
                    <span className="font-medium text-foreground">
                      {SERVICE_LABELS[change.service_type as ServiceType]} v{change.version}
                    </span>{" "}
                    {soum(change.new_floor_minor)} – {soum(change.new_ceiling_minor)} so&apos;m
                    <span className="block text-xs text-muted-foreground">
                      {new Date(change.changed_at).toLocaleString("uz-UZ")} · {change.actor ?? "—"} · {change.reason}
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
