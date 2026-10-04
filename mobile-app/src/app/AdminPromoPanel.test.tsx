/**
 * Referral va bonuslar: every control follows the staff capabilities (DESIGN-ADMIN-DIFF 12.1, Q105/Q114/Q127/Q147),
 * every status command asks first. SYNTHETIC data only; the API layer is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const promo = vi.hoisted(() => ({
  adminActivateCampaign: vi.fn(),
  adminAddVersion: vi.fn(),
  adminApproveCombination: vi.fn(),
  adminApproveBudget: vi.fn(),
  adminBudgetRequests: vi.fn(),
  adminCampaign: vi.fn(),
  adminCampaigns: vi.fn(),
  adminCloseCampaign: vi.fn(),
  adminCreateCampaign: vi.fn(),
  adminDecideReview: vi.fn(),
  adminPauseCampaign: vi.fn(),
  adminReconciliation: vi.fn(),
  adminRejectBudget: vi.fn(),
  adminRequestBudget: vi.fn(),
  adminResumeCampaign: vi.fn(),
  adminResumeProcessing: vi.fn(),
  adminReviews: vi.fn(),
  adminRevokeCombination: vi.fn(),
  adminStartReview: vi.fn(),
  adminSuspendProcessing: vi.fn(),
  adminWithdrawBudget: vi.fn(),
}));
const ops = vi.hoisted(() => ({ capabilities: vi.fn() }));

vi.mock("../api/v2/promo.api", () => promo);
vi.mock("../api/v2/ops.api", () => ops);
vi.mock("../api/v2/mfa.api", () => ({ stepUp: vi.fn() }));

import { AdminPromoPanel } from "./AdminPromoPanel";

const BUDGET = {
  allocated_minor: 500_000_000, promised_minor: 140_000_000, granted_minor: 60_000_000, consumed_minor: 180_000_000,
  released_minor: 0, available_for_new_minor: 120_000_000, shortfall_minor: 0, reducible_minor: 120_000_000,
  pending_reinstatements_minor: 0, currency: "UZS",
};
const CAMPAIGN = {
  id: "pcm_1", name: "Synthetic invite", status: "active", service_type: "passenger", kind: "referral_client_client",
  family: "client_acquisition", version: 3, active_version_no: 1, budget: BUDGET, versions: [], combinations: [],
};
const OPERATOR = ["promo.campaign_view", "promo.fraud_review", "ops.view"];
const FINANCE = ["promo.campaign_view", "promo.budget_allocate", "ops.view"];
const SUPER = ["promo.campaign_view", "promo.campaign_manage", "promo.budget_allocate", "promo.fraud_review", "promo.fraud_decide"];

function budgetRequest(overrides: Record<string, unknown> = {}) {
  return {
    id: "pbr_1", campaign_id: "pcm_1", kind: "allocate", amount_minor: 200_000_000, currency: "UZS", reason: "synthetic",
    evidence_reference: "B-1", status: "pending", requested_by_me: false, needs_second_approver: true, version: 1,
    created_at: "2026-09-24T00:00:00Z", ...overrides,
  };
}

beforeEach(() => {
  for (const fn of Object.values(promo)) fn.mockReset();
  promo.adminCampaigns.mockResolvedValue([CAMPAIGN]);
  promo.adminCampaign.mockResolvedValue(CAMPAIGN);
  promo.adminBudgetRequests.mockResolvedValue([]);
  promo.adminReviews.mockResolvedValue([]);
  promo.adminReconciliation.mockResolvedValue([]);
});

function as(capabilities: string[]) {
  ops.capabilities.mockResolvedValue({ capabilities, roles: [], driver_eligibility: null });
}

describe("AdminPromoPanel", () => {
  it("shows an operator the campaign and its budget, but no status, version or budget control", async () => {
    as(OPERATOR);
    render(<AdminPromoPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Synthetic invite/ }));
    expect(await screen.findByText("Kamaytirish mumkin (B − S − L)")).toBeInTheDocument();
    expect(screen.getAllByText("1 200 000 so'm").length).toBeGreaterThan(0);
    expect(screen.queryByText("Aktivlashtirish")).toBeNull();
    expect(screen.queryByText("Pauza")).toBeNull();
    expect(screen.queryByText("Yangi versiya qo'shish")).toBeNull();
    expect(screen.queryByText("Byudjet o'zgarishi")).toBeNull();
    expect(screen.queryByText("Qoralama yaratish")).toBeNull();
    // there is no free "give a bonus" button anywhere (Q127/Q133)
    expect(screen.queryByText(/bonus berish/i)).toBeNull();
  });

  it("lets an operator start a review but not decide it (promo.fraud_decide is admin+)", async () => {
    as(OPERATOR);
    promo.adminReviews.mockResolvedValue([
      { id: "prv_1", kind: "identity_match", status: "open", reason_codes: ["identity_match"], evidence: [], version: 1, assigned_to_me: false },
    ]);
    render(<AdminPromoPanel />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tekshiruv navbati" }));
    const card = await screen.findByTestId("review-prv_1");
    expect(within(card).getByText("Tekshiruvni boshlash")).toBeInTheDocument();
    expect(within(card).queryByText("Tasdiqlash")).toBeNull();
    expect(within(card).queryByText("Rad etish")).toBeNull();
  });

  it("never offers reject on the retired parcel path (Q147)", async () => {
    as(SUPER);
    promo.adminReviews.mockResolvedValue([
      { id: "prv_2", kind: "qualification_path_retired", status: "open", reason_codes: [], evidence: [], version: 1, assigned_to_me: false, escalated_at: "2026-09-24T00:00:00Z" },
    ]);
    render(<AdminPromoPanel />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tekshiruv navbati" }));
    const card = await screen.findByTestId("review-prv_2");
    expect(within(card).getByText("Pochta dalili olib tashlangan - va'da saqlanadi")).toBeInTheDocument();
    expect(within(card).getByText("Rad etib bo'lmaydi; bajarish yo'li D-4 ochiq")).toBeInTheDocument();
    expect(within(card).getByText("muddati o'tgan (eskalatsiya)")).toBeInTheDocument();
    expect(within(card).queryByText("Rad etish")).toBeNull();
  });

  it("hides the review queue from finance and lets the requester only withdraw (Q114)", async () => {
    as(FINANCE);
    promo.adminBudgetRequests.mockResolvedValue([budgetRequest({ requested_by_me: true }), budgetRequest({ id: "pbr_2", kind: "reduce_allocation", amount_minor: 50_000_000, needs_second_approver: false })]);
    promo.adminApproveBudget.mockResolvedValue(budgetRequest({ id: "pbr_2", status: "posted" }));
    render(<AdminPromoPanel />);
    await screen.findByRole("tab", { name: "Kampaniyalar" });
    expect(screen.queryByRole("tab", { name: "Tekshiruv navbati" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Byudjet so'rovlari" }));
    const own = await screen.findByTestId("budget-pbr_1");
    expect(own).toHaveTextContent("Ajratish · 2 000 000 so'm · ikkinchi tasdiq kerak");
    expect(own).toHaveTextContent("Siz so'ragansiz — boshqa xodim tasdiqlaydi.");
    expect(within(own).getByText("Qaytarib olish")).toBeInTheDocument();
    expect(within(own).queryByText("Tasdiqlash")).toBeNull();
    const other = screen.getByTestId("budget-pbr_2");
    fireEvent.click(within(other).getByText("Tasdiqlash"));
    expect(promo.adminApproveBudget).not.toHaveBeenCalled();
    fireEvent.click(within(other).getByText("Ha, bajarish"));
    await waitFor(() => expect(promo.adminApproveBudget).toHaveBeenCalledWith("pbr_2", 1, undefined));
  });

  it("asks before pausing a campaign (super_admin)", async () => {
    as(SUPER);
    promo.adminPauseCampaign.mockResolvedValue({ ...CAMPAIGN, status: "paused", version: 4 });
    render(<AdminPromoPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Synthetic invite/ }));
    await screen.findByText("Holatni o'zgartirish");
    // combinations come first, the status block owns the last "Sabab (audit)" field above its buttons
    const reasons = screen.getAllByLabelText("Sabab (audit)");
    fireEvent.change(reasons[reasons.length - 1], { target: { value: "synthetic pause" } });
    fireEvent.click(screen.getByText("Pauza"));
    expect(screen.getByText("Kampaniya pauzaga qo'yilsinmi?")).toBeInTheDocument();
    expect(promo.adminPauseCampaign).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Ha, bajarish"));
    await waitFor(() => expect(promo.adminPauseCampaign).toHaveBeenCalledWith("pcm_1", { expected_version: 3, reason: "synthetic pause" }));
  });
});
