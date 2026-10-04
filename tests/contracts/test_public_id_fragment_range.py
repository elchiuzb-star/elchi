"""Staff lookup by a short code (admin panel): a code prefix maps to one contiguous UUID range."""

import uuid

import pytest

from app.contracts.ids import (
    MIN_CODE_FRAGMENT_LENGTH,
    PublicIdPrefix,
    format_public_id,
    public_id_fragment_range,
)


def test_every_prefix_of_a_code_brackets_its_uuid() -> None:
    for _ in range(500):
        value = uuid.uuid4()
        public_id = format_public_id(PublicIdPrefix.BOOKING, value)
        code = public_id.partition("_")[2]
        for length in range(MIN_CODE_FRAGMENT_LENGTH, len(code) + 1):
            for text in (code[:length], code[:length].upper(), f"bkg_{code[:length]}"):
                low, high = public_id_fragment_range(text, PublicIdPrefix.BOOKING)
                assert low.bytes <= value.bytes <= high.bytes


def test_the_full_code_is_an_exact_match() -> None:
    value = uuid.uuid4()
    low, high = public_id_fragment_range(format_public_id(PublicIdPrefix.TRIP, value), PublicIdPrefix.TRIP)
    assert low == high == value


@pytest.mark.parametrize("text", ["abc", "trp_abcd", "ab1d", "abcd!", "", "bkg_", "a" * 27])
def test_what_cannot_start_a_booking_code_is_refused(text: str) -> None:
    assert public_id_fragment_range(text, PublicIdPrefix.BOOKING) is None
