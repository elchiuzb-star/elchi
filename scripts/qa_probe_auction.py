"""Live probe of the two-sided auction, in both directions (wave 15 exit criteria).

`qa_probe_ui_journey.py` walks the client's screens. This one asks the narrower question the architecture is
built around: can **either side** open a negotiation, and does a booking only ever come out of an accepted
proposal version?

    A)  passenger request  -> driver proposal  -> passenger counteroffer -> driver accept    -> booking
    B)  driver trip_offer  -> passenger proposal -> driver counteroffer  -> passenger accept -> booking

Both directions are first-class (Q92). Direction B additionally proves the fixture fix: publishing a trip offer
needs `driver_listing_enabled`, which defaults to `false` and had no row in the dev corridor - a driver simply
could not put a journey on the market, and the supply side looked broken for a configuration reason.

It also checks what must stay true around the money at accept (§9): the fee is quoted and frozen on the
version, the hold comes out of *available* and not out of the posted balance, a replayed accept returns the
same booking without holding twice, and cancelling releases.

Needs a running backend and a **non-production** database with the geo fixture seeded::

    py scripts/seed_geo_fixtures.py --actor-user-id 1
    py -m uvicorn app.main:app --port 8000
    QA_BASE=http://127.0.0.1:8000 py scripts/qa_probe_auction.py

What it writes: two accounts with random phone numbers, one vehicle, one trip, three listings, two bookings and
one approved top-up. Never point it at production.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import sys
import uuid
from typing import Any

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8000")
V1, V2 = f"{BASE}/api/v1", f"{BASE}/api/v2"
STAFF_USER = os.environ.get("QA_STAFF_USER", "qa_super")
STAFF_PASSWORD = os.environ.get("QA_STAFF_PASSWORD", "QaSuper!2026")

TZ = dt.timezone(dt.timedelta(hours=5))  # Asia/Tashkent, the display zone of the app
SUFFIX = random.randint(1000, 9999)
PLATE = f"01{random.randint(100, 999)}AUC"

RESULTS: list[tuple[str, str, str]] = []
client = httpx.Client(timeout=30.0)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    line = f"{status:5} {name}" + (f" | {detail}" if detail else "")
    sys.stdout.buffer.write(line.encode("utf-8", "replace") + b"\n")
    sys.stdout.flush()


def check(name: str, ok: bool, detail: str = "") -> bool:
    record("PASS" if ok else "FAIL", name, detail)
    return ok


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


class StepFailed(Exception):
    pass


def data(response: httpx.Response, name: str) -> Any:
    if response.status_code >= 400:
        record("FAIL", name, f"{response.status_code} {response.text[:220]}")
        raise StepFailed(name)
    return response.json()["data"]


def error_code(response: httpx.Response) -> str:
    try:
        return (response.json().get("error") or {}).get("code", "")
    except ValueError:
        return ""


def refuse_on_production() -> bool:
    from app.db.session import SessionLocal
    from app.modules.platform import service as platform_service

    with SessionLocal() as session:
        if platform_service.is_production(session):
            record("FAIL", "guard", "refusing: this database is marked production")
            return True
    return False


def login(phone: str, role: str) -> dict[str, str]:
    body = client.post(f"{V1}/auth/request-otp", json={"phone": phone, "role": role}).json()
    otp = body.get("dev_otp") or (body.get("data") or {}).get("dev_otp")
    if not otp:
        record("FAIL", f"login[{role}]", "no dev_otp in the response (rate limited or not a dev build)")
        raise StepFailed("login")
    verified = client.post(f"{V1}/auth/verify-otp", json={"phone": phone, "otp": otp, "role": role})
    return {"Authorization": f"Bearer {data(verified, f'login[{role}]')['access_token']}"}


def set_flag(sh: dict, corridor_id: str, flag: str, enabled: bool) -> None:
    """Switch one corridor flag through the admin API - the same path an operator uses."""
    rows = data(client.get(f"{V2}/admin/feature-flags", headers=sh, params={"flag_key": flag}), "admin flags")
    current = next((r for r in rows if r["scope_type"] == "corridor" and r["scope_ref"] == corridor_id), None)
    body: dict[str, Any] = {"enabled": enabled, "reason": "auction probe"}
    if current is not None:
        body["expected_version"] = current["version"]
    response = client.put(
        f"{V2}/admin/feature-flags/{flag}/scopes/corridor/{corridor_id}", headers={**sh, **key()}, json=body
    )
    data(response, f"set {flag}={enabled}")


# --- setup ------------------------------------------------------------------------------------------------


def setup() -> dict:
    staff = client.post(f"{V1}/auth/staff-login", json={"username": STAFF_USER, "password": STAFF_PASSWORD})
    if staff.status_code >= 400:
        record("FAIL", "staff login", f"{staff.status_code} {staff.text[:160]}")
        raise StepFailed("staff")
    sh = {"Authorization": f"Bearer {staff.json()['access_token']}"}

    ch = login(f"+99890{SUFFIX}111", "client")
    dh = login(f"+99890{SUFFIX}222", "driver")

    corridor = data(client.get(f"{V2}/corridors", headers=ch), "/corridors")[0]
    flags = data(
        client.get(f"{V2}/feature-flags/effective", params={"corridor_id": corridor["id"]}, headers=ch),
        "effective flags",
    )["flags"]
    check(
        "the dev corridor has the whole marketplace on, driver listings included",
        all(flags[k] for k in ("passenger_enabled", "parcel_enabled", "driver_listing_enabled")),
        str(flags),
    )

    stops = [s for s in data(client.get(f"{V2}/corridors/{corridor['id']}/stops", headers=ch), "stops") if s["is_active"]]
    routes = data(client.get(f"{V2}/corridors/{corridor['id']}/routes", params={"limit": 1}, headers=ch), "routes")
    route = routes[0]

    # driver: profile, documents, approval, vehicle
    client.put(f"{V1}/driver/profile", headers=dh, json={
        "full_name": "Sardor", "car_model": "Cobalt", "car_color": "Oq", "plate_number": PLATE,
    })
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8"
        "0f000101010018dd8db00000000049454e44ae426082"
    )
    for doc_type in ("passport", "selfie", "license", "car_document", "car_photo"):
        uploaded = data(client.post(f"{V1}/files/upload", headers=dh,
                                    files={"file": (f"{doc_type}.png", png, "image/png")},
                                    data={"type": doc_type}), f"upload[{doc_type}]")
        data(client.post(f"{V1}/driver/documents", headers=dh, json={
            "document_type": doc_type, "file_url": uploaded["file_url"],
            "mime_type": uploaded.get("mime_type", "image/png"), "size_bytes": uploaded.get("size_bytes", len(png)),
        }), f"document[{doc_type}]")
    driver_id = (client.get(f"{V1}/driver/profile", headers=dh).json().get("data") or {})["id"]
    client.post(f"{V1}/admin/drivers/{driver_id}/approve", headers=sh, json={"comment": "auction probe"})

    vehicle = data(client.post(f"{V2}/vehicles", headers={**dh, **key()}, json={
        "plate_number": PLATE, "make_model": "Cobalt", "color": "Oq", "seat_capacity": 4,
        "cargo_max_weight_g": 20000, "cargo_max_volume_ml": 100000,
    }), "POST /vehicles")
    vehicle = data(client.post(f"{V2}/admin/vehicles/{vehicle['id']}/verify", headers={**sh, **key()},
                               json={"expected_version": vehicle["version"], "decision": "approve"}), "verify vehicle")

    departure = (dt.datetime.now(TZ) + dt.timedelta(minutes=30)).replace(microsecond=0)
    trip = data(client.post(f"{V2}/trips", headers={**dh, **key()}, json={
        "vehicle_id": vehicle["id"], "route_version_id": route["id"],
        "planned_start_at": departure.isoformat(),
        "planned_end_at": (departure + dt.timedelta(seconds=route["duration_s"])).isoformat(),
        "seat_capacity": 4, "cargo_capacity_weight_g": 20000, "cargo_capacity_volume_ml": 100000,
        "max_detour_minutes": 15, "max_detour_m": 5000, "pickup_wait_minutes": 10,
        "stops": [
            {
                "stop_id": stop["stop_id"], "seq": index + 1,
                "planned_arrival_at": (departure + dt.timedelta(seconds=stop["cumulative_duration_s"])).isoformat(),
                "dwell_minutes": 5,
            }
            for index, stop in enumerate(route["stops"])
        ],
    }), "POST /trips")

    # commission balance: a hold at accept needs available funds (§9.1)
    topup = data(client.post(f"{V2}/wallet/topups", headers={**dh, **key()},
                             json={"amount_minor": 20000000, "method": "bank_transfer"}), "POST /wallet/topups")
    rows = data(client.get(f"{V2}/admin/topups", params={"status": "pending", "limit": 50}, headers=sh), "admin topups")
    row = next(r for r in rows if r["id"] == topup["id"])
    data(client.post(f"{V2}/admin/topups/{topup['id']}/approve", headers={**sh, **key()}, json={
        "expected_version": row["version"], "source_type": "bank_statement",
        "source_reference": f"auction-{SUFFIX}", "received_amount_minor": 20000000,
        "received_at": dt.datetime.now(TZ).isoformat(),
    }), "finance approve top-up")

    return {
        "sh": sh, "ch": ch, "dh": dh, "corridor": corridor, "stops": stops,
        "trip": trip, "departure": departure,
    }


def wallet(dh: dict) -> dict:
    return data(client.get(f"{V2}/wallet", headers=dh), "GET /wallet")


# --- direction A: the client asks, the driver answers -------------------------------------------------------


def direction_a(env: dict) -> None:
    ch, dh, stops, trip = env["ch"], env["dh"], env["stops"], env["trip"]
    departure = env["departure"]
    window_from = (departure - dt.timedelta(minutes=20)).isoformat()
    window_to = (departure + dt.timedelta(minutes=40)).isoformat()
    origin, destination = stops[0], stops[-1]

    record("INFO", "A) passenger request -> driver -> client counter -> driver accept")

    draft = data(client.post(f"{V2}/listings", headers={**ch, **key()}, json={
        "kind": "request", "service_type": "passenger",
        "origin_stop_id": origin["id"], "destination_stop_id": destination["id"],
        "departure_window_start": window_from, "departure_window_end": window_to,
        "price_basis": "per_seat", "unit_price_minor": 30000000,
        "passenger": {"seat_count": 1, "adults": 1},
    }), "A1 POST /listings (passenger request)")
    listing = data(client.post(f"{V2}/listings/{draft['id']}/publish", headers={**ch, **key()},
                               json={"expected_version": draft["version"]}), "A2 publish")
    check("the client publishes a passenger request at their own price", listing["status"] == "published",
          f"{listing['unit_price_minor'] // 100} so'm/o'rin")

    thread = data(client.post(f"{V2}/listings/{listing['id']}/proposals", headers={**dh, **key()}, json={
        "trip_id": trip["id"],
        "pickup_stop_id": origin["id"], "dropoff_stop_id": destination["id"],
        "pickup_window_start": window_from, "pickup_window_end": window_to,
        "price_basis": "per_seat", "quantity": 1, "unit_price_minor": 35000000,
    }), "A3 driver proposes their own price")
    check("the driver answers with a different price", thread["current_version"]["total_minor"] == 35000000,
          f"{35000000 // 100} so'm")

    countered = data(client.post(f"{V2}/proposals/{thread['id']}/counter", headers={**ch, **key()}, json={
        "expected_revision": thread["current_version"]["revision"], "unit_price_minor": 32000000,
    }), "A4 client counters")
    current = countered["current_version"]
    check("the client's counter becomes the current version",
          current["author_side"] == "client" and current["total_minor"] == 32000000,
          f"revision {current['revision']}")

    stale = client.post(f"{V2}/proposals/{thread['id']}/accept", headers={**dh, **key()}, json={
        "proposal_version_id": thread["current_version"]["id"],
        "expected_listing_terms_version": listing["terms_version"],
    })
    check("a superseded version cannot be accepted", stale.status_code >= 400, error_code(stale))

    own = client.post(f"{V2}/proposals/{thread['id']}/accept", headers={**ch, **key()}, json={
        "proposal_version_id": current["id"], "expected_listing_terms_version": listing["terms_version"],
    })
    check("the author cannot accept their own version (AC05)", own.status_code >= 400, error_code(own))

    before = wallet(dh)
    accept_key = key()
    booking = data(client.post(f"{V2}/proposals/{thread['id']}/accept", headers={**dh, **accept_key}, json={
        "proposal_version_id": current["id"], "expected_listing_terms_version": listing["terms_version"],
    }), "A5 driver accepts")
    check("the booking carries the agreed number, not a computed fare (Q90)",
          booking["total_minor"] == 32000000, f"{booking['total_minor'] // 100} so'm")
    check("the booking points at the accepted version",
          booking["accepted_proposal_version_id"] == current["id"], booking["id"])

    after = wallet(dh)
    held = after["held_minor"] - before["held_minor"]
    check("the commission is held out of available, and the posted balance is untouched",
          held > 0 and after["posted_balance_minor"] == before["posted_balance_minor"]
          and after["available_minor"] == before["available_minor"] - held,
          f"held {held // 100} so'm")

    replay = client.post(f"{V2}/proposals/{thread['id']}/accept", headers={**dh, **accept_key}, json={
        "proposal_version_id": current["id"], "expected_listing_terms_version": listing["terms_version"],
    })
    replayed = data(replay, "A6 replayed accept")
    again = wallet(dh)
    check("the same key returns the same booking and holds nothing twice (AC08)",
          replayed["id"] == booking["id"] and again["held_minor"] == after["held_minor"],
          f"held still {again['held_minor'] // 100} so'm")

    env["a_booking"] = booking
    env["a_held"] = held


# --- direction B: the driver offers, the client answers -----------------------------------------------------


def direction_b(env: dict) -> None:
    sh, ch, dh = env["sh"], env["ch"], env["dh"]
    stops, trip, corridor = env["stops"], env["trip"], env["corridor"]
    departure = env["departure"]
    window_from = (departure - dt.timedelta(minutes=20)).isoformat()
    window_to = (departure + dt.timedelta(minutes=40)).isoformat()
    origin, destination = stops[0], stops[-1]

    record("INFO", "B) driver trip_offer -> client -> driver counter -> client accept")

    # The fourth quadrant of Q92: the driver publishes a journey with seats and their own starting price, and
    # the client answers it. Direction A covered `request + passenger`; the parcel request is covered by
    # `qa_probe_ui_journey.py`.
    offer_body = {
        "kind": "trip_offer", "service_type": "passenger", "trip_id": trip["id"],
        "origin_stop_id": origin["id"], "destination_stop_id": destination["id"],
        "departure_window_start": window_from, "departure_window_end": window_to,
        "price_basis": "per_seat", "unit_price_minor": 20000000,
    }

    # The fixture fix, asserted from both sides on **one** draft: only the flag differs between the two
    # attempts. A second draft would hit §5.4 instead (one open trip offer per trip and service) and prove
    # nothing about the flag.
    draft = data(client.post(f"{V2}/listings", headers={**dh, **key()}, json=offer_body), "B1 POST /listings (trip offer)")

    set_flag(sh, corridor["id"], "driver_listing_enabled", False)
    blocked = client.post(f"{V2}/listings/{draft['id']}/publish", headers={**dh, **key()},
                          json={"expected_version": draft["version"]})
    check("with driver_listing_enabled off the trip offer is refused",
          blocked.status_code >= 400 and error_code(blocked) == "FEATURE_DISABLED", error_code(blocked))

    set_flag(sh, corridor["id"], "driver_listing_enabled", True)
    published = client.post(f"{V2}/listings/{draft['id']}/publish", headers={**dh, **key()},
                            json={"expected_version": draft["version"]})
    check("with the flag on the same draft publishes", published.status_code == 200, str(published.status_code))
    offer = data(published, "B2 publish trip offer")

    thread = data(client.post(f"{V2}/listings/{offer['id']}/proposals", headers={**ch, **key()}, json={
        "pickup_stop_id": origin["id"], "dropoff_stop_id": destination["id"],
        "pickup_window_start": window_from, "pickup_window_end": window_to,
        "price_basis": "per_seat", "quantity": 1, "unit_price_minor": 16000000,
    }), "B3 client proposes their own price")
    check("the client answers the driver's offer with their own number",
          thread["current_version"]["author_side"] == "client" and thread["current_version"]["total_minor"] == 16000000,
          f"{16000000 // 100} so'm")

    countered = data(client.post(f"{V2}/proposals/{thread['id']}/counter", headers={**dh, **key()}, json={
        "expected_revision": thread["current_version"]["revision"], "unit_price_minor": 18000000,
    }), "B4 driver counters")
    current = countered["current_version"]
    check("the driver's counter becomes the current version",
          current["author_side"] == "driver" and current["total_minor"] == 18000000,
          f"revision {current['revision']}")

    before = wallet(dh)
    booking = data(client.post(f"{V2}/proposals/{thread['id']}/accept", headers={**ch, **key()}, json={
        "proposal_version_id": current["id"], "expected_listing_terms_version": offer["terms_version"],
    }), "B5 client accepts")
    check("the booking is the driver's last number, agreed by the client",
          booking["total_minor"] == 18000000, f"{booking['total_minor'] // 100} so'm")
    check("the booking points at the accepted version",
          booking["accepted_proposal_version_id"] == current["id"], booking["id"])

    after = wallet(dh)
    held = after["held_minor"] - before["held_minor"]
    check("a second booking holds its own commission on top of the first",
          held > 0 and after["held_minor"] == before["held_minor"] + held, f"held {held // 100} so'm")

    env["b_booking"] = booking
    env["b_held"] = held


def release_on_cancel(env: dict) -> None:
    """A cancelled booking gives the commission back - a hold is not a charge (AC21)."""
    ch, dh = env["ch"], env["dh"]
    booking = env["b_booking"]
    before = wallet(dh)
    cancelled = client.post(f"{V2}/bookings/{booking['id']}/cancel", headers={**ch, **key()}, json={
        "expected_version": booking["version"], "reason_code": "client_changed_plan",
    })
    if cancelled.status_code >= 400:
        record("FAIL", "C1 cancel", f"{cancelled.status_code} {cancelled.text[:160]}")
        return
    after = wallet(dh)
    check("cancelling releases the hold back into available",
          after["held_minor"] == before["held_minor"] - env["b_held"]
          and after["available_minor"] == before["available_minor"] + env["b_held"],
          f"released {env['b_held'] // 100} so'm")


def main() -> int:
    if refuse_on_production():
        return 2
    try:
        env = setup()
        direction_a(env)
        direction_b(env)
        release_on_cancel(env)
    except StepFailed as failure:
        record("INFO", "stopped", f"after {failure}")
    failures = [r for r in RESULTS if r[0] == "FAIL"]
    record("INFO", "summary", f"{len([r for r in RESULTS if r[0] != 'INFO'])} checks, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
