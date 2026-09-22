"""Fill the district centres the catalogue is still missing, from the geocoder rather than from memory.

Wave 17.1 established the rule this script exists to keep: a district centre is either a coordinate somebody
checked or it is NULL - never a guess. 105 of the 170 districts were filled from
`scripts/seed_districts.py::DISTRICT_CENTERS`, which is hand-checked. The other 65 have no source in this
repository, and writing them out of my own recollection would be the same defect in a new coat.

A geocoder *is* a source. This asks ours - the same Yandex account the app already uses for
`/geo/reverse-geocode` - for each missing district by name, and writes back only answers that survive three
checks:

* the answer is inside Uzbekistan's bounding box (the same one the CHECK constraint enforces);
* it is within `--max-km` of the district's own region centre, so a match on a same-named place in another
  country or another province is refused rather than stored;
* Yandex's own returned locality name still resembles the district asked for, after the same normalisation
  the catalogue uses for its two spellings.

Anything that fails stays NULL, which is the honest answer and is what the client already handles: the map
opens on the province and asks the person to mark their place.

**It writes nothing by default.** Run it, read the table, then re-run with `--apply`.

    py scripts/geocode_missing_district_centres.py                 # report only
    py scripts/geocode_missing_district_centres.py --apply         # write the accepted rows

Needs `ELCHI_YANDEX_GEOCODER_API_KEY` in the environment; without it the script says so and stops, because
there is nothing it could do that would not be invention.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings  # noqa: E402
from app.services import yandex_maps_service as maps  # noqa: E402

#: Uzbekistan's bounding box, the same one `ck_geo_districts_centre_pair` enforces.
LAT_RANGE = (37.0, 46.0)
LNG_RANGE = (55.0, 74.0)


@dataclass
class Candidate:
    district_id: int
    district: str
    region: str
    region_lat: float
    region_lng: float
    lat: float | None = None
    lng: float | None = None
    returned: str | None = None
    verdict: str = "no answer"


def normalise(name: str) -> str:
    folded = name.lower().replace("‘", "").replace("’", "").replace("'", "").replace("`", "")
    folded = folded.replace("o'", "o").replace("g'", "g")
    for suffix in (" shahri", " tumani", " rayoni"):
        if folded.endswith(suffix):
            folded = folded[: -len(suffix)]
    return re.sub(r"[^a-z]", "", folded)


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(value))


def judge(candidate: Candidate, max_km: float) -> str:
    if candidate.lat is None or candidate.lng is None:
        return "no answer"
    if not (LAT_RANGE[0] <= candidate.lat <= LAT_RANGE[1] and LNG_RANGE[0] <= candidate.lng <= LNG_RANGE[1]):
        return "outside Uzbekistan"
    distance = km_between((candidate.lat, candidate.lng), (candidate.region_lat, candidate.region_lng))
    if distance > max_km:
        return f"{distance:.0f} km from the region centre"
    # `returned` is usually the whole formatted address ("Oʻzbekiston, Toshkent viloyati, Oqqoʻrgʻon
    # tumani"), because Yandex files an Uzbek district under the `area` kind, which
    # `_extract_components` maps to the *region* rather than the district. Comparing the two strings for
    # equality therefore rejected every correct answer - 98 of 99 on the first run here. Containment is
    # what the check was always after: the place Yandex named must still be the district asked for.
    if candidate.returned and normalise(candidate.district) not in normalise(candidate.returned):
        return f"named '{candidate.returned}'"
    return "accepted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the accepted rows (default: report only)")
    parser.add_argument("--max-km", type=float, default=250.0, help="how far from its region centre a district may be")
    parser.add_argument("--pause", type=float, default=0.2, help="seconds between requests")
    args = parser.parse_args()

    if not maps.is_configured():
        print("ELCHI_YANDEX_GEOCODER_API_KEY is not set - nothing to ask, and nothing may be guessed.")
        return 1

    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT d.id, d.name_uz AS district, r.name_uz AS region,
                       r.center_lat AS region_lat, r.center_lng AS region_lng
                  FROM geo_districts d
                  JOIN regions r ON r.id = d.region_id
                 WHERE d.center_lat IS NULL
                   AND d.is_active
                   AND r.center_lat IS NOT NULL
                 ORDER BY r.name_uz, d.name_uz
                """
            )
        ).all()

    if not rows:
        print("Every active district already has a centre.")
        return 0

    candidates: list[Candidate] = []
    for row in rows:
        candidate = Candidate(
            district_id=row.id,
            district=row.district,
            region=row.region,
            region_lat=float(row.region_lat),
            region_lng=float(row.region_lng),
        )
        answer = maps.geocode(f"O'zbekiston, {row.region}, {row.district} tumani", language="uz")
        if answer is None:
            answer = maps.geocode(f"O'zbekiston, {row.region}, {row.district}", language="uz")
        if answer is not None:
            candidate.lat = answer.get("lat")
            candidate.lng = answer.get("lng")
            candidate.returned = answer.get("district") or answer.get("formatted_address")
        candidate.verdict = judge(candidate, args.max_km)
        candidates.append(candidate)
        time.sleep(args.pause)

    accepted = [c for c in candidates if c.verdict == "accepted"]
    print(f"{'district':<24} {'region':<28} {'lat':>10} {'lng':>10}  verdict")
    for candidate in candidates:
        lat = f"{candidate.lat:.5f}" if candidate.lat is not None else "-"
        lng = f"{candidate.lng:.5f}" if candidate.lng is not None else "-"
        print(f"{candidate.district:<24} {candidate.region:<28} {lat:>10} {lng:>10}  {candidate.verdict}")
    print(f"\n{len(accepted)} accepted, {len(candidates) - len(accepted)} left NULL.")

    if not args.apply:
        print("Report only. Re-run with --apply once the table above looks right.")
        return 0

    with engine.begin() as conn:
        for candidate in accepted:
            conn.execute(
                text(
                    "UPDATE geo_districts SET center_lat = :lat, center_lng = :lng, updated_at = now() "
                    "WHERE id = :id AND center_lat IS NULL"
                ),
                {"id": candidate.district_id, "lat": candidate.lat, "lng": candidate.lng},
            )
    print(f"Wrote {len(accepted)} centres.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
