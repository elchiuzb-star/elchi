"""Proof code attempt limits and reissue policy (wave 2.1, BR blocker 3; ADR-0018 §2).

Five wrong codes lock a proof kind (``PROOF_ATTEMPTS_EXCEEDED``). Without a reissue the passenger or parcel is
locked out forever. A reissue increments ``booking_proofs.code_rotation``: the code is derived from the rotation
(``crypto.derive_proof_code``), so the previous code stops verifying and ``failed_attempts`` restarts at 0.

* Self-service reissue - only the code owner (passenger: boarding; sender: pickup/delivery/return), never the
  driver; limited by :func:`reissue_decision` -> ``429 PROOF_REISSUE_LIMITED``.
* Operator reissue - ``OperatorBookingCommand.REISSUE_PROOF_CODE`` (``ops.booking_command``), reason required,
  audited, not rate-limited.
* Every reissue: audit row (actor, side, kind, from/to rotation, reason) and ``booking.proof_code.reissued``
  (payload never contains a code). An accepted proof cannot be reissued.

Pilot defaults are integrator constants (change through the integrator, like other contract values).
Pure: stdlib only.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts.enums import ProofKind
from app.contracts.timeutil import ensure_aware_utc

PROOF_CODE_MAX_FAILED_ATTEMPTS = 5  # DB CHECK booking_proofs.failed_attempts <= 5 (0049)
PROOF_REISSUE_MIN_INTERVAL = timedelta(minutes=2)
PROOF_REISSUE_WINDOW = timedelta(hours=24)
PROOF_REISSUE_MAX_IN_WINDOW = 3  # self-service, per booking x proof kind, rolling window

REISSUABLE_PROOF_KINDS: frozenset[ProofKind] = frozenset(
    {ProofKind.BOARDING_CODE, ProofKind.PICKUP_CODE, ProofKind.DELIVERY_CODE, ProofKind.RETURN_CODE}
)


@dataclass(frozen=True, slots=True)
class ReissueDecision:
    allowed: bool
    retry_after_s: int  # 0 when allowed
    reissues_left: int  # self-service reissues left in the window after this decision

    def error_details(self) -> dict[str, int]:
        """``details`` of ``PROOF_REISSUE_LIMITED``."""
        return {"retry_after_s": self.retry_after_s, "reissues_left": self.reissues_left}


def reissue_decision(previous_self_service_reissues: Iterable[datetime], now: datetime) -> ReissueDecision:
    """Whether the code owner may reissue now, given earlier self-service reissues of the same booking + kind."""
    now = ensure_aware_utc(now, field="now")
    window_start = now - PROOF_REISSUE_WINDOW
    recent = sorted(t for t in (ensure_aware_utc(v, field="reissued_at") for v in previous_self_service_reissues) if t > window_start)
    if recent and now - recent[-1] < PROOF_REISSUE_MIN_INTERVAL:
        wait = PROOF_REISSUE_MIN_INTERVAL - (now - recent[-1])
        return ReissueDecision(False, max(1, int(wait.total_seconds())), max(0, PROOF_REISSUE_MAX_IN_WINDOW - len(recent)))
    if len(recent) >= PROOF_REISSUE_MAX_IN_WINDOW:
        wait = recent[len(recent) - PROOF_REISSUE_MAX_IN_WINDOW] + PROOF_REISSUE_WINDOW - now
        return ReissueDecision(False, max(1, int(wait.total_seconds())), 0)
    return ReissueDecision(True, 0, PROOF_REISSUE_MAX_IN_WINDOW - len(recent) - 1)
