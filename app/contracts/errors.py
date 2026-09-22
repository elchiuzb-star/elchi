"""API v2 error code catalogue (spec §14.2, ADR-0005).

Every v2 error response is ``{"success": false, "error": {"code", "message",
"details", "request_id"}}`` with the HTTP status listed here. Codes are
stable identifiers for clients; messages are for humans and may change.

Visibility rule: an object that does not exist *or* that the caller may not
know exists returns ``NOT_FOUND`` (404), never ``FORBIDDEN``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # generic (shared with v1 where the v1 code already exists)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    # request mechanics
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_INVALID = "IDEMPOTENCY_KEY_INVALID"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_CURSOR = "INVALID_CURSOR"
    CLIENT_UPGRADE_REQUIRED = "CLIENT_UPGRADE_REQUIRED"
    LEGACY_OBJECT_READ_ONLY = "LEGACY_OBJECT_READ_ONLY"
    # identity / eligibility
    CAPABILITY_REQUIRED = "CAPABILITY_REQUIRED"
    DRIVER_NOT_ELIGIBLE = "DRIVER_NOT_ELIGIBLE"
    VEHICLE_NOT_ELIGIBLE = "VEHICLE_NOT_ELIGIBLE"
    ROLE_COMBINATION_FORBIDDEN = "ROLE_COMBINATION_FORBIDDEN"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    FLAG_LOCKED_IN_ENVIRONMENT = "FLAG_LOCKED_IN_ENVIRONMENT"
    PRODUCTION_INVARIANTS_FAILED = "PRODUCTION_INVARIANTS_FAILED"
    # state machines
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    # marketplace
    LISTING_INCOMPLETE = "LISTING_INCOMPLETE"
    LISTING_NOT_OPEN = "LISTING_NOT_OPEN"
    LISTING_EXPIRED = "LISTING_EXPIRED"
    DUPLICATE_LISTING = "DUPLICATE_LISTING"
    SELF_DEALING_FORBIDDEN = "SELF_DEALING_FORBIDDEN"
    NOT_PROPOSAL_RECIPIENT = "NOT_PROPOSAL_RECIPIENT"
    PROPOSAL_CHANGED = "PROPOSAL_CHANGED"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    NEGOTIATION_LIMIT_REACHED = "NEGOTIATION_LIMIT_REACHED"
    PRICE_BASIS_NOT_ALLOWED = "PRICE_BASIS_NOT_ALLOWED"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_OUT_OF_BAND = "PRICE_OUT_OF_BAND"
    # trips / capacity / geo
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    CAPACITY_UNAVAILABLE = "CAPACITY_UNAVAILABLE"
    CARGO_LIMIT_EXCEEDED = "CARGO_LIMIT_EXCEEDED"
    ROUTE_CHANGED = "ROUTE_CHANGED"
    ROUTE_MISMATCH = "ROUTE_MISMATCH"
    DETOUR_LIMIT_EXCEEDED = "DETOUR_LIMIT_EXCEEDED"
    TIME_WINDOW_CONFLICT = "TIME_WINDOW_CONFLICT"
    BOOKING_CUTOFF_PASSED = "BOOKING_CUTOFF_PASSED"
    CORRIDOR_NOT_ACTIVE = "CORRIDOR_NOT_ACTIVE"
    ROUTING_UNAVAILABLE = "ROUTING_UNAVAILABLE"
    TRIP_HAS_UNRESOLVED_BOOKINGS = "TRIP_HAS_UNRESOLVED_BOOKINGS"
    # bookings
    PROOF_INVALID = "PROOF_INVALID"
    PROOF_ATTEMPTS_EXCEEDED = "PROOF_ATTEMPTS_EXCEEDED"
    CUSTODY_REQUIRES_RETURN_FLOW = "CUSTODY_REQUIRES_RETURN_FLOW"
    NO_SHOW_NOT_ALLOWED = "NO_SHOW_NOT_ALLOWED"
    NO_SHOW_REVIEW_PENDING = "NO_SHOW_REVIEW_PENDING"
    AMENDMENT_CONFLICT = "AMENDMENT_CONFLICT"
    # wallet / ledger / commission
    INSUFFICIENT_COMMISSION_BALANCE = "INSUFFICIENT_COMMISSION_BALANCE"
    TOPUP_REFERENCE_DUPLICATE = "TOPUP_REFERENCE_DUPLICATE"
    SECOND_APPROVER_REQUIRED = "SECOND_APPROVER_REQUIRED"
    LEDGER_UNBALANCED = "LEDGER_UNBALANCED"
    REVERSAL_EXCEEDS_CAPTURED = "REVERSAL_EXCEEDS_CAPTURED"
    COMMISSION_POLICY_OVERLAP = "COMMISSION_POLICY_OVERLAP"
    COMMISSION_POLICY_UNCONFIRMED = "COMMISSION_POLICY_UNCONFIRMED"
    COMMISSION_POLICY_RETROACTIVE = "COMMISSION_POLICY_RETROACTIVE"
    # §5.2 parcel policy (wave 7): no approved prohibited-items policy -> no NEW parcel business.
    PARCEL_POLICY_UNCONFIRMED = "PARCEL_POLICY_UNCONFIRMED"
    # tracking
    TRACKING_SESSION_SUPERSEDED = "TRACKING_SESSION_SUPERSEDED"
    TRACKING_BATCH_TOO_LARGE = "TRACKING_BATCH_TOO_LARGE"
    TRACKING_WINDOW_NOT_OPEN = "TRACKING_WINDOW_NOT_OPEN"
    # trust & support
    DISPUTE_ALREADY_OPEN = "DISPUTE_ALREADY_OPEN"
    RATING_NOT_ALLOWED = "RATING_NOT_ALLOWED"
    RATING_ALREADY_EXISTS = "RATING_ALREADY_EXISTS"
    ACCOUNT_DELETION_BLOCKED = "ACCOUNT_DELETION_BLOCKED"
    APPROVAL_REFERENCE_REQUIRED = "APPROVAL_REFERENCE_REQUIRED"
    # wave 2.1 (15.09.2026, Q59-Q73 and the wave 2 BR review)
    TRIP_NOT_STARTED = "TRIP_NOT_STARTED"
    TRIP_STOPS_LOCKED = "TRIP_STOPS_LOCKED"
    PROOF_REISSUE_LIMITED = "PROOF_REISSUE_LIMITED"
    INTEGRITY_CONFLICT = "INTEGRITY_CONFLICT"
    # wave 3 (16.09.2026): tracking (A6), communications (A7), saved searches (A5)
    TRACKING_SESSION_CLOSED = "TRACKING_SESSION_CLOSED"
    CHAT_CLOSED = "CHAT_CLOSED"
    SAVED_SEARCH_LIMIT_REACHED = "SAVED_SEARCH_LIMIT_REACHED"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    http_status: int
    description: str


ERROR_CATALOGUE: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.VALIDATION_ERROR: ErrorSpec(400, "Request body, query or header failed validation."),
    ErrorCode.UNAUTHORIZED: ErrorSpec(401, "Missing, expired or revoked access token."),
    ErrorCode.FORBIDDEN: ErrorSpec(403, "Caller is known to the object but may not perform the command."),
    ErrorCode.NOT_FOUND: ErrorSpec(404, "Object missing or hidden from the caller."),
    ErrorCode.RATE_LIMITED: ErrorSpec(429, "Quantitative limit reached; see Retry-After."),
    ErrorCode.SERVER_ERROR: ErrorSpec(500, "Unexpected server failure; the transaction was rolled back."),
    ErrorCode.SERVICE_UNAVAILABLE: ErrorSpec(503, "Dependency required for this read/command is unavailable."),
    ErrorCode.IDEMPOTENCY_KEY_REQUIRED: ErrorSpec(400, "Command requires an Idempotency-Key header."),
    ErrorCode.IDEMPOTENCY_KEY_INVALID: ErrorSpec(400, "Idempotency-Key has an invalid format."),
    ErrorCode.IDEMPOTENCY_KEY_REUSED: ErrorSpec(409, "Same key was used with a different request (spec §14.2)."),
    ErrorCode.IDEMPOTENCY_IN_PROGRESS: ErrorSpec(409, "A request with the same key is still being processed."),
    ErrorCode.VERSION_CONFLICT: ErrorSpec(409, "expected_version does not match the current aggregate version."),
    ErrorCode.INVALID_CURSOR: ErrorSpec(400, "Cursor is malformed, tampered or belongs to another query."),
    ErrorCode.CLIENT_UPGRADE_REQUIRED: ErrorSpec(409, "Legacy client cannot mutate this v2 object (spec §18 M5, AC39)."),
    ErrorCode.LEGACY_OBJECT_READ_ONLY: ErrorSpec(409, "v1 object is read-only through v2 (spec §18 M4)."),
    ErrorCode.CAPABILITY_REQUIRED: ErrorSpec(403, "Caller lacks the server-computed capability."),
    ErrorCode.DRIVER_NOT_ELIGIBLE: ErrorSpec(403, "Driver is not approved, is blocked or inactive."),
    ErrorCode.VEHICLE_NOT_ELIGIBLE: ErrorSpec(409, "Vehicle is not verified/active or lacks capacity."),
    ErrorCode.ROLE_COMBINATION_FORBIDDEN: ErrorSpec(409, "Staff and marketplace roles cannot be combined."),
    ErrorCode.FEATURE_DISABLED: ErrorSpec(403, "Feature flag is off for the resolved scope."),
    ErrorCode.FLAG_LOCKED_IN_ENVIRONMENT: ErrorSpec(409, "Flag value is fixed in this environment (wallet_required in production)."),
    ErrorCode.PRODUCTION_INVARIANTS_FAILED: ErrorSpec(
        503, "Money commands are refused while production invariants fail (N1); an alert is raised."
    ),
    ErrorCode.INVALID_STATE_TRANSITION: ErrorSpec(409, "Command is not allowed from the current state."),
    ErrorCode.LISTING_INCOMPLETE: ErrorSpec(400, "Listing lacks fields required for publishing."),
    ErrorCode.LISTING_NOT_OPEN: ErrorSpec(409, "Listing is not published (paused, fulfilled, expired, cancelled)."),
    ErrorCode.LISTING_EXPIRED: ErrorSpec(409, "Listing validity or departure window has passed."),
    ErrorCode.DUPLICATE_LISTING: ErrorSpec(409, "A very similar active listing already exists (spec §5.4)."),
    ErrorCode.SELF_DEALING_FORBIDDEN: ErrorSpec(403, "Actor cannot respond to or accept own listing/proposal (AC05)."),
    ErrorCode.NOT_PROPOSAL_RECIPIENT: ErrorSpec(403, "Only the counterparty of the current version may accept/reject."),
    ErrorCode.PROPOSAL_CHANGED: ErrorSpec(409, "Proposal version is not current (spec §14.2, AC04)."),
    ErrorCode.PROPOSAL_EXPIRED: ErrorSpec(
        409, "Proposal version TTL has passed; its frozen fee quote expires with it, so a new version is needed (AC43)."
    ),
    ErrorCode.NEGOTIATION_LIMIT_REACHED: ErrorSpec(409, "Side exhausted its price revisions (spec §5.3: 3)."),
    ErrorCode.PRICE_BASIS_NOT_ALLOWED: ErrorSpec(400, "Price basis not allowed for this kind/service."),
    ErrorCode.QUANTITY_MISMATCH: ErrorSpec(409, "Proposal quantity must equal the request seat_count; requests are not split (§5.3(6))."),
    ErrorCode.PRICE_OUT_OF_BAND: ErrorSpec(
        400,
        "Offered price is outside the operator-configured band (Q42, Q53; checked at submit/counter only); "
        "details {floor_minor, ceiling_minor, currency, price_basis, scope: segment|corridor}.",
    ),
    ErrorCode.SCHEDULE_CONFLICT: ErrorSpec(409, "Driver or vehicle already has an overlapping active trip (AC13)."),
    ErrorCode.CAPACITY_UNAVAILABLE: ErrorSpec(409, "A required segment lacks seats (spec §14.2, AC07, AC10)."),
    ErrorCode.CARGO_LIMIT_EXCEEDED: ErrorSpec(409, "Baggage/cargo weight or volume exceeds remaining capacity (AC12)."),
    ErrorCode.ROUTE_CHANGED: ErrorSpec(409, "Route version changed since the proposal (spec §14.2)."),
    ErrorCode.ROUTE_MISMATCH: ErrorSpec(409, "Pickup/dropoff not on route or in wrong order (AC14, AC16)."),
    ErrorCode.DETOUR_LIMIT_EXCEEDED: ErrorSpec(409, "Cumulative detour exceeds the trip limit (AC17)."),
    ErrorCode.TIME_WINDOW_CONFLICT: ErrorSpec(409, "Pickup ETA window does not intersect or breaks others' windows."),
    ErrorCode.BOOKING_CUTOFF_PASSED: ErrorSpec(409, "New bookings are closed for this trip (spec §7)."),
    ErrorCode.CORRIDOR_NOT_ACTIVE: ErrorSpec(409, "Service corridor or stop is not active for this service."),
    ErrorCode.ROUTING_UNAVAILABLE: ErrorSpec(503, "Routing/maps provider unavailable; no fake match (AC35)."),
    ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS: ErrorSpec(409, "Trip cannot complete while bookings are unresolved (AC42)."),
    ErrorCode.PROOF_INVALID: ErrorSpec(409, "Boarding/pickup/delivery/return code does not match this action."),
    ErrorCode.PROOF_ATTEMPTS_EXCEEDED: ErrorSpec(429, "Too many wrong code attempts; operator review required."),
    ErrorCode.CUSTODY_REQUIRES_RETURN_FLOW: ErrorSpec(409, "Parcel in custody cannot be simply cancelled (AC22)."),
    ErrorCode.NO_SHOW_NOT_ALLOWED: ErrorSpec(409, "No-show guards not met (arrival, wait time, contact attempts)."),
    ErrorCode.NO_SHOW_REVIEW_PENDING: ErrorSpec(409, "A no-show review is pending; only an operator decision may close it."),
    ErrorCode.AMENDMENT_CONFLICT: ErrorSpec(409, "Another amendment is open or the booking changed."),
    ErrorCode.INSUFFICIENT_COMMISSION_BALANCE: ErrorSpec(409, "Driver available commission balance is too low (AC19)."),
    ErrorCode.TOPUP_REFERENCE_DUPLICATE: ErrorSpec(409, "Source receipt/bank reference already credited (AC23)."),
    ErrorCode.SECOND_APPROVER_REQUIRED: ErrorSpec(409, "Amount requires approval by a different finance user."),
    ErrorCode.LEDGER_UNBALANCED: ErrorSpec(500, "Posting debits and credits differ; transaction aborted."),
    ErrorCode.REVERSAL_EXCEEDS_CAPTURED: ErrorSpec(409, "Sum of reversals would exceed the captured commission (D4)."),
    ErrorCode.COMMISSION_POLICY_OVERLAP: ErrorSpec(409, "Another policy of the same scope/kind covers this period."),
    ErrorCode.COMMISSION_POLICY_UNCONFIRMED: ErrorSpec(
        503, "Only the migration-seeded rate applies; a super_admin must confirm or create the rate (Q28)."
    ),
    ErrorCode.PARCEL_POLICY_UNCONFIRMED: ErrorSpec(
        503,
        "No approved prohibited-items policy is active; new parcel listings and bookings stay closed until a "
        "super_admin confirms one (spec §5.2). Existing bookings are unaffected.",
    ),
    ErrorCode.COMMISSION_POLICY_RETROACTIVE: ErrorSpec(409, "Policies cannot take effect in the past."),
    ErrorCode.TRACKING_SESSION_SUPERSEDED: ErrorSpec(409, "A newer writer session exists for this trip (AC29)."),
    ErrorCode.TRACKING_BATCH_TOO_LARGE: ErrorSpec(400, "More than 100 points in one batch (spec §10.4)."),
    ErrorCode.TRACKING_WINDOW_NOT_OPEN: ErrorSpec(403, "Live location not yet visible for this booking (AC44)."),
    ErrorCode.DISPUTE_ALREADY_OPEN: ErrorSpec(409, "An active dispute of this type exists for the booking."),
    ErrorCode.RATING_NOT_ALLOWED: ErrorSpec(409, "Only completed real bookings can be rated, within the window."),
    ErrorCode.RATING_ALREADY_EXISTS: ErrorSpec(409, "This author already rated this subject for the booking."),
    ErrorCode.ACCOUNT_DELETION_BLOCKED: ErrorSpec(409, "Active bookings, disputes or wallet balance must be closed first."),
    ErrorCode.APPROVAL_REFERENCE_REQUIRED: ErrorSpec(400, "Production enablement needs a recorded approval reference (K7)."),
    ErrorCode.TRIP_NOT_STARTED: ErrorSpec(
        409,
        "Boarding/pickup needs the trip in boarding or in_progress; a planned trip has not started "
        "(state_machines.TRIP_STATUSES_ALLOWING_SERVICE_START).",
    ),
    ErrorCode.TRIP_STOPS_LOCKED: ErrorSpec(
        409, "Trip stops cannot change once any booking was allocated on the trip, even if released (Q63)."
    ),
    ErrorCode.PROOF_REISSUE_LIMITED: ErrorSpec(
        429, "Self-service proof code reissue limit reached; details {retry_after_s, reissues_left} (proofs.py)."
    ),
    ErrorCode.INTEGRITY_CONFLICT: ErrorSpec(
        409, "A database integrity rule refused the change; details {reason} (db_errors.py). Reload and retry."
    ),
    ErrorCode.TRACKING_SESSION_CLOSED: ErrorSpec(
        409, "The tracking session is closed (trip finished or session closed); start a new session if still allowed."
    ),
    ErrorCode.CHAT_CLOSED: ErrorSpec(
        409, "The chat is read-only: the proposal thread is no longer open or the booking ended more than 24 h ago."
    ),
    ErrorCode.SAVED_SEARCH_LIMIT_REACHED: ErrorSpec(
        409, "Saved search limit per user reached; details {limit} (app.contracts.feed.SAVED_SEARCH_MAX_PER_USER)."
    ),
}


class WarningCode(StrEnum):
    """Non-fatal outcomes returned with a successful response (``Envelope.warnings``)."""

    # Q43: free text contained contact information; it was stored/shown masked
    # (details: ContactScanResult.warning_details() - categories, match_count, filter_version).
    CONTACT_INFO_MASKED = "CONTACT_INFO_MASKED"
    # Q53 (G13): a corridor-wide band floor is above an existing segment band floor
    # (details carry both floors); saved anyway - corridor bands are loose safety limits.
    CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR = "CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR"
    # Q65 (wave 2.1): returned with B5 codes when a delivery code is shown to the sender (field "codes.delivery_code").
    DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY = "DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY"
    # Q90 (wave 15): the offered price sits outside the corridor's reference range. It is *advice* - the price
    # the two sides agree on is the price - so it arrives as a warning on a successful submit/counter, with the
    # Q53 details (floor, ceiling, currency, price_basis, scope). Deliberately **not** spelled
    # ``PRICE_OUT_OF_BAND``: that name belongs to the error an ``enforced`` band raises, and warning codes and
    # error codes never share a spelling, so a client never has to guess which register a code is in.
    PRICE_OUTSIDE_REFERENCE = "PRICE_OUTSIDE_REFERENCE"


WARNING_CATALOGUE: dict[WarningCode, str] = {
    WarningCode.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY: (
        "Give the delivery code only to the receiver; the driver must not receive it before handing over the parcel (Q65)."
    ),
    WarningCode.CONTACT_INFO_MASKED: (
        "Contact details (phone, e-mail, handle, messenger or link, call request) were hidden; "
        "communicate through in-app chat until the service starts (Q43, Q44)."
    ),
    WarningCode.CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR: (
        "The corridor-wide floor is above a segment band floor; segment prices below it will be refused (Q53)."
    ),
    WarningCode.PRICE_OUTSIDE_REFERENCE: (
        "This price is outside the usual range for this direction. It was accepted - the two of you agree the "
        "price - but it is worth a second look (Q90)."
    ),
}


def http_status_for(code: ErrorCode) -> int:
    return ERROR_CATALOGUE[code].http_status


class DomainError(Exception):
    """Raised by domain services; the v2 exception handler renders the envelope."""

    def __init__(self, code: ErrorCode, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        if not isinstance(code, ErrorCode):
            raise TypeError("code must be an ErrorCode")
        self.code = code
        self.message = message or ERROR_CATALOGUE[code].description
        self.details = details
        super().__init__(f"{code}: {self.message}")

    @property
    def http_status(self) -> int:
        return http_status_for(self.code)

    def to_error_body(self, request_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        if request_id is not None:
            body["request_id"] = request_id
        return body
