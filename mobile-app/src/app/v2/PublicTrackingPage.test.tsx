/**
 * K7 public tracking page: loading, not-found, error, and the §9 rule that stale GPS is never called live.
 * SYNTHETIC data.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/safety.api", () => ({ publicTracking: vi.fn() }));

import * as api from "../../api/v2/safety.api";
import type { PublicTrackingDTO } from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { PublicTrackingPage, effectiveFreshness, statusText } from "./PublicTrackingPage";

const m = vi.mocked(api);
const NOW = new Date("2026-09-24T10:00:00Z");

function dto(ageSeconds: number | null, freshness: PublicTrackingDTO["freshness"]): PublicTrackingDTO {
  const at = ageSeconds === null ? null : new Date(NOW.getTime() - ageSeconds * 1000).toISOString();
  return {
    freshness,
    status_label: "parcel.in_transit",
    subject_label: "vehicle_carrying_your_booking",
    last_point: at
      ? { lat: 41.31, lng: 69.28, accuracy_m: 12, low_accuracy: false, captured_at: at, received_at: at }
      : null,
  };
}

beforeEach(() => vi.resetAllMocks());

describe("effectiveFreshness", () => {
  it("never upgrades the server bucket and downgrades an old point", () => {
    expect(effectiveFreshness(dto(10, "fresh"), NOW)).toBe("fresh");
    expect(effectiveFreshness(dto(90, "fresh"), NOW)).toBe("delayed");
    expect(effectiveFreshness(dto(600, "fresh"), NOW)).toBe("lost");
    expect(effectiveFreshness(dto(5, "lost"), NOW)).toBe("lost");
    expect(effectiveFreshness(dto(null, "fresh"), NOW)).toBe("no_data");
  });

  it("maps known status labels and falls back without leaking raw codes", () => {
    expect(statusText("parcel.in_transit")).toBe("Jo'natma yo'lda");
    expect(statusText("something.new")).toBe("Bron faol");
  });
});

describe("PublicTrackingPage", () => {
  it("shows loading, then a live position only when it is fresh", async () => {
    m.publicTracking.mockResolvedValue(dto(10, "fresh"));
    render(<PublicTrackingPage token="tok" now={() => NOW} />);
    expect(screen.getByText("Yuklanmoqda...")).toBeInTheDocument();
    expect(await screen.findByText("Jonli")).toBeInTheDocument();
    expect(screen.getByTestId("tracking-status").textContent).toBe("Jo'natma yo'lda");
    expect(m.publicTracking).toHaveBeenCalledWith("tok");
    expect(screen.queryByTestId("tracking-stale")).toBeNull();
  });

  it("never says live when the point is stale, even if the server said fresh", async () => {
    m.publicTracking.mockResolvedValue(dto(600, "fresh"));
    render(<PublicTrackingPage token="tok" now={() => NOW} />);
    expect(await screen.findByText("Aloqa uzilgan")).toBeInTheDocument();
    expect(screen.queryByText("Jonli")).toBeNull();
    expect(screen.getByTestId("tracking-stale")).toBeInTheDocument();
  });

  it("shows no marker without a point", async () => {
    m.publicTracking.mockResolvedValue(dto(null, "no_data"));
    render(<PublicTrackingPage token="tok" now={() => NOW} />);
    expect(await screen.findByTestId("tracking-no-point")).toBeInTheDocument();
    expect(screen.queryByText("Koordinatalar")).toBeNull();
  });

  it("treats 404 as a plain 'not available' and other errors with retry", async () => {
    m.publicTracking.mockRejectedValue(new ApiError(404, { code: "NOT_FOUND", message: "Topilmadi" }));
    const { unmount } = render(<PublicTrackingPage token="bad" />);
    expect(await screen.findByTestId("tracking-unavailable")).toBeInTheDocument();
    unmount();
    m.publicTracking.mockRejectedValue(new ApiError(500, { code: "SERVER_ERROR", message: "Server xatosi" }));
    render(<PublicTrackingPage token="tok" />);
    expect(await screen.findByText("Qayta urinish")).toBeInTheDocument();
  });
});
