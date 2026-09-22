"""v1 finance settings, adapted to versioned commission policies (A3, ADR-0009 §9, Q1/Q2).

* GET shape is unchanged. The rate comes from the current global standard policy
  (``commission_policies``); ``system_settings`` is only the fallback where the v2 table
  does not exist (legacy SQLite suite) and stays mirrored on PATCH.
* PATCH requires ``finance.commission_policy_manage`` (super_admin only); admin gets v1
  ``403 FORBIDDEN``. 0% is rejected with v1 ``400 VALIDATION_ERROR`` (0% only as a campaign).
  A valid PATCH ends the current global standard at now and starts a new one.
* v1 order snapshots (``orders.system_fee_rate``) are untouched; the legacy fee never
  enters the ledger (§18.2).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.contracts.enums import STAFF_ROLE_CAPABILITIES, Capability, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import legacy_rate_to_bps
from app.models import Order, SystemSetting, User
from app.schemas.system_settings import DriverCommissionUpdate
from app.services.audit_service import write_audit_log

DRIVER_COMMISSION_KEY = "driver_commission_rate"
DEFAULT_DRIVER_COMMISSION_RATE = Decimal("0.15")
RATE_QUANT = Decimal("0.0001")
MONEY_QUANT = Decimal("0.01")
V1_PATCH_REASON = "v1 PATCH /api/v1/admin/settings/driver-commission"


def _decimal(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value))


def quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def percent_to_rate(percent: Decimal) -> Decimal:
    return quantize_rate(_decimal(percent) / Decimal("100"))


def rate_to_percent(rate: Decimal) -> Decimal:
    return (_decimal(rate) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bps_to_rate(fee_bps: int) -> Decimal:
    return quantize_rate(Decimal(fee_bps) / Decimal(10000))


def user_capabilities(user: User) -> frozenset[Capability]:
    try:
        return STAFF_ROLE_CAPABILITIES.get(Role(user.role), frozenset())
    except ValueError:
        return frozenset()


def _policies_available(db: Session) -> bool:
    from app.modules.platform.service import table_exists

    return table_exists(db, "commission_policies")


def _current_global_standard(db: Session):
    if not _policies_available(db):
        return None
    from app.modules.wallet.service import current_global_standard

    return current_global_standard(db)


def _legacy_setting_rate(setting: SystemSetting | None) -> Decimal:
    if setting is None:
        return DEFAULT_DRIVER_COMMISSION_RATE
    try:
        return quantize_rate(_decimal(setting.value))
    except Exception:
        return DEFAULT_DRIVER_COMMISSION_RATE


def get_driver_commission_rate(db: Session) -> Decimal:
    policy = _current_global_standard(db)
    if policy is not None:
        return bps_to_rate(policy.fee_bps)
    return _legacy_setting_rate(db.get(SystemSetting, DRIVER_COMMISSION_KEY))


def calculate_order_income(final_price: Decimal, rate: Decimal) -> dict[str, Decimal]:
    gross_income = quantize_money(_decimal(final_price))
    fee_rate = quantize_rate(_decimal(rate))
    system_fee = quantize_money(gross_income * fee_rate)
    return {
        "gross_income": gross_income,
        "system_fee_rate": fee_rate,
        "system_fee": system_fee,
        "driver_income": quantize_money(gross_income - system_fee),
    }


def apply_order_commission(db: Session, order: Order) -> dict[str, Decimal] | None:
    if order.final_price is None:
        order.system_fee_rate = None
        order.system_fee = None
        order.driver_income = None
        return None
    income = calculate_order_income(order.final_price, get_driver_commission_rate(db))
    order.system_fee_rate = income["system_fee_rate"]
    order.system_fee = income["system_fee"]
    order.driver_income = income["driver_income"]
    return income


def finance_settings_to_dict(db: Session) -> dict[str, Any]:
    setting = db.get(SystemSetting, DRIVER_COMMISSION_KEY)
    policy = _current_global_standard(db)
    if policy is not None:
        rate = bps_to_rate(policy.fee_bps)
        changed_by_staff = policy.created_by is not None
        return {
            "driver_commission_rate": rate,
            "driver_commission_percent": rate_to_percent(rate),
            # The migration seed (created_by NULL) mirrors the legacy row or the 15% default.
            "is_default": setting is None and not changed_by_staff,
            "updated_at": policy.created_at if changed_by_staff else (setting.updated_at if setting else None),
            "updated_by_user_id": policy.created_by if changed_by_staff else (setting.updated_by_user_id if setting else None),
        }
    rate = _legacy_setting_rate(setting)
    return {
        "driver_commission_rate": rate,
        "driver_commission_percent": rate_to_percent(rate),
        "is_default": setting is None,
        "updated_at": setting.updated_at if setting else None,
        "updated_by_user_id": setting.updated_by_user_id if setting else None,
    }


_V1_STATUS_FOR_DOMAIN = {
    ErrorCode.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
}


def update_driver_commission(db: Session, user: User, payload: DriverCommissionUpdate) -> dict[str, Any]:
    capabilities = user_capabilities(user)
    if Capability.FINANCE_COMMISSION_POLICY_MANAGE not in capabilities:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    rate = percent_to_rate(payload.driver_commission_percent)
    fee_bps = legacy_rate_to_bps(rate)
    if fee_bps == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="0% commission is only allowed as a time-boxed campaign policy.",
        )
    old_data = finance_settings_to_dict(db)
    if _policies_available(db):
        from app.modules.wallet.service import replace_global_standard

        try:
            replace_global_standard(
                db,
                actor_user_id=user.id,
                actor_capabilities=capabilities,
                fee_bps=fee_bps,
                reason=V1_PATCH_REASON,
            )
        except DomainError as exc:
            db.rollback()
            # v1 knows only 400/401/403/404 codes; conflicts are reported as validation errors.
            raise HTTPException(
                status_code=_V1_STATUS_FOR_DOMAIN.get(exc.code, status.HTTP_400_BAD_REQUEST),
                detail=exc.message,
            ) from exc
    setting = db.get(SystemSetting, DRIVER_COMMISSION_KEY)
    if setting is None:
        setting = SystemSetting(
            key=DRIVER_COMMISSION_KEY,
            value=str(rate),
            description="Driverlardan olinadigan tizim solig'i foizi",
            updated_by_user_id=user.id,
        )
    else:
        setting.value = str(rate)
        setting.updated_by_user_id = user.id
    db.add(setting)
    db.flush()
    new_data = finance_settings_to_dict(db)
    write_audit_log(
        db,
        user,
        "system_settings",
        0,
        "driver_commission_updated",
        old_value=old_data,
        new_value=new_data,
        reason="admin_updated_driver_commission",
    )
    db.commit()
    return new_data
