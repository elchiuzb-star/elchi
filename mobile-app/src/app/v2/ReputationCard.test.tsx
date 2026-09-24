/** S2 reputation: no invented rating (§8.2), only what the server returns. SYNTHETIC data. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/safety.api", () => ({ userReputation: vi.fn() }));

import * as api from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { ReputationCard } from "./ReputationCard";

const m = vi.mocked(api);
const base = {
  user_id: "usr_1",
  service_type: "passenger" as const,
  completed_bookings: 0,
  completed_trips: 0,
};

beforeEach(() => vi.resetAllMocks());

describe("ReputationCard", () => {
  it("loads with the service type and says 'hali baholanmagan' without ratings - no 4.5", async () => {
    m.userReputation.mockResolvedValue({ ...base, rating_count: 0, average_rating: null, label: "new_verified" });
    const { container } = render(<ReputationCard userId="usr_1" serviceType="passenger" />);
    expect(container.querySelector(".el-skeleton")).not.toBeNull();
    expect(await screen.findByTestId("rating-none")).toHaveTextContent("Hali baholanmagan");
    expect(m.userReputation).toHaveBeenCalledWith("usr_1", "passenger");
    expect(container.textContent).not.toMatch(/4[.,]5|★/);
    expect(container.textContent).not.toMatch(/hujjat/i);
  });

  it("shows the returned average and counts", async () => {
    m.userReputation.mockResolvedValue({
      ...base, rating_count: 12, average_rating: 4.83, label: "rated", completed_bookings: 30, completed_trips: 9,
    });
    render(<ReputationCard userId="usr_1" serviceType="parcel" />);
    expect(await screen.findByTestId("rating-value")).toHaveTextContent("4,8");
    expect(screen.getByText("12 ta")).toBeInTheDocument();
    expect(screen.getByText("30 ta")).toBeInTheDocument();
    expect(screen.getByText("9 ta")).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    m.userReputation.mockRejectedValue(new ApiError(404, { code: "NOT_FOUND", message: "Topilmadi" }));
    render(<ReputationCard userId="usr_x" serviceType="passenger" />);
    expect(await screen.findByText("Qayta urinish")).toBeInTheDocument();
  });
});
