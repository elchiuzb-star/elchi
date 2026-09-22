from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_roles
from app.contracts.enums import Capability
from app.db.session import get_db
from app.models import User
from app.schemas.system_settings import DriverCommissionUpdate
from app.services.system_settings_service import finance_settings_to_dict, update_driver_commission, user_capabilities

router = APIRouter(prefix="/admin/settings")


def require_capability(capability: Capability) -> Callable[[User], User]:
    """v1-shaped 403 unless the staff role grants the capability (Q2: policy manage = super_admin)."""

    def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        if capability not in user_capabilities(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return current_user

    return dependency


@router.get("", response_model=None)
def get_admin_settings(
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "data": finance_settings_to_dict(db), "message": "OK"}


@router.patch("/driver-commission", response_model=None)
def update_driver_commission_endpoint(
    payload: DriverCommissionUpdate,
    current_user: User = Depends(require_capability(Capability.FINANCE_COMMISSION_POLICY_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "data": update_driver_commission(db, current_user, payload), "message": "OK"}
