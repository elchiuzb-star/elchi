"""The stage-2 client asks for as many OTP digits as the backend issues (Q8, wave 13).

`auth_service` accepts a code only when `len(otp) == settings.otp_length` (5 in this repo's `.env`). A client
that disagrees is not a cosmetic bug: `mobile-app` labelled the field "5 xonali kod" but enabled the submit
button only at six characters, so a real code could never be sent and login was impossible.

The fix was to derive the label, the placeholder, the input clipping and the gate from one number read from
the environment. These tests hold that shape: one source of truth, matching the backend's length.

`frontend/` is frozen (AGENTS §2) and is not asserted here; its own default is noted in the wave card.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import settings

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "mobile-app" / "src" / "app" / "ConnectedApp.tsx"
DEFAULT = re.compile(r"Number\(import\.meta\.env\.VITE_OTP_LENGTH\)\s*\|\|\s*(\d+)")

pytestmark = pytest.mark.skipif(not CLIENT.is_file(), reason="mobile-app sources are not present")


def source() -> str:
    return CLIENT.read_text(encoding="utf-8")


def test_the_client_default_matches_the_backend() -> None:
    found = DEFAULT.findall(source())
    assert found, "the client should read VITE_OTP_LENGTH with a default, not hard-code the digit count"
    assert {int(value) for value in found} == {settings.otp_length}, (
        f"the client defaults to {found}, the backend issues {settings.otp_length} digits"
    )


def test_the_otp_screen_never_writes_a_digit_count_into_its_own_text() -> None:
    otp_screen = source().split('if (screen === "otp")', 1)[-1].split('if (screen ===', 1)[0]
    stray = re.findall(r"\b(\d+)\s+xonali", otp_screen)
    assert stray == [], f"the OTP screen writes a digit count into its own text: {stray}"


def test_the_submit_gate_asks_for_exactly_that_many_digits() -> None:
    """The original bug: the field said five, the button unlocked at six, so no real code could be sent."""
    text = source()
    assert "otp.length !== OTP_LENGTH" in text, "the submit gate must compare against OTP_LENGTH"
    assert not re.search(r"otp\.trim\(\)\.length\s*[<>]", text), "no loose length comparison on the code"
