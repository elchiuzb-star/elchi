/** §5.2 parcel policy: unconfirmed is never "everything allowed"; items as returned with their source. SYNTHETIC. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/safety.api", () => ({ parcelPolicy: vi.fn() }));

import * as api from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { ParcelPolicyNotice } from "./ParcelPolicyNotice";

const m = vi.mocked(api);

beforeEach(() => vi.resetAllMocks());

describe("ParcelPolicyNotice", () => {
  it("says the list is not confirmed - never that everything is allowed", async () => {
    m.parcelPolicy.mockResolvedValue({ approved: false, notice: "Ro'yxat hali tasdiqlanmagan (server).", items: [] });
    const { container } = render(<ParcelPolicyNotice />);
    expect(container.querySelector(".el-skeleton")).not.toBeNull();
    expect(await screen.findByTestId("policy-unconfirmed")).toBeInTheDocument();
    expect(screen.getByText("Ro'yxat hali tasdiqlanmagan (server).")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/hammasi ruxsat|hamma narsa ruxsat/i);
  });

  it("groups returned items by category with their legal source", async () => {
    m.parcelPolicy.mockResolvedValue({
      approved: true,
      notice: "Quyidagi jo'natmalarni yuborib bo'lmaydi.",
      label: "v1",
      effective_from: "2026-09-01T00:00:00Z",
      items: [
        {
          code: "weapons", category: "prohibited", applies_to: "all", title: "Qurol", description: "Sintetik tavsif",
          legal_basis: "Sintetik qonun 1-modda", source_ref: "SRC-1", source_checked_on: "2026-08-30",
        },
        { code: "liquids", category: "restricted", applies_to: "parcel", title: "Suyuqlik", description: "Sintetik" },
      ],
    });
    render(<ParcelPolicyNotice />);
    expect(await screen.findByText("Qurol")).toBeInTheDocument();
    expect(screen.getByText("Taqiqlangan")).toBeInTheDocument();
    expect(screen.getByText("Cheklangan")).toBeInTheDocument();
    expect(screen.getByText(/Sintetik qonun 1-modda · SRC-1 \(tekshirilgan: 2026-08-30\)/)).toBeInTheDocument();
    expect(screen.getAllByTestId("policy-item")).toHaveLength(2);
  });

  it("an approved but empty list still does not claim everything is allowed", async () => {
    m.parcelPolicy.mockResolvedValue({ approved: true, notice: "n", items: [] });
    render(<ParcelPolicyNotice />);
    expect(await screen.findByTestId("policy-empty")).toHaveTextContent("baribir yuborilmaydi");
  });

  it("shows an error with retry and a reminder to check the list", async () => {
    m.parcelPolicy.mockRejectedValue(new ApiError(500, { code: "SERVER_ERROR", message: "x" }));
    render(<ParcelPolicyNotice />);
    expect(await screen.findByText("Qayta urinish")).toBeInTheDocument();
    expect(screen.getByText(/albatta tekshiring/)).toBeInTheDocument();
  });
});
