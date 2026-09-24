"""Mapping of database-raised errors to the v2 error envelope (wave 2.1, BR medium; ADR-0005).

Deferred constraint triggers, CHECK/unique/exclusion constraints and guard triggers fire at flush or COMMIT,
outside the owning service's ``DomainError`` translation, and used to surface as a bare 500. ``app.api.v2.web``
now renders every non-retryable ``DBAPIError`` on ``/api/v2`` with :func:`map_db_error`:

1. ``constraint`` - ``diag.constraint_name``. **Convention for wave 2.1+ guard triggers:**
   ``RAISE EXCEPTION '...' USING ERRCODE = '<sqlstate>', CONSTRAINT = '<rule name>'`` with a rule name from
   :data:`CONSTRAINT_RULES` (add the name here through the integrator first).
2. ``message`` prefix - legacy trigger messages without a constraint name (:data:`MESSAGE_PREFIX_RULES`).
3. exact SQLSTATE (:data:`SQLSTATE_RULES`), then SQLSTATE class (:data:`SQLSTATE_CLASS_RULES`).
4. otherwise ``500 SERVER_ERROR`` ``reason=database_error``.

Response ``details`` carry only ``{"reason": <rule reason>}`` - never the DB message, SQL, constraint or
parameters (they go to the server log). Such responses are not stored as idempotent results (the transaction
was rolled back), so a retry with the same ``Idempotency-Key`` re-executes the command.
Owner services should still translate expected violations themselves (better ``details``).
Pure: stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.errors import ErrorCode


@dataclass(frozen=True, slots=True)
class DbErrorRule:
    code: ErrorCode
    reason: str


_R = DbErrorRule

# Rule names used by wave 2.1 migrations (``USING CONSTRAINT = ...``).
CONSTRAINT_RULES: dict[str, DbErrorRule] = {
    "trip_stops_locked": _R(ErrorCode.TRIP_STOPS_LOCKED, "trip_stops_locked"),  # A1 0054, Q63
    "booking_snapshot_frozen": _R(ErrorCode.INTEGRITY_CONFLICT, "booking_snapshot_frozen"),  # A4 0056, Q60
    "approver_not_finance_staff": _R(ErrorCode.FORBIDDEN, "approver_not_finance_staff"),  # A3 0055, Q69
    "q48_gate_money_refused": _R(ErrorCode.PRODUCTION_INVARIANTS_FAILED, "gate_failed"),  # A3 0055, Q70
    # Q72: the admin API sets the source marker, so reaching this through /api/v2 is a server bug.
    "flag_enable_source_refused": _R(ErrorCode.SERVER_ERROR, "flag_enable_source_refused"),  # A2 0057
    # Wave 3 (16.09.2026) planned guards; owners use exactly these names.
    "tracking_session_superseded": _R(ErrorCode.TRACKING_SESSION_SUPERSEDED, "tracking_session_superseded"),  # A6 0058
    "tracking_session_closed": _R(ErrorCode.TRACKING_SESSION_CLOSED, "tracking_session_closed"),  # A6 0058
    "chat_message_immutable": _R(ErrorCode.INTEGRITY_CONFLICT, "chat_message_immutable"),  # A7 0059
    "dispute_terminal_frozen": _R(ErrorCode.INVALID_STATE_TRANSITION, "dispute_terminal_frozen"),  # A12 0060
    # partial unique index name (diag.constraint_name of a unique-index violation is the index name)
    "uq_disputes_v2_booking_type_active": _R(ErrorCode.DISPUTE_ALREADY_OPEN, "dispute_already_open"),  # A12 0060
    "saved_search_limit": _R(ErrorCode.SAVED_SEARCH_LIMIT_REACHED, "saved_search_limit"),  # A5 0061
    # generic append-only guard for wave 3 history tables (dispute_evidence, contact_strikes, tracking receipts, ...)
    "append_only_violation": _R(ErrorCode.INTEGRITY_CONFLICT, "append_only_violation"),
    # wave 5 (A10b 0065, Q4): INSTEAD OF trigger on every legacy_*_v projection refuses writes for any role.
    "legacy_object_read_only": _R(ErrorCode.LEGACY_OBJECT_READ_ONLY, "legacy_object_read_only"),
    # referral stage 1 (0084, ADR-0023): promotions budget, ledger and state guards.
    "promo_budget_exhausted": _R(ErrorCode.PROMO_BUDGET_EXHAUSTED, "promo_budget_exhausted"),
    "uq_bookings_trip_intent_binding": _R(ErrorCode.TRIP_INTENT_BOOKED, "trip_intent_already_booked"),  # 0091
    "booking_trip_intent_mismatch": _R(ErrorCode.INTEGRITY_CONFLICT, "booking_trip_intent_mismatch"),  # 0091
    "trip_intent_link_frozen": _R(ErrorCode.INTEGRITY_CONFLICT, "trip_intent_link_frozen"),  # 0091
    "trip_intent_invalid_transition": _R(ErrorCode.INVALID_STATE_TRANSITION, "trip_intent_invalid_transition"),  # 0091
    "promo_budget_below_commitment": _R(ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT, "promo_budget_below_commitment"),  # 0090
    "promo_funding_loss_evidence": _R(ErrorCode.VALIDATION_ERROR, "promo_funding_loss_evidence"),  # 0090
    "promo_budget_writer_refused": _R(ErrorCode.INTEGRITY_CONFLICT, "promo_budget_writer_refused"),
    "promo_budget_cache_mismatch": _R(ErrorCode.INTEGRITY_CONFLICT, "promo_budget_cache_mismatch"),
    "promo_second_approver_required": _R(ErrorCode.SECOND_APPROVER_REQUIRED, "promo_second_approver_required"),
    "promo_activation_incomplete": _R(ErrorCode.PROMO_PARAMETERS_UNSET, "promo_activation_incomplete"),
    "promo_invalid_transition": _R(ErrorCode.INVALID_STATE_TRANSITION, "promo_invalid_transition"),
    "promo_lot_balance_mismatch": _R(ErrorCode.INTEGRITY_CONFLICT, "promo_lot_balance_mismatch"),
    "promo_flag_enable_refused": _R(ErrorCode.PRODUCTION_INVARIANTS_FAILED, "gate_failed"),
    "promo_reinstate_invalid": _R(ErrorCode.INVALID_STATE_TRANSITION, "promo_reinstate_invalid"),  # 0086
    "promo_booking_terms_mismatch": _R(ErrorCode.INTEGRITY_CONFLICT, "promo_booking_terms_mismatch"),  # 0087
}

# Existing (wave 1-2) trigger messages without a constraint name; matched with ``str.startswith``.
MESSAGE_PREFIX_RULES: tuple[tuple[str, DbErrorRule], ...] = (
    ("feature_flag_values: enabling", _R(ErrorCode.PRODUCTION_INVARIANTS_FAILED, "gate_failed")),  # 0053, Q56
    ("booking agreement snapshot is immutable", _R(ErrorCode.INTEGRITY_CONFLICT, "booking_snapshot_frozen")),  # 0048
    ("LEDGER_SOURCE_INVALID", _R(ErrorCode.SERVER_ERROR, "ledger_source_invalid")),  # 0052, Q55
    ("platform_environment:", _R(ErrorCode.SERVER_ERROR, "environment_marker_guard")),  # 0042/0047/0052
)

SQLSTATE_RULES: dict[str, DbErrorRule] = {
    "23505": _R(ErrorCode.INTEGRITY_CONFLICT, "unique_violation"),
    "23P01": _R(ErrorCode.INTEGRITY_CONFLICT, "exclusion_violation"),
    "23503": _R(ErrorCode.INTEGRITY_CONFLICT, "foreign_key_violation"),
    "23514": _R(ErrorCode.INTEGRITY_CONFLICT, "check_violation"),
    "23001": _R(ErrorCode.INTEGRITY_CONFLICT, "restrict_violation"),
    "23502": _R(ErrorCode.SERVER_ERROR, "not_null_violation"),
    "40001": _R(ErrorCode.SERVICE_UNAVAILABLE, "db_contention"),
    "40P01": _R(ErrorCode.SERVICE_UNAVAILABLE, "db_contention"),
    "55P03": _R(ErrorCode.SERVICE_UNAVAILABLE, "lock_not_available"),
    "57014": _R(ErrorCode.SERVICE_UNAVAILABLE, "statement_timeout"),
    "42501": _R(ErrorCode.SERVER_ERROR, "insufficient_privilege"),
}

SQLSTATE_CLASS_RULES: dict[str, DbErrorRule] = {
    "08": _R(ErrorCode.SERVICE_UNAVAILABLE, "database_unavailable"),  # connection exception
    "53": _R(ErrorCode.SERVICE_UNAVAILABLE, "database_unavailable"),  # insufficient resources
    "57": _R(ErrorCode.SERVICE_UNAVAILABLE, "database_unavailable"),  # operator intervention (shutdown)
}

DEFAULT_DB_ERROR_RULE = _R(ErrorCode.SERVER_ERROR, "database_error")
CONNECTION_LOST_RULE = _R(ErrorCode.SERVICE_UNAVAILABLE, "database_unavailable")


def map_db_error(
    *, sqlstate: str | None, constraint: str | None = None, message: str | None = None, connection_lost: bool = False
) -> DbErrorRule:
    """Resolve the envelope rule for a DB error (precedence: constraint, message, SQLSTATE, class, default)."""
    if constraint and constraint in CONSTRAINT_RULES:
        return CONSTRAINT_RULES[constraint]
    if message:
        for prefix, rule in MESSAGE_PREFIX_RULES:
            if message.startswith(prefix):
                return rule
    if sqlstate:
        if sqlstate in SQLSTATE_RULES:
            return SQLSTATE_RULES[sqlstate]
        if sqlstate[:2] in SQLSTATE_CLASS_RULES:
            return SQLSTATE_CLASS_RULES[sqlstate[:2]]
    if connection_lost:
        return CONNECTION_LOST_RULE
    return DEFAULT_DB_ERROR_RULE
