import { describe, expect, it } from "vitest";

import type { FlagValueDTO } from "../api/v2/admin-platform.api";
import { ApiError } from "../types/api";
import {
  corridorRefusalMessage,
  flagRefusalMessage,
  policyItemProblem,
  policySummary,
  resolveFlag,
  scopeRefProblem,
  stopHasEvidence,
} from "./adminPlatform";

const CORRIDOR = "cor_" + "a".repeat(26);

function row(partial: Partial<FlagValueDTO>): FlagValueDTO {
  return {
    id: "ffv_x", flag_key: "parcel_enabled", scope_type: "country", scope_ref: "UZ", enabled: true, version: 1,
    updated_at: "2026-09-24T00:00:00Z", ...partial,
  } as FlagValueDTO;
}

describe("resolveFlag (mirrors geo/flags.py)", () => {
  it("falls back to the production default when no row matches", () => {
    expect(resolveFlag([], "parcel_enabled", {})).toMatchObject({ enabled: false, sourceScope: null });
    expect(resolveFlag([], "wallet_required", {})).toMatchObject({ enabled: true, sourceScope: null });
  });

  it("lets the corridor row win over the country row", () => {
    const rows = [row({ enabled: true }), row({ id: "b", scope_type: "corridor", scope_ref: CORRIDOR, enabled: false })];
    expect(resolveFlag(rows, "parcel_enabled", { corridorRef: CORRIDOR })).toMatchObject({ enabled: false, sourceScope: "corridor" });
    expect(resolveFlag(rows, "parcel_enabled", {})).toMatchObject({ enabled: true, sourceScope: "country" });
  });

  it("resolves conflicting rows on one level to the safe default (Q26)", () => {
    const rows = [
      row({ id: "a", scope_type: "region", scope_ref: "UZ-TK", enabled: true }),
      row({ id: "b", scope_type: "region", scope_ref: "UZ-SA", enabled: false }),
    ];
    expect(resolveFlag(rows, "parcel_enabled", { regionRefs: ["UZ-TK", "UZ-SA"] })).toMatchObject({ enabled: false, conflict: true });
  });
});

describe("scope refs", () => {
  it("accepts only the server's syntax", () => {
    expect(scopeRefProblem("country", "UZ")).toBeNull();
    expect(scopeRefProblem("country", "KZ")).not.toBeNull();
    expect(scopeRefProblem("region", "UZ-SA")).toBeNull();
    expect(scopeRefProblem("cohort", "Pilot")).not.toBeNull();
    expect(scopeRefProblem("corridor", CORRIDOR)).toBeNull();
  });
});

describe("refusal messages", () => {
  it("names the Q48 gate and the Q5 approval reference", () => {
    const gate = new ApiError(503, { code: "PRODUCTION_INVARIANTS_FAILED", message: "x", details: { gate: "q48", reason: "gate_failed" } });
    expect(flagRefusalMessage(gate)).toMatch(/Q48/);
    const approval = new ApiError(422, { code: "APPROVAL_REFERENCE_REQUIRED", message: "x" });
    expect(flagRefusalMessage(approval)).toMatch(/Q5/);
    const superAdmin = new ApiError(403, { code: "FORBIDDEN", message: "x", details: { required_role: "super_admin" } });
    expect(flagRefusalMessage(superAdmin)).toMatch(/super_admin/);
    expect(flagRefusalMessage(new Error("x"))).toBeNull();
  });

  it("explains a Q47 rollout refusal", () => {
    const error = new ApiError(409, {
      code: "INVALID_STATE_TRANSITION", message: "x",
      details: { reason: "stops_missing_meeting_evidence", stop_ids: ["stp_1"] },
    });
    expect(corridorRefusalMessage(error)).toMatch(/dalil.*stp_1/s);
  });
});

describe("stops and parcel policy", () => {
  it("counts a note or a photo as evidence, not a blank note", () => {
    expect(stopHasEvidence({ meeting_note: "  " })).toBe(false);
    expect(stopHasEvidence({ meeting_note: "Bekat oldida" })).toBe(true);
    expect(stopHasEvidence({ meeting_photo_file_id: "f1" })).toBe(true);
  });

  it("never reads an empty or unconfirmed list as 'everything allowed'", () => {
    expect(policySummary([])).toMatch(/yopiq/);
    expect(policySummary([{ status: "draft", item_count: 3 }])).toMatch(/hammasi mumkin.*emas/);
    expect(policySummary([{ status: "active", item_count: 3 }])).toMatch(/3 ta band/);
  });

  it("requires legal basis and source for a prohibited item", () => {
    const base = { code: "weapons", category: "prohibited", title_uz: "Qurol", description_uz: "Har qanday qurol" };
    expect(policyItemProblem(base)).not.toBeNull();
    expect(policyItemProblem({ ...base, legal_basis: "Qonun", source_ref: "lex.uz" })).toBeNull();
    expect(policyItemProblem({ ...base, category: "business_declined" })).toBeNull();
  });
});
