/** Driver trip detail: per-segment capacity, manifest with Q44 phone timing, independent loading. SYNTHETIC. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/safety.api", () => ({
  getTrip: vi.fn(),
  tripAvailability: vi.fn(),
  tripManifest: vi.fn(),
}));

import * as api from "../../api/v2/safety.api";
import type { TripDTO } from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { DriverTripDetail } from "./DriverTripDetail";

const m = vi.mocked(api);
const at = "2026-09-25T05:00:00Z";
const trip = {
  id: "trp_1",
  status: "planned",
  version: 1,
  vehicle: { id: "veh_1", make_model: "Cobalt", color: "oq", plate_masked: "01 *** AA", seat_capacity: 4 },
  route_version_id: "rtv_1",
  stops: [
    { seq: 1, stop: { id: "stp_a", name_uz: "Toshkent" }, planned_arrival_at: at, dwell_minutes: 5 },
    { seq: 2, stop: { id: "stp_b", name_uz: "Qarshi" }, planned_arrival_at: at, dwell_minutes: 5 },
  ],
  planned_start_at: at,
  planned_end_at: at,
  timezone: "Asia/Tashkent",
  seat_capacity: 4,
  booking_cutoff_at: at,
  listings: [],
  created_at: at,
} as unknown as TripDTO;
const availability = {
  trip_id: "trp_1",
  trip_version: 1,
  computed_at: at,
  segments: [
    {
      from_seq: 1, to_seq: 2, from_stop_id: "stp_a", to_stop_id: "stp_b", seats_remaining: 3,
      baggage_remaining_ml: 200000, cargo_remaining_weight_g: 50000, cargo_remaining_volume_ml: 100000,
    },
  ],
};
const manifest = {
  trip_id: "trp_1",
  trip_version: 1,
  stops: [
    {
      seq: 1, planned_arrival_at: at, stop: { id: "stp_a", name_uz: "Toshkent" },
      pickups: [
        { booking_id: "bkg_1", service_type: "passenger", service_status: "confirmed", client_first_name: "Ali", seats: 2, contact_phone: null },
        { booking_id: "bkg_2", service_type: "parcel", service_status: "picked_up", client_first_name: "Vali", parcel_summary: "Quti, 2 kg", contact_phone: "+998900000000" },
      ],
      dropoffs: [],
    },
    { seq: 2, planned_arrival_at: at, stop: null, point: { lat: 1, lng: 2, address: "Sintetik ko'cha" }, pickups: [], dropoffs: [] },
  ],
};

beforeEach(() => vi.resetAllMocks());

describe("DriverTripDetail", () => {
  it("shows the trip, remaining capacity per segment and the manifest", async () => {
    m.getTrip.mockResolvedValue(trip);
    m.tripAvailability.mockResolvedValue(availability);
    m.tripManifest.mockResolvedValue(manifest as never);
    const { container } = render(<DriverTripDetail tripId="trp_1" />);
    expect(container.querySelectorAll(".el-skeleton").length).toBeGreaterThan(0);
    expect(await screen.findByTestId("trip-route")).toHaveTextContent("Toshkent → Qarshi");
    expect(await screen.findByTestId("availability-list")).toHaveTextContent("3 o'rin");
    expect(screen.getByTestId("availability-list")).toHaveTextContent("50 kg");
    const items = await screen.findAllByTestId("manifest-item");
    expect(items).toHaveLength(2);
    expect(screen.getByTestId("manifest-phone-hidden")).toHaveTextContent("safar boshlanganda");
    expect(screen.getByTestId("manifest-phone")).toHaveTextContent("+998900000000");
    expect(screen.getByText("Quti, 2 kg")).toBeInTheDocument();
    expect(m.getTrip).toHaveBeenCalledWith("trp_1");
  });

  it("shows empty availability and empty manifest", async () => {
    m.getTrip.mockResolvedValue(trip);
    m.tripAvailability.mockResolvedValue({ ...availability, segments: [] });
    m.tripManifest.mockResolvedValue({ trip_id: "trp_1", trip_version: 1, stops: [] });
    render(<DriverTripDetail tripId="trp_1" />);
    expect(await screen.findByTestId("availability-empty")).toBeInTheDocument();
    expect(await screen.findByTestId("manifest-empty")).toBeInTheDocument();
  });

  it("one failed call does not hide the others, and refresh reloads all three", async () => {
    m.getTrip.mockResolvedValue(trip);
    m.tripAvailability.mockResolvedValue(availability);
    m.tripManifest.mockRejectedValue(new ApiError(403, { code: "FORBIDDEN", message: "Ruxsat yo'q" }));
    render(<DriverTripDetail tripId="trp_1" />);
    expect(await screen.findByText("Qayta urinish")).toBeInTheDocument();
    expect(await screen.findByTestId("trip-route")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Yangilash"));
    await waitFor(() => expect(m.tripManifest).toHaveBeenCalledTimes(2));
    expect(m.getTrip).toHaveBeenCalledTimes(2);
    expect(m.tripAvailability).toHaveBeenCalledTimes(2);
  });
});
