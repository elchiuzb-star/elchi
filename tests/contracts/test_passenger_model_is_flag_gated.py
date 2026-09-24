"""The passenger request model is part of the architecture, and the flag only gates the rollout (Q91).

This file used to assert the opposite: that the client contained no passenger flow at all. That was a
misreading of Q7. Q7 says the passenger service is **built** and stays off in production until the legal
review (K7) - it is a rollout flag, not a decision to delete a quarter of the marketplace. Wave 13's guard
would have frozen that mistake into the test suite, so it is replaced here by the invariants that actually
hold:

* all four listing kinds exist in the contract, passenger requests among them;
* the client can compose a passenger listing, and does so behind `passenger_enabled`;
* nothing reaches a passenger screen without consulting that flag;
* navigation is screen state, so a flag that is off cannot be walked around with a URL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.contracts.enums import ALLOWED_PRICE_BASIS, ListingKind, ServiceType

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src"
CONNECTED_APP = CLIENT / "app" / "ConnectedApp.tsx"


def test_all_four_listing_kinds_are_in_the_contract() -> None:
    """request/trip_offer x passenger/parcel: both sides of the market, both services (Q92)."""
    assert set(ALLOWED_PRICE_BASIS) == {
        (ListingKind.REQUEST, ServiceType.PASSENGER),
        (ListingKind.REQUEST, ServiceType.PARCEL),
        (ListingKind.TRIP_OFFER, ServiceType.PASSENGER),
        (ListingKind.TRIP_OFFER, ServiceType.PARCEL),
    }


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_the_client_can_compose_a_passenger_listing() -> None:
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert re.search(r'service_type:\s*passenger\s*\?\s*"passenger"\s*:\s*"parcel"', source), (
        "the publish body must be able to say passenger (Q91); a client that can only send parcel has "
        "dropped a quarter of the marketplace"
    )
    assert re.search(r'passenger:\s*\{\s*seat_count', source), "a passenger listing carries its seat count"


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_the_passenger_entry_point_is_behind_its_flag() -> None:
    """Q7/K7 is a rollout gate: the mode is offered only when the corridor has `passenger_enabled`."""
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert "flags?.passenger_enabled" in source, "the passenger mode must consult the flag"
    assert "effectiveFlags(" in source, "flags are read from the server, per corridor"


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_navigation_is_screen_state_so_a_closed_flag_cannot_be_walked_around() -> None:
    main = (CLIENT / "main.tsx").read_text(encoding="utf-8")
    routed = set(re.findall(r'path\.startsWith\("([^"]+)"\)', main))
    # `/privacy` is a static page the store listing links to, with no session and no screen stack behind it,
    # so it cannot reach a flagged mode; the guard is about paths that enter the app. `/t/` is the public tracking
    # page of a booking's tracking grant (read-only, token-scoped, no session) - the same kind of page as `/e/`.
    assert routed == {"/admin", "/e/", "/privacy", "/t/"}, f"the URL surface changed: {sorted(routed)}"
    assert main.count("window.location.pathname") == 1
