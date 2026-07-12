from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.models import City, District


CITY_META = {
    "Toshkent": {"type": "city", "requires_district": False, "display_order": 1, "region": "Toshkent shahri"},
    "Nurafshon": {"type": "region", "requires_district": True, "display_order": 2, "region": "Toshkent viloyati"},
    "Samarqand": {"type": "region", "requires_district": True, "display_order": 3, "region": "Samarqand"},
    "Andijon": {"type": "region", "requires_district": True, "display_order": 4, "region": "Andijon"},
    "Fargona": {"type": "region", "requires_district": True, "display_order": 5, "region": "Fargona"},
    "Namangan": {"type": "region", "requires_district": True, "display_order": 6, "region": "Namangan"},
    "Jizzax": {"type": "region", "requires_district": True, "display_order": 7, "region": "Jizzax"},
    "Guliston": {"type": "region", "requires_district": True, "display_order": 8, "region": "Sirdaryo"},
    "Navoiy": {"type": "region", "requires_district": True, "display_order": 9, "region": "Navoiy"},
    "Buxoro": {"type": "region", "requires_district": True, "display_order": 10, "region": "Buxoro"},
    "Qarshi": {"type": "region", "requires_district": True, "display_order": 11, "region": "Qashqadaryo"},
    "Termiz": {"type": "region", "requires_district": True, "display_order": 12, "region": "Surxondaryo"},
    "Urganch": {"type": "region", "requires_district": True, "display_order": 13, "region": "Xorazm"},
    "Nukus": {"type": "republic", "requires_district": True, "display_order": 14, "region": "Qoraqalpogiston"},
}


DISTRICTS = {
    "Nurafshon": ["Nurafshon", "Angren", "Bekobod", "Chirchiq", "Olmaliq", "Ohangaron", "Parkent", "Qibray", "Zangiota"],
    "Samarqand": ["Samarqand shahri", "Kattaqorgon", "Urgut", "Pastdargom", "Bulungur", "Jomboy", "Ishtixon", "Narpay", "Payariq", "Qoshrabot", "Toyloq"],
    "Andijon": ["Andijon shahri", "Asaka", "Xonobod", "Shahrixon", "Marhamat", "Baliqchi", "Jalaquduq", "Izboskan", "Paxtaobod"],
    "Fargona": ["Fargona shahri", "Qoqon", "Margilon", "Rishton", "Oltiariq", "Beshariq", "Dangara", "Uchkoprik", "Quva", "Yozyovon"],
    "Namangan": ["Namangan shahri", "Chust", "Chortoq", "Kosonsoy", "Pop", "Uchqorgon", "Uychi", "Yangiqorgon"],
    "Jizzax": ["Jizzax shahri", "Zomin", "Gallaorol", "Dostlik", "Paxtakor", "Forish", "Sharof Rashidov", "Mirzachol"],
    "Guliston": ["Guliston shahri", "Yangiyer", "Shirin", "Boyovut", "Sardoba", "Sayxunobod", "Sirdaryo", "Xovos"],
    "Navoiy": ["Navoiy shahri", "Zarafshon", "Karmana", "Qiziltepa", "Konimex", "Nurota", "Tomdi", "Uchquduq"],
    "Buxoro": ["Buxoro shahri", "Gijduvon", "Kogon", "Vobkent", "Qorakol", "Romitan", "Shofirkon", "Olot"],
    "Qarshi": ["Qarshi shahri", "Shahrisabz", "Kitob", "Koson", "Muborak", "Guzor", "Chiroqchi", "Yakkabog"],
    "Termiz": ["Termiz shahri", "Denov", "Boysun", "Sherobod", "Jarqorgon", "Qumqorgon", "Sariosiyo", "Uzun"],
    "Urganch": ["Urganch shahri", "Xiva", "Hazorasp", "Gurlan", "Shovot", "Bogot", "Xonqa", "Yangiariq"],
    "Nukus": ["Nukus shahri", "Beruniy", "Chimboy", "Ellikqala", "Moynoq", "Qongirot", "Tortkol", "Xojayli"],
}


DISTRICT_CENTERS = {
    ("Nurafshon", "Nurafshon"): (41.0320, 69.3530),
    ("Nurafshon", "Angren"): (41.0167, 70.1436),
    ("Nurafshon", "Bekobod"): (40.2208, 69.2697),
    ("Nurafshon", "Chirchiq"): (41.4689, 69.5822),
    ("Nurafshon", "Olmaliq"): (40.8447, 69.5983),
    ("Nurafshon", "Ohangaron"): (40.9064, 69.6383),
    ("Nurafshon", "Parkent"): (41.2944, 69.6764),
    ("Nurafshon", "Qibray"): (41.3897, 69.4650),
    ("Nurafshon", "Zangiota"): (41.1897, 69.1664),
    ("Samarqand", "Samarqand shahri"): (39.6542, 66.9597),
    ("Samarqand", "Kattaqorgon"): (39.8989, 66.2561),
    ("Samarqand", "Urgut"): (39.4022, 67.2431),
    ("Samarqand", "Pastdargom"): (39.6564, 66.7500),
    ("Samarqand", "Bulungur"): (39.7647, 67.2714),
    ("Samarqand", "Jomboy"): (39.6986, 67.0939),
    ("Samarqand", "Ishtixon"): (39.9664, 66.4861),
    ("Samarqand", "Narpay"): (39.9000, 65.9250),
    ("Samarqand", "Payariq"): (39.9944, 66.8611),
    ("Samarqand", "Qoshrabot"): (40.2500, 66.6889),
    ("Samarqand", "Toyloq"): (39.6000, 67.0833),
    ("Andijon", "Andijon shahri"): (40.7821, 72.3442),
    ("Andijon", "Asaka"): (40.6415, 72.2387),
    ("Andijon", "Xonobod"): (40.8000, 73.0000),
    ("Andijon", "Shahrixon"): (40.7130, 72.0570),
    ("Andijon", "Marhamat"): (40.4800, 72.3130),
    ("Andijon", "Baliqchi"): (40.9100, 71.8500),
    ("Andijon", "Jalaquduq"): (40.7300, 72.6200),
    ("Andijon", "Izboskan"): (40.9167, 72.2333),
    ("Andijon", "Paxtaobod"): (40.9294, 72.5000),
    ("Fargona", "Fargona shahri"): (40.3894, 71.7844),
    ("Fargona", "Qoqon"): (40.5286, 70.9425),
    ("Fargona", "Margilon"): (40.4711, 71.7247),
    ("Fargona", "Rishton"): (40.3561, 71.2847),
    ("Fargona", "Oltiariq"): (40.3917, 71.4747),
    ("Fargona", "Beshariq"): (40.4358, 70.6103),
    ("Fargona", "Dangara"): (40.5833, 70.9167),
    ("Fargona", "Uchkoprik"): (40.5422, 71.0606),
    ("Fargona", "Quva"): (40.5222, 72.0722),
    ("Fargona", "Yozyovon"): (40.6500, 71.7333),
    ("Namangan", "Namangan shahri"): (40.9983, 71.6726),
    ("Namangan", "Chust"): (41.0000, 71.2370),
    ("Namangan", "Chortoq"): (41.0700, 71.8200),
    ("Namangan", "Kosonsoy"): (41.2561, 71.5508),
    ("Namangan", "Pop"): (40.8736, 71.1089),
    ("Namangan", "Uchqorgon"): (41.1139, 72.0794),
    ("Namangan", "Uychi"): (41.0800, 71.9230),
    ("Namangan", "Yangiqorgon"): (41.1872, 71.7339),
    ("Jizzax", "Jizzax shahri"): (40.1158, 67.8422),
    ("Jizzax", "Zomin"): (39.9600, 68.3950),
    ("Jizzax", "Gallaorol"): (40.0333, 67.5833),
    ("Jizzax", "Dostlik"): (40.5247, 68.0358),
    ("Jizzax", "Paxtakor"): (40.3153, 67.9544),
    ("Jizzax", "Forish"): (40.3667, 67.2333),
    ("Jizzax", "Sharof Rashidov"): (40.1500, 67.9000),
    ("Jizzax", "Mirzachol"): (40.5000, 68.3500),
    ("Guliston", "Guliston shahri"): (40.4897, 68.7842),
    ("Guliston", "Yangiyer"): (40.2750, 68.8225),
    ("Guliston", "Shirin"): (40.2300, 69.1167),
    ("Guliston", "Boyovut"): (40.5167, 68.9500),
    ("Guliston", "Sardoba"): (40.3667, 68.6500),
    ("Guliston", "Sayxunobod"): (40.6500, 68.8333),
    ("Guliston", "Sirdaryo"): (40.8333, 68.6667),
    ("Guliston", "Xovos"): (40.2500, 68.9000),
    ("Navoiy", "Navoiy shahri"): (40.1039, 65.3683),
    ("Navoiy", "Zarafshon"): (41.5764, 64.2072),
    ("Navoiy", "Karmana"): (40.1378, 65.3750),
    ("Navoiy", "Qiziltepa"): (40.0333, 64.8500),
    ("Navoiy", "Konimex"): (40.2750, 65.1500),
    ("Navoiy", "Nurota"): (40.5614, 65.6886),
    ("Navoiy", "Tomdi"): (41.7500, 64.6167),
    ("Navoiy", "Uchquduq"): (42.1500, 63.5667),
    ("Buxoro", "Buxoro shahri"): (39.7747, 64.4286),
    ("Buxoro", "Gijduvon"): (40.1000, 64.6833),
    ("Buxoro", "Kogon"): (39.7228, 64.5517),
    ("Buxoro", "Vobkent"): (40.0333, 64.5167),
    ("Buxoro", "Qorakol"): (39.5000, 63.8333),
    ("Buxoro", "Romitan"): (39.9333, 64.3833),
    ("Buxoro", "Shofirkon"): (40.1200, 64.5000),
    ("Buxoro", "Olot"): (39.4167, 63.8000),
    ("Qarshi", "Qarshi shahri"): (38.8606, 65.7890),
    ("Qarshi", "Shahrisabz"): (39.0578, 66.8342),
    ("Qarshi", "Kitob"): (39.1214, 66.8750),
    ("Qarshi", "Koson"): (39.0375, 65.5850),
    ("Qarshi", "Muborak"): (39.2553, 65.1528),
    ("Qarshi", "Guzor"): (38.6208, 66.2481),
    ("Qarshi", "Chiroqchi"): (39.0333, 66.5667),
    ("Qarshi", "Yakkabog"): (38.9767, 66.6889),
    ("Termiz", "Termiz shahri"): (37.2242, 67.2783),
    ("Termiz", "Denov"): (38.2667, 67.9000),
    ("Termiz", "Boysun"): (38.2083, 67.2061),
    ("Termiz", "Sherobod"): (37.6700, 67.0000),
    ("Termiz", "Jarqorgon"): (37.5050, 67.4190),
    ("Termiz", "Qumqorgon"): (37.8150, 67.5830),
    ("Termiz", "Sariosiyo"): (38.6500, 68.0000),
    ("Termiz", "Uzun"): (38.3667, 68.0500),
    ("Urganch", "Urganch shahri"): (41.5500, 60.6333),
    ("Urganch", "Xiva"): (41.3783, 60.3639),
    ("Urganch", "Hazorasp"): (41.3194, 61.0742),
    ("Urganch", "Gurlan"): (41.8447, 60.3919),
    ("Urganch", "Shovot"): (41.6558, 60.3025),
    ("Urganch", "Bogot"): (41.3147, 60.8533),
    ("Urganch", "Xonqa"): (41.4750, 60.7850),
    ("Urganch", "Yangiariq"): (41.3597, 60.5889),
    ("Nukus", "Nukus shahri"): (42.4531, 59.6103),
    ("Nukus", "Beruniy"): (41.6911, 60.7525),
    ("Nukus", "Chimboy"): (42.9294, 59.7697),
    ("Nukus", "Ellikqala"): (41.9300, 60.7200),
    ("Nukus", "Moynoq"): (43.7683, 59.0214),
    ("Nukus", "Qongirot"): (43.0500, 58.8500),
    ("Nukus", "Tortkol"): (41.5500, 61.0000),
    ("Nukus", "Xojayli"): (42.4000, 59.4500),
}


def main() -> None:
    engine = create_engine(settings.database_url)
    created = 0
    updated_cities = 0
    with Session(engine) as db:
        cities = {city.name_uz: city for city in db.scalars(select(City)).all()}
        for city_name, meta in CITY_META.items():
            city = cities.get(city_name)
            if city is None:
                continue
            changed = False
            for key, value in meta.items():
                if getattr(city, key) != value:
                    setattr(city, key, value)
                    changed = True
            if changed:
                updated_cities += 1
                db.add(city)

        db.flush()
        for city_name, names in DISTRICTS.items():
            city = cities.get(city_name)
            if city is None:
                continue
            existing = {district.name_uz.casefold(): district for district in db.scalars(select(District).where(District.city_id == city.id))}
            for index, name in enumerate(names, start=1):
                key = name.casefold()
                center = DISTRICT_CENTERS.get((city_name, name))
                if key in existing:
                    district = existing[key]
                    if not district.is_active or district.display_order != index:
                        district.is_active = True
                        district.display_order = index
                        db.add(district)
                    if center and (district.center_lat != center[0] or district.center_lng != center[1]):
                        district.center_lat = center[0]
                        district.center_lng = center[1]
                        db.add(district)
                    continue
                db.add(
                    District(
                        city_id=city.id,
                        name_uz=name,
                        is_active=True,
                        display_order=index,
                        center_lat=center[0] if center else None,
                        center_lng=center[1] if center else None,
                    )
                )
                created += 1
        db.commit()
    print(f"updated_cities={updated_cities}")
    print(f"created_districts={created}")


if __name__ == "__main__":
    main()
