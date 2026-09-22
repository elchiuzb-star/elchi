from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.schemas.order import ClientOrderCancel, ClientOrderCreate, ClientOrderRatingCreate, SelectDriverRequest
from app.services.order_service import (
    cancel_order,
    confirm_delivered_order,
    create_order_draft,
    create_order_rating,
    get_owned_order,
    list_order_bids,
    list_client_orders,
    order_detail_to_dict,
    publish_order,
    select_driver_for_order,
    update_order,
)
from app.utils.api_response import error_response
from app.utils.legacy_time import v1_naive

router = APIRouter(prefix="/client/orders")
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | JSONResponse:
    if credentials is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    payload = verify_token(credentials.credentials)
    if payload is None or payload.get("type") != "access" or payload.get("sub") is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    if user.status != "active":
        return error_response(403, "FORBIDDEN", "User account is not active")
    if user.role != "client":
        return error_response(403, "FORBIDDEN", "Client role required")
    return user


@router.post("", response_model=None)
def create_order_endpoint(
    payload: ClientOrderCreate,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    order = create_order_draft(db, current_user, payload)
    if isinstance(order, JSONResponse):
        return order
    message = "Order draft created" if order.suggested_price is not None else "Order draft created without suggested price"
    return {"success": True, "data": order_detail_to_dict(db, order), "message": message}


@router.patch("/{order_id}", response_model=None)
def update_order_endpoint(
    order_id: int,
    payload: ClientOrderCreate,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    order = update_order(db, current_user, order_id, payload)
    if isinstance(order, JSONResponse):
        return order
    return {"success": True, "data": order_detail_to_dict(db, order), "message": "Order updated"}


@router.post("/{order_id}/publish", response_model=None)
def publish_order_endpoint(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    order = publish_order(db, current_user, order_id)
    if isinstance(order, JSONResponse):
        return order
    publish_result = order
    order = publish_result.order
    message = "Order published" if publish_result.matched_drivers_count else "Order published, but no matched drivers found"
    return {
        "success": True,
        "data": {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "matched_drivers_count": publish_result.matched_drivers_count,
        },
        "message": message,
    }


@router.get("", response_model=None)
def get_client_orders(
    status: str | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = list_client_orders(db, current_user, status, from_city_id, to_city_id, page, limit)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "OK"}


@router.post("/{order_id}/select-driver", response_model=None)
def select_driver_endpoint(
    order_id: int,
    payload: SelectDriverRequest,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = select_driver_for_order(db, current_user, order_id, payload)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Driver selected"}


@router.get("/{order_id}/bids", response_model=None)
def get_order_bids_endpoint(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = list_order_bids(db, current_user, order_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.post("/{order_id}/confirm", response_model=None)
def confirm_order_endpoint(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = confirm_delivered_order(db, current_user, order_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Order confirmed"}


@router.post("/{order_id}/rating", response_model=None)
def create_rating_endpoint(
    order_id: int,
    payload: ClientOrderRatingCreate,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    rating = create_order_rating(db, current_user, order_id, payload)
    if isinstance(rating, JSONResponse):
        return rating
    return {
        "success": True,
        "data": {
            "rating_id": rating.id,
            "order_id": rating.order_id,
            "driver_id": rating.driver_id,
            "rating": rating.rating,
            "comment": rating.comment,
            "created_at": rating.created_at,
        },
        "message": "Rating created",
    }


@router.get("/{order_id}", response_model=None)
def get_order_detail_endpoint(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    order = get_owned_order(db, current_user, order_id)
    if isinstance(order, JSONResponse):
        return order
    return {"success": True, "data": order_detail_to_dict(db, order), "message": "OK"}


@router.post("/{order_id}/cancel", response_model=None)
def cancel_order_endpoint(
    order_id: int,
    payload: ClientOrderCancel,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    order = cancel_order(db, current_user, order_id, payload)
    if isinstance(order, JSONResponse):
        return order
    return {
        "success": True,
        "data": {
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "cancel_reason": order.cancel_reason,
            "cancelled_at": v1_naive(order.cancelled_at),
        },
        "message": "Order cancelled",
    }
