"""Parcel size catalog (ADR-0026, Q140). The client picks a category instead of typing dimensions and weight.

A category is a server-side row with a user-facing name, an icon key, max dimensions, max weight and max volume. The
same rows feed the client form, the driver's view before proposing and the capacity check: a request with a category
demands the category's **max** weight and volume from the trip's segment capacity (worst case for the category), so the
existing capacity engine (``proposal_versions.cargo_*`` → ``booking_allocations`` → segment counters) is unchanged.

Versioned like the parcel policy (0070): a draft is staff-only; ``active`` needs a *second* super_admin; one version is
active at a time. An agreement points at the immutable item row, so a later catalog edit (a new version) never changes
an existing agreement. ``synthetic`` catalogs carry demo/test values: they are never confirmable in production and no
real limit is invented anywhere in code - production fails closed (no confirmed catalog = no new parcel business).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import Capability
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.marketplace import (
    PARCEL_PILOT_MAX_DIMENSION_CM,
    PARCEL_PILOT_MAX_VOLUME_ML,
    PARCEL_PILOT_MAX_WEIGHT_G,
)
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.identity import service as identity_service
from app.modules.marketplace.models import ParcelCategoryItem, ParcelCategoryVersion

DRAFT, ACTIVE, SUPERSEDED = "draft", "active", "superseded"


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def item_public_id(item: ParcelCategoryItem) -> str:
    return format_public_id(PublicIdPrefix.PARCEL_CATEGORY, item.public_id)


def version_public_id(version: ParcelCategoryVersion) -> str:
    return format_public_id(PublicIdPrefix.PARCEL_CATEGORY_VERSION, version.public_id)


@dataclass(frozen=True, slots=True)
class CatalogView:
    version: ParcelCategoryVersion | None
    items: list[ParcelCategoryItem]

    @property
    def confirmed(self) -> bool:
        return self.version is not None


def items_of(session: Session, version_id: int) -> list[ParcelCategoryItem]:
    return list(session.execute(
        select(ParcelCategoryItem).where(ParcelCategoryItem.catalog_version_id == version_id)
        .order_by(ParcelCategoryItem.display_order, ParcelCategoryItem.id)
    ).scalars())


def active_catalog(session: Session) -> CatalogView:
    version = session.execute(select(ParcelCategoryVersion).where(ParcelCategoryVersion.status == ACTIVE)).scalar_one_or_none()
    return CatalogView(version, items_of(session, version.id) if version is not None else [])


def get_item(session: Session, item_id: int) -> ParcelCategoryItem:
    item = session.get(ParcelCategoryItem, item_id)
    if item is None:  # pragma: no cover - FK
        raise DomainError(ErrorCode.NOT_FOUND)
    return item


def resolve_active_item(session: Session, category_public_id: str) -> ParcelCategoryItem:
    """A category a client may pick *now*: it must belong to the active catalog version (an old version's item is only
    ever read through an existing agreement)."""
    value = parse_public_id(category_public_id, PublicIdPrefix.PARCEL_CATEGORY)
    item = session.execute(
        select(ParcelCategoryItem).join(ParcelCategoryVersion, ParcelCategoryVersion.id == ParcelCategoryItem.catalog_version_id)
        .where(ParcelCategoryItem.public_id == value, ParcelCategoryVersion.status == ACTIVE)
    ).scalar_one_or_none()
    if item is None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel.category_id", "reason": "not_in_active_catalog"})
    return item


def assert_catalog_ready(session: Session) -> None:
    """Fail-closed gate for **new** parcel business in production (same shape as the parcel policy, §5.2).

    Production needs a confirmed, non-synthetic catalog; outside production a synthetic one is enough for development.
    Never called on an existing booking's path - an accepted parcel finishes on the category it was agreed on.
    """
    from app.modules.platform import service as platform_service

    view = active_catalog(session)
    if platform_service.is_production(session):
        if view.version is None or view.version.synthetic:
            raise DomainError(ErrorCode.PARCEL_CATALOG_UNCONFIRMED, details={"reason": "parcel_catalog_unconfirmed"})


def item_dto(item: ParcelCategoryItem) -> dict[str, Any]:
    return {
        "id": item_public_id(item), "code": item.code, "name_uz": item.name_uz, "name_ru": item.name_ru,
        "icon_key": item.icon_key, "max_length_cm": item.max_length_cm, "max_width_cm": item.max_width_cm,
        "max_height_cm": item.max_height_cm, "max_weight_g": item.max_weight_g, "max_volume_ml": item.max_volume_ml,
    }


def _validate_item(item: Any) -> None:
    over: dict[str, int] = {}
    if item.max_weight_g > PARCEL_PILOT_MAX_WEIGHT_G:
        over["max_weight_g"] = PARCEL_PILOT_MAX_WEIGHT_G
    if max(item.max_length_cm, item.max_width_cm, item.max_height_cm) > PARCEL_PILOT_MAX_DIMENSION_CM:
        over["max_dimension_cm"] = PARCEL_PILOT_MAX_DIMENSION_CM
    if item.max_volume_ml > PARCEL_PILOT_MAX_VOLUME_ML:
        over["max_volume_ml"] = PARCEL_PILOT_MAX_VOLUME_ML
    if item.max_volume_ml > item.max_length_cm * item.max_width_cm * item.max_height_cm:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": f"items.{item.code}.max_volume_ml",
                                                               "reason": "volume_exceeds_box"})
    if over:
        # a category may never promise more than the pilot carries (§5.2); the answer is a refusal, never a silent cut
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "pilot_parcel_limit", "code": item.code, "limits": over})


def create_version(
    session: Session, *, actor_user_id: int, label: str, source_note: str | None, synthetic: bool, items: Sequence[Any],
    now: datetime | None = None,
) -> ParcelCategoryVersion:
    """Draft a catalog version (``platform.policy_manage`` = super_admin, MFA step-up). A draft applies to nobody."""
    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.PLATFORM_POLICY_MANAGE,
        session=session,
    )
    if not items:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "items", "reason": "empty_catalog"})
    codes = [item.code for item in items]
    if len(set(codes)) != len(codes):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "items", "reason": "duplicate_code"})
    for item in items:
        _validate_item(item)
    version = ParcelCategoryVersion(public_id=new_public_uuid(), label=label.strip(), status=DRAFT, synthetic=synthetic,
                                    source_note=source_note, created_by=actor_user_id, created_at=now, updated_at=now,
                                    version=1)
    session.add(version)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if "uq_parcel_category_versions_label" in str(exc.orig):
            raise DomainError(ErrorCode.INTEGRITY_CONFLICT, details={"field": "label", "reason": "label_exists"}) from None
        raise
    for order, item in enumerate(items, start=1):
        session.add(ParcelCategoryItem(
            public_id=new_public_uuid(), catalog_version_id=version.id, code=item.code, name_uz=item.name_uz,
            name_ru=item.name_ru, icon_key=item.icon_key, max_length_cm=item.max_length_cm, max_width_cm=item.max_width_cm,
            max_height_cm=item.max_height_cm, max_weight_g=item.max_weight_g, max_volume_ml=item.max_volume_ml,
            display_order=item.display_order or order * 10, created_at=now,
        ))
    session.flush()
    _audit(session, actor_user_id, "parcel_catalog_version_created", {
        "version_id": version_public_id(version), "label": version.label, "synthetic": synthetic,
        "item_codes": [item.code for item in items], "source_note": source_note})
    return version


def confirm_version(
    session: Session, *, actor_user_id: int, version_public_id_value: str, expected_version: int, now: datetime | None = None,
) -> ParcelCategoryVersion:
    """Activate a draft (``platform.policy_manage``). The previous active version is superseded - its items stay, so
    every agreement made on them keeps its category. No second approver: the size catalog is not the prohibited-items
    policy and no approved rule asks for two people here (0094); who activated what is in the audit log. A synthetic
    version is never activated in production."""
    from app.modules.platform import service as platform_service

    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.PLATFORM_POLICY_MANAGE,
        session=session,
    )
    value = parse_public_id(version_public_id_value, PublicIdPrefix.PARCEL_CATEGORY_VERSION)
    version = session.execute(
        select(ParcelCategoryVersion).where(ParcelCategoryVersion.public_id == value).with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if version.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": version.version})
    if version.status != DRAFT:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "parcel_catalog", "status": version.status})
    if version.synthetic and platform_service.is_production(session):
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "synthetic_catalog_not_for_production"})
    current = session.execute(
        select(ParcelCategoryVersion).where(ParcelCategoryVersion.status == ACTIVE).with_for_update()
    ).scalar_one_or_none()
    if current is not None:
        current.status, current.updated_at, current.version = SUPERSEDED, now, current.version + 1
        session.flush()
    version.status, version.confirmed_by, version.confirmed_at, version.effective_from = ACTIVE, actor_user_id, now, now
    version.updated_at, version.version = now, version.version + 1
    session.flush()
    _audit(session, actor_user_id, "parcel_catalog_version_activated", {
        "version_id": version_public_id(version), "label": version.label, "synthetic": version.synthetic,
        "superseded_version_id": version_public_id(current) if current is not None else None})
    return version


def _audit(session: Session, actor_user_id: int, action: str, details: dict) -> None:
    from app.models import AuditLog

    session.add(AuditLog(actor_id=actor_user_id, entity_type="parcel_catalog", entity_id=None, action=action, details=details))
    session.flush()


def list_versions(session: Session, *, actor_user_id: int, now: datetime | None = None) -> list[ParcelCategoryVersion]:
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=_now(now)), Capability.OPS_VIEW
    )
    return list(session.execute(select(ParcelCategoryVersion).order_by(ParcelCategoryVersion.id.desc())).scalars())
