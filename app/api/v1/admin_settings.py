from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.schemas.system_settings import DriverCommissionUpdate
from app.services.system_settings_service import finance_settings_to_dict, update_driver_commission

router = APIRouter(prefix="/admin/settings")


@router.get("", response_model=None)
def get_admin_settings(
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "data": finance_settings_to_dict(db), "message": "OK"}


@router.patch("/driver-commission", response_model=None)
def update_driver_commission_endpoint(
    payload: DriverCommissionUpdate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "data": update_driver_commission(db, current_user, payload), "message": "OK"}
