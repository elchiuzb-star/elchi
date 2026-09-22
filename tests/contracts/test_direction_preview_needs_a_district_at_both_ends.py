"""Every marked end carries a district, including where the catalogue never asks for one.

`GET /directions/preview` (Q88) requires a district id at **both** ends - the schema makes them
required query parameters. The client, though, only asks for a district when the chosen region says
`requires_district`. Tashkent city says false (wave 10), so picking it sent the person straight to the
map and the end reached the home screen with `district: null`.

The effect that fetches the preview then returned early: no request, no preview, no error message - and
because "Yo'nalishni ko'rish" is enabled by `bothPoints`, which needs a preview, the button sat grey
with nothing on screen explaining why. Both places were marked and the product looked broken.

These tests pin the two halves of the fix:

* the endpoint really does demand a district at both ends (so the client cannot be lax about it);
* the client fills one in from the marked place when the region never asked.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src"
CONNECTED_APP = CLIENT / "app" / "ConnectedApp.tsx"


def test_the_preview_endpoint_requires_a_district_at_both_ends() -> None:
    from app.modules.marketplace.api import preview_direction

    parameters = inspect.signature(preview_direction).parameters
    for name in ("origin_district_id", "destination_district_id"):
        assert name in parameters, f"{name} is no longer a parameter of the preview endpoint"
        # FastAPI marks a Query parameter with no default as required; that is what forces the client to
        # have a district at each end before it can ask at all.
        assert parameters[name].default.is_required(), f"{name} became optional - the client fallback is now moot"


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_marking_a_place_fills_in_a_district_when_the_region_never_asked() -> None:
    source = CONNECTED_APP.read_text(encoding="utf-8")
    match = re.search(r"async function markPoint\(point: MarkedPoint\) \{(.+?)\n  \}", source, re.S)
    assert match, "markPoint is no longer where this invariant lives - find it and re-point this test"
    body = match.group(1)

    assert "if (!district)" in body, "markPoint no longer fills in a missing district"
    assert "nearestDistrict(" in body, "markPoint no longer resolves the district from the marked place"
    assert "district," in body or "district:" in body, "the resolved district is not applied to the end"


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_the_preview_effect_still_guards_on_both_districts() -> None:
    """The early return stays - it is correct. What changed is that the districts are now there."""
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert "if (!from || !to || !pickupEnd.district || !dropoffEnd.district)" in source, (
        "the preview effect's precondition changed; check that a missing district still cannot "
        "silently produce a request with an empty district id"
    )


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_the_service_gate_follows_the_chosen_mode() -> None:
    """Q5 is per service: with Taksi selected, a closed *parcel* service must not disable the button."""
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert 'serviceMode === "passenger" ? flags?.passenger_enabled === false' in source, (
        "the home gate no longer reads the flag of the mode that is actually selected"
    )


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_the_review_screen_has_no_stop_only_rows() -> None:
    """A Q88 direction has no stops, so a "bekat" row could only ever render a dash.

    The review screen is the last thing a person reads before publishing. Three of its rows printed "-"
    for every point-ended order: both stop rows, and the districts on the route - which were read from a
    corridor id that only a stop end sets. Rows now come from the marked places and the preview.
    """
    source = CONNECTED_APP.read_text(encoding="utf-8")
    review = source[source.index('if (screen === "client-order-review")') :]
    review = review[: review.index('if (screen === "client-success")')]

    assert "Olib ketish bekati" not in review, "the stop-only row is back; a marked place never fills it"
    assert "Yetkazish bekati" not in review, "the stop-only row is back; a marked place never fills it"
    assert "districts_on_route" in review, "the review no longer reads the districts the preview resolved"
    assert "leg_distance_m" in review, "the review no longer shows the distance of this trip"


@pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")
def test_editing_a_passenger_order_goes_back_to_where_it_was_composed() -> None:
    """"Tahrirlash" sent a taxi order to the parcel contact screen, which it never passed through."""
    source = CONNECTED_APP.read_text(encoding="utf-8")
    assert 'go(passengerMode ? "client-route-summary" : "client-order-address")' in source
