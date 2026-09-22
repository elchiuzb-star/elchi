"""geo: district and region centres come from a verified table, never from the generated v1 lattice

Owner: A0a/A2 (wave 17, correction to 0079/0080).

0079 backfilled `geo_districts.center_lat/center_lng` from the v1 `districts` table on the assumption that the
v1 catalogue carried surveyed town centres. It does not. Whichever script filled a given database decides:

* `scripts/seed_districts.py` holds `DISTRICT_CENTERS`, 111 hand-checked coordinates (Urgut 39.4022/67.2431,
  Mo'ynoq 43.7683/59.0214, Qarshi 38.8606/65.7890). Those are real places.
* `scripts/seed_admin_required_data.py` holds `district_center()`, which lays a city's districts out on a
  **5-wide lattice stepping 0.08 degrees** from the city centre. Those are not places at all. In the
  development database every one of the 176 rows is a lattice point, so 0079 imported 164 invented
  coordinates and the picker would have opened on them as if they were Urgut or Mo'ynoq - Mo'ynoq's lattice
  point is about 250 km from the town.

A camera that opens 250 km away and looks authoritative is worse than one that opens on the region, because
the person drops a pin where it lands. AGENTS.md section 9 forbids presenting invented data as real, so this
migration:

1. clears every district centre that is provably a lattice point - recomputed here from the same 14 city
   centres and `districts.display_order` the generator used, matched to within a metre;
2. fills district centres from the hand-checked table only, which covers 99 of the 170 v2 districts. The
   remaining 65 real districts stay NULL and the client falls back to the region, which is honest and still
   opens inside the right province;
3. sets every region centre to its real administrative capital. 0080 averaged the lattice instead, which
   landed 1-3 km out and was derived from invented data either way. The 14 capitals in `CITY_SEEDS` are real
   and are the source of truth here.

Still only a **camera position**. Section 2 of the specification rejects deciding a route by administrative
unit and Q88 projects a marked point onto a confirmed route; `tests/pg/geo/test_district_map_centre_pg.py`
guards that over the source, and now also guards that no centre is a lattice point.

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260919_0081
Revises: 20260919_0080
Create Date: 2026-09-19 23:10:00.000000
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from alembic import op
from sqlalchemy import text

revision: str = "20260919_0081"
down_revision: str = "20260919_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The city centres `scripts/seed_admin_required_data.py` lays its lattice out from. These are real - it is
#: the districts derived from them that are invented - so the same table serves as the region capitals below.
_CITY_CENTRES: dict[str, tuple[str, float, float]] = {
    # v1 city name -> (v2 region code, lat, lng)
    "Toshkent shahri": ("UZ-TK", 41.3111, 69.2797),
    "Toshkent viloyati": ("UZ-TO", 41.0320, 69.3530),
    "Samarqand viloyati": ("UZ-SA", 39.6542, 66.9597),
    "Andijon viloyati": ("UZ-AN", 40.7821, 72.3442),
    "Farg'ona viloyati": ("UZ-FA", 40.3894, 71.7844),
    "Namangan viloyati": ("UZ-NG", 40.9983, 71.6726),
    "Jizzax viloyati": ("UZ-JI", 40.1158, 67.8422),
    "Sirdaryo viloyati": ("UZ-SI", 40.4897, 68.7842),
    "Navoiy viloyati": ("UZ-NW", 40.1039, 65.3683),
    "Buxoro viloyati": ("UZ-BU", 39.7747, 64.4286),
    "Qashqadaryo viloyati": ("UZ-QA", 38.8606, 65.7890),
    "Surxondaryo viloyati": ("UZ-SU", 37.2242, 67.2783),
    "Xorazm viloyati": ("UZ-XO", 41.5500, 60.6333),
    "Qoraqalpog'iston Respublikasi": ("UZ-QR", 42.4531, 59.6103),
}

#: Hand-checked district centres, lifted from `scripts/seed_districts.py::DISTRICT_CENTERS` and keyed by the
#: region code plus the normalised district name, because the two catalogues spell names differently
#: ("Kattaqorgon" against "Kattaqo'rg'on", "Nukus shahri" against "Nukus").
_DISTRICT_CENTRES: dict[tuple[str, str], tuple[float, float]] = {
    ("UZ-AN", "andijon"): (40.7821, 72.3442),  # Andijon shahri
    ("UZ-AN", "asaka"): (40.6415, 72.2387),  # Asaka
    ("UZ-AN", "baliqchi"): (40.91, 71.85),  # Baliqchi
    ("UZ-AN", "izboskan"): (40.9167, 72.2333),  # Izboskan
    ("UZ-AN", "jalaquduq"): (40.73, 72.62),  # Jalaquduq
    ("UZ-AN", "marhamat"): (40.48, 72.313),  # Marhamat
    ("UZ-AN", "paxtaobod"): (40.9294, 72.5),  # Paxtaobod
    ("UZ-AN", "shahrixon"): (40.713, 72.057),  # Shahrixon
    ("UZ-AN", "xonobod"): (40.8, 73.0),  # Xonobod
    ("UZ-BU", "buxoro"): (39.7747, 64.4286),  # Buxoro shahri
    ("UZ-BU", "gijduvon"): (40.1, 64.6833),  # Gijduvon
    ("UZ-BU", "kogon"): (39.7228, 64.5517),  # Kogon
    ("UZ-BU", "olot"): (39.4167, 63.8),  # Olot
    ("UZ-BU", "qorakol"): (39.5, 63.8333),  # Qorakol
    ("UZ-BU", "romitan"): (39.9333, 64.3833),  # Romitan
    ("UZ-BU", "shofirkon"): (40.12, 64.5),  # Shofirkon
    ("UZ-BU", "vobkent"): (40.0333, 64.5167),  # Vobkent
    ("UZ-FA", "beshariq"): (40.4358, 70.6103),  # Beshariq
    ("UZ-FA", "dangara"): (40.5833, 70.9167),  # Dangara
    ("UZ-FA", "fargona"): (40.3894, 71.7844),  # Fargona shahri
    ("UZ-FA", "margilon"): (40.4711, 71.7247),  # Margilon
    ("UZ-FA", "oltiariq"): (40.3917, 71.4747),  # Oltiariq
    ("UZ-FA", "qoqon"): (40.5286, 70.9425),  # Qoqon
    ("UZ-FA", "quva"): (40.5222, 72.0722),  # Quva
    ("UZ-FA", "rishton"): (40.3561, 71.2847),  # Rishton
    ("UZ-FA", "uchkoprik"): (40.5422, 71.0606),  # Uchkoprik
    ("UZ-FA", "yozyovon"): (40.65, 71.7333),  # Yozyovon
    ("UZ-JI", "dostlik"): (40.5247, 68.0358),  # Dostlik
    ("UZ-JI", "forish"): (40.3667, 67.2333),  # Forish
    ("UZ-JI", "gallaorol"): (40.0333, 67.5833),  # Gallaorol
    ("UZ-JI", "jizzax"): (40.1158, 67.8422),  # Jizzax shahri
    ("UZ-JI", "mirzachol"): (40.5, 68.35),  # Mirzachol
    ("UZ-JI", "paxtakor"): (40.3153, 67.9544),  # Paxtakor
    ("UZ-JI", "sharofrashidov"): (40.15, 67.9),  # Sharof Rashidov
    ("UZ-JI", "zomin"): (39.96, 68.395),  # Zomin
    ("UZ-NG", "chortoq"): (41.07, 71.82),  # Chortoq
    ("UZ-NG", "chust"): (41.0, 71.237),  # Chust
    ("UZ-NG", "kosonsoy"): (41.2561, 71.5508),  # Kosonsoy
    ("UZ-NG", "namangan"): (40.9983, 71.6726),  # Namangan shahri
    ("UZ-NG", "pop"): (40.8736, 71.1089),  # Pop
    ("UZ-NG", "uchqorgon"): (41.1139, 72.0794),  # Uchqorgon
    ("UZ-NG", "uychi"): (41.08, 71.923),  # Uychi
    ("UZ-NG", "yangiqorgon"): (41.1872, 71.7339),  # Yangiqorgon
    ("UZ-NW", "karmana"): (40.1378, 65.375),  # Karmana
    ("UZ-NW", "konimex"): (40.275, 65.15),  # Konimex
    ("UZ-NW", "navoiy"): (40.1039, 65.3683),  # Navoiy shahri
    ("UZ-NW", "nurota"): (40.5614, 65.6886),  # Nurota
    ("UZ-NW", "qiziltepa"): (40.0333, 64.85),  # Qiziltepa
    ("UZ-NW", "tomdi"): (41.75, 64.6167),  # Tomdi
    ("UZ-NW", "uchquduq"): (42.15, 63.5667),  # Uchquduq
    ("UZ-NW", "zarafshon"): (41.5764, 64.2072),  # Zarafshon
    ("UZ-QA", "chiroqchi"): (39.0333, 66.5667),  # Chiroqchi
    ("UZ-QA", "guzor"): (38.6208, 66.2481),  # Guzor
    ("UZ-QA", "kitob"): (39.1214, 66.875),  # Kitob
    ("UZ-QA", "koson"): (39.0375, 65.585),  # Koson
    ("UZ-QA", "muborak"): (39.2553, 65.1528),  # Muborak
    ("UZ-QA", "qarshi"): (38.8606, 65.789),  # Qarshi shahri
    ("UZ-QA", "shahrisabz"): (39.0578, 66.8342),  # Shahrisabz
    ("UZ-QA", "yakkabog"): (38.9767, 66.6889),  # Yakkabog
    ("UZ-QR", "beruniy"): (41.6911, 60.7525),  # Beruniy
    ("UZ-QR", "chimboy"): (42.9294, 59.7697),  # Chimboy
    ("UZ-QR", "ellikqala"): (41.93, 60.72),  # Ellikqala
    ("UZ-QR", "moynoq"): (43.7683, 59.0214),  # Moynoq
    ("UZ-QR", "nukus"): (42.4531, 59.6103),  # Nukus shahri
    ("UZ-QR", "qongirot"): (43.05, 58.85),  # Qongirot
    ("UZ-QR", "tortkol"): (41.55, 61.0),  # Tortkol
    ("UZ-QR", "xojayli"): (42.4, 59.45),  # Xojayli
    ("UZ-SA", "bulungur"): (39.7647, 67.2714),  # Bulungur
    ("UZ-SA", "ishtixon"): (39.9664, 66.4861),  # Ishtixon
    ("UZ-SA", "jomboy"): (39.6986, 67.0939),  # Jomboy
    ("UZ-SA", "kattaqorgon"): (39.8989, 66.2561),  # Kattaqorgon
    ("UZ-SA", "narpay"): (39.9, 65.925),  # Narpay
    ("UZ-SA", "pastdargom"): (39.6564, 66.75),  # Pastdargom
    ("UZ-SA", "payariq"): (39.9944, 66.8611),  # Payariq
    ("UZ-SA", "qoshrabot"): (40.25, 66.6889),  # Qoshrabot
    ("UZ-SA", "samarqand"): (39.6542, 66.9597),  # Samarqand shahri
    ("UZ-SA", "toyloq"): (39.6, 67.0833),  # Toyloq
    ("UZ-SA", "urgut"): (39.4022, 67.2431),  # Urgut
    ("UZ-SI", "boyovut"): (40.5167, 68.95),  # Boyovut
    ("UZ-SI", "guliston"): (40.4897, 68.7842),  # Guliston shahri
    ("UZ-SI", "sardoba"): (40.3667, 68.65),  # Sardoba
    ("UZ-SI", "sayxunobod"): (40.65, 68.8333),  # Sayxunobod
    ("UZ-SI", "shirin"): (40.23, 69.1167),  # Shirin
    ("UZ-SI", "sirdaryo"): (40.8333, 68.6667),  # Sirdaryo
    ("UZ-SI", "xovos"): (40.25, 68.9),  # Xovos
    ("UZ-SI", "yangiyer"): (40.275, 68.8225),  # Yangiyer
    ("UZ-SU", "boysun"): (38.2083, 67.2061),  # Boysun
    ("UZ-SU", "denov"): (38.2667, 67.9),  # Denov
    ("UZ-SU", "jarqorgon"): (37.505, 67.419),  # Jarqorgon
    ("UZ-SU", "qumqorgon"): (37.815, 67.583),  # Qumqorgon
    ("UZ-SU", "sariosiyo"): (38.65, 68.0),  # Sariosiyo
    ("UZ-SU", "sherobod"): (37.67, 67.0),  # Sherobod
    ("UZ-SU", "termiz"): (37.2242, 67.2783),  # Termiz shahri
    ("UZ-SU", "uzun"): (38.3667, 68.05),  # Uzun
    ("UZ-TO", "angren"): (41.0167, 70.1436),  # Angren
    ("UZ-TO", "bekobod"): (40.2208, 69.2697),  # Bekobod
    ("UZ-TO", "chirchiq"): (41.4689, 69.5822),  # Chirchiq
    ("UZ-TO", "nurafshon"): (41.032, 69.353),  # Nurafshon
    ("UZ-TO", "ohangaron"): (40.9064, 69.6383),  # Ohangaron
    ("UZ-TO", "olmaliq"): (40.8447, 69.5983),  # Olmaliq
    ("UZ-TO", "parkent"): (41.2944, 69.6764),  # Parkent
    ("UZ-TO", "qibray"): (41.3897, 69.465),  # Qibray
    ("UZ-TO", "zangiota"): (41.1897, 69.1664),  # Zangiota
    ("UZ-XO", "bogot"): (41.3147, 60.8533),  # Bogot
    ("UZ-XO", "gurlan"): (41.8447, 60.3919),  # Gurlan
    ("UZ-XO", "hazorasp"): (41.3194, 61.0742),  # Hazorasp
    ("UZ-XO", "shovot"): (41.6558, 60.3025),  # Shovot
    ("UZ-XO", "urganch"): (41.55, 60.6333),  # Urganch shahri
    ("UZ-XO", "xiva"): (41.3783, 60.3639),  # Xiva
    ("UZ-XO", "xonqa"): (41.475, 60.785),  # Xonqa
    ("UZ-XO", "yangiariq"): (41.3597, 60.5889),  # Yangiariq
}

#: The lattice step and width from `district_center()`. A real coordinate landing on one of these points to
#: within a metre does not happen; anything that does was generated.
_LATTICE_STEP = 0.08
_LATTICE_WIDTH = 5
_LATTICE_TOLERANCE = 1e-5


def _norm(name: str) -> str:
    """Fold the two catalogues' spellings onto one key."""
    folded = name.lower().replace("‘", "").replace("’", "").replace("'", "").replace("`", "")
    folded = folded.replace("o'", "o").replace("g'", "g")
    for suffix in (" shahri", " tumani", " rayoni"):
        if folded.endswith(suffix):
            folded = folded[: -len(suffix)]
    return re.sub(r"[^a-z]", "", folded)


def _lattice_point(city_lat: float, city_lng: float, display_order: int) -> tuple[float, float]:
    row = (display_order - 1) // _LATTICE_WIDTH
    col = (display_order - 1) % _LATTICE_WIDTH
    return (
        round(city_lat + (row - 1) * _LATTICE_STEP, 6),
        round(city_lng + (col - 2) * _LATTICE_STEP, 6),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. Drop what the generator produced. Only rows whose current value still *is* the lattice point are
    #    touched, so a coordinate somebody corrected by hand survives.
    rows = bind.execute(
        text(
            """
            SELECT g.id, c.name_uz AS city_name, d.display_order, g.center_lat, g.center_lng
              FROM geo_districts g
              JOIN districts d ON d.id = g.legacy_district_id
              JOIN cities c ON c.id = d.city_id
             WHERE g.center_lat IS NOT NULL AND g.center_lng IS NOT NULL
            """
        )
    ).all()
    invented = []
    for row in rows:
        seed = _CITY_CENTRES.get(row.city_name)
        if seed is None or row.display_order is None:
            continue
        lat, lng = _lattice_point(seed[1], seed[2], int(row.display_order))
        if (
            abs(float(row.center_lat) - lat) < _LATTICE_TOLERANCE
            and abs(float(row.center_lng) - lng) < _LATTICE_TOLERANCE
        ):
            invented.append(row.id)
    if invented:
        bind.execute(
            text(
                "UPDATE geo_districts SET center_lat = NULL, center_lng = NULL, updated_at = now() "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": invented},
        )

    # 2. Fill from the hand-checked table. Empty rows only, so a correction made in v2 stays.
    empty = bind.execute(
        text(
            """
            SELECT g.id, r.code AS region_code, g.name_uz
              FROM geo_districts g
              JOIN regions r ON r.id = g.region_id
             WHERE g.center_lat IS NULL
            """
        )
    ).all()
    for row in empty:
        centre = _DISTRICT_CENTRES.get((row.region_code, _norm(row.name_uz)))
        if centre is None:
            continue
        bind.execute(
            text(
                "UPDATE geo_districts SET center_lat = :lat, center_lng = :lng, updated_at = now() "
                "WHERE id = :id AND center_lat IS NULL"
            ),
            {"id": row.id, "lat": Decimal(str(centre[0])), "lng": Decimal(str(centre[1]))},
        )

    # 3. Region centres: the administrative capital, not an average of invented points.
    for code, lat, lng in _CITY_CENTRES.values():
        bind.execute(
            text(
                "UPDATE regions SET center_lat = :lat, center_lng = :lng, updated_at = now() "
                "WHERE code = :code AND (center_lat IS DISTINCT FROM :lat OR center_lng IS DISTINCT FROM :lng)"
            ),
            {"code": code, "lat": Decimal(str(lat)), "lng": Decimal(str(lng))},
        )


def downgrade() -> None:
    """Dev/test only (ADR-0016).

    Nothing is restored. The values this removed were invented, and putting them back would re-introduce the
    defect; the columns themselves belong to 0079/0080.
    """
    return
