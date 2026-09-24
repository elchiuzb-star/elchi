"""Read models and HTTP guards of the promotions surface (referral stage 5, ADR-0023 §19).

Everything money-related is computed by the existing services (``referral``, ``booking``, ``service``,
``qualification``); this module only *reads* them for screens and adds the two HTTP-level guards the API needs:

* **abuse limits** - the platform's existing mechanism (count recent rows in a window, like OTP per IP, listings per
  author, support tickets per user) over ``promo_rate_events``; the source is stored only as a purpose-subkey HMAC;
* **real MFA step-up** for budget, campaign and review decisions - an *active* factor verified within
  ``STEP_UP_MAX_AGE``. Unlike the platform-wide audit-only rollout (ADR-0021), promotions never lets a missing factor
  through: without a working factor these endpoints stay closed (``FORBIDDEN step_up_required``). A client header is
  never MFA evidence.

No function here commits; API handlers own the transaction.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.enums import Capability, PromoRewardStatus, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id
from app.contracts.promo import referral_family_for
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions import service as promo_service
from app.modules.promotions.models import (
    PromoBudgetRequest,
    PromoCampaign,
    PromoCampaignVersion,
    PromoEnrollment,
    PromoLot,
    PromoQualification,
    PromoRateEvent,
    PromoReview,
    ReferralAttribution,
    ReferralCode,
)

RATE_KEY_PURPOSE = "promo-rate-key"
RATE_EVENT_RETENTION = timedelta(days=1)
CODE_CHECK_WINDOW = timedelta(minutes=1)
ATTRIBUTION_WINDOW = timedelta(hours=1)


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now, field="now")


# --- guards ---------------------------------------------------------------------------------------------------------


def _rate_key(source: str) -> str:
    from app.contracts.crypto import derive_subkey
    from app.core.config import settings

    key = derive_subkey(settings.secret_key, RATE_KEY_PURPOSE)
    return hmac.new(key, source.encode("utf-8"), hashlib.sha256).hexdigest()


def check_rate(session: Session, *, action: str, source: str, limit: int, window: timedelta,
               now: datetime | None = None) -> None:
    """Refuse when ``source`` already used ``limit`` requests of ``action`` in ``window``. Reads only."""
    now = _now(now)
    recent = session.execute(select(func.count(PromoRateEvent.id), func.min(PromoRateEvent.created_at)).where(
        PromoRateEvent.action == action, PromoRateEvent.key_hash == _rate_key(source),
        PromoRateEvent.created_at >= now - window)).one()
    if recent[0] >= limit:
        oldest = ensure_aware_utc(recent[1], field="oldest") if recent[1] is not None else now
        retry = max(1, int((oldest + window - now).total_seconds()))
        raise DomainError(ErrorCode.RATE_LIMITED, details={"limit": limit, "window_s": int(window.total_seconds()),
                                                           "retry_after_s": retry})


def record_rate(session: Session, *, action: str, source: str, now: datetime | None = None) -> None:
    """Count one request. Called outside the command's domain savepoint, so a *refused* attempt (e.g. an unknown
    code) still counts - otherwise guessing codes would never reach the limit."""
    session.add(PromoRateEvent(action=action, key_hash=_rate_key(source), created_at=_now(now)))
    session.flush()


def consume_rate(session: Session, *, action: str, source: str, limit: int, window: timedelta,
                 now: datetime | None = None) -> None:
    """Check and count in one step (endpoints without a command savepoint)."""
    check_rate(session, action=action, source=source, limit=limit, window=window, now=now)
    record_rate(session, action=action, source=source, now=now)


def purge_rate_events(session: Session, *, now: datetime | None = None, limit: int = 5000) -> int:
    """Worker job: counters older than a day are no longer needed for any window."""
    now = _now(now)
    ids = session.execute(select(PromoRateEvent.id).where(PromoRateEvent.created_at < now - RATE_EVENT_RETENTION)
                          .order_by(PromoRateEvent.id).limit(limit)).scalars().all()
    if ids:
        session.execute(PromoRateEvent.__table__.delete().where(PromoRateEvent.id.in_(ids)))
    return len(ids)


def capabilities(session: Session, user_id: int) -> frozenset[Capability]:
    """Server-computed capabilities of the authenticated caller (ADR-0007); never taken from the request."""
    from app.modules.identity import service as identity_service

    return frozenset(identity_service.get_capabilities(session, user_id).capabilities)


def require(session: Session, user_id: int, capability: Capability) -> frozenset[Capability]:
    caps = capabilities(session, user_id)
    if capability not in caps:
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": capability.value})
    return caps


def require_step_up(session: Session, *, user_id: int, capability: Capability,
                    now: datetime | None = None) -> frozenset[Capability]:
    """Capability plus a **real** recent factor check (active TOTP factor, step-up within ``STEP_UP_MAX_AGE``).

    The platform's audit-only rollout mode is deliberately not honoured here: a promotions budget, campaign or review
    decision without a working second factor is refused, never recorded-and-allowed.
    """
    from app.modules.identity import mfa

    caps = require(session, user_id, capability)
    state = mfa.state(session, user_id)
    if state.active and state.step_up_fresh(now=now):
        return caps
    raise DomainError(ErrorCode.FORBIDDEN, details={
        "reason": "step_up_required", "capability": capability.value, "mfa_active": state.active,
        "max_age_seconds": int(mfa.STEP_UP_MAX_AGE.total_seconds())})


# --- identifiers ----------------------------------------------------------------------------------------------------


def campaign_public_id(campaign: PromoCampaign) -> str:
    return format_public_id(PublicIdPrefix.PROMO_CAMPAIGN, campaign.public_id)


def attribution_public_id(row: ReferralAttribution) -> str:
    return format_public_id(PublicIdPrefix.REFERRAL_ATTRIBUTION, row.public_id)


def enrollment_public_id(row: PromoEnrollment) -> str:
    return format_public_id(PublicIdPrefix.PROMO_ENROLLMENT, row.public_id)


def lot_public_id(row: PromoLot) -> str:
    return format_public_id(PublicIdPrefix.PROMO_LOT, row.public_id)


def review_public_id(row: PromoReview) -> str:
    return format_public_id(PublicIdPrefix.PROMO_REVIEW, row.public_id)


def budget_request_public_id(row: PromoBudgetRequest) -> str:
    return format_public_id(PublicIdPrefix.PROMO_BUDGET_REQUEST, row.public_id)


def _by_public_id(session: Session, model, prefix: PublicIdPrefix, value: str):  # noqa: ANN001, ANN202
    try:
        uid = parse_public_id(value, prefix)
    except DomainError:
        raise DomainError(ErrorCode.NOT_FOUND) from None
    row = session.execute(select(model).where(model.public_id == uid)).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def combination_public_id(row) -> str:  # noqa: ANN001 - PromoCampaignCombination
    return format_public_id(PublicIdPrefix.PROMO_COMBINATION, row.public_id)


def get_combination(session: Session, value: str):  # noqa: ANN201
    from app.modules.promotions.models import PromoCampaignCombination

    return _by_public_id(session, PromoCampaignCombination, PublicIdPrefix.PROMO_COMBINATION, value)


def get_campaign(session: Session, value: str) -> PromoCampaign:
    return _by_public_id(session, PromoCampaign, PublicIdPrefix.PROMO_CAMPAIGN, value)


def get_budget_request(session: Session, value: str) -> PromoBudgetRequest:
    return _by_public_id(session, PromoBudgetRequest, PublicIdPrefix.PROMO_BUDGET_REQUEST, value)


def get_review(session: Session, value: str) -> PromoReview:
    return _by_public_id(session, PromoReview, PublicIdPrefix.PROMO_REVIEW, value)


def own_attribution(session: Session, value: str, user_id: int) -> ReferralAttribution:
    """Someone else's attribution id answers exactly like an unknown one (404, no oracle)."""
    row = _by_public_id(session, ReferralAttribution, PublicIdPrefix.REFERRAL_ATTRIBUTION, value)
    if row.referee_user_id != user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def campaign_version(session: Session, campaign: PromoCampaign, version_no: int) -> PromoCampaignVersion:
    row = session.execute(select(PromoCampaignVersion).where(PromoCampaignVersion.campaign_id == campaign.id,
                                                             PromoCampaignVersion.version_no == version_no)
                          ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


# --- client read models ---------------------------------------------------------------------------------------------


def share_url(code: str) -> str | None:
    from app.core.config import settings

    host = (settings.referral_link_host or "").strip().strip("/")
    return f"https://{host}/r/{code}" if host else None


@dataclass(frozen=True)
class OfferRow:
    campaign: PromoCampaign
    attribution: ReferralAttribution
    version_no: int
    offer: object  # referral.EnrollmentOffer


def offers_for(session: Session, user_id: int, audience: str) -> list[OfferRow]:
    """Active campaigns the caller may join now: its own open attribution of that family, not yet enrolled there."""
    from app.modules.promotions import referral

    family = referral_family_for(audience).value
    attribution = session.execute(select(ReferralAttribution).where(
        ReferralAttribution.referee_user_id == user_id, ReferralAttribution.family == family,
        ReferralAttribution.status.in_(("attributed", "qualifying")))).scalar_one_or_none()
    if attribution is None:
        return []
    enrolled = set(session.execute(select(PromoEnrollment.campaign_id).where(
        PromoEnrollment.attribution_id == attribution.id)).scalars())
    rows = []
    for campaign in session.execute(select(PromoCampaign).where(
            PromoCampaign.family == family, PromoCampaign.status == "active").order_by(PromoCampaign.id)).scalars():
        if campaign.id in enrolled or campaign.active_version_id is None:
            continue
        version = session.get(PromoCampaignVersion, campaign.active_version_id)
        rows.append(OfferRow(campaign, attribution, version.version_no,
                             referral.enrollment_offer(session, campaign_id=campaign.id)))
    return rows


@dataclass(frozen=True)
class EnrollmentView:
    enrollment: PromoEnrollment
    campaign: PromoCampaign
    qualification_status: str | None
    side: str  # "referee" | "referrer"


def my_enrollments(session: Session, user_id: int) -> list[EnrollmentView]:
    """Enrollments where the caller is the referee or the referrer. The other party is never identified."""
    rows = session.execute(select(PromoEnrollment, PromoCampaign).join(
        PromoCampaign, PromoCampaign.id == PromoEnrollment.campaign_id).where(
        (PromoEnrollment.referee_user_id == user_id) | (PromoEnrollment.referrer_user_id == user_id))
        .order_by(PromoEnrollment.id.desc()).limit(100)).all()
    views = []
    for enrollment, campaign in rows:
        status = session.execute(select(PromoQualification.status).where(
            PromoQualification.enrollment_id == enrollment.id).order_by(PromoQualification.milestone.desc())
            .limit(1)).scalar_one_or_none()
        views.append(EnrollmentView(enrollment, campaign, status,
                                    "referee" if enrollment.referee_user_id == user_id else "referrer"))
    return views


def my_attributions(session: Session, user_id: int) -> list[ReferralAttribution]:
    return list(session.execute(select(ReferralAttribution).where(ReferralAttribution.referee_user_id == user_id)
                                .order_by(ReferralAttribution.id)).scalars())


def invited_counts(session: Session, user_id: int) -> dict[str, int]:
    """How many people joined with my code, by attribution status - counts only, never who (Q43 spirit)."""
    return {status: count for status, count in session.execute(
        select(ReferralAttribution.status, func.count()).where(ReferralAttribution.referrer_user_id == user_id)
        .group_by(ReferralAttribution.status)).all()}


@dataclass(frozen=True)
class BalanceBucket:
    instrument: str
    service_type: str
    available_minor: int
    reserved_minor: int
    under_review_minor: int
    consumed_minor: int
    expired_minor: int
    reversed_minor: int
    next_expiry_at: datetime | None


def promo_balance(session: Session, user_id: int, now: datetime | None = None) -> tuple[list[BalanceBucket], list[PromoLot]]:
    """The caller's discount rights by instrument and service type. Never money: nothing here can be withdrawn."""
    now = _now(now)
    lots = list(session.execute(select(PromoLot).where(PromoLot.owner_user_id == user_id)
                                .order_by(PromoLot.expires_at, PromoLot.id)).scalars())
    buckets: dict[tuple[str, str], dict] = {}
    for lot in lots:
        key = (lot.instrument, lot.service_type)
        b = buckets.setdefault(key, dict(available_minor=0, reserved_minor=0, under_review_minor=0, consumed_minor=0,
                                         expired_minor=0, reversed_minor=0, next_expiry_at=None))
        free = promo_service._available(lot)
        expired_now = ensure_aware_utc(lot.expires_at, field="expires_at") <= now
        if lot.status == PromoRewardStatus.AVAILABLE.value and not expired_now:
            b["available_minor"] += free
            if free and (b["next_expiry_at"] is None or lot.expires_at < b["next_expiry_at"]):
                b["next_expiry_at"] = lot.expires_at
        elif lot.status == PromoRewardStatus.PENDING_REVIEW.value:
            b["under_review_minor"] += free
        elif lot.status == PromoRewardStatus.AVAILABLE.value and expired_now:
            b["expired_minor"] += free  # due, the expiry job has not run yet: shown as expired, never as spendable
        b["reserved_minor"] += lot.reserved_minor
        b["consumed_minor"] += lot.consumed_minor
        b["expired_minor"] += lot.expired_minor
        b["reversed_minor"] += lot.reversed_minor
    return [BalanceBucket(instrument=k[0], service_type=k[1], **v) for k, v in sorted(buckets.items())], lots


def active_code(session: Session, user_id: int) -> ReferralCode | None:
    return session.execute(select(ReferralCode).where(ReferralCode.owner_user_id == user_id,
                                                      ReferralCode.status == "active")).scalar_one_or_none()


# --- staff read models ---------------------------------------------------------------------------------------------


def campaigns(session: Session) -> list[PromoCampaign]:
    return list(session.execute(select(PromoCampaign).order_by(PromoCampaign.id.desc()).limit(200)).scalars())


def campaign_versions(session: Session, campaign: PromoCampaign) -> list[PromoCampaignVersion]:
    return list(session.execute(select(PromoCampaignVersion).where(PromoCampaignVersion.campaign_id == campaign.id)
                                .order_by(PromoCampaignVersion.version_no)).scalars())


def budget_requests(session: Session, *, status: str | None = None) -> list[PromoBudgetRequest]:
    query = select(PromoBudgetRequest).order_by(PromoBudgetRequest.id.desc()).limit(200)
    if status:
        query = query.where(PromoBudgetRequest.status == status)
    return list(session.execute(query).scalars())


def reviews(session: Session, *, open_only: bool = True) -> list[PromoReview]:
    query = select(PromoReview).order_by(PromoReview.due_at.asc().nullslast(), PromoReview.id).limit(200)
    if open_only:
        query = query.where(PromoReview.status.in_(("open", "under_review")))
    return list(session.execute(query).scalars())


def service_type_of(value: str) -> ServiceType:
    return ServiceType(value)
