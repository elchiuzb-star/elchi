from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from app.models import Order, SystemSetting, User
from app.schemas.system_settings import DriverCommissionUpdate
from app.services.audit_service import write_audit_log

DRIVER_COMMISSION_KEY = "driver_commission_rate"
DEFAULT_DRIVER_COMMISSION_RATE = Decimal("0.15")
RATE_QUANT = Decimal("0.0001")
MONEY_QUANT = Decimal("0.01")


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


def get_driver_commission_rate(db: Session) -> Decimal:
    setting = db.get(SystemSetting, DRIVER_COMMISSION_KEY)
    if setting is None:
        return DEFAULT_DRIVER_COMMISSION_RATE
    try:
        return quantize_rate(_decimal(setting.value))
    except Exception:
        return DEFAULT_DRIVER_COMMISSION_RATE


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
    rate = get_driver_commission_rate(db)
    return {
        "driver_commission_rate": rate,
        "driver_commission_percent": rate_to_percent(rate),
        "is_default": setting is None,
        "updated_at": setting.updated_at if setting else None,
        "updated_by_user_id": setting.updated_by_user_id if setting else None,
    }


def update_driver_commission(db: Session, user: User, payload: DriverCommissionUpdate) -> dict[str, Any]:
    old_data = finance_settings_to_dict(db)
    rate = percent_to_rate(payload.driver_commission_percent)
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
