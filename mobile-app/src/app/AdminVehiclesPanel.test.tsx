/**
 * Staff vehicle queue: loading, empty, error, the confirm-then-act flow and the refresh after a decision.
 * SYNTHETIC data only; the API wrappers are mocked so the test proves which wrapper gets which arguments.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminVehicle } from "../api/v2/admin-vehicles.api";
import { ApiError } from "../types/api";

const api = vi.hoisted(() => ({
  adminVehicles: vi.fn(),
  adminVerifyVehicle: vi.fn(),
  adminSetDriverEligibility: vi.fn(),
}));

vi.mock("../api/v2/admin-vehicles.api", () => api);

import { AdminVehiclesPanel } from "./AdminVehiclesPanel";

function vehicle(overrides: Partial<AdminVehicle> = {}): AdminVehicle {
  return {
    id: "veh_synthetic1",
    plate_number: "01A123BC",
    plate_masked: "01A***BC",
    make_model: "Chevrolet Cobalt",
    color: "oq",
    seat_capacity: 4,
    baggage_capacity_ml: 400_000,
    cargo_max_weight_g: 100_000,
    cargo_max_volume_ml: null,
    document_file_ids: [],
    verification_status: "pending",
    version: 1,
    created_at: "2026-09-20T08:00:00Z",
    verification_reason: null,
    verified_at: null,
    updated_at: "2026-09-20T08:00:00Z",
    owner: {
      user_id: "usr_synthetic",
      is_driver: true,
      account_active: true,
      driver_verification_status: "approved",
      eligible: true,
      reasons: [],
      blocked_reason: null,
      eligibility_version: 1,
      active_trip_count: 0,
    },
    ...overrides,
  } as AdminVehicle;
}

beforeEach(() => {
  api.adminVehicles.mockReset();
  api.adminVerifyVehicle.mockReset();
  api.adminSetDriverEligibility.mockReset();
});

describe("AdminVehiclesPanel", () => {
  it("shows loading, then asks the server for the pending queue by default", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    api.adminVehicles.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = render(<AdminVehiclesPanel />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
    expect(api.adminVehicles).toHaveBeenCalledWith({ status: "pending", limit: 20 });
    resolve({ items: [], nextCursor: null });
    expect(await screen.findByText("Tasdiq kutayotgan avtomobil yo'q.")).toBeInTheDocument();
  });

  it("shows the server's error and retries on request", async () => {
    api.adminVehicles.mockRejectedValueOnce(new ApiError(403, { code: "CAPABILITY_REQUIRED", message: "no" }));
    api.adminVehicles.mockResolvedValueOnce({ items: [vehicle()], nextCursor: null });
    render(<AdminVehiclesPanel />);
    expect(await screen.findByText("Bu amal uchun ruxsatingiz yo'q")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Qayta urinish"));
    expect(await screen.findByText(/Chevrolet Cobalt · oq · 01A123BC/)).toBeInTheDocument();
  });

  it("changes the filter and sends no status for 'all'", async () => {
    api.adminVehicles.mockResolvedValue({ items: [], nextCursor: null });
    render(<AdminVehiclesPanel />);
    await screen.findByText("Tasdiq kutayotgan avtomobil yo'q.");
    fireEvent.click(screen.getByText("Hammasi"));
    await waitFor(() => expect(api.adminVehicles).toHaveBeenLastCalledWith({ status: undefined, limit: 20 }));
  });

  it("approves only after confirmation, with the row version, then reloads", async () => {
    api.adminVehicles.mockResolvedValue({ items: [vehicle()], nextCursor: null });
    api.adminVerifyVehicle.mockResolvedValue({});
    render(<AdminVehiclesPanel />);
    fireEvent.click(await screen.findByText("Tasdiqlash"));
    expect(api.adminVerifyVehicle).not.toHaveBeenCalled();
    expect(screen.getByText("Avtomobilni tasdiqlaysizmi?")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Ha, tasdiqlayman"));
    await waitFor(() => expect(api.adminVerifyVehicle).toHaveBeenCalledTimes(1));
    const [id, body, key] = api.adminVerifyVehicle.mock.calls[0];
    expect(id).toBe("veh_synthetic1");
    expect(body).toEqual({ decision: "approve", expected_version: 1, reason: null });
    expect(typeof key).toBe("string");
    await waitFor(() => expect(api.adminVehicles).toHaveBeenCalledTimes(2));
  });

  it("requires a reason to reject and keeps the dialog open on a server refusal", async () => {
    api.adminVehicles.mockResolvedValue({ items: [vehicle()], nextCursor: null });
    api.adminVerifyVehicle.mockRejectedValue(new ApiError(409, { code: "VERSION_CONFLICT", message: "stale" }));
    render(<AdminVehiclesPanel />);
    fireEvent.click(await screen.findByText("Rad etish"));
    const confirm = screen.getByText("Ha, tasdiqlayman").closest("button") as HTMLButtonElement;
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Raqam hujjatga mos emas" } });
    expect(confirm).not.toBeDisabled();
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(api.adminVerifyVehicle).toHaveBeenCalledWith(
        "veh_synthetic1",
        { decision: "reject", expected_version: 1, reason: "Raqam hujjatga mos emas" },
        expect.any(String),
      ),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(api.adminVehicles).toHaveBeenCalledTimes(1);
  });

  it("blocks a driver's new business with the eligibility version, and says why a profile is still unverified", async () => {
    const row = vehicle({
      owner: { ...vehicle().owner, eligible: false, reasons: ["not_verified"], driver_verification_status: "pending", eligibility_version: 4 },
    });
    api.adminVehicles.mockResolvedValue({ items: [row], nextCursor: null });
    api.adminSetDriverEligibility.mockResolvedValue({});
    render(<AdminVehiclesPanel />);
    expect(await screen.findByText(/haydovchi profilini tasdiqlamaydi/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Yangi ishini bloklash"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Hujjat tekshirilmoqda" } });
    fireEvent.click(screen.getByText("Ha, tasdiqlayman"));
    await waitFor(() =>
      expect(api.adminSetDriverEligibility).toHaveBeenCalledWith(
        "usr_synthetic",
        { action: "block", expected_version: 4, reason: "Hujjat tekshirilmoqda" },
        expect.any(String),
      ),
    );
  });

  it("offers no decision the server would refuse for the row's status", async () => {
    api.adminVehicles.mockResolvedValue({ items: [vehicle({ verification_status: "blocked" })], nextCursor: null });
    render(<AdminVehiclesPanel />);
    await screen.findByText(/Chevrolet Cobalt/);
    expect(screen.queryByText("Tasdiqlash")).toBeNull();
    expect(screen.queryByText("Rad etish")).toBeNull();
  });
});
