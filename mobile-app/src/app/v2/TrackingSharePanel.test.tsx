/**
 * K5 tracking grants and O1 share links: Q83 TTL bounds, the once-only URL, expiry, copy and revoke. SYNTHETIC data.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/safety.api", () => ({
  TRACKING_GRANT_MIN_MINUTES: 15,
  TRACKING_GRANT_MAX_MINUTES: 1440,
  SHARE_LINK_MAX_HOURS: 336,
  createTrackingGrant: vi.fn(),
  revokeTrackingGrant: vi.fn(),
  createShareLink: vi.fn(),
  revokeShareLink: vi.fn(),
}));

import * as api from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import {
  SHARE_TTL_OPTIONS,
  TRACKING_TTL_OPTIONS,
  TrackingGrantPanel,
  TrackingSharePanel,
  ShareLinkPanel,
  sharePageUrl,
  trackingPageUrl,
} from "./TrackingSharePanel";

const m = vi.mocked(api);
const future = new Date(Date.now() + 3600_000).toISOString();

beforeEach(() => vi.resetAllMocks());

describe("link helpers", () => {
  it("turns the JSON endpoint into the app page and keeps configured page URLs", () => {
    expect(trackingPageUrl("/api/v2/public/tracking/tok123", "https://app.test")).toBe("https://app.test/t/tok123");
    expect(trackingPageUrl("https://elchigo.uz/track/tok", "https://app.test")).toBe("https://elchigo.uz/track/tok");
    expect(sharePageUrl("/api/v2/public/listings/tok9", "https://app.test")).toBe("https://app.test/e/tok9");
  });

  it("offers only Q83 lifetimes (15 min - 24 h) and share lifetimes within 336 h", () => {
    for (const [minutes] of TRACKING_TTL_OPTIONS) {
      expect(minutes).toBeGreaterThanOrEqual(15);
      expect(minutes).toBeLessThanOrEqual(1440);
    }
    expect(TRACKING_TTL_OPTIONS.map(([v]) => v)).toContain(15);
    expect(TRACKING_TTL_OPTIONS.map(([v]) => v)).toContain(1440);
    for (const [hours] of SHARE_TTL_OPTIONS) expect(hours).toBeLessThanOrEqual(336);
  });
});

describe("TrackingGrantPanel", () => {
  it("creates a grant with the chosen TTL, shows the link and expiry, copies and revokes", async () => {
    m.createTrackingGrant.mockResolvedValue({
      id: "tgr_1",
      url: "/api/v2/public/tracking/secret",
      valid_from: new Date().toISOString(),
      expires_at: future,
    });
    m.revokeTrackingGrant.mockResolvedValue({});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    render(<TrackingGrantPanel bookingId="bkg_1" />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "180" } });
    fireEvent.click(screen.getByText("Havola yaratish"));
    const input = (await screen.findByTestId("tracking-url")) as HTMLInputElement;
    expect(m.createTrackingGrant).toHaveBeenCalledWith("bkg_1", 180, expect.any(String));
    expect(input.value).toBe(`${window.location.origin}/t/secret`);
    expect(screen.getByText(/Amal qiladi:/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Havoladan nusxa olish"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/t/secret`));
    expect(await screen.findByText("Nusxa olindi")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Bekor qilish"));
    expect(await screen.findByText("Havola bekor qilindi.")).toBeInTheDocument();
    expect(m.revokeTrackingGrant).toHaveBeenCalledWith("bkg_1", "tgr_1");
    expect(screen.queryByTestId("tracking-url")).toBeNull();
  });

  it("says the link is not shown again on an idempotent replay, and marks an expired grant", async () => {
    m.createTrackingGrant.mockResolvedValue({ id: "tgr_2", url: null, valid_from: future, expires_at: future });
    const { unmount } = render(<TrackingGrantPanel bookingId="bkg_1" />);
    fireEvent.click(screen.getByText("Havola yaratish"));
    expect(await screen.findByText(/faqat birinchi javobda/)).toBeInTheDocument();
    unmount();
    m.createTrackingGrant.mockResolvedValue({ id: "tgr_3", url: "/x", valid_from: future, expires_at: "2020-01-01T00:00:00Z" });
    render(<TrackingGrantPanel bookingId="bkg_1" />);
    fireEvent.click(screen.getByText("Havola yaratish"));
    expect(await screen.findByText(/Muddati tugagan/)).toBeInTheDocument();
    expect(screen.queryByTestId("tracking-url")).toBeNull();
  });

  it("shows the server's refusal", async () => {
    m.createTrackingGrant.mockRejectedValue(new ApiError(409, { code: "TRACKING_NOT_AVAILABLE", message: "Kuzatuv yopiq" }));
    render(<TrackingGrantPanel bookingId="bkg_1" />);
    fireEvent.click(screen.getByText("Havola yaratish"));
    expect(await screen.findByText("Kuzatuv yopiq")).toBeInTheDocument();
  });
});

describe("ShareLinkPanel", () => {
  it("creates a share link with ttl and channel, shows the page link inside the share text, revokes", async () => {
    m.createShareLink.mockResolvedValue({
      id: "shl_1",
      channel: "telegram",
      url: "/api/v2/public/listings/tokA",
      share_text: "Toshkent → Qarshi /api/v2/public/listings/tokA",
      expires_at: future,
      created_at: future,
    });
    m.revokeShareLink.mockResolvedValue({});
    render(<ShareLinkPanel listingId="lst_1" />);
    const [ttl, channel] = screen.getAllByRole("combobox");
    fireEvent.change(ttl, { target: { value: "168" } });
    fireEvent.change(channel, { target: { value: "telegram" } });
    fireEvent.click(screen.getByText("Havola yaratish"));
    const input = (await screen.findByTestId("share-url")) as HTMLInputElement;
    expect(m.createShareLink).toHaveBeenCalledWith("lst_1", { ttl_hours: 168, channel: "telegram" }, expect.any(String));
    expect(input.value).toBe(`${window.location.origin}/e/tokA`);
    expect(screen.getByText(`Toshkent → Qarshi ${window.location.origin}/e/tokA`)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Bekor qilish"));
    expect(await screen.findByText("Havola bekor qilindi.")).toBeInTheDocument();
    expect(m.revokeShareLink).toHaveBeenCalledWith("shl_1");
  });
});

describe("TrackingSharePanel", () => {
  it("renders each part only when its id is given", () => {
    const { rerender } = render(<TrackingSharePanel bookingId="bkg_1" />);
    expect(screen.getByText("Kuzatuv havolasi")).toBeInTheDocument();
    expect(screen.queryByText("E'lonni ulashish")).toBeNull();
    rerender(<TrackingSharePanel listingId="lst_1" />);
    expect(screen.queryByText("Kuzatuv havolasi")).toBeNull();
    expect(screen.getByText("E'lonni ulashish")).toBeInTheDocument();
  });
});
