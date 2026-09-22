"""Opaque public identifiers for API v2 (spec §14, ADR-0002).

New v2 tables keep a ``BIGINT`` identity primary key for joins, FKs and the
global lock order (spec §15), plus a ``public_id UUID NOT NULL UNIQUE`` column
generated with :func:`new_public_uuid`. The API only ever exposes the prefixed
form ``<prefix>_<26 lowercase base32 chars>``, e.g. ``bkg_...``.

A malformed id, or an id with the wrong prefix, is reported as ``NOT_FOUND`` so
id probing reveals nothing.
"""

from __future__ import annotations

import base64
import uuid
from enum import StrEnum

from app.contracts.errors import DomainError, ErrorCode

_ENCODED_LENGTH = 26  # 128 bits in base32 without padding


class PublicIdPrefix(StrEnum):
    USER = "usr"
    VEHICLE = "veh"
    CORRIDOR = "cor"
    STOP = "stp"
    ROUTE_VERSION = "rtv"
    TRIP = "trp"
    LISTING = "lst"
    SAVED_SEARCH = "svs"
    PROPOSAL_THREAD = "prp"
    PROPOSAL_VERSION = "prv"
    BOOKING = "bkg"
    AMENDMENT = "amd"
    CASH_RECEIPT = "csh"
    WALLET = "wal"
    LEDGER_TRANSACTION = "ltx"
    TOPUP = "top"
    COMMISSION_POLICY = "cmp"
    FEATURE_FLAG = "flg"
    TRACKING_SESSION = "trs"
    TRACKING_GRANT = "trg"
    RATING = "rat"
    DISPUTE = "dsp"
    REPORT = "rpt"
    SHARE_LINK = "shl"
    DEVICE = "dev"
    CHAT_THREAD = "cht"
    CHAT_MESSAGE = "msg"
    EVENT = "evt"
    # Integration pass 1 (additive): A3 ledger adjustment requests, A2 geo catalogue.
    LEDGER_ADJUSTMENT = "adj"
    REGION = "reg"
    DISTRICT = "dst"
    # Wave 3 (additive): A12 support tickets and trust review items, A7 notification inbox rows.
    SUPPORT_TICKET = "sup"
    TRUST_REVIEW = "trv"
    NOTIFICATION = "ntf"
    # Wave 6 (additive): A12 blocks and fraud signals (S9-S12, §8.1, §17.3).
    USER_BLOCK = "blk"
    FRAUD_SIGNAL = "fsg"
    # Wave 7 (additive): §5.2 parcel policy versions.
    PARCEL_POLICY = "ppv"
    STAFF_MFA_FACTOR = "mfa"


def new_public_uuid() -> uuid.UUID:
    """Random 122-bit UUIDv4 from the stdlib CSPRNG; no new dependency."""
    return uuid.uuid4()


def format_public_id(prefix: PublicIdPrefix, value: uuid.UUID) -> str:
    if not isinstance(prefix, PublicIdPrefix):
        raise TypeError("prefix must be a PublicIdPrefix")
    if not isinstance(value, uuid.UUID):
        raise TypeError("value must be a UUID")
    encoded = base64.b32encode(value.bytes).decode("ascii").rstrip("=").lower()
    return f"{prefix.value}_{encoded}"


def parse_public_id(text: str, expected: PublicIdPrefix) -> uuid.UUID:
    not_found = DomainError(ErrorCode.NOT_FOUND)
    if not isinstance(text, str):
        raise not_found
    prefix, sep, encoded = text.partition("_")
    if sep != "_" or prefix != expected.value or len(encoded) != _ENCODED_LENGTH or encoded != encoded.lower():
        raise not_found
    try:
        raw = base64.b32decode(encoded.upper() + "======")
    except (ValueError, TypeError):
        raise not_found from None
    if len(raw) != 16:
        raise not_found
    value = uuid.UUID(bytes=raw)
    # Reject non-canonical encodings (trailing bits set) so one UUID has one id.
    if format_public_id(expected, value) != text:
        raise not_found
    return value
