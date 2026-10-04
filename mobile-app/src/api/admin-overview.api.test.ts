/**
 * v2 queue tiles on the overview (§3.4/§3.5, contract §4.1): the summary endpoint wins, a capped count stays
 * "at least", the fallback reads a page and flags the cap, and finance asks only for its money queue.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../types/api";

const admin = vi.hoisted(() => ({ opsQueueSummary: vi.fn() }));
const ops = vi.hoisted(() => ({ opsQueue: vi.fn() }));
const trust = vi.hoisted(() => ({ listFraudSignals: vi.fn(), listSupportThreadsAdmin: vi.fn() }));

vi.mock("./admin.api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...admin }));
vi.mock("./v2/ops.api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...ops }));
vi.mock("./v2/admin-trust.api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...trust }));

import { QUEUE_COUNT_PAGE, formatTileCount, getV2QueueCounts } from "./admin-overview.api";

beforeEach(() => {
  for (const group of [admin, ops, trust]) Object.values(group).forEach((mock) => mock.mockReset());
  trust.listFraudSignals.mockResolvedValue([{}, {}]);
});

describe("getV2QueueCounts", () => {
  it("uses the summary and keeps a capped count as a lower bound", async () => {
    admin.opsQueueSummary.mockResolvedValue([
      { queue: "finance_review", count: 200, capped: true, cap: 200 },
      { queue: "no_show_review", count: 3, capped: false, cap: 200 },
      { queue: "support_thread", count: 6, capped: false, cap: 200 },
      { queue: "dispute", count: 4, capped: false, cap: 200 },
    ]);
    const { counts, failed } = await getV2QueueCounts("admin");
    expect(failed).toBe(false);
    expect(formatTileCount(counts.finance_review)).toBe("200+");
    expect(formatTileCount(counts.no_show_review)).toBe("3");
    expect(formatTileCount(counts.support_threads)).toBe("6");
    expect(formatTileCount(counts.disputes)).toBe("4");
    expect(formatTileCount(counts.fraud)).toBe("2");
    expect(ops.opsQueue).not.toHaveBeenCalled();
  });

  it("falls back to reading a page when the summary route is missing", async () => {
    admin.opsQueueSummary.mockRejectedValue(new ApiError(404, { code: "NOT_FOUND", message: "Not Found" }));
    ops.opsQueue.mockImplementation(async (queue: string) => (queue === "finance_review" ? Array.from({ length: QUEUE_COUNT_PAGE }) : [{}]));
    trust.listSupportThreadsAdmin.mockResolvedValue([{}]);
    const { counts } = await getV2QueueCounts("operator");
    expect(formatTileCount(counts.finance_review)).toBe(`${QUEUE_COUNT_PAGE}+`);
    expect(formatTileCount(counts.no_show_review)).toBe("1");
  });

  it("asks finance only for the money queue", async () => {
    admin.opsQueueSummary.mockResolvedValue([{ queue: "finance_review", count: 14, capped: false, cap: 200 }]);
    const { counts } = await getV2QueueCounts("finance");
    expect(Object.keys(counts)).toEqual(["finance_review"]);
    expect(trust.listFraudSignals).not.toHaveBeenCalled();
  });

  it("hides a tile the role may not read instead of failing the page", async () => {
    admin.opsQueueSummary.mockResolvedValue([]);
    ops.opsQueue.mockResolvedValue([]);
    trust.listFraudSignals.mockRejectedValue(new ApiError(403, { code: "CAPABILITY_REQUIRED", message: "no" }));
    trust.listSupportThreadsAdmin.mockResolvedValue([]);
    const { counts, failed } = await getV2QueueCounts("operator");
    expect(counts.fraud).toBeUndefined();
    expect(failed).toBe(false);
  });
});
