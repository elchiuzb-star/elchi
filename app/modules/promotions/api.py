"""API v2 promotions router (referral stage 5, ADR-0023 §16, §19). Mounted by the integrator.

* The actor is always the authenticated session (``current_user_id``); no body field names a user, a role or a
  capability. Capabilities are server-computed (``portal.capabilities``).
* Object access: an attribution, enrollment, lot or bonus of another user answers 404 like an unknown id.
* Budget, campaign and review *decisions* need the capability **and** a real recent MFA step-up
  (``portal.require_step_up``): without an active factor these endpoints stay closed.
* Money and eligibility are decided by the existing services (``referral``, ``service``, ``qualification``);
  nothing here computes an amount.
* Abuse-prone endpoints (public code check per source, attribution per user) are rate limited (``promo_rate_events``).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v2.web import ERROR_RESPONSES, current_user_id, get_session, run_command
from app.contracts.dto import Envelope
from app.contracts.enums import Capability, PromoInstrument, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions import portal, referral, reporting
from app.modules.promotions import service as promo_service
from app.modules.promotions.models import PromoCampaign, PromoCampaignVersion
from app.modules.promotions.schemas import (
    AttributionDTO,
    AttributionRequest,
    BudgetDTO,
    BudgetRequestCreate,
    BudgetRequestDecision,
    BudgetRequestDTO,
    CampaignCommand,
    CampaignCreate,
    CampaignDTO,
    CampaignVersionCreate,
    CampaignVersionDTO,
    CombinationCreate,
    CombinationDTO,
    CombinationRevoke,
    DisclosureDTO,
    EnrollmentDTO,
    EnrollmentOfferDTO,
    EnrollmentRequest,
    InvitedCountsDTO,
    MilestoneDTO,
    MyReferralsDTO,
    ProcessingCommand,
    ProgressDTO,
    PromoBalanceDTO,
    PromoBucketDTO,
    PromoLotDTO,
    PromoReportDTO,
    ReconciliationIssueDTO,
    ReferralCodeCheckDTO,
    ReferralCodeDTO,
    ReviewDecision,
    ReviewDTO,
    ReviewStart,
)

router = APIRouter(tags=["v2 Promotions"])


def _client_ip(request: Request) -> str:
    """The same source rule as the OTP limiter (the proxy's left-most X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enabled(session: Session) -> None:
    referral._require_promotions_enabled(session)


# --- DTO builders ----------------------------------------------------------------------------------------------------


def _attribution_dto(row) -> AttributionDTO:  # noqa: ANN001
    return AttributionDTO(id=portal.attribution_public_id(row),
                          audience="driver" if row.family == "driver_acquisition" else "client", status=row.status,
                          attributed_at=ensure_aware_utc(row.attributed_at),
                          window_ends_at=ensure_aware_utc(row.window_ends_at))


def _enrollment_dto(view: portal.EnrollmentView, session: Session | None = None) -> EnrollmentDTO:
    e = view.enrollment
    progress = None
    if session is not None and view.side == "referee" and e.status == "promised":
        from app.modules.promotions.qualification import progress_for

        found = progress_for(session, e)
        if found is not None:
            progress = ProgressDTO(unit=found.unit, required=found.required, done=found.done,
                                   in_review=found.in_review, remaining=found.remaining,
                                   milestones=[MilestoneDTO(threshold=t, reached=r) for t, r in found.milestones])
    return EnrollmentDTO(id=portal.enrollment_public_id(e), campaign_id=portal.campaign_public_id(view.campaign),
                         campaign_name=view.campaign.name, service_type=ServiceType(view.campaign.service_type),
                         side=view.side, status=e.status, qualification_status=view.qualification_status,
                         enrolled_at=ensure_aware_utc(e.enrolled_at),
                         qualification_deadline=ensure_aware_utc(e.qualification_deadline), progress=progress)


def _combination_dto(session: Session, row) -> CombinationDTO:  # noqa: ANN001
    ids = [portal.campaign_public_id(session.get(PromoCampaign, cid)) for cid in (row.campaign_low_id, row.campaign_high_id)]
    return CombinationDTO(id=portal.combination_public_id(row), campaign_ids=ids, cost_basis=row.cost_basis,
                          status=row.status, reason=row.reason, created_at=ensure_aware_utc(row.created_at),
                          revoked_at=None if row.revoked_at is None else ensure_aware_utc(row.revoked_at),
                          version=row.version)


def _budget_dto(session: Session, campaign: PromoCampaign) -> BudgetDTO:
    position = promo_service.budget_position(session, campaign.id)
    pending = promo_service.pending_reinstatements_minor(session, campaign.id)
    return BudgetDTO(allocated_minor=position.allocated_minor, promised_minor=position.promised_minor,
                     granted_minor=position.granted_minor, consumed_minor=position.consumed_minor,
                     released_minor=position.released_minor, available_for_new_minor=position.available_for_new_minor,
                     shortfall_minor=position.shortfall_minor, pending_reinstatements_minor=pending,
                     reducible_minor=position.reducible_minor(pending))


def _version_dto(session: Session, campaign: PromoCampaign, version: PromoCampaignVersion) -> CampaignVersionDTO:
    terms = promo_service.version_terms(session, campaign, version)
    return CampaignVersionDTO(
        version_no=version.version_no, referrer_reward_minor=version.referrer_reward_minor,
        referee_reward_minor=version.referee_reward_minor, referrer_instrument=version.referrer_instrument,
        referee_instrument=version.referee_instrument,
        milestone_thresholds=None if version.milestone_thresholds is None else list(version.milestone_thresholds),
        min_distinct_clients=version.min_distinct_clients, enrollment_limit=version.enrollment_limit,
        qualification_window_s=version.qualification_window_s, reward_validity_s=version.reward_validity_s,
        review_sla_s=version.review_sla_s, restoration_grace_s=version.restoration_grace_s,
        max_discount_share_bps=version.max_discount_share_bps,
        max_discount_per_booking_minor=version.max_discount_per_booking_minor,
        passenger_bonus_max_per_booking_minor=version.passenger_bonus_max_per_booking_minor,
        driver_credit_max_per_booking_minor=version.driver_credit_max_per_booking_minor,
        variable_cost_fixed_minor=version.variable_cost_fixed_minor, variable_cost_bps=version.variable_cost_bps,
        min_margin_minor=version.min_margin_minor, approval_reference=version.approval_reference,
        missing_for_activation=list(terms.missing_for_activation()), created_at=ensure_aware_utc(version.created_at))


def _campaign_dto(session: Session, campaign: PromoCampaign, *, with_versions: bool = False) -> CampaignDTO:
    versions = portal.campaign_versions(session, campaign)
    active = next((v.version_no for v in versions if v.id == campaign.active_version_id), None)
    return CampaignDTO(
        id=portal.campaign_public_id(campaign), name=campaign.name, kind=campaign.kind, family=campaign.family,
        service_type=ServiceType(campaign.service_type), status=campaign.status, version=campaign.version,
        active_version_no=active,
        processing_suspended_at=None if campaign.processing_suspended_at is None
        else ensure_aware_utc(campaign.processing_suspended_at),
        processing_suspend_reason=campaign.processing_suspend_reason, budget=_budget_dto(session, campaign),
        versions=[_version_dto(session, campaign, v) for v in versions] if with_versions else [],
        combinations=[_combination_dto(session, row) for row in promo_service.combinations_of(session, campaign.id)]
        if with_versions else [])


def _budget_request_dto(session: Session, row, user_id: int) -> BudgetRequestDTO:  # noqa: ANN001
    from app.contracts.promo import budget_change_requires_second_approver

    return BudgetRequestDTO(
        id=portal.budget_request_public_id(row),
        campaign_id=portal.campaign_public_id(session.get(PromoCampaign, row.campaign_id)), kind=row.kind,
        amount_minor=row.amount_minor, reason=row.reason, evidence_reference=row.evidence_reference, status=row.status,
        requested_by_me=row.requested_by == user_id,
        needs_second_approver=budget_change_requires_second_approver(row.amount_minor),
        decided_at=None if row.decided_at is None else ensure_aware_utc(row.decided_at), version=row.version,
        created_at=ensure_aware_utc(row.created_at))


def _review_dto(session: Session, row, user_id: int) -> ReviewDTO:  # noqa: ANN001
    campaign = session.get(PromoCampaign, row.campaign_id) if row.campaign_id else None
    return ReviewDTO(
        id=portal.review_public_id(row), kind=row.kind, status=row.status, reason_codes=list(row.reason_codes),
        evidence=list(row.evidence), campaign_id=portal.campaign_public_id(campaign) if campaign else None,
        opened_at=ensure_aware_utc(row.opened_at), due_at=None if row.due_at is None else ensure_aware_utc(row.due_at),
        escalated_at=None if row.escalated_at is None else ensure_aware_utc(row.escalated_at),
        assigned_to_me=row.assigned_to == user_id, decision_note=row.decision_note,
        decided_at=None if row.decided_at is None else ensure_aware_utc(row.decided_at), version=row.version)


# --- client: code, attribution, enrollment, balance ------------------------------------------------------------------


@router.post("/me/referral-code", response_model=Envelope[ReferralCodeDTO], responses=ERROR_RESPONSES)
def my_referral_code(request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                     user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """The caller's own code, created on first use. The code is random; it says nothing about its owner."""

    def handler() -> ReferralCodeDTO:
        _enabled(session)
        code = referral.issue_referral_code(session, owner_user_id=user_id)
        url = portal.share_url(code.code)
        return ReferralCodeDTO(code=code.code, share_url=url,
                               link_status="configured_unverified" if url else "not_configured")

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=None,
                       handler=handler, resource_type="referral_code")


@router.get("/public/referral-codes/{code}", response_model=Envelope[ReferralCodeCheckDTO], responses=ERROR_RESPONSES)
def check_referral_code(code: str, request: Request, session: Session = Depends(get_session)) -> Envelope[ReferralCodeCheckDTO]:
    """No authentication. Unknown, revoked and inactive-owner codes give the same answer. Rate limited per source."""
    from app.core.config import settings

    _enabled(session)
    try:
        portal.consume_rate(session, action="code_check", source=f"ip:{_client_ip(request)}",
                            limit=settings.referral_code_checks_per_ip_per_minute, window=portal.CODE_CHECK_WINDOW)
        result = referral.check_code(session, code[:32])
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return Envelope[ReferralCodeCheckDTO](data=ReferralCodeCheckDTO(valid=result.valid))


@router.post("/referrals/attribution", response_model=Envelope[AttributionDTO], status_code=201, responses=ERROR_RESPONSES)
def attribute(body: AttributionRequest, request: Request,
              idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
              user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Attach the code to the *caller*. A refusal never blocks sign-up; the first attribution is never replaced."""
    from app.core.config import settings

    source = f"user:{user_id}"

    def handler() -> AttributionDTO:
        _enabled(session)
        portal.check_rate(session, action="attribution", source=source,
                          limit=settings.referral_attributions_per_user_per_hour, window=portal.ATTRIBUTION_WINDOW)
        row = referral.attribute(session, referee_user_id=user_id, raw_code=body.code, audience_role=body.audience,
                                 idempotency_key=idempotency_key)
        return _attribution_dto(row)

    def count_attempt(replayed: bool) -> None:
        if not replayed:  # a refused guess counts too; an idempotent replay does not
            portal.record_rate(session, action="attribution", source=source)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="referral_attribution",
                       after_command=count_attempt)


@router.get("/referrals/offers", response_model=Envelope[list[EnrollmentOfferDTO]], responses=ERROR_RESPONSES)
def offers(audience: str = Query(pattern="^(client|driver)$"), user_id: int = Depends(current_user_id),
           session: Session = Depends(get_session)) -> Envelope[list[EnrollmentOfferDTO]]:
    _enabled(session)
    rows = portal.offers_for(session, user_id, audience)
    return Envelope[list[EnrollmentOfferDTO]](data=[
        EnrollmentOfferDTO(
            campaign_id=portal.campaign_public_id(row.campaign), campaign_name=row.campaign.name,
            service_type=ServiceType(row.campaign.service_type),
            attribution_id=portal.attribution_public_id(row.attribution), version_no=row.version_no,
            terms_fingerprint=row.offer.terms_fingerprint,
            disclosures=[DisclosureDTO(code=k, value=list(v) if isinstance(v, tuple) else v)
                         for k, v in row.offer.disclosures.items()],
            parcel_sender_pays_only=row.campaign.service_type == ServiceType.PARCEL.value)
        for row in rows])


@router.post("/referrals/enrollments", response_model=Envelope[EnrollmentDTO], status_code=201, responses=ERROR_RESPONSES)
def enroll(body: EnrollmentRequest, request: Request,
           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
           user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Join a campaign under exactly the terms shown (fingerprint). Changed terms -> 409, show the new offer."""
    from app.modules.promotions import identity as identity_keys

    def handler() -> EnrollmentDTO:
        _enabled(session)
        attribution = portal.own_attribution(session, body.attribution_id, user_id)  # someone else's -> 404
        campaign = portal.get_campaign(session, body.campaign_id)
        version = portal.campaign_version(session, campaign, body.version_no)
        row = referral.enroll(session, referee_user_id=user_id, attribution_id=attribution.id, campaign_id=campaign.id,
                              accepted_campaign_version_id=version.id,
                              accepted_terms_fingerprint=body.terms_fingerprint, idempotency_key=idempotency_key,
                              keys=identity_keys.configured_keys())
        return _enrollment_dto(portal.EnrollmentView(row, campaign, None, "referee"))

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="promo_enrollment")


@router.get("/me/referrals", response_model=Envelope[MyReferralsDTO], responses=ERROR_RESPONSES)
def my_referrals(user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> Envelope[MyReferralsDTO]:
    counts = portal.invited_counts(session, user_id)
    return Envelope[MyReferralsDTO](data=MyReferralsDTO(
        attributions=[_attribution_dto(row) for row in portal.my_attributions(session, user_id)],
        enrollments=[_enrollment_dto(view, session) for view in portal.my_enrollments(session, user_id)],
        invited=InvitedCountsDTO(**{k: v for k, v in counts.items() if k in InvitedCountsDTO.model_fields})))


@router.get("/me/promo-balance", response_model=Envelope[PromoBalanceDTO], responses=ERROR_RESPONSES)
def my_promo_balance(user_id: int = Depends(current_user_id),
                     session: Session = Depends(get_session)) -> Envelope[PromoBalanceDTO]:
    """The caller's own discount rights only. Available even with promotions off: nothing here can be spent then."""
    buckets, lots = portal.promo_balance(session, user_id)
    return Envelope[PromoBalanceDTO](data=PromoBalanceDTO(
        buckets=[PromoBucketDTO(instrument=PromoInstrument(b.instrument), service_type=ServiceType(b.service_type),
                                available_minor=b.available_minor, reserved_minor=b.reserved_minor,
                                under_review_minor=b.under_review_minor, consumed_minor=b.consumed_minor,
                                expired_minor=b.expired_minor, reversed_minor=b.reversed_minor,
                                next_expiry_at=None if b.next_expiry_at is None else ensure_aware_utc(b.next_expiry_at))
                 for b in buckets],
        lots=[PromoLotDTO(id=portal.lot_public_id(lot), instrument=PromoInstrument(lot.instrument),
                          service_type=ServiceType(lot.service_type), status=lot.status, amount_minor=lot.amount_minor,
                          available_minor=promo_service._available(lot), reserved_minor=lot.reserved_minor,
                          consumed_minor=lot.consumed_minor, expired_minor=lot.expired_minor,
                          available_from=None if lot.available_from is None else ensure_aware_utc(lot.available_from),
                          expires_at=ensure_aware_utc(lot.expires_at)) for lot in lots]))


# --- staff: campaigns ---------------------------------------------------------------------------------------------------


@router.get("/admin/promo/campaigns", response_model=Envelope[list[CampaignDTO]], responses=ERROR_RESPONSES)
def list_campaigns(user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> Envelope[list[CampaignDTO]]:
    portal.require(session, user_id, Capability.PROMO_CAMPAIGN_VIEW)
    return Envelope[list[CampaignDTO]](data=[_campaign_dto(session, c) for c in portal.campaigns(session)])


@router.get("/admin/promo/campaigns/{campaign_id}", response_model=Envelope[CampaignDTO], responses=ERROR_RESPONSES)
def get_campaign(campaign_id: str, user_id: int = Depends(current_user_id),
                 session: Session = Depends(get_session)) -> Envelope[CampaignDTO]:
    portal.require(session, user_id, Capability.PROMO_CAMPAIGN_VIEW)
    return Envelope[CampaignDTO](data=_campaign_dto(session, portal.get_campaign(session, campaign_id), with_versions=True))


@router.post("/admin/promo/campaigns", response_model=Envelope[CampaignDTO], status_code=201, responses=ERROR_RESPONSES)
def create_campaign(body: CampaignCreate, request: Request,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    def handler() -> CampaignDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_CAMPAIGN_MANAGE)
        campaign = promo_service.create_campaign(session, actor_user_id=user_id, actor_capabilities=caps,
                                                 kind=body.kind, service_type=body.service_type, name=body.name)
        return _campaign_dto(session, campaign, with_versions=True)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="promo_campaign")


@router.post("/admin/promo/campaigns/{campaign_id}/versions", response_model=Envelope[CampaignDTO], status_code=201,
             responses=ERROR_RESPONSES)
def add_version(campaign_id: str, body: CampaignVersionCreate, request: Request,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    from app.contracts.promo import PromoMarginPolicy

    def handler() -> CampaignDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_CAMPAIGN_MANAGE)
        campaign = portal.get_campaign(session, campaign_id)
        seconds = (lambda v: None if v is None else timedelta(seconds=v))  # noqa: E731
        terms = promo_service.VersionTerms(
            referrer_reward_minor=body.referrer_reward_minor, referee_reward_minor=body.referee_reward_minor,
            referrer_instrument=body.referrer_instrument, referee_instrument=body.referee_instrument,
            milestone_thresholds=None if body.milestone_thresholds is None else tuple(body.milestone_thresholds),
            min_distinct_clients=body.min_distinct_clients, enrollment_limit=body.enrollment_limit,
            qualification_window=seconds(body.qualification_window_s), reward_validity=seconds(body.reward_validity_s),
            review_sla=seconds(body.review_sla_s), restoration_grace=seconds(body.restoration_grace_s),
            margin_policy=PromoMarginPolicy(
                max_discount_share_bps=body.max_discount_share_bps,
                max_discount_per_booking_minor=body.max_discount_per_booking_minor,
                passenger_bonus_max_per_booking_minor=body.passenger_bonus_max_per_booking_minor,
                driver_credit_max_per_booking_minor=body.driver_credit_max_per_booking_minor,
                variable_cost_fixed_minor=body.variable_cost_fixed_minor, variable_cost_bps=body.variable_cost_bps,
                min_margin_minor=body.min_margin_minor),
            approval_reference=body.approval_reference, note=body.note)
        promo_service.add_campaign_version(session, actor_user_id=user_id, actor_capabilities=caps,
                                           campaign_id=campaign.id, terms=terms)
        return _campaign_dto(session, campaign, with_versions=True)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="promo_campaign")


def _campaign_command(command: str, campaign_id: str, body: CampaignCommand, request: Request,
                      idempotency_key: str | None, user_id: int, session: Session) -> JSONResponse:
    def handler() -> CampaignDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_CAMPAIGN_MANAGE)
        campaign = portal.get_campaign(session, campaign_id)
        common = dict(actor_user_id=user_id, actor_capabilities=caps, campaign_id=campaign.id,
                      expected_version=body.expected_version, reason=body.reason)
        if command == "activate":
            if body.version_no is None:
                raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "version_no"})
            version = portal.campaign_version(session, campaign, body.version_no)
            promo_service.activate_campaign(session, version_id=version.id, **common)
        else:
            getattr(promo_service, f"{command}_campaign")(session, **common)
        session.refresh(campaign)
        return _campaign_dto(session, campaign, with_versions=True)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="promo_campaign")


def _register_campaign_command(command: str) -> None:
    def endpoint(campaign_id: str, body: CampaignCommand, request: Request,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
        return _campaign_command(command, campaign_id, body, request, idempotency_key, user_id, session)

    endpoint.__name__ = f"campaign_{command}"
    router.add_api_route(f"/admin/promo/campaigns/{{campaign_id}}/{command}", endpoint, methods=["POST"],
                         response_model=Envelope[CampaignDTO], responses=ERROR_RESPONSES, name=f"campaign_{command}")


for _command in ("activate", "pause", "resume", "close"):
    _register_campaign_command(_command)


def _processing(action: str, campaign_id: str, body: ProcessingCommand, request: Request, idempotency_key: str | None,
                user_id: int, session: Session) -> JSONResponse:
    """Operational stop of qualification/grant processing (Q122): deletes, releases and grants nothing."""
    from app.modules.promotions import qualification

    def handler() -> CampaignDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_CAMPAIGN_MANAGE)
        campaign = portal.get_campaign(session, campaign_id)
        fn = qualification.suspend_processing if action == "suspend" else qualification.resume_processing
        fn(session, campaign_id=campaign.id, actor_user_id=user_id, actor_capabilities=caps, reason=body.reason)
        session.refresh(campaign)
        return _campaign_dto(session, campaign, with_versions=True)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="promo_campaign")


def _register_processing(action: str) -> None:
    def endpoint(campaign_id: str, body: ProcessingCommand, request: Request,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
        return _processing(action, campaign_id, body, request, idempotency_key, user_id, session)

    endpoint.__name__ = f"processing_{action}"
    router.add_api_route(f"/admin/promo/campaigns/{{campaign_id}}/processing/{action}", endpoint, methods=["POST"],
                         response_model=Envelope[CampaignDTO], responses=ERROR_RESPONSES, name=f"processing_{action}")


for _action in ("suspend", "resume"):
    _register_processing(_action)


# --- staff: budget ------------------------------------------------------------------------------------------------------


@router.post("/admin/promo/campaigns/{campaign_id}/combinations", response_model=Envelope[CampaignDTO], status_code=201,
             responses=ERROR_RESPONSES)
def approve_combination(campaign_id: str, body: CombinationCreate, request: Request,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                        user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Q123: allow two campaigns on one booking with an explicit cost basis (super_admin + real MFA step-up)."""
    def handler() -> CampaignDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_CAMPAIGN_MANAGE)
        campaign = portal.get_campaign(session, campaign_id)
        other = portal.get_campaign(session, body.other_campaign_id)
        promo_service.approve_combination(session, actor_user_id=user_id, actor_capabilities=caps,
                                          campaign_a=campaign.id, campaign_b=other.id, cost_basis=body.cost_basis,
                                          reason=body.reason)
        return _campaign_dto(session, campaign, with_versions=True)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="promo_combination")


@router.post("/admin/promo/combinations/{combination_id}/revoke", response_model=Envelope[CombinationDTO],
             responses=ERROR_RESPONSES)
def revoke_combination(combination_id: str, body: CombinationRevoke, request: Request,
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                       user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Q123: new bookings stop combining the pair; agreements already made keep their recorded cost basis."""
    def handler() -> CombinationDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_CAMPAIGN_MANAGE)
        row = portal.get_combination(session, combination_id)
        row = promo_service.revoke_combination(session, actor_user_id=user_id, actor_capabilities=caps,
                                               combination_id=row.id, expected_version=body.expected_version,
                                               reason=body.reason)
        return _combination_dto(session, row)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="promo_combination")


@router.get("/admin/promo/budget-requests", response_model=Envelope[list[BudgetRequestDTO]], responses=ERROR_RESPONSES)
def list_budget_requests(status: str | None = Query(default=None, pattern="^(pending|posted|rejected|withdrawn)$"),
                         user_id: int = Depends(current_user_id),
                         session: Session = Depends(get_session)) -> Envelope[list[BudgetRequestDTO]]:
    portal.require(session, user_id, Capability.PROMO_CAMPAIGN_VIEW)
    return Envelope[list[BudgetRequestDTO]](data=[_budget_request_dto(session, r, user_id)
                                                  for r in portal.budget_requests(session, status=status)])


@router.post("/admin/promo/campaigns/{campaign_id}/budget-requests", response_model=Envelope[BudgetRequestDTO],
             status_code=201, responses=ERROR_RESPONSES)
def request_budget(campaign_id: str, body: BudgetRequestCreate, request: Request,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Up to the two-person threshold it posts on the requester's authority; above it a *different* finance
    approver must approve with their own session and step-up (Q17, Q114)."""

    def handler() -> BudgetRequestDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_BUDGET_ALLOCATE)
        campaign = portal.get_campaign(session, campaign_id)
        row = promo_service.request_budget_change(session, actor_user_id=user_id, actor_capabilities=caps,
                                                  campaign_id=campaign.id, kind=body.kind, amount_minor=body.amount_minor,
                                                  reason=body.reason, evidence_reference=body.evidence_reference)
        return _budget_request_dto(session, row, user_id)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="promo_budget_request")


def _decide_budget(decision: str, request_id: str, body: BudgetRequestDecision, request: Request,
                   idempotency_key: str | None, user_id: int, session: Session) -> JSONResponse:
    def handler() -> BudgetRequestDTO:
        row = portal.get_budget_request(session, request_id)
        if decision == "withdraw":  # only the requester, on their own session (no extra money moves)
            portal.require(session, user_id, Capability.PROMO_BUDGET_ALLOCATE)
            row = promo_service.withdraw_budget_request(session, actor_user_id=user_id, request_id=row.id,
                                                        expected_version=body.expected_version)
        else:
            caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_BUDGET_ALLOCATE)
            if decision == "approve":
                row = promo_service.approve_budget_request(session, actor_user_id=user_id, actor_capabilities=caps,
                                                           request_id=row.id, expected_version=body.expected_version,
                                                           note=body.reason)
            else:
                row = promo_service.reject_budget_request(session, actor_user_id=user_id, actor_capabilities=caps,
                                                          request_id=row.id, expected_version=body.expected_version,
                                                          reason=body.reason or "")
        return _budget_request_dto(session, row, user_id)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="promo_budget_request")


def _register_budget_decision(decision: str) -> None:
    def endpoint(request_id: str, body: BudgetRequestDecision, request: Request,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
        return _decide_budget(decision, request_id, body, request, idempotency_key, user_id, session)

    endpoint.__name__ = f"budget_request_{decision}"
    router.add_api_route(f"/admin/promo/budget-requests/{{request_id}}/{decision}", endpoint, methods=["POST"],
                         response_model=Envelope[BudgetRequestDTO], responses=ERROR_RESPONSES,
                         name=f"budget_request_{decision}")


for _decision in ("approve", "reject", "withdraw"):
    _register_budget_decision(_decision)


# --- staff: reviews and reconciliation ---------------------------------------------------------------------------------


@router.get("/admin/promo/reviews", response_model=Envelope[list[ReviewDTO]], responses=ERROR_RESPONSES)
def list_reviews(open_only: bool = Query(default=True), user_id: int = Depends(current_user_id),
                 session: Session = Depends(get_session)) -> Envelope[list[ReviewDTO]]:
    portal.require(session, user_id, Capability.PROMO_FRAUD_REVIEW)
    return Envelope[list[ReviewDTO]](data=[_review_dto(session, r, user_id)
                                           for r in portal.reviews(session, open_only=open_only)])


@router.post("/admin/promo/reviews/{review_id}/start", response_model=Envelope[ReviewDTO], responses=ERROR_RESPONSES)
def start_review(review_id: str, body: ReviewStart, request: Request,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Operator: take the review and leave a note (audit). No decision."""
    from app.modules.promotions import qualification

    def handler() -> ReviewDTO:
        caps = portal.require(session, user_id, Capability.PROMO_FRAUD_REVIEW)
        row = portal.get_review(session, review_id)
        row = qualification.start_review(session, review_id=row.id, actor_user_id=user_id, actor_capabilities=caps,
                                         note=body.note)
        return _review_dto(session, row, user_id)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="promo_review")


@router.post("/admin/promo/reviews/{review_id}/decide", response_model=Envelope[ReviewDTO], responses=ERROR_RESPONSES)
def decide_review(review_id: str, body: ReviewDecision, request: Request,
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> JSONResponse:
    """Admin+ with a fresh step-up. Approval creates no reward and never changes an attribution (Q122)."""
    from app.modules.promotions import qualification

    def handler() -> ReviewDTO:
        caps = portal.require_step_up(session, user_id=user_id, capability=Capability.PROMO_FRAUD_DECIDE)
        row = portal.get_review(session, review_id)
        row = qualification.decide_review(session, review_id=row.id, decision=body.decision, actor_user_id=user_id,
                                          actor_capabilities=caps, note=body.note,
                                          expected_version=body.expected_version)
        return _review_dto(session, row, user_id)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="promo_review")


@router.get("/admin/promo/reconciliation", response_model=Envelope[list[ReconciliationIssueDTO]], responses=ERROR_RESPONSES)
def reconciliation(user_id: int = Depends(current_user_id),
                   session: Session = Depends(get_session)) -> Envelope[list[ReconciliationIssueDTO]]:
    """Promo ledger vs budget vs obligations vs lots. Empty list = consistent."""
    portal.require(session, user_id, Capability.PROMO_CAMPAIGN_VIEW)
    return Envelope[list[ReconciliationIssueDTO]](data=[
        ReconciliationIssueDTO(kind=str(item.get("kind")), detail={k: v for k, v in item.items() if k != "kind"})
        for item in promo_service.reconciliation_issues(session)])



@router.get("/admin/promo/report", response_model=Envelope[PromoReportDTO], responses=ERROR_RESPONSES)
def promo_report(from_: date = Query(alias="from"), to: date = Query(),
                 group_by: str = Query(default="service", pattern="^(service|corridor|campaign_version|cohort)$"),
                 user_id: int = Depends(current_user_id),
                 session: Session = Depends(get_session)) -> Envelope[PromoReportDTO]:
    """Operational aggregate (real rows only; the simulator is never served here). Read-only, at most 366 days,
    bounded by a statement timeout. Needs campaign view **and** finance reports (money of the programme)."""
    portal.require(session, user_id, Capability.PROMO_CAMPAIGN_VIEW)
    portal.require(session, user_id, Capability.FINANCE_REPORTS)
    start, end = reporting.day_bounds(from_, to)
    try:
        data = reporting.build_report(session, group_by=group_by, start=start, end=end, now=utc_now())
        return Envelope[PromoReportDTO](data=PromoReportDTO.model_validate(data))
    finally:
        session.rollback()  # nothing to keep: ends the read snapshot and the local statement timeout
