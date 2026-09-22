"""Every error message the client shows is keyed on a real error code (wave 13; wave 15: two languages).

A typo in this map is invisible: the code simply never matches and the person sees the generic fallback
instead of the sentence that tells them what to do. So the keys are checked against the contract enum, and the
codes a person actually meets in the stage-2 flows are required to have a message.

The messages moved from `utils/errors.ts` into the shared dictionary (`src/i18n/messages.ts`) when the client
gained Russian, so the same guard now also proves a reachable refusal is not Uzbek-only - a Russian speaker
reading an Uzbek refusal cannot act on it any more than they could read the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.contracts.errors import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
MESSAGES_TS = ROOT / "mobile-app" / "src" / "i18n" / "messages.ts"

# v1 codes the legacy screens still raise; they are not in the v2 enum but are real.
V1_ONLY = {
    "ROLE_MISMATCH", "OTP_INVALID", "OTP_EXPIRED", "OTP_USED", "OTP_RESEND_TOO_SOON",
    "OTP_TOO_MANY_ATTEMPTS", "OTP_SEND_LIMIT_EXCEEDED", "INVALID_PHONE", "DRIVER_NOT_APPROVED",
    "DRIVER_NOT_AVAILABLE", "DRIVER_DOCUMENTS_INCOMPLETE", "DRIVER_DOCUMENT_INVALID_TYPE",
    "DRIVER_DOCUMENT_TOO_LARGE", "DRIVER_VEHICLE_LOCKED", "CITY_INACTIVE", "DISTRICT_REQUIRED",
    "DISTRICT_CITY_MISMATCH", "DISTRICT_INACTIVE", "ROUTE_TARIFF_NOT_FOUND", "ROUTE_NOT_MATCHED", "USER_BLOCKED", "USER_INACTIVE",
}

# What a client or driver can actually run into while publishing, negotiating, carrying and closing a booking.
REACHABLE = {
    ErrorCode.FEATURE_DISABLED, ErrorCode.VERSION_CONFLICT, ErrorCode.INSUFFICIENT_COMMISSION_BALANCE,
    ErrorCode.NOT_PROPOSAL_RECIPIENT, ErrorCode.PROPOSAL_CHANGED, ErrorCode.PROPOSAL_EXPIRED,
    ErrorCode.NEGOTIATION_LIMIT_REACHED, ErrorCode.PRICE_OUT_OF_BAND, ErrorCode.CARGO_LIMIT_EXCEEDED,
    ErrorCode.CAPACITY_UNAVAILABLE, ErrorCode.TIME_WINDOW_CONFLICT, ErrorCode.TRIP_NOT_STARTED,
    ErrorCode.PROOF_INVALID, ErrorCode.TRACKING_WINDOW_NOT_OPEN, ErrorCode.VEHICLE_NOT_ELIGIBLE,
    ErrorCode.DRIVER_NOT_ELIGIBLE, ErrorCode.LISTING_NOT_OPEN, ErrorCode.RATING_ALREADY_EXISTS,
    ErrorCode.DISPUTE_ALREADY_OPEN,
}


def mapped_codes() -> dict[str, str]:
    """`{ERROR_CODE: the whole dictionary entry}` for every `error.*` key in the shared dictionary.

    The entry text is kept, not just the key, so a second check can ask whether the Russian side is filled in.
    """
    source = MESSAGES_TS.read_text(encoding="utf-8")
    pattern = re.compile(r'^  "error\.([A-Z][A-Z0-9_]+)": (\{[^\n]*\}|\{\n(?:[^\n]*\n)*?  \}),$', re.M)
    return {match.group(1): match.group(2) for match in pattern.finditer(source)}


@pytest.mark.skipif(not MESSAGES_TS.exists(), reason="mobile-app sources are not present")
def test_every_key_is_a_real_error_code() -> None:
    known = {code.value for code in ErrorCode} | V1_ONLY
    unknown = sorted(set(mapped_codes()) - known)
    assert unknown == [], f"these keys match no error the server sends: {unknown}"


@pytest.mark.skipif(not MESSAGES_TS.exists(), reason="mobile-app sources are not present")
def test_the_refusals_a_person_can_fix_have_a_message() -> None:
    mapped = mapped_codes()
    missing = sorted(code.value for code in REACHABLE if code.value not in mapped)
    assert missing == [], f"these would show only the generic failure: {missing}"


@pytest.mark.skipif(not MESSAGES_TS.exists(), reason="mobile-app sources are not present")
def test_those_refusals_are_not_uzbek_only() -> None:
    """A refusal a person can act on has to be readable by both audiences, not just the default one."""
    mapped = mapped_codes()
    untranslated = sorted(
        code.value for code in REACHABLE if code.value in mapped and "ru:" not in mapped[code.value]
    )
    assert untranslated == [], f"no Russian for: {untranslated}"
