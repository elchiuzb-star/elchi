/** Stop search and the public referral code check (Q117: reveals nothing about the owner). SYNTHETIC. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/v2/safety.api", () => ({ searchStops: vi.fn(), checkReferralCode: vi.fn() }));

import * as api from "../../api/v2/safety.api";
import type { StopDTO } from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { ReferralCodeCheck } from "./StopSearch";

const m = vi.mocked(api);
const stop: StopDTO = {
  id: "stp_1",
  name_uz: "Qarshi avtovokzal",
  district: { id: "dst_1", name_uz: "Qarshi shahri" },
  point: { lat: 38.8, lng: 65.8 },
  is_active: true,
  meeting_note: "Kassa oldida",
};

beforeEach(() => vi.resetAllMocks());

describe("ReferralCodeCheck", () => {
  it("says only valid or not valid", async () => {
    m.checkReferralCode.mockResolvedValueOnce({ valid: true }).mockResolvedValueOnce({ valid: false });
    const onValid = vi.fn();
    render(<ReferralCodeCheck onValid={onValid} />);
    const button = screen.getByText("Tekshirish").closest("button")!;
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: " ABC123 " } });
    fireEvent.click(button);
    expect(await screen.findByTestId("referral-result")).toHaveTextContent("Kod amal qiladi.");
    expect(m.checkReferralCode).toHaveBeenCalledWith("ABC123");
    expect(onValid).toHaveBeenCalledWith("ABC123");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ZZZ" } });
    fireEvent.click(button);
    expect(await screen.findByTestId("referral-result")).toHaveTextContent("Bu kod amal qilmaydi.");
    expect(onValid).toHaveBeenCalledTimes(1);
  });

  it("shows a rate-limit or server error", async () => {
    m.checkReferralCode.mockRejectedValue(new ApiError(429, { code: "RATE_LIMITED", message: "Keyinroq urining" }));
    render(<ReferralCodeCheck initialCode="ABC" />);
    fireEvent.click(screen.getByText("Tekshirish"));
    await waitFor(() => expect(document.querySelector("p.text-destructive")).not.toBeNull());
    expect(screen.queryByTestId("referral-result")).toBeNull();
  });
});
