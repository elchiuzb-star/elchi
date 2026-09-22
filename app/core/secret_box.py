"""Authenticated encryption for secrets that the platform must be able to read back (ADR-0022).

Most secrets in Elchi are stored as a hash and never recovered: proof codes, share-link tokens, passwords. A
push registration token is different - FCM needs the token itself to deliver a message - so it is the first
value that has to survive a round trip. It is therefore encrypted at rest rather than stored in the clear.

Design:

* AES-256-GCM, key derived per purpose with :func:`app.contracts.crypto.derive_subkey`, so this key is not the
  application secret and cannot decrypt anything else;
* a random 96-bit nonce per message, stored in front of the ciphertext;
* ``key_version`` travels with the row so a key rotation can re-encrypt in the background instead of
  invalidating every device at once;
* ``aad`` binds the ciphertext to its row (e.g. the device public id). A ciphertext moved to another row fails
  to decrypt instead of quietly authenticating the wrong device.

This module lives in ``app/core`` and not in ``app/contracts`` on purpose: contracts stay dependency-free
(AGENTS §4) and AES-GCM needs ``cryptography``.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.contracts.crypto import derive_subkey

NONCE_BYTES = 12
CURRENT_KEY_VERSION = 1


class SecretBoxError(ValueError):
    """The ciphertext did not authenticate: wrong key, wrong row, or the bytes were tampered with."""


def _aesgcm(master_secret: str | bytes, purpose: str, key_version: int) -> AESGCM:
    return AESGCM(derive_subkey(master_secret, purpose, key_version)[:32])


def seal(master_secret: str | bytes, purpose: str, plaintext: str, *, aad: str, key_version: int = CURRENT_KEY_VERSION) -> bytes:
    """Encrypt ``plaintext``; the result is ``nonce || ciphertext`` and is safe to store in a BYTEA column."""
    if not plaintext:
        raise ValueError("refusing to seal an empty value: an empty token is a bug, not a secret")
    nonce = os.urandom(NONCE_BYTES)
    box = _aesgcm(master_secret, purpose, key_version)
    return nonce + box.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))


def open_sealed(master_secret: str | bytes, purpose: str, sealed: bytes, *, aad: str, key_version: int = CURRENT_KEY_VERSION) -> str:
    """Decrypt what :func:`seal` produced. Raises :class:`SecretBoxError` rather than returning junk."""
    if sealed is None or len(sealed) <= NONCE_BYTES:
        raise SecretBoxError("sealed value is too short to contain a nonce and a ciphertext")
    nonce, ciphertext = bytes(sealed[:NONCE_BYTES]), bytes(sealed[NONCE_BYTES:])
    box = _aesgcm(master_secret, purpose, key_version)
    try:
        return box.decrypt(nonce, ciphertext, aad.encode("utf-8")).decode("utf-8")
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise SecretBoxError("sealed value failed authentication") from exc
