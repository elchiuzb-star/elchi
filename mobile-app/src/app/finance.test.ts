/** Pure finance-panel rules (Q17, Q49, Q69, Q70). SYNTHETIC ids only. */
import { describe, expect, it } from "vitest";

import { ApiError } from "../types/api";
import {
  CAP,
  GATE_MESSAGE,
  adjustmentActions,
  daysBefore,
  financeErrorMessage,
  isPostedTransaction,
  isStepUp,
  parseSoumToMinor,
  tashkentLocalToIso,
  tashkentToday,
  topupActions,
} from "./finance";

const all = new Set<string>(Object.values(CAP));

describe("parseSoumToMinor", () => {
  it("turns so'm text into integer tiyin without a float", () => {
    expect(parseSoumToMinor("150 000")).toBe(15_000_000);
    expect(parseSoumToMinor("150000,5")).toBe(15_000_050);
    expect(parseSoumToMinor("1.05")).toBe(105);
  });
  it("refuses empty, zero, negative and malformed amounts", () => {
    for (const bad of ["", "0", "-5", "1,234", "abc", "1e5", "12.345"]) expect(parseSoumToMinor(bad)).toBeNull();
  });
});

describe("time helpers", () => {
  it("reads datetime-local as Tashkent time with an explicit offset", () => {
    expect(tashkentLocalToIso("2026-09-24T10:30")).toBe("2026-09-24T10:30:00+05:00");
    expect(tashkentLocalToIso("garbage")).toBeNull();
  });
  it("uses the Tashkent date, not the UTC one, near midnight", () => {
    expect(tashkentToday(new Date("2026-09-23T20:00:00Z"))).toBe("2026-09-24");
    expect(daysBefore("2026-03-01", 1)).toBe("2026-02-28");
  });
});

describe("topupActions", () => {
  it("offers approve and reject on a pending top-up to finance staff", () => {
    expect(topupActions({ status: "pending" }, "usr_me", all)).toMatchObject({ approve: true, reject: true, secondStep: false });
  });
  it("never offers the first approver the second approval", () => {
    const row = { status: "awaiting_second_approval", first_approver: { id: "usr_me" } };
    expect(topupActions(row, "usr_me", all)).toMatchObject({ approve: false, reject: true });
    expect(topupActions(row, "usr_other", all)).toMatchObject({ approve: true, secondStep: true });
  });
  it("offers nothing without finance.topup_approve and nothing on a closed row", () => {
    expect(topupActions({ status: "pending" }, "usr_me", new Set([CAP.reports]))).toMatchObject({ approve: false, reject: false });
    expect(topupActions({ status: "approved" }, "usr_me", all)).toMatchObject({ approve: false, reject: false, note: null });
  });
});

describe("adjustmentActions (Q49)", () => {
  const pending = (by: string) => ({ status: "pending_second_approval", requested_by: { id: by } });
  it("lets the requester only withdraw", () => {
    expect(adjustmentActions(pending("usr_me"), "usr_me", all)).toMatchObject({ approve: false, reject: false, withdraw: true });
  });
  it("lets a different approver approve or reject", () => {
    expect(adjustmentActions(pending("usr_other"), "usr_me", all)).toMatchObject({ approve: true, reject: true, withdraw: false });
    expect(adjustmentActions(pending("usr_other"), "usr_me", new Set([CAP.reports]))).toMatchObject({ approve: false, reject: false });
  });
});

describe("errors", () => {
  it("names the Q48 production gate instead of a generic error", () => {
    const gate = new ApiError(503, { code: "PRODUCTION_INVARIANTS_FAILED", message: "x", details: { failed: ["q48_gate"] } });
    expect(financeErrorMessage(gate)).toBe(GATE_MESSAGE);
  });
  it("recognises the MFA step-up refusal", () => {
    expect(isStepUp(new ApiError(403, { code: "FORBIDDEN", message: "x", details: { reason: "step_up_required" } }))).toBe(true);
    expect(isStepUp(new ApiError(403, { code: "FORBIDDEN", message: "x" }))).toBe(false);
  });
  it("tells a posted transaction from a request awaiting a second person", () => {
    expect(isPostedTransaction({ id: "ltx_1", entries: [] })).toBe(true);
    expect(isPostedTransaction({ id: "ladj_1", status: "pending_second_approval" })).toBe(false);
  });
});
