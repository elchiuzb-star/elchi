/**
 * ADR-0027: what drivers said they drive (`GET /admin/driver-directions`, `ops.view`, read-only).
 *
 * A direction is two ends and a car - no time, stop or corridor. Trips are made from it by the system when the driver
 * offers on a client request, so the panel shows each direction with the trip it currently runs. Nothing here changes
 * a direction: a driver pauses or removes their own; staff act on the trips and bookings in their own panels.
 */
import { useCallback, useEffect, useState } from "react";

import { adminListDirections, type AdminDriverDirectionDTO } from "../api/v2/directions.api";
import { translate, translateDynamic } from "../i18n";
import { useT } from "../i18n/react";
import { v2ErrorMessage } from "../utils/v2Errors";
import { formatDateTime } from "../utils/v2Format";
import { Badge, Btn, Note, PanelHead } from "./adminMarketKit";
import { directionEndName } from "./directionFeed";
import { RefreshCw } from "./ui/icons";

const STATUS_TONE = { active: "ok", paused: "warn", archived: "gray" } as const;

function statusLabel(status: AdminDriverDirectionDTO["status"]): string {
  if (status === "active") return translate("dir.statusActive");
  if (status === "paused") return translate("dir.statusPaused");
  return translate("admin.dir.archivedStatus");
}

export function AdminDirectionsPanel() {
  useT();
  const [rows, setRows] = useState<AdminDriverDirectionDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setRows(await adminListDirections({ limit: 100 }));
    } catch (err) {
      setError(v2ErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="space-y-4">
      <PanelHead
        title={translate("admin.dir.title")}
        sub={translate("admin.dir.hint")}
        actions={
          <Btn onClick={() => void load()} disabled={busy} label={translate("admin.dir.refresh")}>
            <RefreshCw size={16} />
          </Btn>
        }
      />
      {error && <Note tone="warn">{error}</Note>}
      {!busy && rows.length === 0 && !error && <Note>{translate("admin.dir.empty")}</Note>}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-[14px] border border-border bg-card">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">{translate("admin.dir.driver")}</th>
                <th className="px-4 py-3">{translate("admin.dir.ends")}</th>
                <th className="px-4 py-3">{translate("admin.dir.trip")}</th>
                <th className="px-4 py-3">{translate("admin.dir.status")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-border align-top" data-testid="admin-direction">
                  <td className="px-4 py-3 font-semibold text-foreground">{row.driver_display_name ?? row.driver_id}</td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-foreground">
                      {directionEndName(row.origin)} {"->"} {directionEndName(row.destination)}
                    </p>
                    {(row.via_district_names ?? []).length > 0 && (
                      <p className="text-xs text-muted-foreground">{translate("dir.via", { names: (row.via_district_names ?? []).join(", ") })}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {translate("dir.capacity", { seats: row.seat_capacity, kg: Math.round(row.cargo_capacity_weight_g / 1000) })}
                    </p>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {row.active_trip ? `${formatDateTime(row.active_trip.planned_start_at)} · ${translateDynamic(`tripStatus.${row.active_trip.status}`) ?? row.active_trip.status} · ${translate("dir.seatsBooked", { seats: row.active_trip.seats_booked })}` : "-"}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={STATUS_TONE[row.status]}>{statusLabel(row.status)}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
