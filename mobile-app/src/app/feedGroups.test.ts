/**
 * The split between a result and a suggestion, asserted directly.
 *
 * The whole point of asking the server for alternatives is that a driver with nothing on their exact route
 * still gets somewhere to look. That only holds if the two groups stay apart: mixed into one list, a match
 * three hours away reads as a match, and the driver bids on a trip they cannot make.
 */
import { describe, expect, it } from "vitest";

import { alternativeReason, splitFeedGroups, type GroupedItem } from "./feedGroups";

function item(group: GroupedItem["group"], reasons: string[] = []): GroupedItem & { id: string } {
  return { id: `${group}-${reasons.join("+")}`, group, match: { reasons } };
}

describe("splitFeedGroups", () => {
  it("keeps the driver's own route apart from what is merely near it", () => {
    const groups = splitFeedGroups([
      item("primary", ["full_route"]),
      item("alternative", ["time_differs"]),
      item("primary", ["intermediate_segment"]),
    ]);
    expect(groups.primary).toHaveLength(2);
    expect(groups.alternative).toHaveLength(1);
    expect(groups.alternative[0].match.reasons).toContain("time_differs");
  });

  it("preserves the server's order inside each group", () => {
    // The server ranks the page; re-sorting it on the client would throw away the score.
    const groups = splitFeedGroups([
      item("primary", ["a"]),
      item("primary", ["b"]),
      item("alternative", ["c"]),
      item("alternative", ["d"]),
    ]);
    expect(groups.primary.map((entry) => entry.id)).toEqual(["primary-a", "primary-b"]);
    expect(groups.alternative.map((entry) => entry.id)).toEqual(["alternative-c", "alternative-d"]);
  });

  it("treats an unknown group as a real result, not as a suggestion", () => {
    // A group added later must not silently demote matches to the bottom of the screen.
    const groups = splitFeedGroups([{ group: "primary" as GroupedItem["group"], match: { reasons: [] } }]);
    expect(groups.primary).toHaveLength(1);
    expect(groups.alternative).toHaveLength(0);
  });

  it("is empty-safe: no page means no sections, not an empty heading", () => {
    const groups = splitFeedGroups([]);
    expect(groups.primary).toEqual([]);
    expect(groups.alternative).toEqual([]);
  });
});

describe("alternativeReason", () => {
  it("names the clock before the map", () => {
    // A trip at another hour may not work at all; a nearby stop is a few minutes' driving.
    expect(alternativeReason(["nearby_stop", "time_differs"])).toBe("time_differs");
  });

  it("reports a nearby stop when the time does fit", () => {
    expect(alternativeReason(["intermediate_segment", "nearby_stop"])).toBe("nearby_stop");
  });

  it("returns null rather than inventing a reason", () => {
    expect(alternativeReason(["intermediate_segment"])).toBeNull();
    expect(alternativeReason([])).toBeNull();
  });
});
