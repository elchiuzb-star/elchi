"""The view count survives the round trip: DTO -> client -> screen (Q98).

The counting rules are proved where they run (`tests/modules/marketplace/test_listing_views.py` and
`tests/pg/marketplace/test_listing_views_pg.py`). What is left is the quiet failure: the server counts
correctly, the field is on the DTO, and no screen ever renders it - the owner is back to not knowing whether
anybody looked. Nothing fails, so nothing catches it but this.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.marketplace.schemas import ListingDTO, ListingPublicDTO

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src"
CONNECTED_APP = CLIENT / "app" / "ConnectedApp.tsx"
GENERATED = CLIENT / "api" / "generated" / "v2.ts"
MESSAGES_TS = CLIENT / "i18n" / "messages.ts"


@pytest.mark.parametrize("dto", [ListingDTO, ListingPublicDTO])
def test_both_listing_dtos_carry_the_count(dto: type) -> None:
    """The owner reads it to decide; everyone else gets it as ordinary market information. A count of people
    names nobody, so the public DTO can carry it without touching §10.6."""
    assert "view_count" in dto.model_fields
    assert dto.model_fields["view_count"].default == 0, "a listing nobody has opened is 0, never null"


@pytest.mark.skipif(not GENERATED.is_file(), reason="mobile-app sources are not present")
def test_the_generated_client_types_are_not_stale() -> None:
    """`npm run gen:api` after the schema change - otherwise the field exists and the client cannot see it."""
    assert "view_count" in GENERATED.read_text(encoding="utf-8")


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_the_count_reaches_a_screen_on_both_sides() -> None:
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert "viewCountLabel" in source, "the field is fetched and never shown"
    # The client's own request, in the list and on its detail screen, is drawn by ListingCard.
    card = source.split("function ListingCard", 1)[1].split("\nfunction ", 1)[0]
    assert "viewCountLabel(listing.view_count)" in card, "a client cannot see who looked at their request"
    # The driver's own trip offers are drawn on the trip card.
    opening = re.search(r'if \(screen === "driver-routes"(?: [^)]*)?\) \{', source)
    assert opening
    routes = source[opening.end():].split('\n    if (screen === "', 1)[0]
    assert "viewCountLabel(offer.view_count)" in routes, "a driver cannot see who looked at their trip offer"


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_zero_is_a_sentence_not_a_digit() -> None:
    """"0" beside a listing reads as a failed load; "nobody has looked yet" is what the owner can act on."""
    source = CONNECTED_APP.read_text(encoding="utf-8")
    helper = source.split("function viewCountLabel", 1)[1].split("\n}", 1)[0]
    assert "count > 0" in helper and "listing.viewsNone" in helper
    messages = MESSAGES_TS.read_text(encoding="utf-8")
    for key in ("listing.viewsSuffix", "listing.viewsNone"):
        entry = re.search(re.escape(f'"{key}"') + r": \{([^\n]*)\}", messages)
        assert entry, f"{key} is missing; the count would render its raw key"
        assert "uz:" in entry.group(1) and "ru:" in entry.group(1)
