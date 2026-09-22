"""The suggestion group has to be asked for, and then shown apart (§6.4, §8.2).

`include_alternatives` defaults to **false** on the server, on purpose: a near miss is not a result, and an
endpoint that returned one by default would be answering a question nobody asked. The consequence is that the
whole feature is one query parameter away from not existing - and for a while that is exactly what it was: the
matcher, the ranking, the `alternative` group and even the client's "Muqobil" label were all in place, and no
client call ever set the flag, so a driver with nothing on their route saw an empty list and no suggestions.

That is invisible in every other test: every screen renders, every request succeeds, the feed is simply thin.
So the flag is asserted at each call site, and the split is asserted at each screen. The logic of the split is
tested where it lives, in `mobile-app/src/app/feedGroups.test.ts`; the server side is proved in
`tests/pg/marketplace/feed/test_feed_pg.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.contracts.feed import MATCH_SCOPE_CONFIRMED_STOPS

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src"
CONNECTED_APP = CLIENT / "app" / "ConnectedApp.tsx"
DRIVER_API = CLIENT / "api" / "v2" / "driver.api.ts"
MARKETPLACE_API = CLIENT / "api" / "v2" / "marketplace.api.ts"
GROUPS_TS = CLIENT / "app" / "feedGroups.ts"
MESSAGES_TS = CLIENT / "i18n" / "messages.ts"

pytestmark = pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")


# --- the flag is actually sent -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "function"),
    [
        (DRIVER_API, "requestsFeed"),  # the driver's feed of client requests
        (MARKETPLACE_API, "offersFeed"),  # the client's feed of driver trip offers
        (MARKETPLACE_API, "listingMatches"),  # either side, from a listing they already published
    ],
)
def test_every_discovery_call_asks_for_the_alternatives(source: Path, function: str) -> None:
    text = source.read_text(encoding="utf-8")
    body = text.split(f"export function {function}", 1)
    assert len(body) == 2, f"{function} is gone from {source.name}"
    body = body[1].split("\nexport ", 1)[0]
    assert "include_alternatives" in body, (
        f"{function} never sets include_alternatives, so the server returns only exact matches and the "
        f"suggestion group is dead code"
    )
    assert re.search(r"include_alternatives:\s*params\.include_alternatives \?\? true", body), (
        f"{function} must default the flag to true; an opt-in the client never opts into is the bug this "
        f"guard exists for"
    )


# --- the split is done, and done in one place --------------------------------------------------------------


def test_the_split_lives_in_a_pure_module() -> None:
    """Not inline on three screens: the same rule written three times is three chances to mix the groups."""
    assert GROUPS_TS.is_file(), "feedGroups.ts is the single place the two groups are separated"
    source = GROUPS_TS.read_text(encoding="utf-8")
    for forbidden in ("import React", "from \"react\"", "fetch(", "v2Request"):
        assert forbidden not in source, f"feedGroups.ts must stay pure (found {forbidden})"


@pytest.mark.parametrize("screen", ["driver-feed", "client-offers", "listing-matches"])
def test_each_list_screen_separates_the_two_groups(screen: str) -> None:
    source = CONNECTED_APP.read_text(encoding="utf-8")
    opening = re.search(rf'if \(screen === "{re.escape(screen)}"(?: [^)]*)?\) \{{', source)
    assert opening, f"no render block for {screen}"
    body = source[opening.end():].split('\n    if (screen === "', 1)[0]
    assert "splitFeedGroups(" in body, f"{screen} renders one list, so a near miss reads as a match"
    assert "match.alternativesTitle" in body, f"{screen} shows suggestions without saying they are suggestions"
    assert ".alternative.map(" in body, f"{screen} computes the split but never renders the second group"
    # The primaries must be drawn before the heading; otherwise the ranking the server did is thrown away.
    assert body.index(".primary.map(") < body.index("match.alternativesTitle")


def test_a_suggestion_says_which_kind_it_is() -> None:
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert "alternativeReasonLabel" in source, (
        '"Muqobil" alone is not actionable - the driver has to know whether to look at the clock or the map'
    )
    helper = source.split("function alternativeReasonLabel", 1)[1].split("\n}", 1)[0]
    assert "match.reason." in helper


# --- the copy exists in both languages ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["match.alternativesTitle", "match.alternativesNote", "match.reason.time_differs", "match.reason.nearby_stop"]
)
def test_the_suggestion_copy_is_translated(key: str) -> None:
    messages = MESSAGES_TS.read_text(encoding="utf-8")
    entry = re.search(re.escape(f'"{key}"') + r": \{(.*?)\n?  \}|" + re.escape(f'"{key}"') + r": \{([^\n]*)\}", messages, re.S)
    assert entry, f"{key} is missing; the section would render its raw key"
    body = entry.group(1) or entry.group(2)
    assert "uz:" in body and "ru:" in body, f"{key} is not translated into both languages"


def test_the_confirmed_stops_caveat_still_travels_with_the_results() -> None:
    """Q46: the app must not imply a measured detour. Widening the search does not widen what was measured."""
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert f'matchScope === "{MATCH_SCOPE_CONFIRMED_STOPS}"' in source
