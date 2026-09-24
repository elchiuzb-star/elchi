/**
 * S9-S11 panel: block list states, silent block/unblock, report reasons exactly as the backend enum, warnings from
 * the contact filter shown after a report. SYNTHETIC data only.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import openapi from "../../api/generated/openapi-v2.json";

vi.mock("../../api/v2/safety.api", () => ({
  listBlocks: vi.fn(),
  blockUser: vi.fn(),
  unblockUser: vi.fn(),
  createReport: vi.fn(),
  listMyReports: vi.fn(),
}));

import * as api from "../../api/v2/safety.api";
import { ApiError } from "../../types/api";
import { BlockAndReportPanel, BlockPanel, MyReportsList, REPORT_REASONS, ReportForm } from "./BlockAndReportPanel";

const m = vi.mocked(api);
const block = { id: "blk_1", user_id: "usr_other", created_at: "2026-09-20T10:00:00Z" };
const report = {
  id: "rep_1",
  subject_type: "user" as const,
  subject_id: "usr_other",
  reason_code: "harassment" as const,
  status: "under_review" as const,
  created_at: "2026-09-20T10:00:00Z",
  details: null,
  reviewed_at: null,
  version: 1,
};

beforeEach(() => {
  vi.resetAllMocks();
  m.listMyReports.mockResolvedValue({ data: [], warnings: [], meta: { next_cursor: null } });
});

describe("REPORT_REASONS", () => {
  it("matches the backend ReportReasonCode enum exactly", () => {
    const schema = (openapi as unknown as { components: { schemas: Record<string, { enum: string[] }> } }).components.schemas;
    expect(REPORT_REASONS.map(([code]) => code)).toEqual(schema.ReportReasonCode.enum);
  });
});

describe("BlockPanel", () => {
  it("shows loading, then an empty list", async () => {
    m.listBlocks.mockResolvedValue([]);
    render(<BlockPanel />);
    expect(screen.getByText("Yuklanmoqda...")).toBeInTheDocument();
    expect(await screen.findByTestId("blocks-empty")).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    m.listBlocks.mockRejectedValueOnce(new ApiError(500, { code: "SERVER_ERROR", message: "x" }));
    m.listBlocks.mockResolvedValueOnce([block]);
    render(<BlockPanel />);
    fireEvent.click(await screen.findByText("Qayta urinish"));
    expect(await screen.findByTestId("blocks-list")).toBeInTheDocument();
  });

  it("blocks the target with an idempotency key, then unblocks it", async () => {
    m.listBlocks.mockResolvedValue([]);
    m.blockUser.mockResolvedValue(block);
    m.unblockUser.mockResolvedValue({});
    const onBlocked = vi.fn();
    const onUnblocked = vi.fn();
    render(<BlockPanel targetUserId="usr_other" onBlocked={onBlocked} onUnblocked={onUnblocked} labelFor={() => "Haydovchi"} />);
    fireEvent.click(await screen.findByText("Bloklash", { selector: "button" }));
    await waitFor(() => expect(onBlocked).toHaveBeenCalledWith(block));
    expect(m.blockUser).toHaveBeenCalledWith("usr_other", expect.any(String));
    expect(screen.getByText("Haydovchi")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Blokdan chiqarish"));
    await waitFor(() => expect(onUnblocked).toHaveBeenCalledWith("usr_other"));
    expect(m.unblockUser).toHaveBeenCalledWith("usr_other");
    expect(await screen.findByTestId("blocks-empty")).toBeInTheDocument();
  });
});

describe("ReportForm", () => {
  it("needs a reason, sends the report and shows the contact-filter warning", async () => {
    m.createReport.mockResolvedValue({
      data: { ...report, details: "qo'ng'iroq qiling ***" },
      warnings: [{ code: "CONTACT_INFO_MASKED", message: "masked" }],
      meta: null,
    });
    const onReported = vi.fn();
    render(<ReportForm subjectType="user" subjectId="usr_other" onReported={onReported} />);
    const submit = screen.getByText("Yuborish").closest("button")!;
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "harassment" } });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "qo'ng'iroq qiling 901234567" } });
    fireEvent.click(submit);
    await waitFor(() => expect(onReported).toHaveBeenCalled());
    expect(m.createReport).toHaveBeenCalledWith(
      { subject_type: "user", subject_id: "usr_other", reason_code: "harassment", details: "qo'ng'iroq qiling 901234567" },
      expect.any(String),
    );
    expect(screen.getByText("Shikoyat yuborildi")).toBeInTheDocument();
    expect(screen.getByTestId("report-details").textContent).toContain("***");
    expect(document.body.textContent).not.toContain("901234567");
  });

  it("shows the server error and keeps the form", async () => {
    m.createReport.mockRejectedValue(new ApiError(429, { code: "RATE_LIMITED", message: "Juda ko'p so'rov" }));
    render(<ReportForm subjectType="listing" subjectId="lst_1" />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "other" } });
    fireEvent.click(screen.getByText("Yuborish"));
    expect(await screen.findByText(/.+/, { selector: "p.text-destructive" })).toBeInTheDocument();
    expect(screen.getByText("Yuborish")).toBeInTheDocument();
  });
});

describe("MyReportsList", () => {
  it("shows empty, then data with status and pagination", async () => {
    const { unmount } = render(<MyReportsList />);
    expect(await screen.findByTestId("reports-empty")).toBeInTheDocument();
    unmount();
    m.listMyReports
      .mockResolvedValueOnce({ data: [report], warnings: [], meta: { next_cursor: "c1" } })
      .mockResolvedValueOnce({ data: [{ ...report, id: "rep_2", status: "actioned" }], warnings: [], meta: { next_cursor: null } });
    render(<MyReportsList />);
    expect(await screen.findByText("Ko'rib chiqilmoqda")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Yana yuklash"));
    expect(await screen.findByText("Chora ko'rildi")).toBeInTheDocument();
    expect(m.listMyReports).toHaveBeenLastCalledWith("c1");
    expect(screen.queryByText("Yana yuklash")).toBeNull();
  });
});

describe("BlockAndReportPanel", () => {
  it("renders the report form only when a subject is given", async () => {
    m.listBlocks.mockResolvedValue([]);
    const { rerender } = render(<BlockAndReportPanel targetUserId="usr_other" />);
    expect(screen.queryByText(/Shikoyat:/)).toBeNull();
    rerender(<BlockAndReportPanel targetUserId="usr_other" subject={{ type: "user", id: "usr_other" }} />);
    expect(screen.getByText(/Shikoyat:/)).toBeInTheDocument();
    await screen.findByTestId("blocks-empty");
  });
});
