/**
 * The auction rules, asserted directly.
 *
 * These are the conditions that decide whether a person can turn a conversation into a booking. They were
 * inline on three screens with no test at all; the one that matters most (AC05 - you cannot accept your own
 * price) is a single `!==` that nothing would have caught if it flipped.
 */
import { describe, expect, it } from "vitest";

import { agreedTotalMinor, negotiationActions, turnLabel, type ProposalThreadDTO } from "./auction";

type Version = NonNullable<ProposalThreadDTO["current_version"]>;

function version(overrides: Partial<Version> = {}): Version {
  return {
    id: "prv_1",
    revision: 1,
    status: "active",
    author_side: "driver",
    pickup_window_start: "2026-09-18T06:00:00Z",
    pickup_window_end: "2026-09-18T07:00:00Z",
    quantity: 1,
    price_basis: "per_seat",
    unit_price_minor: 33_000_000,
    total_minor: 33_000_000,
    currency: "UZS",
    price_revisions_left: { client: 2, driver: 2 },
    expires_at: "2026-09-18T12:00:00Z",
    created_at: "2026-09-18T05:00:00Z",
    ...overrides,
  } as Version;
}

function thread(overrides: Partial<ProposalThreadDTO> = {}): ProposalThreadDTO {
  return { id: "pth_1", state: "open", current_version: version(), ...overrides } as ProposalThreadDTO;
}

describe("who may accept", () => {
  it("lets the client accept a version the driver authored", () => {
    const actions = negotiationActions(thread(), "client");
    expect(actions.canAccept).toBe(true);
    expect(actions.theirTurn).toBe(true);
  });

  it("never lets the author accept their own version (AC05)", () => {
    const actions = negotiationActions(thread(), "driver");
    expect(actions.canAccept).toBe(false);
    expect(actions.canWithdraw).toBe(true);
  });

  it("works the same way round when the client spoke last", () => {
    const clientSpoke = thread({ current_version: version({ author_side: "client" }) });
    expect(negotiationActions(clientSpoke, "driver").canAccept).toBe(true);
    expect(negotiationActions(clientSpoke, "client").canAccept).toBe(false);
  });
});

describe("who may answer", () => {
  it("offers a counteroffer while this side has revisions left", () => {
    const actions = negotiationActions(thread(), "client");
    expect(actions.canCounter).toBe(true);
    expect(actions.revisionsLeft).toBe(2);
  });

  it("stops offering one when this side has used them up", () => {
    const spent = thread({ current_version: version({ price_revisions_left: { client: 0, driver: 2 } }) });
    expect(negotiationActions(spent, "client").canCounter).toBe(false);
    expect(negotiationActions(spent, "driver").canCounter).toBe(true);
  });

  it("lets each side take back only its own version and refuse only the other's", () => {
    const mine = negotiationActions(thread(), "driver");
    const theirs = negotiationActions(thread(), "client");
    expect([mine.canWithdraw, mine.canReject]).toEqual([true, false]);
    expect([theirs.canWithdraw, theirs.canReject]).toEqual([false, true]);
  });
});

describe("a closed negotiation takes no answer", () => {
  it.each([
    ["the thread is closed", thread({ state: "closed" })],
    ["the version was superseded", thread({ current_version: version({ status: "superseded" }) })],
    ["the version was accepted", thread({ current_version: version({ status: "accepted" }) })],
    ["there is no current version", thread({ current_version: null } as Partial<ProposalThreadDTO>)],
  ])("%s", (_name, closed) => {
    const actions = negotiationActions(closed, "client");
    expect(actions.open).toBe(false);
    expect([actions.canAccept, actions.canCounter, actions.canWithdraw, actions.canReject]).toEqual([
      false,
      false,
      false,
      false,
    ]);
  });
});

describe("the agreed price", () => {
  it("is read off the version and never recomputed (Q90)", () => {
    // 300k -> 350k -> 320k -> 330k -> accept: the booking is 330 000, whatever any band says.
    const agreed = thread({ current_version: version({ unit_price_minor: 33_000_000, total_minor: 33_000_000 }) });
    expect(agreedTotalMinor(agreed)).toBe(33_000_000);
  });

  it("carries a multi-seat total as the server calculated it", () => {
    const twoSeats = thread({
      current_version: version({ quantity: 2, unit_price_minor: 20_000_000, total_minor: 40_000_000 }),
    });
    expect(agreedTotalMinor(twoSeats)).toBe(40_000_000);
  });

  it("is null when there is nothing agreed yet", () => {
    expect(agreedTotalMinor(thread({ current_version: null } as Partial<ProposalThreadDTO>))).toBeNull();
  });
});

describe("what the screen says about whose turn it is", () => {
  it("names the other side when they answered last", () => {
    expect(turnLabel(negotiationActions(thread(), "client"), "client")).toContain("Haydovchi");
    const clientSpoke = thread({ current_version: version({ author_side: "client" }) });
    expect(turnLabel(negotiationActions(clientSpoke, "driver"), "driver")).toContain("Mijoz");
  });

  it("says the offer is yours when you spoke last", () => {
    expect(turnLabel(negotiationActions(thread(), "driver"), "driver")).toContain("Sizning");
  });
});
