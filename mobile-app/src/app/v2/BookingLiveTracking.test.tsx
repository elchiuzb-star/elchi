/**
 * K4 + K8 viewer: the WebSocket moves the marker, a closed window falls back to the server's reason, a revoked
 * subject stops, and a stale point is never called live. SYNTHETIC data.
 */
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/bookings.api", () => ({ getBookingTracking: vi.fn() }));

import * as api from "../../api/v2/bookings.api";
import type { BookingTrackingDTO } from "../../api/v2/bookings.api";
import { BookingLiveTracking } from "./BookingLiveTracking";

const m = vi.mocked(api);

function dto(ageSeconds: number | null, patch: Partial<BookingTrackingDTO> = {}): BookingTrackingDTO {
  const at = ageSeconds === null ? null : new Date(Date.now() - ageSeconds * 1000).toISOString();
  return {
    booking_id: "bkg_1",
    window: { is_open: true, reason: "open" },
    freshness: ageSeconds === null ? "no_data" : "fresh",
    last_point: at ? { lat: 41.31, lng: 69.28, accuracy_m: 9, low_accuracy: false, captured_at: at, received_at: at } : null,
    eta_is_estimate: true,
    subject_label: "vehicle_carrying_your_booking",
    ...patch,
  } as BookingTrackingDTO;
}

class FakeSocket {
  static last: FakeSocket | null = null;
  sent: string[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  constructor(public url: string) {
    FakeSocket.last = this;
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {}
  open() {
    this.onopen?.(new Event("open"));
  }
  push(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
  shut(code: number) {
    this.onclose?.({ code } as CloseEvent);
  }
}

const factory = (url: string) => new FakeSocket(url);

beforeEach(() => {
  vi.resetAllMocks();
  FakeSocket.last = null;
});

describe("BookingLiveTracking", () => {
  it("subscribes over the WebSocket with the booking id and follows the pushed point", async () => {
    m.getBookingTracking.mockResolvedValue(dto(null));
    render(
      <BookingLiveTracking bookingId="bkg_1" initial={dto(null)} trackingEnabled windowText={(r) => r} socketFactory={factory} />,
    );
    expect(screen.getByTestId("live-no-point")).toBeInTheDocument();
    const socket = FakeSocket.last!;
    expect(socket.url).toMatch(/^wss?:\/\/.+\/api\/v2\/ws$/);
    act(() => socket.open());
    expect(JSON.parse(socket.sent[0])).toMatchObject({ action: "subscribe", booking_id: "bkg_1" });
    act(() => socket.push({ type: "tracking.point", booking_id: "bkg_1", data: dto(3) }));
    expect(await screen.findByTestId("vehicle-map")).toBeInTheDocument();
    expect(screen.getByTestId("live-freshness").textContent).toBe("Jonli joylashuv");
  });

  it("never calls an old point live, whatever the server's bucket said", () => {
    m.getBookingTracking.mockResolvedValue(dto(400));
    render(<BookingLiveTracking bookingId="bkg_1" initial={dto(400)} trackingEnabled windowText={(r) => r} socketFactory={null} />);
    expect(screen.getByTestId("live-freshness").textContent).toBe("Haydovchi telefoni bilan aloqa uzilgan");
    expect(screen.getByTestId("live-stale")).toBeInTheDocument();
  });

  it("shows the server's window reason when the window is closed", async () => {
    const closed = dto(null, { window: { is_open: false, reason: "not_yet_open" } as BookingTrackingDTO["window"] });
    m.getBookingTracking.mockResolvedValue(closed);
    render(<BookingLiveTracking bookingId="bkg_1" initial={closed} trackingEnabled windowText={(r) => `reason:${r}`} socketFactory={null} />);
    expect(screen.getByText("reason:not_yet_open")).toBeInTheDocument();
  });

  it("stops when the server says the booking is not visible (4404)", async () => {
    m.getBookingTracking.mockResolvedValue(dto(3));
    render(<BookingLiveTracking bookingId="bkg_1" initial={dto(3)} trackingEnabled windowText={(r) => r} socketFactory={factory} />);
    act(() => FakeSocket.last!.shut(4404));
    expect(await screen.findByText("Bu bron uchun jonli joylashuv endi mavjud emas.")).toBeInTheDocument();
  });

  it("does nothing while tracking is switched off for the corridor", () => {
    render(<BookingLiveTracking bookingId="bkg_1" initial={null} trackingEnabled={false} windowText={(r) => r} socketFactory={factory} />);
    expect(FakeSocket.last).toBeNull();
    expect(m.getBookingTracking).not.toHaveBeenCalled();
  });
});
