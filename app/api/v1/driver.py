from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import City, District, User
from app.schemas.bid import BidCreate, BidUpdate, OrderReject
from app.schemas.driver_order import DriverOrderCancel
from app.schemas.driver import (
    DriverAvailabilityUpdate,
    DriverDocumentCreate,
    DriverProfileUpdate,
    DriverRouteCreate,
    DriverRouteStatusUpdate,
)
from app.services.driver_order_service import (
    MAX_BID_PRICE_UPDATES,
    cancel_assigned_order_by_driver,
    create_bid,
    get_driver_order_detail,
    get_driver_profile_for_user,
    list_assigned_driver_orders,
    list_driver_feed,
    mark_driver_order_status,
    reject_order,
    update_bid,
)
from app.services.driver_service import (
    disable_driver_route,
    document_to_dict,
    get_or_create_driver_profile,
    list_driver_routes,
    profile_to_dict,
    profile_update_dict,
    route_to_dict,
    submit_driver_document,
    update_availability,
    update_driver_profile,
    update_driver_route,
    create_driver_route,
    update_route_status,
)
from app.utils.api_response import error_response

router = APIRouter(prefix="/driver")
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_driver(
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
    if user.role != "driver":
        return error_response(403, "FORBIDDEN", "Driver role required")
    return user


@router.get("/orders/feed", response_model=None)
def get_driver_order_feed(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    result = list_driver_feed(db, profile, page, limit, status, from_city_id, to_city_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.get("/orders", response_model=None)
def get_driver_assigned_orders(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    result = list_assigned_driver_orders(db, profile, page, limit, status)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.get("/orders/{order_id}", response_model=None)
def get_driver_order(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    result = get_driver_order_detail(db, profile, order_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.post("/orders/{order_id}/bids", response_model=None)
def post_driver_bid(
    order_id: int,
    payload: BidCreate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    bid = create_bid(db, current_user, profile, order_id, payload)
    if isinstance(bid, JSONResponse):
        return bid
    return {
        "success": True,
        "data": {
            "bid_id": bid.id,
            "order_id": bid.order_id,
            "price": bid.price,
            "status": bid.status,
            "created_at": bid.created_at,
            "price_update_count": bid.price_update_count,
            "price_updates_left": max(0, MAX_BID_PRICE_UPDATES - bid.price_update_count),
        },
        "message": "Bid created",
    }


@router.patch("/bids/{bid_id}", response_model=None)
def patch_driver_bid(
    bid_id: int,
    payload: BidUpdate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    bid = update_bid(db, current_user, profile, bid_id, payload)
    if isinstance(bid, JSONResponse):
        return bid
    return {
        "success": True,
        "data": {
            "bid_id": bid.id,
            "price": bid.price,
            "status": bid.status,
            "updated_at": bid.updated_at,
            "price_update_count": bid.price_update_count,
            "price_updates_left": max(0, MAX_BID_PRICE_UPDATES - bid.price_update_count),
        },
        "message": "Bid updated",
    }


@router.post("/orders/{order_id}/reject", response_model=None)
def post_driver_order_reject(
    order_id: int,
    payload: OrderReject,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    result = reject_order(db, current_user, profile, order_id, payload)
    return result


@router.post("/orders/{order_id}/picked-up", response_model=None)
def post_driver_order_picked_up(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    return mark_driver_order_status(db, current_user, profile, order_id, "picked_up")


@router.post("/orders/{order_id}/in-transit", response_model=None)
def post_driver_order_in_transit(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    return mark_driver_order_status(db, current_user, profile, order_id, "in_transit")


@router.post("/orders/{order_id}/delivered", response_model=None)
def post_driver_order_delivered(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    return mark_driver_order_status(db, current_user, profile, order_id, "delivered")


@router.post("/orders/{order_id}/cancel", response_model=None)
def post_driver_order_cancel(
    order_id: int,
    payload: DriverOrderCancel,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_driver_profile_for_user(db, current_user)
    if isinstance(profile, JSONResponse):
        return profile
    return cancel_assigned_order_by_driver(db, current_user, profile, order_id, payload)


@router.get("/profile", response_model=None)
def get_driver_profile(
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    return {"success": True, "data": profile_to_dict(profile, current_user), "message": "OK"}


@router.patch("/profile", response_model=None)
def patch_driver_profile(
    payload: DriverProfileUpdate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    updated = update_driver_profile(db, current_user, profile, payload)
    if isinstance(updated, JSONResponse):
        return updated
    return {"success": True, "data": profile_update_dict(updated), "message": "Driver profile updated"}


@router.post("/documents", response_model=None)
def submit_document(
    payload: DriverDocumentCreate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    document = submit_driver_document(db, current_user, profile, payload)
    if isinstance(document, JSONResponse):
        return document
    return {"success": True, "data": document_to_dict(document), "message": "Document submitted"}


@router.patch("/availability", response_model=None)
def patch_availability(
    payload: DriverAvailabilityUpdate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    updated = update_availability(db, current_user, profile, payload)
    if isinstance(updated, JSONResponse):
        return updated
    return {"success": True, "data": {"is_available": updated.is_available}, "message": "Availability updated"}


@router.post("/routes", response_model=None)
def post_driver_route(
    payload: DriverRouteCreate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    route = create_driver_route(db, current_user, profile, payload)
    if isinstance(route, JSONResponse):
        return route
    from_city = db.get(City, route.from_city_id)
    to_city = db.get(City, route.to_city_id)
    from_district = db.get(District, route.from_district_id) if route.from_district_id else None
    to_district = db.get(District, route.to_district_id) if route.to_district_id else None
    return {"success": True, "data": route_to_dict(route, from_city, to_city, from_district, to_district), "message": "Driver route created"}


@router.get("/routes", response_model=None)
def get_driver_routes(
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    routes = list_driver_routes(db, profile, status, page, limit)
    if isinstance(routes, JSONResponse):
        return routes
    data = []
    for route in routes:
        data.append(
            route_to_dict(
                route,
                db.get(City, route.from_city_id),
                db.get(City, route.to_city_id),
                db.get(District, route.from_district_id) if route.from_district_id else None,
                db.get(District, route.to_district_id) if route.to_district_id else None,
            )
        )
    return {"success": True, "data": data, "message": "OK"}


@router.patch("/routes/{route_id}/status", response_model=None)
def patch_route_status(
    route_id: int,
    payload: DriverRouteStatusUpdate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    route = update_route_status(db, current_user, profile, route_id, payload)
    if isinstance(route, JSONResponse):
        return route
    return {"success": True, "data": {"route_id": route.id, "status": route.status}, "message": "Route status updated"}


@router.patch("/routes/{route_id}", response_model=None)
def patch_driver_route(
    route_id: int,
    payload: DriverRouteCreate,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    route = update_driver_route(db, current_user, profile, route_id, payload)
    if isinstance(route, JSONResponse):
        return route
    from_city = db.get(City, route.from_city_id)
    to_city = db.get(City, route.to_city_id)
    from_district = db.get(District, route.from_district_id) if route.from_district_id else None
    to_district = db.get(District, route.to_district_id) if route.to_district_id else None
    return {"success": True, "data": route_to_dict(route, from_city, to_city, from_district, to_district), "message": "Driver route updated"}


@router.delete("/routes/{route_id}", response_model=None)
def delete_route(
    route_id: int,
    current_user: User | JSONResponse = Depends(get_current_driver),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_driver_profile(db, current_user)
    deleted = disable_driver_route(db, current_user, profile, route_id)
    if isinstance(deleted, JSONResponse):
        return deleted
    return {"success": True, "data": {"route_id": deleted, "status": "deleted"}, "message": "Route deleted"}
