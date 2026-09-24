/**
 * Finance staff panel: render states, capability-gated actions, confirmation before money, idempotency keys, and
 * the Q48 gate message. SYNTHETIC data only; the API layer is mocked.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LedgerAdjustmentDTO, TopupAdminDTO } from "../api/v2/admin-finance.api";
import { ApiError } from "../types/api";

vi.mock("../api/v2/ops.api", () => ({ capabilities: vi.fn() }));
vi.mock("../api/v2/mfa.api", () => ({ stepUp: vi.fn() }));
vi.mock("../api/v2/admin-finance.api", () => ({
  financeMe: vi.fn(),
  listTopups: vi.fn(),
  approveTopup: vi.fn(),
  rejectTopup: vi.fn(),
  listAdjustments: vi.fn(),
  createAdjustment: vi.fn(),
  approveAdjustment: vi.fn(),
  rejectAdjustment: vi.fn(),
  withdrawAdjustment: vi.fn(),
  listCommissionPolicies: vi.fn(),
  createCommissionPolicy: vi.fn(),
  confirmCommissionPolicy: vi.fn(),
  endCommissionPolicy: vi.fn(),
  financeReconciliation: vi.fn(),
  financeReport: vi.fn(),
  splitAdjustmentSignals: vi.fn(),
  promoReport: vi.fn(),
}));

import * as api from "../api/v2/admin-finance.api";
import * as ops from "../api/v2/ops.api";
import { AdminFinancePanel } from "./AdminFinancePanel";
import { GATE_MESSAGE } from "./finance";

const m = vi.mocked;
const FINANCE = [
  "finance.reports",
  "finance.topup_approve",
  "finance.adjustment",
  "finance.adjustment_approve",
  "finance.commission_policy_view",
];

function topup(overrides: Partial<TopupAdminDTO> = {}): TopupAdminDTO {
  return {
    id: "tpu_synthetic1",
    amount_minor: 20_000_000,
    created_at: "2026-09-24T05:00:00Z",
    decided_at: null,
    driver: { id: "usr_driver" },
    evidence: {
      evidence_file_id: null,
      note: "synthetic",
      payer_reference: "card *0000",
      received_amount_minor: null,
      received_at: null,
      source_reference: null,
      source_type: null,
    },
    first_approver: null,
    second_approver: null,
    method: "bank_transfer",
    status: "pending",
    version: 3,
    ...overrides,
  };
}

function adjustment(overrides: Partial<LedgerAdjustmentDTO> = {}): LedgerAdjustmentDTO {
  return {
    id: "ladj_synthetic1",
    amount_minor: 150_000_000,
    created_at: "2026-09-24T05:00:00Z",
    direction: "credit",
    reason: "synthetic correction",
    requested_by: { id: "usr_other" },
    status: "pending_second_approval",
    version: 1,
    wallet_id: "wal_synthetic",
    ...overrides,
  };
}

function setup(caps: string[] = FINANCE, me = "usr_me") {
  m(ops.capabilities).mockResolvedValue({ capabilities: caps as never, roles: ["finance"], driver_eligibility: null });
  m(api.financeMe).mockResolvedValue({ id: me } as never);
  m(api.listTopups).mockResolvedValue({ items: [], nextCursor: null });
  m(api.listAdjustments).mockResolvedValue({ items: [], nextCursor: null });
  m(api.listCommissionPolicies).mockResolvedValue({ items: [], nextCursor: null });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AdminFinancePanel", () => {
  it("shows loading, then the honest empty state of the top-up queue", async () => {
    setup();
    render(<AdminFinancePanel />);
    expect(screen.getByText("Yuklanmoqda...")).toBeInTheDocument();
    expect(await screen.findByText("Bu holatda top-up so'rovi yo'q.")).toBeInTheDocument();
    expect(api.listTopups).toHaveBeenCalledWith(expect.objectContaining({ status: "pending" }));
    expect(screen.getByText(/So'rov va skrinshot pul emas/)).toBeInTheDocument();
  });

  it("says so when the staff member has no finance capability", async () => {
    setup(["ops.view"]);
    render(<AdminFinancePanel />);
    expect(await screen.findByText("Moliya bo'limi uchun ruxsatingiz yo'q.")).toBeInTheDocument();
    expect(api.listTopups).not.toHaveBeenCalled();
  });

  it("approves a top-up only after confirmation, with integer tiyin and an idempotency key", async () => {
    setup();
    m(api.listTopups).mockResolvedValue({ items: [topup()], nextCursor: null });
    m(api.approveTopup).mockResolvedValue(topup({ status: "approved", version: 4 }));
    render(<AdminFinancePanel />);
    fireEvent.click(await screen.findByText("Ko'rib chiqish"));
    expect(screen.getByText(/hali pul emas/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Hujjat raqami"), { target: { value: "BS-0001" } });
    fireEvent.change(screen.getByLabelText("Haqiqatda qabul qilingan summa (so'm)"), { target: { value: "200 000" } });
    fireEvent.change(screen.getByLabelText("Qabul qilingan vaqt (Toshkent)"), { target: { value: "2026-09-24T09:15" } });
    fireEvent.click(screen.getByText("Tasdiqlash"));
    expect(api.approveTopup).not.toHaveBeenCalled(); // confirmation first
    fireEvent.click(screen.getByText("Ha, bajarish"));
    await waitFor(() => expect(api.approveTopup).toHaveBeenCalledTimes(1));
    const [id, body, key] = m(api.approveTopup).mock.calls[0];
    expect(id).toBe("tpu_synthetic1");
    expect(body).toEqual({
      expected_version: 3,
      source_type: "bank_statement",
      source_reference: "BS-0001",
      received_amount_minor: 20_000_000,
      received_at: "2026-09-24T09:15:00+05:00",
      note: null,
    });
    expect(typeof key).toBe("string");
    expect(key.length).toBeGreaterThan(8);
    expect(await screen.findByText(/haydovchi balansiga o'tdi/)).toBeInTheDocument();
  });

  it("rejects a top-up with a reason and a key", async () => {
    setup();
    m(api.listTopups).mockResolvedValue({ items: [topup()], nextCursor: null });
    m(api.rejectTopup).mockResolvedValue(topup({ status: "rejected", version: 4 }));
    render(<AdminFinancePanel />);
    fireEvent.click(await screen.findByText("Ko'rib chiqish"));
    fireEvent.change(screen.getByLabelText("Rad etish sababi"), { target: { value: "no such transfer" } });
    fireEvent.click(screen.getByText("Rad etish"));
    fireEvent.click(screen.getByText("Ha, bajarish"));
    await waitFor(() => expect(api.rejectTopup).toHaveBeenCalledTimes(1));
    const [id, body, key] = m(api.rejectTopup).mock.calls[0];
    expect(id).toBe("tpu_synthetic1");
    expect(body).toEqual({ expected_version: 3, reason: "no such transfer" });
    expect(typeof key).toBe("string");
  });

  it("shows the Q48 production gate refusal as the launch gate, not a generic error", async () => {
    setup();
    m(api.listTopups).mockResolvedValue({ items: [topup()], nextCursor: null });
    m(api.approveTopup).mockRejectedValue(
      new ApiError(503, { code: "PRODUCTION_INVARIANTS_FAILED", message: "x", details: { failed: ["q48_gate"] } }),
    );
    render(<AdminFinancePanel />);
    fireEvent.click(await screen.findByText("Ko'rib chiqish"));
    fireEvent.change(screen.getByLabelText("Hujjat raqami"), { target: { value: "BS-0002" } });
    fireEvent.change(screen.getByLabelText("Haqiqatda qabul qilingan summa (so'm)"), { target: { value: "200000" } });
    fireEvent.change(screen.getByLabelText("Qabul qilingan vaqt (Toshkent)"), { target: { value: "2026-09-24T09:15" } });
    fireEvent.click(screen.getByText("Tasdiqlash"));
    fireEvent.click(screen.getByText("Ha, bajarish"));
    expect(await screen.findByText(GATE_MESSAGE)).toBeInTheDocument();
  });

  it("does not offer review to staff without finance.topup_approve", async () => {
    setup(["finance.reports"]);
    m(api.listTopups).mockResolvedValue({ items: [topup()], nextCursor: null });
    render(<AdminFinancePanel />);
    expect(await screen.findByText(/faqat faol moliya xodimi/)).toBeInTheDocument();
    expect(screen.queryByText("Ko'rib chiqish")).toBeNull();
  });

  it("never offers the requester approve/reject of their own adjustment, only withdraw", async () => {
    setup();
    m(api.listAdjustments).mockResolvedValue({ items: [adjustment({ requested_by: { id: "usr_me" } })], nextCursor: null });
    m(api.withdrawAdjustment).mockResolvedValue(adjustment({ status: "withdrawn", version: 2 }));
    render(<AdminFinancePanel />);
    fireEvent.click(await screen.findByText("Tuzatishlar"));
    expect(await screen.findByText("Qaytarib olish")).toBeInTheDocument();
    expect(screen.queryByText("Tasdiqlash")).toBeNull();
    fireEvent.click(screen.getByText("Qaytarib olish"));
    fireEvent.click(screen.getByText("Ha, bajarish"));
    await waitFor(() => expect(api.withdrawAdjustment).toHaveBeenCalledWith("ladj_synthetic1", { expected_version: 1, reason: null }, expect.any(String)));
  });

  it("lets a different approver approve someone else's adjustment with a key", async () => {
    setup();
    m(api.listAdjustments).mockResolvedValue({ items: [adjustment()], nextCursor: null });
    m(api.approveAdjustment).mockResolvedValue({ id: "ltx_synthetic", entries: [], reference: "x", created_at: "2026-09-24T05:00:00Z" });
    render(<AdminFinancePanel />);
    fireEvent.click(await screen.findByText("Tuzatishlar"));
    fireEvent.click(await screen.findByText("Tasdiqlash"));
    fireEvent.click(screen.getByText("Ha, bajarish"));
    await waitFor(() =>
      expect(api.approveAdjustment).toHaveBeenCalledWith("ladj_synthetic1", { expected_version: 1, note: null }, expect.any(String)),
    );
  });

  it("keeps commission policy read-only without the manage capability (Q2) and flags an unconfirmed seed (Q28)", async () => {
    setup();
    m(api.listCommissionPolicies).mockResolvedValue({
      items: [
        {
          id: "cpol_seed",
          kind: "standard",
          fee_bps: 1000,
          fee_percent: "10",
          effective_from: "2026-01-01T00:00:00Z",
          effective_to: null,
          created_at: "2026-01-01T00:00:00Z",
          created_by: null,
          is_active_now: true,
          is_confirmed: false,
          reason: "seed",
          scope: {},
          version: 1,
        },
      ],
      nextCursor: null,
    });
    render(<AdminFinancePanel />);
    fireEvent.click(await screen.findByText("Komissiya siyosati"));
    expect(await screen.findByText(/Faqat o'qish/)).toBeInTheDocument();
    expect(screen.getByText(/seed stavkasi tasdiqlanmagan/)).toBeInTheDocument();
    expect(screen.queryByText("Stavkani tasdiqlash")).toBeNull();
    expect(screen.queryByText("Siyosat yaratish")).toBeNull();
  });
});
