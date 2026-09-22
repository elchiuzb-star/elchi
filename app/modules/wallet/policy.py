"""Pure commission-policy resolution (ADR-0009 §2, decision Q19). No I/O.

Precedence: any applicable ``campaign`` beats every ``standard``; within the
winning kind the most specific scope wins:
corridor+service (3) > corridor (2) > service (1) > global (0).
The exclusion constraint guarantees at most one policy per (scope, kind, instant),
so ties cannot happen on PostgreSQL; the tie-breaker only makes the function total.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.contracts.enums import CommissionPolicyKind, ServiceType
from app.contracts.money import bps_to_percent
from app.contracts.timeutil import ensure_aware_utc


@dataclass(frozen=True, slots=True)
class PolicyCandidate:
    id: int
    kind: CommissionPolicyKind
    scope_corridor_id: int | None
    scope_service_type: ServiceType | None
    fee_bps: int
    effective_from: datetime
    effective_to: datetime | None


def scope_specificity(candidate: PolicyCandidate) -> int:
    return (2 if candidate.scope_corridor_id is not None else 0) + (1 if candidate.scope_service_type is not None else 0)


def policy_applies(
    candidate: PolicyCandidate, *, corridor_id: int | None, service_type: ServiceType | str | None, at: datetime
) -> bool:
    at = ensure_aware_utc(at, field="at")
    service = None if service_type is None else ServiceType(service_type)
    if candidate.scope_corridor_id is not None and candidate.scope_corridor_id != corridor_id:
        return False
    if candidate.scope_service_type is not None and candidate.scope_service_type != service:
        return False
    start = ensure_aware_utc(candidate.effective_from, field="effective_from")
    if at < start:
        return False
    return candidate.effective_to is None or at < ensure_aware_utc(candidate.effective_to, field="effective_to")


def select_policy(
    candidates: Iterable[PolicyCandidate],
    *,
    corridor_id: int | None,
    service_type: ServiceType | str | None,
    at: datetime,
) -> PolicyCandidate | None:
    applicable = [c for c in candidates if policy_applies(c, corridor_id=corridor_id, service_type=service_type, at=at)]
    if not applicable:
        return None
    return max(
        applicable,
        key=lambda c: (
            c.kind is CommissionPolicyKind.CAMPAIGN,
            scope_specificity(c),
            ensure_aware_utc(c.effective_from),
            c.id,
        ),
    )


def fee_percent_text(fee_bps: int) -> str:
    """``1500`` -> ``"15.00"`` for display DTOs (never used for arithmetic)."""
    return str(bps_to_percent(fee_bps).quantize(Decimal("0.01")))
