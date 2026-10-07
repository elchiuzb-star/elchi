/**
 * ADR-0026 (Q141) operator chat queue: the queue shows requester, booking, owner and open/closed; staff take a
 * thread, answer and close it through the right wrapper with the thread's version; nothing here moves money.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/v2/admin-trust.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/v2/admin-trust.api")>();
  return { ...actual, listSupportThreadsAdmin: vi.fn(), getSupportThreadAdmin: vi.fn(), supportThreadCommand: vi.fn(),
           supportThreadFileLink: vi.fn() };
});
vi.mock("../api/v2/ops.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/v2/ops.api")>();
  return { ...actual, capabilities: vi.fn() };
});

import * as trust from "../api/v2/admin-trust.api";
import * as ops from "../api/v2/ops.api";
import { AdminSupportThreadsPanel, threadQuery } from "./AdminSupportThreadsPanel";

const m = <T,>(fn: T) => fn as unknown as ReturnType<typeof vi.fn>;

const thread = {
  id: "sth_1",
  booking_id: "bkg_1",
  requester_side: "client",
  requester_user_id: "usr_7",
  status: "open",
  staff_status: "waiting",
  message_count: 1,
  version: 1,
  created_at: "2026-09-25T08:00:00Z",
  assigned_to: null,
  carried_over_from_dispute: false,
  files: [{ ref: "smg_1.0", name: "Dalil 1 - mijoz, 25.09.2026, PNG", message_id: "smg_1", staff_only: false }],
  messages: [{ id: "smg_1", author: "client", text: "Haydovchi kechikdi", has_files: true, created_at: "2026-09-25T08:00:00Z" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  m(ops.capabilities).mockResolvedValue({ roles: [], capabilities: ["ops.view", "ops.trust_review"], driver_eligibility: null });
  m(trust.listSupportThreadsAdmin).mockResolvedValue([thread]);
  m(trust.getSupportThreadAdmin).mockResolvedValue(thread);
});

describe("threadQuery", () => {
  it("maps the filter chips to the API query", () => {
    expect(threadQuery("unassigned")).toEqual({ status: "open", assigned: "unassigned" });
    expect(threadQuery("me")).toEqual({ status: "open", assigned: "me" });
    expect(threadQuery("open")).toEqual({ status: "open" });
    expect(threadQuery("closed")).toEqual({ status: "closed" });
  });
});

describe("AdminSupportThreadsPanel", () => {
  it("lists the queue with requester and booking and opens a thread", async () => {
    render(<AdminSupportThreadsPanel />);
    const row = await screen.findByText(/Mijoz · bkg_1/);
    expect(screen.getByText("Navbatda (hech kim olmagan)")).toBeTruthy();
    fireEvent.click(row);
    await screen.findByText("Haydovchi kechikdi");
    expect(screen.getByText(/mas'ul: hech kim/)).toBeTruthy();
    expect(screen.queryByText(/pul qaytarmaydi/)).toBeNull();
    expect(m(trust.listSupportThreadsAdmin)).toHaveBeenCalledWith({ status: "open", assigned: "unassigned", limit: 50 });
  });

  it("takes, answers and closes through the command wrapper with the thread version", async () => {
    m(trust.supportThreadCommand).mockImplementation(async (_id: string, command: string) => ({
      ...thread, version: 2, assigned_to: "usr_op", staff_status: command === "close" ? "closed" : "assigned",
      status: command === "close" ? "closed" : "open",
    }));
    render(<AdminSupportThreadsPanel />);
    fireEvent.click(await screen.findByText(/Mijoz · bkg_1/));
    fireEvent.click(await screen.findByText("O'zimga olish"));
    await waitFor(() => expect(m(trust.supportThreadCommand)).toHaveBeenCalledWith("sth_1", "assign", { expected_version: 1, text: null }, expect.any(String)));
    fireEvent.change(screen.getByLabelText("Javob"), { target: { value: "Ko'rib chiqyapmiz" } });
    fireEvent.click(screen.getByText("Javob yuborish"));
    await waitFor(() => expect(m(trust.supportThreadCommand)).toHaveBeenCalledWith("sth_1", "reply", { expected_version: 2, text: "Ko'rib chiqyapmiz" }, expect.any(String)));
    fireEvent.click(screen.getByText("Yopish"));
    await waitFor(() => expect(m(trust.supportThreadCommand)).toHaveBeenCalledWith("sth_1", "close", expect.objectContaining({ expected_version: 2 }), expect.any(String)));
    expect(await screen.findByText(/Holat: Yopilgan/)).toBeTruthy();
  });

  it("shows the design's note, system line and staff-only marker, and counts the queue chip", async () => {
    m(trust.getSupportThreadAdmin).mockResolvedValue({
      ...thread,
      carried_over_from_dispute: true,
      messages: [
        ...thread.messages,
        { id: "smg_2", author: "operator", text: "Ichki eslatma", has_files: false, staff_only: true, created_at: "2026-09-25T08:05:00Z" },
      ],
    });
    render(<AdminSupportThreadsPanel />);
    expect(await screen.findByRole("button", { name: "Navbat · 1" })).toBeTruthy();
    expect(screen.getByText(/1 ta xabar/)).toBeTruthy();
    fireEvent.click(screen.getByText(/Mijoz · bkg_1/));
    expect(await screen.findByText("Bron bkg_1")).toBeTruthy();
    expect(screen.getByText(/^Ichki izoh: /)).toBeTruthy();
    expect(screen.queryByText(/Q141\/Q146/)).toBeNull(); // v3 §8.1: no subtitle
  });

  it("hides the commands without ops.trust_review", async () => {
    m(ops.capabilities).mockResolvedValue({ roles: [], capabilities: ["ops.view"], driver_eligibility: null });
    render(<AdminSupportThreadsPanel />);
    fireEvent.click(await screen.findByText(/Mijoz · bkg_1/));
    expect(await screen.findByText(/ops.trust_review huquqi kerak/)).toBeTruthy();
    expect(screen.queryByText("Javob yuborish")).toBeNull();
  });
});

describe("evidence files", () => {
  it("shows a readable name, never the storage key, and opens only a server-issued signed link", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    m(trust.supportThreadFileLink).mockResolvedValue({
      ref: "smg_1.0", name: "Dalil 1 - mijoz, 25.09.2026, PNG", url: "/api/v1/files/k?exp=1&sig=s",
      expires_at: "2026-09-25T09:00:00Z", content_type: "image/png",
    });
    render(<AdminSupportThreadsPanel />);
    fireEvent.click(await screen.findByText(/Mijoz · bkg_1/));
    expect(await screen.findByText("Dalil 1 - mijoz, 25.09.2026, PNG")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/dispute_evidence\//);
    fireEvent.click(screen.getByText("Ko'rish"));
    await waitFor(() => expect(m(trust.supportThreadFileLink)).toHaveBeenCalledWith("sth_1", "smg_1.0"));
    await waitFor(() => expect(open).toHaveBeenCalledWith(expect.stringContaining("/api/v1/files/k?exp=1&sig=s"), "_blank", "noopener,noreferrer"));
    open.mockRestore();
  });
});
