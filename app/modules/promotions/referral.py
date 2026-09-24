"""Referral codes, attribution and enrollment (referral stage 2, ADR-0023, Q106/Q108/Q112/Q117/Q118).

* **Attribution** records *who invited whom* - once per ``(referee, family)``, first wins, server clock, 72 h from
  the referee's first verified sign-up (or driver onboarding) and only before their first accepted service. It
  promises nothing and reserves no budget.
* **Enrollment** records *which campaign version's terms the referee accepted* and, in the same transaction,
  reserves both sides' maximum rewards in the campaign budget. No budget -> no enrollment, and nothing is left
  behind. One live enrollment per person and family, whichever service (passenger or parcel) it comes through.

Neither ever blocks registration or ordinary service: every refusal is a ``DomainError`` raised inside a savepoint,
so the caller's own transaction (a sign-up, a profile update) stays usable.

Races (lock contract, ADR-0023 §13): attribution and enrollment lock the ``users`` rows of both parties
``FOR NO KEY UPDATE`` first - the same rows ``bookings.accept_proposal`` locks first - so "attribute" and "first
booking accepted" serialise; whichever commits second sees the other. The accept side of that contract is proven
with a stand-in here and becomes a full test with the stage-4 booking integration.

No HTTP endpoints yet (stage 5): see ``docs/referral/REFERRAL_PLAN.md`` for the public contract.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import (
    PILOT_CAMPAIGN_KINDS,
    Capability,
    FeatureFlagKey,
    PromoCampaignKind,
    PromoCampaignStatus,
    ReferralAttributionStatus,
    Role,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import (
    ATTRIBUTION_WINDOW,
    CAMPAIGN_PARTIES,
    IdentityRetentionPolicy,
    decide_attribution,
    enrollment_allowed,
    enrollment_rewards,
    new_referral_code,
    normalize_referral_code,
    qualification_deadline,
    referral_family_for,
    request_fingerprint,
    reward_key,
    terms_fingerprint,
)
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions import identity as identity_service
from app.modules.promotions import service as promo_service
from app.modules.promotions.models import (
    PromoCampaign,
    PromoCampaignVersion,
    PromoEnrollment,
    PromoIdentity,
    PromoObligation,
    ReferralAttribution,
    ReferralCode,
)

__all__ = [
    "CodeCheck",
    "EnrollmentOffer",
    "attribute",
    "check_code",
    "enroll",
    "enrollment_offer",
    "issue_referral_code",
    "revoke_referral_code",
]

CODE_INSERT_ATTEMPTS = 5


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now, field="now")


def _not_eligible(reason: str) -> DomainError:
    return DomainError(ErrorCode.REFERRAL_NOT_ELIGIBLE, details={"reason": reason})


def _require_promotions_enabled(session: Session) -> None:
    from app.modules.geo import service as geo_service

    if not geo_service.is_flag_enabled(session, FeatureFlagKey.PROMOTIONS_ENABLED):
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"flag": FeatureFlagKey.PROMOTIONS_ENABLED.value})


def _lock_users(session: Session, *user_ids: int) -> dict[int, dict]:
    """``users`` first, ids ascending, FOR NO KEY UPDATE - the global lock order (ADR-0017)."""
    rows = {}
    for user_id in sorted(set(user_ids)):
        row = session.execute(
            text("SELECT id, role, status, phone, is_phone_verified, created_at FROM users WHERE id = :id "
                 "FOR NO KEY UPDATE"), {"id": user_id}
        ).mappings().one_or_none()
        if row is None:
            raise DomainError(ErrorCode.NOT_FOUND)
        rows[user_id] = dict(row)
    return rows


def _roles(session: Session, user_id: int):  # noqa: ANN202
    from app.modules.identity import service as identity_module

    return identity_module.get_capabilities(session, user_id)


def _audit(session: Session, actor_user_id: int | None, entity_type: str, entity_id: int, action: str,
           new_value: dict, reason: str | None = None) -> None:
    promo_service._audit(session, actor_user_id, entity_type, entity_id, action, new_value, reason)


# --- codes -----------------------------------------------------------------------------------------------------


def issue_referral_code(session: Session, *, owner_user_id: int,
                        randbelow: Callable[[int], int] = secrets.randbelow) -> ReferralCode:
    """The owner's active code, created on first use. Idempotent; a code collision is retried with a fresh code.

    Codes are random (``promo.new_referral_code``), never derived from the phone, KYC data or the user id.
    """
    owner = _lock_users(session, owner_user_id)[owner_user_id]
    if owner["status"] != "active":
        raise _not_eligible("owner_not_active")
    for _ in range(CODE_INSERT_ATTEMPTS):
        existing = _active_code(session, owner_user_id)
        if existing is not None:
            return existing
        savepoint = session.begin_nested()
        try:
            code = ReferralCode(public_id=uuid.uuid4(), code=new_referral_code(randbelow), owner_user_id=owner_user_id,
                                status="active")
            session.add(code)
            session.flush()
        except IntegrityError as exc:
            savepoint.rollback()
            if promo_service._constraint_of(exc) in {"uq_referral_codes_code", "uq_referral_codes_one_active_per_owner"}:
                continue  # collision with another code, or a parallel issue for the same owner: read / try again
            raise
        savepoint.commit()
        _audit(session, owner_user_id, "referral_codes", code.id, "referral_code_issued", {})
        return code
    raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "referral_code_space_busy"})


def _active_code(session: Session, owner_user_id: int) -> ReferralCode | None:
    return session.execute(
        select(ReferralCode).where(ReferralCode.owner_user_id == owner_user_id, ReferralCode.status == "active")
    ).scalar_one_or_none()


def revoke_referral_code(session: Session, *, code_id: int, actor_user_id: int,
                         actor_capabilities: frozenset[Capability] | set[Capability] = frozenset(),
                         reason: str, issue_replacement: bool = True, now: datetime | None = None) -> ReferralCode | None:
    """Revoke (and by default replace) a code. The owner or admin+ may do it. Earlier attributions, enrollments and
    obligations made with the old code are untouched; the old code simply stops attributing new people."""
    now = _now(now)
    code = session.execute(select(ReferralCode).where(ReferralCode.id == code_id).with_for_update(key_share=True)).scalar_one_or_none()
    if code is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if actor_user_id != code.owner_user_id and Capability.PROMO_FRAUD_DECIDE not in set(actor_capabilities):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.PROMO_FRAUD_DECIDE.value})
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    if code.status == "active":
        code.status = "revoked"
        code.revoked_at = now
        code.revoke_reason = reason.strip()
        session.flush()
        _audit(session, actor_user_id, "referral_codes", code.id, "referral_code_revoked", {}, reason.strip())
    return issue_referral_code(session, owner_user_id=code.owner_user_id) if issue_replacement else None


@dataclass(frozen=True, slots=True)
class CodeCheck:
    """The only thing a public code check may say (stage-5 contract): usable or not. Never who owns it."""

    valid: bool


def check_code(session: Session, raw_code: str | None) -> CodeCheck:
    code = _usable_code(session, raw_code)
    return CodeCheck(valid=code is not None)


def _usable_code(session: Session, raw_code: str | None) -> ReferralCode | None:
    """Unknown, revoked and inactive-owner codes are indistinguishable to the caller (no oracle about the owner)."""
    normalized = normalize_referral_code(raw_code)
    if normalized is None:
        return None
    row = session.execute(
        select(ReferralCode).where(ReferralCode.code == normalized, ReferralCode.status == "active")
    ).scalar_one_or_none()
    if row is None:
        return None
    status = session.execute(text("SELECT status FROM users WHERE id = :id"), {"id": row.owner_user_id}).scalar_one()
    return row if status == "active" else None


# --- attribution (Q106, Q117) --------------------------------------------------------------------------------------


def _window_started_at(session: Session, user: dict, audience_role: str) -> datetime | None:
    """Client: the first verified sign-up. Driver: when the driver role was taken (onboarding start)."""
    if not user["is_phone_verified"]:
        return None
    if audience_role == "client":
        return ensure_aware_utc(user["created_at"], field="created_at")
    started = session.execute(
        text("SELECT min(created_at) FROM user_roles WHERE user_id = :u AND role = 'driver'"), {"u": user["id"]}
    ).scalar_one()
    if started is None and user["role"] == "driver":
        started = user["created_at"]
    return None if started is None else ensure_aware_utc(started, field="driver_role_created_at")


def _first_service_at(session: Session, user_id: int, audience_role: str) -> datetime | None:
    """First accepted service in that audience: a v2 booking, or a v1 order that got a driver."""
    if audience_role == "client":
        return session.execute(text(
            "SELECT min(t) FROM ("
            " SELECT min(created_at) AS t FROM bookings WHERE client_user_id = :u"
            " UNION ALL SELECT min(created_at) FROM orders WHERE client_id = :u AND assigned_driver_id IS NOT NULL"
            ") s"), {"u": user_id}).scalar_one()
    return session.execute(text(
        "SELECT min(t) FROM ("
        " SELECT min(created_at) AS t FROM bookings WHERE driver_user_id = :u"
        " UNION ALL SELECT min(o.created_at) FROM orders o JOIN driver_profiles d ON d.id = o.assigned_driver_id"
        "  WHERE d.user_id = :u"
        ") s"), {"u": user_id}).scalar_one()


def _has_audience_role(session: Session, user_id: int, audience_role: str) -> bool:
    caps = _roles(session, user_id)
    return (Role.CLIENT if audience_role == "client" else Role.DRIVER) in caps.roles


def attribute(session: Session, *, referee_user_id: int, raw_code: str | None, audience_role: str,
              idempotency_key: str, now: datetime | None = None) -> ReferralAttribution:
    """Attach a referral once. Refusals never touch the caller's transaction (savepoint) or the account."""
    now = _now(now)
    family = referral_family_for(audience_role)
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_INVALID)
    request_hash = request_fingerprint({"code": normalize_referral_code(raw_code) or raw_code, "audience": audience_role})
    _require_promotions_enabled(session)
    code = _usable_code(session, raw_code)
    if code is None:
        raise DomainError(ErrorCode.REFERRAL_CODE_INVALID)
    users = _lock_users(session, referee_user_id, code.owner_user_id)
    existing = session.execute(
        select(ReferralAttribution).where(ReferralAttribution.referee_user_id == referee_user_id,
                                          ReferralAttribution.family == family.value)
    ).scalar_one_or_none()
    if existing is not None and existing.idempotency_key == idempotency_key:
        if existing.request_hash != request_hash:
            raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REUSED)
        return existing
    referee = users[referee_user_id]
    if referee["status"] != "active":
        raise _not_eligible("referee_not_active")
    if not _has_audience_role(session, referee_user_id, audience_role):
        raise _not_eligible("referee_lacks_role")
    window_started = _window_started_at(session, referee, audience_role)
    first_service = _first_service_at(session, referee_user_id, audience_role)
    window_open = (
        window_started is not None and first_service is None and window_started <= now < window_started + ATTRIBUTION_WINDOW
    )
    decide_attribution(
        referrer_user_id=code.owner_user_id,
        referee_user_id=referee_user_id,
        referrer_identity_keys=_identity_keys_of(session, code.owner_user_id),
        referee_identity_keys=_identity_keys_of(session, referee_user_id),
        existing_referrer_user_id=None if existing is None else existing.referrer_user_id,
        window_open=window_open,
    )
    if existing is not None:
        return existing  # same referrer again with another key: replay, nothing new (Q106)
    attribution = ReferralAttribution(
        public_id=uuid.uuid4(), referee_user_id=referee_user_id, family=family.value,
        referrer_user_id=code.owner_user_id, referral_code_id=code.id, status=ReferralAttributionStatus.ATTRIBUTED.value,
        attributed_at=now, window_started_at=window_started, window_ends_at=window_started + ATTRIBUTION_WINDOW,
        idempotency_key=idempotency_key, request_hash=request_hash,
    )
    savepoint = session.begin_nested()
    try:
        session.add(attribution)
        session.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if promo_service._constraint_of(exc) == "uq_referral_attributions_referee_family":
            # only reachable without the users lock (e.g. a caller that skipped it): the first one wins
            raise DomainError(ErrorCode.REFERRAL_ALREADY_ATTRIBUTED) from exc
        raise
    savepoint.commit()
    _audit(session, referee_user_id, "referral_attributions", attribution.id, "referral_attributed",
           {"family": family.value, "referral_code_id": code.id})
    return attribution


def _identity_keys_of(session: Session, user_id: int) -> frozenset[str]:
    identity_id = session.execute(
        select(PromoIdentity.id).where(PromoIdentity.current_user_id == user_id)
    ).scalar_one_or_none()
    return frozenset() if identity_id is None else frozenset({f"identity:{identity_id}"})


# --- enrollment (Q117, Q118) ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrollmentOffer:
    """What the referee is shown and accepts: pinned version + fingerprint of every term and disclosure."""

    campaign_id: int
    campaign_version_id: int
    terms_fingerprint: str
    disclosures: dict


def enrollment_offer(session: Session, *, campaign_id: int) -> EnrollmentOffer:
    from app.contracts.promo import enrollment_disclosures

    campaign = session.get(PromoCampaign, campaign_id)
    if campaign is None or campaign.status != PromoCampaignStatus.ACTIVE.value or campaign.active_version_id is None:
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"reason": "campaign_not_accepting_enrollments"})
    version = session.get(PromoCampaignVersion, campaign.active_version_id)
    terms = promo_service.version_terms(session, campaign, version)
    return EnrollmentOffer(campaign.id, version.id, terms_fingerprint(terms, campaign_version_id=version.id),
                           {code.value: value for code, value in enrollment_disclosures(terms).items()})


def enroll(session: Session, *, referee_user_id: int, attribution_id: int, campaign_id: int,
           accepted_campaign_version_id: int, accepted_terms_fingerprint: str, idempotency_key: str,
           keys: identity_service.IdentityKeys | None,
           retention: IdentityRetentionPolicy = identity_service.APPROVED_RETENTION,
           now: datetime | None = None) -> PromoEnrollment:
    """Join one campaign under the terms the referee saw; reserve both sides' maximum rewards atomically."""
    from app.modules.platform import service as platform_service

    now = _now(now)
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_INVALID)
    request_hash = request_fingerprint({"attribution_id": attribution_id, "campaign_id": campaign_id,
                                        "version_id": accepted_campaign_version_id,
                                        "terms": accepted_terms_fingerprint})
    _require_promotions_enabled(session)
    if not enrollment_allowed(is_production=platform_service.is_production(session), retention=retention,
                              identity_key_available=keys is not None):
        # Q108/Q118: no identity protection -> no enrollment. Never a fallback that hands out rewards unprotected.
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"reason": "identity_protection_not_ready"})
    attribution = session.get(ReferralAttribution, attribution_id)
    if attribution is None or attribution.referee_user_id != referee_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    users = _lock_users(session, attribution.referee_user_id, attribution.referrer_user_id)
    replay = session.execute(
        select(PromoEnrollment).where(PromoEnrollment.referee_user_id == referee_user_id,
                                      PromoEnrollment.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if replay is not None:
        if replay.request_hash != request_hash:
            raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REUSED)
        return replay
    campaign = promo_service._lock_campaign(session, campaign_id)
    savepoint = session.begin_nested()
    try:
        enrollment = _enroll_locked(session, attribution=attribution, users=users, campaign=campaign,
                                    accepted_campaign_version_id=accepted_campaign_version_id,
                                    accepted_terms_fingerprint=accepted_terms_fingerprint,
                                    idempotency_key=idempotency_key, request_hash=request_hash, keys=keys, now=now)
    except (DomainError, IntegrityError) as exc:
        savepoint.rollback()
        if isinstance(exc, IntegrityError):
            name = promo_service._constraint_of(exc)
            if name in {"uq_promo_enrollments_identity_family", "uq_promo_enrollments_user_family"}:
                raise _not_eligible("already_enrolled_in_family") from exc
            if name == "uq_promo_enrollments_attribution_campaign":
                raise _not_eligible("already_enrolled_in_campaign") from exc
        raise
    savepoint.commit()
    _audit(session, referee_user_id, "promo_enrollments", enrollment.id, "referral_enrolled",
           {"campaign_id": campaign.id, "campaign_version_id": enrollment.campaign_version_id})
    return enrollment


def _enroll_locked(session: Session, *, attribution: ReferralAttribution, users: dict[int, dict],
                   campaign: PromoCampaign, accepted_campaign_version_id: int, accepted_terms_fingerprint: str,
                   idempotency_key: str, request_hash: str, keys: identity_service.IdentityKeys,
                   now: datetime) -> PromoEnrollment:
    kind = PromoCampaignKind(campaign.kind)
    if campaign.status != PromoCampaignStatus.ACTIVE.value or campaign.active_version_id is None:
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"reason": "campaign_not_accepting_enrollments"})
    if kind not in PILOT_CAMPAIGN_KINDS or campaign.family != attribution.family:
        raise _not_eligible("campaign_not_for_this_referral")
    if campaign.active_version_id != accepted_campaign_version_id:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"reason": "campaign_terms_changed"})
    version = session.get(PromoCampaignVersion, campaign.active_version_id)
    terms = promo_service.version_terms(session, campaign, version)
    if terms_fingerprint(terms, campaign_version_id=version.id) != accepted_terms_fingerprint:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"reason": "campaign_terms_changed"})
    if attribution.status not in (ReferralAttributionStatus.ATTRIBUTED.value, ReferralAttributionStatus.QUALIFYING.value):
        raise _not_eligible("attribution_closed")

    referrer_role, referee_role = CAMPAIGN_PARTIES[kind]
    referrer = users[attribution.referrer_user_id]
    referee = users[attribution.referee_user_id]
    if referrer["status"] != "active":
        raise _not_eligible("referrer_not_active")  # earlier enrollments and obligations are not touched
    referrer_caps = _roles(session, attribution.referrer_user_id)
    if referrer_role == "driver" and not referrer_caps.driver_eligible:
        raise _not_eligible("referrer_driver_not_eligible")
    if referrer_role == "client" and Role.CLIENT not in referrer_caps.roles:
        raise _not_eligible("referrer_lacks_role")
    if referee["status"] != "active" or not _has_audience_role(session, attribution.referee_user_id, referee_role):
        raise _not_eligible("referee_not_eligible")
    if _first_service_at(session, attribution.referee_user_id, referee_role) is not None:
        raise _not_eligible("referee_not_new")  # the reward is for a new person's next service

    resolved = identity_service.resolve_identity(
        session, user_id=attribution.referee_user_id, phone=referee["phone"],
        window_started_at=attribution.window_started_at, keys=keys,
    )
    if resolved is None:
        raise _not_eligible("identity_unavailable")
    if resolved.matched_previous_account:
        # Q108/ADR-0023 §17 T3: maybe a recycled number - never a block of the account or of ordinary service. A person decides;
        # the review is saved in its own transaction so this refused (rolled back) command cannot lose it, and a
        # retry finds the same review instead of adding another. Approval lets a *new* enrollment attempt through,
        # where every other check runs again.
        from app.modules.promotions.models import PromoReview
        from app.modules.promotions.qualification import _review_sla, open_review_autonomously

        dedup_key = f"identity_match:{attribution.id}:{campaign.id}"
        review = session.execute(select(PromoReview).where(PromoReview.dedup_key == dedup_key)).scalar_one_or_none()
        if review is None:
            open_review_autonomously(
                session, kind="identity_match", dedup_key=dedup_key, reasons=["identity_key_match"],
                evidence=[{"table": "referral_attributions", "id": attribution.id},
                          {"table": "promo_identities", "id": resolved.identity.id}],
                now=now, sla=_review_sla(session, campaign.id), campaign_id=campaign.id, attribution_id=attribution.id,
            )
            raise _not_eligible("identity_needs_review")
        if review.status == "rejected":
            raise _not_eligible("identity_review_rejected")
        if review.status != "approved":
            raise _not_eligible("identity_needs_review")
    enrolled_count = session.execute(
        select(func.count()).select_from(PromoEnrollment).where(PromoEnrollment.campaign_version_id == version.id)
    ).scalar_one()
    if enrolled_count >= (version.enrollment_limit or 0):
        raise _not_eligible("enrollment_limit_reached")

    enrollment = PromoEnrollment(
        public_id=uuid.uuid4(), attribution_id=attribution.id, campaign_id=campaign.id, campaign_version_id=version.id,
        family=campaign.family, service_type=campaign.service_type, referrer_user_id=attribution.referrer_user_id,
        referee_user_id=attribution.referee_user_id, referee_identity_id=resolved.identity.id,
        terms_fingerprint=accepted_terms_fingerprint, enrolled_at=now,
        qualification_deadline=qualification_deadline(now, terms.qualification_window),
        status="promised", idempotency_key=idempotency_key, request_hash=request_hash,
    )
    session.add(enrollment)
    session.flush()
    beneficiaries = {"referrer": attribution.referrer_user_id, "referee": attribution.referee_user_id}
    specs = [
        promo_service.RewardSpec(
            beneficiary_user_id=beneficiaries[side], side=side, instrument=instrument, amount_minor=amount,
            reward_key=reward_key(campaign_version_id=version.id, attribution_id=attribution.id, side=side,
                                  milestone=milestone),
            milestone=milestone,
        )
        for side, instrument, amount, milestone in enrollment_rewards(terms)
    ]
    promo_service.promise_rewards(session, campaign_id=campaign.id, rewards=specs, source_type="promo_enrollment",
                                  source_id=enrollment.id, enrollment_id=enrollment.id, now=now)
    return enrollment


def obligations_of(session: Session, enrollment_id: int) -> list[PromoObligation]:
    return list(session.execute(
        select(PromoObligation).where(PromoObligation.enrollment_id == enrollment_id).order_by(PromoObligation.id)
    ).scalars())
