from math import ceil

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_operator_or_admin, require_roles
from app.db.session import get_db
from app.models import ClientProfile, Order, User
from app.services.audit_service import write_audit_log
from app.utils.api_response import error_response

router = APIRouter(prefix="/admin/clients")


def client_to_dict(db: Session, user: User) -> dict:
    profile = user.client_profile
    orders_count = db.scalar(select(func.count(Order.id)).where(Order.client_id == user.id)) or 0
    active_orders_count = db.scalar(
        select(func.count(Order.id)).where(
            Order.client_id == user.id,
            Order.status.in_(["published", "bidding", "accepted", "picked_up", "in_transit", "delivered"]),
        ),
    ) or 0
    completed_orders_count = db.scalar(
        select(func.count(Order.id)).where(Order.client_id == user.id, Order.status == "confirmed"),
    ) or 0
    cancelled_orders_count = db.scalar(
        select(func.count(Order.id)).where(Order.client_id == user.id, Order.status == "cancelled"),
    ) or 0
    last_order_at = db.scalar(select(func.max(Order.created_at)).where(Order.client_id == user.id))
    return {
        "id": user.id,
        "profile_id": profile.id if profile else None,
        "phone": user.phone,
        "full_name": profile.full_name if profile and profile.full_name else user.full_name,
        "role": "client",
        "status": user.status,
        "is_phone_verified": user.is_phone_verified,
        "orders_count": orders_count,
        "active_orders_count": active_orders_count,
        "completed_orders_count": completed_orders_count,
        "cancelled_orders_count": cancelled_orders_count,
        "last_order_at": last_order_at,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@router.get("", response_model=None)
def list_admin_clients(
    search: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    is_phone_verified: bool | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(User).outerjoin(ClientProfile, ClientProfile.user_id == User.id).where(User.role == "client")
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.phone.ilike(q), User.full_name.ilike(q), ClientProfile.full_name.ilike(q)))
    if status_filter:
        stmt = stmt.where(User.status == status_filter)
    if is_phone_verified is not None:
        stmt = stmt.where(User.is_phone_verified == is_phone_verified)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    safe_limit = max(1, min(limit, 100))
    offset = (page - 1) * safe_limit
    users = list(db.scalars(stmt.order_by(User.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "success": True,
        "data": {
            "items": [client_to_dict(db, user) for user in users],
            "pagination": {
                "page": page,
                "limit": safe_limit,
                "total": total,
                "total_pages": ceil(total / safe_limit) if total else 0,
            },
        },
        "message": "OK",
    }


@router.get("/{user_id}", response_model=None)
def get_admin_client(
    user_id: int,
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role != "client":
        return error_response(status.HTTP_404_NOT_FOUND, "CLIENT_NOT_FOUND", "Client not found")
    return {"success": True, "data": client_to_dict(db, user), "message": "OK"}


@router.post("/{user_id}/block", response_model=None)
def block_admin_client(
    user_id: int,
    payload: dict | None = None,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role != "client":
        return error_response(status.HTTP_404_NOT_FOUND, "CLIENT_NOT_FOUND", "Client not found")
    old_status = user.status
    user.status = "blocked"
    db.add(user)
    write_audit_log(
        db,
        current_user,
        "clients",
        user.id,
        "client_blocked",
        old_value={"status": old_status},
        new_value={"status": user.status},
        reason=(payload or {}).get("reason"),
    )
    db.commit()
    db.refresh(user)
    return {"success": True, "data": client_to_dict(db, user), "message": "Client blocked"}


@router.post("/{user_id}/unblock", response_model=None)
def unblock_admin_client(
    user_id: int,
    payload: dict | None = None,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role != "client":
        return error_response(status.HTTP_404_NOT_FOUND, "CLIENT_NOT_FOUND", "Client not found")
    old_status = user.status
    user.status = "active"
    db.add(user)
    write_audit_log(
        db,
        current_user,
        "clients",
        user.id,
        "client_unblocked",
        old_value={"status": old_status},
        new_value={"status": user.status},
        reason=(payload or {}).get("reason"),
    )
    db.commit()
    db.refresh(user)
    return {"success": True, "data": client_to_dict(db, user), "message": "Client unblocked"}
