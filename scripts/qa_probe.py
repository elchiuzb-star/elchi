"""Live QA probe: one real user journey through the running API, checked against the database.

This is **not** a replacement for ``pytest`` - the invariants live there, on an isolated PostgreSQL. This script
answers a different question: does the deployed stack, with its real configuration, actually let a person get
from an OTP login to a booking with a commission hold? It only calls HTTP endpoints, then reads the database to
confirm that what the response claimed is what was stored.

It needs a running backend and a **non-production** database with the geo catalogue seeded::

    docker compose -f docker-compose.dev.yml up -d --wait
    py scripts/import_legacy_districts.py --create-regions --apply
    py scripts/seed_geo_fixtures.py --actor-user-id 1          # dev corridor, stops, confirmed routes
    py -m uvicorn app.main:app --port 8001
    QA_BASE=http://127.0.0.1:8001 py scripts/qa_probe.py

What it writes: test accounts with random phone numbers, one vehicle, one trip, one listing, one booking and one
approved top-up. Never point it at production.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8001")
V1, V2 = f"{BASE}/api/v1", f"{BASE}/api/v2"
RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    line = f"{status:5} {name}" + (f" | {detail}" if detail else "")
    sys.stdout.buffer.write(line.encode("utf-8", "replace") + b"\n")
    sys.stdout.flush()


def check(name: str, ok: bool, detail: str = "") -> bool:
    record("PASS" if ok else "FAIL", name, detail)
    return ok


def sql(query: str, **params: Any) -> list[Any]:
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        result = session.execute(text(query), params)
        return result.all() if result.returns_rows else []


def api(method: str, url: str, token: str | None = None, key: str | None = None, **kw: Any) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    return httpx.request(method, url, headers=headers, timeout=60, **kw)


def data_of(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("data") if isinstance(body, dict) else body


def error_code(response: httpx.Response) -> str:
    try:
        return (response.json().get("error") or {}).get("code", "")
    except Exception:  # noqa: BLE001
        return ""


def login(phone: str, role: str) -> str:
    requested = api("POST", f"{V1}/auth/request-otp", json={"phone": phone, "role": role})
    if requested.status_code != 200:
        record("FAIL", f"login[{role}]", f"request-otp {requested.status_code} {requested.text[:120]}")
        return ""
    body = requested.json()
    otp = body.get("dev_otp") or (body.get("data") or {}).get("dev_otp")
    verified = api("POST", f"{V1}/auth/verify-otp", json={"phone": phone, "otp": otp, "role": role})
    if verified.status_code != 200:
        record("FAIL", f"login[{role}]", f"verify-otp {verified.status_code} {verified.text[:160]}")
        return ""
    return verified.json().get("access_token", "")


def phone() -> str:
    return f"+99890{uuid.uuid4().int % 10_000_000:07d}"


def refuse_on_production() -> bool:
    """A probe that creates bookings and approves top-ups must never touch production."""
    from app.modules.platform import service as platform_service
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        if platform_service.is_production(session):
            record("FAIL", "guard", "refusing: this database is marked production")
            return True
    return False


def main() -> int:  # noqa: PLR0915
    if refuse_on_production():
        return 2
    # --- world from the seeded catalogue -----------------------------------------------------------------
    rows = sql(
        "SELECT rv.public_id AS route, sc.public_id AS corridor FROM route_versions rv "
        "JOIN service_corridors sc ON sc.id = rv.corridor_id WHERE rv.status = 'confirmed' ORDER BY rv.id LIMIT 1"
    )
    if not rows:
        record("FAIL", "setup", "no confirmed route version in the database")
        return 1
    from app.contracts.ids import PublicIdPrefix, format_public_id

    route_id = format_public_id(PublicIdPrefix.ROUTE_VERSION, rows[0].route)
    corridor_id = format_public_id(PublicIdPrefix.CORRIDOR, rows[0].corridor)
    stops = sql(
        "SELECT cs.public_id, cs.name_uz, rvs.seq FROM route_version_stops rvs "
        "JOIN corridor_stops cs ON cs.id = rvs.stop_id JOIN route_versions rv ON rv.id = rvs.route_version_id "
        "WHERE rv.public_id = :r ORDER BY rvs.seq",
        r=rows[0].route,
    )
    stop_ids = [format_public_id(PublicIdPrefix.STOP, s.public_id) for s in stops]
    record("INFO", "setup route", f"{corridor_id} | {len(stop_ids)} stops | {[s.name_uz for s in stops]}")
    if len(stop_ids) < 3:
        record("FAIL", "setup", "the confirmed route needs at least three stops for the segment checks")
        return 1

    start = (datetime.now(UTC) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)

    # --- accounts ----------------------------------------------------------------------------------------
    client_phone, driver_phone = phone(), phone()
    client_token = login(client_phone, "client")
    driver_token = login(driver_phone, "driver")
    if not (client_token and driver_token):
        return 1
    check("B1 client and driver sign in with OTP", True)

    # The driver must be an approved driver with an active vehicle before any of this is allowed.
    from sqlalchemy import text as _text

    from app.db.session import SessionLocal

    with SessionLocal() as s:
        s.execute(_text("UPDATE driver_profiles SET verification_status = 'approved' WHERE user_id = "
                        "(SELECT id FROM users WHERE phone = :p)"), {"p": driver_phone})
        s.commit()
    approved = sql("SELECT verification_status FROM driver_profiles WHERE user_id = "
                   "(SELECT id FROM users WHERE phone = :p)", p=driver_phone)
    check("B2 driver profile is approved (setup)", bool(approved) and approved[0][0] == "approved",
          str(approved))

    vehicle = api("POST", f"{V2}/vehicles", token=driver_token, key=str(uuid.uuid4()), json={
        "plate_number": f"{uuid.uuid4().int % 100:02d}A{uuid.uuid4().int % 1000:03d}"
                        f"{chr(65 + uuid.uuid4().int % 26)}{chr(65 + uuid.uuid4().int % 26)}",
        "make_model": "Chevrolet Cobalt",
        "color": "oq",
        "seat_capacity": 4,
        "baggage_capacity_ml": 300_000,
        "cargo_max_weight_g": 50_000,
        "cargo_max_volume_ml": 200_000,
    })
    vehicle_id = (data_of(vehicle) or {}).get("id", "")
    check("B3 driver registers a vehicle", vehicle.status_code in (200, 201) and bool(vehicle_id),
          f"{vehicle.status_code} {vehicle.text[:160]}")
    # A vehicle is usable only once it is verified (spec S17.1); that is staff work.
    from app.contracts.ids import parse_public_id

    with SessionLocal() as s:
        s.execute(_text("UPDATE vehicles SET verification_status = 'approved' WHERE public_id = :v"),
                  {"v": parse_public_id(vehicle_id, PublicIdPrefix.VEHICLE)})
        s.commit()

    trip = api("POST", f"{V2}/trips", token=driver_token, key=str(uuid.uuid4()), json={
        "vehicle_id": vehicle_id,
        "route_version_id": route_id,
        "planned_start_at": start.isoformat(),
        "planned_end_at": (start + timedelta(hours=7)).isoformat(),
        "seat_capacity": 4,
        "max_detour_minutes": 15,
        "max_detour_m": 5000,
        "baggage_capacity_ml": 300_000,
        "stops": [
            {"stop_id": stop_id, "seq": index + 1,
             "planned_arrival_at": (start + timedelta(hours=index)).isoformat(), "dwell_minutes": 5}
            for index, stop_id in enumerate(stop_ids)
        ],
    })
    trip_id = (data_of(trip) or {}).get("id", "")
    check("B4 driver creates a trip on the confirmed route", trip.status_code in (200, 201) and bool(trip_id),
          f"{trip.status_code} {trip.text[:200]}")
    if not trip_id:
        return 1

    # --- C. listing -> proposal -> accept ----------------------------------------------------------------
    listing = api("POST", f"{V2}/listings", token=client_token, key=str(uuid.uuid4()), json={
        "kind": "request",
        "service_type": "passenger",
        "origin_stop_id": stop_ids[0],
        "destination_stop_id": stop_ids[-1],
        "departure_window_start": start.isoformat(),
        "departure_window_end": (start + timedelta(minutes=30)).isoformat(),
        "price_basis": "per_seat",
        "unit_price_minor": 20_000_000,
        "passenger": {"seat_count": 2, "adults": 2},
        "comment": "QA probe",
    })
    listing_id = (data_of(listing) or {}).get("id", "")
    listing_data = data_of(listing) or {}
    check("C1 client creates a 2-seat passenger request", listing.status_code in (200, 201) and bool(listing_id),
          f"{listing.status_code} {listing.text[:200]}")
    check("C2 AC01: the server computes the total itself (2 x 200 000 = 400 000)",
          listing_data.get("total_minor") == 40_000_000,
          f"unit={listing_data.get('unit_price_minor')} total={listing_data.get('total_minor')}")

    # S5/Q5: every v2 service is off until staff enable it for the corridor. Doing it through the real admin
    # API is part of the flow under test - a QA probe that writes the flag straight into the table would prove
    # nothing about the capability check.
    staff = api("POST", f"{V1}/auth/staff-login", json={"username": "qa_super", "password": "QaSuper!2026"})
    staff_token = (staff.json() or {}).get("access_token", "")
    check("C2b super_admin signs in with username and password", staff.status_code == 200 and bool(staff_token),
          f"{staff.status_code} {staff.text[:120]}")
    existing = {
        (row["flag_key"], row["scope_ref"]): row
        for row in (data_of(api("GET", f"{V2}/admin/feature-flags", token=staff_token)) or [])
    }
    for flag in ("passenger_enabled", "corridor_matching_enabled", "tracking_enabled"):
        body = {"enabled": True, "reason": "QA probe: dev corridor"}
        current = existing.get((flag, corridor_id))
        if current:  # optimistic concurrency: an existing row must be addressed by its version
            body["expected_version"] = current["version"]
        flipped = api("PUT", f"{V2}/admin/feature-flags/{flag}/scopes/corridor/{corridor_id}", token=staff_token,
                      key=str(uuid.uuid4()), json=body)
        if flag == "passenger_enabled":
            check("C2c staff enable the service flag for this corridor", flipped.status_code in (200, 201),
                  f"{flipped.status_code} {flipped.text[:160]}")

    published = api("POST", f"{V2}/listings/{listing_id}/publish", token=client_token, key=str(uuid.uuid4()),
                    json={"expected_version": listing_data.get("version", 1)})
    check("C3 client publishes the listing", published.status_code == 200,
          f"{published.status_code} {published.text[:160]}")
    terms_version = (data_of(published) or {}).get("terms_version", 1)

    proposal = api("POST", f"{V2}/listings/{listing_id}/proposals", token=driver_token, key=str(uuid.uuid4()), json={
        "trip_id": trip_id,
        "pickup_stop_id": stop_ids[0],
        "dropoff_stop_id": stop_ids[-1],
        "pickup_window_start": start.isoformat(),
        "pickup_window_end": (start + timedelta(minutes=30)).isoformat(),
        "quantity": 2,
        "price_basis": "per_seat",
        "unit_price_minor": 19_000_000,
        "message": "Yo'lda olib ketaman",
    })
    thread = data_of(proposal) or {}
    thread_id = thread.get("id", "")
    version_id = (thread.get("current_version") or {}).get("id", "")
    check("C4 driver offers a price on the client request", proposal.status_code in (200, 201) and bool(version_id),
          f"{proposal.status_code} {proposal.text[:220]}")
    if not version_id:
        return 1

    # AC05: the author may not accept their own version.
    self_accept = api("POST", f"{V2}/proposals/{thread_id}/accept", token=driver_token, key=str(uuid.uuid4()),
                      json={"proposal_version_id": version_id, "expected_listing_terms_version": terms_version})
    check("C5 AC05: the author cannot accept their own proposal",
          self_accept.status_code in (403, 409), f"{self_accept.status_code} {self_accept.text[:300]}")

    # The client counters; the driver's old version must then be stale (AC04).
    counter = api("POST", f"{V2}/proposals/{thread_id}/counter", token=client_token, key=str(uuid.uuid4()),
                  json={"expected_revision": (thread.get("current_version") or {}).get("revision", 1),
                        "unit_price_minor": 18_000_000, "message": "Shu narxga roziman"})
    counter_data = data_of(counter) or {}
    new_version_id = (counter_data.get("current_version") or {}).get("id", "")
    check("C6 client counters the price", counter.status_code in (200, 201) and bool(new_version_id),
          f"{counter.status_code} {counter.text[:200]}")

    stale = api("POST", f"{V2}/proposals/{thread_id}/accept", token=driver_token, key=str(uuid.uuid4()),
                json={"proposal_version_id": version_id, "expected_listing_terms_version": terms_version})
    check("C7 AC04: accepting the superseded version is refused", stale.status_code == 409 and
          error_code(stale) in ("PROPOSAL_CHANGED", "INVALID_STATE_TRANSITION"),
          f"{stale.status_code} {error_code(stale)}")
    bookings_now = sql("SELECT count(*) FROM bookings")[0][0]

    # --- D. wallet gate ----------------------------------------------------------------------------------
    wallet = data_of(api("GET", f"{V2}/wallet", token=driver_token)) or {}
    record("INFO", "D1 driver wallet before top-up",
           f"posted={wallet.get('posted_balance_minor')} held={wallet.get('held_minor')} "
           f"available={wallet.get('available_minor')} pending={wallet.get('pending_topups_minor')}")

    no_money = api("POST", f"{V2}/proposals/{thread_id}/accept", token=driver_token, key=str(uuid.uuid4()),
                   json={"proposal_version_id": new_version_id, "expected_listing_terms_version": terms_version})
    check("D2 S9.2: an empty commission balance blocks the paid booking",
          no_money.status_code == 409 and error_code(no_money) == "INSUFFICIENT_COMMISSION_BALANCE",
          f"{no_money.status_code} {error_code(no_money)}")
    check("D3 the refused accept created no booking", sql("SELECT count(*) FROM bookings")[0][0] == bookings_now)

    topup = api("POST", f"{V2}/wallet/topups", token=driver_token, key=str(uuid.uuid4()),
                json={"amount_minor": 10_000_000, "method": "bank_transfer", "payer_reference": f"QA-{uuid.uuid4().hex[:8]}"})
    topup_id = (data_of(topup) or {}).get("id", "")
    check("D4 driver files a top-up request", topup.status_code in (200, 201) and bool(topup_id),
          f"{topup.status_code} {topup.text[:160]}")
    after_request = data_of(api("GET", f"{V2}/wallet", token=driver_token)) or {}
    check("D5 AC24: a pending top-up is not money",
          after_request.get("posted_balance_minor") == wallet.get("posted_balance_minor") == 0
          and after_request.get("available_minor") == 0
          and after_request.get("pending_topups_minor") == 10_000_000,
          f"posted={after_request.get('posted_balance_minor')} available={after_request.get('available_minor')} "
          f"pending={after_request.get('pending_topups_minor')}")

    # --- E. finance approves the top-up, then the booking becomes possible ------------------------------
    approve = api("POST", f"{V2}/admin/topups/{topup_id}/approve", token=staff_token, key=str(uuid.uuid4()), json={
        "expected_version": 1,
        "source_type": "bank_statement",
        "source_reference": f"QA-{uuid.uuid4().hex[:10]}",
        "received_amount_minor": 10_000_000,
        "received_at": datetime.now(UTC).isoformat(),
        "note": "QA probe",
    })
    check("E1 finance approves the top-up with a source reference", approve.status_code == 200,
          f"{approve.status_code} {approve.text[:200]}")
    funded = data_of(api("GET", f"{V2}/wallet", token=driver_token)) or {}
    check("E2 S9.4: an approved top-up becomes posted balance and available money",
          funded.get("posted_balance_minor") == 10_000_000 and funded.get("available_minor") == 10_000_000,
          f"posted={funded.get('posted_balance_minor')} available={funded.get('available_minor')}")

    accept_key = str(uuid.uuid4())
    accepted = api("POST", f"{V2}/proposals/{thread_id}/accept", token=driver_token, key=accept_key,
                   json={"proposal_version_id": new_version_id, "expected_listing_terms_version": terms_version})
    booking = data_of(accepted) or {}
    booking_id = booking.get("id", "")
    check("E3 accept creates the booking", accepted.status_code in (200, 201) and bool(booking_id),
          f"{accepted.status_code} {accepted.text[:220]}")
    if not booking_id:
        return 1
    check("E4 AC01: the booking carries the agreed total (2 x 180 000 = 360 000)",
          booking.get("total_minor") == 36_000_000, f"total={booking.get('total_minor')}")

    # The database, not the response, is the evidence.
    rows = sql(
        "SELECT b.service_status, b.cash_status, b.seats, b.total_minor, b.commission_status, b.commission_minor, "
        "(SELECT count(*) FROM booking_allocations a WHERE a.booking_id = b.id AND a.active) AS allocations "
        "FROM bookings b WHERE b.public_id = :p",
        p=parse_public_id(booking_id, PublicIdPrefix.BOOKING),
    )
    check("E5 the booking row exists with its segment allocations", bool(rows) and rows[0].allocations >= 1,
          str(rows[0]) if rows else "-")
    held = data_of(api("GET", f"{V2}/wallet", token=driver_token)) or {}
    expected_fee = round(36_000_000 * 1500 / 10_000)
    check("E6 S9.3: the commission is held, not spent (available = posted - hold)",
          held.get("held_minor") == expected_fee and held.get("available_minor") == 10_000_000 - expected_fee,
          f"held={held.get('held_minor')} available={held.get('available_minor')} expected_fee={expected_fee}")

    replay = api("POST", f"{V2}/proposals/{thread_id}/accept", token=driver_token, key=accept_key,
                 json={"proposal_version_id": new_version_id, "expected_listing_terms_version": terms_version})
    check("E7 AC08: the same idempotency key replays one booking, not two",
          replay.status_code in (200, 201) and (data_of(replay) or {}).get("id") == booking_id
          and sql("SELECT count(*) FROM wallet_holds WHERE booking_id = (SELECT id FROM bookings WHERE public_id = :p)",
                  p=parse_public_id(booking_id, PublicIdPrefix.BOOKING))[0][0] == 1,
          f"{replay.status_code} replay_id={(data_of(replay) or {}).get('id')}")

    reused = api("POST", f"{V2}/proposals/{thread_id}/accept", token=driver_token, key=accept_key,
                 json={"proposal_version_id": new_version_id, "expected_listing_terms_version": terms_version + 1})
    check("E8 AC09: the same key with a different body is refused", reused.status_code == 409
          and error_code(reused) == "IDEMPOTENCY_KEY_REUSED", f"{reused.status_code} {error_code(reused)}")

    # --- F. service lifecycle and the single commission capture ----------------------------------------
    version = (data_of(api("GET", f"{V2}/bookings/{booking_id}", token=driver_token)) or {}).get("version", 1)
    proof = sql(
        "SELECT code_plain FROM booking_proofs WHERE booking_id = "
        "(SELECT id FROM bookings WHERE public_id = :p) AND action = 'board' LIMIT 1",
        p=parse_public_id(booking_id, PublicIdPrefix.BOOKING),
    ) if False else []
    awaiting = api("POST", f"{V2}/bookings/{booking_id}/actions/mark_awaiting_pickup", token=driver_token,
                   key=str(uuid.uuid4()), json={"expected_version": version})
    check("F1 driver moves the booking to awaiting_pickup", awaiting.status_code == 200,
          f"{awaiting.status_code} {awaiting.text[:200]}")
    state = data_of(awaiting) or {}
    record("INFO", "F2 service status after awaiting_pickup", str(state.get("service_status")))

    # The boarding code is the client's; the driver cannot invent it (S11).
    wrong_code = api("POST", f"{V2}/bookings/{booking_id}/actions/board", token=driver_token, key=str(uuid.uuid4()),
                     json={"expected_version": state.get("version", version + 1), "code": "000000"})
    check("F3 S11: a wrong boarding code is refused", wrong_code.status_code in (400, 403, 409, 422),
          f"{wrong_code.status_code} {error_code(wrong_code)}")

    print()
    print(json.dumps({"checks": len(RESULTS), "failed": sum(1 for r in RESULTS if r[0] == "FAIL")}))
    return 1 if any(r[0] == "FAIL" for r in RESULTS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
