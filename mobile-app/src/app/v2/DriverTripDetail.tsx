/**
 * T3/T10: the driver's own trip - stops, remaining capacity per segment and the manifest.
 *
 * Remaining capacity is what the server computed (AC07/AC10), not a reservation, and the screen never adds its
 * own arithmetic. The manifest shows only what the API returns: a phone number appears only when the server sends
 * it (Q44 - after the service starts; a parcel receiver's phone only after pick-up), otherwise the screen says when
 * it will appear. The three calls load independently so one failure does not hide the rest.
 */
import {
  getTrip,
  tripAvailability,
  tripManifest,
  type ManifestItemDTO,
  type TripAvailabilityDTO,
  type TripDTO,
  type TripManifestDTO,
} from "../../api/v2/safety.api";
import { translate } from "../../i18n";
import { formatDateTime, formatTime } from "../../utils/v2Format";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { Badge, Card, ErrorNote, InlineButton, Row, SkeletonCard } from "../ui/mobile";
import { useAsync } from "./useAsync";

type Tone = "progress" | "ok" | "neutral" | "warn" | "danger";

const TRIP_STATUS: Record<string, [string, Tone]> = {
  get planned(): [string, Tone] { return [translate("tripStatus.planned"), "progress"]; },
  get boarding(): [string, Tone] { return [translate("tripDetail.status.boarding"), "progress"]; },
  get in_progress(): [string, Tone] { return [translate("tripStatus.in_progress"), "ok"]; },
  get completed(): [string, Tone] { return [translate("tripStatus.completed"), "neutral"]; },
  get cancelled(): [string, Tone] { return [translate("tripStatus.cancelled"), "danger"]; },
  get interrupted(): [string, Tone] { return [translate("tripStatus.interrupted"), "warn"]; },
};

const SERVICE_STATUS: Record<string, string> = {
  get confirmed() { return translate("status.approved"); },
  get awaiting_pickup() { return translate("tripDetail.service.awaiting_pickup"); },
  get onboard() { return translate("tripDetail.service.onboard"); },
  get arrived() { return translate("tripDetail.service.arrived"); },
  get completed() { return translate("status.completed"); },
  get cancelled() { return translate("status.cancelled"); },
  get no_show() { return translate("status.no_show"); },
  get picked_up() { return translate("tripDetail.service.picked_up"); },
  get in_transit() { return translate("status.in_transit"); },
  get delivered() { return translate("tripDetail.service.delivered"); },
  get delivery_failed() { return translate("tripDetail.service.delivery_failed"); },
  get return_required() { return translate("tripDetail.service.return_required"); },
  get returned() { return translate("tripDetail.service.returned"); },
};

function kg(grams: number): string {
  return translate("tripDetail.kg", { value: (grams / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 }) });
}

function litres(ml: number): string {
  return translate("tripDetail.litres", { value: (ml / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 }) });
}

function ManifestItem({ item }: { item: ManifestItemDTO }) {
  const parcel = item.service_type === "parcel";
  return (
    <li className="rounded-[10px] bg-background px-3 py-2" data-testid="manifest-item">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[14px] font-medium text-foreground">{item.client_first_name}</span>
        <span className="text-[11px] text-muted-foreground">{SERVICE_STATUS[item.service_status] ?? item.service_status}</span>
      </div>
      <p className="text-[12px] text-muted-foreground">
        {parcel ? item.parcel_summary ?? translate("tripDetail.parcel") : translate("tripDetail.seats", { count: item.seats ?? 1 })}
      </p>
      {item.contact_phone ? (
        <a href={`tel:${item.contact_phone}`} className="text-[13px] font-semibold text-primary" data-testid="manifest-phone">
          {item.contact_phone}
        </a>
      ) : (
        <p className="text-[11px] text-muted-foreground" data-testid="manifest-phone-hidden">
          {parcel
            ? translate("tripDetail.phoneAfterPickup")
            : translate("tripDetail.phoneAfterStart")}
        </p>
      )}
    </li>
  );
}

export function DriverTripDetail(props: { tripId: string; onBack?: () => void }) {
  const trip = useAsync<TripDTO>(() => getTrip(props.tripId), [props.tripId]);
  const availability = useAsync<TripAvailabilityDTO>(() => tripAvailability(props.tripId), [props.tripId]);
  const manifest = useAsync<TripManifestDTO>(() => tripManifest(props.tripId), [props.tripId]);

  const reloadAll = () => {
    trip.reload();
    availability.reload();
    manifest.reload();
  };

  const stopName = new Map((trip.data?.stops ?? []).map((stop) => [stop.stop.id, stop.stop.name_uz]));

  return (
    <div className="flex flex-col gap-3">
      {trip.loading ? (
        <SkeletonCard lines={3} />
      ) : !trip.data ? (
        <ErrorNote message={v2ErrorMessage(trip.error)} onRetry={trip.reload} />
      ) : (
        <Card>
          <div className="flex items-center justify-between gap-2">
            <strong className="text-[15px]" data-testid="trip-route">
              {trip.data.stops[0]?.stop.name_uz ?? "-"} → {trip.data.stops[trip.data.stops.length - 1]?.stop.name_uz ?? "-"}
            </strong>
            <Badge {...badge(trip.data.status)} />
          </div>
          <Row label={translate("tripDetail.departure")} value={formatDateTime(trip.data.planned_start_at)} />
          <Row label={translate("tripDetail.arrival")} value={formatDateTime(trip.data.planned_end_at)} />
          <Row
            label={translate("tripDetail.vehicle")}
            value={`${trip.data.vehicle.make_model}, ${trip.data.vehicle.color} · ${trip.data.vehicle.plate_masked}`}
          />
          <Row label={translate("tripDetail.seatsLabel")} value={translate("tripDetail.seatsValue", { count: trip.data.seat_capacity })} />
          <Row
            label={translate("tripDetail.cutoffLabel")}
            value={translate("tripDetail.cutoffValue", { time: formatDateTime(trip.data.booking_cutoff_at) })}
          />
          <ol className="mt-1 flex flex-col gap-1">
            {trip.data.stops.map((stop) => (
              <li key={stop.seq} className="flex justify-between gap-2 text-[13px]">
                <span className="text-foreground">{stop.stop.name_uz}</span>
                <span className="text-muted-foreground">{formatTime(stop.eta_arrival_at ?? stop.planned_arrival_at)}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <Card>
        <strong className="text-[15px]">{translate("tripDetail.availabilityTitle")}</strong>
        {availability.loading ? (
          <SkeletonCard lines={2} />
        ) : !availability.data ? (
          <ErrorNote message={v2ErrorMessage(availability.error)} onRetry={availability.reload} />
        ) : availability.data.segments.length === 0 ? (
          <p className="text-[13px] text-muted-foreground" data-testid="availability-empty">{translate("tripDetail.availabilityEmpty")}</p>
        ) : (
          <>
            <ul className="flex flex-col gap-1.5" data-testid="availability-list">
              {availability.data.segments.map((segment) => (
                <li key={`${segment.from_seq}-${segment.to_seq}`} className="rounded-[10px] bg-background px-3 py-2">
                  <p className="text-[13px] font-medium text-foreground">
                    {stopName.get(segment.from_stop_id) ?? translate("tripDetail.stopSeq", { seq: segment.from_seq })} →{" "}
                    {stopName.get(segment.to_stop_id) ?? translate("tripDetail.stopSeq", { seq: segment.to_seq })}
                  </p>
                  <p className="text-[12px] text-muted-foreground">
                    {translate("tripDetail.segmentLine", {
                      seats: segment.seats_remaining,
                      weight: kg(segment.cargo_remaining_weight_g),
                      volume: litres(segment.cargo_remaining_volume_ml),
                      baggage: litres(segment.baggage_remaining_ml),
                    })}
                  </p>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-muted-foreground">
              {translate("tripDetail.computedNote", { time: formatDateTime(availability.data.computed_at) })}
            </p>
          </>
        )}
      </Card>

      <Card>
        <strong className="text-[15px]">{translate("tripDetail.manifestTitle")}</strong>
        {manifest.loading ? (
          <SkeletonCard lines={2} />
        ) : !manifest.data ? (
          <ErrorNote message={v2ErrorMessage(manifest.error)} onRetry={manifest.reload} />
        ) : manifest.data.stops.every((stop) => stop.pickups.length === 0 && stop.dropoffs.length === 0) ? (
          <p className="text-[13px] text-muted-foreground" data-testid="manifest-empty">{translate("tripDetail.manifestEmpty")}</p>
        ) : (
          manifest.data.stops
            .filter((stop) => stop.pickups.length || stop.dropoffs.length)
            .map((stop) => (
              <section key={stop.seq} className="flex flex-col gap-1.5">
                <p className="text-[13px] font-semibold text-secondary-foreground">
                  {stop.stop?.name_uz ?? stop.point?.address ?? stop.point?.district?.name_uz ?? translate("tripDetail.agreedPoint")} ·{" "}
                  {formatTime(stop.planned_arrival_at)}
                </p>
                {stop.pickups.length ? (
                  <>
                    <p className="text-[11px] font-semibold text-muted-foreground">{translate("tripDetail.pickups")}</p>
                    <ul className="flex flex-col gap-1.5">
                      {stop.pickups.map((item) => (
                        <ManifestItem key={`p-${item.booking_id}`} item={item} />
                      ))}
                    </ul>
                  </>
                ) : null}
                {stop.dropoffs.length ? (
                  <>
                    <p className="text-[11px] font-semibold text-muted-foreground">{translate("tripDetail.dropoffs")}</p>
                    <ul className="flex flex-col gap-1.5">
                      {stop.dropoffs.map((item) => (
                        <ManifestItem key={`d-${item.booking_id}`} item={item} />
                      ))}
                    </ul>
                  </>
                ) : null}
              </section>
            ))
        )}
      </Card>

      <div className="flex gap-2">
        <InlineButton onClick={reloadAll}>{translate("tripDetail.refresh")}</InlineButton>
        {props.onBack ? <InlineButton onClick={props.onBack}>{translate("common.back")}</InlineButton> : null}
      </div>
    </div>
  );
}

function badge(status: string): { text: string; tone: Tone } {
  const [text, tone] = TRIP_STATUS[status] ?? [status, "neutral"];
  return { text, tone };
}
