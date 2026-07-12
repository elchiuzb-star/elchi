from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt
import sys
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models import City, District, RouteTariff, User
from app.services.auth_service import normalize_phone


CITY_SEEDS = [
    {"name": "Toshkent shahri", "region": "Toshkent shahri", "type": "city", "requires_district": True, "order": 1, "center": (41.3111, 69.2797)},
    {"name": "Toshkent viloyati", "region": "Toshkent viloyati", "type": "region", "requires_district": True, "order": 2, "center": (41.0320, 69.3530)},
    {"name": "Samarqand viloyati", "region": "Samarqand viloyati", "type": "region", "requires_district": True, "order": 3, "center": (39.6542, 66.9597)},
    {"name": "Andijon viloyati", "region": "Andijon viloyati", "type": "region", "requires_district": True, "order": 4, "center": (40.7821, 72.3442)},
    {"name": "Farg'ona viloyati", "region": "Farg'ona viloyati", "type": "region", "requires_district": True, "order": 5, "center": (40.3894, 71.7844)},
    {"name": "Namangan viloyati", "region": "Namangan viloyati", "type": "region", "requires_district": True, "order": 6, "center": (40.9983, 71.6726)},
    {"name": "Jizzax viloyati", "region": "Jizzax viloyati", "type": "region", "requires_district": True, "order": 7, "center": (40.1158, 67.8422)},
    {"name": "Sirdaryo viloyati", "region": "Sirdaryo viloyati", "type": "region", "requires_district": True, "order": 8, "center": (40.4897, 68.7842)},
    {"name": "Navoiy viloyati", "region": "Navoiy viloyati", "type": "region", "requires_district": True, "order": 9, "center": (40.1039, 65.3683)},
    {"name": "Buxoro viloyati", "region": "Buxoro viloyati", "type": "region", "requires_district": True, "order": 10, "center": (39.7747, 64.4286)},
    {"name": "Qashqadaryo viloyati", "region": "Qashqadaryo viloyati", "type": "region", "requires_district": True, "order": 11, "center": (38.8606, 65.7890)},
    {"name": "Surxondaryo viloyati", "region": "Surxondaryo viloyati", "type": "region", "requires_district": True, "order": 12, "center": (37.2242, 67.2783)},
    {"name": "Xorazm viloyati", "region": "Xorazm viloyati", "type": "region", "requires_district": True, "order": 13, "center": (41.5500, 60.6333)},
    {"name": "Qoraqalpog'iston Respublikasi", "region": "Qoraqalpog'iston Respublikasi", "type": "republic", "requires_district": True, "order": 14, "center": (42.4531, 59.6103)},
]


DISTRICT_SEEDS = {
    "Toshkent shahri": [
        "Bektemir", "Chilonzor", "Yashnobod", "Mirobod", "Mirzo Ulug'bek", "Sergeli",
        "Shayxontohur", "Olmazor", "Uchtepa", "Yakkasaroy", "Yunusobod", "Yangihayot",
    ],
    "Qoraqalpog'iston Respublikasi": [
        "Amudaryo", "Beruniy", "Bo'zatov", "Chimboy", "Ellikqal'a", "Kegeyli", "Mo'ynoq", "Nukus",
        "Qanliko'l", "Qo'ng'irot", "Qorao'zak", "Shumanay", "Taxtako'pir", "Taxiatosh", "To'rtko'l", "Xo'jayli",
    ],
    "Andijon viloyati": [
        "Andijon", "Asaka", "Baliqchi", "Bo'ston", "Buloqboshi", "Izboskan", "Jalaquduq",
        "Xo'jaobod", "Qo'rg'ontepa", "Marhamat", "Oltinko'l", "Paxtaobod", "Shahrixon", "Ulug'nor",
    ],
    "Buxoro viloyati": [
        "Olot", "Buxoro", "G'ijduvon", "Jondor", "Kogon", "Qorako'l", "Qorovulbozor",
        "Peshku", "Romitan", "Shofirkon", "Vobkent",
    ],
    "Farg'ona viloyati": [
        "Oltiariq", "Bag'dod", "Beshariq", "Buvayda", "Dang'ara", "Farg'ona", "Furqat",
        "Qo'shtepa", "Quva", "Rishton", "So'x", "Toshloq", "Uchko'prik", "O'zbekiston", "Yozyovon",
    ],
    "Jizzax viloyati": [
        "Arnasoy", "Baxmal", "Do'stlik", "Forish", "G'allaorol", "Sharof Rashidov",
        "Mirzacho'l", "Paxtakor", "Yangiobod", "Zomin", "Zafarobod", "Zarbdor",
    ],
    "Namangan viloyati": [
        "Chortoq", "Chust", "Kosonsoy", "Mingbuloq", "Namangan", "Norin", "Pop",
        "To'raqo'rg'on", "Uchqo'rg'on", "Uychi", "Yangiqo'rg'on", "Yangi Namangan",
    ],
    "Navoiy viloyati": [
        "Konimex", "Qiziltepa", "Xatirchi", "Navbahor", "Karmana", "Nurota", "Tomdi", "Uchquduq",
    ],
    "Qashqadaryo viloyati": [
        "Chiroqchi", "Dehqonobod", "G'uzor", "Qamashi", "Qarshi", "Koson", "Kasbi",
        "Kitob", "Mirishkor", "Muborak", "Nishon", "Shahrisabz", "Yakkabog'", "Ko'kdala",
    ],
    "Samarqand viloyati": [
        "Bulung'ur", "Ishtixon", "Jomboy", "Kattaqo'rg'on", "Qo'shrabot", "Narpay", "Nurobod",
        "Oqdaryo", "Paxtachi", "Payariq", "Pastdarg'om", "Samarqand", "Toyloq", "Urgut",
    ],
    "Sirdaryo viloyati": [
        "Oqoltin", "Boyovut", "Guliston", "Xovos", "Mirzaobod", "Sardoba", "Sayxunobod", "Sirdaryo",
    ],
    "Surxondaryo viloyati": [
        "Angor", "Bandixon", "Boysun", "Denov", "Jarqo'rg'on", "Qiziriq", "Qumqo'rg'on",
        "Muzrabot", "Oltinsoy", "Sariosiyo", "Sherobod", "Sho'rchi", "Termiz", "Uzun",
    ],
    "Toshkent viloyati": [
        "Bekobod", "Bo'stonliq", "Bo'ka", "Chinoz", "Qibray", "Ohangaron", "Oqqo'rg'on",
        "Parkent", "Piskent", "Quyi Chirchiq", "Zangiota", "O'rta Chirchiq", "Yangiyo'l",
        "Yuqori Chirchiq", "Toshkent",
    ],
    "Xorazm viloyati": [
        "Bog'ot", "Gurlan", "Xonqa", "Hazorasp", "Xiva", "Qo'shko'pir", "Shovot",
        "Urganch", "Yangiariq", "Yangibozor", "Tuproqqal'a",
    ],
}


def money(value: Decimal | int | float) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def coordinate(value: Decimal | int | float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def district_center(city_center: tuple[float, float], index: int) -> tuple[Decimal, Decimal]:
    row = (index - 1) // 5
    col = (index - 1) % 5
    lat_offset = (row - 1) * 0.08
    lng_offset = (col - 2) * 0.08
    return coordinate(city_center[0] + lat_offset), coordinate(city_center[1] + lng_offset)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    radius_km = 6371.0
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * radius_km * asin(sqrt(value))


def suggested_price(from_center: tuple[float, float], to_center: tuple[float, float]) -> Decimal:
    distance = haversine_km(from_center, to_center)
    raw = Decimal(30000 + distance * 130)
    rounded = (raw / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(10000)
    return max(money(40000), money(rounded))


def seed_super_admin(db) -> str:
    phone = normalize_phone("+998900000001")
    if not isinstance(phone, str):
        raise RuntimeError("Invalid super admin phone")
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(phone=phone, role="super_admin", status="active", is_phone_verified=True, full_name="Elchi Super Admin")
        db.add(user)
    else:
        user.role = "super_admin"
        user.status = "active"
        user.is_phone_verified = True
        user.full_name = user.full_name or "Elchi Super Admin"
        db.add(user)
    return phone


def seed_cities(db) -> dict[str, City]:
    existing = {city.name_uz.casefold(): city for city in db.scalars(select(City)).all()}
    cities: dict[str, City] = {}
    for seed in CITY_SEEDS:
        city = existing.get(seed["name"].casefold())
        if city is None:
            city = City(name=seed["name"], name_uz=seed["name"])
            db.add(city)
        city.name = seed["name"]
        city.name_uz = seed["name"]
        city.name_ru = city.name_ru or seed["name"]
        city.region = seed["region"]
        city.type = seed["type"]
        city.requires_district = seed["requires_district"]
        city.display_order = seed["order"]
        city.is_active = True
        db.add(city)
        cities[seed["name"]] = city
    db.flush()
    return cities


def seed_districts(db, cities: dict[str, City]) -> int:
    created = 0
    for city_name, district_names in DISTRICT_SEEDS.items():
        city = cities[city_name]
        existing = {district.name_uz.casefold(): district for district in db.scalars(select(District).where(District.city_id == city.id))}
        seed_names = {name.casefold() for name in district_names}
        center = next(seed["center"] for seed in CITY_SEEDS if seed["name"] == city_name)
        for key, district in existing.items():
            if key not in seed_names and district.is_active:
                district.is_active = False
                db.add(district)
        for index, name in enumerate(district_names, start=1):
            district = existing.get(name.casefold())
            if district is None:
                district = District(city_id=city.id, name_uz=name)
                created += 1
            district.name_uz = name
            district.name_ru = district.name_ru or name
            district.is_active = True
            district.display_order = index
            district.center_lat, district.center_lng = district_center(center, index)
            db.add(district)
    return created


def seed_tariffs(db, cities: dict[str, City]) -> int:
    created = 0
    active_cities = [city for city in cities.values() if city.is_active]
    center_by_city_id = {cities[seed["name"]].id: seed["center"] for seed in CITY_SEEDS}
    existing = {
        (tariff.from_city_id, tariff.to_city_id): tariff
        for tariff in db.scalars(select(RouteTariff)).all()
    }
    for from_city in active_cities:
        for to_city in active_cities:
            if from_city.id == to_city.id:
                continue
            key = (from_city.id, to_city.id)
            tariff = existing.get(key)
            if tariff is None:
                tariff = RouteTariff(from_city_id=from_city.id, to_city_id=to_city.id)
                db.add(tariff)
                created += 1
            tariff.is_active = True
            if tariff.suggested_price is None:
                tariff.suggested_price = suggested_price(center_by_city_id[from_city.id], center_by_city_id[to_city.id])
            if tariff.min_price is None:
                tariff.min_price = money(Decimal(tariff.suggested_price) * Decimal("0.80"))
            if tariff.max_price is None:
                tariff.max_price = money(Decimal(tariff.suggested_price) * Decimal("1.35"))
            db.add(tariff)
    return created


def main() -> None:
    db = SessionLocal()
    try:
        super_admin_phone = seed_super_admin(db)
        cities = seed_cities(db)
        created_districts = seed_districts(db, cities)
        created_tariffs = seed_tariffs(db, cities)
        db.commit()
        print(f"super_admin={super_admin_phone}")
        print(f"cities={len(cities)}")
        print(f"created_districts={created_districts}")
        print(f"created_route_tariffs={created_tariffs}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
