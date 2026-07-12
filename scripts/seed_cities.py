from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import City, RouteTariff
from app.services.city_service import city_name_key, normalize_required_text, normalize_text


CITY_SEEDS = [
    {"name_uz": "Toshkent", "name_ru": "Ташкент", "region": "Toshkent"},
    {"name_uz": "Samarqand", "name_ru": "Самарканд", "region": "Samarqand"},
    {"name_uz": "Buxoro", "name_ru": "Бухара", "region": "Buxoro"},
    {"name_uz": "Andijon", "name_ru": "Андижан", "region": "Andijon"},
    {"name_uz": "Farg'ona", "name_ru": "Фергана", "region": "Farg'ona"},
    {"name_uz": "Namangan", "name_ru": "Наманган", "region": "Namangan"},
    {"name_uz": "Navoiy", "name_ru": "Навои", "region": "Navoiy"},
    {"name_uz": "Qarshi", "name_ru": "Карши", "region": "Qashqadaryo"},
    {"name_uz": "Termiz", "name_ru": "Термез", "region": "Surxondaryo"},
    {"name_uz": "Nukus", "name_ru": "Нукус", "region": "Qoraqalpog'iston"},
    {"name_uz": "Xiva", "name_ru": "Хива", "region": "Xorazm"},
    {"name_uz": "Jizzax", "name_ru": "Джизак", "region": "Jizzax"},
]

TARIFF_SEEDS = [
    {"from": "Toshkent", "to": "Samarqand", "min_price": 50000, "suggested_price": 60000, "max_price": 80000},
    {"from": "Samarqand", "to": "Toshkent", "min_price": 50000, "suggested_price": 60000, "max_price": 80000},
    {"from": "Toshkent", "to": "Buxoro", "min_price": 75000, "suggested_price": 90000, "max_price": 120000},
    {"from": "Buxoro", "to": "Toshkent", "min_price": 75000, "suggested_price": 90000, "max_price": 120000},
]


def upsert_city(db, seed: dict[str, str]) -> City:
    name_uz = normalize_required_text(seed["name_uz"])
    existing = None
    for city in db.scalars(select(City)):
        if city_name_key(city.name_uz) == city_name_key(name_uz):
            existing = city
            break

    if existing is None:
        existing = City(name=name_uz, name_uz=name_uz, is_active=True)
        db.add(existing)

    existing.name = name_uz
    existing.name_uz = name_uz
    existing.name_ru = normalize_text(seed.get("name_ru"))
    existing.region = normalize_text(seed.get("region"))
    existing.is_active = True
    db.flush()
    return existing


def upsert_tariff(db, city_by_name: dict[str, City], seed: dict[str, object]) -> None:
    from_city = city_by_name[city_name_key(str(seed["from"]))]
    to_city = city_by_name[city_name_key(str(seed["to"]))]
    tariff = db.scalar(
        select(RouteTariff).where(
            RouteTariff.from_city_id == from_city.id,
            RouteTariff.to_city_id == to_city.id,
            RouteTariff.is_active == True,  # noqa: E712
        )
    )
    if tariff is None:
        tariff = RouteTariff(from_city_id=from_city.id, to_city_id=to_city.id, is_active=True)
        db.add(tariff)
    tariff.min_price = seed.get("min_price")
    tariff.suggested_price = seed["suggested_price"]
    tariff.max_price = seed.get("max_price")


def main() -> None:
    db = SessionLocal()
    try:
        city_by_name = {}
        for seed in CITY_SEEDS:
            city = upsert_city(db, seed)
            city_by_name[city_name_key(city.name_uz)] = city
        for seed in TARIFF_SEEDS:
            upsert_tariff(db, city_by_name, seed)
        db.commit()
        print(f"Seeded {len(CITY_SEEDS)} cities and {len(TARIFF_SEEDS)} active route tariffs.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
