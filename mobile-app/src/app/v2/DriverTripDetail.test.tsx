/** Driver trip detail: capacity per stretch of road (ADR-0028), manifest with Q44 phone timing, independent loading. SYNTHETIC. */
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
  route_start_m: 10_000,
  route_end_m: 450_000,
  planned_start_at: at,
  planned_end_at: "2026-09-25T11:00:00Z",
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
  stretches: [
    {
      from_m: 10_000, to_m: 130_000, seats_remaining: 3,
      baggage_remaining_ml: 200000, cargo_remaining_weight_g: 50000, cargo_remaining_volume_ml: 100000,
    },
  ],
};
const manifest = {
  trip_id: "trp_1",
  trip_version: 1,
  places: [
    {
      seq: 1, planned_arrival_at: at, point: { lat: 41.3, lng: 69.2, address: null, district: { id: "dis_1", name_uz: "Chilonzor" } },
      pickups: [
        { booking_id: "bkg_1", service_type: "passenger", service_status: "confirmed", client_first_name: "Ali", seats: 2, contact_phone: null },
        { booking_id: "bkg_2", service_type: "parcel", service_status: "picked_up", client_first_name: "Vali", parcel_summary: "Quti, 2 kg", contact_phone: "+998900000000" },
      ],
      dropoffs: [],
    },
    { seq: 2, planned_arrival_at: at, point: { lat: 1, lng: 2, address: "Sintetik ko'cha" }, pickups: [], dropoffs: [] },
  ],
};

beforeEach(() => vi.resetAllMocks());

describe("DriverTripDetail", () => {
  it("shows the trip, remaining capacity per stretch of road and the manifest", async () => {
    m.getTrip.mockResolvedValue(trip);
    m.tripAvailability.mockResolvedValue(availability);
    m.tripManifest.mockResolvedValue(manifest as never);
    const { container } = render(<DriverTripDetail tripId="trp_1" routeName="Toshkent shahri → Qarshi" />);
    expect(container.querySelectorAll(".el-skeleton").length).toBeGreaterThan(0);
    // ADR-0028: the trip is named by its direction's areas, never by a stop
    expect(await screen.findByTestId("trip-route")).toHaveTextContent("Toshkent shahri → Qarshi");
    expect(screen.queryByText(/bekat/i)).toBeNull();
    // a stretch is read in km along this trip (route_start_m is km 0), not as stop numbers
    expect(await screen.findByTestId("availability-list")).toHaveTextContent("0–120 km");
    expect(screen.getByTestId("availability-list")).toHaveTextContent("3 o'rin");
    expect(screen.getByTestId("availability-list")).toHaveTextContent("50 kg");
    const items = await screen.findAllByTestId("manifest-item");
    expect(items).toHaveLength(2);
    expect(screen.getByTestId("manifest-phone-hidden")).toHaveTextContent("safar boshlanganda");
    expect(screen.getByTestId("manifest-phone")).toHaveTextContent("+998900000000");
    expect(screen.getByText("Quti, 2 kg")).toBeInTheDocument();
    // a manifest place is the client's own marked place: its district when no address was given
    expect(screen.getByText(/Chilonzor/)).toBeInTheDocument();
    expect(m.getTrip).toHaveBeenCalledWith("trp_1");
  });

  it("names a trip without a direction by its route times", async () => {
    m.getTrip.mockResolvedValue(trip);
    m.tripAvailability.mockResolvedValue(availability);
    m.tripManifest.mockResolvedValue(manifest as never);
    render(<DriverTripDetail tripId="trp_1" />);
    expect(await screen.findByTestId("trip-route")).toHaveTextContent("→");
    expect(screen.getByTestId("trip-route").textContent).not.toMatch(/undefined|-\s*→/);
  });

  it("shows empty availability and empty manifest", async () => {
    m.getTrip.mockResolvedValue(trip);
    m.tripAvailability.mockResolvedValue({ ...availability, stretches: [] });
    m.tripManifest.mockResolvedValue({ trip_id: "trp_1", trip_version: 1, places: [] });
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
