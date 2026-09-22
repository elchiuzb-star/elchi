"""Outbox event envelope with per-event payload allowlists (spec §15, ADR-0012, D17).

Each event has an id, aggregate type/id/version, occurred_at and a minimal,
flat payload. Only keys listed for the event type are accepted and values must
be scalars (or lists of scalars). Phone numbers, passport data, names,
addresses, coordinates, codes and tokens therefore cannot enter a payload;
consumers fetch current state from the API with the recipient's permissions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.contracts.enums import EventType
from app.contracts.timeutil import ensure_aware_utc, to_iso_utc

E = EventType

EVENT_PAYLOAD_ALLOWLIST: dict[EventType, frozenset[str]] = {
    E.LISTING_PUBLISHED: frozenset(
        {"kind", "service_type", "corridor_id", "origin_stop_id", "destination_stop_id",
         "departure_window_start", "departure_window_end", "listing_version"}
    ),
    E.LISTING_EXPIRED: frozenset({"kind", "service_type", "reason_code"}),
    E.LISTING_CANCELLED: frozenset({"kind", "service_type", "reason_code"}),
    E.PROPOSAL_CREATED: frozenset({"listing_id", "thread_id", "revision", "author_side"}),
    E.PROPOSAL_SUPERSEDED: frozenset({"listing_id", "thread_id", "revision", "author_side"}),
    E.PROPOSAL_WITHDRAWN: frozenset({"listing_id", "thread_id", "revision", "reason_code"}),
    E.PROPOSAL_REJECTED: frozenset({"listing_id", "thread_id", "revision", "reason_code"}),
    E.PROPOSAL_EXPIRED: frozenset({"listing_id", "thread_id", "revision", "reason_code"}),
    E.BOOKING_ACCEPTED: frozenset(
        {"service_type", "trip_id", "listing_id", "proposal_version_id", "service_status", "commission_status"}
    ),
    E.BOOKING_CANCELLED: frozenset({"service_type", "trip_id", "cancelled_by_side", "reason_code"}),
    E.BOOKING_STARTED: frozenset({"service_type", "trip_id", "service_status"}),
    E.BOOKING_STATUS_CHANGED: frozenset({"service_type", "trip_id", "machine", "from_status", "to_status"}),
    E.BOOKING_COMPLETED: frozenset({"service_type", "trip_id", "commission_status"}),
    E.BOOKING_NO_SHOW_REPORTED: frozenset({"trip_id", "review_status"}),
    E.BOOKING_CUSTODY_CASE_OPENED: frozenset({"trip_id", "service_status", "reason_code"}),
    E.TRIP_STATUS_CHANGED: frozenset({"from_status", "to_status", "reason_code"}),
    E.WALLET_HOLD_CREATED: frozenset({"booking_id", "amount_minor", "currency"}),
    E.WALLET_HOLD_ADJUSTED: frozenset({"booking_id", "amount_minor", "delta_minor", "currency"}),
    E.WALLET_HOLD_RELEASED: frozenset({"booking_id", "amount_minor", "currency"}),
    E.COMMISSION_CAPTURED: frozenset({"booking_id", "amount_minor", "currency", "fee_bps"}),
    E.COMMISSION_REVERSED: frozenset({"booking_id", "amount_minor", "currency", "reversal_kind"}),
    E.COMMISSION_POLICY_CREATED: frozenset(
        {"policy_id", "kind", "fee_bps", "scope_corridor_id", "scope_service_type", "effective_from", "effective_to"}
    ),
    E.COMMISSION_POLICY_ENDED: frozenset({"policy_id", "effective_to"}),
    E.TOPUP_APPROVED: frozenset({"topup_id", "amount_minor", "currency"}),
    E.TRACKING_STALE: frozenset({"trip_id", "freshness", "last_captured_at"}),
    E.DISPUTE_OPENED: frozenset({"booking_id", "dispute_type"}),
    E.DISPUTE_RESOLVED: frozenset({"booking_id", "dispute_type", "status", "resolution_code"}),
    # Q43/Q45: which field of which object was masked - no raw or masked text.
    E.CONTACT_FILTER_HIT: frozenset(
        {"actor_id", "subject_type", "subject_id", "field", "categories", "match_count", "filter_version"}
    ),
    E.CONTACT_STRIKE_RECORDED: frozenset({"actor_id", "strike_count", "reason_code", "subject_type", "subject_id"}),
    # Wave 2 (§9.5): operator queue signals (awaiting_confirmation / hold_escalation), no personal data.
    E.BOOKING_CONFIRMATION_OVERDUE: frozenset({"booking_id", "trip_id", "service_type", "service_status", "overdue_since"}),
    E.WALLET_HOLD_ESCALATION_DUE: frozenset({"booking_id", "hold_id", "amount_minor", "currency", "escalate_at"}),
    # Wave 2.1: a proof code was reissued (never the code itself); Q66 commission held for finance review.
    E.BOOKING_PROOF_CODE_REISSUED: frozenset({"service_type", "proof_kind", "code_rotation", "requested_by_side"}),
    E.COMMISSION_FINANCE_REVIEW_REQUIRED: frozenset({"booking_id", "reason_code", "amount_minor", "currency"}),
    # Wave 3 (16.09.2026): no text, phone, name, coordinate or code values (§15).
    E.CHAT_MESSAGE_CREATED: frozenset({"thread_id", "thread_kind", "message_id", "author_side", "quick_reply"}),
    E.BOOKING_DRIVER_ARRIVED: frozenset({"service_type", "trip_id", "arrived_at"}),
    E.TRACKING_WINDOW_OPENED: frozenset({"booking_id", "trip_id", "service_type", "opens_at"}),
    E.SAVED_SEARCH_MATCHED: frozenset({"saved_search_id", "listing_id", "service_type", "side"}),
    E.TRUST_REVIEW_OPENED: frozenset({"review_id", "signal_type", "subject_id"}),
    E.TRUST_WARNING_ISSUED: frozenset({"review_id", "signal_type"}),
    # Wave 5: what changed and who asked - no price-per-unit commission, no free text (Q16, §15).
    E.BOOKING_AMENDMENT_REQUESTED: frozenset(
        {"amendment_id", "service_type", "author_side", "new_quantity", "new_total_minor", "currency", "expires_at"}
    ),
    E.BOOKING_AMENDMENT_DECIDED: frozenset({"amendment_id", "service_type", "author_side", "status"}),
    E.SUPPORT_TICKET_OPENED: frozenset({"ticket_id", "kind", "booking_id", "trip_id"}),
    E.SUPPORT_SOS_RAISED: frozenset({"ticket_id", "booking_id", "trip_id"}),
    E.SUPPORT_TICKET_STATUS_CHANGED: frozenset({"ticket_id", "kind", "from_status", "to_status"}),
    E.RATING_PUBLISHED: frozenset({"booking_id", "service_type", "subject_side"}),
    E.DISPUTE_ESCALATION_DUE: frozenset({"booking_id", "dispute_type", "escalate_at"}),
}

class EventAudience(StrEnum):
    """Recipient class of an event copy (N2). Concrete recipients are resolved by A7."""

    CLIENT = "client"
    DRIVER = "driver"
    STAFF = "staff"
    # Wave 3 (ADR-0019 §9): an eligible driver with an open proposal thread on the same request listing, who is
    # not a party of the event's thread. Gets only COMPETING_DRIVER_PAYLOAD_KEYS and re-reads P9.
    COMPETING_DRIVER = "competing_driver"


_ALL = frozenset({EventAudience.CLIENT, EventAudience.DRIVER, EventAudience.STAFF})
_DRIVER_STAFF = frozenset({EventAudience.DRIVER, EventAudience.STAFF})
_STAFF = frozenset({EventAudience.STAFF})
_ALL_AND_COMPETITORS = _ALL | frozenset({EventAudience.COMPETING_DRIVER})

# ADR-0019 §9: proposal events whose competitor copy is delivered; the copy carries only these keys (no price).
COMPETING_DRIVER_EVENT_TYPES: frozenset[EventType] = frozenset(
    {E.PROPOSAL_CREATED, E.PROPOSAL_SUPERSEDED, E.PROPOSAL_WITHDRAWN, E.PROPOSAL_EXPIRED}
)
COMPETING_DRIVER_PAYLOAD_KEYS: frozenset[str] = frozenset({"listing_id"})

# N2 / Q16: wallet.* and commission.* never reach clients; commission policy events are staff-only.
EVENT_AUDIENCES: dict[EventType, frozenset[EventAudience]] = {
    E.LISTING_PUBLISHED: _ALL,
    E.LISTING_EXPIRED: _ALL,
    E.LISTING_CANCELLED: _ALL,
    E.PROPOSAL_CREATED: _ALL_AND_COMPETITORS,
    E.PROPOSAL_SUPERSEDED: _ALL_AND_COMPETITORS,
    E.PROPOSAL_WITHDRAWN: _ALL_AND_COMPETITORS,
    E.PROPOSAL_REJECTED: _ALL,
    E.PROPOSAL_EXPIRED: _ALL_AND_COMPETITORS,
    E.BOOKING_ACCEPTED: _ALL,
    E.BOOKING_CANCELLED: _ALL,
    E.BOOKING_STARTED: _ALL,
    E.BOOKING_STATUS_CHANGED: _ALL,
    E.BOOKING_COMPLETED: _ALL,
    E.BOOKING_NO_SHOW_REPORTED: _ALL,
    E.BOOKING_CUSTODY_CASE_OPENED: _ALL,
    E.TRIP_STATUS_CHANGED: _ALL,
    E.WALLET_HOLD_CREATED: _DRIVER_STAFF,
    E.WALLET_HOLD_ADJUSTED: _DRIVER_STAFF,
    E.WALLET_HOLD_RELEASED: _DRIVER_STAFF,
    E.COMMISSION_CAPTURED: _DRIVER_STAFF,
    E.COMMISSION_REVERSED: _DRIVER_STAFF,
    E.COMMISSION_POLICY_CREATED: _STAFF,
    E.COMMISSION_POLICY_ENDED: _STAFF,
    E.TOPUP_APPROVED: _DRIVER_STAFF,
    E.TRACKING_STALE: _ALL,
    E.DISPUTE_OPENED: _ALL,
    E.DISPUTE_RESOLVED: _ALL,
    E.CONTACT_FILTER_HIT: _STAFF,
    E.CONTACT_STRIKE_RECORDED: _STAFF,
    E.BOOKING_CONFIRMATION_OVERDUE: _STAFF,
    E.WALLET_HOLD_ESCALATION_DUE: _STAFF,
    E.BOOKING_PROOF_CODE_REISSUED: _ALL,
    E.COMMISSION_FINANCE_REVIEW_REQUIRED: _STAFF,
    E.CHAT_MESSAGE_CREATED: _ALL,
    E.BOOKING_DRIVER_ARRIVED: _ALL,
    E.TRACKING_WINDOW_OPENED: _ALL,
    E.SAVED_SEARCH_MATCHED: _ALL,
    E.TRUST_REVIEW_OPENED: _STAFF,
    E.TRUST_WARNING_ISSUED: _ALL,
    E.BOOKING_AMENDMENT_REQUESTED: _ALL,
    E.BOOKING_AMENDMENT_DECIDED: _ALL,
    E.SUPPORT_TICKET_OPENED: _STAFF,
    E.SUPPORT_SOS_RAISED: _STAFF,
    E.SUPPORT_TICKET_STATUS_CHANGED: _ALL,
    E.RATING_PUBLISHED: _ALL,
    E.DISPUTE_ESCALATION_DUE: _STAFF,
}

# Keys removed from every client copy: they reveal commission (Q16).
CLIENT_REDACTED_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"commission_status", "fee_bps", "commission_minor", "net_minor", "fee_policy_id", "amount_minor", "delta_minor"}
)
# booking.status_changed copies about these machines are not sent to clients at all.
CLIENT_HIDDEN_STATUS_MACHINES: frozenset[str] = frozenset({"commission"})
# Wave 3 (Q16): dispute.* copies about these dispute types are not sent to clients (drivers and staff still get them).
CLIENT_HIDDEN_DISPUTE_TYPES: frozenset[str] = frozenset({"commission"})


def payload_for_audience(
    event_type: EventType, payload: dict[str, Any], audience: EventAudience
) -> dict[str, Any] | None:
    """Return the payload copy for an audience, or ``None`` if it must not be sent (N2)."""
    audience = EventAudience(audience)
    if audience not in EVENT_AUDIENCES[event_type]:
        return None
    if audience is EventAudience.COMPETING_DRIVER:
        if event_type not in COMPETING_DRIVER_EVENT_TYPES:
            return None
        return {key: value for key, value in payload.items() if key in COMPETING_DRIVER_PAYLOAD_KEYS}
    if audience is not EventAudience.CLIENT:
        return dict(payload)
    if payload.get("machine") in CLIENT_HIDDEN_STATUS_MACHINES:
        return None
    if payload.get("dispute_type") in CLIENT_HIDDEN_DISPUTE_TYPES:
        return None
    return {key: value for key, value in payload.items() if key not in CLIENT_REDACTED_PAYLOAD_KEYS}


_SCALARS = (str, int, bool, type(None))


def payload_violations(event_type: EventType, payload: dict[str, Any]) -> list[str]:
    """Return human-readable violations; empty list means the payload is valid."""
    allowed = EVENT_PAYLOAD_ALLOWLIST[event_type]
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be a dict"]
    for key, value in payload.items():
        if key not in allowed:
            problems.append(f"key not allowed for {event_type.value}: {key}")
            continue
        if isinstance(value, float):
            problems.append(f"float not allowed: {key}")
        elif isinstance(value, list):
            if not all(isinstance(item, _SCALARS) and not isinstance(item, float) for item in value):
                problems.append(f"list items must be scalars: {key}")
        elif not isinstance(value, _SCALARS):
            problems.append(f"value must be a scalar: {key}")
    return problems


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_type: EventType
    aggregate_type: str
    aggregate_public_id: str
    aggregate_version: int
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, EventType):
            raise TypeError("event_type must be an EventType")
        if isinstance(self.aggregate_version, bool) or not isinstance(self.aggregate_version, int) or self.aggregate_version < 1:
            raise ValueError("aggregate_version must be a positive int")
        object.__setattr__(self, "occurred_at", ensure_aware_utc(self.occurred_at, field="occurred_at"))
        problems = payload_violations(self.event_type, self.payload)
        if problems:
            raise ValueError(f"invalid event payload: {problems}")

    def payload_for(self, audience: EventAudience) -> dict[str, Any] | None:
        return payload_for_audience(self.event_type, self.payload, audience)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_public_id,
            "aggregate_version": self.aggregate_version,
            "occurred_at": to_iso_utc(self.occurred_at),
            "payload": self.payload,
        }
