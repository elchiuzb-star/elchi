/** Q148 driver bar: honest status words, no "GPS faol", and the right action per state. SYNTHETIC data. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DriverTrackingBar } from "./DriverTrackingBar";
import type { DriverTracker, TrackerSnapshot } from "./driverTracker";

const BASE: TrackerSnapshot = {
  phase: "idle",
  tripId: null,
  sessionId: null,
  queued: 0,
  dropped: 0,
  lastFixAt: null,
  lastAccuracyM: null,
  lastSentAt: null,
  hidden: false,
  offline: false,
  wakeLock: true,
  permission: "granted",
  unavailableReason: null,
  battery: null,
  lastGap: null,
  gapCount: 0,
  errorCode: null,
  endReason: null,
};

function fake(patch: Partial<TrackerSnapshot>) {
  const snapshot = { ...BASE, ...patch };
  return {
    subscribe: () => () => undefined,
    getSnapshot: () => snapshot,
    start: vi.fn(async () => undefined),
    stop: vi.fn(async () => undefined),
  } as unknown as DriverTracker & { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
}

describe("DriverTrackingBar", () => {
  it("is absent without a running trip", () => {
    const { container } = render(<DriverTrackingBar tripId={null} tracker={fake({})} />);
    expect(container.firstChild).toBeNull();
  });

  it("asks the driver to switch it on for a running trip", () => {
    const tracker = fake({});
    render(<DriverTrackingBar tripId="trp_1" tracker={tracker} />);
    fireEvent.click(screen.getByText("Yoqish"));
    expect(tracker.start).toHaveBeenCalledWith("trp_1");
    expect(screen.getByText("Joylashuv faqat ilova ochiq va ekran yoniq turganda yuboriladi.")).toBeInTheDocument();
  });

  it("says 'sending' only with a recent fix, and counts queued and lost points", () => {
    render(
      <DriverTrackingBar
        tripId="trp_1"
        tracker={fake({ phase: "active", tripId: "trp_1", lastFixAt: Date.now() - 5_000, queued: 3, offline: true, dropped: 2, hidden: true })}
      />,
    );
    expect(screen.getByTestId("driver-tracking-title").textContent).toBe("Joylashuv yuborilmoqda");
    expect(screen.getByText(/3 ta nuqta telefonda kutmoqda/)).toBeInTheDocument();
    expect(screen.getByText(/2 ta nuqta serverga yetib bormadi/)).toBeInTheDocument();
    expect(screen.getByText(/Ilova fonda/)).toBeInTheDocument();
    expect(screen.queryByText(/GPS faol/)).toBeNull();
  });

  it("does not say 'sending' when the phone has been quiet", () => {
    render(<DriverTrackingBar tripId="trp_1" tracker={fake({ phase: "active", tripId: "trp_1", lastFixAt: Date.now() - 90_000 })} />);
    expect(screen.getByTestId("driver-tracking-title").textContent).toMatch(/^Yangi joylashuv yo'q/);
  });

  it("offers to take over when another device publishes", () => {
    const tracker = fake({ phase: "ended", endReason: "superseded", tripId: "trp_1" });
    render(<DriverTrackingBar tripId="trp_1" tracker={tracker} />);
    expect(screen.getByTestId("driver-tracking-title").textContent).toBe("Joylashuv boshqa qurilma yoki oynadan yuborilmoqda");
    fireEvent.click(screen.getByText("Shu telefondan yuborish"));
    expect(tracker.start).toHaveBeenCalledWith("trp_1");
  });

  it("explains a denied permission", () => {
    render(<DriverTrackingBar tripId="trp_1" tracker={fake({ phase: "permission_denied", tripId: "trp_1" })} />);
    expect(screen.getByText("Joylashuvga ruxsat berilmagan")).toBeInTheDocument();
  });
});

describe("DriverTrackingBar device conditions", () => {
  it("says why a page without HTTPS cannot publish", () => {
    render(<DriverTrackingBar tripId="trp_1" tracker={fake({ phase: "unavailable", unavailableReason: "insecure" })} />);
    expect(screen.getByTestId("driver-tracking-title").textContent).toMatch(/HTTPS/);
  });

  it("warns about a low battery, a gap, a stalled GPS and a screen that may lock", () => {
    const now = Date.now();
    render(
      <DriverTrackingBar
        tripId="trp_1"
        tracker={fake({
          phase: "active",
          tripId: "trp_1",
          lastFixAt: now - 70_000,
          battery: { pct: 12, charging: false },
          lastGap: { from: now - 600_000, to: now - 300_000, cause: "background" },
          wakeLock: false,
        })}
      />,
    );
    expect(screen.getByText(/Batareya 12%/)).toBeInTheDocument();
    expect(screen.getByText(/ekran qulflangan yoki ilova fonda edi/)).toBeInTheDocument();
    expect(screen.getByText(/1 daqiqadan beri joylashuv bermayapti/)).toBeInTheDocument();
    expect(screen.getByText(/Ekran o'zi o'chib qolishi mumkin/)).toBeInTheDocument();
  });

  it("tells the driver to answer the browser's permission question", () => {
    render(<DriverTrackingBar tripId="trp_1" tracker={fake({ permission: "prompt" })} />);
    expect(screen.getByText(/«Ruxsat berish»ni tanlang/)).toBeInTheDocument();
  });
});
