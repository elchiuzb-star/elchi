"""The driver side of the client, guarded at the source (wave 16: Q94, Q95, Q96).

Three of these rules are invisible in a screenshot and cheap to undo in a refactor:

* the competing-offer board is what makes the auction an auction (Q90/Q40) - delete the call and every screen
  still renders, the market just stops finding a price;
* the vehicle inputs must be closed once the car is on record (Q94) - re-open them and the refusal only
  arrives on save, which reads as a bug rather than a rule;
* the screens that start new business must refuse an unverified driver in words (Q96) - drop the check and the
  server still says no, but the driver never learns why.

So each one is asserted against the source. These are guards, not a substitute for the server-side tests:
`tests/test_driver_profile_documents_routes.py` proves the v1 lock itself, and the eligibility rules live in
`tests/modules/identity/test_identity_capabilities.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src"
CONNECTED_APP = CLIENT / "app" / "ConnectedApp.tsx"
ADMIN_DRIVERS = CLIENT / "app" / "AdminDriversPanel.tsx"
MESSAGES_TS = CLIENT / "i18n" / "messages.ts"

pytestmark = pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")


def app_source() -> str:
    return CONNECTED_APP.read_text(encoding="utf-8")


def uzbek_text() -> dict[str, str]:
    """Every dictionary key with its Uzbek sentence - the screen copy lives in `src/i18n/`, not in the JSX."""
    found: dict[str, str] = {}
    for path in (CLIENT / "i18n").rglob("*.ts"):
        if path.name.endswith(".test.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'"([\w.]+)": \{\s*uz:\s*((?:"(?:[^"\\]|\\.)*"\s*\+?\s*)+),', text):
            parts = re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(2))
            found[match.group(1)] = "".join(parts).replace('\\"', '"')
    return found


def label_of(uzbek: str, block: str) -> str:
    """The source form of the `label=` in `block` whose Uzbek text is `uzbek`: `label={translate("key")}`."""
    keys = [key for key, text in uzbek_text().items() if text == uzbek]
    assert keys, f"no dictionary entry says {uzbek!r}"
    labels = [f'label={{translate("{key}")}}' for key in keys]
    return next((label for label in labels if label in block), labels[0])


def render_block(screen: str) -> str:
    """The `if (screen === ...) { ... }` that *draws* the screen.

    Not the first mention of the name: the effect list above the renderer says `if (screen === "x") void
    run(...)` for most of these, and anchoring on that silently asserted against one line of loader wiring.
    The renderer is the one followed by a brace, and it ends where the next screen begins.
    """
    source = app_source()
    opening = re.search(rf'if \(screen === "{re.escape(screen)}"(?: [^)]*)?\) \{{', source)
    assert opening, f"no render block for {screen}"
    body = source[opening.end():]
    return body.split('\n    if (screen === "', 1)[0]


# --- Q95: the open auction board ---------------------------------------------------------------------------


def test_the_bid_screen_loads_and_shows_the_competing_offers() -> None:
    source = app_source()
    assert "listListingOffers" in source, (
        "the driver cannot see what the other drivers are asking; Q40's endpoint exists but nothing calls it"
    )
    assert "RivalOfferBoard" in source, "the competing offers are fetched but never rendered"
    # The board belongs on the screen where the number is typed, not two taps away.
    assert "<RivalOfferBoard" in render_block("driver-bid"), "the board must be on the bid screen itself"


def test_the_board_shows_only_what_the_server_anonymised() -> None:
    """R2/Q43: before accept there is no identity. The DTO cannot carry one, so the risk is a UI that
    quietly joins the board to another source - assert the rendered fields stay on the anonymous set."""
    source = app_source()
    board = source.split("function RivalOfferBoard", 1)[1].split("\nfunction ", 1)[0]
    for leaked in ("full_name", "display_name", "phone", "plate_number", "make_model", "driver_user_id"):
        assert leaked not in board, f"the competing-offer board must not render {leaked}"
    assert "offer.label" in board, "each offer is identified by its stable anonymous label"
    assert "rating_count" in board, "U6: the bucket is meaningless without the count beside it (§8.2)"


# --- Q94: the car is entered once --------------------------------------------------------------------------


def test_the_vehicle_inputs_close_once_the_car_is_on_record() -> None:
    source = app_source()
    assert "const vehicleLocked = Boolean(driverProfile?.plate_number)" in source, (
        "the lock must follow the saved profile, not the approval status"
    )
    form = render_block("driver-profile-form")
    # Every vehicle field, and only the name left open.
    # The labels are dictionary keys since the screen copy moved to `src/i18n/`; the field is found by the key
    # whose Uzbek text is the label the driver reads, so the guard still names the same four fields.
    for field in ("Avtomobil modeli", "Avtomobil rangi", "Davlat raqami", "Yo'lovchi o'rinlari"):
        label = label_of(field, form)
        assert label in form, f"{field} is no longer a field of the profile form"
        block = form.split(label, 1)[1].split("/>", 1)[0]
        assert "disabled={vehicleLocked}" in block, f"{field} stays editable after the first save"
    name = label_of("Ism familiya", form)
    assert name in form and "disabled" not in form.split(name, 1)[1].split("/>", 1)[0], (
        "the name must stay editable - the lock is about the car"
    )
    where_to_go = [key for key, text in uzbek_text().items() if "operator yoki adminga murojaat qiling" in text]
    assert any(f'translate("{key}"' in form for key in where_to_go), "a locked field has to say where to go"


def test_a_locked_profile_sends_only_the_name() -> None:
    source = app_source()
    assert "updateDriverProfile(vehicleLocked ? { full_name: driverForm.full_name } : driverForm)" in source, (
        "a locked save must not post the vehicle keys at all"
    )


def test_staff_have_the_way_out_the_driver_is_pointed_at() -> None:
    """The driver screen says "ask an operator", so the panel must actually be able to do it."""
    panel = ADMIN_DRIVERS.read_text(encoding="utf-8")
    assert "updateDriverVehicle" in panel, "the admin panel cannot change a vehicle, so Q94 is a dead end"
    assert "VehicleModal" in panel, "the call exists but there is no way to reach it"


def test_the_refusal_has_client_copy_in_both_languages() -> None:
    messages = MESSAGES_TS.read_text(encoding="utf-8")
    entry = re.search(r'"error\.DRIVER_VEHICLE_LOCKED": \{(.*?)\}', messages, re.S)
    assert entry, "DRIVER_VEHICLE_LOCKED would show the generic failure"
    assert "uz:" in entry.group(1) and "ru:" in entry.group(1)


# --- Q96: an unverified driver takes no new business -------------------------------------------------------


# ADR-0026 (Q138): driver-offer-create is gone - drivers publish no listings
@pytest.mark.parametrize("screen", ["driver-feed", "driver-bid", "driver-routes"])
def test_the_new_business_screens_refuse_an_unverified_driver(screen: str) -> None:
    body = render_block(screen)
    assert "!driverApproved" in body, f"{screen} lets an unverified driver start work and fail on send"
    assert "DriverVerificationGate" in body, f"{screen} refuses without saying why"


def test_the_gate_sends_a_rejected_driver_to_support_not_back_to_the_uploads() -> None:
    source = app_source()
    gate = source.split("function DriverVerificationGate", 1)[1].split("\n/**", 1)[0]
    assert 'status === "rejected" || status === "blocked"' in gate, (
        "a decided account must not be told to upload more documents"
    )
    assert "onSupport" in gate


# --- §17.1: the driver has to know which slot they are filling ---------------------------------------------


def test_each_document_slot_names_itself_and_says_where_its_review_stands() -> None:
    body = render_block("driver-documents")
    assert "docTypeLabel(type)" in body, "the slot must be named"
    assert "docTypeHint(type)" in body, "the name alone does not say what has to be in the frame"
    assert "docState." in body, "the driver cannot tell which slot is still missing"
    assert "rejection_reason" in body, "a rejection without its reason gets the same photo back"
    # The toast after the upload names the slot too; five identical toasts say nothing.
    toast = [key for key, text in uzbek_text().items() if text == "{type} ko'rib chiqishga yuborildi"]
    assert any(f'translate("{key}", {{ type: docTypeLabel(type) }})' in body for key in toast)


def test_every_document_slot_has_a_name_and_a_hint_in_both_languages() -> None:
    source = app_source()
    types = re.search(r"const DRIVER_DOCUMENT_TYPES: DriverDocumentType\[\] = \[(.*?)\]", source, re.S)
    assert types
    slots = re.findall(r'"([a-z_]+)"', types.group(1))
    assert slots, "the document list went missing"
    messages = MESSAGES_TS.read_text(encoding="utf-8")
    for slot in slots:
        for key in (f'"docType.{slot}"', f'"docHint.{slot}"'):
            entry = re.search(re.escape(key) + r': \{(.*?)\}', messages, re.S)
            assert entry, f"{key} is missing; the slot would render its raw code"
            assert "uz:" in entry.group(1) and "ru:" in entry.group(1), f"{key} is not translated"
