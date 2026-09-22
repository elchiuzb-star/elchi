"""Unit tests for feature-flag rules (ADR-0008; Q1, Q4, Q5; AC38 core)."""

from __future__ import annotations

import pytest

from app.contracts.enums import (
    PRODUCTION_FLAG_DEFAULTS,
    STAFF_ROLE_CAPABILITIES,
    Capability,
    FeatureFlagKey,
    FlagScopeType,
    Role,
)
from app.contracts.errors import DomainError, ErrorCode
from app.modules.geo.flags import (
    FlagRow,
    FlagScopeContext,
    authorize_flag_change,
    resolve_flag,
    validate_scope_ref,
)

P = FeatureFlagKey.PASSENGER_ENABLED
W = FeatureFlagKey.WALLET_REQUIRED
COR = "cor_" + "a" * 26
CTX = FlagScopeContext(corridor_ref=COR, region_refs=("UZ-TK", "UZ-QA"), cohort_refs=("internal-testers",))


def row(scope: FlagScopeType, ref: str, enabled: bool, key: FeatureFlagKey = P) -> FlagRow:
    return FlagRow(key, scope, ref, enabled)


def test_no_rows_uses_production_defaults_everywhere() -> None:
    for key, default in PRODUCTION_FLAG_DEFAULTS.items():
        for production in (True, False):
            assert resolve_flag(key, [], CTX, production=production).enabled is default
    # Q5: every new service is off by default.
    assert not any(PRODUCTION_FLAG_DEFAULTS[k] for k in FeatureFlagKey if k is not W)


@pytest.mark.parametrize(
    ("rows", "expected", "source"),
    [
        ([row(FlagScopeType.COUNTRY, "UZ", True)], True, FlagScopeType.COUNTRY),
        ([row(FlagScopeType.COUNTRY, "UZ", True), row(FlagScopeType.REGION, "UZ-TK", False)], False, FlagScopeType.REGION),
        ([row(FlagScopeType.REGION, "UZ-TK", False), row(FlagScopeType.CORRIDOR, COR, True)], True, FlagScopeType.CORRIDOR),
        ([row(FlagScopeType.CORRIDOR, COR, True), row(FlagScopeType.COHORT, "internal-testers", False)], False, FlagScopeType.COHORT),
        (
            [
                row(FlagScopeType.COUNTRY, "UZ", False),
                row(FlagScopeType.REGION, "UZ-QA", False),
                row(FlagScopeType.CORRIDOR, COR, False),
                row(FlagScopeType.COHORT, "internal-testers", True),
            ],
            True,
            FlagScopeType.COHORT,
        ),
    ],
)
def test_scope_precedence_cohort_over_corridor_over_region_over_country(rows, expected, source) -> None:  # noqa: ANN001
    resolution = resolve_flag(P, rows, CTX, production=False)
    assert resolution.enabled is expected and resolution.source_scope_type is source


def test_rows_for_other_scopes_and_keys_are_ignored() -> None:
    rows = [
        row(FlagScopeType.CORRIDOR, "cor_" + "b" * 26, True),
        row(FlagScopeType.COHORT, "someone-else", True),
        row(FlagScopeType.REGION, "UZ-SA", True),
        row(FlagScopeType.COUNTRY, "UZ", True, key=FeatureFlagKey.PARCEL_ENABLED),
    ]
    assert resolve_flag(P, rows, CTX, production=False).enabled is False


def test_conflicting_rows_on_one_level_resolve_to_safe_default() -> None:
    rows = [row(FlagScopeType.REGION, "UZ-TK", True), row(FlagScopeType.REGION, "UZ-QA", False)]
    assert resolve_flag(P, rows, CTX, production=False).enabled is False
    wallet_rows = [row(FlagScopeType.REGION, "UZ-TK", True, key=W), row(FlagScopeType.REGION, "UZ-QA", False, key=W)]
    assert resolve_flag(W, wallet_rows, CTX, production=False).enabled is True


def test_q1_wallet_required_locked_true_in_production_even_with_false_rows() -> None:
    rows = [row(FlagScopeType.COHORT, "internal-testers", False, key=W), row(FlagScopeType.COUNTRY, "UZ", False, key=W)]
    locked = resolve_flag(W, rows, CTX, production=True)
    assert locked.enabled is True and locked.locked
    assert resolve_flag(W, rows, CTX, production=False).enabled is False  # non-production seed may relax it


ADMIN = STAFF_ROLE_CAPABILITIES[Role.ADMIN]
SUPER = STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
OPERATOR = STAFF_ROLE_CAPABILITIES[Role.OPERATOR]


def _code(fn) -> ErrorCode | None:  # noqa: ANN001
    try:
        fn()
    except DomainError as exc:
        return exc.code
    return None


def test_q1_writing_wallet_required_false_in_production_is_locked() -> None:
    call = lambda: authorize_flag_change(W, enabled=False, approval_reference="X", actor_capabilities=SUPER, actor_is_super_admin=True, production=True)  # noqa: E731
    assert _code(call) is ErrorCode.FLAG_LOCKED_IN_ENVIRONMENT
    assert _code(lambda: authorize_flag_change(W, enabled=True, approval_reference=None, actor_capabilities=ADMIN, actor_is_super_admin=False, production=True)) is None
    assert _code(lambda: authorize_flag_change(W, enabled=False, approval_reference=None, actor_capabilities=ADMIN, actor_is_super_admin=False, production=False)) is None


@pytest.mark.parametrize("key", [FeatureFlagKey.PASSENGER_ENABLED, FeatureFlagKey.CARD_PAYMENTS_ENABLED])
def test_q5_enabling_passenger_or_card_in_production_needs_super_admin_and_reference(key: FeatureFlagKey) -> None:
    assert _code(lambda: authorize_flag_change(key, enabled=True, approval_reference="LEGAL-7", actor_capabilities=ADMIN, actor_is_super_admin=False, production=True)) is ErrorCode.FORBIDDEN
    assert _code(lambda: authorize_flag_change(key, enabled=True, approval_reference="  ", actor_capabilities=SUPER, actor_is_super_admin=True, production=True)) is ErrorCode.APPROVAL_REFERENCE_REQUIRED
    assert _code(lambda: authorize_flag_change(key, enabled=True, approval_reference=None, actor_capabilities=SUPER, actor_is_super_admin=True, production=True)) is ErrorCode.APPROVAL_REFERENCE_REQUIRED
    assert _code(lambda: authorize_flag_change(key, enabled=True, approval_reference="LEGAL-7", actor_capabilities=SUPER, actor_is_super_admin=True, production=True)) is None
    # Turning it off is always allowed to admin+; outside production no approval needed.
    assert _code(lambda: authorize_flag_change(key, enabled=False, approval_reference=None, actor_capabilities=ADMIN, actor_is_super_admin=False, production=True)) is None
    assert _code(lambda: authorize_flag_change(key, enabled=True, approval_reference=None, actor_capabilities=ADMIN, actor_is_super_admin=False, production=False)) is None


def test_other_flags_need_feature_flag_manage_capability() -> None:
    parcel = FeatureFlagKey.PARCEL_ENABLED
    assert Capability.OPS_FEATURE_FLAG_MANAGE not in OPERATOR
    assert _code(lambda: authorize_flag_change(parcel, enabled=True, approval_reference=None, actor_capabilities=OPERATOR, actor_is_super_admin=False, production=True)) is ErrorCode.FORBIDDEN
    assert _code(lambda: authorize_flag_change(parcel, enabled=True, approval_reference=None, actor_capabilities=ADMIN, actor_is_super_admin=False, production=True)) is None


def test_q4_no_legacy_write_kill_switch_flag() -> None:
    assert not any("legacy" in key.value or "v1" in key.value for key in FeatureFlagKey)


@pytest.mark.parametrize(
    ("scope", "ref", "ok"),
    [
        (FlagScopeType.COUNTRY, "UZ", True),
        (FlagScopeType.COUNTRY, "KZ", False),
        (FlagScopeType.REGION, "UZ-QA", True),
        (FlagScopeType.REGION, "qashqadaryo", False),
        (FlagScopeType.COHORT, "internal-testers", True),
        (FlagScopeType.COHORT, "Bad Cohort", False),
        (FlagScopeType.CORRIDOR, COR, True),
        (FlagScopeType.CORRIDOR, "42", False),
    ],
)
def test_scope_ref_validation(scope: FlagScopeType, ref: str, ok: bool) -> None:
    assert (_code(lambda: validate_scope_ref(scope, ref)) is None) is ok
