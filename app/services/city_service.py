from decimal import Decimal
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import City, District, RouteTariff, User
from app.services.audit_service import write_audit_log
from app.schemas.city import CityCreate, CityUpdate, RouteTariffCreate, RouteTariffUpdate
from app.schemas.district import DistrictCreate, DistrictUpdate
from app.utils.api_response import error_response


def pagination(page: int = 1, limit: int = 20) -> tuple[int, int]:
    safe_page = max(page, 1)
    safe_limit = min(max(limit, 1), 100)
    return (safe_page - 1) * safe_limit, safe_limit


def pagination_meta(total: int, page: int = 1, limit: int = 20) -> dict[str, int]:
    safe_page = max(page, 1)
    safe_limit = min(max(limit, 1), 100)
    return {
        "page": safe_page,
        "limit": safe_limit,
        "total": total,
        "total_pages": ceil(total / safe_limit) if total else 0,
    }


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def normalize_required_text(value: str) -> str:
    return normalize_text(value) or ""


def city_name_key(value: str) -> str:
    return normalize_required_text(value).casefold()


def datetime_to_str(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def price_to_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def city_ref(city: City | None) -> dict[str, Any] | None:
    if city is None:
        return None
    return {
        "id": city.id,
        "name_uz": city.name_uz,
        "name_ru": city.name_ru,
        "region": city.region,
        "type": city.type,
        "requires_district": city.requires_district,
        "display_order": city.display_order,
    }


def city_to_dict(city: City) -> dict[str, Any]:
    return {
        "id": city.id,
        "name_uz": city.name_uz,
        "name_ru": city.name_ru,
        "region": city.region,
        "type": city.type,
        "requires_district": city.requires_district,
        "display_order": city.display_order,
        "is_active": city.is_active,
        "created_at": datetime_to_str(city.created_at),
        "updated_at": datetime_to_str(city.updated_at),
    }


def district_ref(district: District | None) -> dict[str, Any] | None:
    if district is None:
        return None
    return {
        "id": district.id,
        "city_id": district.city_id,
        "name_uz": district.name_uz,
        "name_ru": district.name_ru,
        "center_lat": district.center_lat,
        "center_lng": district.center_lng,
    }


def district_to_dict(district: District) -> dict[str, Any]:
    return {
        "id": district.id,
        "city_id": district.city_id,
        "name_uz": district.name_uz,
        "name_ru": district.name_ru,
        "is_active": district.is_active,
        "display_order": district.display_order,
        "center_lat": district.center_lat,
        "center_lng": district.center_lng,
        "created_at": datetime_to_str(district.created_at),
        "updated_at": datetime_to_str(district.updated_at),
    }


def tariff_to_dict(tariff: RouteTariff, from_city: City | None, to_city: City | None) -> dict[str, Any]:
    return {
        "id": tariff.id,
        "from_city_id": tariff.from_city_id,
        "to_city_id": tariff.to_city_id,
        "from_city": city_ref(from_city),
        "to_city": city_ref(to_city),
        "suggested_price": price_to_int(tariff.suggested_price),
        "min_price": price_to_int(tariff.min_price),
        "max_price": price_to_int(tariff.max_price),
        "currency": "UZS",
        "is_active": tariff.is_active,
        "created_at": datetime_to_str(tariff.created_at),
        "updated_at": datetime_to_str(tariff.updated_at),
    }


def list_cities(
    db: Session,
    search: str | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    stmt = select(City)
    if is_active is not None:
        stmt = stmt.where(City.is_active == is_active)
    normalized_search = normalize_text(search)
    if normalized_search:
        pattern = f"%{normalized_search}%"
        stmt = stmt.where(
            or_(
                City.name_uz.ilike(pattern),
                City.name_ru.ilike(pattern),
                City.region.ilike(pattern),
            )
        )
    offset, safe_limit = pagination(page, limit)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    cities = list(db.scalars(stmt.order_by(City.display_order.asc(), City.name_uz.asc()).offset(offset).limit(safe_limit)))
    return {
        "items": [city_to_dict(city) for city in cities],
        "pagination": pagination_meta(total, page, limit),
    }


def list_tariffs(
    db: Session,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    is_active: bool | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    stmt = select(RouteTariff)
    if from_city_id is not None:
        stmt = stmt.where(RouteTariff.from_city_id == from_city_id)
    if to_city_id is not None:
        stmt = stmt.where(RouteTariff.to_city_id == to_city_id)
    if is_active is not None:
        stmt = stmt.where(RouteTariff.is_active == is_active)

    offset, safe_limit = pagination(page, limit)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    tariffs = list(db.scalars(stmt.order_by(RouteTariff.created_at.desc()).offset(offset).limit(safe_limit)))

    items = []
    for tariff in tariffs:
        items.append(tariff_to_dict(tariff, db.get(City, tariff.from_city_id), db.get(City, tariff.to_city_id)))
    return {
        "items": items,
        "pagination": pagination_meta(total, page, limit),
    }


def ensure_city_name_available(db: Session, name_uz: str, exclude_city_id: int | None = None) -> JSONResponse | None:
    normalized_name = normalize_required_text(name_uz)
    stmt = select(City).where(func.lower(City.name_uz) == normalized_name.lower())
    if exclude_city_id is not None:
        stmt = stmt.where(City.id != exclude_city_id)
    exact_existing = db.scalar(stmt)
    if exact_existing is not None:
        return error_response(status.HTTP_409_CONFLICT, "CITY_ALREADY_EXISTS", "City already exists")

    candidates = list(db.scalars(select(City)))
    normalized_key = city_name_key(normalized_name)
    for city in candidates:
        if exclude_city_id is not None and city.id == exclude_city_id:
            continue
        if city_name_key(city.name_uz) == normalized_key:
            return error_response(status.HTTP_409_CONFLICT, "CITY_ALREADY_EXISTS", "City already exists")
    return None


def create_city(db: Session, payload: CityCreate, actor: User) -> City | JSONResponse:
    name_uz = normalize_required_text(payload.name_uz)
    if not name_uz:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "name_uz is required")
    duplicate = ensure_city_name_available(db, name_uz)
    if duplicate is not None:
        return duplicate

    city = City(
        name=name_uz,
        name_uz=name_uz,
        name_ru=normalize_text(payload.name_ru),
        region=normalize_text(payload.region),
        type=normalize_text(payload.type) or "region",
        requires_district=payload.requires_district,
        display_order=payload.display_order,
        is_active=True,
    )
    db.add(city)
    db.flush()
    write_audit_log(db, actor, "city", city.id, "city_created", new_value=city_to_dict(city))
    db.commit()
    db.refresh(city)
    return city


def update_city(db: Session, city_id: int, payload: CityUpdate, actor: User) -> City | JSONResponse:
    city = db.get(City, city_id)
    if city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "CITY_NOT_FOUND", "City not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "name_uz" in update_data and update_data["name_uz"] is not None:
        update_data["name_uz"] = normalize_required_text(update_data["name_uz"])
        if not update_data["name_uz"]:
            return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "name_uz is required")
        duplicate = ensure_city_name_available(db, update_data["name_uz"], exclude_city_id=city.id)
        if duplicate is not None:
            return duplicate
    for field in ("name_ru", "region", "type"):
        if field in update_data:
            update_data[field] = normalize_text(update_data[field])

    old_value = city_to_dict(city)
    for field, value in update_data.items():
        setattr(city, field, value)
        if field == "name_uz" and value is not None:
            city.name = value
    db.add(city)
    db.flush()
    write_audit_log(
        db,
        actor,
        "city",
        city.id,
        "city_updated",
        old_value=old_value,
        new_value=city_to_dict(city),
    )
    db.commit()
    db.refresh(city)
    return city


def ensure_district_name_available(
    db: Session,
    city_id: int,
    name_uz: str,
    exclude_district_id: int | None = None,
) -> JSONResponse | None:
    normalized_name = normalize_required_text(name_uz)
    stmt = select(District).where(District.city_id == city_id, func.lower(District.name_uz) == normalized_name.lower())
    if exclude_district_id is not None:
        stmt = stmt.where(District.id != exclude_district_id)
    existing = db.scalar(stmt)
    if existing is not None:
        return error_response(status.HTTP_409_CONFLICT, "DISTRICT_ALREADY_EXISTS", "District already exists")

    normalized_key = city_name_key(normalized_name)
    for district in db.scalars(select(District).where(District.city_id == city_id)):
        if exclude_district_id is not None and district.id == exclude_district_id:
            continue
        if city_name_key(district.name_uz) == normalized_key:
            return error_response(status.HTTP_409_CONFLICT, "DISTRICT_ALREADY_EXISTS", "District already exists")
    return None


def list_districts(
    db: Session,
    city_id: int | None = None,
    search: str | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    stmt = select(District)
    if city_id is not None:
        stmt = stmt.where(District.city_id == city_id)
    if is_active is not None:
        stmt = stmt.where(District.is_active == is_active)
    normalized_search = normalize_text(search)
    if normalized_search:
        pattern = f"%{normalized_search}%"
        stmt = stmt.where(or_(District.name_uz.ilike(pattern), District.name_ru.ilike(pattern)))
    offset, safe_limit = pagination(page, limit)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    districts = list(
        db.scalars(stmt.order_by(District.display_order.asc(), District.name_uz.asc()).offset(offset).limit(safe_limit))
    )
    return {
        "items": [district_to_dict(district) for district in districts],
        "pagination": pagination_meta(total, page, limit),
    }


def list_public_city_districts(
    db: Session,
    city_id: int,
    search: str | None = None,
    is_active: bool | None = True,
    page: int = 1,
    limit: int = 20,
) -> tuple[dict[str, Any], str | None] | JSONResponse:
    city = db.get(City, city_id)
    if city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "CITY_NOT_FOUND", "City not found")
    if not city.is_active:
        return error_response(status.HTTP_400_BAD_REQUEST, "CITY_INACTIVE", "City is inactive")
    if not city.requires_district:
        return {
            "items": [],
            "pagination": pagination_meta(0, page, limit),
        }, "District selection is not required for this city"
    return list_districts(db, city_id=city_id, search=search, is_active=is_active, page=page, limit=limit), None


def create_district(db: Session, payload: DistrictCreate, actor: User) -> District | JSONResponse:
    city = db.get(City, payload.city_id)
    if city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "CITY_NOT_FOUND", "City not found")
    name_uz = normalize_required_text(payload.name_uz)
    if not name_uz:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "name_uz is required")
    duplicate = ensure_district_name_available(db, payload.city_id, name_uz)
    if duplicate is not None:
        return duplicate
    district = District(
        city_id=payload.city_id,
        name_uz=name_uz,
        name_ru=normalize_text(payload.name_ru),
        is_active=payload.is_active,
        display_order=payload.display_order,
        center_lat=payload.center_lat,
        center_lng=payload.center_lng,
    )
    db.add(district)
    db.flush()
    write_audit_log(db, actor, "district", district.id, "district_created", new_value=district_to_dict(district))
    db.commit()
    db.refresh(district)
    return district


def update_district(db: Session, district_id: int, payload: DistrictUpdate, actor: User) -> District | JSONResponse:
    district = db.get(District, district_id)
    if district is None:
        return error_response(status.HTTP_404_NOT_FOUND, "DISTRICT_NOT_FOUND", "District not found")
    update_data = payload.model_dump(exclude_unset=True)
    if "name_uz" in update_data and update_data["name_uz"] is not None:
        update_data["name_uz"] = normalize_required_text(update_data["name_uz"])
        duplicate = ensure_district_name_available(db, district.city_id, update_data["name_uz"], exclude_district_id=district.id)
        if duplicate is not None:
            return duplicate
    if "name_ru" in update_data:
        update_data["name_ru"] = normalize_text(update_data["name_ru"])

    old_value = district_to_dict(district)
    for field, value in update_data.items():
        setattr(district, field, value)
    db.add(district)
    db.flush()
    write_audit_log(
        db,
        actor,
        "district",
        district.id,
        "district_updated",
        old_value=old_value,
        new_value=district_to_dict(district),
    )
    db.commit()
    db.refresh(district)
    return district


def get_active_city_pair(db: Session, from_city_id: int, to_city_id: int) -> tuple[City, City] | JSONResponse:
    if from_city_id == to_city_id:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "SAME_CITY_ROUTE",
            "from_city_id and to_city_id cannot be the same",
        )
    from_city = db.get(City, from_city_id)
    to_city = db.get(City, to_city_id)
    if from_city is None or to_city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "CITY_NOT_FOUND", "City not found")
    if not from_city.is_active or not to_city.is_active:
        return error_response(status.HTTP_400_BAD_REQUEST, "CITY_INACTIVE", "City is inactive")
    return from_city, to_city


def validate_city_district(
    db: Session,
    city: City,
    district_id: int | None,
    field_name: str,
) -> District | None | JSONResponse:
    if city.requires_district and district_id is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "DISTRICT_REQUIRED", "District is required for selected city")
    if district_id is None:
        return None
    district = db.get(District, district_id)
    if district is None:
        return error_response(status.HTTP_404_NOT_FOUND, "DISTRICT_NOT_FOUND", "District not found")
    if district.city_id != city.id:
        return error_response(status.HTTP_400_BAD_REQUEST, "DISTRICT_CITY_MISMATCH", f"{field_name} does not belong to selected city")
    if not district.is_active:
        return error_response(status.HTTP_400_BAD_REQUEST, "DISTRICT_INACTIVE", "District is inactive")
    return district


def validate_active_city_district_pair(
    db: Session,
    from_city_id: int,
    to_city_id: int,
    from_district_id: int | None,
    to_district_id: int | None,
) -> tuple[City, City, District | None, District | None] | JSONResponse:
    cities = get_active_city_pair(db, from_city_id, to_city_id)
    if isinstance(cities, JSONResponse):
        return cities
    from_city, to_city = cities
    from_district = validate_city_district(db, from_city, from_district_id, "from_district_id")
    if isinstance(from_district, JSONResponse):
        return from_district
    to_district = validate_city_district(db, to_city, to_district_id, "to_district_id")
    if isinstance(to_district, JSONResponse):
        return to_district
    return from_city, to_city, from_district, to_district


def validate_tariff_prices(
    suggested_price: Decimal | int | None,
    min_price: Decimal | int | None,
    max_price: Decimal | int | None,
) -> JSONResponse | None:
    if suggested_price is not None and suggested_price < 0:
        return error_response(status.HTTP_400_BAD_REQUEST, "INVALID_PRICE_RANGE", "suggested_price must be >= 0")
    if min_price is not None and min_price < 0:
        return error_response(status.HTTP_400_BAD_REQUEST, "INVALID_PRICE_RANGE", "min_price must be >= 0")
    if max_price is not None and max_price < 0:
        return error_response(status.HTTP_400_BAD_REQUEST, "INVALID_PRICE_RANGE", "max_price must be >= 0")
    if min_price is not None and suggested_price is not None and min_price > suggested_price:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PRICE_RANGE",
            "min_price cannot be greater than suggested_price",
        )
    if max_price is not None and suggested_price is not None and suggested_price > max_price:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PRICE_RANGE",
            "suggested_price cannot be greater than max_price",
        )
    return None


def active_tariff_exists(
    db: Session,
    from_city_id: int,
    to_city_id: int,
    exclude_tariff_id: int | None = None,
) -> bool:
    stmt = select(RouteTariff).where(
        RouteTariff.from_city_id == from_city_id,
        RouteTariff.to_city_id == to_city_id,
        RouteTariff.is_active == True,  # noqa: E712
    )
    if exclude_tariff_id is not None:
        stmt = stmt.where(RouteTariff.id != exclude_tariff_id)
    return db.scalar(stmt) is not None


def create_tariff(db: Session, payload: RouteTariffCreate, actor: User) -> RouteTariff | JSONResponse:
    cities = get_active_city_pair(db, payload.from_city_id, payload.to_city_id)
    if isinstance(cities, JSONResponse):
        return cities
    validation_error = validate_tariff_prices(payload.suggested_price, payload.min_price, payload.max_price)
    if validation_error is not None:
        return validation_error
    if active_tariff_exists(db, payload.from_city_id, payload.to_city_id):
        return error_response(
            status.HTTP_409_CONFLICT,
            "ROUTE_TARIFF_ALREADY_EXISTS",
            "Active route tariff already exists",
        )

    tariff = RouteTariff(
        from_city_id=payload.from_city_id,
        to_city_id=payload.to_city_id,
        suggested_price=payload.suggested_price,
        min_price=payload.min_price,
        max_price=payload.max_price,
        is_active=True,
    )
    db.add(tariff)
    db.flush()
    from_city, to_city = cities
    write_audit_log(
        db,
        actor,
        "route_tariff",
        tariff.id,
        "route_tariff_created",
        new_value=tariff_to_dict(tariff, from_city, to_city),
    )
    db.commit()
    db.refresh(tariff)
    return tariff


def update_tariff(db: Session, tariff_id: int, payload: RouteTariffUpdate, actor: User) -> RouteTariff | JSONResponse:
    tariff = db.get(RouteTariff, tariff_id)
    if tariff is None:
        return error_response(status.HTTP_404_NOT_FOUND, "ROUTE_TARIFF_NOT_FOUND", "Route tariff not found")

    from_city = db.get(City, tariff.from_city_id)
    to_city = db.get(City, tariff.to_city_id)
    if from_city is None or to_city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "CITY_NOT_FOUND", "City not found")

    update_data = payload.model_dump(exclude_unset=True)
    next_suggested = update_data.get("suggested_price", tariff.suggested_price)
    next_min = update_data.get("min_price", tariff.min_price)
    next_max = update_data.get("max_price", tariff.max_price)
    validation_error = validate_tariff_prices(next_suggested, next_min, next_max)
    if validation_error is not None:
        return validation_error

    if update_data.get("is_active") is True and active_tariff_exists(
        db,
        tariff.from_city_id,
        tariff.to_city_id,
        exclude_tariff_id=tariff.id,
    ):
        return error_response(
            status.HTTP_409_CONFLICT,
            "ROUTE_TARIFF_ALREADY_EXISTS",
            "Active route tariff already exists",
        )

    old_value = tariff_to_dict(tariff, from_city, to_city)
    for field, value in update_data.items():
        setattr(tariff, field, value)
    db.add(tariff)
    db.flush()
    write_audit_log(
        db,
        actor,
        "route_tariff",
        tariff.id,
        "route_tariff_updated",
        old_value=old_value,
        new_value=tariff_to_dict(tariff, from_city, to_city),
    )
    db.commit()
    db.refresh(tariff)
    return tariff
