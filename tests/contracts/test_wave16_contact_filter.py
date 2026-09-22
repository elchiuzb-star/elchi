"""Wave 1.6 contract additions: contact filter (Q43), PRICE_OUT_OF_BAND (Q42), filter events (Q45)."""

import pytest

from app.contracts.contact_filter import (
    CONTACT_FILTER_VERSION,
    MASK,
    ContactCategory,
    mask,
    scan,
)
from app.contracts.enums import EventType
from app.contracts.errors import WARNING_CATALOGUE, ErrorCode, WarningCode, http_status_for
from app.contracts.events import EVENT_AUDIENCES, EventAudience, payload_for_audience, payload_violations

P = ContactCategory.PHONE

POSITIVE = [
    # phones: country code, local, separators
    ("+998 90 123 45 67", {P}),
    ("998901234567", {P}),
    ("+998901234567", {P}),
    ("90 123 45 67", {P}),
    ("901234567", {P}),
    ("(90) 123-45-67", {P}),
    ("8 (90) 123-45-67", {P}),
    ("90.123.45.67", {P}),
    ("90-123-45-67", {P}),
    ("90 / 123 / 45 67", {P}),
    ("9 0 1 2 3 4 5 6 7", {P}),
    ("123-45-67", {P}),
    ("+7 912 345 67 89", {P}),
    ("Mening raqamim: 33 123 45 67", {ContactCategory.CALL_REQUEST, P}),
    ("bog'lanish 55 123 45 67", {P}),
    # obfuscation: full-width digits, zero-width characters, Arabic-Indic digits
    ("９０１２３４５６７", {P}),
    ("90​123​45​67", {P}),
    ("9‍0 1⁠234567", {P}),
    ("٩٠١٢٣٤٥٦٧", {P}),
    # number words: Uzbek Latin / Cyrillic, Russian Cyrillic / Latin, mixed with digits
    ("to'qson bir bir ikki uch qirq besh oltmish yetti", {P}),
    ("to‘qson bir, bir yuz yigirma uch, qirq besh, oltmish yetti", {P}),
    ("тўқсон бир бир икки уч қирқ беш олтмиш етти", {P}),
    ("девяносто один сто двадцать три сорок пять шестьдесят семь", {P}),
    ("devyanosto odin sto dvadtsat tri sorok pyat shestdesyat sem", {P}),
    ("90 bir ikki uch 45 67", {P}),
    ("to'qson 123 45 67", {P}),
    # e-mail, handles, messengers, links
    ("email: ali.valiyev@gmail.com", {ContactCategory.EMAIL}),
    ("ali (at) mail (dot) ru", {ContactCategory.EMAIL}),
    ("yozing @ali_driver", {ContactCategory.HANDLE}),
    ("t.me/ali_driver", {ContactCategory.MESSENGER_LINK}),
    ("https://wa.me/998901234567", {ContactCategory.MESSENGER_LINK}),
    ("telegramdan yozing", {ContactCategory.MESSENGER_LINK}),
    ("WhatsApp bor", {ContactCategory.MESSENGER_LINK}),
    ("ватсапга ёзинг", {ContactCategory.MESSENGER_LINK}),
    ("инстаграм: ali", {ContactCategory.MESSENGER_LINK}),
    ("instagram.com/ali", {ContactCategory.MESSENGER_LINK}),
    ("www.example.uz", {ContactCategory.URL}),
    ("https://example.com/profile", {ContactCategory.URL}),
    # call requests
    ("menga qo‘ng‘iroq qiling", {ContactCategory.CALL_REQUEST}),
    ("qongiroq qil", {ContactCategory.CALL_REQUEST}),
    ("raqamimni oling", {ContactCategory.CALL_REQUEST}),
    ("менга қўнғироқ қилинг", {ContactCategory.CALL_REQUEST}),
    ("позвоните мне", {ContactCategory.CALL_REQUEST}),
    ("номер телефона дам", {ContactCategory.CALL_REQUEST}),
    ("pozvoni", {ContactCategory.CALL_REQUEST}),
    # combinations
    ("tel: (90) 123-45-67", {ContactCategory.CALL_REQUEST, P}),
    ("@ali_driver yoki 90 123 45 67", {ContactCategory.HANDLE, P}),
]

NEGATIVE = [
    "200 000 so'm",
    "200000 so'm",
    "1 500 000 so'm",
    "12 500 000 so‘m",
    "narxi 350000",
    "narx 70 000 dan 90 000 gacha",
    "90 000 - 95 000",
    "120 000 - 150 000",
    "150 000 000",
    "900 000 000",
    "1 200 000 сум",
    "450 минг",
    "14.09.2026 08:30 da jo'nayman",
    "2026-09-14 08:30",
    "14/09/2026",
    "Jo'nash 15.09 soat 07:00",
    "soat 9 dan 12 gacha",
    "3 o'rin bor",
    "bir o'rin qoldi",
    "uch kishi, ikki sumka",
    "2 ta sumka 15 kg",
    "o'n besh kg",
    "Toshkent - Samarqand 300 km",
    "yo'lga 5 soat",
    "iPhone 13 telefon yuboraman",
    "Aloqa ilova ichida",
    "01 777 AAA",
    "+30%",
    "ali@gmail",
    "Chegirma 10%, 2 kishi uchun 180 000 so'm",
    "Мест 3, цена 150 000 сум",
    "",
]


@pytest.mark.parametrize(("text", "expected"), POSITIVE)
def test_contact_info_is_detected_and_masked(text: str, expected: set[ContactCategory]) -> None:
    result = scan(text)
    assert result.categories == expected, (text, result)
    assert result.has_contact
    assert MASK in result.masked_text
    assert result.filter_version == CONTACT_FILTER_VERSION
    for match in result.matches:
        assert 0 <= match.start < match.end <= len(text)
    if P in expected:
        # no run of 7+ digits survives masking
        digits = "".join(ch for ch in result.masked_text if ch.isdigit())
        assert len(digits) < 7, result.masked_text


@pytest.mark.parametrize("text", NEGATIVE)
def test_prices_dates_times_and_counts_are_not_masked(text: str) -> None:
    result = scan(text)
    assert not result.has_contact, (text, result.matches)
    assert result.masked_text == text


def test_spans_refer_to_original_text_and_surrounding_text_is_kept() -> None:
    text = "Salom!​ Raqam: 90​123 45 67, narx 200 000 so'm"
    result = scan(text)
    assert [m.category for m in result.matches] == [P]
    match = result.matches[0]
    assert text[match.start : match.end] == "90​123 45 67"
    assert result.masked_text == f"Salom!​ Raqam: {MASK}, narx 200 000 so'm"


def test_mask_is_idempotent_and_matches_scan() -> None:
    text = "90 123 45 67 va t.me/ali, @ali_driver, ali@mail.ru"
    once = mask(text)
    assert once == scan(text).masked_text
    assert mask(once) == once
    assert "ali" not in once


def test_link_containing_phone_is_one_messenger_match() -> None:
    result = scan("https://wa.me/998901234567 yozing")
    assert len(result.matches) == 1
    assert result.matches[0].category is ContactCategory.MESSENGER_LINK


def test_warning_details_carry_no_text() -> None:
    details = scan("90 123 45 67 @ali_driver").warning_details()
    assert details == {"categories": ["handle", "phone"], "match_count": 2, "filter_version": CONTACT_FILTER_VERSION}


def test_price_out_of_band_and_contact_warning_codes() -> None:
    assert http_status_for(ErrorCode.PRICE_OUT_OF_BAND) == 400
    assert WarningCode.CONTACT_INFO_MASKED in WARNING_CATALOGUE
    assert set(WARNING_CATALOGUE) == set(WarningCode)
    assert not set(WarningCode.__members__) & set(ErrorCode.__members__)


@pytest.mark.parametrize("event_type", [EventType.CONTACT_FILTER_HIT, EventType.CONTACT_STRIKE_RECORDED])
def test_contact_filter_events_are_staff_only_and_textless(event_type: EventType) -> None:
    assert EVENT_AUDIENCES[event_type] == frozenset({EventAudience.STAFF})
    payload = {"actor_id": "usr_x", "subject_type": "listing", "subject_id": "lst_x"}
    assert payload_for_audience(event_type, payload, EventAudience.CLIENT) is None
    assert payload_for_audience(event_type, payload, EventAudience.DRIVER) is None
    assert payload_violations(event_type, {**payload, "text": "90 123 45 67"})
    assert payload_violations(event_type, {**payload, "masked_text": "•••"})


def test_contact_filter_hit_payload_shape() -> None:
    payload = {
        "actor_id": "usr_x",
        "subject_type": "proposal_version",
        "subject_id": "prv_x",
        "field": "message",
        "categories": ["phone"],
        "match_count": 1,
        "filter_version": CONTACT_FILTER_VERSION,
    }
    assert payload_violations(EventType.CONTACT_FILTER_HIT, payload) == []
