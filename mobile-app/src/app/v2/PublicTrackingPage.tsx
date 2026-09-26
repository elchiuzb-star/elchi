/**
 * K7: the page a recipient opens from a tracking link. No login, no identity, nothing but what the API returns.
 *
 * Honesty rules (§9, §10.4): the position is called live only while the server says `fresh` **and** the last point
 * is still young on this device's clock - a page left open never keeps saying "live" after the phone went quiet.
 * A delayed or lost signal is named as such with the age of the last point; no point means no marker at all.
 * An unknown, revoked or expired link and a closed tracking window are the same "not available" (no difference is
 * revealed).
 */
import { useEffect, useState } from "react";

import { publicTracking, type PublicTrackingDTO, type TrackingFreshness } from "../../api/v2/safety.api";
import { publicSubscribeFrame } from "../../api/v2/tracking.api";
import { effectiveFreshness as sharedEffectiveFreshness } from "../gpsOutbox";
import { formatDateTime, minutesSince } from "../../utils/v2Format";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { Badge, COLORS, Card, ErrorNote, Loading, Row, ScreenBody } from "../ui/mobile";
import { VehicleMap } from "./LiveTrackingMap";
import { useLiveTracking, type LiveTrackingOptions } from "./useLiveTracking";
import { translate } from "../../i18n";

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

/**
 * The freshness shown on screen: the server's bucket, only ever made *worse* by the age of the last point on this
 * device's clock. Never better than the server said (§10.4 buckets: <=30 s fresh, 31-120 s delayed, >120 s lost).
 */
export function effectiveFreshness(data: PublicTrackingDTO, now: Date = new Date()): TrackingFreshness {
  return sharedEffectiveFreshness(data, now);
}

const FRESHNESS_TEXT: Record<TrackingFreshness, [string, "ok" | "warn" | "danger" | "neutral"]> = {
  get fresh(): [string, "ok"] { return [translate("publicTracking.fresh"), "ok"]; },
  get delayed(): [string, "warn"] { return [translate("publicTracking.delayed"), "warn"]; },
  get lost(): [string, "danger"] { return [translate("publicTracking.lost"), "danger"]; },
  get no_data(): [string, "neutral"] { return [translate("publicTracking.noData"), "neutral"]; },
};

export function PublicTrackingPage({
  token,
  now,
  socketFactory,
}: {
  token: string;
  now?: () => Date;
  /** Tests pass `null` (no socket); the page itself uses the browser's WebSocket. */
  socketFactory?: LiveTrackingOptions<PublicTrackingDTO>["socketFactory"];
}) {
  // K8 with the link token; K7 polling whenever the socket is not open (§10.3 step 5).
  const [attempt, setAttempt] = useState(0);
  const live = useLiveTracking<PublicTrackingDTO>({
    subject: `${token}#${attempt}`,
    fetchSnapshot: () => publicTracking(token),
    subscribeFrame: () => publicSubscribeFrame(token),
    windowOpen: (value) => value.last_point != null,
    socketFactory,
  });
  // Re-evaluate the age of the last point between server updates, so "live" turns into "delayed" on its own.
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 5_000);
    return () => window.clearInterval(timer);
  }, []);
  const page = { data: live.data, error: live.error, loading: !live.data && !live.error && !live.gone };

  if (page.loading) {
    return (
      <ScreenBody>
        <Loading />
      </ScreenBody>
    );
  }
  // A link that expired or was revoked while the page was open stops showing the old position.
  const notFound = live.gone;
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
          <ErrorNote message={page.error ? v2ErrorMessage(page.error) : null} onRetry={() => setAttempt((value) => value + 1)} />
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
            <VehicleMap point={point} live={freshness === "fresh"} />
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
