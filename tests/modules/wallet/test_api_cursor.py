"""Wave 1.6 N4: wallet cursors use the dedicated cursor signing key."""

from __future__ import annotations

from app.core.config import cursor_signing_secret, settings
from app.modules.wallet import api


def test_wallet_cursor_secret_is_the_configured_cursor_key(monkeypatch):
    assert api._cursor_secret() == cursor_signing_secret()
    monkeypatch.setattr(settings, "cursor_signing_key", "a-dedicated-cursor-signing-key-0123456789")
    assert api._cursor_secret() == cursor_signing_secret()
    token = api._next_cursor(42, "scope", page_len=1, limit=1)
    assert api._decode_after(token, "scope") == 42
