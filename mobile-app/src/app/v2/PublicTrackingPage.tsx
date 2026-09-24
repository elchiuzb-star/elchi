/**
 * K7: the page a recipient opens from a tracking link. No login, no identity, nothing but what the API returns.
 *
 * Honesty rules (§9, §10.4): the position is called live only while the server says `fresh` **and** the last point
 * is still young on this device's clock - a page left open never keeps saying "live" after the phone went quiet.
 * A delayed or lost signal is named as such with the age of the last point; no point means no marker at all.
 * An unknown, revoked or expired link and a closed tracking window are the same "not available" (no difference is
 * revealed).
 */
import { useEffect } from "react";

import { publicTracking, type PublicTrackingDTO, type TrackingFreshness } from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { formatDateTime, minutesSince } from "../../utils/v2Format";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { Badge, COLORS, Card, ErrorNote, Loading, Row, ScreenBody } from "../ui/mobile";
import { useAsync } from "./useAsync";
import { translate } from "../../i18n";

/** §10.4 buckets: <=30 s fresh, 31-120 s delayed, >120 s lost. */
const FRESH_MAX_S = 30;
const DELAYED_MAX_S = 120;
const REFRESH_MS = 30_000;

const STATUS_TEXT: Record<string, string> = {
  get "passenger.confirmed"() { return translate("publicTracking.status.passengerConfirmed"); },
  get "passenger.awaiting_pickup"() { return translate("publicTracking.status.passengerAwaitingPickup"); },
  get "passenger.onboard"() { return translate("publicTracking.status.passengerOnboard"); },
  get "passenger.arrived"() { return translate("publicTracking.status.passengerArrived"); },
  get "passenger.completed"() { return translate("publicTracking.status.passengerCompleted"); },
  get "parcel.confirmed"() { return translate("publicTracking.status.parcelConfirmed"); },
  get "parcel.awaiting_pickup"() { return translate("publicTracking.status.parcelAwaitingPickup"); },
  get "parcel.picked_up"() { return translate("publicTracking.status.parcelPickedUp"); },
  get "parcel.in_transit"() { return translate("publicTracking.status.parcelInTransit"); },
  get "parcel.delivery_failed"() { return translate("publicTracking.status.parcelDeliveryFailed"); },
  get "parcel.delivered"() { return translate("publicTracking.status.parcelDelivered"); },
  get "parcel.return_required"() { return translate("publicTracking.status.parcelReturnRequired"); },
  get "parcel.returned"() { return translate("publicTracking.status.parcelReturned"); },
  get "parcel.completed"() { return translate("publicTracking.status.parcelCompleted"); },
};

export function statusText(label: string): string {
  return STATUS_TEXT[label] ?? translate("publicTracking.status.active");
}

const RANK: Record<TrackingFreshness, number> = { fresh: 0, delayed: 1, lost: 2, no_data: 3 };

/**
 * The freshness shown on screen: the server's bucket, only ever made *worse* by the age of the last point on this
 * device's clock. Never better than the server said.
 */
export function effectiveFreshness(data: PublicTrackingDTO, now: Date = new Date()): TrackingFreshness {
  if (!data.last_point) return "no_data";
  const age = (now.getTime() - new Date(data.last_point.captured_at).getTime()) / 1000;
  const local: TrackingFreshness = age <= FRESH_MAX_S ? "fresh" : age <= DELAYED_MAX_S ? "delayed" : "lost";
  return RANK[local] > RANK[data.freshness] ? local : data.freshness;
}

const FRESHNESS_TEXT: Record<TrackingFreshness, [string, "ok" | "warn" | "danger" | "neutral"]> = {
  get fresh(): [string, "ok"] { return [translate("publicTracking.fresh"), "ok"]; },
  get delayed(): [string, "warn"] { return [translate("publicTracking.delayed"), "warn"]; },
  get lost(): [string, "danger"] { return [translate("publicTracking.lost"), "danger"]; },
  get no_data(): [string, "neutral"] { return [translate("publicTracking.noData"), "neutral"]; },
};

export function PublicTrackingPage({ token, now }: { token: string; now?: () => Date }) {
  const page = useAsync<PublicTrackingDTO>(() => publicTracking(token), [token]);
  const reload = page.reload;

  useEffect(() => {
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  if (page.loading) {
    return (
      <ScreenBody>
        <Loading />
      </ScreenBody>
    );
  }
  // A link that expired or was revoked while the page was open stops showing the old position.
  const notFound = page.error instanceof ApiError && page.error.status === 404;
  if (!page.data || notFound) {
    return (
      <ScreenBody>
        {notFound ? (
          <Card>
            <strong>{translate("publicTracking.unavailableTitle")}</strong>
            <span style={{ fontSize: 14, color: COLORS.muted }} data-testid="tracking-unavailable">
              {translate("publicTracking.unavailableBody")}
            </span>
          </Card>
        ) : (
          <ErrorNote message={page.error ? v2ErrorMessage(page.error) : null} onRetry={page.reload} />
        )}
      </ScreenBody>
    );
  }

  const data = page.data;
  const current = now ? now() : new Date();
  const freshness = effectiveFreshness(data, current);
  const [freshLabel, tone] = FRESHNESS_TEXT[freshness];
  const point = data.last_point;
  const ageMinutes = point ? minutesSince(point.captured_at, current) : null;

  return (
    <ScreenBody>
      <Card>
        <span style={{ fontSize: 12, color: COLORS.muted }}>{translate("publicTracking.vehicleTitle")}</span>
        <div className="flex items-center justify-between gap-2">
          <strong data-testid="tracking-status">{statusText(data.status_label)}</strong>
          <Badge text={freshLabel} tone={tone} />
        </div>
      </Card>

      <Card>
        {point ? (
          <>
            <Row label={translate("publicTracking.lastPosition")} value={formatDateTime(point.captured_at)} />
            <Row
              label={translate("publicTracking.howLongAgo")}
              value={
                ageMinutes !== null && ageMinutes < 1
                  ? translate("publicTracking.lessThanMinute")
                  : translate("publicTracking.minutesAgo", { minutes: String(ageMinutes) })
              }
            />
            <Row label={translate("publicTracking.coordinates")} value={`${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`} />
            <Row label={translate("publicTracking.accuracy")} value={`±${point.accuracy_m} m`} />
            {point.low_accuracy ? (
              <span style={{ fontSize: 12, color: COLORS.muted }}>{translate("publicTracking.lowAccuracy")}</span>
            ) : null}
            {freshness === "delayed" ? (
              <span style={{ fontSize: 13, color: COLORS.muted }} data-testid="tracking-stale">
                {translate("publicTracking.delayedHint")}
              </span>
            ) : null}
            {freshness === "lost" ? (
              <span style={{ fontSize: 13, color: COLORS.muted }} data-testid="tracking-stale">
                {translate("publicTracking.lostHint")}
              </span>
            ) : null}
          </>
        ) : (
          <span style={{ fontSize: 14, color: COLORS.muted }} data-testid="tracking-no-point">
            {translate("publicTracking.noPointHint")}
          </span>
        )}
      </Card>

      <span style={{ fontSize: 12, color: COLORS.muted }}>
        {translate("publicTracking.sourceNote")}
      </span>
    </ScreenBody>
  );
}
