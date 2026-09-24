/**
 * Staff platform panel: loading/empty/error states, and every mutating action runs only after an explicit
 * confirmation and carries an Idempotency-Key.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const CORRIDOR = {
  id: "cor_" + "a".repeat(26), name: "Toshkent — Samarqand", origin_region: { id: "reg_1", code: "UZ-TK", name_uz: "Toshkent" },
  destination_region: { id: "reg_2", code: "UZ-SA", name_uz: "Samarqand" }, enabled_services: [], stops_count: 1,
  rollout_state: "internal", config_version: 1, config: { revision: 1, search_radius_m: 3000, default_max_detour_minutes: 15, default_max_detour_m: 5000 },
  version: 4, updated_at: "2026-09-24T00:00:00Z",
};

const api = vi.hoisted(() => ({
  adminFeatureFlags: vi.fn(),
  adminFeatureFlagHistory: vi.fn(),
  adminSetFeatureFlag: vi.fn(),
  adminCorridors: vi.fn(),
  adminCreateCorridor: vi.fn(),
  adminPatchCorridor: vi.fn(),
  adminCreateStop: vi.fn(),
  adminPatchStop: vi.fn(),
  adminCorridorStops: vi.fn(),
  adminQ47Violations: vi.fn(),
  adminRegions: vi.fn(),
  adminDistricts: vi.fn(),
  adminOutbox: vi.fn(),
  adminRetryOutbox: vi.fn(),
  adminParcelPolicies: vi.fn(),
  activeParcelPolicy: vi.fn(),
  adminCreateParcelPolicy: vi.fn(),
  adminConfirmParcelPolicy: vi.fn(),
  adminProviderQuota: vi.fn(),
  adminLegacyOrder: vi.fn(),
}));
const caps = vi.hoisted(() => ({ capabilities: vi.fn() }));

vi.mock("../api/v2/admin-platform.api", () => api);
vi.mock("../api/v2/ops.api", () => caps);
vi.mock("../api/v2/mfa.api", () => ({ stepUp: vi.fn() }));

import { ApiError } from "../types/api";
import { AdminLegacyOrderDetail, AdminPlatformPanel } from "./AdminPlatformPanel";

const ALL_CAPS = ["ops.view", "ops.feature_flag_manage", "ops.corridor_manage", "platform.policy_manage", "ops.booking_command"];

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  caps.capabilities.mockResolvedValue({ capabilities: ALL_CAPS, roles: ["super_admin"] });
  api.adminFeatureFlags.mockResolvedValue([]);
  api.adminCorridors.mockResolvedValue({ items: [CORRIDOR], nextCursor: null });
  api.adminQ47Violations.mockResolvedValue([]);
  api.adminRegions.mockResolvedValue([]);
  api.adminDistricts.mockResolvedValue([]);
  api.adminCorridorStops.mockResolvedValue([]);
  api.adminOutbox.mockResolvedValue({ items: [], nextCursor: null });
  api.adminParcelPolicies.mockResolvedValue([]);
  api.activeParcelPolicy.mockResolvedValue({ approved: false, notice: "Ro'yxat tasdiqlanmagan", items: [] });
  api.adminProviderQuota.mockResolvedValue([]);
});

function tab(name: string) {
  fireEvent.click(screen.getByRole("tab", { name }));
}

function confirm() {
  fireEvent.click(within(screen.getByRole("dialog", { name: "Tasdiqlash" })).getByRole("button", { name: "Tasdiqlayman" }));
}

describe("flags", () => {
  it("shows the default when no row exists, and the Q48 refusal in words", async () => {
    api.adminSetFeatureFlag.mockRejectedValue(
      new ApiError(503, { code: "PRODUCTION_INVARIANTS_FAILED", message: "x", details: { gate: "q48", reason: "gate_failed" } }),
    );
    render(<AdminPlatformPanel />);
    const section = await screen.findByRole("region", { name: "Pochta (v2)" });
    expect(section).toHaveTextContent("Saqlangan qator yo'q");
    fireEvent.click(within(section).getByRole("button", { name: "Yangi doira qo'shish…" }));
    fireEvent.change(within(section).getByLabelText("Doira turi"), { target: { value: "country" } });
    fireEvent.change(within(section).getByLabelText("Sabab (audit)"), { target: { value: "pilot" } });
    fireEvent.click(within(section).getByRole("button", { name: "Davom etish" }));
    expect(api.adminSetFeatureFlag).not.toHaveBeenCalled();
    confirm();
    await waitFor(() => expect(api.adminSetFeatureFlag).toHaveBeenCalledTimes(1));
    const [flag, scope, ref, body, key] = api.adminSetFeatureFlag.mock.calls[0];
    expect([flag, scope, ref]).toEqual(["parcel_enabled", "country", "UZ"]);
    expect(body).toMatchObject({ enabled: true, reason: "pilot", expected_version: null });
    expect(typeof key).toBe("string");
    expect(key.length).toBeGreaterThan(8);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Q48/);
  });

  it("shows the load error", async () => {
    api.adminFeatureFlags.mockRejectedValue(new ApiError(403, { code: "FORBIDDEN", message: "Ruxsat yo'q" }));
    render(<AdminPlatformPanel />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("hides change buttons without the capability", async () => {
    caps.capabilities.mockResolvedValue({ capabilities: ["ops.view"], roles: ["operator"] });
    render(<AdminPlatformPanel />);
    await screen.findByRole("region", { name: "Pochta (v2)" });
    expect(screen.queryByRole("button", { name: "Yangi doira qo'shish…" })).toBeNull();
  });
});

describe("corridors", () => {
  it("lists Q47 violations and patches a corridor only after confirmation", async () => {
    api.adminQ47Violations.mockResolvedValue([
      { corridor_id: "cor_x", name: "Buxoro", rollout_state: "pilot", active_stops: 1, stops_missing_evidence: ["stp_9"], reasons: ["needs_two_active_stops"] },
    ]);
    api.adminPatchCorridor.mockResolvedValue({ ...CORRIDOR, name: "Yangi nom", version: 5 });
    render(<AdminPlatformPanel initialTab="corridors" />);
    expect(await screen.findByText(/Q47 buzilgan koridorlar: 1/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Toshkent — Samarqand/ }));
    fireEvent.change(screen.getByLabelText("Nomi"), { target: { value: "Yangi nom" } });
    fireEvent.change(screen.getAllByLabelText("Sabab (audit)")[0], { target: { value: "nomlash" } });
    fireEvent.click(screen.getByRole("button", { name: "Koridorni saqlash…" }));
    expect(api.adminPatchCorridor).not.toHaveBeenCalled();
    confirm();
    await waitFor(() => expect(api.adminPatchCorridor).toHaveBeenCalledTimes(1));
    const [id, body, key] = api.adminPatchCorridor.mock.calls[0];
    expect(id).toBe(CORRIDOR.id);
    expect(body).toEqual({ expected_version: 4, reason: "nomlash", name: "Yangi nom" });
    expect(typeof key).toBe("string");
  });

  it("creates a stop with an idempotency key after confirmation", async () => {
    api.adminDistricts.mockResolvedValue([{ id: "dis_1", name_uz: "Chilonzor", region: { id: "reg_1", code: "UZ-TK", name_uz: "Toshkent" }, stops_count: 0 }]);
    const created = {
      id: "stp_1", name_uz: "Bekat", district: { id: "dis_1", name_uz: "Chilonzor" }, point: { lat: 41.3, lng: 69.2 },
      is_active: false, corridor_id: CORRIDOR.id, sequence_hint: 0, version: 1, meeting_note: "Kafe oldida",
    };
    api.adminCreateStop.mockResolvedValue(created);
    // The staff list is re-read from the server after a save: empty first, then with the new stop.
    api.adminCorridorStops.mockResolvedValueOnce([]).mockResolvedValue([created]);
    render(<AdminPlatformPanel initialTab="corridors" />);
    fireEvent.click(await screen.findByRole("button", { name: /Toshkent — Samarqand/ }));
    await screen.findByRole("option", { name: "Toshkent: Chilonzor" });
    fireEvent.change(screen.getByLabelText("Nomi (uz)"), { target: { value: "Bekat" } });
    fireEvent.change(screen.getByLabelText("Tuman"), { target: { value: "dis_1" } });
    fireEvent.change(screen.getByLabelText("Kenglik (lat)"), { target: { value: "41.3" } });
    fireEvent.change(screen.getByLabelText("Uzunlik (lng)"), { target: { value: "69.2" } });
    fireEvent.change(screen.getByLabelText("Uchrashuv izohi (dalil)"), { target: { value: "Kafe oldida" } });
    fireEvent.click(screen.getByRole("button", { name: "Bekat qo'shish…" }));
    expect(api.adminCreateStop).not.toHaveBeenCalled();
    confirm();
    await waitFor(() => expect(api.adminCreateStop).toHaveBeenCalledTimes(1));
    const [id, body, key] = api.adminCreateStop.mock.calls[0];
    expect(id).toBe(CORRIDOR.id);
    expect(body).toMatchObject({ name_uz: "Bekat", district_id: "dis_1", point: { lat: 41.3, lng: 69.2 }, meeting_note: "Kafe oldida", is_active: false });
    expect(typeof key).toBe("string");
    expect(await screen.findByText(/v1 · dalil bor/)).toBeInTheDocument();
  });
});

describe("parcel policy", () => {
  it("never claims everything is allowed when no version is confirmed", async () => {
    render(<AdminPlatformPanel initialTab="policy" />);
    expect(await screen.findByText(/«hammasi mumkin» degani emas/)).toBeInTheDocument();
  });

  it("confirms a draft with an idempotency key and shows who confirmed", async () => {
    api.adminParcelPolicies.mockResolvedValue([
      { id: "ppv_2", label: "2026-10", status: "draft", item_count: 4, version: 1, created_by: "usr_a" },
      { id: "ppv_1", label: "2026-09", status: "active", item_count: 3, version: 2, created_by: "usr_a", confirmed_by: "usr_b", confirmed_at: "2026-09-20T10:00:00Z" },
    ]);
    api.adminConfirmParcelPolicy.mockResolvedValue({});
    render(<AdminPlatformPanel initialTab="policy" />);
    expect(await screen.findByText(/Tasdiqlagan: usr_b/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tasdiqlash…" }));
    expect(api.adminConfirmParcelPolicy).not.toHaveBeenCalled();
    confirm();
    await waitFor(() => expect(api.adminConfirmParcelPolicy).toHaveBeenCalledWith("ppv_2", 1, expect.any(String)));
  });

  it("explains the second-approver rule when the author tries to confirm", async () => {
    api.adminParcelPolicies.mockResolvedValue([{ id: "ppv_2", label: "2026-10", status: "draft", item_count: 4, version: 1, created_by: "usr_a" }]);
    api.adminConfirmParcelPolicy.mockRejectedValue(
      new ApiError(403, { code: "FORBIDDEN", message: "x", details: { reason: "author_cannot_confirm_own_policy" } }),
    );
    render(<AdminPlatformPanel initialTab="policy" />);
    fireEvent.click(await screen.findByRole("button", { name: "Tasdiqlash…" }));
    confirm();
    expect(await screen.findByText(/boshqa super_admin/)).toBeInTheDocument();
  });

  it("creates a draft only after confirmation", async () => {
    api.adminCreateParcelPolicy.mockResolvedValue({});
    render(<AdminPlatformPanel initialTab="policy" />);
    await screen.findByText(/«hammasi mumkin» degani emas/);
    fireEvent.change(screen.getByLabelText("Versiya nomi"), { target: { value: "2026-10" } });
    fireEvent.change(screen.getByLabelText("Band kodi"), { target: { value: "cash" } });
    fireEvent.change(screen.getByLabelText("Toifa"), { target: { value: "business_declined" } });
    fireEvent.change(screen.getByLabelText("Band nomi"), { target: { value: "Naqd pul" } });
    fireEvent.change(screen.getByLabelText("Band tavsifi"), { target: { value: "Naqd pul jo'natilmaydi" } });
    fireEvent.click(screen.getByRole("button", { name: "Bandni qo'shish" }));
    fireEvent.click(screen.getByRole("button", { name: "Qoralamani saqlash…" }));
    expect(api.adminCreateParcelPolicy).not.toHaveBeenCalled();
    confirm();
    await waitFor(() => expect(api.adminCreateParcelPolicy).toHaveBeenCalledTimes(1));
    const [body, key] = api.adminCreateParcelPolicy.mock.calls[0];
    expect(body).toMatchObject({ label: "2026-10", items: [{ code: "cash", category: "business_declined", legal_basis: null }] });
    expect(typeof key).toBe("string");
  });
});

describe("outbox", () => {
  it("shows the empty state, then retries an event after confirmation", async () => {
    render(<AdminPlatformPanel initialTab="outbox" />);
    expect(await screen.findByText("Bu holatda hodisa yo'q.")).toBeInTheDocument();
  });

  it("retries with a reason and an idempotency key", async () => {
    api.adminOutbox.mockResolvedValue({
      items: [{
        id: "evt_1", event_type: "booking.accepted", aggregate_type: "booking", aggregate_id: "bkg_1", aggregate_version: 2,
        occurred_at: "2026-09-24T00:00:00Z", payload: {}, attempts: 5, next_attempt_at: "2026-09-24T01:00:00Z", last_error: "timeout",
      }],
      nextCursor: null,
    });
    api.adminRetryOutbox.mockResolvedValue({});
    render(<AdminPlatformPanel initialTab="outbox" />);
    fireEvent.change(await screen.findByLabelText("Qayta yuborish sababi"), { target: { value: "provayder tiklandi" } });
    fireEvent.click(screen.getByRole("button", { name: "Qayta yuborish…" }));
    expect(api.adminRetryOutbox).not.toHaveBeenCalled();
    confirm();
    await waitFor(() => expect(api.adminRetryOutbox).toHaveBeenCalledWith("evt_1", "provayder tiklandi", expect.any(String)));
  });
});

describe("system", () => {
  it("says an empty quota list is not 'unknown'", async () => {
    render(<AdminPlatformPanel initialTab="system" />);
    expect(await screen.findByText(/noma'lum» degani emas/)).toBeInTheDocument();
  });

  it("renders a legacy order read-only", async () => {
    api.adminLegacyOrder.mockResolvedValue({
      legacy_order_number: "ORD-1", status: "completed", route_summary: "Toshkent → Samarqand", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z", final_price_minor: 15_000_000, legacy_calculated_fee_minor: null, flags: ["unknown_time"],
    });
    render(<AdminLegacyOrderDetail legacyOrderNumber="ORD-1" />);
    expect(await screen.findByText("Toshkent → Samarqand")).toBeInTheDocument();
    expect(screen.getByText("vaqti noma'lum")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /o'zgartir|bekor/i })).toBeNull();
  });
});
