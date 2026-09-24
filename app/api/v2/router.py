"""Aggregated ``/api/v2`` router and start-up port wiring (integrator-owned).

Wave 1 (integration passes 1+2): geo (A2), wallet (A3), identity, trips, marketplace (A1).
Routers are mounted with no extra prefix: A1/A3 idempotency records are scoped to the
mounted route template (e.g. ``POST /api/v2/me/roles``).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.bookings.api import router as bookings_router
from app.modules.communications.api import router as communications_router
from app.modules.geo.api import router as geo_router
from app.modules.identity.api import router as identity_router
from app.modules.marketplace.api import router as marketplace_router
from app.modules.marketplace.feed.api import router as feed_router
from app.modules.operations.api import router as operations_router
from app.modules.promotions.api import router as promotions_router
from app.modules.tracking.api import router as tracking_router
from app.modules.trips.api import router as trips_router
from app.modules.trust_support.api import router as trust_support_router
from app.modules.wallet.api import router as wallet_router

api_router = APIRouter()
api_router.include_router(identity_router)
api_router.include_router(geo_router)
api_router.include_router(trips_router)
api_router.include_router(marketplace_router)
api_router.include_router(wallet_router)
# Wave 2: A4 bookings (P8 accept, B1-B13, T9 trip actions, T10 manifest).
api_router.include_router(bookings_router)
# Wave 3: A6 tracking (K1-K7, K9, K8 WebSocket /ws), A7 communications (N1-N11), A12 trust & support (I4 DELETE /me,
# S1-S8, S13-S20), A5 feed (M1-M5). No path+method overlaps with earlier routers (GET /me stays identity's).
api_router.include_router(tracking_router)
api_router.include_router(communications_router)
api_router.include_router(trust_support_router)
api_router.include_router(feed_router)
# Wave 4: A13 operations and growth (O1-O3 share links incl. the public page, O4 queues, O5 KPI, O6 SLO,
# O7 listing on behalf). The public page is the only unauthenticated /api/v2 route.
api_router.include_router(operations_router)
# Referral stage 5 (ADR-0023 §16, §19): promotions client + admin. GET /public/referral-codes/{code} is unauthenticated
# and rate limited per source.
api_router.include_router(promotions_router)


def configure_v2_ports() -> None:
    """Register cross-module adapters (idempotent).

    A1's adapters are used (``trips.adapters.GeoServiceAdapter``,
    ``marketplace.adapters.default_marketplace_ports`` with ``FlagServiceAdapter`` and
    ``WalletFeeAdapter``). A2's ``app.modules.geo.adapters`` implements the same geo/flag ports
    and is intentionally not wired (duplicate; no fee adapter).
    """
    from app.modules.marketplace.adapters import default_marketplace_ports
    from app.modules.marketplace.ports import configure_ports
    from app.modules.trips.adapters import GeoServiceAdapter
    from app.modules.trips.ports import set_geo_port

    set_geo_port(GeoServiceAdapter())
    configure_ports(default_marketplace_ports())

    # Wave 2: geo corridor close/reopen sees active bookings (set_active_booking_counter).
    from app.modules.bookings.service import register_geo_hooks

    register_geo_hooks()

    # Wave 3: A12 dispute probe + payment dispute opener. Ends the Q74 fallback in the running app
    # (bookings.service.dispute_state -> open/clear); without this registration Q74 (finance_review) still applies.
    from app.modules.trust_support.service import register_booking_hooks

    register_booking_hooks()

    # Wave 5: A7 chat thread lookup for BookingDTO.contact.chat_thread_id (read-only; never creates a thread).
    from app.modules.communications.service import register_booking_hooks as register_chat_hooks

    register_chat_hooks()
