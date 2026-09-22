"""Contact-information filter for free text (Q43, ADR-0020).

Pure and dependency-free. Every free-text field a marketplace user writes before service start
(listing comment, proposal comment, chat, parcel description, rating text, profile fields) goes
through :func:`scan`; the caller stores/shows ``masked_text`` and returns the
``CONTACT_INFO_MASKED`` warning (``app.contracts.errors.WarningCode``) when ``has_contact``.

Categories: phone, email, handle, messenger_link, url, call_request; proof_code only with
``scan(text, mask_proof_codes=True)`` (chat, Q65 - 6-digit code-like chains).

Phone detection works on a normalized copy of the text (zero-width characters removed, full-width
and other Unicode decimal digits mapped to ASCII, apostrophe variants unified, lower-cased) and
accepts digit groups joined by spaces, dots, dashes, slashes and parentheses, mixed with number
words in Uzbek (Latin and Cyrillic) and Russian (Cyrillic and Latin transliteration). A digit
chain is a phone only when its shape looks like one (``+998``/``998`` + 9 digits, a local 9-digit
number with an Uzbek operator/area code, a 3-2-2 local number, or 10-15 digits that are not a
thousands-grouped amount); prices ("200 000 so'm"), dates, times and seat counts stay untouched.

Spans in results always refer to the ORIGINAL text. Filter hits carry no raw text into events
(``events.EVENT_PAYLOAD_ALLOWLIST``). The filter reduces, and cannot prevent, off-platform contact
(ADR-0020 §10); rules are versioned by :data:`CONTACT_FILTER_VERSION`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

CONTACT_FILTER_VERSION = "2026-09-15.1"  # wave 2.1: optional proof-code masking (Q65); default rules unchanged
MASK = "•••"  # "•••" - contains no digits, so masking is idempotent
PROOF_CODE_DIGITS = 6  # app.contracts.crypto.derive_proof_code default length


class ContactCategory(StrEnum):
    PHONE = "phone"
    EMAIL = "email"
    HANDLE = "handle"
    MESSENGER_LINK = "messenger_link"
    URL = "url"
    CALL_REQUEST = "call_request"
    # Q65 (chat only, ``scan(..., mask_proof_codes=True)``): a 6-digit chain that may be a boarding/pickup/
    # delivery/return code. Not a contact detail, but it must not travel through chat.
    PROOF_CODE = "proof_code"


# Overlap resolution: lower number wins.
_PRIORITY: dict[ContactCategory, int] = {
    ContactCategory.EMAIL: 0,
    ContactCategory.MESSENGER_LINK: 1,
    ContactCategory.URL: 2,
    ContactCategory.HANDLE: 3,
    ContactCategory.PHONE: 4,
    ContactCategory.CALL_REQUEST: 5,
    ContactCategory.PROOF_CODE: 6,
}


@dataclass(frozen=True, slots=True)
class ContactMatch:
    category: ContactCategory
    start: int  # index into the original text
    end: int  # exclusive


@dataclass(frozen=True, slots=True)
class ContactScanResult:
    matches: tuple[ContactMatch, ...]
    masked_text: str
    filter_version: str = CONTACT_FILTER_VERSION

    @property
    def has_contact(self) -> bool:
        return bool(self.matches)

    @property
    def categories(self) -> frozenset[ContactCategory]:
        return frozenset(match.category for match in self.matches)

    def warning_details(self) -> dict[str, object]:
        """Details for the ``CONTACT_INFO_MASKED`` warning; never includes the matched text."""
        return {
            "categories": sorted(category.value for category in self.categories),
            "match_count": len(self.matches),
            "filter_version": self.filter_version,
        }


# --- normalization ---------------------------------------------------------------------------

_ZERO_WIDTH = frozenset("​‌‍⁠﻿­᠎⁡⁢⁣⁤")
_APOSTROPHES = frozenset("‘’ʻʼʹ`´′")


def _normalize(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index: list[int] = []
    for position, char in enumerate(text):
        if char in _ZERO_WIDTH or unicodedata.category(char) == "Cf":
            continue
        if char in _APOSTROPHES:
            char = "'"
        else:
            decimal = unicodedata.decimal(char, None)
            if decimal is not None:
                char = str(decimal)
            else:
                folded = unicodedata.normalize("NFKC", char)
                if len(folded) == 1:
                    char = folded
        lowered = char.lower()
        if len(lowered) == 1:
            char = lowered
        chars.append(char)
        index.append(position)
    return "".join(chars), index


# --- number words ----------------------------------------------------------------------------

# kind: U unit 0-9, T tens (takes a unit), N closed two-digit (11-19), H "hundred" multiplier,
# HH closed hundreds 200-900 (takes tens/unit).
_WORDS: dict[str, tuple[str, int]] = {}


def _add(kind: str, value: int, *words: str) -> None:
    for word in words:
        _WORDS[word.replace("'", "")] = (kind, value)


# Uzbek (Latin)
for _value, _words in enumerate(
    [("nol",), ("bir",), ("ikki",), ("uch",), ("to'rt", "tort"), ("besh",), ("olti",), ("yetti",),
     ("sakkiz",), ("to'qqiz", "toqqiz")]
):
    _add("U", _value, *_words)
_add("T", 10, "o'n", "on")
_add("T", 20, "yigirma")
_add("T", 30, "o'ttiz", "ottiz")
_add("T", 40, "qirq")
_add("T", 50, "ellik")
_add("T", 60, "oltmish")
_add("T", 70, "yetmish")
_add("T", 80, "sakson")
_add("T", 90, "to'qson", "toqson")
_add("H", 100, "yuz")
# Uzbek (Cyrillic)
for _value, _words in enumerate(
    [("нол", "ноль"), ("бир",), ("икки",), ("уч",), ("тўрт", "турт"), ("беш",), ("олти",), ("етти",),
     ("саккиз",), ("тўққиз", "туккиз", "тўккиз")]
):
    _add("U", _value, *_words)
_add("T", 10, "ўн", "ун")
_add("T", 20, "йигирма")
_add("T", 30, "ўттиз", "уттиз")
_add("T", 40, "қирқ", "кирк")
_add("T", 50, "эллик")
_add("T", 60, "олтмиш")
_add("T", 70, "етмиш")
_add("T", 80, "саксон")
_add("T", 90, "тўқсон", "туксон")
_add("H", 100, "юз")
# Russian (Cyrillic)
for _value, _words in enumerate(
    [("ноль", "нуль"), ("один", "одна"), ("два", "две"), ("три",), ("четыре",), ("пять",), ("шесть",),
     ("семь",), ("восемь",), ("девять",)]
):
    _add("U", _value, *_words)
for _value, _word in enumerate(
    ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
     "семнадцать", "восемнадцать", "девятнадцать"]
):
    _add("N" if _value else "T", 10 + _value, _word)
for _value, _word in zip(
    range(20, 100, 10),
    ["двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"],
):
    _add("T", _value, _word)
_add("H", 100, "сто")
for _value, _word in zip(
    range(200, 1000, 100), ["двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
):
    _add("HH", _value, _word)
# Russian (Latin transliteration)
for _value, _words in enumerate(
    [("nol", "nul"), ("odin", "odna"), ("dva", "dve"), ("tri",), ("chetyre",), ("pyat", "pyat'"), ("shest",),
     ("sem",), ("vosem",), ("devyat",)]
):
    for _word in _words:
        _WORDS.setdefault(_word.replace("'", ""), ("U", _value))
for _value, _word in enumerate(
    ["desyat", "odinnadtsat", "dvenadtsat", "trinadtsat", "chetyrnadtsat", "pyatnadtsat", "shestnadtsat",
     "semnadtsat", "vosemnadtsat", "devyatnadtsat"]
):
    _add("N" if _value else "T", 10 + _value, _word)
for _value, _word in zip(
    range(20, 100, 10),
    ["dvadtsat", "tridtsat", "sorok", "pyatdesyat", "shestdesyat", "semdesyat", "vosemdesyat", "devyanosto"],
):
    _add("T", _value, _word)
_add("H", 100, "sto")
for _value, _word in zip(
    range(200, 1000, 100), ["dvesti", "trista", "chetyresta", "pyatsot", "shestsot", "semsot", "vosemsot", "devyatsot"]
):
    _add("HH", _value, _word)


def _word_value(word: str) -> tuple[str, int] | None:
    return _WORDS.get(word.replace("'", ""))


def _words_to_groups(values: list[tuple[str, int]]) -> list[str]:
    """Spoken digit groups -> digit strings, e.g. to'qson bir -> "91", сто двадцать три -> "123"."""
    groups: list[str] = []
    i, n = 0, len(values)

    def unit_at(k: int) -> bool:
        return k < n and values[k][0] == "U" and not (k + 1 < n and values[k + 1][0] == "H")

    while i < n:
        kind, value = values[i]
        if (kind == "U" and i + 1 < n and values[i + 1][0] == "H") or kind in ("H", "HH"):
            if kind == "U":
                total, i = max(value, 1) * 100, i + 2
            else:
                total, i = value, i + 1
            if i < n and values[i][0] == "N":
                total, i = total + values[i][1], i + 1
            else:
                if i < n and values[i][0] == "T":
                    total, i = total + values[i][1], i + 1
                if unit_at(i):
                    total, i = total + values[i][1], i + 1
            groups.append(str(total))
        elif kind == "N":
            groups.append(str(value))
            i += 1
        elif kind == "T":
            total, i = value, i + 1
            if unit_at(i):
                total, i = total + values[i][1], i + 1
            groups.append(str(total))
        else:
            groups.append(str(value))
            i += 1
    return groups


# --- patterns (applied to the normalized, lower-cased text) ----------------------------------

_EMAIL = re.compile(
    r"[a-z0-9][a-z0-9._%+-]*\s*(?:@|\(at\)|\[at\])\s*[a-z0-9-]+(?:\s*(?:\.|\(dot\)|\[dot\])\s*[a-z0-9-]+)*"
    r"\s*(?:\.|\(dot\)|\[dot\])\s*[a-z]{2,10}\b"
)
_MESSENGER_LINK = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.(?:me|org|dog)|wa\.me|(?:api\.|web\.|chat\.)?whatsapp\.com"
    r"|instagram\.com|instagr\.am|viber\.com|invite\.viber\.com|vk\.com|ok\.ru|facebook\.com|fb\.me|m\.me)"
    r"(?:/[^\s]*)?"
    r"|\b(?:telegram\w*|telegramm\w*|телеграм\w*|whats\s?app\w*|wats?app\w*|vatsap\w*|ватсап\w*|вотсап\w*"
    r"|instagram\w*|инстаграм\w*|insta|инста|viber\w*|вайбер\w*)"
)
_URL = re.compile(
    r"\b(?:https?://|www\.)[^\s]+"
    r"|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:uz|com|ru|org|net|me|io|info|xyz|su|kz|tj|kg)\b(?:/[^\s]*)?"
)
_HANDLE = re.compile(r"(?<![\w.@])@[a-z0-9_](?:[a-z0-9_.]{2,31})")
_CALL_REQUEST = re.compile(
    r"\bqo'?ng'?iroq\w*|\bqongiroq\w*|\b(?:telefon|tel)\s+qil\w*|\braqam(?:im|imni|imga)\b|\bnomer(?:im|imni|imga)\b"
    r"|\baloqaga\s+chiq\w*"
    r"|\bқўнғироқ\w*|\bқонғироқ\w*|\bкунгирок\w*|\bқўнгироқ\w*|\bтелефон\s+қил\w*|\bрақам(?:им|имни|имга)\b"
    r"|\bномер(?:им|имни|имга)\b"
    r"|\b(?:по|пере)?звон\w*|\bнабер(?:и|ите)\b|\bмой\s+(?:номер|телефон|тел)\b|\bномер\s+телефона\b"
    r"|\bсвяж(?:ись|итесь)\b"
    r"|\b(?:po|pere)?zvon\w*|\bnaberi(?:te)?\b|\bmoy\s+nomer\b"
    r"|\b(?:tel|тел)\s*[:]"
)
# Dates are opaque for the phone scanner (dd.mm.yyyy, yyyy-mm-dd with 4-digit years 19xx/20xx).
_DATE = re.compile(
    r"(?<!\d)(?:(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}"
    r"|(?:19|20)\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01]))(?!\d)"
)
_TOKEN = re.compile(r"(?P<num>\d+)|(?P<word>[^\W\d_]+(?:'[^\W\d_]+)*)|(?P<space>\s+)|(?P<punct>.)", re.DOTALL)
_SEPARATORS = frozenset("-./()")
_CURRENCY_CUES = ("so'm", "som", "sum", "сум", "сўм", "сом", "uzs", "ming", "минг", "тыс", "млн", "mln", "million",
                  "миллион", "mlrd", "usd", "dollar", "доллар", "руб", "rubl", "kg", "кг", "km", "км", "%", "$")
# Uzbek mobile operator and Tashkent area codes for local 9-digit numbers.
_UZ_CODES = frozenset({"20", "33", "50", "55", "61", "62", "65", "66", "67", "69", "71", "72", "73", "74", "75",
                       "76", "77", "78", "79", "88", "90", "91", "93", "94", "95", "97", "98", "99"})


@dataclass(slots=True)
class _Token:
    kind: str
    start: int
    end: int
    text: str
    groups: list[str] | None = None  # digit groups for numeric tokens


def _tokens(normalized: str) -> list[_Token]:
    blocked = [(m.start(), m.end()) for m in _DATE.finditer(normalized)]
    result: list[_Token] = []
    for match in _TOKEN.finditer(normalized):
        kind = match.lastgroup or "punct"
        start, end = match.span()
        if any(b_start <= start < b_end for b_start, b_end in blocked):
            kind = "blocked"
        result.append(_Token(kind, start, end, match.group()))
    return result


def _is_numeric(token: _Token) -> bool:
    return token.kind == "num" or (token.kind == "word" and _word_value(token.text) is not None)


def _thousands_amount(groups: list[int], digits: str) -> bool:
    return (
        len(groups) >= 2
        and 1 <= groups[0] <= 3
        and all(size == 3 for size in groups[1:])
        and digits.endswith("000")
    )


def _looks_like_phone(digits: str, groups: list[int], has_plus: bool) -> bool:
    n = len(digits)
    if has_plus and 10 <= n <= 15:
        return True
    if digits.startswith("998") and n == 12:
        return True
    if _thousands_amount(groups, digits):
        return False
    if n == 9 and digits[:2] in _UZ_CODES:
        return True
    if n == 7 and groups == [3, 2, 2]:
        return True
    return 10 <= n <= 15


def _looks_like_proof_code(digits: str, groups: list[int]) -> bool:
    """Q65: exactly six digits that are not a thousands-grouped amount ("150 000")."""
    return len(digits) == PROOF_CODE_DIGITS and not _thousands_amount(groups, digits)


def _phone_spans(normalized: str, *, mask_proof_codes: bool = False) -> list[tuple[ContactCategory, int, int]]:
    tokens = _tokens(normalized)
    spans: list[tuple[ContactCategory, int, int]] = []
    i = 0
    while i < len(tokens):
        if not _is_numeric(tokens[i]):
            i += 1
            continue
        parts = [i]
        j = i + 1
        separator_len = 0
        separator_text = ""
        while j < len(tokens):
            token = tokens[j]
            if _is_numeric(token):
                # " - " style separators mean a range ("90 000 - 95 000"), not a phone.
                is_range = "-" in separator_text and " " in separator_text
                # Commas join only spoken groups ("to'qson bir, bir yuz yigirma uch"), never digit amounts.
                comma_between_digits = "," in separator_text and not (
                    tokens[parts[-1]].kind == "word" and token.kind == "word"
                )
                if separator_len > 3 or is_range or comma_between_digits or separator_text.count("\n") > 0:
                    break
                parts.append(j)
                separator_len, separator_text = 0, ""
                j += 1
                continue
            if token.kind == "space" or (token.kind == "punct" and (token.text in _SEPARATORS or token.text == ",")):
                separator_len += len(token.text)
                separator_text += token.text
                if separator_len > 3:
                    break
                j += 1
                continue
            break
        last = parts[-1]
        spans.extend(_evaluate_chain(normalized, tokens, parts, mask_proof_codes=mask_proof_codes))
        i = last + 1
    return spans


def _evaluate_chain(
    normalized: str, tokens: list[_Token], parts: list[int], *, mask_proof_codes: bool = False
) -> list[tuple[ContactCategory, int, int]]:
    digits = ""
    groups: list[int] = []
    pending_words: list[tuple[str, int]] = []

    def flush() -> None:
        nonlocal digits
        for group in _words_to_groups(pending_words):
            digits += group
            groups.append(len(group))
        pending_words.clear()

    for index in parts:
        token = tokens[index]
        if token.kind == "num":
            flush()
            digits += token.text
            groups.append(len(token.text))
        else:
            value = _word_value(token.text)
            assert value is not None
            pending_words.append(value)
    flush()

    first, last = tokens[parts[0]], tokens[parts[-1]]
    start = first.start
    has_plus = False
    k = parts[0] - 1
    while k >= 0 and tokens[k].kind in ("space", "punct") and tokens[k].text in ("(", "+", " ") and start - tokens[k].start <= 3:
        if tokens[k].text == "+":
            has_plus = True
        if tokens[k].text in "(+":
            start = tokens[k].start
        k -= 1

    # Currency / unit cue right after the chain -> an amount, not a phone.
    k = parts[-1] + 1
    while k < len(tokens) and tokens[k].kind == "space":
        k += 1
    if k < len(tokens) and tokens[k].kind in ("word", "punct"):
        following = normalized[tokens[k].start : tokens[k].start + 8]
        if any(following.startswith(cue) for cue in _CURRENCY_CUES) and not has_plus:
            return []

    if _looks_like_phone(digits, groups, has_plus):
        return [(ContactCategory.PHONE, start, last.end)]
    if mask_proof_codes and _looks_like_proof_code(digits, groups):
        return [(ContactCategory.PROOF_CODE, start, last.end)]
    return []


# --- public API --------------------------------------------------------------------------------


def scan(text: str, *, mask_proof_codes: bool = False) -> ContactScanResult:
    """Detect and mask contact details. ``mask_proof_codes=True`` (chat, Q65) also masks 6-digit code-like chains
    (category ``proof_code``); thousands-grouped amounts ("150 000") and amounts with a currency cue stay.
    Known chat false positives: other bare six-digit numbers ("150000", "15 09 26")."""
    if not text:
        return ContactScanResult(matches=(), masked_text=text or "")
    normalized, index = _normalize(text)
    candidates: list[tuple[ContactCategory, int, int]] = []
    for category, pattern in (
        (ContactCategory.EMAIL, _EMAIL),
        (ContactCategory.MESSENGER_LINK, _MESSENGER_LINK),
        (ContactCategory.URL, _URL),
        (ContactCategory.HANDLE, _HANDLE),
        (ContactCategory.CALL_REQUEST, _CALL_REQUEST),
    ):
        candidates.extend((category, m.start(), m.end()) for m in pattern.finditer(normalized) if m.end() > m.start())
    candidates.extend(_phone_spans(normalized, mask_proof_codes=mask_proof_codes))

    accepted: list[tuple[ContactCategory, int, int]] = []
    for category, start, end in sorted(candidates, key=lambda c: (_PRIORITY[c[0]], c[1], -c[2])):
        if all(end <= a_start or start >= a_end for _, a_start, a_end in accepted):
            accepted.append((category, start, end))
    accepted.sort(key=lambda c: c[1])

    matches = tuple(ContactMatch(category, index[start], index[end - 1] + 1) for category, start, end in accepted)
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start])
        pieces.append(MASK)
        cursor = match.end
    pieces.append(text[cursor:])
    return ContactScanResult(matches=matches, masked_text="".join(pieces))


def mask(text: str, *, mask_proof_codes: bool = False) -> str:
    return scan(text, mask_proof_codes=mask_proof_codes).masked_text
