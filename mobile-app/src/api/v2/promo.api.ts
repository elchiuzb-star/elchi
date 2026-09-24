/**
 * Referral, bonus and promo administration (referral stage 5, ADR-0023 §16, §19).
 *
 * Every amount comes from the server; the app never computes a discount. Commands carry an Idempotency-Key that
 * the caller keeps for one user action (`promo.ts` `actionKey`), so a retry after a timeout replays the first
 * answer. Paths are written out in full so tests/test_mobile_v2_client_contract.py can check them.
 */
import { newIdempotencyKey, v2AdminRequest, v2Request, type Schemas } from "./http";

export type ReferralCodeDTO = Schemas["ReferralCodeDTO"];
export type ReferralCodeCheckDTO = Schemas["ReferralCodeCheckDTO"];
export type AttributionDTO = Schemas["AttributionDTO"];
export type EnrollmentOfferDTO = Schemas["EnrollmentOfferDTO"];
export type EnrollmentDTO = Schemas["EnrollmentDTO"];
export type MyReferralsDTO = Schemas["MyReferralsDTO"];
export type PromoBalanceDTO = Schemas["PromoBalanceDTO"];
export type ProposalPromoClientDTO = Schemas["ProposalPromoClientDTO"];
export type PromoPreviewDTO = Schemas["PromoPreviewDTO"];
export type ProgressDTO = Schemas["ProgressDTO"];
export type CombinationDTO = Schemas["CombinationDTO"];
export type CampaignDTO = Schemas["CampaignDTO"];
export type CampaignVersionCreate = Schemas["CampaignVersionCreate"];
export type BudgetRequestDTO = Schemas["BudgetRequestDTO"];
export type ReviewDTO = Schemas["ReviewDTO"];
export type ReconciliationIssueDTO = Schemas["ReconciliationIssueDTO"];

// --- client -----------------------------------------------------------------------------------------------------

/** My own referral code (created on first use). `share_url` is null until a link host is configured. */
export function myReferralCode(idempotencyKey: string = newIdempotencyKey()) {
  return v2Request<ReferralCodeDTO>("/me/referral-code", { method: "POST", idempotencyKey });
}

/** Unauthenticated, rate limited; answers only `valid`. */
export function checkReferralCode(code: string) {
  return v2Request<ReferralCodeCheckDTO>(`/public/referral-codes/${encodeURIComponent(code)}`, { auth: false });
}

export function attributeReferral(code: string, audience: "client" | "driver", idempotencyKey: string) {
  return v2Request<AttributionDTO>("/referrals/attribution", { method: "POST", body: { code, audience }, idempotencyKey });
}

export function referralOffers(audience: "client" | "driver") {
  return v2Request<EnrollmentOfferDTO[]>("/referrals/offers", { query: { audience } });
}

export function enrollInCampaign(offer: EnrollmentOfferDTO, idempotencyKey: string) {
  return v2Request<EnrollmentDTO>("/referrals/enrollments", {
    method: "POST",
    body: {
      attribution_id: offer.attribution_id,
      campaign_id: offer.campaign_id,
      version_no: offer.version_no,
      terms_fingerprint: offer.terms_fingerprint,
    },
    idempotencyKey,
  });
}

export function myReferrals() {
  return v2Request<MyReferralsDTO>("/me/referrals");
}

export function myPromoBalance() {
  return v2Request<PromoBalanceDTO>("/me/promo-balance");
}

/** What my bonus would do to a price I am about to offer or counter - or, when nothing applies, a plain reason. */
export function listingPromoPreview(listingId: string, unitPriceMinor: number, quantity = 1) {
  return v2Request<PromoPreviewDTO>(`/listings/${listingId}/promo-preview`, {
    query: { unit_price_minor: unitPriceMinor, quantity },
  });
}

/**
 * Q126: the author of the open version confirms its promo terms again from this session (the other side's accept said
 * the earlier confirmation went stale). The client repeats the exact numbers it is shown; the driver sends none.
 */
export function confirmProposalPromo(
  threadId: string,
  proposalVersionId: string,
  consent: { passenger_bonus_minor: number; cash_due_minor: number } | undefined,
  idempotencyKey: string,
) {
  return v2Request<Schemas["ProposalThreadDTO"]>(`/proposals/${threadId}/promo-confirmation`, {
    method: "POST",
    body: { proposal_version_id: proposalVersionId, ...(consent ? { promo_consent: consent } : {}) },
    idempotencyKey,
  });
}

// --- staff (admin session; decisions need a fresh MFA step-up on the server) ----------------------------------

export function adminCampaigns() {
  return v2AdminRequest<CampaignDTO[]>("/admin/promo/campaigns");
}

export function adminCampaign(campaignId: string) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}`);
}

export function adminCreateCampaign(body: { kind: string; service_type: "passenger" | "parcel"; name: string }) {
  return v2AdminRequest<CampaignDTO>("/admin/promo/campaigns", { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function adminAddVersion(campaignId: string, body: CampaignVersionCreate) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/versions`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

type CampaignCommandBody = { expected_version: number; reason: string; version_no?: number };

export function adminActivateCampaign(campaignId: string, body: CampaignCommandBody) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/activate`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function adminPauseCampaign(campaignId: string, body: CampaignCommandBody) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/pause`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function adminResumeCampaign(campaignId: string, body: CampaignCommandBody) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/resume`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function adminCloseCampaign(campaignId: string, body: CampaignCommandBody) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/close`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function adminSuspendProcessing(campaignId: string, reason: string) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/processing/suspend`, {
    method: "POST",
    body: { reason },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminResumeProcessing(campaignId: string, reason: string) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/processing/resume`, {
    method: "POST",
    body: { reason },
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Q123: allow two campaigns on one booking with an explicitly chosen cost basis (super_admin, step-up). */
export function adminApproveCombination(
  campaignId: string,
  body: { other_campaign_id: string; cost_basis: "shared" | "additive"; reason: string },
) {
  return v2AdminRequest<CampaignDTO>(`/admin/promo/campaigns/${campaignId}/combinations`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminRevokeCombination(combinationId: string, expectedVersion: number, reason: string) {
  return v2AdminRequest<CombinationDTO>(`/admin/promo/combinations/${combinationId}/revoke`, {
    method: "POST",
    body: { expected_version: expectedVersion, reason },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminBudgetRequests(status?: string) {
  return v2AdminRequest<BudgetRequestDTO[]>("/admin/promo/budget-requests", { query: { status } });
}

export function adminRequestBudget(
  campaignId: string,
  body: { kind: "allocate" | "reduce_allocation" | "funding_loss"; amount_minor: number; reason: string; evidence_reference?: string | null },
) {
  return v2AdminRequest<BudgetRequestDTO>(`/admin/promo/campaigns/${campaignId}/budget-requests`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminApproveBudget(requestId: string, expectedVersion: number, note?: string) {
  return v2AdminRequest<BudgetRequestDTO>(`/admin/promo/budget-requests/${requestId}/approve`, {
    method: "POST",
    body: { expected_version: expectedVersion, reason: note ?? null },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminRejectBudget(requestId: string, expectedVersion: number, reason: string) {
  return v2AdminRequest<BudgetRequestDTO>(`/admin/promo/budget-requests/${requestId}/reject`, {
    method: "POST",
    body: { expected_version: expectedVersion, reason },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminWithdrawBudget(requestId: string, expectedVersion: number) {
  return v2AdminRequest<BudgetRequestDTO>(`/admin/promo/budget-requests/${requestId}/withdraw`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminReviews(openOnly = true) {
  return v2AdminRequest<ReviewDTO[]>("/admin/promo/reviews", { query: { open_only: openOnly } });
}

export function adminStartReview(reviewId: string, note?: string) {
  return v2AdminRequest<ReviewDTO>(`/admin/promo/reviews/${reviewId}/start`, {
    method: "POST",
    body: { note: note ?? null },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminDecideReview(reviewId: string, decision: "approve" | "reject", note: string, expectedVersion: number) {
  return v2AdminRequest<ReviewDTO>(`/admin/promo/reviews/${reviewId}/decide`, {
    method: "POST",
    body: { decision, note, expected_version: expectedVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function adminReconciliation() {
  return v2AdminRequest<ReconciliationIssueDTO[]>("/admin/promo/reconciliation");
}
