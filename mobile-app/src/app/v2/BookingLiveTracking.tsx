/**
 * K4 + K8 for a booking participant: the live card of the booking tracking screen.
 *
 * The first snapshot is the one the screen already loaded; after that the WebSocket pushes updates and the HTTP
 * snapshot is polled while the socket is down. The window rule is the server's (passenger: 30 minutes before
 * pickup; parcel: from departure, Q142) - this card only renders its answer.
 */
import { useEffect, useState } from "react";

import { getBookingTracking, type BookingTrackingDTO } from "../../api/v2/bookings.api";
import { bookingSubscribeFrame } from "../../api/v2/tracking.api";
import { translate } from "../../i18n";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { LiveTrackingMap } from "./LiveTrackingMap";
import { useLiveTracking, type LiveTrackingOptions } from "./useLiveTracking";

export function BookingLiveTracking(props: {
  bookingId: string;
  initial: BookingTrackingDTO | null;
  trackingEnabled: boolean;
  windowText: (reason: string) => string;
  pickup?: { lat: number; lng: number } | null;
  socketFactory?: LiveTrackingOptions<BookingTrackingDTO>["socketFactory"];
}) {
  const live = useLiveTracking<BookingTrackingDTO>({
    subject: props.bookingId,
    enabled: props.trackingEnabled,
    initial: props.initial,
    fetchSnapshot: () => getBookingTracking(props.bookingId),
    subscribeFrame: () => bookingSubscribeFrame(props.bookingId),
    windowOpen: (value) => value.window.is_open,
    socketFactory: props.socketFactory,
  });
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 5_000);
    return () => window.clearInterval(timer);
  }, []);

  if (!props.trackingEnabled) {
    return <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{translate("bookingTracking.liveDisabled")}</p>;
  }
  if (live.gone) {
    return <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{translate("liveTracking.gone")}</p>;
  }
  const data = live.data;
  if (!data) {
    return (
      <p className="mt-1 text-[13px] text-muted-foreground">
        {live.error ? v2ErrorMessage(live.error) : translate("common.loading")}
      </p>
    );
  }
  if (!data.window.is_open) {
    return <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{props.windowText(data.window.reason)}</p>;
  }
  return (
    <div className="mt-2">
      <LiveTrackingMap data={data} pickup={props.pickup} transport={live.transport} now={now} />
    </div>
  );
}
