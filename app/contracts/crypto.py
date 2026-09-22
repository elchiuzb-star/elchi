"""Key derivation, proof codes and secret tokens (spec §10.6, §11; D11, D18; ADR-0018).

* Never use ``settings.secret_key`` directly for a feature. Derive a dedicated
  subkey per purpose: ``HMAC-SHA256(master, b"elchi:<purpose>:v<version>")``.
  This is the same label format H0 uses for file URL signing
  (``elchi:file-url-signing-key:v1``), so all features share one scheme.
* Proof codes are derived from the proof-code subkey, not stored in plaintext;
  the DB keeps only a keyed hash plus attempt counters.
* Tokens given to humans/links (tracking share, public listing share) come from
  ``secrets.token_bytes`` with at least 128 bits; only their SHA-256 hash is stored.

No settings access here: callers pass the master secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

PURPOSE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")

PURPOSE_BOOKING_PROOF_CODE = "booking-proof-code-key"
PURPOSE_CURSOR_SIGNING = "cursor-signing-key"
PURPOSE_FILE_URL_SIGNING = "file-url-signing-key"  # H0-owned feature; listed for uniqueness

MIN_SECRET_TOKEN_BYTES = 16
DEFAULT_SECRET_TOKEN_BYTES = 32
PROOF_CODE_DIGITS = 6


def _as_bytes(value: str | bytes, name: str) -> bytes:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raise TypeError(f"{name} must be str or bytes")
    if not raw:
        raise ValueError(f"{name} must not be empty")
    return raw


def derive_subkey(master_secret: str | bytes, purpose: str, version: int = 1) -> bytes:
    """Domain-separated 32-byte subkey for one purpose."""
    if not isinstance(purpose, str) or not PURPOSE_PATTERN.fullmatch(purpose):
        raise ValueError("purpose must be a lowercase slug")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive int")
    label = f"elchi:{purpose}:v{version}".encode("ascii")
    return hmac.new(_as_bytes(master_secret, "master_secret"), label, hashlib.sha256).digest()


def derive_proof_code(
    proof_key: bytes,
    booking_public_id: str,
    proof_kind: str,
    rotation: int,
    digits: int = PROOF_CODE_DIGITS,
) -> str:
    """Deterministic numeric code bound to booking, proof kind and rotation.

    Recomputable for the authorised recipient without storing plaintext;
    rotating (operator action after attempt limit) invalidates the old code.
    """
    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation < 0:
        raise ValueError("rotation must be a non-negative int")
    if not 4 <= digits <= 8:
        raise ValueError("digits must be between 4 and 8")
    message = f"{booking_public_id}|{proof_kind}|{rotation}".encode("utf-8")
    digest = hmac.new(_as_bytes(proof_key, "proof_key"), message, hashlib.sha256).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def proof_code_hash(proof_key: bytes, booking_public_id: str, proof_kind: str, code: str) -> str:
    """Keyed hash stored in ``booking_proofs.code_hash`` (a short code needs a keyed hash)."""
    message = f"{booking_public_id}|{proof_kind}|{code}".encode("utf-8")
    return hmac.new(_as_bytes(proof_key, "proof_key"), message, hashlib.sha256).hexdigest()


def codes_match(expected: str, provided: str) -> bool:
    return hmac.compare_digest(expected.encode("utf-8"), provided.strip().encode("utf-8"))


@dataclass(frozen=True)
class KeyRing:
    """Current subkey plus previous subkeys still accepted for verification (N5).

    New codes/signatures always use ``current``. After ``secret_key`` rotation (or a
    purpose ``version`` bump) the previous subkey stays in ``previous`` for a bounded
    window (``KEY_ROTATION_VERIFICATION_WINDOW``) so codes already shown to users keep
    working; afterwards it is removed from configuration.
    """

    current: bytes
    previous: tuple[bytes, ...] = ()

    def candidates(self) -> tuple[bytes, ...]:
        return (self.current, *self.previous)


KEY_ROTATION_VERIFICATION_WINDOW = timedelta(hours=48)
PROOF_CODE_KEY_VERSION = 1


def build_keyring(
    purpose: str,
    current_master: str | bytes,
    previous_masters: Sequence[str | bytes] = (),
    *,
    version: int = 1,
    previous_versions: Sequence[int] = (),
) -> KeyRing:
    """Derive a keyring for one purpose.

    ``previous_masters`` covers ``secret_key`` rotation (same version); ``previous_versions``
    covers a subkey version bump under the current master. Duplicates are dropped.
    """
    current = derive_subkey(current_master, purpose, version)
    previous: list[bytes] = []
    for master in previous_masters:
        previous.append(derive_subkey(master, purpose, version))
    for old_version in previous_versions:
        previous.append(derive_subkey(current_master, purpose, old_version))
    unique = tuple(dict.fromkeys(key for key in previous if key != current))
    return KeyRing(current=current, previous=unique)


def verify_proof_code(
    keyring: KeyRing,
    booking_public_id: str,
    proof_kind: str,
    rotation: int,
    provided: str,
    digits: int = PROOF_CODE_DIGITS,
) -> bool:
    """Accept a code derived with the current or any previous subkey.

    Every candidate is checked (no early exit) so timing does not reveal which key matched.
    """
    matched = False
    for key in keyring.candidates():
        expected = derive_proof_code(key, booking_public_id, proof_kind, rotation, digits)
        matched = codes_match(expected, provided) | matched
    return matched


def new_secret_token(nbytes: int = DEFAULT_SECRET_TOKEN_BYTES) -> str:
    """URL-safe token from ``secrets.token_bytes`` (>= 128 bits)."""
    if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes < MIN_SECRET_TOKEN_BYTES:
        raise ValueError(f"tokens need at least {MIN_SECRET_TOKEN_BYTES} bytes")
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def secret_token_hash(token: str) -> str:
    """SHA-256 hex stored in ``tracking_grants.token_hash`` / ``share_links.token_hash``."""
    return hashlib.sha256(_as_bytes(token, "token")).hexdigest()
