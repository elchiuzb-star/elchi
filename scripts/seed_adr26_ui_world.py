"""SYNTHETIC world for the ADR-0026 screen checks (docs/ops/SYNTHETIC_UI_DB.md). Never production.

Run only against a throw-away database on the local test stack whose name starts with ``elchi_ui_`` (the script
refuses anything else), with ``ELCHI_DATABASE_URL`` / ``ELCHI_ENVIRONMENT=development`` / a synthetic
``ELCHI_SECRET_KEY`` given in the shell - never by editing ``.env``. Writes ``adr26_world.json`` (synthetic ids and
short-lived dev tokens) next to ``--out``.

* a synthetic (flagged) parcel size catalog;
* `client` has a published parcel request (small box) that `driver` sees in the requests feed, plus a parcel booking
  with `driver2` (agreed price, category, trip departed -> in transit) and an open complaint chat on it;
* `driver2` has its own chat on the same booking, already answered by the operator;
* `client_new` has nothing (empty states).
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.modules.marketplace import ports as marketplace_ports  # noqa: E402
from app.modules.marketplace.ports import MarketplacePorts  # noqa: E402
from app.modules.trips import ports as trips_ports  # noqa: E402
from app.modules.trust_support import threads  # noqa: E402
from tests.pg.bookings.conftest import (  # noqa: E402
    BW, accept, driver_trip, enable_flags, fund, parcel_request_body, passenger_request_body, propose, publish_listing,
    run_trip_action,
)
from tests.pg.conftest import PgDatabase  # noqa: E402
from tests.pg.identity.a1_world import SqlGeoAdapter, add_user, build_world  # noqa: E402

HERE = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path.cwd()
url = make_url(settings.database_url)
if not (url.database or "").startswith("elchi_ui_") or settings.environment == "production":
    raise SystemExit("refusing: this seeds SYNTHETIC data only into a local elchi_ui_* database")
db = PgDatabase(name=url.database, url=url, engine=create_engine(url, pool_size=5), clone_seconds=0.0)
world = build_world(db)
geo = SqlGeoAdapter()
trips_ports.set_geo_port(geo)
marketplace_ports.configure_ports(MarketplacePorts(geo=geo, flags=world.flags, fees=world.fees))

with db.session() as s:
    super_id = add_user(s, "+998900000400", "super_admin", full_name="Super Admin")
    operator_id = add_user(s, "+998900000401", "operator", full_name="Operator")
    finance_id = add_user(s, "+998900000402", "finance", full_name="Finance")
    client_new = add_user(s, "+998900000405", "client", full_name="Synthetic Client")
    s.commit()
enable_flags(db, world.admin_id, keys=("passenger_enabled", "parcel_enabled"))
bw = BW(world, super_id, operator_id, finance_id)
for driver in (world.driver_id, world.driver2_id):
    fund(bw, driver, 100_000_000, super_id)

# 1. an open parcel request the driver sees in the feed (category from the synthetic catalog)
open_request = publish_listing(bw, world.client_id, parcel_request_body(bw, unit=6_500_000))
# a passenger request too, so the feed is not a single card (client2 can change its seat count before a booking)
publish_listing(bw, world.client2_id, passenger_request_body(bw, seats=2, unit=18_000_000))
# one driver answers the client's open parcel request - the client compares it (driver_summary, Q40 set)
_, answer_trip = driver_trip(bw, world.driver_id, "01U201UA")
propose(bw, open_request, world.driver_id, trip_public_id=answer_trip, quantity=1, unit=6_800_000, dropoff="C",
        price_basis="total")

# 2. a parcel booking with driver2, on the way (trip departed)
trip_id, trip_public = driver_trip(bw, world.driver2_id, "01U200UA")
second_request = publish_listing(bw, world.client_id, parcel_request_body(bw, destination="D", unit=7_000_000))
ref = propose(bw, second_request, world.driver2_id, trip_public_id=trip_public, quantity=1, unit=7_200_000, dropoff="D",
              price_basis="total")
booking = accept(bw, ref, world.client_id)
run_trip_action(bw, trip_id, world.driver2_id, "start_boarding", now=bw.base - timedelta(minutes=30))
run_trip_action(bw, trip_id, world.driver2_id, "depart", now=bw.base + timedelta(minutes=5))

# 3. complaint chats: the client's is waiting; the driver's has an operator answer
from app.modules.bookings import service as bookings_service  # noqa: E402

public = bookings_service.booking_public_id(booking)
with db.session() as s:
    client_thread, _ = threads.open_or_get_thread(s, booking_public_id_value=public, actor_user_id=world.client_id,
                                                  text_value="Jo'natma qachon yetib borishini bilmoqchiman.",
                                                  warnings=[], filter_hits=[])
    driver_thread, _ = threads.open_or_get_thread(s, booking_public_id_value=public, actor_user_id=world.driver2_id,
                                                  text_value="Qabul qiluvchi manzilni aniqlashtirmadi.",
                                                  warnings=[], filter_hits=[])
    s.commit()
    driver_thread_id = threads.thread_public_id(driver_thread)
with db.session() as s:
    t = threads.staff_command(s, thread_public_id_value=driver_thread_id, actor_user_id=operator_id, command="assign",
                              expected_version=driver_thread.version, text_value=None, assignee_user_id=None)
    s.commit()
    version = t.version
with db.session() as s:
    threads.staff_command(s, thread_public_id_value=driver_thread_id, actor_user_id=operator_id, command="reply",
                          expected_version=version, text_value="Qabul qiluvchi bilan bog'lanyapmiz, ilovada kuting.",
                          assignee_user_id=None)
    s.commit()


def token(user_id: int, role: str) -> str:
    return create_access_token(str(user_id), extra_claims={"role": role})


people = {"client": (world.client_id, "client"), "client2": (world.client2_id, "client"), "client_new": (client_new, "client"), "driver": (world.driver_id, "driver"),
          "driver2": (world.driver2_id, "driver"), "operator": (operator_id, "operator"), "super": (super_id, "super_admin")}
out = {name: {"id": uid, "role": role, "token": token(uid, role)} for name, (uid, role) in people.items()}
out["open_request"], out["booking"] = open_request, public
out["client_thread"], out["driver_thread"] = threads.thread_public_id(client_thread), driver_thread_id
(HERE / "adr26_world.json").write_text(json.dumps(out, indent=2))
print("adr26 world ok", public)
