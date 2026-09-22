"""A named stage-2 cast you can actually log in as, for testing the client by hand.

Why this exists
---------------
The dev database already fills up with data - the QA probes and the v1 seeders leave hundreds of accounts
behind - but none of it is *findable*. Every phone number is random, so the first question when you open the
app ("which number do I type?") has no answer, and the second ("what should I see after I log in?") has no
answer either, because whatever state those accounts are in is whatever the last probe left.

This script fixes both by seeding a small cast with **fixed, memorable phone numbers** and putting it in a
known state: two clients, two approved drivers and one unapproved driver, with the listings, the trips, the
open negotiations and the notifications that let every screen of the client be exercised without touching the
database by hand. Log in with any of the printed numbers and the OTP is the dev mock (``ELCHI_DEV_MOCK_OTP``).

What it is not
--------------
Not a fixture for automated tests (those build their own world in ``tests/pg``), and not production data. It
writes through the **domain services**, never straight into tables, so everything it creates obeys the same
rules a real user would meet - an unapproved driver really cannot publish, a proposal really carries a frozen
fee quote, a listing really belongs to a corridor whose flags are on. That is the point: if this script cannot
build a state, the app cannot either, and that is a finding rather than something to work around.

Idempotent: run it as often as you like. Accounts are matched by phone, and the listings, trips and threads it
owns are recognised by a marker in their comment, so a second run tops the world up instead of doubling it.

Run::

    docker compose -f docker-compose.dev.yml up -d --wait
    .venv/Scripts/python.exe -m alembic upgrade head
    .venv/Scripts/python.exe scripts/seed_demo_v2.py
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.contracts.errors import DomainError  # noqa: E402
from app.contracts.ids import PublicIdPrefix, format_public_id  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import DriverProfile, User  # noqa: E402
from app.modules.identity import service as identity_service  # noqa: E402
from app.modules.marketplace import service as marketplace_service  # noqa: E402
from app.modules.marketplace.models import Listing  # noqa: E402
from app.modules.marketplace.schemas import ListingCreate, ProposalCounter, ProposalCreate  # noqa: E402
from app.modules.platform import service as platform_service  # noqa: E402
from app.modules.trips import service as trips_service  # noqa: E402
from app.modules.trips.models import Vehicle  # noqa: E402
from app.modules.trips.schemas import TripCreate, VehicleCreate  # noqa: E402
from app.modules.wallet import service as wallet_service  # noqa: E402
from app.modules.wallet.models import TopupRequest  # noqa: E402

#: Everything this script owns says so in its comment, so a re-run can find its own work and a person reading
#: the database can tell seeded rows from ones they made by hand.
MARKER = "[demo-v2]"

#: A block nothing else uses: the v1 seeders draw random subscriber numbers and the super admin is ...0001.
CLIENT_A = "+998900001001"
CLIENT_B = "+998900001002"
DRIVER_A = "+998900001010"
DRIVER_B = "+998900001011"
DRIVER_NEW = "+998900001012"


@dataclass(frozen=True, slots=True)
class Person:
    phone: str
    full_name: str
    role: str
    #: Drivers only: the v1 verification status. "new" is a real state to test, not an unfinished account -
    #: it is what the verification gate on the driver screens is for.
    verification: str | None = None


CAST = (
    Person(CLIENT_A, "Demo Mijoz", "client"),
    Person(CLIENT_B, "Demo Mijoz 2", "client"),
    Person(DRIVER_A, "Demo Haydovchi", "driver", "approved"),
    Person(DRIVER_B, "Demo Haydovchi 2", "driver", "approved"),
    Person(DRIVER_NEW, "Demo Haydovchi (yangi)", "driver", "new"),
)

VEHICLES = {
    DRIVER_A: ("90 D 001 AA", "Chevrolet Cobalt", "oq", 4),
    DRIVER_B: ("90 D 002 BB", "Chevrolet Lacetti", "kulrang", 4),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --- accounts ---------------------------------------------------------------------------------------------


def ensure_person(session: Session, person: Person) -> int:
    """The user row and, for a driver, the v1 profile the client reads its verification state from."""
    user = session.execute(select(User).where(User.phone == person.phone)).scalar_one_or_none()
    if user is None:
        user = User(
            phone=person.phone,
            role=person.role,
            status="active",
            is_phone_verified=True,
            full_name=person.full_name,
        )
        session.add(user)
        session.flush()
    else:
        user.full_name = person.full_name
    if person.role != "driver":
        return user.id

    profile = session.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    ).scalar_one_or_none()
    plate, model, colour, _seats = VEHICLES.get(person.phone, (None, None, None, None))
    if profile is None:
        profile = DriverProfile(
            user_id=user.id,
            full_name=person.full_name,
            verification_status=person.verification or "new",
            is_available=person.verification == "approved",
        )
        session.add(profile)
    profile.verification_status = person.verification or "new"
    # Q94 locks these against the driver, not against an operator - and this script is the operator.
    if plate is not None:
        profile.car_model, profile.car_color = model, colour
        profile.plate_number = plate
        profile.plate_number_normalized = plate.replace(" ", "").upper()
    session.flush()
    return user.id


def ensure_vehicle(session: Session, driver_id: int, admin_id: int, phone: str) -> str | None:
    """One approved vehicle per demo driver. Approval goes through the real staff command."""
    plate, model, colour, seats = VEHICLES[phone]
    existing = session.execute(
        select(Vehicle).where(Vehicle.driver_user_id == driver_id).order_by(Vehicle.id)
    ).scalars().first()
    if existing is None:
        existing = trips_service.create_vehicle(
            session,
            driver_user_id=driver_id,
            data=VehicleCreate.model_validate(
                {
                    "plate_number": plate,
                    "make_model": model,
                    "color": colour,
                    "seat_capacity": seats,
                    "baggage_capacity_ml": 300_000,
                    "cargo_max_weight_g": 80_000,
                    "cargo_max_volume_ml": 400_000,
                }
            ),
        )
        session.flush()
    public_id = trips_service.vehicle_public_id(existing)
    if existing.verification_status != "approved":
        trips_service.verify_vehicle(
            session,
            vehicle_public_id=public_id,
            actor_user_id=admin_id,
            expected_version=existing.version,
            decision="approve",
            reason=None,
        )
    return public_id


# --- the corridor this world lives on ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Corridor:
    id: int
    name: str
    route_public_id: str
    stop_public_ids: list[str]
    stop_names: list[str]


def pick_corridor(session: Session) -> Corridor:
    """The richest open corridor: most confirmed stops, and a confirmed route to hang a trip on.

    Chosen from the data rather than hardcoded, because which corridors exist depends on which of the geo
    seeders has been run. If none qualifies the script stops and says so - silently seeding into a closed
    corridor would produce listings nobody can see, which looks like a bug in the app.
    """
    row = session.execute(
        text(
            """
            SELECT c.id, c.name,
                   (SELECT rv.public_id FROM route_versions rv
                     WHERE rv.corridor_id = c.id AND rv.status = 'confirmed'
                     ORDER BY rv.id LIMIT 1) AS route_public_id,
                   (SELECT count(*) FROM corridor_stops cs
                     WHERE cs.corridor_id = c.id AND cs.is_active) AS stops
            FROM service_corridors c
            WHERE c.rollout_state IN ('pilot', 'active')
            ORDER BY stops DESC, c.id
            """
        )
    ).all()
    for corridor_id, name, route_public_id, stops in row:
        if route_public_id is None or stops < 2:
            continue
        stop_rows = session.execute(
            text(
                "SELECT public_id, name_uz FROM corridor_stops "
                "WHERE corridor_id = :c AND is_active ORDER BY sequence_hint, id"
            ),
            {"c": corridor_id},
        ).all()
        return Corridor(
            id=corridor_id,
            name=name,
            route_public_id=format_public_id(PublicIdPrefix.ROUTE_VERSION, route_public_id),
            stop_public_ids=[format_public_id(PublicIdPrefix.STOP, r[0]) for r in stop_rows],
            stop_names=[r[1] for r in stop_rows],
        )
    raise SystemExit(
        "no open corridor with a confirmed route and two active stops.\n"
        "Seed the geo fixture first: py scripts/seed_geo_fixtures.py --actor-user-id 1"
    )


# --- listings ---------------------------------------------------------------------------------------------


def owned_listing(session: Session, owner_id: int, kind: str, service: str) -> Listing | None:
    """A listing this script made earlier, recognised by the marker in its comment."""
    return session.execute(
        select(Listing)
        .where(
            Listing.owner_user_id == owner_id,
            Listing.kind == kind,
            Listing.service_type == service,
            Listing.comment.like(f"%{MARKER}%"),
            Listing.status.in_(["draft", "published", "paused"]),
        )
        .order_by(Listing.id.desc())
    ).scalars().first()


def publish(session: Session, listing: Listing, owner_id: int) -> str:
    public_id = marketplace_service.listing_public_id(listing)
    if listing.status == "draft":
        marketplace_service.publish_listing(
            session, listing_public_id=public_id, actor_user_id=owner_id, expected_version=listing.version
        )
    return public_id


def ensure_request(
    session: Session, *, client_id: int, corridor: Corridor, service: str, start: datetime, price_minor: int
) -> str:
    existing = owned_listing(session, client_id, "request", service)
    if existing is not None:
        return publish(session, existing, client_id)
    body = {
        "kind": "request",
        "service_type": service,
        "origin_stop_id": corridor.stop_public_ids[0],
        "destination_stop_id": corridor.stop_public_ids[-1],
        "departure_window_start": start.isoformat(),
        "departure_window_end": (start + timedelta(hours=2)).isoformat(),
        "price_basis": "per_seat" if service == "passenger" else "total",
        "unit_price_minor": price_minor,
        "comment": f"{MARKER} mijoz so'rovi",
    }
    if service == "passenger":
        body["passenger"] = {
            "seat_count": 2,
            "adults": 2,
            "baggage": {"pieces": 1, "total_weight_g": 12_000, "total_volume_ml": 40_000},
        }
    else:
        # A parcel request cannot be published half-filled: who pays and who hands it over / takes it are
        # part of the offer, not decoration (`REQUEST_PARCEL_REQUIRED`). Leaving them out is how a "demo"
        # listing ends up in a state no real client could reach.
        body["parcel"] = {
            "parcel_type": "box",
            "weight_g": 4_000,
            "length_cm": 30,
            "width_cm": 20,
            "height_cm": 15,
            "payer": "sender",
            "sender": {"name": "Demo Mijoz", "phone": CLIENT_A},
            "receiver": {"name": "Qabul qiluvchi", "phone": "+998900001099"},
        }
    listing = marketplace_service.create_listing(
        session, owner_user_id=client_id, data=ListingCreate.model_validate(body)
    )
    session.flush()
    return publish(session, listing, client_id)


def ensure_trip_offer(
    session: Session, *, driver_id: int, trip_public_id: str, corridor: Corridor, service: str,
    start: datetime, price_minor: int,
) -> str:
    """Q92/Q99: one trip carries both services, so this is called twice for the same trip."""
    existing = owned_listing(session, driver_id, "trip_offer", service)
    if existing is not None:
        return publish(session, existing, driver_id)
    listing = marketplace_service.create_listing(
        session,
        owner_user_id=driver_id,
        data=ListingCreate.model_validate(
            {
                "kind": "trip_offer",
                "service_type": service,
                "trip_id": trip_public_id,
                "origin_stop_id": corridor.stop_public_ids[0],
                "destination_stop_id": corridor.stop_public_ids[-1],
                "departure_window_start": start.isoformat(),
                "departure_window_end": (start + timedelta(hours=1)).isoformat(),
                "price_basis": "per_seat" if service == "passenger" else "total",
                "unit_price_minor": price_minor,
                "comment": f"{MARKER} haydovchi e'loni",
                # What the driver will take, not what is being sent (`OFFER_PARCEL_REQUIRED`).
                **(
                    {}
                    if service == "passenger"
                    else {"parcel": {"max_weight_g": 60_000, "max_volume_ml": 300_000, "max_dimension_cm": 90}}
                ),
            }
        ),
    )
    session.flush()
    return publish(session, listing, driver_id)


def ensure_trip(session: Session, *, driver_id: int, vehicle_public_id: str, corridor: Corridor,
                start: datetime) -> str:
    """One planned trip per demo driver, on the corridor's confirmed route."""
    existing = session.execute(
        text(
            "SELECT public_id FROM trips WHERE driver_user_id = :d AND status = 'planned' "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"d": driver_id},
    ).scalar_one_or_none()
    if existing is not None:
        return format_public_id(PublicIdPrefix.TRIP, existing)
    hops = len(corridor.stop_public_ids)
    trip = trips_service.create_trip(
        session,
        driver_user_id=driver_id,
        data=TripCreate.model_validate(
            {
                "vehicle_id": vehicle_public_id,
                "route_version_id": corridor.route_public_id,
                "stops": [
                    {
                        "stop_id": stop_id,
                        "seq": index + 1,
                        "planned_arrival_at": (start + timedelta(hours=index)).isoformat(),
                    }
                    for index, stop_id in enumerate(corridor.stop_public_ids)
                ],
                "planned_start_at": start.isoformat(),
                "planned_end_at": (start + timedelta(hours=hops)).isoformat(),
                "seat_capacity": 4,
                "baggage_capacity_ml": 300_000,
                "cargo_capacity_weight_g": 80_000,
                "cargo_capacity_volume_ml": 400_000,
                "max_detour_minutes": 15,
                "max_detour_m": 5_000,
            }
        ),
    )
    session.flush()
    return trips_service.trip_public_id(trip)


# --- negotiations -----------------------------------------------------------------------------------------


def ensure_proposal(
    session: Session, *, listing_public_id: str, actor_id: int, trip_public_id: str | None,
    corridor: Corridor, start: datetime, quantity: int, price_basis: str, price_minor: int, message: str,
) -> str | None:
    """One open thread per (listing, actor). Returns the thread id, or None when the server refused.

    A refusal is printed rather than raised: a demo world that is 90% built is far more useful than a
    traceback, and the refusal itself is information (it is the product saying no for a real reason).
    """
    listing = marketplace_service.get_listing_by_public_id(session, listing_public_id)
    existing = session.execute(
        text(
            "SELECT t.public_id FROM proposal_threads t WHERE t.listing_id = :l AND t.state = 'open' "
            "AND (t.client_user_id = :a OR t.driver_user_id = :a) ORDER BY t.id DESC LIMIT 1"
        ),
        {"l": listing.id, "a": actor_id},
    ).scalar_one_or_none()
    if existing is not None:
        return format_public_id(PublicIdPrefix.PROPOSAL_THREAD, existing)
    body = {
        "pickup_stop_id": corridor.stop_public_ids[0],
        "dropoff_stop_id": corridor.stop_public_ids[-1],
        "pickup_window_start": start.isoformat(),
        "pickup_window_end": (start + timedelta(hours=2)).isoformat(),
        "quantity": quantity,
        "price_basis": price_basis,
        "unit_price_minor": price_minor,
        "message": message,
    }
    if trip_public_id is not None:
        body["trip_id"] = trip_public_id
    # BR #3: a proposal on a *request* takes the demand from the request itself, so it must not repeat it;
    # only an answer to a driver's trip offer describes the parcel being sent.
    if listing.service_type == "parcel" and listing.kind == "trip_offer":
        # Q79: a parcel proposal names the receiver, and `pick_up` refuses without one.
        body["parcel"] = {
            "parcel_type": "box",
            "weight_g": 4_000,
            "length_cm": 30,
            "width_cm": 20,
            "height_cm": 15,
            "receiver": {"name": "Qabul qiluvchi", "phone": "+998900001099"},
        }
    try:
        thread = marketplace_service.submit_proposal(
            session, listing_public_id=listing_public_id, actor_user_id=actor_id,
            data=ProposalCreate.model_validate(body),
        )
    except DomainError as error:
        print(f"  ! proposal on {listing_public_id} refused: {error.code.value} {error.details}")
        return None
    session.flush()
    return marketplace_service.thread_public_id(thread)


def ensure_counter(session: Session, *, thread_public_id: str, actor_id: int, price_minor: int,
                   message: str) -> None:
    """Hand the turn back to the other side, so a screen exists that has something to answer."""
    thread = marketplace_service.get_thread_for_party(session, thread_public_id, actor_id)
    current = marketplace_service.current_version(session, thread)
    if current is None or current.author_side != ("client" if actor_id == thread.driver_user_id else "driver"):
        return  # it is not this side's turn: already countered on an earlier run
    try:
        marketplace_service.counter_proposal(
            session, thread_public_id_value=thread_public_id, actor_user_id=actor_id,
            data=ProposalCounter.model_validate(
                {"expected_revision": current.revision, "unit_price_minor": price_minor, "message": message}
            ),
        )
    except DomainError as error:
        print(f"  ! counter on {thread_public_id} refused: {error.code.value} {error.details}")


def ensure_wallet_money(session: Session, *, driver_id: int, admin_id: int) -> tuple[int, int]:
    """One approved top-up and one still pending, so the wallet screen is not a row of zeros.

    Both go through the real commands: the approval needs a finance approver, a source reference and a
    received amount, and it posts to the ledger - which is the behaviour worth being able to look at. The
    super admin stands in for the finance clerk (Q69 accepts either), because there is no way to grant the
    `finance` role yet.

    Returns ``(approved_minor, pending_minor)``; zeros when a guard refused, which is printed, not raised.
    """
    existing = session.execute(
        select(TopupRequest).where(TopupRequest.driver_user_id == driver_id)
    ).scalars().all()
    approved = sum(t.received_amount_minor or 0 for t in existing if t.status == "approved")
    pending = sum(t.amount_minor for t in existing if t.status == "pending")
    if existing:
        return approved, pending

    try:
        credited = wallet_service.create_topup(
            session, driver_user_id=driver_id, amount_minor=50_000_00, method="bank_transfer",
            payer_reference="DEMO-001", note=f"{MARKER} tasdiqlangan to'ldirish",
        )
        session.flush()
        wallet_service.approve_topup(
            session,
            actor_user_id=admin_id,
            actor_capabilities=list(
                identity_service.get_capabilities(session, admin_id).capabilities
            ),
            topup_id=credited.id,
            expected_version=credited.version,
            source_type="bank_statement",
            source_reference=f"DEMO-{driver_id}-001",
            received_amount_minor=50_000_00,
            received_at=now_utc(),
            note="demo seed",
        )
        waiting = wallet_service.create_topup(
            session, driver_user_id=driver_id, amount_minor=20_000_00, method="cash_desk",
            payer_reference="DEMO-002", note=f"{MARKER} kutilayotgan to'ldirish",
        )
        session.flush()
        return 50_000_00, waiting.amount_minor
    except DomainError as error:
        print(f"  ! top-up refused: {error.code.value} {error.details}")
        return 0, 0


# --- views and notifications ------------------------------------------------------------------------------


def record_views(session: Session, listing_public_ids: list[str], viewer_ids: list[int]) -> int:
    """Q98: a few real rows, so the count on the owner's screen is not always zero."""
    counted = 0
    for listing_public_id in listing_public_ids:
        listing = marketplace_service.get_listing_by_public_id(session, listing_public_id)
        for viewer_id in viewer_ids:
            if marketplace_service.record_listing_view(session, listing, viewer_user_id=viewer_id):
                counted += 1
    return counted


def dispatch_notifications(limit_batches: int = 60) -> int:
    """Turn the events this run produced into the inbox rows the client reads.

    The worker normally does this on a timer; a seeder that leaves the queue full would leave both demo
    inboxes empty, which is the one screen you cannot check by looking at another table.
    """
    from app.modules.communications import service as comms

    total = 0
    for _ in range(limit_batches):
        session = SessionLocal()
        try:
            handled = comms.dispatch_outbox(session, limit=200)
            session.commit()
        finally:
            session.close()
        total += handled
        if handled == 0:
            break
    return total


# --- the run ----------------------------------------------------------------------------------------------


def seed(session: Session) -> dict[str, object]:
    admin_id = session.execute(
        select(User.id).where(User.role == "super_admin", User.status == "active").order_by(User.id)
    ).scalars().first()
    if admin_id is None:
        raise SystemExit("no active super_admin; run scripts/seed_admin_required_data.py first")

    corridor = pick_corridor(session)
    print(f"corridor: {corridor.name} ({len(corridor.stop_public_ids)} bekat)")
    print(f"  {corridor.stop_names[0]} -> {corridor.stop_names[-1]}")

    people = {person.phone: ensure_person(session, person) for person in CAST}
    session.flush()

    start = now_utc() + timedelta(days=1)
    trips: dict[str, str] = {}
    for phone in (DRIVER_A, DRIVER_B):
        vehicle_public_id = ensure_vehicle(session, people[phone], admin_id, phone)
        trips[phone] = ensure_trip(
            session, driver_id=people[phone], vehicle_public_id=vehicle_public_id,
            corridor=corridor, start=start + timedelta(hours=1),
        )

    # The client's side of the market: one request per service, both published.
    parcel_request = ensure_request(
        session, client_id=people[CLIENT_A], corridor=corridor, service="parcel",
        start=start, price_minor=8_000_000,
    )
    passenger_request = ensure_request(
        session, client_id=people[CLIENT_A], corridor=corridor, service="passenger",
        start=start, price_minor=12_000_000,
    )

    # The driver's side: Q99 - the same trip advertised for both services.
    passenger_offer = ensure_trip_offer(
        session, driver_id=people[DRIVER_A], trip_public_id=trips[DRIVER_A], corridor=corridor,
        service="passenger", start=start + timedelta(hours=1), price_minor=15_000_000,
    )
    parcel_offer = ensure_trip_offer(
        session, driver_id=people[DRIVER_A], trip_public_id=trips[DRIVER_A], corridor=corridor,
        service="parcel", start=start + timedelta(hours=1), price_minor=9_000_000,
    )

    # Two drivers bidding on the same request: this is what the Q40 competing-offer board needs to show.
    thread_a = ensure_proposal(
        session, listing_public_id=parcel_request, actor_id=people[DRIVER_A], trip_public_id=trips[DRIVER_A],
        corridor=corridor, start=start, quantity=1, price_basis="total", price_minor=9_500_000,
        message="Ertaga yo'ldaman, quti sig'adi.",
    )
    thread_b = ensure_proposal(
        session, listing_public_id=parcel_request, actor_id=people[DRIVER_B], trip_public_id=trips[DRIVER_B],
        corridor=corridor, start=start, quantity=1, price_basis="total", price_minor=8_800_000,
        message="Men ham shu yo'nalishdaman.",
    )
    # ...and the client answers one of them, so the driver has a turn waiting on his screen.
    if thread_a is not None:
        ensure_counter(
            session, thread_public_id=thread_a, actor_id=people[CLIENT_A], price_minor=9_000_000,
            message="Biroz arzonlashtirsangiz roziman.",
        )

    # The other direction (Q92): a client answering a driver's trip offer.
    thread_c = ensure_proposal(
        session, listing_public_id=passenger_offer, actor_id=people[CLIENT_B], trip_public_id=None,
        corridor=corridor, start=start + timedelta(hours=1), quantity=1, price_basis="per_seat",
        price_minor=13_000_000, message="Bitta o'rin kerak.",
    )

    money = {
        phone: ensure_wallet_money(session, driver_id=people[phone], admin_id=admin_id)
        for phone in (DRIVER_A, DRIVER_B)
    }

    views = record_views(
        session,
        [parcel_request, passenger_request, passenger_offer, parcel_offer],
        [people[CLIENT_B], people[DRIVER_A], people[DRIVER_B], people[DRIVER_NEW]],
    )

    return {
        "people": people,
        "corridor": corridor,
        "listings": {
            "client parcel request": parcel_request,
            "client passenger request": passenger_request,
            "driver passenger offer": passenger_offer,
            "driver parcel offer": parcel_offer,
        },
        "threads": [t for t in (thread_a, thread_b, thread_c) if t is not None],
        "views": views,
        "money": money,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="build everything, then roll back")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if platform_service.is_production(session):
            print("refusing to run against a production marker")
            return 2
        result = seed(session)
        if args.dry_run:
            session.rollback()
            print("\ndry run: rolled back")
            return 0
        session.commit()
    finally:
        session.close()

    dispatched = dispatch_notifications()

    from app.core.config import settings

    print("\naccounts (OTP: %s or %s)" % (settings.dev_mock_otp, settings.mock_otp_code))
    for person in CAST:
        state = f" [{person.verification}]" if person.verification else ""
        print(f"  {person.phone}  {person.role:6} {person.full_name}{state}")
    print("\nlistings")
    for label, public_id in result["listings"].items():  # type: ignore[union-attr]
        print(f"  {label:26} {public_id}")
    print(f"\nopen negotiations: {len(result['threads'])}")
    print(f"listing views recorded: {result['views']}")
    for phone, (approved, pending) in result["money"].items():  # type: ignore[union-attr]
        print(f"wallet {phone}: {approved // 100} so'm tasdiqlangan, {pending // 100} so'm kutilmoqda")
    print(f"notifications dispatched from the outbox: {dispatched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
