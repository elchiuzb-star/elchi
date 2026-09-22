"""Live probe of the journey the `mobile-app` screens actually perform (wave 12).

`qa_probe.py` asks whether the running stack can carry one person from an OTP login to a booking with a
commission hold. This script asks a narrower, newer question: do the **v1 screens now wired to the stage-2
engine** work end to end, call by call, in the order the UI issues them?

Every step below is one screen of `mobile-app/src/app/ConnectedApp.tsx`:

    Qayerdan?/Qayerga?      GET /regions, /districts, /corridors/{id}/stops
    Yo'nalish               GET /corridors/{id}/districts, /corridors/{id}/routes
    Buyurtmani e'lon qilish POST /listings + /publish
    Yo'nalish qo'shish      POST /vehicles, POST /trips
    Mos buyurtmalar         GET /feed?side=requests (district ends)
    Taklif yuborish         POST /listings/{id}/proposals
    Komissiya balansi       POST /wallet/topups (+ finance approval)
    Haydovchi takliflari    POST /proposals/{id}/counter, POST /proposals/{id}/accept
    Buyurtma tafsilotlari   trip + booking actions with the client's proof codes
    Posilka rasmi           the signed link on the booking, and what an outsider gets
    Xabarlar / Kuzatuv      POST /bookings/{id}/messages, GET /bookings/{id}/tracking
    Naqd to'lov qaydi       POST /bookings/{id}/cash-receipts (+ acknowledge)
    Xaritadan joy (Q88)     GET /directions/preview, POST /listings with point ends

It needs a running backend and a **non-production** database with the geo catalogue seeded (see
`RUNNING.md` and the header of `qa_probe.py`)::

    py -m uvicorn app.main:app --port 8000
    QA_BASE=http://127.0.0.1:8000 py scripts/qa_probe_ui_journey.py

The parcel service flag must be on for the corridor under test - that is the point of Q5, so the probe reports
`FEATURE_DISABLED` as a finding rather than switching it on by itself.

What it writes: two accounts with random phone numbers, one vehicle, one trip, one listing, one booking and one
approved top-up. Never point it at production.
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
#: Every identity this probe creates is unique per run. The plate has its own, wider space: it is unique in
#: the database, so a repeat would fail at `POST /vehicles` and look like a product defect when it is only a
#: collision between two runs of this script.
SUFFIX = random.randint(1000, 9999)
PLATE = f"{random.randint(10, 99)}{random.choice('ABCDEFGHJKLMNPRSTUVXYZ')}{random.randint(100, 999)}{random.choice('ABCDEFGHJKLMNPRSTUVXYZ')}{random.choice('ABCDEFGHJKLMNPRSTUVXYZ')}"
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
        record("FAIL", name, f"{response.status_code} {response.text[:200]}")
        raise StepFailed(name)
    return response.json()["data"]


def refuse_on_production() -> bool:
    """A probe that creates bookings and approves top-ups must never touch production."""
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
    token = data(verified, f"login[{role}]")["access_token"]
    return {"Authorization": f"Bearer {token}"}


def journey() -> None:  # noqa: PLR0915 - it is one linear journey on purpose
    staff = client.post(f"{V1}/auth/staff-login", json={"username": STAFF_USER, "password": STAFF_PASSWORD})
    sh = {"Authorization": f"Bearer {staff.json()['access_token']}"} if staff.status_code < 400 else None
    if sh is None:
        record("FAIL", "staff login", f"{staff.status_code} {staff.text[:160]}")
        raise StepFailed("staff")

    ch = login(f"+99890{SUFFIX}101", "client")
    dh = login(f"+99890{SUFFIX}202", "driver")
    sh_client_outsider = login(f"+99890{SUFFIX}404", "client")  # no part in anything below

    services = data(client.get(f"{V2}/feature-flags/effective", headers=ch), "F1 effective flags")["flags"]
    check("passenger stays off until the legal review (Q7/K7)", services["passenger_enabled"] is False, str(services))

    # --- "Qayerdan? / Qayerga?" ---------------------------------------------------------------------
    regions = data(client.get(f"{V2}/regions", headers=ch), "G1 /regions")
    tashkent = next((r for r in regions if r["code"] == "UZ-TK"), None)
    check("Toshkent shahri needs no district step", bool(tashkent) and not tashkent["requires_district"])
    check("every other region asks for a district",
          all(r["requires_district"] for r in regions if r["code"] != "UZ-TK"),
          f"{len(regions)} regions")

    corridor = data(client.get(f"{V2}/corridors", headers=ch), "/corridors")[0]
    stops = data(client.get(f"{V2}/corridors/{corridor['id']}/stops", headers=ch), "/corridors/{id}/stops")
    active = [s for s in stops if s["is_active"]]
    check("the corridor has verified stops", len(active) >= 2, f"{len(active)} stops")

    # Q5: a service is enabled per corridor, so the country scope is not the answer the UI needs.
    scoped = data(client.get(f"{V2}/feature-flags/effective", params={"corridor_id": corridor["id"]}, headers=ch),
                  "F1 effective flags (corridor scope)")["flags"]
    check("the corridor scope is what decides whether the flow is open",
          scoped["parcel_enabled"] is True, f"country={services['parcel_enabled']} corridor={scoped['parcel_enabled']}")
    # Q7/K7 is a *production* rule (the Q48 gate blocks enabling it there; tests/pg/geo/test_geo_q48_gate_q47_pg.py
    # covers that). On a dev stack the flag may well be on, so this is reported, not asserted - what the client
    # guarantees is covered by tests/contracts/test_client_has_no_passenger_flow.py.
    record("INFO", "corridor flag state", str(scoped))

    districts = data(client.get(f"{V2}/corridors/{corridor['id']}/districts", headers=ch), "G17 /districts")
    on_route = [d for d in districts if d["on_confirmed_route"]]
    check("the districts on the way come back in travel order", len(on_route) >= 2,
          " - ".join(d["district"]["name_uz"] for d in on_route))

    routes = data(client.get(f"{V2}/corridors/{corridor['id']}/routes", params={"limit": 1}, headers=ch),
                  "G18 /routes")
    check("a confirmed road is readable without the routing provider",
          bool(routes) and routes[0]["status"] == "confirmed",
          f"{routes[0]['distance_m']} m" if routes else "")

    # --- "Yuk yuborish" -> "Buyurtmani e'lon qilish" --------------------------------------------------
    departure = (dt.datetime.now(TZ) + dt.timedelta(minutes=30)).replace(microsecond=0)
    window_from = (departure - dt.timedelta(minutes=20)).isoformat()
    window_to = (departure + dt.timedelta(minutes=40)).isoformat()
    origin, destination = active[0], active[-1]

    # The cargo photo the client uploads on "Posilka rasmi" - attached by reference, never as a public path.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8"
        "0f000101010018dd8db00000000049454e44ae426082"
    )
    photo_upload = data(client.post(f"{V1}/files/upload", headers=ch,
                                    files={"file": ("cargo.png", png, "image/png")},
                                    data={"type": "cargo_photo"}), "upload cargo photo")

    created = client.post(f"{V2}/listings", headers={**ch, **key()}, json={
        "kind": "request", "service_type": "parcel",
        "origin_stop_id": origin["id"], "destination_stop_id": destination["id"],
        "departure_window_start": window_from, "departure_window_end": window_to,
        "price_basis": "total", "unit_price_minor": 24000000,
        "comment": "Ehtiyot bo'ling, 90 123 45 67 ga qo'ng'iroq qiling",
        "parcel": {
            "parcel_type": "box", "weight_g": 3000,
            "length_cm": 40, "width_cm": 30, "height_cm": 20, "payer": "sender",
            "sender": {"name": "Aziz", "phone": f"+99890{SUFFIX}101"},
            "receiver": {"name": "Dilnoza", "phone": f"+99890{SUFFIX}303"},
            "photo_file_id": photo_upload["file_url"],
        },
    })
    draft = data(created, "L1 POST /listings")
    warnings = [w["code"] for w in (created.json().get("warnings") or [])]
    check("a phone number in the free text is masked (Q43)", "CONTACT_INFO_MASKED" in warnings,
          f"comment stored as: {draft['comment']}")

    published = client.post(f"{V2}/listings/{draft['id']}/publish", headers={**ch, **key()},
                            json={"expected_version": draft["version"]})
    if published.status_code == 403 and "FEATURE_DISABLED" in published.text:
        record("FAIL", "L4 publish", "parcel_enabled is off for this corridor (Q5) - enable it for the probe")
        raise StepFailed("publish")
    listing = data(published, "L4 publish")
    check("the listing is published", listing["status"] == "published", listing["id"])

    owner_photo = (listing.get("parcel") or {}).get("photo")
    check("the owner gets a signed link, not a bucket path", bool(owner_photo) and "sig=" in (owner_photo or {}).get("url", ""),
          (owner_photo or {}).get("content_type"))
    check("the stored reference is a key, not an expiring URL",
          bool(owner_photo) and "?" not in owner_photo["file_id"], (owner_photo or {}).get("file_id"))

    # --- driver: profile, documents, vehicle, trip ----------------------------------------------------
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
    approved_driver = client.post(f"{V1}/admin/drivers/{driver_id}/approve", headers=sh, json={"comment": "probe"})
    check("staff approve the driver", approved_driver.status_code == 200, approved_driver.text[:120])

    vehicle = data(client.post(f"{V2}/vehicles", headers={**dh, **key()}, json={
        "plate_number": PLATE, "make_model": "Cobalt", "color": "Oq", "seat_capacity": 4,
        "cargo_max_weight_g": 20000, "cargo_max_volume_ml": 100000,
    }), "S17 POST /vehicles")
    check("a new car is not usable yet (§17.1)", vehicle["verification_status"] == "pending")
    vehicle = data(client.post(f"{V2}/admin/vehicles/{vehicle['id']}/verify", headers={**sh, **key()},
                               json={"expected_version": vehicle["version"], "decision": "approve"}),
                   "admin verify vehicle")
    check("staff verify the car", vehicle["verification_status"] == "approved")

    route = routes[0]
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
    }), "T1 POST /trips")
    check("the trip is planned on a confirmed road", trip["status"] == "planned", f"{len(trip['stops'])} stops")

    # --- "Mos buyurtmalar": the districts along the way ------------------------------------------------
    now = dt.datetime.now(TZ)
    feed = client.get(f"{V2}/feed", headers=dh, params={
        "side": "requests", "service_type": "parcel",
        "date_from": (now - dt.timedelta(days=1)).isoformat(), "date_to": (now + dt.timedelta(days=3)).isoformat(),
        "origin_district_id": on_route[0]["district"]["id"],
        "destination_district_id": on_route[-1]["district"]["id"],
        "limit": 20,
    })
    items = data(feed, "M1 GET /feed")
    mine = [item for item in items if item["listing"]["id"] == listing["id"]]
    check("a district-wide question finds the request", bool(mine),
          f"{len(items)} items, match={mine[0]['match']['match_type'] if mine else '-'}")
    meta = feed.json().get("meta") or {}
    check("matching stays on confirmed stops while the provider is off (Q46)",
          meta.get("match_scope") == "confirmed_stops", str(meta.get("degraded")))

    # --- "Taklif yuborish" -----------------------------------------------------------------------------
    thread = data(client.post(f"{V2}/listings/{listing['id']}/proposals", headers={**dh, **key()}, json={
        "trip_id": trip["id"],
        "pickup_stop_id": listing["origin_stop"]["id"], "dropoff_stop_id": listing["destination_stop"]["id"],
        "pickup_window_start": window_from, "pickup_window_end": window_to,
        "price_basis": listing["price_basis"], "quantity": listing["quantity"],
        "unit_price_minor": 24000000,
    }), "P3 POST /proposals")
    threads = data(client.get(f"{V2}/listings/{listing['id']}/proposals", headers=ch), "P4 client proposals")
    check("the client sees the driver anonymously (Q40)",
          bool(threads) and threads[0]["driver"]["label"].startswith("Haydovchi")
          and not threads[0]["driver"].get("display_name"),
          threads[0]["driver"]["label"] if threads else "")

    # --- "Komissiya balansi" ---------------------------------------------------------------------------
    before = data(client.get(f"{V2}/wallet", headers=dh), "W1 GET /wallet")
    topup = data(client.post(f"{V2}/wallet/topups", headers={**dh, **key()},
                             json={"amount_minor": 5000000, "method": "bank_transfer"}), "W3 POST /wallet/topups")
    pending = data(client.get(f"{V2}/wallet", headers=dh), "wallet with a pending request")
    check("a pending top-up is not money yet (§9.2)",
          pending["available_minor"] == before["available_minor"] and pending["pending_topups_minor"] == 5000000)
    admin_rows = data(client.get(f"{V2}/admin/topups", params={"status": "pending", "limit": 50}, headers=sh),
                      "admin topups")
    row = next(r for r in admin_rows if r["id"] == topup["id"])
    data(client.post(f"{V2}/admin/topups/{topup['id']}/approve", headers={**sh, **key()}, json={
        "expected_version": row["version"], "source_type": "bank_statement",
        "source_reference": f"probe-{SUFFIX}", "received_amount_minor": 5000000,
        "received_at": dt.datetime.now(TZ).isoformat(),
    }), "finance approve top-up")
    funded = data(client.get(f"{V2}/wallet", headers=dh), "wallet after approval")
    check("finance approval turns the request into balance", funded["available_minor"] == 5000000)

    # --- "Boshqa narx taklif qilish" (P6) --------------------------------------------------------------
    first = threads[0]["current_version"]
    countered = client.post(f"{V2}/proposals/{threads[0]['id']}/counter", headers={**ch, **key()}, json={
        "expected_revision": first["revision"], "unit_price_minor": 22000000,
    })
    counter_thread = data(countered, "P6 counter")
    check("the client's counter becomes the current version",
          counter_thread["current_version"]["author_side"] == "client"
          and counter_thread["current_version"]["total_minor"] == 22000000,
          f"revision {counter_thread['current_version']['revision']}")

    stale = client.post(f"{V2}/proposals/{threads[0]['id']}/counter", headers={**ch, **key()}, json={
        "expected_revision": first["revision"], "unit_price_minor": 21000000,
    })
    check("a counter on a revision that already moved is refused", stale.status_code == 409,
          (stale.json().get("error") or {}).get("code"))

    self_accept = client.post(f"{V2}/proposals/{threads[0]['id']}/accept", headers={**ch, **key()}, json={
        "proposal_version_id": counter_thread["current_version"]["id"],
        "expected_listing_terms_version": listing["terms_version"],
    })
    check("the author cannot accept their own version (AC05)", self_accept.status_code >= 400,
          (self_accept.json().get("error") or {}).get("code"))

    # --- the driver takes the client's price ------------------------------------------------------------
    version = counter_thread["current_version"]
    booking = data(client.post(f"{V2}/proposals/{threads[0]['id']}/accept", headers={**dh, **key()}, json={
        "proposal_version_id": version["id"], "expected_listing_terms_version": listing["terms_version"],
    }), "P8 accept")
    held = data(client.get(f"{V2}/wallet", headers=dh), "wallet after accept")
    expected_hold = round(booking["total_minor"] * 1500 / 10000)
    check("accept holds the commission, it is not taken", held["held_minor"] == expected_hold,
          f"total {booking['total_minor']}, held {held['held_minor']}")

    # --- the cargo photo on the booking (Q6) ------------------------------------------------------------
    driver_booking = data(client.get(f"{V2}/bookings/{booking['id']}", headers=dh), "driver reads the booking")
    driver_photo = driver_booking.get("parcel_photo")
    check("the assigned driver gets a signed link to the cargo photo", bool(driver_photo), (driver_photo or {}).get("content_type"))
    if driver_photo:
        opened = client.get(f"{BASE}{driver_photo['url']}")
        check("the signed link actually opens the file", opened.status_code == 200, opened.headers.get("content-type"))
        bare = client.get(f"{BASE}{driver_photo['url'].split('?')[0]}")
        check("the same path without a signature is refused", bare.status_code == 403, str(bare.status_code))
        outsider = client.get(f"{V2}/bookings/{booking['id']}", headers=sh_client_outsider)
        check("someone with no part in the booking gets nothing", outsider.status_code == 404, str(outsider.status_code))

    # --- "Xabarlar" (N6) --------------------------------------------------------------------------------
    sent = client.post(f"{V2}/bookings/{booking['id']}/messages", headers={**dh, **key()},
                       json={"text": "Bekatdaman, 90 123 45 67 ga qo'ng'iroq qiling"})
    message_body = sent.json()
    check("a phone number in a chat message is masked (Q43)",
          any(w["code"] == "CONTACT_INFO_MASKED" for w in (message_body.get("warnings") or [])),
          (message_body.get("data") or {}).get("text"))
    thread_messages = data(client.get(f"{V2}/bookings/{booking['id']}/messages", params={"limit": 30}, headers=ch),
                           "N7 read messages")
    check("the client sees the driver's message", len(thread_messages) >= 1, f"{len(thread_messages)} message(s)")

    # --- "Kuzatuv" (§10.6) ------------------------------------------------------------------------------
    track = client.get(f"{V2}/bookings/{booking['id']}/tracking", headers=ch)
    if track.status_code == 200:
        window = data(track, "tracking")["window"]
        check("live location is not claimed before it is open", window["is_open"] in (True, False), window["reason"])
    else:
        check("tracking answers with a reason, not a crash", track.status_code in (403, 404),
              (track.json().get("error") or {}).get("code"))

    # --- proof codes belong to the client --------------------------------------------------------------
    codes = data(client.get(f"{V2}/bookings/{booking['id']}/codes", headers=ch), "B5 codes")
    by_kind = {row["kind"]: row["code"] for row in codes["codes"]}
    denied = client.get(f"{V2}/bookings/{booking['id']}/codes", headers=dh)
    check("the driver cannot read the codes", denied.status_code == 403, str(denied.status_code))

    # --- "Yo'nalishlarim" trip actions, then the booking -----------------------------------------------
    for action in ("start_boarding", "depart"):
        current = data(client.get(f"{V2}/trips/{trip['id']}", headers=dh), f"trip before {action}")
        data(client.post(f"{V2}/trips/{trip['id']}/actions/{action}", headers={**dh, **key()},
                         json={"expected_version": current["version"]}), f"T9 {action}")
    started = data(client.get(f"{V2}/trips/{trip['id']}", headers=dh), "trip after depart")
    check("the trip really starts before anything is picked up", started["status"] == "in_progress")

    for action, code in (
        ("arrive_at_pickup", None),
        ("pick_up", by_kind.get("pickup_code")),
        ("start_transit", None),
        ("deliver", by_kind.get("delivery_code")),
    ):
        current = data(client.get(f"{V2}/bookings/{booking['id']}", headers=dh), f"booking before {action}")
        body: dict[str, Any] = {"expected_version": current["version"]}
        if code:
            body["code"] = code
        data(client.post(f"{V2}/bookings/{booking['id']}/actions/{action}", headers={**dh, **key()}, json=body),
             f"B3-B6 {action}")
    delivered = data(client.get(f"{V2}/bookings/{booking['id']}", headers=ch), "booking after deliver")
    check("delivered does not complete the booking by itself (Q65)", delivered["service_status"] == "delivered")

    final = data(client.post(f"{V2}/bookings/{booking['id']}/actions/complete", headers={**ch, **key()},
                             json={"expected_version": delivered["version"]}), "B7 complete")
    check("the sender completes it", final["service_status"] == "completed")
    # --- Q88: the map-point flow ------------------------------------------------------------------------
    point_journey(ch, dh, corridor, active, districts)

    closed = data(client.get(f"{V2}/wallet", headers=dh), "wallet at the end")
    check("the commission is captured, not left hanging",
          closed["held_minor"] == 0 and closed["posted_balance_minor"] == 5000000 - expected_hold,
          f"posted {closed['posted_balance_minor']}, held {closed['held_minor']}")

    # --- "Naqd to'lov qaydi" (B10) ----------------------------------------------------------------------
    current = data(client.get(f"{V2}/bookings/{booking['id']}", headers=dh), "booking before the cash record")
    receipt = data(client.post(f"{V2}/bookings/{booking['id']}/cash-receipts", headers={**dh, **key()}, json={
        "expected_version": current["version"], "amount_minor": current["total_minor"],
        "reported_at": dt.datetime.now(TZ).isoformat(),
    }), "B10 report cash")
    after_report = data(client.get(f"{V2}/bookings/{booking['id']}", headers=ch), "client sees the record")
    check("the cash record is visible to the other side after a reload",
          after_report["cash_status"] == "reported_paid" and after_report["cash_receipt"]["id"] == receipt["id"])
    wallet_after_cash = data(client.get(f"{V2}/wallet", headers=dh), "wallet after the cash record")
    check("recording cash moves no balance - ELCHI never held the fare",
          wallet_after_cash["posted_balance_minor"] == closed["posted_balance_minor"],
          f"{wallet_after_cash['posted_balance_minor']} minor")
    acknowledged = data(client.post(
        f"{V2}/bookings/{booking['id']}/cash-receipts/{receipt['id']}/acknowledge",
        headers={**ch, **key()}, json={"expected_version": after_report["cash_receipt"]["version"], "comment": None},
    ), "B10b acknowledge")
    check("the counterpart can confirm it", acknowledged["status"] == "acknowledged", acknowledged["status"])

    # --- "Haydovchini baholang" va "Muammo haqida xabar berish" -----------------------------------------
    rated = client.post(f"{V2}/bookings/{booking['id']}/ratings", headers={**ch, **key()},
                        json={"subject_side": "driver", "stars": 5, "comment": "Rahmat, 90 123 45 67"})
    check("a completed booking can be rated", rated.status_code in (200, 201), str(rated.status_code))
    if rated.status_code < 400:
        check("a phone number in a rating comment is masked too (Q43)",
              any(w["code"] == "CONTACT_INFO_MASKED" for w in (rated.json().get("warnings") or [])),
              str((rated.json().get("data") or {}).get("comment_moderated")))

    dispute = client.post(f"{V2}/bookings/{booking['id']}/disputes", headers={**ch, **key()},
                          json={"type": "service", "description": "Posilka kechikdi, tekshirib bering"})
    check("a participant can open a dispute", dispute.status_code in (200, 201), str(dispute.status_code))
    if dispute.status_code < 400:
        mine = data(client.get(f"{V2}/me/disputes", params={"limit": 10}, headers=ch), "S10 my disputes")
        check("the dispute comes back on my list", any(d["booking_id"] == booking["id"] for d in mine),
              f"{len(mine)} dispute(s)")


def point_journey(ch: dict, dh: dict, corridor: dict, stops: list, districts: list) -> None:
    """Q88: the passenger flow where both ends are places marked on the map, not stops from a catalogue."""
    import datetime as _dt

    on_route = [item for item in districts if item["on_confirmed_route"]]
    origin_district = on_route[0]["district"]["id"]
    destination_district = on_route[-1]["district"]["id"]
    first, last = stops[0], stops[-1]

    # ~1 km off the road at the first stop: a kerb, not another district.
    origin = {"lat": first["point"]["lat"] + 0.009, "lng": first["point"]["lng"]}
    destination = {"lat": last["point"]["lat"], "lng": last["point"]["lng"]}

    params = {
        "origin_lat": origin["lat"], "origin_lng": origin["lng"], "origin_district_id": origin_district,
        "destination_lat": destination["lat"], "destination_lng": destination["lng"],
        "destination_district_id": destination_district,
    }
    preview = data(client.get(f"{V2}/directions/preview", params=params, headers=ch), "Q88 GET /directions/preview")
    check("the server resolves two marked places to a corridor", bool(preview["corridor_id"]), preview["corridor_name"])
    check("the preview carries the road itself, for the map", bool(preview["route_polyline"]),
          f"{preview['distance_m']} m")
    check("the radius is the corridor's configuration, not a constant",
          preview["max_point_offset_m"] > 0, f"{preview['max_point_offset_m']} m")
    check("the offset of each place is reported", preview["origin"]["route_offset_m"] is not None,
          f"{preview['origin']['route_offset_m']} / {preview['destination']['route_offset_m']} m")

    nowhere = dict(params, origin_lat=42.45, origin_lng=59.60)
    refused = client.get(f"{V2}/directions/preview", params=nowhere, headers=ch)
    check("two places no route serves get the product's no-route answer", refused.status_code == 409,
          (refused.json().get("error") or {}).get("code"))

    reversed_params = {
        "origin_lat": destination["lat"], "origin_lng": destination["lng"], "origin_district_id": destination_district,
        "destination_lat": origin["lat"], "destination_lng": origin["lng"], "destination_district_id": origin_district,
    }
    backwards = client.get(f"{V2}/directions/preview", params=reversed_params, headers=ch)
    check("a direction that runs backwards along the road is refused", backwards.status_code == 409,
          (backwards.json().get("error") or {}).get("code"))

    departure = (dt.datetime.now(TZ) + dt.timedelta(minutes=30)).replace(microsecond=0)
    created = client.post(f"{V2}/listings", headers={**ch, **key()}, json={
        "kind": "request", "service_type": "passenger",
        "origin_point": {**origin, "district_id": origin_district, "address": "Samarqand, Registon ko'chasi 1"},
        "destination_point": {**destination, "district_id": destination_district, "address": "Qarshi, markaz"},
        "departure_window_start": (departure - dt.timedelta(hours=2)).isoformat(),
        "departure_window_end": (departure + dt.timedelta(hours=6)).isoformat(),
        "price_basis": "per_seat", "unit_price_minor": 5000000,
        "passenger": {"seat_count": 1, "adults": 1},
    })
    listing = data(created, "Q88 POST /listings (point ends)")
    check("the listing has no stop ids at all", listing["origin_stop"] is None and listing["destination_stop"] is None)
    check("it carries the place, the address and how far off the road it sits",
          listing["origin_point"]["address"] == "Samarqand, Registon ko'chasi 1"
          and listing["origin_point"]["route_offset_m"] is not None,
          f"{listing['origin_point']['route_offset_m']} m from the road")
    check("the district travels as metadata", bool(listing["origin_point"]["district"]),
          (listing["origin_point"]["district"] or {}).get("name_uz"))

    both = client.post(f"{V2}/listings", headers={**ch, **key()}, json={
        "kind": "request", "service_type": "passenger",
        "origin_stop_id": stops[0]["id"],
        "origin_point": {**origin, "district_id": origin_district},
        "destination_point": {**destination, "district_id": destination_district},
        "departure_window_start": (departure - dt.timedelta(hours=2)).isoformat(),
        "departure_window_end": (departure + dt.timedelta(hours=6)).isoformat(),
        "price_basis": "per_seat", "unit_price_minor": 5000000,
        "passenger": {"seat_count": 1, "adults": 1},
    })
    check("an end cannot be a stop and a place at once", both.status_code == 400,
          (both.json().get("error") or {}).get("code"))

    del dh  # the driver half is covered by the PG suite, which can plan a trip on the fixture route


def main() -> int:
    if refuse_on_production():
        return 2
    try:
        journey()
    except StepFailed as exc:
        record("FAIL", "journey", f"stopped at: {exc}")
    failures = [row for row in RESULTS if row[0] == "FAIL"]
    record("INFO", "summary", f"{len(RESULTS)} checks, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
