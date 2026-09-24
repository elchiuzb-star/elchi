"""Promotions domain service (ADR-0023, referral stage 1): campaigns, budget, obligations, lots, redemptions.

Public API of the module. Functions never ``commit``; the caller owns the transaction and wraps commands in
``platform.service.run_with_db_retry``. Money rules come from ``app.contracts.promo``; the database enforces the
same invariants independently (append-only ledger, trigger-written budget, deferred balance checks), so a bug here
or a direct SQL write cannot overspend a budget or spend one bonus twice.

Lock order (ADR-0017 extended by ADR-0023 §13): ``promo_campaigns`` (FOR SHARE / FOR NO KEY UPDATE) ->
``promo_obligations`` -> ``promo_lots`` (id ASC) -> ``promo_redemptions`` -> ``promo_budgets`` (taken last, only by
the ledger trigger). Rows that other rows reference by FK are locked ``FOR NO KEY UPDATE``, never plain
``FOR UPDATE`` (AGENTS.md §6).

What is deliberately *not* here yet (later stages, see docs/referral/REFERRAL_PLAN.md): attribution and enrollment
(stage 2), qualification (stage 3), the booking accept/cancel/capture integration and real-balance hold of C_net
(stage 4), HTTP endpoints (stage 5).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import (
    PILOT_CAMPAIGN_KINDS,
    Capability,
    PromoBudgetRequestStatus,
    PromoCampaignFamily,
    PromoCampaignKind,
    PromoCampaignStatus,
    PromoFault,
    PromoInstrument,
    PromoLedgerKind,
    PromoObligationStatus,
    PromoRedemptionStatus,
    PromoRewardStatus,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import validate_minor_amount
from app.contracts.promo import (
    STALE_SCOPE,
    BudgetPosition,
    CampaignTerms,
    PromoMarginPolicy,
    budget_change_requires_second_approver,
    max_commitment_for,
    restored_expiry,
    validate_activation,
)
from app.contracts.state_machines import PROMO_CAMPAIGN, PROMO_OBLIGATION, PROMO_REDEMPTION, PROMO_REWARD
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions.models import (
    PromoBudget,
    PromoBudgetRequest,
    PromoCampaign,
    PromoCampaignCombination,
    PromoCampaignVersion,
    PromoLedgerTransaction,
    PromoLot,
    PromoObligation,
    PromoRedemption,
)

__all__ = [
    "RewardSpec",
    "VersionTerms",
    "activate_campaign",
    "add_campaign_version",
    "approve_budget_request",
    "budget_position",
    "close_campaign",
    "consume_redemption",
    "create_campaign",
    "expire_due_lots",
    "grant_obligation",
    "make_lot_available",
    "on_account_deleted",
    "pause_campaign",
    "pause_exhausted_campaigns",
    "promise_rewards",
    "reconciliation_issues",
    "reject_budget_request",
    "release_obligation",
    "release_redemption",
    "request_budget_change",
    "reserve_lot",
    "resume_campaign",
    "reverse_lot",
    "withdraw_budget_request",
]

_KIND_FAMILY: dict[PromoCampaignKind, PromoCampaignFamily] = {
    PromoCampaignKind.REFERRAL_CLIENT_CLIENT: PromoCampaignFamily.CLIENT_ACQUISITION,
    PromoCampaignKind.REFERRAL_DRIVER_CLIENT: PromoCampaignFamily.CLIENT_ACQUISITION,
    PromoCampaignKind.REFERRAL_DRIVER_DRIVER: PromoCampaignFamily.DRIVER_ACQUISITION,
    PromoCampaignKind.CASHBACK: PromoCampaignFamily.LOYALTY,
    PromoCampaignKind.LOYALTY: PromoCampaignFamily.LOYALTY,
    PromoCampaignKind.CORRIDOR_BONUS: PromoCampaignFamily.LOYALTY,
    PromoCampaignKind.REACTIVATION: PromoCampaignFamily.REACTIVATION,
}

# DB rule names (migration 0084) -> domain errors the service raises itself (better details than the generic map).
_CONSTRAINT_ERRORS: dict[str, ErrorCode] = {
    "promo_budget_exhausted": ErrorCode.PROMO_BUDGET_EXHAUSTED,
    "promo_budget_below_commitment": ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT,
    "promo_funding_loss_evidence": ErrorCode.VALIDATION_ERROR,
    "promo_second_approver_required": ErrorCode.SECOND_APPROVER_REQUIRED,
    "approver_not_finance_staff": ErrorCode.FORBIDDEN,
    "promo_activation_incomplete": ErrorCode.PROMO_PARAMETERS_UNSET,
    "promo_invalid_transition": ErrorCode.INVALID_STATE_TRANSITION,
    "promo_reinstate_invalid": ErrorCode.INVALID_STATE_TRANSITION,
}


# --- helpers ------------------------------------------------------------------------------------------------


def _require_capability(capabilities: Collection[Capability | str], capability: Capability) -> None:
    if capability not in {Capability(c) for c in capabilities}:
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": capability.value})


def _require_text(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": field})
    return value.strip()


def _constraint_of(exc: DBAPIError) -> str | None:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _flush_translating(session: Session, *rows: Any) -> None:
    """Add ``rows`` and flush inside a savepoint; turn the migration's named guard violations into ``DomainError``.

    The savepoint is opened *before* the rows are added: ``begin_nested`` flushes pending objects first, so a row
    added earlier would fail outside the savepoint and leave the caller's transaction broken. The savepoint keeps
    the caller's transaction usable after a refused posting (ADR-0005 pattern).
    """
    session.flush()
    savepoint = session.begin_nested()
    try:
        session.add_all(rows)
        session.flush()
    except DBAPIError as exc:
        savepoint.rollback()
        code = _CONSTRAINT_ERRORS.get(_constraint_of(exc) or "")
        if code is None:
            raise
        raise DomainError(code, details={"reason": _constraint_of(exc)}) from exc
    savepoint.commit()


def _audit(session: Session, actor_user_id: int | None, entity_type: str, entity_id: int, action: str,
           new_value: dict[str, Any], reason: str | None = None) -> None:
    from fastapi.encoders import jsonable_encoder

    from app.models import AuditLog

    session.add(
        AuditLog(
            actor_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details=jsonable_encoder({"new_value": new_value, "reason": reason, "module": "promotions"}),
        )
    )


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now, field="now")


def _lock_campaign(session: Session, campaign_id: int, *, share: bool = False) -> PromoCampaign:
    query = select(PromoCampaign).where(PromoCampaign.id == campaign_id).execution_options(populate_existing=True)
    query = query.with_for_update(read=True) if share else query.with_for_update(key_share=True)
    campaign = session.execute(query).scalar_one_or_none()
    if campaign is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return campaign


def _lock_lot(session: Session, lot_id: int) -> PromoLot:
    lot = session.execute(
        select(PromoLot).where(PromoLot.id == lot_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if lot is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return lot


def _post(session: Session, *, campaign_id: int, kind: PromoLedgerKind, amount_minor: int, reference_key: str,
          obligation_id: int | None = None, lot_id: int | None = None, redemption_id: int | None = None,
          budget_request_id: int | None = None, actor_user_id: int | None = None, reason: str | None = None,
          reversal_of_id: int | None = None) -> PromoLedgerTransaction:
    """Append one promo ledger movement. The DB trigger applies it to the budget and refuses overspending."""
    validate_minor_amount(amount_minor, allow_zero=False)
    row = PromoLedgerTransaction(
        public_id=uuid.uuid4(),
        campaign_id=campaign_id,
        kind=kind.value,
        amount_minor=amount_minor,
        reference_key=reference_key,
        obligation_id=obligation_id,
        lot_id=lot_id,
        redemption_id=redemption_id,
        budget_request_id=budget_request_id,
        actor_user_id=actor_user_id,
        reason=reason,
        reversal_of_id=reversal_of_id,
    )
    _flush_translating(session, row)
    return row


def _touch(row: Any, now: datetime) -> None:
    row.version += 1
    if hasattr(row, "updated_at"):
        row.updated_at = now


# --- campaigns and versions (Q105) -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionTerms:
    """Terms of one immutable campaign version. ``None`` = not decided (never read as 0)."""

    referrer_reward_minor: int | None = None
    referee_reward_minor: int | None = None
    referrer_instrument: PromoInstrument | None = None
    referee_instrument: PromoInstrument | None = None
    milestone_thresholds: tuple[int, ...] | None = None
    min_distinct_clients: int | None = None
    enrollment_limit: int | None = None
    qualification_window: timedelta | None = None
    reward_validity: timedelta | None = None
    review_sla: timedelta | None = None
    restoration_grace: timedelta | None = None
    margin_policy: PromoMarginPolicy | None = None
    approval_reference: str | None = None
    note: str | None = None


def _seconds(value: timedelta | None) -> int | None:
    return None if value is None else int(value.total_seconds())


def _delta(value: int | None) -> timedelta | None:
    return None if value is None else timedelta(seconds=value)


def create_campaign(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                    kind: PromoCampaignKind | str, service_type: ServiceType | str, name: str) -> PromoCampaign:
    """New campaign in ``draft``. Nothing is promised and no budget exists until finance allocates one."""
    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    kind = PromoCampaignKind(kind)
    campaign = PromoCampaign(
        public_id=uuid.uuid4(),
        kind=kind.value,
        family=_KIND_FAMILY[kind].value,
        service_type=ServiceType(service_type).value,
        name=_require_text(name, "name"),
        status=PromoCampaignStatus.DRAFT.value,
        created_by=actor_user_id,
    )
    session.add(campaign)
    session.flush()
    _audit(session, actor_user_id, "promo_campaigns", campaign.id, "campaign_created",
           {"kind": kind.value, "service_type": campaign.service_type, "name": campaign.name})
    return campaign


def add_campaign_version(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                         campaign_id: int, terms: VersionTerms) -> PromoCampaignVersion:
    """Append a new immutable version. Existing versions - and every promise made under them - never change."""
    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    campaign = _lock_campaign(session, campaign_id)
    if campaign.status == PromoCampaignStatus.CLOSED.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "promo_campaign", "from": "closed"})
    policy = terms.margin_policy
    next_no = 1 + session.execute(
        select(func.coalesce(func.max(PromoCampaignVersion.version_no), 0))
        .where(PromoCampaignVersion.campaign_id == campaign.id)
    ).scalar_one()
    version = PromoCampaignVersion(
        campaign_id=campaign.id,
        version_no=next_no,
        referrer_reward_minor=terms.referrer_reward_minor,
        referee_reward_minor=terms.referee_reward_minor,
        referrer_instrument=None if terms.referrer_instrument is None else PromoInstrument(terms.referrer_instrument).value,
        referee_instrument=None if terms.referee_instrument is None else PromoInstrument(terms.referee_instrument).value,
        milestone_thresholds=None if terms.milestone_thresholds is None else list(terms.milestone_thresholds),
        min_distinct_clients=terms.min_distinct_clients,
        enrollment_limit=terms.enrollment_limit,
        qualification_window_s=_seconds(terms.qualification_window),
        reward_validity_s=_seconds(terms.reward_validity),
        review_sla_s=_seconds(terms.review_sla),
        restoration_grace_s=_seconds(terms.restoration_grace),
        max_discount_share_bps=None if policy is None else policy.max_discount_share_bps,
        max_discount_per_booking_minor=None if policy is None else policy.max_discount_per_booking_minor,
        passenger_bonus_max_per_booking_minor=None if policy is None else policy.passenger_bonus_max_per_booking_minor,
        driver_credit_max_per_booking_minor=None if policy is None else policy.driver_credit_max_per_booking_minor,
        variable_cost_fixed_minor=None if policy is None else policy.variable_cost_fixed_minor,
        variable_cost_bps=None if policy is None else policy.variable_cost_bps,
        min_margin_minor=None if policy is None else policy.min_margin_minor,
        approval_reference=terms.approval_reference,
        note=terms.note,
        created_by=actor_user_id,
    )
    session.add(version)
    savepoint = session.begin_nested()
    try:
        session.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if _constraint_of(exc) == "uq_promo_campaign_versions_campaign_no":
            # A concurrent version got the same number; the caller retries with a fresh read.
            raise DomainError(ErrorCode.VERSION_CONFLICT, details={"reason": "version_number_taken"}) from exc
        raise
    savepoint.commit()
    _audit(session, actor_user_id, "promo_campaign_versions", version.id, "campaign_version_added",
           {"campaign_id": campaign.id, "version_no": next_no})
    return version


def version_terms(session: Session, campaign: PromoCampaign, version: PromoCampaignVersion) -> CampaignTerms:
    """The contract view of a stored version, with the budget actually allocated to the campaign."""
    allocated = budget_position(session, campaign.id).allocated_minor
    policy = PromoMarginPolicy(
        max_discount_share_bps=version.max_discount_share_bps,
        max_discount_per_booking_minor=version.max_discount_per_booking_minor,
        passenger_bonus_max_per_booking_minor=version.passenger_bonus_max_per_booking_minor,
        driver_credit_max_per_booking_minor=version.driver_credit_max_per_booking_minor,
        variable_cost_fixed_minor=version.variable_cost_fixed_minor,
        variable_cost_bps=version.variable_cost_bps,
        min_margin_minor=version.min_margin_minor,
    )
    return CampaignTerms(
        kind=PromoCampaignKind(campaign.kind),
        service_type=ServiceType(campaign.service_type),
        budget_allocated_minor=allocated if allocated > 0 else None,
        referrer_reward_minor=version.referrer_reward_minor,
        referee_reward_minor=version.referee_reward_minor,
        referrer_instrument=None if version.referrer_instrument is None else PromoInstrument(version.referrer_instrument),
        referee_instrument=None if version.referee_instrument is None else PromoInstrument(version.referee_instrument),
        milestone_thresholds=None if version.milestone_thresholds is None else tuple(version.milestone_thresholds),
        min_distinct_clients=version.min_distinct_clients,
        enrollment_limit=version.enrollment_limit,
        qualification_window=_delta(version.qualification_window_s),
        reward_validity=_delta(version.reward_validity_s),
        review_sla=_delta(version.review_sla_s),
        restoration_grace=_delta(version.restoration_grace_s),
        margin_policy=policy,
        approval_reference=version.approval_reference,
    )


def _campaign_transition(session: Session, campaign: PromoCampaign, target: PromoCampaignStatus, command: str,
                         *, actor_user_id: int | None, reason: str | None, now: datetime,
                         details: dict[str, Any] | None = None) -> PromoCampaign:
    PROMO_CAMPAIGN.assert_transition(campaign.status, target.value, command)
    previous = campaign.status
    campaign.status = target.value
    _touch(campaign, now)
    _flush_translating(session)
    _audit(session, actor_user_id, "promo_campaigns", campaign.id, f"campaign_{command}",
           {"from": previous, "to": target.value, **(details or {})}, reason)
    return campaign


def _check_version(campaign: PromoCampaign, expected_version: int) -> None:
    if campaign.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": campaign.version})


def activate_campaign(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                      campaign_id: int, version_id: int, expected_version: int, reason: str,
                      now: datetime | None = None) -> PromoCampaign:
    """``draft|paused -> active`` under a complete version (Q105, Q111). The DB re-checks the same rules."""
    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    now = _now(now)
    campaign = _lock_campaign(session, campaign_id)
    _check_version(campaign, expected_version)
    version = session.get(PromoCampaignVersion, version_id)
    if version is None or version.campaign_id != campaign.id:
        raise DomainError(ErrorCode.NOT_FOUND)
    terms = version_terms(session, campaign, version)
    validate_activation(terms)
    position = budget_position(session, campaign.id)
    if position.shortfall_minor or not position.accepts_new_enrollments(max_commitment_for(terms)):
        raise DomainError(ErrorCode.PROMO_BUDGET_EXHAUSTED,
                          details={"available_minor": position.available_for_new_minor})
    command = {
        PromoCampaignStatus.DRAFT.value: "activate",
        PromoCampaignStatus.PAUSED.value: "resume",
        PromoCampaignStatus.ACTIVE.value: "switch_version",
    }.get(campaign.status, "activate")
    campaign.active_version_id = version.id
    return _campaign_transition(session, campaign, PromoCampaignStatus.ACTIVE, command,
                                actor_user_id=actor_user_id, reason=_require_text(reason, "reason"), now=now,
                                details={"version_id": version.id})


def pause_campaign(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                   campaign_id: int, expected_version: int, reason: str, now: datetime | None = None) -> PromoCampaign:
    """No new enrollments. Promises already made and granted bonuses stay valid and spendable (task §8)."""
    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    campaign = _lock_campaign(session, campaign_id)
    _check_version(campaign, expected_version)
    return _campaign_transition(session, campaign, PromoCampaignStatus.PAUSED, "pause",
                                actor_user_id=actor_user_id, reason=_require_text(reason, "reason"), now=_now(now))


def resume_campaign(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                    campaign_id: int, expected_version: int, reason: str, now: datetime | None = None) -> PromoCampaign:
    campaign = _lock_campaign(session, campaign_id)
    if campaign.active_version_id is None:
        raise DomainError(ErrorCode.PROMO_PARAMETERS_UNSET, details={"fields": ["active_version_id"]})
    return activate_campaign(session, actor_user_id=actor_user_id, actor_capabilities=actor_capabilities,
                             campaign_id=campaign_id, version_id=campaign.active_version_id,
                             expected_version=expected_version, reason=reason, now=now)


def close_campaign(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                   campaign_id: int, expected_version: int, reason: str, now: datetime | None = None) -> PromoCampaign:
    """No new enrollments ever. Existing promises are still honoured or released by their own rules."""
    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    campaign = _lock_campaign(session, campaign_id)
    _check_version(campaign, expected_version)
    command = "discard" if campaign.status == PromoCampaignStatus.DRAFT.value else "close"
    return _campaign_transition(session, campaign, PromoCampaignStatus.CLOSED, command,
                                actor_user_id=actor_user_id, reason=_require_text(reason, "reason"), now=_now(now))


# --- Q123: approved campaign combinations ----------------------------------------------------------------------


def approve_combination(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                        campaign_a: int, campaign_b: int, cost_basis: str, reason: str,
                        now: datetime | None = None) -> PromoCampaignCombination:
    """Q123: allow a passenger-bonus campaign and a driver-credit campaign to fund one booking together, stating
    how their O relate (``shared``: the same cost - the larger counts; ``additive``: separate costs - both count).
    super_admin (``promo.campaign_manage``); audited; nothing is combined without such a row."""
    from app.contracts.promo import CostBasis, campaign_pair

    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    reason = _require_text(reason, "reason")
    try:
        basis = CostBasis(cost_basis)
        low, high = campaign_pair(campaign_a, campaign_b)
    except ValueError as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "combination", "reason": str(exc)}) from exc
    for campaign_id in (low, high):
        _lock_campaign(session, campaign_id, share=True)
    existing = session.execute(select(PromoCampaignCombination).where(
        PromoCampaignCombination.campaign_low_id == low, PromoCampaignCombination.campaign_high_id == high,
        PromoCampaignCombination.status == "active")).scalar_one_or_none()
    if existing is not None:
        if existing.cost_basis == basis.value:
            return existing
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"reason": "combination_exists_revoke_first"})
    row = PromoCampaignCombination(public_id=uuid.uuid4(), campaign_low_id=low, campaign_high_id=high,
                                   cost_basis=basis.value, status="active", reason=reason, created_by=actor_user_id)
    _flush_translating(session, row)
    _audit(session, actor_user_id, "promo_campaign_combinations", row.id, "combination_approved",
           {"campaigns": [low, high], "cost_basis": basis.value}, reason)
    return row


def revoke_combination(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                       combination_id: int, expected_version: int, reason: str,
                       now: datetime | None = None) -> PromoCampaignCombination:
    """Stops *new* bookings from combining the pair. Agreements already made keep their recorded cost basis."""
    _require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    reason = _require_text(reason, "reason")
    now = _now(now)
    row = session.execute(select(PromoCampaignCombination).where(PromoCampaignCombination.id == combination_id)
                          .with_for_update(key_share=True).execution_options(populate_existing=True)
                          ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if row.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": row.version})
    if row.status != "active":
        return row
    row.status, row.revoked_by, row.revoked_at, row.revoke_reason = "revoked", actor_user_id, now, reason
    row.version += 1
    session.flush()
    _audit(session, actor_user_id, "promo_campaign_combinations", row.id, "combination_revoked", {}, reason)
    return row


def combinations_of(session: Session, campaign_id: int) -> list[PromoCampaignCombination]:
    return list(session.execute(select(PromoCampaignCombination).where(
        (PromoCampaignCombination.campaign_low_id == campaign_id)
        | (PromoCampaignCombination.campaign_high_id == campaign_id))
        .order_by(PromoCampaignCombination.id.desc())).scalars())


def pause_exhausted_campaigns(session: Session, *, now: datetime | None = None, limit: int = 100) -> list[int]:
    """System job: pause active campaigns that cannot cover one more maximum promise, or are in shortfall."""
    now = _now(now)
    paused: list[int] = []
    ids = session.execute(
        select(PromoCampaign.id).where(PromoCampaign.status == PromoCampaignStatus.ACTIVE.value)
        .order_by(PromoCampaign.id).limit(limit)
    ).scalars().all()
    for campaign_id in ids:
        campaign = _lock_campaign(session, campaign_id)
        if campaign.status != PromoCampaignStatus.ACTIVE.value or campaign.active_version_id is None:
            continue
        version = session.get(PromoCampaignVersion, campaign.active_version_id)
        position = budget_position(session, campaign.id)
        needed = max_commitment_for(version_terms(session, campaign, version))
        if position.accepts_new_enrollments(needed):
            continue
        _campaign_transition(session, campaign, PromoCampaignStatus.PAUSED, "budget_exhausted", actor_user_id=None,
                             reason="budget cannot cover one more maximum promise", now=now,
                             details={"available_minor": position.available_for_new_minor,
                                      "shortfall_minor": position.shortfall_minor, "needed_minor": needed})
        paused.append(campaign.id)
    return paused


# --- budget (Q105, Q114) ----------------------------------------------------------------------------------------


def pending_reinstatements_minor(session: Session, campaign_id: int) -> int:
    """Approved reinstatements still waiting for budget room (open ``reinstate_unfulfilled`` reviews): part of L."""
    if session.get_bind().dialect.name != "postgresql":
        return 0
    return int(session.execute(text("SELECT public.promo_pending_reinstatements(:c)"), {"c": campaign_id}).scalar_one())


def budget_position(session: Session, campaign_id: int) -> BudgetPosition:
    row = session.execute(select(PromoBudget).where(PromoBudget.campaign_id == campaign_id)
                          .execution_options(populate_existing=True)).scalar_one_or_none()
    if row is None:
        return BudgetPosition(allocated_minor=0)
    return BudgetPosition(allocated_minor=row.allocated_minor, promised_minor=row.promised_minor,
                          granted_minor=row.granted_minor, consumed_minor=row.consumed_minor,
                          released_minor=row.released_minor)


def _require_finance_staff(session: Session, user_id: int) -> None:
    from app.modules.wallet.service import is_finance_approver  # Q69 rule, reused as-is

    if not is_finance_approver(session, user_id):
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "approver_not_finance_staff"})


def request_budget_change(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                          campaign_id: int, kind: PromoLedgerKind | str, amount_minor: int, reason: str,
                          evidence_reference: str | None = None, now: datetime | None = None) -> PromoBudgetRequest:
    """Allocate or reduce a campaign budget.

    Up to ``TWO_PERSON_APPROVAL_THRESHOLD_MINOR`` it posts at once on the requester's own authority (finance or
    super_admin); above it the request waits for a *different* finance approver - the wallet's existing rule.

    G14: a plain ``reduce_allocation`` never takes the budget below spent + outstanding obligations (``B >= S + L``)
    - checked here and, finally, by the ledger trigger under the budget row lock. A real loss of external funding is
    a separate ``funding_loss`` with an evidence reference: it may leave a shortfall, cancels nothing, and pauses the
    campaign (new promises stop) when it posts.
    """
    _require_capability(actor_capabilities, Capability.PROMO_BUDGET_ALLOCATE)
    kind = PromoLedgerKind(kind)
    if kind not in _BUDGET_CHANGE_KINDS:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "kind"})
    validate_minor_amount(amount_minor, allow_zero=False)
    reason = _require_text(reason, "reason")
    if kind is PromoLedgerKind.FUNDING_LOSS:
        evidence_reference = _require_text(evidence_reference or "", "evidence_reference")
    _require_finance_staff(session, actor_user_id)
    now = _now(now)
    campaign = _lock_campaign(session, campaign_id)
    _check_reduction(session, campaign.id, kind, amount_minor)
    if campaign.status == PromoCampaignStatus.CLOSED.value and kind is PromoLedgerKind.ALLOCATE:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "promo_campaign", "from": "closed"})
    request = PromoBudgetRequest(
        public_id=uuid.uuid4(), campaign_id=campaign.id, kind=kind.value, amount_minor=amount_minor, reason=reason,
        evidence_reference=evidence_reference, status=PromoBudgetRequestStatus.PENDING.value,
        requested_by=actor_user_id,
    )
    session.add(request)
    session.flush()
    if budget_change_requires_second_approver(amount_minor):
        _audit(session, actor_user_id, "promo_budget_requests", request.id, "budget_change_requested",
               {"kind": kind.value, "amount_minor": amount_minor}, reason)
        return request
    _post_budget_request(session, request, actor_user_id=actor_user_id, now=now)
    return request


_BUDGET_CHANGE_KINDS = (PromoLedgerKind.ALLOCATE, PromoLedgerKind.REDUCE_ALLOCATION, PromoLedgerKind.FUNDING_LOSS)


def _check_reduction(session: Session, campaign_id: int, kind: PromoLedgerKind, amount_minor: int) -> None:
    """G14 in the service (clear details); the ledger trigger re-checks under the budget row lock."""
    if kind is PromoLedgerKind.REDUCE_ALLOCATION:
        budget_position(session, campaign_id).reduce_allocation(
            amount_minor, pending_reinstatements_minor=pending_reinstatements_minor(session, campaign_id))


def _post_budget_request(session: Session, request: PromoBudgetRequest, *, actor_user_id: int,
                         now: datetime) -> PromoLedgerTransaction:
    transaction = _post(
        session, campaign_id=request.campaign_id, kind=PromoLedgerKind(request.kind), amount_minor=request.amount_minor,
        reference_key=f"budget:{request.id}", budget_request_id=request.id, actor_user_id=actor_user_id,
        reason=request.reason,
    )
    request.status = PromoBudgetRequestStatus.POSTED.value
    request.ledger_transaction_id = transaction.id
    request.decided_at = now
    _touch(request, now)
    session.flush()
    _audit(session, actor_user_id, "promo_ledger_transactions", transaction.id, "budget_change_posted",
           {"budget_request_id": request.id, "kind": request.kind, "amount_minor": request.amount_minor},
           request.reason)
    if request.kind == PromoLedgerKind.FUNDING_LOSS.value:
        _escalate_funding_loss(session, request, actor_user_id=actor_user_id, now=now)
    return transaction


def _escalate_funding_loss(session: Session, request: PromoBudgetRequest, *, actor_user_id: int, now: datetime) -> None:
    """A funding loss stops new promises at once (pause) and is escalated; obligations and bonuses stay valid."""
    campaign = _lock_campaign(session, request.campaign_id)
    position = budget_position(session, campaign.id)
    if campaign.status == PromoCampaignStatus.ACTIVE.value:
        _campaign_transition(session, campaign, PromoCampaignStatus.PAUSED, "funding_loss", actor_user_id=actor_user_id,
                             reason=request.reason, now=now,
                             details={"shortfall_minor": position.shortfall_minor,
                                      "evidence_reference": request.evidence_reference})
    _audit(session, actor_user_id, "promo_campaigns", campaign.id, "funding_loss_escalated",
           {"budget_request_id": request.id, "shortfall_minor": position.shortfall_minor,
            "committed_minor": position.committed_minor, "allocated_minor": position.allocated_minor},
           request.reason)


def _lock_request(session: Session, request_id: int) -> PromoBudgetRequest:
    unlocked = session.get(PromoBudgetRequest, request_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    _lock_campaign(session, unlocked.campaign_id)
    return session.execute(
        select(PromoBudgetRequest).where(PromoBudgetRequest.id == request_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalar_one()


def _pending(request: PromoBudgetRequest, expected_version: int, target: str) -> None:
    if request.status != PromoBudgetRequestStatus.PENDING.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "promo_budget_request", "from": request.status, "to": target})
    if request.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": request.version})


def approve_budget_request(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                           request_id: int, expected_version: int, note: str | None = None,
                           now: datetime | None = None) -> PromoBudgetRequest:
    """Second, different finance approver posts a large budget change (Q17, Q114)."""
    _require_capability(actor_capabilities, Capability.PROMO_BUDGET_ALLOCATE)
    _require_finance_staff(session, actor_user_id)
    now = _now(now)
    request = _lock_request(session, request_id)
    _pending(request, expected_version, "posted")
    if request.requested_by == actor_user_id:
        raise DomainError(ErrorCode.SECOND_APPROVER_REQUIRED)
    request.approved_by = actor_user_id
    session.flush()
    _post_budget_request(session, request, actor_user_id=actor_user_id, now=now)
    _audit(session, actor_user_id, "promo_budget_requests", request.id, "budget_change_second_approved",
           {"amount_minor": request.amount_minor}, note)
    return request


def reject_budget_request(session: Session, *, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                          request_id: int, expected_version: int, reason: str,
                          now: datetime | None = None) -> PromoBudgetRequest:
    _require_capability(actor_capabilities, Capability.PROMO_BUDGET_ALLOCATE)
    _require_finance_staff(session, actor_user_id)
    reason = _require_text(reason, "reason")
    now = _now(now)
    request = _lock_request(session, request_id)
    _pending(request, expected_version, "rejected")
    if request.requested_by == actor_user_id:
        raise DomainError(ErrorCode.SECOND_APPROVER_REQUIRED, details={"reason": "requester_cannot_reject"})
    request.status = PromoBudgetRequestStatus.REJECTED.value
    request.rejected_by = actor_user_id
    request.reject_reason = reason
    request.decided_at = now
    _touch(request, now)
    session.flush()
    _audit(session, actor_user_id, "promo_budget_requests", request.id, "budget_change_rejected", {}, reason)
    return request


def withdraw_budget_request(session: Session, *, actor_user_id: int, request_id: int, expected_version: int,
                            now: datetime | None = None) -> PromoBudgetRequest:
    now = _now(now)
    request = _lock_request(session, request_id)
    _pending(request, expected_version, "withdrawn")
    if request.requested_by != actor_user_id:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "only_the_requester_withdraws"})
    request.status = PromoBudgetRequestStatus.WITHDRAWN.value
    request.decided_at = now
    _touch(request, now)
    session.flush()
    _audit(session, actor_user_id, "promo_budget_requests", request.id, "budget_change_withdrawn", {})
    return request


# --- obligations: promise, grant, release (Q115) ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RewardSpec:
    """One beneficiary's maximum reward inside an enrollment. Referrer and referee are separate specs."""

    beneficiary_user_id: int
    side: str  # "referrer" | "referee"
    instrument: PromoInstrument
    amount_minor: int
    reward_key: str
    milestone: int = 0


def promise_rewards(session: Session, *, campaign_id: int, rewards: Sequence[RewardSpec], source_type: str,
                    source_id: int, enrollment_id: int | None = None,
                    now: datetime | None = None) -> list[PromoObligation]:
    """Reserve every reward of one enrollment in the budget, all or nothing (task §8, QA #6, #7).

    Idempotent per ``reward_key``: a replay (same keys) returns the existing obligations and posts nothing. The
    budget check happens in the ledger trigger under the budget row lock, so parallel enrollments can never take
    the same remainder twice.
    """
    if not rewards:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "rewards"})
    now = _now(now)
    keys = [spec.reward_key for spec in rewards]
    existing = _obligations_by_key(session, keys)
    if len(existing) == len(keys):
        return [existing[key] for key in keys]
    if existing:
        raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"reason": "partial_enrollment_replay"})
    campaign = _lock_campaign(session, campaign_id, share=True)
    if campaign.status != PromoCampaignStatus.ACTIVE.value or campaign.active_version_id is None:
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"reason": "campaign_not_accepting_enrollments"})
    savepoint = session.begin_nested()
    created: list[PromoObligation] = []
    try:
        for spec in rewards:
            obligation = PromoObligation(
                public_id=uuid.uuid4(), campaign_id=campaign.id, campaign_version_id=campaign.active_version_id,
                beneficiary_user_id=spec.beneficiary_user_id, side=spec.side, milestone=spec.milestone,
                instrument=PromoInstrument(spec.instrument).value, service_type=campaign.service_type,
                amount_minor=validate_minor_amount(spec.amount_minor, allow_zero=False), reward_key=spec.reward_key,
                source_type=_require_text(source_type, "source_type"), source_id=source_id,
                status=PromoObligationStatus.PROMISED.value, enrollment_id=enrollment_id,
            )
            session.add(obligation)
            session.flush()
            session.add(PromoLedgerTransaction(
                public_id=uuid.uuid4(), campaign_id=campaign.id, kind=PromoLedgerKind.PROMISE.value,
                amount_minor=obligation.amount_minor, reference_key=f"promise:{obligation.id}",
                obligation_id=obligation.id,
            ))
            session.flush()
            created.append(obligation)
    except DBAPIError as exc:
        savepoint.rollback()
        name = _constraint_of(exc)
        if name == "uq_promo_obligations_reward_key":
            # a concurrent replay of the same enrollment won: return what it created
            replay = _obligations_by_key(session, keys)
            if len(replay) == len(keys):
                return [replay[key] for key in keys]
        code = _CONSTRAINT_ERRORS.get(name or "")
        if code is None:
            raise
        raise DomainError(code, details={"reason": name}) from exc
    savepoint.commit()
    for obligation in created:
        _audit(session, None, "promo_obligations", obligation.id, "reward_promised",
               {"campaign_id": campaign.id, "amount_minor": obligation.amount_minor, "side": obligation.side})
    return created


def _obligations_by_key(session: Session, keys: Sequence[str]) -> dict[str, PromoObligation]:
    rows = session.execute(select(PromoObligation).where(PromoObligation.reward_key.in_(list(keys)))).scalars().all()
    return {row.reward_key: row for row in rows}


def _lock_obligation(session: Session, obligation_id: int) -> PromoObligation:
    unlocked = session.get(PromoObligation, obligation_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    _lock_campaign(session, unlocked.campaign_id, share=True)
    return session.execute(
        select(PromoObligation).where(PromoObligation.id == obligation_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalar_one()


def grant_obligation(session: Session, *, obligation_id: int, granted_minor: int | None = None,
                     hold_for_review: bool = False, now: datetime | None = None) -> PromoLot:
    """Qualification: the promise becomes a bonus lot (promised -> granted). Idempotent per obligation.

    Any part of the promise that is not granted is released back to the budget in the same transaction. Works
    on paused or closed campaigns: a promise made is a promise kept (task §8).
    """
    now = _now(now)
    obligation = _lock_obligation(session, obligation_id)
    if obligation.status == PromoObligationStatus.GRANTED.value:
        lot = session.execute(select(PromoLot).where(PromoLot.obligation_id == obligation.id)).scalar_one()
        return lot
    PROMO_OBLIGATION.assert_transition(obligation.status, PromoObligationStatus.GRANTED.value, "grant")
    amount = obligation.amount_minor if granted_minor is None else validate_minor_amount(granted_minor, allow_zero=False)
    if amount > obligation.amount_minor:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "grant_exceeds_promise"})
    version = session.get(PromoCampaignVersion, obligation.campaign_version_id)
    if not version.reward_validity_s:
        raise DomainError(ErrorCode.PROMO_PARAMETERS_UNSET, details={"fields": ["reward_validity"]})
    lot = PromoLot(
        public_id=uuid.uuid4(), obligation_id=obligation.id, campaign_id=obligation.campaign_id,
        owner_user_id=obligation.beneficiary_user_id, instrument=obligation.instrument,
        service_type=obligation.service_type, amount_minor=amount,
        status=(PromoRewardStatus.PENDING_REVIEW if hold_for_review else PromoRewardStatus.AVAILABLE).value,
        # the spend period starts when the holder can spend (a lot held for review restarts it on release)
        available_from=None if hold_for_review else now,
        expires_at=now + timedelta(seconds=version.reward_validity_s),
    )
    session.add(lot)
    session.flush()
    _post(session, campaign_id=obligation.campaign_id, kind=PromoLedgerKind.GRANT, amount_minor=amount,
          reference_key=f"grant:{obligation.id}", obligation_id=obligation.id, lot_id=lot.id)
    if amount < obligation.amount_minor:
        _post(session, campaign_id=obligation.campaign_id, kind=PromoLedgerKind.RELEASE_PROMISE,
              amount_minor=obligation.amount_minor - amount, reference_key=f"release_promise:{obligation.id}",
              obligation_id=obligation.id)
    obligation.status = PromoObligationStatus.GRANTED.value
    obligation.decided_at = now
    _touch(obligation, now)
    session.flush()
    _audit(session, None, "promo_lots", lot.id, "reward_granted",
           {"obligation_id": obligation.id, "amount_minor": amount, "status": lot.status})
    return lot


def release_obligation(session: Session, *, obligation_id: int, reason: str, actor_user_id: int | None = None,
                       now: datetime | None = None) -> PromoObligation:
    """The promise will not be earned (expired / rejected): its reserve returns to the budget. Idempotent."""
    now = _now(now)
    obligation = _lock_obligation(session, obligation_id)
    if obligation.status == PromoObligationStatus.RELEASED.value:
        return obligation
    PROMO_OBLIGATION.assert_transition(obligation.status, PromoObligationStatus.RELEASED.value, "release")
    _post(session, campaign_id=obligation.campaign_id, kind=PromoLedgerKind.RELEASE_PROMISE,
          amount_minor=obligation.amount_minor, reference_key=f"release_promise:{obligation.id}",
          obligation_id=obligation.id, actor_user_id=actor_user_id, reason=reason)
    obligation.status = PromoObligationStatus.RELEASED.value
    obligation.decided_at = now
    _touch(obligation, now)
    session.flush()
    _audit(session, actor_user_id, "promo_obligations", obligation.id, "reward_promise_released",
           {"amount_minor": obligation.amount_minor}, _require_text(reason, "reason"))
    return obligation


# --- lots and redemptions (QA #9, #14, #15, #16) ----------------------------------------------------------------


def _available(lot: PromoLot) -> int:
    return lot.amount_minor - lot.reserved_minor - lot.consumed_minor - lot.expired_minor - lot.reversed_minor


def make_lot_available(session: Session, *, lot_id: int, actor_user_id: int | None = None,
                       actor_capabilities: Collection[Capability | str] | None = None, reason: str | None = None,
                       now: datetime | None = None) -> PromoLot:
    """``pending_review -> available``: by the system after a clean risk window, or by admin+ after review."""
    if actor_user_id is not None:
        _require_capability(actor_capabilities or (), Capability.PROMO_FRAUD_DECIDE)
    now = _now(now)
    lot = _lock_lot(session, lot_id)
    if lot.status == PromoRewardStatus.AVAILABLE.value:
        return lot
    PROMO_REWARD.assert_transition(lot.status, PromoRewardStatus.AVAILABLE.value, "release_to_holder")
    lot.status = PromoRewardStatus.AVAILABLE.value
    if lot.available_from is None:
        # never let the spend period run while the holder could not spend: it starts now
        version = session.get(PromoCampaignVersion, session.get(PromoObligation, lot.obligation_id).campaign_version_id)
        lot.available_from = now
        lot.expires_at = now + timedelta(seconds=version.reward_validity_s)
    _touch(lot, now)
    session.flush()
    _audit(session, actor_user_id, "promo_lots", lot.id, "reward_released_to_holder", {}, reason)
    return lot


def flag_lot_for_review(session: Session, *, lot_id: int, reason: str, now: datetime | None = None) -> PromoLot:
    """Q122: stop *new* spending of a lot under a post-grant review (``available -> pending_review``).

    Only the not-yet-reserved part is affected: reservations already made settle with their bookings (capture or
    release), a confirmed booking discount is never cancelled. The lot row lock orders this against ``reserve_lot``:
    whichever takes it first wins - a later reserve sees ``pending_review`` and refuses only that accept attempt.
    Lots in any other state are left alone. Idempotent.
    """
    now = _now(now)
    lot = _lock_lot(session, lot_id)
    if lot.status != PromoRewardStatus.AVAILABLE.value:
        return lot
    PROMO_REWARD.assert_transition(lot.status, PromoRewardStatus.PENDING_REVIEW.value, "flag_for_review")
    lot.status = PromoRewardStatus.PENDING_REVIEW.value
    _touch(lot, now)
    session.flush()
    _audit(session, None, "promo_lots", lot.id, "reward_spending_suspended", {"reserved_minor": lot.reserved_minor}, reason)
    return lot


def reserve_lot(session: Session, *, lot_id: int, booking_id: int, amount_minor: int, terms_seq: int = 1,
                now: datetime | None = None) -> PromoRedemption:
    """Hold part of a lot for one booking agreement. Idempotent per ``(lot, booking, terms_seq)``; never more than
    is available.

    The bookings orchestrator calls this inside the accept transaction (``promotions.booking``); which lot and how
    much come from the promo quote.
    """
    validate_minor_amount(amount_minor, allow_zero=False)
    now = _now(now)
    lot = _lock_lot(session, lot_id)
    existing = session.execute(
        select(PromoRedemption).where(PromoRedemption.lot_id == lot.id, PromoRedemption.booking_id == booking_id,
                                      PromoRedemption.terms_seq == terms_seq)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == PromoRedemptionStatus.RESERVED.value and existing.amount_minor == amount_minor:
            return existing
        raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"reason": "lot_already_used_for_booking"})
    if lot.status != PromoRewardStatus.AVAILABLE.value or now >= ensure_aware_utc(lot.expires_at, field="expires_at"):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "promo_reward", "from": lot.status, "command": "reserve"})
    if amount_minor > _available(lot):
        # Q119: refuses this accept attempt only; the caller re-quotes (the lot changed since the quote)
        raise DomainError(ErrorCode.PROMO_QUOTE_STALE,
                          details={"reasons": ["passenger_bonus_changed"], "available_minor": _available(lot),
                                   **STALE_SCOPE})
    PROMO_REWARD.assert_transition(lot.status, PromoRewardStatus.AVAILABLE.value, "reserve")
    redemption = PromoRedemption(public_id=uuid.uuid4(), lot_id=lot.id, booking_id=booking_id,
                                 amount_minor=amount_minor, terms_seq=terms_seq,
                                 status=PromoRedemptionStatus.RESERVED.value)
    session.add(redemption)
    lot.reserved_minor += amount_minor
    _touch(lot, now)
    session.flush()
    return redemption


def carry_reservation(session: Session, *, redemption_id: int, new_amount_minor: int, new_terms_seq: int,
                      fault: PromoFault | str, now: datetime | None = None) -> PromoRedemption | None:
    """Amendment (Q116): move an existing reservation to the booking's next agreement, never growing it.

    The old redemption is released and, when ``new_amount_minor > 0``, a new one of that size is reserved on the
    same lot for ``new_terms_seq`` in the same step - a continuation of spending already agreed, so it is allowed on
    a lot that expired or went to review meanwhile. Only the difference leaves the booking; it follows
    ``release_redemption``'s fair-restoration rules (``fault`` = the amendment's author). Returns the new redemption.
    """
    now = _now(now)
    lot, old = _lock_redemption(session, redemption_id)
    if old.status != PromoRedemptionStatus.RESERVED.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "promo_redemption", "from": old.status, "command": "carry"})
    if not 0 <= new_amount_minor <= old.amount_minor:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "amendment_never_grows_a_discount"})
    fault = PromoFault(fault)
    PROMO_REDEMPTION.assert_transition(old.status, PromoRedemptionStatus.RELEASED.value, "release")
    old.status = PromoRedemptionStatus.RELEASED.value
    old.release_fault = fault.value
    old.settled_at = now
    old.version += 1
    lot.reserved_minor -= old.amount_minor - new_amount_minor  # the continuation never passes through "available"
    new = None
    if new_amount_minor > 0:
        new = PromoRedemption(public_id=uuid.uuid4(), lot_id=lot.id, booking_id=old.booking_id,
                              amount_minor=new_amount_minor, terms_seq=new_terms_seq,
                              status=PromoRedemptionStatus.RESERVED.value)
        session.add(new)
    if old.amount_minor > new_amount_minor:
        _return_to_lot(session, lot, old, old.amount_minor - new_amount_minor, fault, now)
    else:
        _touch(lot, now)
        session.flush()
    return new


def _lock_redemption(session: Session, redemption_id: int) -> tuple[PromoLot, PromoRedemption]:
    unlocked = session.get(PromoRedemption, redemption_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    lot = _lock_lot(session, unlocked.lot_id)
    redemption = session.execute(
        select(PromoRedemption).where(PromoRedemption.id == redemption_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalar_one()
    return lot, redemption


def consume_redemption(session: Session, *, redemption_id: int, now: datetime | None = None) -> PromoRedemption:
    """Reserved -> consumed, once (stage 4: together with the booking's commission capture).

    Idempotent: a second call on a consumed redemption returns it and posts nothing. Works on expired or reversed
    lots too - the reservation was made while the lot was valid.
    """
    now = _now(now)
    lot, redemption = _lock_redemption(session, redemption_id)
    if redemption.status == PromoRedemptionStatus.CONSUMED.value:
        return redemption
    PROMO_REDEMPTION.assert_transition(redemption.status, PromoRedemptionStatus.CONSUMED.value, "consume")
    redemption.status = PromoRedemptionStatus.CONSUMED.value
    redemption.settled_at = now
    redemption.version += 1
    lot.reserved_minor -= redemption.amount_minor
    lot.consumed_minor += redemption.amount_minor
    if lot.consumed_minor == lot.amount_minor and lot.status != PromoRewardStatus.REVERSED.value:
        lot.status = PromoRewardStatus.EXHAUSTED.value
    _touch(lot, now)
    session.flush()
    _post(session, campaign_id=lot.campaign_id, kind=PromoLedgerKind.CONSUME, amount_minor=redemption.amount_minor,
          reference_key=f"consume:{redemption.id}", lot_id=lot.id, redemption_id=redemption.id)
    return redemption


def release_redemption(session: Session, *, redemption_id: int, fault: PromoFault | str,
                       now: datetime | None = None) -> PromoRedemption:
    """Reserved -> released: the value returns to the lot (stage 4: booking cancelled before service).

    Fair restoration (ADR-0023 §7): if the driver or the platform caused the release and the lot has expired or
    has less than the campaign's grace left, the lot lives until ``now + grace``. On a client-fault release of an
    expired lot the returned value expires. Idempotent.
    """
    now = _now(now)
    fault = PromoFault(fault)
    lot, redemption = _lock_redemption(session, redemption_id)
    if redemption.status == PromoRedemptionStatus.RELEASED.value:
        return redemption
    PROMO_REDEMPTION.assert_transition(redemption.status, PromoRedemptionStatus.RELEASED.value, "release")
    redemption.status = PromoRedemptionStatus.RELEASED.value
    redemption.release_fault = fault.value
    redemption.settled_at = now
    redemption.version += 1
    lot.reserved_minor -= redemption.amount_minor
    _return_to_lot(session, lot, redemption, redemption.amount_minor, fault, now)
    return redemption


def _return_to_lot(session: Session, lot: PromoLot, redemption: PromoRedemption, returned_minor: int,
                   fault: PromoFault, now: datetime) -> None:
    """``returned_minor`` of a released reservation leaves the booking: back to the holder, restored with grace, or -
    on an expired / reversed lot - out of the lot and back to the budget (ADR-0023 §7)."""
    expires_at = ensure_aware_utc(lot.expires_at, field="expires_at")
    version = session.get(PromoCampaignVersion, session.get(PromoObligation, lot.obligation_id).campaign_version_id)
    grace = timedelta(seconds=version.restoration_grace_s) if version.restoration_grace_s else None
    # Q129: the holder of *this* lot is judged on its own (client for a bonus, driver for a credit)
    new_expiry = None if grace is None else restored_expiry(lot_expires_at=expires_at, released_at=now, fault=fault,
                                                            grace=grace, instrument=lot.instrument)
    returned_to_budget = 0
    release_key = ""
    if lot.status == PromoRewardStatus.REVERSED.value:
        # the reward was reversed while this reservation was in flight: the value is reversed, not restored
        lot.reversed_minor += returned_minor
        returned_to_budget = returned_minor
        release_key = f"release_granted:reversal-redemption:{redemption.id}"
        new_expiry = None
    elif new_expiry is not None:
        redemption.restored_from, redemption.restored_until = expires_at, new_expiry  # a later decision may undo it
        lot.expires_at = new_expiry
        if lot.status == PromoRewardStatus.EXPIRED.value:
            lot.status = PromoRewardStatus.AVAILABLE.value
    elif now >= expires_at:
        # the lot is past its end: the returned value *and* any free remainder expire together - once the lot is
        # ``expired`` the expiry job no longer visits it, so nothing may stay "available" on it
        free = _available(lot)
        lot.expired_minor += free
        lot.status = PromoRewardStatus.EXPIRED.value
        returned_to_budget = free
        # an expiry release: a later reinstatement may point at it (0086 promo_ledger_reinstate_check)
        release_key = f"release_granted:expiry-redemption:{redemption.id}"
    _touch(lot, now)
    session.flush()
    if returned_to_budget:
        _post(session, campaign_id=lot.campaign_id, kind=PromoLedgerKind.RELEASE_GRANTED,
              amount_minor=returned_to_budget, reference_key=release_key,
              lot_id=lot.id)
    _audit(session, None, "promo_redemptions", redemption.id, "redemption_released",
           {"fault": fault.value, "amount_minor": redemption.amount_minor, "returned_minor": returned_minor,
            "restored_until": None if new_expiry is None else new_expiry.isoformat()})


def withdraw_restoration(session: Session, *, redemption_id: int, actor_user_id: int,
                         actor_capabilities: Collection[Capability | str], reason: str,
                         now: datetime | None = None) -> PromoLot:
    """Q129: an admin decided the release *was* the holder's own fault after an ``undetermined`` cancel gave a grace
    extension. Only what is still unspent loses the extension: the lot's end goes back to ``max(now, original)`` -
    and if that is already past, its free part expires now (Q128). Value reserved or spent meanwhile is untouched;
    a lot whose end changed since (another release, a reinstatement) is left alone. Idempotent."""
    _require_capability(actor_capabilities, Capability.PROMO_FRAUD_DECIDE)
    reason = _require_text(reason, "reason")
    now = _now(now)
    lot, redemption = _lock_redemption(session, redemption_id)
    if redemption.restored_until is None:
        return lot
    until = ensure_aware_utc(redemption.restored_until, field="restored_until")
    if lot.status != PromoRewardStatus.AVAILABLE.value or ensure_aware_utc(lot.expires_at, field="expires_at") != until:
        return lot
    original = ensure_aware_utc(redemption.restored_from, field="restored_from")
    lot.expires_at = max(now, original)
    expired_now = 0
    if lot.expires_at <= now:
        expired_now = _available(lot)
        PROMO_REWARD.assert_transition(lot.status, PromoRewardStatus.EXPIRED.value, "expire")
        lot.expired_minor += expired_now
        lot.status = PromoRewardStatus.EXPIRED.value
    _touch(lot, now)
    session.flush()
    if expired_now:
        # an expiry release like any other: a later reinstatement may point at it (0086 reinstate check)
        _post(session, campaign_id=lot.campaign_id, kind=PromoLedgerKind.RELEASE_GRANTED, amount_minor=expired_now,
              reference_key=f"release_granted:expiry-withdrawn:{redemption.id}", lot_id=lot.id,
              actor_user_id=actor_user_id, reason=reason)
    _audit(session, actor_user_id, "promo_lots", lot.id, "restoration_withdrawn",
           {"redemption_id": redemption.id, "expired_minor": expired_now}, reason)
    return lot


def expire_due_lots(session: Session, *, now: datetime | None = None, limit: int = 100) -> list[int]:
    """System job: the free part of each due, available lot expires and its value returns to the budget.

    Reserved value is left to its booking; lots under review do not expire while a person decides.
    """
    now = _now(now)
    ids = session.execute(
        select(PromoLot.id).where(PromoLot.status == PromoRewardStatus.AVAILABLE.value, PromoLot.expires_at <= now)
        .order_by(PromoLot.id).limit(limit)
    ).scalars().all()
    expired: list[int] = []
    for lot_id in ids:
        lot = _lock_lot(session, lot_id)
        if lot.status != PromoRewardStatus.AVAILABLE.value or ensure_aware_utc(lot.expires_at, field="expires_at") > now:
            continue
        free = _available(lot)
        PROMO_REWARD.assert_transition(lot.status, PromoRewardStatus.EXPIRED.value, "expire")
        lot.expired_minor += free
        lot.status = PromoRewardStatus.EXPIRED.value
        _touch(lot, now)
        session.flush()
        if free:
            _post(session, campaign_id=lot.campaign_id, kind=PromoLedgerKind.RELEASE_GRANTED, amount_minor=free,
                  reference_key=f"release_granted:expiry:{lot.id}:{lot.version}", lot_id=lot.id)
        expired.append(lot.id)
    return expired


def reverse_lot(session: Session, *, lot_id: int, actor_user_id: int, actor_capabilities: Collection[Capability | str],
                reason: str, now: datetime | None = None) -> PromoLot:
    """Reverse a reward (admin+ after review). Only unspent value returns to the budget.

    Consumed value stays consumed - a risk cost, never a debt on anyone's real balance (QA #16). A reservation in
    flight settles with its booking; if it is released later, that value is reversed too.
    """
    _require_capability(actor_capabilities, Capability.PROMO_FRAUD_DECIDE)
    reason = _require_text(reason, "reason")
    now = _now(now)
    lot = _lock_lot(session, lot_id)
    if lot.status == PromoRewardStatus.REVERSED.value:
        return lot
    PROMO_REWARD.assert_transition(lot.status, PromoRewardStatus.REVERSED.value, "reverse")
    free = _available(lot)
    lot.reversed_minor += free
    lot.status = PromoRewardStatus.REVERSED.value
    _touch(lot, now)
    session.flush()
    if free:
        _post(session, campaign_id=lot.campaign_id, kind=PromoLedgerKind.RELEASE_GRANTED, amount_minor=free,
              reference_key=f"release_granted:reversal:{lot.id}", lot_id=lot.id, actor_user_id=actor_user_id,
              reason=reason)
    _audit(session, actor_user_id, "promo_lots", lot.id, "reward_reversed",
           {"reversed_minor": free, "reserved_minor": lot.reserved_minor, "risk_cost_minor": lot.consumed_minor}, reason)
    return lot


# --- reconciliation (QA #24) --------------------------------------------------------------------------------------


def reconciliation_issues(session: Session, campaign_id: int | None = None) -> list[dict[str, Any]]:
    """Promo ledger vs budget cache vs obligations vs lots vs redemptions. Empty list = consistent."""
    issues: list[dict[str, Any]] = []
    where = "" if campaign_id is None else "WHERE campaign_id = :c"
    params = {} if campaign_id is None else {"c": campaign_id}
    for row in session.execute(text(
        f"SELECT obligation_id, issue FROM promo_obligation_reconciliation {where} "
        f"{'AND' if where else 'WHERE'} issue IS NOT NULL"), params):
        issues.append({"kind": "obligation", "id": row.obligation_id, "issue": row.issue})
    campaign_filter = "" if campaign_id is None else "AND b.campaign_id = :c"
    for row in session.execute(text(
        f"""
        SELECT b.campaign_id, b.granted_minor, b.consumed_minor,
               COALESCE(l.outstanding, 0) AS lots_outstanding, COALESCE(l.consumed, 0) AS lots_consumed
          FROM promo_budgets b
          LEFT JOIN (SELECT campaign_id,
                            SUM(amount_minor - consumed_minor - expired_minor - reversed_minor) AS outstanding,
                            SUM(consumed_minor) AS consumed
                       FROM promo_lots GROUP BY campaign_id) l ON l.campaign_id = b.campaign_id
         WHERE (b.granted_minor <> COALESCE(l.outstanding, 0) OR b.consumed_minor <> COALESCE(l.consumed, 0))
         {campaign_filter}
        """), params):
        issues.append({"kind": "budget_vs_lots", "campaign_id": row.campaign_id, "granted_minor": int(row.granted_minor),
                       "lots_outstanding_minor": int(row.lots_outstanding), "consumed_minor": int(row.consumed_minor),
                       "lots_consumed_minor": int(row.lots_consumed)})  # SUM() is numeric: money stays an integer
    if campaign_id is None:
        # QA #24: the promo terms against the real commission money of the same booking. A captured hold is exactly
        # the agreed C_net and consumed exactly its P and H; a released hold consumed nothing.
        for row in session.execute(text(
            """
            SELECT booking_id, hold_status, net_commission_minor, captured_minor, passenger_bonus_minor,
                   driver_credit_minor, consumed_passenger_bonus_minor, consumed_driver_credit_minor
              FROM promo_booking_finance
             WHERE passenger_bonus_minor + driver_credit_minor > 0
               AND ((hold_status = 'captured' AND (captured_minor <> net_commission_minor
                                                   OR consumed_passenger_bonus_minor <> passenger_bonus_minor
                                                   OR consumed_driver_credit_minor <> driver_credit_minor))
                    OR (hold_status = 'released'
                        AND consumed_passenger_bonus_minor + consumed_driver_credit_minor > 0))
            """)):
            issues.append({"kind": "booking_vs_commission", "booking_id": row.booking_id, "hold_status": row.hold_status,
                           **{name: int(getattr(row, name)) for name in (
                               "net_commission_minor", "captured_minor", "passenger_bonus_minor",
                               "consumed_passenger_bonus_minor", "driver_credit_minor", "consumed_driver_credit_minor")}})
    return issues


def campaign_kinds_available_in_pilot() -> frozenset[PromoCampaignKind]:
    return PILOT_CAMPAIGN_KINDS


def on_account_deleted(session: Session, *, user_id: int) -> None:
    """Public entry for the account-deletion flow (ADR-0006: v1 reaches v2 only through ``service``).

    Detaches the promotions identity and, while no retention period is approved (Q108), purges its digests.
    """
    from app.modules.promotions.identity import on_account_deleted as detach_identity

    detach_identity(session, user_id=user_id)
