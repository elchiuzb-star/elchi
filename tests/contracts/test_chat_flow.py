"""The chat opens when the driver is chosen and stops when the trip is over (§16, Q44, ADR-0020).

The backend already drew this line: a proposal chat lives only while the negotiation is open, a booking chat
until 24 hours after the booking's terminal state (`communications.chat_writable`). What the client did with
it was thinner than that - it knew only the booking chat, which is right, but it drew a composer whatever the
state was and found out by being refused.

These guards hold the three things that are invisible once the screen renders:

* the price is settled *before* the conversation starts - the client must not reach the proposal chat, or
  the negotiation moves into free text and the price history stops being the record;
* accepting is what opens the chat, on both sides;
* a closed chat is drawn as closed, not as an input that fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.contracts.communications import CHAT_WRITABLE_AFTER_TERMINAL
from app.contracts.dto import ChatThreadDTO
from app.contracts.enums import QuickReplyCode

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src"
CONNECTED_APP = CLIENT / "app" / "ConnectedApp.tsx"
BOOKINGS_API = CLIENT / "api" / "v2" / "bookings.api.ts"
MESSAGES_TS = CLIENT / "i18n" / "messages.ts"

pytestmark = pytest.mark.skipif(not CONNECTED_APP.is_file(), reason="mobile-app sources are not present")


def app_source() -> str:
    return CONNECTED_APP.read_text(encoding="utf-8")


def chat_screen() -> str:
    source = app_source()
    opening = re.search(r'if \(screen === "booking-chat"(?: [^)]*)?\) \{', source)
    assert opening, "the chat screen is gone"
    return source[opening.end():].split('\n    if (screen === "', 1)[0]


# --- the price is settled before the conversation starts ---------------------------------------------------


def test_the_client_never_opens_a_chat_on_a_proposal() -> None:
    """A chat during the negotiation is where a price gets agreed off the record.

    The endpoint exists for staff and for a later decision; the client must not call it, or the frozen
    proposal versions stop being the whole price history.
    """
    for path in (BOOKINGS_API, CLIENT / "api" / "v2" / "marketplace.api.ts", CONNECTED_APP):
        source = path.read_text(encoding="utf-8")
        assert "/proposals/${" not in source or "/messages" not in source.split("/proposals/${")[1][:60], (
            f"{path.name} reaches the proposal chat"
        )


def test_accepting_is_what_opens_the_chat_on_both_sides() -> None:
    source = app_source()
    accepts = [block for block in source.split("acceptProposal(")[1:]]
    assert len(accepts) >= 2, "both accept paths are gone"
    for index, block in enumerate(accepts):
        window = block[:1200]
        assert "openChat(" in window, f"accept path {index} does not open the chat"


def test_the_booking_is_loaded_before_the_chat_so_back_goes_somewhere() -> None:
    """The chat's back button targets the booking detail, which renders only when the booking is loaded."""
    source = app_source()
    for block in source.split("acceptProposal(")[1:]:
        window = block[:1200]
        assert "openClientBooking(" in window or "openDriverBooking(" in window, (
            "the chat would open over a booking screen that has nothing to render"
        )


# --- a closed chat is drawn as closed ----------------------------------------------------------------------


def test_the_screen_asks_whether_it_may_write_before_drawing_a_composer() -> None:
    source = app_source()
    assert "getChatState(" in source, "the client cannot tell an open chat from a closed one"
    opener = source.split("async function openChat", 1)[1].split("\n  }", 1)[0]
    assert "getChatState(" in opener, "the state must be known before the screen is shown"


def test_a_closed_chat_shows_words_instead_of_an_input() -> None:
    screen = chat_screen()
    assert "chatState && !chatState.writable" in screen, "a closed chat still invites a message"
    assert "chat.closedTitle" in screen and "chat.closedBody" in screen
    # The transcript stays: "read-only" is not "gone".
    assert "chatMessages.map(" in screen, "a closed chat must still show what was said"


def test_the_deadline_is_shown_while_it_is_counting() -> None:
    screen = chat_screen()
    assert "chatState?.writable_until" in screen, (
        "a booking chat closes 24 hours after the trip ends; not saying when is a surprise"
    )
    assert CHAT_WRITABLE_AFTER_TERMINAL.total_seconds() == 24 * 3600, "the copy says 24 hours"


# --- quick replies -----------------------------------------------------------------------------------------


def test_quick_replies_are_offered_and_rendered() -> None:
    source = app_source()
    assert "quickRepliesFor(" in source, "Q44 promises quick replies alongside the chat"
    screen = chat_screen()
    assert "quick_reply_code: code" in screen, "the buttons must send the code, not its text"
    assert "message.quick_reply_code" in screen, "a received quick reply would render as an empty bubble"


def test_the_booking_chat_does_not_offer_to_re_agree_the_price() -> None:
    """`price_agreed` belongs to the negotiation, not to a booking that exists because it was agreed."""
    source = app_source()
    offered = source.split("function quickRepliesFor", 1)[1].split("\n}", 1)[0]
    assert "price_agreed" not in offered
    assert {"arriving_in_5_min", "at_stop", "clarify_stop"} <= set(re.findall(r'"([a-z0-9_]+)"', offered))


@pytest.mark.parametrize("code", [c.value for c in QuickReplyCode])
def test_every_quick_reply_code_has_copy_in_both_languages(code: str) -> None:
    """Including the ones only the negotiation uses: a message already sent must still be readable."""
    messages = MESSAGES_TS.read_text(encoding="utf-8")
    entry = re.search(re.escape(f'"quickReply.{code}"') + r": \{([^\n]*)\}", messages)
    assert entry, f"quickReply.{code} is missing; the bubble would show its raw code"
    assert "uz:" in entry.group(1) and "ru:" in entry.group(1)


def test_the_chat_state_dto_is_what_the_client_reads() -> None:
    assert set(ChatThreadDTO.model_fields) >= {"writable", "writable_until", "message_count"}
    assert ChatThreadDTO.model_fields["writable_until"].default is None
