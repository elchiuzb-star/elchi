import { describe, expect, it } from "vitest";

import {
  CANCEL_REASONS,
  canCancelBooking,
  cancelBlockedByReview,
  canOpenDispute,
  canRate,
  canReissueCode,
  cancelRefusalKey,
  counterpartSide,
  disputeTypesFor,
  intentOfBooking,
  reissueWait,
  waitParts,
} from "./bookingControls";
import { messages } from "../i18n/messages";

describe("booking cancel", () => {
  it("is offered only where the state machine allows `cancel`", () => {
    expect(canCancelBooking("confirmed")).toBe(true);
    expect(canCancelBooking("awaiting_pickup")).toBe(true);
    for (const status of ["onboard", "picked_up", "in_transit", "delivered", "completed", "cancelled", "no_show"]) {
      expect(canCancelBooking(status)).toBe(false);
    }
  });

  it("is blocked while a no-show review is pending (Q7/Q19), not after it was decided", () => {
    expect(cancelBlockedByReview({ status: "pending" })).toBe(true);
    expect(cancelBlockedByReview({ status: "confirmed" })).toBe(false);
    expect(cancelBlockedByReview(null)).toBe(false);
  });

  it("sends machine codes the server accepts and always offers `other` last", () => {
    for (const side of ["client", "driver"] as const) {
      const reasons = CANCEL_REASONS[side];
      expect(reasons[reasons.length - 1]).toBe("other");
      for (const code of reasons) {
        expect(code).toMatch(/^[a-z][a-z0-9_]{2,63}$/);
        expect(messages).toHaveProperty(`bookingCancel.reason.${code}`);
      }
    }
  });

  it("names the server's refusals in words", () => {
    expect(cancelRefusalKey({ code: "NO_SHOW_REVIEW_PENDING" })).toBe("bookingCancel.refused.noShowPending");
    expect(cancelRefusalKey({ code: "CUSTODY_REQUIRES_RETURN_FLOW" })).toBe("bookingCancel.refused.custody");
    expect(cancelRefusalKey({ code: "SOMETHING_ELSE" })).toBeNull();
    for (const code of ["NO_SHOW_REVIEW_PENDING", "CUSTODY_REQUIRES_RETURN_FLOW", "INVALID_STATE_TRANSITION", "VERSION_CONFLICT"]) {
      expect(messages).toHaveProperty(cancelRefusalKey({ code }) as string);
    }
  });

  it("finds the saved request the cancelled booking came from (ADR-0025)", () => {
    const intents = [{ id: "a", booking_id: null }, { id: "b", booking_id: "bkg_1" }];
    expect(intentOfBooking(intents, "bkg_1")?.id).toBe("b");
    expect(intentOfBooking(intents, "bkg_2")).toBeNull();
  });
});

describe("proof code reissue", () => {
  it("belongs to the client only (rules.CLIENT_CODE_KINDS)", () => {
    expect(canReissueCode("client", "boarding_code", "confirmed")).toBe(true);
    expect(canReissueCode("driver", "boarding_code", "confirmed")).toBe(false);
  });

  it("offers the return code only while a return is required, and nothing after the end", () => {
    expect(canReissueCode("client", "return_code", "in_transit")).toBe(false);
    expect(canReissueCode("client", "return_code", "return_required")).toBe(true);
    expect(canReissueCode("client", "delivery_code", "completed")).toBe(false);
    expect(canReissueCode("client", "pickup_code", "cancelled")).toBe(false);
  });

  it("reads the server's wait from PROOF_REISSUE_LIMITED (Q75)", () => {
    expect(reissueWait({ code: "PROOF_REISSUE_LIMITED", details: { retry_after_s: 80, reissues_left: 2 } })).toEqual({
      retryAfterS: 80,
      reissuesLeft: 2,
    });
    expect(reissueWait({ code: "PROOF_REISSUE_LIMITED", details: {} })).toEqual({ retryAfterS: 0, reissuesLeft: null });
    expect(reissueWait({ code: "RATE_LIMITED" })).toBeNull();
  });

  it("splits a wait for a sentence", () => {
    expect(waitParts(80)).toEqual({ hours: 0, minutes: 1, seconds: 20 });
    expect(waitParts(3 * 3600 + 5)).toEqual({ hours: 3, minutes: 0, seconds: 5 });
    expect(waitParts(-4)).toEqual({ hours: 0, minutes: 0, seconds: 0 });
  });
});

describe("rating and dispute", () => {
  it("rates the counterpart, never oneself", () => {
    expect(counterpartSide("client")).toBe("driver");
    expect(counterpartSide("driver")).toBe("client");
  });

  it("rates only a completed booking", () => {
    expect(canRate("completed")).toBe(true);
    expect(canRate("delivered")).toBe(false);
  });

  it("keeps the commission dispute away from the client (Q16)", () => {
    expect(disputeTypesFor("client")).not.toContain("commission");
    expect(disputeTypesFor("driver")).toContain("commission");
    expect(disputeTypesFor("driver")).toEqual(expect.arrayContaining(disputeTypesFor("client")));
  });

  it("waits for something to have happened before offering a dispute", () => {
    expect(canOpenDispute("confirmed")).toBe(false);
    expect(canOpenDispute("awaiting_pickup")).toBe(true);
    expect(canOpenDispute("completed")).toBe(true);
  });
});
