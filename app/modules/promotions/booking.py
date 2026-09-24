"""Promotions inside the booking flow (referral stages 4-5, ADR-0023 §18, §18.1): consent, quote, reservations, C_net.

Called only by the bookings orchestrator (A4), inside *its* transaction - accept, amendment, cancel, completion,
``finalize_fee`` - never the other way round, and never ``commit``.

**Accept is split in two** because the booking's frozen ``terms_snapshot`` must say whether promo terms exist
(``booking_promo_marker``) before the row is inserted:

1. :func:`prepare_accept` - after the caller locked the driver's wallet account (lock order: ``wallet_accounts`` ->
   ``promo_consents`` -> ``promo_campaigns`` (FOR SHARE) -> ``promo_lots`` (id ASC)). Re-quotes on the server from the
   locked lots and the consent (``quote_at_accept``); nothing the client sends is taken as an amount.
2. :func:`commit_accept` - after the booking row exists: lot reservations (``promo_redemptions``), the immutable
   ``promo_booking_terms`` row and the consent marked used. The caller then holds **C_net** (not C) on the real
   balance; the deferred ``promo_booking_terms_verify`` refuses the commit if hold, redemptions and terms disagree.

**One campaign per instrument (Q123):** P comes from one campaign (several of its lots may be used), H from one
campaign. Two different campaigns meet on a booking only under an explicit approved combination
(``promo_campaign_combinations``) that states the cost basis of their O; the total caps take the strictest value.
If adding H would change the P the client agreed to, H is not applied - P is never lowered to make room.

**Never a silent cash increase (Q104):** a consented passenger bonus that cannot be applied exactly - spent
elsewhere, expired, under review, promotions switched off, parameters unset, counterparty app not confirmed - refuses
*this attempt* with ``PROMO_QUOTE_STALE`` (``STALE_SCOPE``); the booking is not created with a larger cash amount.
Driver Credit that cannot be applied simply is not (it never changes what the client pays). A deal with H only needs
no promo capability from the client (Q124).

**Readiness is evidence with an end (Q126):** the acting party's capability is its own request header; the passive
party's readiness is its consent (client) or its readiness row (driver), bound to one proposal version or amendment,
the login session that gave it and that subject's expiry. A later detected change - another live login declaring,
a declaration without the capability, the session ended - makes it stale and a new confirmation is asked for. This
detects what the server can see; it does not claim to catch every downgraded app.

**Amendments (Q116, Q125):** a promo booking's discount is recomputed under the same campaigns, within the booking's
own reservations - no new lot, never more than before. Changed F / P / F_cash needs the client's explicit consent;
changed cash to collect / commission charged needs the driver's acknowledgement of the new numbers. The previous
agreement and its reservations stay until the change is accepted.

**Legacy vs broken:** a booking without the marker is legacy (P = H = 0). A booking whose marker says ``applied``
must have valid terms; a missing or inconsistent row is an ``INTEGRITY_CONFLICT``, never read as "no promo".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.contracts.enums import (
    ActorSide,
    FaultSide,
    FeatureFlagKey,
    PromoFault,
    PromoInstrument,
    PromoRedemptionStatus,
    PromoRewardStatus,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import (
    PROMO_CASH_FEATURE,
    STALE_SCOPE,
    DriverCreditOutcome,
    FundingSource,
    PassengerBonusConsent,
    PromoMarginPolicy,
    PromoQuote,
    PromoSnapshotState,
    amendment_reconfirmation,
    campaign_pair,
    choose_driver_source,
    choose_passenger_source,
    client_view,
    combined_margin_policy,
    driver_view,
    passenger_bonus_allowed,
    plain_quote,
    promo_snapshot_state,
    quote_at_accept,
    quote_from_terms,
    quote_promo,
    strictest_margin_policy,
)
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions import service as promo_service
from app.modules.promotions.models import (
    PromoBookingTerms,
    PromoCampaignCombination,
    PromoCampaignVersion,
    PromoClientFeatures,
    PromoConsent,
    PromoLot,
    PromoObligation,
    PromoPartyReadiness,
    PromoRedemption,
)

__all__ = [
    "AcceptPlan",
    "AmendmentPlan",
    "ConsentInput",
    "DriverAck",
    "after_commission_reversal",
    "booking_has_promo",
    "cash_terms_differ_for",
    "client_promo_view",
    "commit_accept",
    "commit_amendment",
    "confirm_amendment",
    "confirm_current_version",
    "consume_reservations",
    "declared_features",
    "driver_promo_view",
    "fault_for_cancel",
    "fault_for_side",
    "no_discount_reason",
    "note_client_features",
    "note_dispute_resolved",
    "note_version_readiness",
    "prepare_accept",
    "prepare_amendment",
    "record_consent",
    "release_reservations",
    "terms_for_booking",
    "version_confirmation_state",
]

P = PromoInstrument.PASSENGER_BONUS.value
H = PromoInstrument.DRIVER_CREDIT.value


@dataclass(frozen=True, slots=True)
class ConsentInput:
    """What the client says they saw and agree to. Checked against the server's quote; never used as an amount."""

    passenger_bonus_minor: int
    cash_due_minor: int


@dataclass(frozen=True, slots=True)
class DriverAck:
    """Q125: the new driver-side numbers of an amendment the driver has seen. Checked, never used as an amount."""

    cash_to_collect_minor: int
    commission_charged_minor: int


def _stale(*reasons: str, **extra: object) -> DomainError:
    return DomainError(ErrorCode.PROMO_QUOTE_STALE, details={"reasons": list(reasons), **extra, **STALE_SCOPE})


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now, field="now")


# --- client features and readiness (Q110, Q126) -------------------------------------------------------------------


def note_client_features(session: Session, *, user_id: int, features: frozenset[str] | None,
                         session_ref: str | None = None, now: datetime | None = None) -> None:
    """Remember what the user's client last declared on a command, and from which login session.

    Q126: this is only a *change detector* - never the evidence for a deal. Callers do this as the *last* write of
    their transaction, so the row lock never sits between other locks. ``None`` = internal call: nothing recorded.
    """
    if features is None:
        return
    values = sorted(features)
    stmt = pg_insert(PromoClientFeatures).values(user_id=user_id, features=values, declared_at=_now(now),
                                                 session_ref=session_ref)
    session.execute(stmt.on_conflict_do_update(
        index_elements=["user_id"], set_={"features": values, "declared_at": _now(now), "session_ref": session_ref},
        where=(PromoClientFeatures.features != stmt.excluded.features)
        | PromoClientFeatures.session_ref.is_distinct_from(stmt.excluded.session_ref),
    ))


def declared_features(session: Session, user_id: int) -> frozenset[str] | None:
    """The user's last declaration, or ``None`` when the user's client never declared anything (unknown)."""
    row = session.get(PromoClientFeatures, user_id)
    return None if row is None else frozenset(row.features or ())


def _capable(features: Iterable[str] | None) -> bool:
    return features is not None and PROMO_CASH_FEATURE in set(features)


def _evidence_valid(session: Session, *, user_id: int, session_ref: str | None, features: Iterable[str] | None,
                    expires_at: datetime, now: datetime) -> bool:
    """Q126: is a passive party's earlier confirmation still usable *now*?

    It needs: the capability at the time, an unexpired subject, the login session not ended (logout, revoke,
    deletion, expiry), and no detected change since - a later declaration without the capability, or a later
    declaration from another *live* login. A refresh rotation keeps it (the rotation chain is not recorded, so a
    capable declaration from another device after a rotation cannot be told apart - known limit)."""
    from app.services.auth_service import login_session_state

    if not _capable(features) or now >= ensure_aware_utc(expires_at, field="expires_at"):
        return False
    state = login_session_state(session, session_ref, user_id)
    if state == "ended":
        return False
    last = session.get(PromoClientFeatures, user_id)
    if last is None or not _capable(last.features):
        return False
    return last.session_ref == session_ref or state == "rotated"


def _active_readiness(session: Session, *, user_id: int, proposal_version_id: int | None = None,
                      amendment_id: int | None = None) -> PromoPartyReadiness | None:
    query = select(PromoPartyReadiness).where(PromoPartyReadiness.status == "active",
                                              PromoPartyReadiness.user_id == user_id)
    query = (query.where(PromoPartyReadiness.proposal_version_id == proposal_version_id)
             if proposal_version_id is not None else query.where(PromoPartyReadiness.amendment_id == amendment_id))
    return session.execute(query).scalar_one_or_none()


def _record_readiness(session: Session, *, user_id: int, side: ActorSide, session_ref: str | None,
                      features: Iterable[str], expires_at: datetime, proposal_version_id: int | None = None,
                      amendment_id: int | None = None, acknowledged: Mapping[str, int] | None = None,
                      ) -> PromoPartyReadiness:
    previous = _active_readiness(session, user_id=user_id, proposal_version_id=proposal_version_id,
                                 amendment_id=amendment_id)
    if previous is not None:
        previous.status = "superseded"
        session.flush()
    row = PromoPartyReadiness(user_id=user_id, side=side.value, proposal_version_id=proposal_version_id,
                              amendment_id=amendment_id, session_ref=session_ref, features=sorted(features),
                              status="active", expires_at=expires_at)
    if acknowledged is not None:  # unset stays SQL NULL (a JSON null would not be "no acknowledgement")
        row.acknowledged = dict(acknowledged)
    session.add(row)
    session.flush()
    return row


def _readiness_valid(session: Session, row: PromoPartyReadiness | None, now: datetime) -> bool:
    return row is not None and _evidence_valid(session, user_id=row.user_id, session_ref=row.session_ref,
                                               features=row.features, expires_at=row.expires_at, now=now)


def _consent_valid(session: Session, row: PromoConsent, now: datetime) -> bool:
    return _evidence_valid(session, user_id=row.client_user_id, session_ref=row.session_ref,
                           features=row.client_features, expires_at=row.expires_at, now=now)


def note_version_readiness(session: Session, *, thread, actor_user_id: int,  # noqa: ANN001 - ProposalThread
                           features: frozenset[str] | None, session_ref: str | None,
                           now: datetime | None = None) -> None:
    """After an offer or counter: the author's readiness for *this* version (Q126). Only a capable client records
    one - nothing is claimed for an app that did not declare the capability."""
    from app.modules.marketplace import service as marketplace_service

    if not _capable(features):
        return
    version = marketplace_service.current_version(session, thread)
    if version is None or version.author_user_id != actor_user_id:
        return
    side = ActorSide.CLIENT if actor_user_id == thread.client_user_id else ActorSide.DRIVER
    _record_readiness(session, user_id=actor_user_id, side=side, session_ref=session_ref, features=features,
                      expires_at=ensure_aware_utc(version.expires_at), proposal_version_id=version.id)


def version_confirmation_state(session: Session, *, version, viewer_user_id: int,  # noqa: ANN001
                               now: datetime | None = None) -> str | None:
    """For the author of an open version only: ``"valid"``, ``"stale"`` (a confirmation exists but can no longer be
    relied on - the app asks to confirm again) or ``None`` (nothing was confirmed; nothing to show)."""
    if version.author_user_id != viewer_user_id:
        return None
    now = _now(now)
    consent = session.execute(select(PromoConsent).where(PromoConsent.proposal_version_id == version.id,
                                                         PromoConsent.status == "active")).scalar_one_or_none()
    if consent is not None and consent.client_user_id == viewer_user_id:
        return "valid" if _consent_valid(session, consent, now) else "stale"
    row = _active_readiness(session, user_id=viewer_user_id, proposal_version_id=version.id)
    if row is None:
        return None
    return "valid" if _readiness_valid(session, row, now) else "stale"


# --- lots, campaigns and the policy they carry (Q123) -----------------------------------------------------------


def _version_policy(version: PromoCampaignVersion) -> PromoMarginPolicy:
    return PromoMarginPolicy(
        max_discount_share_bps=version.max_discount_share_bps,
        max_discount_per_booking_minor=version.max_discount_per_booking_minor,
        passenger_bonus_max_per_booking_minor=version.passenger_bonus_max_per_booking_minor,
        driver_credit_max_per_booking_minor=version.driver_credit_max_per_booking_minor,
        variable_cost_fixed_minor=version.variable_cost_fixed_minor,
        variable_cost_bps=version.variable_cost_bps,
        min_margin_minor=version.min_margin_minor,
    )


def _policy_of_lots(session: Session, lots: Sequence[PromoLot]) -> PromoMarginPolicy | None:
    """Lots of one campaign (possibly several of its versions): every version's limits at once."""
    versions = {}
    for lot in lots:
        obligation = session.get(PromoObligation, lot.obligation_id)
        version = session.get(PromoCampaignVersion, obligation.campaign_version_id)
        versions[version.id] = version
    return strictest_margin_policy(_version_policy(v) for v in versions.values())


@dataclass
class _Source:
    """The usable lots of one campaign for one instrument, in spending order (soonest expiry first)."""

    campaign_id: int
    lots: list[PromoLot]

    @property
    def available(self) -> int:
        return sum(promo_service._available(lot) for lot in self.lots)


def _sources(lots: Sequence[PromoLot]) -> list[_Source]:
    """Group lots by campaign; campaigns ordered by their soonest-expiring lot, then id (deterministic)."""
    by_campaign: dict[int, list[PromoLot]] = {}
    for lot in lots:
        by_campaign.setdefault(lot.campaign_id, []).append(lot)
    return sorted((_Source(campaign_id, rows) for campaign_id, rows in by_campaign.items()),
                  key=lambda src: (ensure_aware_utc(src.lots[0].expires_at, field="expires_at"), src.campaign_id))


def combination_basis(session: Session, campaign_a: int, campaign_b: int) -> str | None:
    """The approved cost basis of two campaigns on one booking, or ``None`` when the pair is not approved (Q123)."""
    low, high = campaign_pair(campaign_a, campaign_b)
    return session.execute(select(PromoCampaignCombination.cost_basis).where(
        PromoCampaignCombination.campaign_low_id == low, PromoCampaignCombination.campaign_high_id == high,
        PromoCampaignCombination.status == "active")).scalar_one_or_none()


@dataclass(frozen=True)
class _Pairing:
    policy: PromoMarginPolicy | None
    cost_basis: str | None


def _pairing(session: Session, p: _Source | None, h: _Source | None) -> _Pairing | None:
    """The policy of P from ``p`` and H from ``h``; ``None`` when the two campaigns may not meet (Q123)."""
    if p is None or h is None:
        src = p or h
        return _Pairing(None if src is None else _policy_of_lots(session, src.lots), None)
    if p.campaign_id == h.campaign_id:
        return _Pairing(_policy_of_lots(session, [*p.lots, *h.lots]), None)
    basis = combination_basis(session, p.campaign_id, h.campaign_id)
    if basis is None:
        return None
    try:
        policy = combined_margin_policy(_policy_of_lots(session, p.lots), _policy_of_lots(session, h.lots), basis)
    except ValueError:
        return None
    return _Pairing(policy, basis)


def _usable(lot: PromoLot, service_type: str, now: datetime) -> bool:
    return (
        lot.status == PromoRewardStatus.AVAILABLE.value
        and lot.service_type == service_type
        and ensure_aware_utc(lot.expires_at, field="expires_at") > now
        and (lot.available_from is None or ensure_aware_utc(lot.available_from, field="available_from") <= now)
        and promo_service._available(lot) > 0
    )


def _lock_usable_lots(session: Session, owners: Mapping[str, int | None], service_type: str,
                      now: datetime) -> dict[str, list[PromoLot]]:
    """Lock the candidate lots of each instrument (campaigns FOR SHARE, then lots id ASC) and keep the usable ones,
    in spending order: soonest expiry first."""
    candidates = {
        instrument: list(session.execute(
            select(PromoLot.id, PromoLot.campaign_id).where(
                PromoLot.owner_user_id == owner, PromoLot.instrument == instrument,
                PromoLot.service_type == service_type, PromoLot.status == PromoRewardStatus.AVAILABLE.value)
        ).all()) if owner is not None else []
        for instrument, owner in owners.items()
    }
    campaign_ids = sorted({row.campaign_id for rows in candidates.values() for row in rows})
    for campaign_id in campaign_ids:
        promo_service._lock_campaign(session, campaign_id, share=True)
    locked = {lot_id: promo_service._lock_lot(session, lot_id)
              for lot_id in sorted({row.id for rows in candidates.values() for row in rows})}
    return {
        instrument: sorted(
            (locked[row.id] for row in rows if _usable(locked[row.id], service_type, now)),
            key=lambda lot: (ensure_aware_utc(lot.expires_at, field="expires_at"), lot.id),
        )
        for instrument, rows in candidates.items()
    }


def _usable_lots_unlocked(session: Session, owner: int, instrument: str, service_type: str,
                          now: datetime) -> list[PromoLot]:
    rows = session.execute(select(PromoLot).where(
        PromoLot.owner_user_id == owner, PromoLot.instrument == instrument, PromoLot.service_type == service_type,
        PromoLot.status == PromoRewardStatus.AVAILABLE.value)).scalars().all()
    return sorted((lot for lot in rows if _usable(lot, service_type, now)),
                  key=lambda lot: (ensure_aware_utc(lot.expires_at, field="expires_at"), lot.id))


def _allocate(lots: Sequence[PromoLot], amount: int) -> list[tuple[int, int]]:
    """Split ``amount`` over ``lots`` in their order (soonest expiry first)."""
    plan: list[tuple[int, int]] = []
    left = amount
    for lot in lots:
        if left <= 0:
            break
        take = min(left, promo_service._available(lot))
        if take > 0:
            plan.append((lot.id, take))
            left -= take
    if left:  # pragma: no cover - the quote never exceeds the locked available amount
        raise _stale("passenger_bonus_changed")
    return plan


def _funding(src: _Source) -> FundingSource:
    return FundingSource(src.campaign_id, src.available,
                         (ensure_aware_utc(src.lots[0].expires_at, field="expires_at"), src.campaign_id))


def _best_p_source(session: Session, sources: Sequence[_Source], *, fare_minor: int, fee_bps: int,
                   requested: int | None = None) -> tuple[_Source, PromoQuote] | None:
    """Q123: the one campaign that funds P (``contracts.promo.choose_passenger_source`` - the same chooser the
    simulator uses)."""
    by_id = {src.campaign_id: src for src in sources}
    best = choose_passenger_source([_funding(src) for src in sources], fare_minor=fare_minor, fee_bps=fee_bps,
                                   policy_of=lambda f: _policy_of_lots(session, by_id[f.campaign_id].lots),
                                   requested_minor=requested)
    return None if best is None else (by_id[best[0].campaign_id], best[1])


def _with_best_h(session: Session, *, p_src: _Source | None, h_sources: Sequence[_Source], consent, subject: str,
                 now: datetime, fare_minor: int, fee_bps: int
                 ) -> tuple[_Source | None, _Pairing | None, PromoQuote | None, DriverCreditOutcome]:
    """Q123: Driver Credit from the one campaign giving the most H without changing the consented P
    (``contracts.promo.choose_driver_source``): partial H when only part of it fits, none when the pair is not
    approved or would lower P."""
    by_id = {src.campaign_id: src for src in h_sources}
    pairings: dict[int, _Pairing | None] = {}

    def pairing(_p: FundingSource | None, h: FundingSource):  # noqa: ANN202
        paired = pairings.setdefault(h.campaign_id, _pairing(session, p_src, by_id[h.campaign_id]))
        return None if paired is None else (paired.policy, paired.cost_basis)

    h_fund, _basis, quote, outcome = choose_driver_source(
        p_source=None if p_src is None else _funding(p_src), h_sources=[_funding(src) for src in h_sources],
        pairing=pairing, consent=consent, subject=subject, now=now, fare_minor=fare_minor, fee_bps=fee_bps)
    if h_fund is None:
        return None, None, None, outcome
    return by_id[h_fund.campaign_id], pairings[h_fund.campaign_id], quote, outcome


# --- consent (Q104, Q123, Q126) ----------------------------------------------------------------------------------


def _active_consent(session: Session, *, proposal_version_id: int | None = None,
                    amendment_id: int | None = None) -> PromoConsent | None:
    query = select(PromoConsent).where(PromoConsent.status == "active")
    query = (query.where(PromoConsent.proposal_version_id == proposal_version_id) if proposal_version_id is not None
             else query.where(PromoConsent.amendment_id == amendment_id))
    return session.execute(query.with_for_update(key_share=True).execution_options(populate_existing=True)
                           ).scalar_one_or_none()


def _consent_contract(row: PromoConsent, subject: str) -> PassengerBonusConsent:
    return PassengerBonusConsent(proposal_version_id=subject, fare_minor=row.fare_minor,
                                 passenger_bonus_minor=row.passenger_bonus_minor, cash_due_minor=row.cash_due_minor,
                                 quote_fingerprint=row.quote_fingerprint, expires_at=ensure_aware_utc(row.expires_at))


def _new_consent_row(session: Session, *, client_user_id: int, quote: PromoQuote, service_type: str,
                     features: Iterable[str], expires_at: datetime, session_ref: str | None,
                     passenger_campaign_id: int | None, proposal_version_id: int | None = None,
                     amendment_id: int | None = None, booking_id: int | None = None) -> PromoConsent:
    previous = _active_consent(session, proposal_version_id=proposal_version_id, amendment_id=amendment_id)
    if previous is not None:
        previous.status = "superseded"
        session.flush()
    row = PromoConsent(
        public_id=uuid.uuid4(), client_user_id=client_user_id, proposal_version_id=proposal_version_id,
        amendment_id=amendment_id, booking_id=booking_id, service_type=service_type,
        contract_version=quote.contract_version, fare_minor=quote.fare_minor,
        passenger_bonus_minor=quote.passenger_bonus_minor, cash_due_minor=quote.cash_due_minor,
        quote_fingerprint=quote.fingerprint, client_features=sorted(features), status="active",
        expires_at=expires_at, session_ref=session_ref, passenger_campaign_id=passenger_campaign_id,
    )
    session.add(row)
    session.flush()
    return row


def _check_consent_input(consent: ConsentInput, quote: PromoQuote) -> None:
    """The client must have been shown exactly the server's numbers."""
    if (consent.passenger_bonus_minor, consent.cash_due_minor) != (quote.passenger_bonus_minor, quote.cash_due_minor):
        raise _stale("passenger_bonus_changed", passenger_discount_minor=quote.passenger_bonus_minor,
                     cash_due_minor=quote.cash_due_minor)


def record_consent(session: Session, *, client_user_id: int, proposal_version_id: int, service_type: str,
                   parcel_payer: str | None, fare_minor: int, fee_bps: int, expires_at: datetime,
                   client_features: frozenset[str], consent: ConsentInput, flags: Mapping[str, bool],
                   session_ref: str | None = None, driver_user_id: int | None = None,
                   now: datetime | None = None) -> PromoConsent:
    """The client consents to spend passenger bonus on one proposal version (when submitting / countering).

    Recomputed on the server; the client's numbers must match exactly. The consent names the one campaign that funds
    P (Q123) and the login session that gave it (Q126). The accept later re-quotes under locks and applies exactly
    this P or refuses (Q104). One active consent per version; a new one supersedes the old.
    """
    now = _now(now)
    if not flags.get(FeatureFlagKey.PROMOTIONS_ENABLED.value, False):
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"flag": FeatureFlagKey.PROMOTIONS_ENABLED.value})
    if not _capable(client_features):
        raise DomainError(ErrorCode.CLIENT_UPGRADE_REQUIRED, details={"feature": PROMO_CASH_FEATURE})
    if not passenger_bonus_allowed(service_type=service_type, bonus_owner_user_id=client_user_id,
                                   client_user_id=client_user_id, parcel_payer=parcel_payer):
        raise _stale("ineligible")
    lots = _lock_usable_lots(session, {P: client_user_id}, service_type, now)
    best = _best_p_source(session, _sources(lots[P]), fare_minor=fare_minor, fee_bps=fee_bps)
    if best is None:
        raise _stale("passenger_bonus_changed", passenger_discount_minor=0, cash_due_minor=fare_minor)
    source, quote = best
    _check_consent_input(consent, quote)
    return _new_consent_row(session, client_user_id=client_user_id, quote=quote, service_type=service_type,
                            features=client_features, expires_at=expires_at, session_ref=session_ref,
                            passenger_campaign_id=source.campaign_id, proposal_version_id=proposal_version_id)


# --- accept ---------------------------------------------------------------------------------------------------------


@dataclass
class AcceptPlan:
    quote: PromoQuote
    consent: PromoConsent | None = None
    allocations: list[tuple[int, int]] = field(default_factory=list)  # (lot_id, amount) for P and H
    passenger_campaign_id: int | None = None
    driver_campaign_id: int | None = None
    cost_basis: str | None = None
    h_outcome: DriverCreditOutcome = DriverCreditOutcome.NONE

    @property
    def applied(self) -> bool:
        return self.quote.promo_applied


def prepare_accept(
    session: Session,
    *,
    flags: Mapping[str, bool],
    service_type: str,
    parcel_payer: str | None,
    fare_minor: int,
    fee_bps: int,
    proposal_version_id: int,
    version_expires_at: datetime,
    client_user_id: int,
    driver_user_id: int,
    actor_side: ActorSide,
    actor_features: frozenset[str] | None,
    consent_input: ConsentInput | None,
    actor_session_ref: str | None = None,
    driver_ack: DriverAck | None = None,
    now: datetime | None = None,
) -> AcceptPlan:
    """Decide the booking's promo terms under locks (see module docstring). Call after locking the driver wallet."""
    now = _now(now)
    if consent_input is not None and actor_side is not ActorSide.CLIENT:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "promo_consent", "reason": "client_only"})
    if driver_ack is not None and actor_side is not ActorSide.DRIVER:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "promo_driver_ack", "reason": "driver_only"})
    stored = _active_consent(session, proposal_version_id=proposal_version_id)
    if stored is not None and stored.client_user_id != client_user_id:  # pragma: no cover - recorded per thread client
        raise _stale("consent_of_another_user")
    wants_p = consent_input is not None or stored is not None
    if not flags.get(FeatureFlagKey.PROMOTIONS_ENABLED.value, False):
        if wants_p:
            raise _stale("promotions_disabled")
        plain = plain_quote(fare_minor=fare_minor, fee_bps=fee_bps)
        _check_driver_ack(driver_ack, plain)
        return AcceptPlan(quote=plain)

    # Q126: the acting party answers for its own app now; the passive party's confirmation must still hold
    if actor_side is ActorSide.DRIVER:
        driver_ok = _capable(actor_features)
    else:
        driver_ok = _readiness_valid(session, _active_readiness(
            session, user_id=driver_user_id, proposal_version_id=proposal_version_id), now)
    if wants_p:
        if consent_input is not None and not _capable(actor_features):
            raise DomainError(ErrorCode.CLIENT_UPGRADE_REQUIRED, details={"feature": PROMO_CASH_FEATURE})
        if consent_input is None and not _consent_valid(session, stored, now):
            raise _stale("counterparty_confirmation_stale")  # the client must confirm the bonus again
        if not driver_ok:
            raise _stale("counterparty_client_outdated")  # the driver's app could not be shown the cash to collect
        if not passenger_bonus_allowed(service_type=service_type, bonus_owner_user_id=client_user_id,
                                       client_user_id=client_user_id, parcel_payer=parcel_payer):
            raise _stale("ineligible")

    owners = {P: client_user_id if wants_p else None, H: driver_user_id if driver_ok else None}
    lots = _lock_usable_lots(session, owners, service_type, now)
    p_sources, h_sources = _sources(lots[P]), _sources(lots[H])
    subject = str(proposal_version_id)

    p_src: _Source | None = None
    consent: PassengerBonusConsent | None = None
    if consent_input is not None:
        if consent_input.passenger_bonus_minor <= 0 or consent_input.cash_due_minor != fare_minor - consent_input.passenger_bonus_minor:
            raise _stale("fare")  # the client consented to other numbers than this version's fare
        best = _best_p_source(session, p_sources, fare_minor=fare_minor, fee_bps=fee_bps)
        p_src = None if best is None else best[0]
        consent = PassengerBonusConsent(
            proposal_version_id=subject, fare_minor=fare_minor,
            passenger_bonus_minor=consent_input.passenger_bonus_minor, cash_due_minor=consent_input.cash_due_minor,
            quote_fingerprint="", expires_at=ensure_aware_utc(version_expires_at),
        )
    elif stored is not None:
        consent = _consent_contract(stored, subject)
        chosen = stored.passenger_campaign_id
        if chosen is None:  # a consent recorded before 0089: the same deterministic choice as then
            best = _best_p_source(session, p_sources, fare_minor=fare_minor, fee_bps=fee_bps,
                                  requested=stored.passenger_bonus_minor)
            p_src = None if best is None else best[0]
        else:
            p_src = next((src for src in p_sources if src.campaign_id == chosen), None)

    h_src, pairing, h_quote, h_outcome = _with_best_h(session, p_src=p_src, h_sources=h_sources, consent=consent,
                                                      subject=subject, now=now, fare_minor=fare_minor, fee_bps=fee_bps)
    if h_quote is not None:
        quote = h_quote
    else:
        h_src, pairing = None, _pairing(session, p_src, None)
        try:
            quote = quote_at_accept(
                consent=consent, proposal_version_id=subject, now=now, fare_minor=fare_minor, fee_bps=fee_bps,
                policy=pairing.policy, passenger_bonus_available_minor=0 if p_src is None else p_src.available,
                driver_credit_available_minor=0)
        except DomainError as exc:
            if exc.code is not ErrorCode.PROMO_PARAMETERS_UNSET:
                raise
            if wants_p:
                raise _stale("parameters_unset") from exc
            quote = plain_quote(fare_minor=fare_minor, fee_bps=fee_bps)
    if consent_input is not None:
        _check_consent_input(consent_input, quote)
    # Q123 (clarified): the accepting driver confirms the numbers it was shown; a different result - H gone or
    # smaller, so C_net higher - is never applied behind its back: it sees the new numbers and confirms again
    _check_driver_ack(driver_ack, quote)
    row = stored
    if consent_input is not None:
        row = _new_consent_row(session, client_user_id=client_user_id, quote=quote, service_type=service_type,
                               features=actor_features or (), expires_at=ensure_aware_utc(version_expires_at),
                               session_ref=actor_session_ref,
                               passenger_campaign_id=None if p_src is None else p_src.campaign_id,
                               proposal_version_id=proposal_version_id)
    p_amount, h_amount = quote.passenger_bonus_minor, quote.driver_credit_minor
    allocations = (_allocate(p_src.lots, p_amount) if p_amount else []) + (
        _allocate(h_src.lots, h_amount) if h_amount else [])
    return AcceptPlan(
        quote=quote, consent=row if p_amount > 0 else None, allocations=allocations,
        passenger_campaign_id=p_src.campaign_id if p_amount else None,
        driver_campaign_id=h_src.campaign_id if h_amount else None,
        cost_basis=pairing.cost_basis if p_amount and h_amount else None, h_outcome=h_outcome,
    )


def _check_driver_ack(ack: DriverAck | None, quote: PromoQuote) -> None:
    """The driver's own numbers must be exactly the server's; otherwise this attempt is refused with the new ones."""
    if ack is None:
        return
    numbers = _driver_numbers(quote)
    if (ack.cash_to_collect_minor, ack.commission_charged_minor) != (numbers["cash_to_collect_minor"],
                                                                      numbers["commission_charged_minor"]):
        raise _stale("driver_terms_changed", **numbers, driver_credit_minor=quote.driver_credit_minor)


def _insert_terms(session: Session, *, booking_id: int, seq: int, quote: PromoQuote, consent: PromoConsent | None,
                  amendment_id: int | None, currency: str, passenger_campaign_id: int | None,
                  driver_campaign_id: int | None, cost_basis: str | None) -> PromoBookingTerms:
    terms = PromoBookingTerms(
        booking_id=booking_id, seq=seq, amendment_id=amendment_id, consent_id=None if consent is None else consent.id,
        contract_version=quote.contract_version, currency=currency, fare_minor=quote.fare_minor,
        fee_bps=quote.fee_bps, base_commission_minor=quote.base_commission_minor,
        passenger_bonus_minor=quote.passenger_bonus_minor, driver_credit_minor=quote.driver_credit_minor,
        cash_due_minor=quote.cash_due_minor, net_commission_minor=quote.net_commission_minor,
        variable_cost_minor=quote.variable_cost_minor, min_margin_minor=quote.min_margin_minor,
        quote_fingerprint=quote.fingerprint, passenger_campaign_id=passenger_campaign_id,
        driver_campaign_id=driver_campaign_id, combination_cost_basis=cost_basis,
    )
    session.add(terms)
    session.flush()
    return terms


def _use_consent(session: Session, consent: PromoConsent | None, booking_id: int, now: datetime) -> None:
    if consent is None:
        return
    consent.status, consent.booking_id, consent.used_at = "used", booking_id, now
    session.flush()


def commit_accept(session: Session, plan: AcceptPlan, *, booking_id: int, currency: str,
                  now: datetime | None = None) -> None:
    """Reservations + terms + consent used, for the booking just inserted. No-op for a plain booking."""
    now = _now(now)
    if not plan.applied:
        return
    for lot_id, amount in sorted(plan.allocations):
        promo_service.reserve_lot(session, lot_id=lot_id, booking_id=booking_id, amount_minor=amount, terms_seq=1,
                                  now=now)
    _insert_terms(session, booking_id=booking_id, seq=1, quote=plan.quote, consent=plan.consent, amendment_id=None,
                  currency=currency, passenger_campaign_id=plan.passenger_campaign_id,
                  driver_campaign_id=plan.driver_campaign_id, cost_basis=plan.cost_basis)
    _use_consent(session, plan.consent, booking_id, now)


# --- preview before agreeing (no locks, no reservation) ------------------------------------------------------------


def preview_version_quote(session: Session, *, flags: Mapping[str, bool], viewer_side: ActorSide | None,
                          service_type: str, parcel_payer: str | None, fare_minor: int, fee_bps: int,
                          proposal_version_id: int, client_user_id: int, driver_user_id: int,
                          now: datetime | None = None) -> dict | None:
    """What a proposal version would cost with the discounts available *now* - shown before agreeing, reserves
    nothing (ADR-0023 §18). Client: the most its bonus gives on this fare from one campaign (what it can consent
    to). Driver: the cash to collect and the commission charged with the client's recorded consent and the driver's
    own credit, combined only as Q123 allows. ``None`` when no discount would apply. The accept re-quotes under
    locks and may still refuse (stale)."""
    now = _now(now)
    if not flags.get(FeatureFlagKey.PROMOTIONS_ENABLED.value, False) or viewer_side not in (ActorSide.CLIENT,
                                                                                           ActorSide.DRIVER):
        return None
    if viewer_side is ActorSide.CLIENT:
        if not passenger_bonus_allowed(service_type=service_type, bonus_owner_user_id=client_user_id,
                                       client_user_id=client_user_id, parcel_payer=parcel_payer):
            return None
        best = _best_p_source(session, _sources(_usable_lots_unlocked(session, client_user_id, P, service_type, now)),
                              fare_minor=fare_minor, fee_bps=fee_bps)
        return None if best is None else client_view(best[1])
    consent = session.execute(select(PromoConsent).where(
        PromoConsent.proposal_version_id == proposal_version_id, PromoConsent.status == "active")).scalar_one_or_none()
    p_src = None
    contract = None
    if consent is not None:
        p_sources = _sources(_usable_lots_unlocked(session, client_user_id, P, service_type, now))
        p_src = next((src for src in p_sources if src.campaign_id == consent.passenger_campaign_id), None)
        contract = _consent_contract(consent, str(proposal_version_id))
    h_sources = _sources(_usable_lots_unlocked(session, driver_user_id, H, service_type, now))
    _h_src, _pairing_used, h_quote, _outcome = _with_best_h(
        session, p_src=p_src, h_sources=h_sources, consent=contract, subject=str(proposal_version_id), now=now,
        fare_minor=fare_minor, fee_bps=fee_bps)
    if h_quote is not None:
        quote = h_quote
    elif p_src is not None:
        try:
            quote = quote_at_accept(consent=contract, proposal_version_id=str(proposal_version_id), now=now,
                                    fare_minor=fare_minor, fee_bps=fee_bps, policy=_pairing(session, p_src, None).policy,
                                    passenger_bonus_available_minor=p_src.available, driver_credit_available_minor=0)
        except DomainError as exc:
            if exc.code in (ErrorCode.PROMO_QUOTE_STALE, ErrorCode.PROMO_PARAMETERS_UNSET):
                return None
            raise
    else:
        return None
    return driver_view(quote) if quote.promo_applied else None


def _payer_of(session: Session, listing) -> str | None:  # noqa: ANN001 - marketplace Listing
    from app.modules.marketplace import service as marketplace_service

    if listing.service_type != ServiceType.PARCEL.value:
        return None
    details = marketplace_service.get_parcel_details(session, listing.id) if listing.kind == "request" else None
    return details.payer if details is not None and details.payer else "sender"


def preview_for_listing(session: Session, *, listing_public_id: str, client_user_id: int, unit_price_minor: int,
                        quantity: int, client_features: frozenset[str] | None = None,
                        now: datetime | None = None) -> tuple[dict | None, str | None]:
    """Referral stage 5: what the caller's own bonus would do to a price it is about to offer or counter on a listing,
    and - when nothing - why, in plain categories (:func:`no_discount_reason`).

    Only the would-be *client* of the listing asks (the owner of a request; anyone but the owner of a trip offer);
    anyone else gets 404. Reserves nothing. The fee comes from the same port a real proposal freezes (AC43)."""
    from app.contracts.money import total_minor
    from app.modules.geo import service as geo_service
    from app.modules.marketplace import service as marketplace_service

    now = _now(now)
    listing = marketplace_service.get_listing_by_public_id(session, listing_public_id)
    is_request = listing.kind == "request"
    if (listing.owner_user_id == client_user_id) != is_request or listing.status != "published":
        raise DomainError(ErrorCode.NOT_FOUND)
    fare = total_minor(unit_price_minor, quantity) if listing.price_basis == "per_seat" else unit_price_minor
    fee = marketplace_service.quote_fee_for_listing(session, listing, fare, now)
    flags = geo_service.snapshot_flags(session, corridor_id=listing.corridor_id)
    payer = _payer_of(session, listing)
    view = preview_version_quote(
        session, flags=flags, viewer_side=ActorSide.CLIENT, service_type=listing.service_type, parcel_payer=payer,
        fare_minor=fare, fee_bps=fee.fee_bps, proposal_version_id=0, client_user_id=client_user_id,
        driver_user_id=0, now=now)
    if view is not None:
        return view, None
    return None, no_discount_reason(session, flags=flags, user_id=client_user_id, instrument=P,
                                    service_type=listing.service_type, parcel_payer=payer,
                                    client_features=client_features, now=now)


def record_consent_for_current_version(session: Session, *, thread, actor_user_id: int,  # noqa: ANN001
                                       client_features: frozenset[str], consent: ConsentInput,
                                       session_ref: str | None = None, now: datetime | None = None) -> PromoConsent:
    """The client consents on the version it has just sent (submit or counter), in that command's transaction."""
    from app.modules.geo import service as geo_service
    from app.modules.marketplace import service as marketplace_service

    if actor_user_id != thread.client_user_id:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "promo_consent", "reason": "client_only"})
    version = marketplace_service.current_version(session, thread)
    if version is None or version.author_user_id != actor_user_id:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "promo_consent", "reason": "own_version_only"})
    listing = marketplace_service.get_listing(session, thread.listing_id)
    return record_consent(
        session, client_user_id=actor_user_id, proposal_version_id=version.id, service_type=listing.service_type,
        parcel_payer=_payer_of(session, listing), fare_minor=version.total_minor, fee_bps=version.fee_bps,
        expires_at=ensure_aware_utc(version.expires_at), client_features=client_features, consent=consent,
        flags=geo_service.snapshot_flags(session, corridor_id=listing.corridor_id), session_ref=session_ref, now=now)


def confirm_current_version(session: Session, *, thread, actor_user_id: int, proposal_version_id: int,  # noqa: ANN001
                            client_features: frozenset[str], session_ref: str | None,
                            consent: ConsentInput | None, now: datetime | None = None) -> None:
    """Q126: the author of the open version confirms again from its current session (a stale confirmation). The
    client re-consents to the exact numbers; the driver re-declares its app. Nothing else about the offer changes."""
    from app.modules.marketplace import service as marketplace_service

    now = _now(now)
    version = marketplace_service.current_version(session, thread)
    if version is None or version.id != proposal_version_id or version.author_user_id != actor_user_id \
            or version.status != "active" or now >= ensure_aware_utc(version.expires_at):
        raise DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "not_your_open_version"})
    if not _capable(client_features):
        raise DomainError(ErrorCode.CLIENT_UPGRADE_REQUIRED, details={"feature": PROMO_CASH_FEATURE})
    if actor_user_id == thread.client_user_id:
        if consent is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "promo_consent", "reason": "required"})
        record_consent_for_current_version(session, thread=thread, actor_user_id=actor_user_id,
                                           client_features=client_features, consent=consent,
                                           session_ref=session_ref, now=now)
    elif consent is not None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "promo_consent", "reason": "client_only"})
    note_version_readiness(session, thread=thread, actor_user_id=actor_user_id, features=client_features,
                           session_ref=session_ref, now=now)


# --- why no discount (stage 5) ------------------------------------------------------------------------------------

NO_DISCOUNT_REASONS = ("service_not_eligible", "bonus_expired", "bonus_reserved", "bonus_on_hold", "no_campaign",
                       "client_update_required", "trip_terms")


def no_discount_reason(session: Session, *, flags: Mapping[str, bool], user_id: int, instrument: str,
                       service_type: str, parcel_payer: str | None, client_features: frozenset[str] | None,
                       now: datetime | None = None) -> str:
    """A plain category for "why is there no discount here" (stage 5). Never a formula, a limit, a rate or a risk
    signal: ``trip_terms`` stands for every commission/margin/cap reason at once (Q103)."""
    now = _now(now)
    if not flags.get(FeatureFlagKey.PROMOTIONS_ENABLED.value, False):
        return "no_campaign"
    if client_features is not None and not _capable(client_features):
        return "client_update_required"
    lots = session.execute(select(PromoLot).where(PromoLot.owner_user_id == user_id,
                                                  PromoLot.instrument == instrument)).scalars().all()
    if not lots:
        return "no_campaign"
    if instrument == P and not passenger_bonus_allowed(service_type=service_type, bonus_owner_user_id=user_id,
                                                       client_user_id=user_id, parcel_payer=parcel_payer):
        return "service_not_eligible"
    same_service = [lot for lot in lots if lot.service_type == service_type]
    if not same_service:
        return "service_not_eligible"
    if any(_usable(lot, service_type, now) for lot in same_service):
        return "trip_terms"
    if any(lot.status == PromoRewardStatus.PENDING_REVIEW.value for lot in same_service):
        return "bonus_on_hold"
    if any(lot.reserved_minor > 0 and lot.status == PromoRewardStatus.AVAILABLE.value for lot in same_service):
        return "bonus_reserved"
    if any(lot.status == PromoRewardStatus.EXPIRED.value or ensure_aware_utc(lot.expires_at) <= now
           for lot in same_service):
        return "bonus_expired"
    return "no_campaign"


# --- reading a booking's terms -----------------------------------------------------------------------------------


def _latest_terms(session: Session, booking_id: int) -> PromoBookingTerms | None:
    return session.execute(select(PromoBookingTerms).where(PromoBookingTerms.booking_id == booking_id)
                           .order_by(PromoBookingTerms.seq.desc()).limit(1)).scalar_one_or_none()


def _state(booking) -> PromoSnapshotState:  # noqa: ANN001 - bookings.models.Booking
    try:
        return promo_snapshot_state(booking.terms_snapshot)
    except ValueError as exc:
        raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"reason": "promo_snapshot_malformed"}) from exc


def booking_has_promo(booking) -> bool:  # noqa: ANN001
    return _state(booking) is PromoSnapshotState.APPLIED


def _client_ever_discounted(session: Session, booking) -> bool:  # noqa: ANN001
    """Q124: the client's amounts differ from a plain booking only if some agreement of it had P > 0."""
    return booking_has_promo(booking) and session.execute(select(PromoBookingTerms.id).where(
        PromoBookingTerms.booking_id == booking.id, PromoBookingTerms.passenger_bonus_minor > 0).limit(1)
    ).first() is not None


def cash_terms_differ_for(session: Session, booking, side: ActorSide) -> bool:  # noqa: ANN001
    """Does this party's app need to render promo cash terms for the booking (Q110, Q124)? The driver: on any promo
    booking (H and C_net). The client: only when a passenger bonus is or was part of it - a driver-credit-only booking
    looks exactly like a plain one to the client."""
    if side is ActorSide.DRIVER:
        return booking_has_promo(booking)
    if side is ActorSide.CLIENT:
        return _client_ever_discounted(session, booking)
    return False


def terms_for_booking(session: Session, booking) -> PromoQuote:  # noqa: ANN001
    """The booking's money terms. Legacy and plain bookings: P = H = 0. A promo booking with missing or broken
    terms is an error - the legacy fallback never hides it."""
    if _state(booking) is not PromoSnapshotState.APPLIED:
        return plain_quote(fare_minor=booking.total_minor, fee_bps=booking.fee_bps)
    row = _latest_terms(session, booking.id)
    if row is None or (row.fare_minor, row.fee_bps, row.base_commission_minor) != (
            booking.total_minor, booking.fee_bps, booking.commission_minor):
        raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"reason": "promo_terms_missing_or_stale"})
    return _quote_of_row(row)


def _quote_of_row(row: PromoBookingTerms) -> PromoQuote:
    try:
        return quote_from_terms(
            fare_minor=row.fare_minor, fee_bps=row.fee_bps, base_commission_minor=row.base_commission_minor,
            passenger_bonus_minor=row.passenger_bonus_minor, driver_credit_minor=row.driver_credit_minor,
            cash_due_minor=row.cash_due_minor, net_commission_minor=row.net_commission_minor,
            variable_cost_minor=row.variable_cost_minor, min_margin_minor=row.min_margin_minor,
            contract_version=row.contract_version,
        )
    except ValueError as exc:
        raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"reason": "promo_terms_invalid"}) from exc


def client_promo_view(session: Session, booking) -> dict | None:  # noqa: ANN001
    """Q103: fare, discount, cash due - nothing about the commission. ``None`` for a booking without a passenger
    discount (Q124: a driver-credit-only booking shows the client exactly what a plain one does)."""
    if not _client_ever_discounted(session, booking):
        return None
    return client_view(terms_for_booking(session, booking), booking.currency)


def driver_promo_view(session: Session, booking) -> dict | None:  # noqa: ANN001
    if not booking_has_promo(booking):
        return None
    return driver_view(terms_for_booking(session, booking), booking.currency)


# --- settlement: capture / release -----------------------------------------------------------------------------


def _reserved(session: Session, booking_id: int) -> list[int]:
    return list(session.execute(
        select(PromoRedemption.id).where(PromoRedemption.booking_id == booking_id,
                                         PromoRedemption.status == PromoRedemptionStatus.RESERVED.value)
        .order_by(PromoRedemption.lot_id, PromoRedemption.id)).scalars())


def consume_reservations(session: Session, *, booking_id: int, now: datetime | None = None) -> int:
    """With the booking's C_net capture, once: reserved -> consumed. Call after locking the wallet account and
    before the hold (lock order). A repeat finds nothing reserved and posts nothing."""
    ids = _reserved(session, booking_id)
    for redemption_id in ids:
        promo_service.consume_redemption(session, redemption_id=redemption_id, now=now)
    return len(ids)


def release_reservations(session: Session, *, booking_id: int, fault: PromoFault, reason: str | None = None,
                         now: datetime | None = None) -> int:
    """With the booking's hold release (cancel, confirmed no-show, finance release): the value returns to each holder
    under the fair-restoration rules, judged per holder (Q129). Nothing consumed is touched. Idempotent.

    ``undetermined`` never costs a holder the grace extension; when it actually gave one, a ``cancel_fault`` review
    per holder asks a person to decide the cause (an admin's rejection can withdraw only the unspent extension)."""
    now = _now(now)
    ids = _reserved(session, booking_id)
    for redemption_id in ids:
        promo_service.release_redemption(session, redemption_id=redemption_id, fault=fault, now=now)
    if fault is PromoFault.UNDETERMINED and ids:
        _open_cancel_fault_reviews(session, booking_id, ids, reason, now)
    return len(ids)


def _open_cancel_fault_reviews(session: Session, booking_id: int, redemption_ids: Sequence[int], reason: str | None,
                               now: datetime) -> None:
    from app.modules.promotions.qualification import _review_sla, open_review

    extended: dict[str, list[tuple[int, int]]] = {}
    for redemption_id in redemption_ids:
        redemption = session.get(PromoRedemption, redemption_id)
        if redemption.restored_until is None:
            continue  # no extension was given: the cause changes nothing, nobody needs to decide it
        lot = session.get(PromoLot, redemption.lot_id)
        extended.setdefault(lot.instrument, []).append((redemption.id, lot.campaign_id))
    for instrument, items in sorted(extended.items()):
        campaign_id = items[0][1]
        open_review(session, kind="cancel_fault", dedup_key=f"cancel_fault:{booking_id}:{instrument}",
                    reasons=["fault_undetermined", f"holder_{'client' if instrument == P else 'driver'}"],
                    evidence=[{"table": "bookings", "id": booking_id},
                              *({"table": "promo_redemptions", "id": rid} for rid, _ in items)],
                    now=now, sla=_review_sla(session, campaign_id), booking_id=booking_id, campaign_id=campaign_id)


def fault_for_side(side: ActorSide | str | None) -> PromoFault:
    """The cause when only the acting party is known (amendment author). Q129: an operator or the system acting is
    not a cause by itself - it is ``undetermined``, never "the platform's fault" by default."""
    value = ActorSide(side) if side is not None else ActorSide.SYSTEM
    if value is ActorSide.CLIENT:
        return PromoFault.CLIENT
    if value is ActorSide.DRIVER:
        return PromoFault.DRIVER
    return PromoFault.UNDETERMINED


def fault_for_cancel(fault_side: FaultSide | str, *, decided: bool) -> PromoFault:
    """Q129: the promo cause of a cancel from the booking's recorded fault. ``none`` is a *decided* "nobody" only when
    a person recorded it; the default ``none`` of an operator/system cancel without a decision is ``undetermined``."""
    value = FaultSide(fault_side)
    if value is FaultSide.CLIENT:
        return PromoFault.CLIENT
    if value is FaultSide.DRIVER:
        return PromoFault.DRIVER
    if value is FaultSide.PLATFORM:
        return PromoFault.PLATFORM
    return PromoFault.NONE if decided else PromoFault.UNDETERMINED


# --- cases the approved policy does not cover (Q127) ----------------------------------------------------------------


def _consumed_holders(session: Session, booking_id: int) -> list[tuple[str, int]]:
    rows = session.execute(
        select(PromoLot.instrument, PromoLot.campaign_id).join(PromoRedemption, PromoRedemption.lot_id == PromoLot.id)
        .where(PromoRedemption.booking_id == booking_id,
               PromoRedemption.status == PromoRedemptionStatus.CONSUMED.value)).all()
    return sorted({(row.instrument, row.campaign_id) for row in rows})


def _note_uncovered(session: Session, booking_id: int, cause: str, now: datetime) -> None:
    """Q127: spent bonus/credit on a booking later reversed or decided in a dispute - the approved policy has no rule
    to give it back, so it is **shown** to a person (a review), never silently settled against the holder and never
    restored by a generic grant. The review decision records a judgement; it moves no value by itself."""
    from app.modules.promotions.qualification import _review_sla, open_review

    for instrument, campaign_id in _consumed_holders(session, booking_id):
        open_review(session, kind="restoration_uncovered",
                    dedup_key=f"restoration_uncovered:{booking_id}:{instrument}:{cause}",
                    reasons=[cause, f"holder_{'client' if instrument == P else 'driver'}"],
                    evidence=[{"table": "bookings", "id": booking_id}],
                    now=now, sla=_review_sla(session, campaign_id), booking_id=booking_id, campaign_id=campaign_id)


def after_commission_reversal(session: Session, *, booking_id: int, now: datetime | None = None) -> None:
    """A commission reversal is its own operation (Q127): it restores no bonus and is no cash refund. It re-checks a
    granted referral (post-grant intake) and shows spent promo value on the booking to a person."""
    from app.modules.promotions.qualification import record_booking_event

    now = _now(now)
    live = session.execute(text(
        "SELECT 1 FROM promo_enrollments e JOIN bookings b ON b.id = :b WHERE e.referee_user_id IN "
        "(b.client_user_id, b.driver_user_id) LIMIT 1"), {"b": booking_id}).first()
    if live is not None:
        record_booking_event(session, booking_id=booking_id, kind="commission_reversed", occurred_at=now)
    _note_uncovered(session, booking_id, "commission_reversed", now)


def note_dispute_resolved(session: Session, *, booking_id: int, now: datetime | None = None) -> None:
    """A resolved dispute on a booking whose bonus/credit was already spent (Q127): shown to a person."""
    _note_uncovered(session, booking_id, "dispute_resolved", _now(now))


# --- amendments (Q116, Q125) ---------------------------------------------------------------------------------------


@dataclass
class AmendmentPlan:
    old: PromoQuote
    new: PromoQuote
    carries: list[tuple[int, int]]  # (redemption_id, new amount) - every live reservation of the booking
    consent: PromoConsent | None = None
    client_must_confirm: bool = False
    driver_must_confirm: bool = False
    passenger_campaign_id: int | None = None
    driver_campaign_id: int | None = None
    cost_basis: str | None = None


def _driver_numbers(quote: PromoQuote) -> dict[str, int]:
    return {"cash_to_collect_minor": quote.cash_due_minor, "commission_charged_minor": quote.net_commission_minor}


def prepare_amendment(
    session: Session,
    *,
    booking,  # noqa: ANN001 - bookings.models.Booking (locked by the caller)
    new_total_minor: int,
    actor_side: ActorSide,
    stage: str,  # "create" | "accept"
    consent_input: ConsentInput | None,
    actor_features: frozenset[str] | None,
    amendment_id: int | None,
    driver_ack: DriverAck | None = None,
    actor_session_ref: str | None = None,
    amendment_expires_at: datetime | None = None,
    now: datetime | None = None,
) -> AmendmentPlan | None:
    """The new money terms of a promo booking, deterministic between proposing and accepting the change.

    Q125: available amounts are exactly the booking's own reservations (no new lot) and the policy is the campaigns'
    immutable versions and the cost basis recorded at accept, so P and H can only stay or shrink. The party that
    acts confirms its own new numbers now (client: consent to F/P/F_cash when a bonus is involved; driver: the new
    cash to collect and commission charged); at accept the proposer's earlier confirmation must still hold (Q126).
    ``None`` for a booking without promo terms: an amendment never adds a discount.
    """
    now = _now(now)
    computed = _amendment_quote(session, booking, new_total_minor)
    if computed is None:
        return None
    old, new, p_rows, h_rows, terms = computed
    reconfirm = amendment_reconfirmation(old, new)
    client_must = reconfirm.client and (old.passenger_bonus_minor > 0 or new.passenger_bonus_minor > 0)  # Q124
    driver_must = reconfirm.driver
    expires_at = amendment_expires_at or (now + booking_amendment_ttl())
    consent_row = None

    if actor_side is ActorSide.CLIENT and client_must:
        if consent_input is None:
            raise DomainError(ErrorCode.PROMO_CONSENT_REQUIRED,
                              details={"passenger_discount_minor": new.passenger_bonus_minor,
                                       "cash_due_minor": new.cash_due_minor, "fare_minor": new.fare_minor})
        _check_consent_input(consent_input, new)
        if amendment_id is not None:
            if new.passenger_bonus_minor > 0:
                consent_row = _new_consent_row(
                    session, client_user_id=booking.client_user_id, quote=new, service_type=booking.service_type,
                    features=actor_features or (), expires_at=expires_at, session_ref=actor_session_ref,
                    passenger_campaign_id=terms.passenger_campaign_id, amendment_id=amendment_id,
                    booking_id=booking.id)
            if stage == "create":
                _record_readiness(session, user_id=booking.client_user_id, side=ActorSide.CLIENT,
                                  session_ref=actor_session_ref, features=actor_features or (),
                                  expires_at=expires_at, amendment_id=amendment_id,
                                  acknowledged={"fare_minor": new.fare_minor,
                                                "passenger_discount_minor": new.passenger_bonus_minor,
                                                "cash_due_minor": new.cash_due_minor})
    if actor_side is ActorSide.DRIVER and driver_must:
        numbers = _driver_numbers(new)
        if driver_ack is None:
            raise DomainError(ErrorCode.PROMO_CONSENT_REQUIRED,
                              details={**numbers, "driver_credit_minor": new.driver_credit_minor,
                                       "fare_minor": new.fare_minor, "party": "driver"})
        if {"cash_to_collect_minor": driver_ack.cash_to_collect_minor,
                "commission_charged_minor": driver_ack.commission_charged_minor} != numbers:
            raise _stale("driver_terms_changed", **numbers)
        if stage == "create" and amendment_id is not None:
            _record_readiness(session, user_id=booking.driver_user_id, side=ActorSide.DRIVER,
                              session_ref=actor_session_ref, features=actor_features or (), expires_at=expires_at,
                              amendment_id=amendment_id, acknowledged=numbers)

    if stage == "accept":
        # the proposer confirmed at create; that confirmation must still hold and still say these numbers (Q126)
        if actor_side is ActorSide.DRIVER and client_must:
            proof = _active_readiness(session, user_id=booking.client_user_id, amendment_id=amendment_id)
            if not _readiness_valid(session, proof, now) or proof.acknowledged.get("cash_due_minor") != new.cash_due_minor:
                raise _stale("counterparty_confirmation_stale")
            if new.passenger_bonus_minor > 0:
                consent_row = _active_consent(session, amendment_id=amendment_id)
                if consent_row is None or (consent_row.passenger_bonus_minor, consent_row.cash_due_minor) != (
                        new.passenger_bonus_minor, new.cash_due_minor):
                    raise _stale("passenger_bonus_changed")
        if actor_side is ActorSide.CLIENT and driver_must:
            proof = _active_readiness(session, user_id=booking.driver_user_id, amendment_id=amendment_id)
            if not _readiness_valid(session, proof, now) or dict(proof.acknowledged or {}) != _driver_numbers(new):
                raise _stale("counterparty_confirmation_stale")
    carries = _carry_plan(p_rows, new.passenger_bonus_minor) + _carry_plan(h_rows, new.driver_credit_minor)
    return AmendmentPlan(old=old, new=new, carries=carries, consent=consent_row, client_must_confirm=client_must,
                         driver_must_confirm=driver_must, passenger_campaign_id=terms.passenger_campaign_id,
                         driver_campaign_id=terms.driver_campaign_id, cost_basis=terms.combination_cost_basis)


def confirm_amendment(session: Session, *, booking, amendment, actor_side: ActorSide,  # noqa: ANN001
                      client_features: frozenset[str], session_ref: str | None, consent_input: ConsentInput | None,
                      driver_ack: DriverAck | None, now: datetime | None = None) -> None:
    """Q126: the proposer of an open amendment confirms its numbers again from its current session."""
    now = _now(now)
    if amendment.status != "proposed" or ActorSide(amendment.author_side) is not actor_side \
            or now >= ensure_aware_utc(amendment.expires_at):
        raise DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "not_your_open_amendment"})
    if not _capable(client_features):
        raise DomainError(ErrorCode.CLIENT_UPGRADE_REQUIRED, details={"feature": PROMO_CASH_FEATURE})
    prepare_amendment(session, booking=booking, new_total_minor=amendment.new_total_minor, actor_side=actor_side,
                      stage="create", consent_input=consent_input, actor_features=client_features,
                      amendment_id=amendment.id, driver_ack=driver_ack, actor_session_ref=session_ref,
                      amendment_expires_at=ensure_aware_utc(amendment.expires_at), now=now)


def _amendment_quote(session: Session, booking, new_total_minor: int):  # noqa: ANN001, ANN202
    """(old terms, new quote, P reservations, H reservations, latest terms row) of a promo booking, or ``None``.

    Deterministic: the available amounts are exactly the booking's own reservations, the policy comes from the
    campaigns' immutable versions and the cost basis recorded with the agreement - what is shown when a change is
    proposed is what its accept applies.
    """
    if not booking_has_promo(booking):
        return None
    old = terms_for_booking(session, booking)
    terms = _latest_terms(session, booking.id)
    rows = session.execute(
        select(PromoRedemption, PromoLot).join(PromoLot, PromoLot.id == PromoRedemption.lot_id)
        .where(PromoRedemption.booking_id == booking.id,
               PromoRedemption.status == PromoRedemptionStatus.RESERVED.value)
        .order_by(PromoLot.expires_at, PromoLot.id)
    ).all()
    by_instrument: dict[str, list[tuple[PromoRedemption, PromoLot]]] = {P: [], H: []}
    for redemption, lot in rows:
        by_instrument[lot.instrument].append((redemption, lot))
    p_rows, h_rows = by_instrument[P], by_instrument[H]
    if (sum(r.amount_minor for r, _ in p_rows), sum(r.amount_minor for r, _ in h_rows)) != (
            old.passenger_bonus_minor, old.driver_credit_minor):
        raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"reason": "promo_reservations_differ_from_terms"})
    p_lots, h_lots = [lot for _, lot in p_rows], [lot for _, lot in h_rows]
    p_campaigns, h_campaigns = {lot.campaign_id for lot in p_lots}, {lot.campaign_id for lot in h_lots}
    if len(p_campaigns | h_campaigns) <= 1 or terms.combination_cost_basis is None:
        policy = _policy_of_lots(session, p_lots + h_lots)  # one campaign (or pre-0089 terms): as at accept
    else:
        policy = combined_margin_policy(_policy_of_lots(session, p_lots), _policy_of_lots(session, h_lots),
                                        terms.combination_cost_basis)
    new = quote_promo(fare_minor=new_total_minor, fee_bps=booking.fee_bps, policy=policy,
                      passenger_bonus_requested_minor=old.passenger_bonus_minor,
                      passenger_bonus_available_minor=old.passenger_bonus_minor,
                      driver_credit_available_minor=old.driver_credit_minor)
    return old, new, p_rows, h_rows, terms


def amendment_promo_view(session: Session, booking, amendment, *, viewer_role: str) -> dict | None:  # noqa: ANN001
    """Money terms of an amendment for its screen: the preview while proposed, the stored terms once accepted.
    Client: fare, discount, cash due only (Q103), and nothing at all on a driver-credit-only booking (Q124);
    driver/staff: the driver view."""
    if not booking_has_promo(booking):
        return None
    if amendment.status == "accepted":
        row = session.execute(select(PromoBookingTerms).where(PromoBookingTerms.amendment_id == amendment.id)
                              ).scalar_one_or_none()
        if row is None:
            return None
        quote = _quote_of_row(row)
    elif amendment.status == "proposed":
        computed = _amendment_quote(session, booking, amendment.new_total_minor)
        if computed is None:
            return None
        quote = computed[1]
    else:
        return None
    if viewer_role == "client":
        return client_view(quote, booking.currency) if _client_ever_discounted(session, booking) else None
    return driver_view(quote, booking.currency)


def booking_amendment_ttl():  # noqa: ANN201 - timedelta
    from app.modules.bookings.service import AMENDMENT_TTL  # lazy: bookings imports this module

    return AMENDMENT_TTL


def _carry_plan(rows: Sequence[tuple[PromoRedemption, PromoLot]], new_total: int) -> list[tuple[int, int]]:
    """Keep the soonest-expiring value first; each reservation keeps at most what it had."""
    plan = []
    left = new_total
    for redemption, _lot in rows:
        keep = min(left, redemption.amount_minor)
        plan.append((redemption.id, keep))
        left -= keep
    return plan


def commit_amendment(session: Session, plan: AmendmentPlan, *, booking, amendment_id: int,  # noqa: ANN001
                     author_side: ActorSide, now: datetime | None = None) -> None:
    """Swap the reservations to the new agreement and append its terms - in the caller's transaction, so a failure
    anywhere leaves the previous agreement untouched. Call after locking the wallet account, before the hold."""
    now = _now(now)
    seq = int(session.execute(select(func.max(PromoBookingTerms.seq)).where(
        PromoBookingTerms.booking_id == booking.id)).scalar_one()) + 1
    fault = fault_for_side(author_side)
    for redemption_id, amount in sorted(plan.carries):
        promo_service.carry_reservation(session, redemption_id=redemption_id, new_amount_minor=amount,
                                        new_terms_seq=seq, fault=fault, now=now)
    _insert_terms(session, booking_id=booking.id, seq=seq, quote=plan.new, consent=plan.consent,
                  amendment_id=amendment_id, currency=booking.currency,
                  passenger_campaign_id=plan.passenger_campaign_id, driver_campaign_id=plan.driver_campaign_id,
                  cost_basis=plan.cost_basis)
    _use_consent(session, plan.consent, booking.id, now)


# --- qualification intake (stage 3 hook) ---------------------------------------------------------------------------


def record_event_if_enrolled(session: Session, *, booking_id: int, client_user_id: int, driver_user_id: int,
                             kind: str, occurred_at: datetime | None, now: datetime | None = None) -> bool:
    """Record a qualification intake event in the caller's transaction, only when a party has a live enrollment
    (a rolled-back booking command leaves no event; the sweep covers enrollments made later)."""
    from app.modules.promotions.qualification import record_booking_event

    live = session.execute(text(
        "SELECT 1 FROM promo_enrollments WHERE status = 'promised' AND referee_user_id IN (:c, :d) LIMIT 1"),
        {"c": client_user_id, "d": driver_user_id}).first()
    if live is None:
        return False
    return record_booking_event(session, booking_id=booking_id, kind=kind, occurred_at=occurred_at, now=now)
