"""Feature-flag rules without I/O (ADR-0008, decisions Q1, Q4, Q5; spec §20.3).

* Precedence: cohort > corridor > region > country (``FlagScopeType`` order).
* No matching row -> ``PRODUCTION_FLAG_DEFAULTS`` (every environment; non-production
  environments change behaviour only through seeded rows).
* Conflicting rows on the same level (e.g. two cohorts, or origin and destination
  regions) resolve to the flag's production default, i.e. the safe value.
* Production: ``FLAGS_LOCKED_IN_PRODUCTION`` always evaluate to their locked value
  and can't be written with another value (``FLAG_LOCKED_IN_ENVIRONMENT``).
* Production: enabling a flag in ``FLAGS_REQUIRING_APPROVAL_REFERENCE`` needs
  super_admin plus a non-empty approval reference. Disabling never needs it.
* There is no legacy v1 write kill switch (Q4).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.contracts.enums import (
    FLAGS_LOCKED_IN_PRODUCTION,
    FLAGS_REQUIRING_APPROVAL_REFERENCE,
    PRODUCTION_FLAG_DEFAULTS,
    Capability,
    FeatureFlagKey,
    FlagScopeType,
)
from app.contracts.errors import DomainError, ErrorCode

COUNTRY_SCOPE_REF = "UZ"
SCOPE_PRECEDENCE: tuple[FlagScopeType, ...] = (
    FlagScopeType.COHORT,
    FlagScopeType.CORRIDOR,
    FlagScopeType.REGION,
    FlagScopeType.COUNTRY,
)
REGION_CODE_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
COHORT_REF_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
MAX_REASON_LENGTH = 500
MAX_APPROVAL_REFERENCE_LENGTH = 200

# Flags shown to clients by F1 (EffectiveFlagsDTO).
CLIENT_VISIBLE_FLAGS: tuple[FeatureFlagKey, ...] = (
    FeatureFlagKey.PASSENGER_ENABLED,
    FeatureFlagKey.PARCEL_ENABLED,
    FeatureFlagKey.DRIVER_LISTING_ENABLED,
    FeatureFlagKey.TRACKING_ENABLED,
)


@dataclass(frozen=True, slots=True)
class FlagRow:
    flag_key: FeatureFlagKey
    scope_type: FlagScopeType
    scope_ref: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class FlagScopeContext:
    corridor_ref: str | None = None
    region_refs: tuple[str, ...] = ()
    cohort_refs: tuple[str, ...] = ()
    country_ref: str = COUNTRY_SCOPE_REF

    def refs_for(self, scope: FlagScopeType) -> frozenset[str]:
        if scope is FlagScopeType.COHORT:
            return frozenset(self.cohort_refs)
        if scope is FlagScopeType.CORRIDOR:
            return frozenset({self.corridor_ref}) if self.corridor_ref else frozenset()
        if scope is FlagScopeType.REGION:
            return frozenset(self.region_refs)
        return frozenset({self.country_ref})


@dataclass(frozen=True, slots=True)
class FlagResolution:
    flag_key: FeatureFlagKey
    enabled: bool
    source_scope_type: FlagScopeType | None
    source_scope_ref: str | None
    locked: bool = False


def resolve_flag(
    flag_key: FeatureFlagKey,
    rows: Iterable[FlagRow],
    context: FlagScopeContext,
    *,
    production: bool,
) -> FlagResolution:
    key = FeatureFlagKey(flag_key)
    if production and key in FLAGS_LOCKED_IN_PRODUCTION:
        return FlagResolution(key, FLAGS_LOCKED_IN_PRODUCTION[key], None, None, locked=True)
    relevant = [row for row in rows if row.flag_key == key]
    for scope in SCOPE_PRECEDENCE:
        refs = context.refs_for(scope)
        if not refs:
            continue
        matching = sorted((row for row in relevant if row.scope_type == scope and row.scope_ref in refs), key=lambda r: r.scope_ref)
        if not matching:
            continue
        values = {row.enabled for row in matching}
        if len(values) == 1:
            return FlagResolution(key, matching[0].enabled, scope, matching[0].scope_ref)
        return FlagResolution(key, PRODUCTION_FLAG_DEFAULTS[key], scope, None)
    return FlagResolution(key, PRODUCTION_FLAG_DEFAULTS[key], None, None)


def validate_scope_ref(scope_type: FlagScopeType, scope_ref: str) -> str:
    """Syntactic check. Corridor refs are ``cor_…`` public ids (existence checked by the service)."""
    scope = FlagScopeType(scope_type)
    ref = scope_ref.strip() if isinstance(scope_ref, str) else ""
    ok = {
        FlagScopeType.COUNTRY: ref == COUNTRY_SCOPE_REF,
        FlagScopeType.REGION: bool(REGION_CODE_RE.fullmatch(ref)),
        FlagScopeType.COHORT: bool(COHORT_REF_RE.fullmatch(ref)),
        FlagScopeType.CORRIDOR: ref.startswith("cor_") and len(ref) == 30,
    }[scope]
    if not ok:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "scope_ref", "scope_type": scope.value})
    return ref


def normalize_approval_reference(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) > MAX_APPROVAL_REFERENCE_LENGTH:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "approval_reference"})
    return text or None


def authorize_flag_change(
    flag_key: FeatureFlagKey,
    *,
    enabled: bool,
    approval_reference: str | None,
    actor_capabilities: Iterable[Capability],
    actor_is_super_admin: bool,
    production: bool,
) -> None:
    """Raise the contract error for a forbidden flag write (F3)."""
    key = FeatureFlagKey(flag_key)
    if Capability.OPS_FEATURE_FLAG_MANAGE not in frozenset(actor_capabilities):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.OPS_FEATURE_FLAG_MANAGE.value})
    if production and key in FLAGS_LOCKED_IN_PRODUCTION and enabled != FLAGS_LOCKED_IN_PRODUCTION[key]:
        raise DomainError(
            ErrorCode.FLAG_LOCKED_IN_ENVIRONMENT,
            details={"flag_key": key.value, "locked_value": FLAGS_LOCKED_IN_PRODUCTION[key]},
        )
    if production and enabled and key in FLAGS_REQUIRING_APPROVAL_REFERENCE:
        if not actor_is_super_admin:
            raise DomainError(ErrorCode.FORBIDDEN, details={"flag_key": key.value, "required_role": "super_admin"})
        if not normalize_approval_reference(approval_reference):
            raise DomainError(ErrorCode.APPROVAL_REFERENCE_REQUIRED, details={"flag_key": key.value})
