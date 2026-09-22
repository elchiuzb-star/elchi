import uuid
from datetime import datetime

import pytest

from app.contracts.cursor import decode_cursor, encode_cursor
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.idempotency import canonical_json, request_hash, validate_idempotency_key

SECRET = b"test-secret-for-cursors"
SCOPE = "GET /api/v2/feed?service=passenger"


def test_cursor_round_trip_with_tie_breaker() -> None:
    values = [88, "2026-09-13T07:45:00Z", 42, None, True]
    token = encode_cursor(values, scope=SCOPE, secret=SECRET)
    assert decode_cursor(token, scope=SCOPE, secret=SECRET) == values


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t[:-1] + ("A" if t[-1] != "A" else "B"),
        lambda t: "x" + t,
        lambda t: t.replace(".", ""),
        lambda t: "",
        lambda t: "a.b.c",
    ],
)
def test_cursor_tampering_is_rejected(mutate) -> None:
    token = encode_cursor([1, 2], scope=SCOPE, secret=SECRET)
    with pytest.raises(DomainError) as exc:
        decode_cursor(mutate(token), scope=SCOPE, secret=SECRET)
    assert exc.value.code is ErrorCode.INVALID_CURSOR


def test_cursor_bound_to_scope_and_secret() -> None:
    token = encode_cursor([1], scope=SCOPE, secret=SECRET)
    with pytest.raises(DomainError):
        decode_cursor(token, scope="GET /api/v2/feed?service=parcel", secret=SECRET)
    with pytest.raises(DomainError):
        decode_cursor(token, scope=SCOPE, secret=b"other-secret")


@pytest.mark.parametrize("bad", [[1.5], [datetime(2026, 1, 1)], [], "abc"])
def test_cursor_rejects_unsupported_values(bad) -> None:
    with pytest.raises((TypeError, ValueError)):
        encode_cursor(bad, scope=SCOPE, secret=SECRET)


def test_request_hash_ignores_key_order_but_not_content() -> None:
    a = request_hash("post", "/api/v2/proposals/{proposal_id}/accept", {"x": 1, "y": [1, 2]}, {"proposal_id": "prp_a"})
    b = request_hash("POST", "/api/v2/proposals/{proposal_id}/accept", {"y": [1, 2], "x": 1}, {"proposal_id": "prp_a"})
    assert a == b
    assert a != request_hash("POST", "/api/v2/proposals/{proposal_id}/accept", {"x": 2, "y": [1, 2]}, {"proposal_id": "prp_a"})
    assert a != request_hash("POST", "/api/v2/proposals/{proposal_id}/accept", {"x": 1, "y": [1, 2]}, {"proposal_id": "prp_b"})


def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_idempotency_key_validation() -> None:
    assert validate_idempotency_key("0b6f6c1e-7f7a-4a2e-9a55-3d1c2b1a0f00")
    with pytest.raises(DomainError) as missing:
        validate_idempotency_key(None)
    assert missing.value.code is ErrorCode.IDEMPOTENCY_KEY_REQUIRED
    with pytest.raises(DomainError) as invalid:
        validate_idempotency_key("short")
    assert invalid.value.code is ErrorCode.IDEMPOTENCY_KEY_INVALID
    with pytest.raises(DomainError):
        validate_idempotency_key("has space in the key")


def test_public_id_round_trip() -> None:
    value = new_public_uuid()
    text = format_public_id(PublicIdPrefix.BOOKING, value)
    assert text.startswith("bkg_") and len(text) == 30
    assert parse_public_id(text, PublicIdPrefix.BOOKING) == value


def test_public_id_wrong_or_malformed_is_not_found() -> None:
    text = format_public_id(PublicIdPrefix.BOOKING, uuid.UUID(int=12345))
    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    # The 26th char carries 3 data bits and 2 zero padding bits; setting a
    # padding bit yields a same-length but non-canonical encoding.
    non_canonical_last = alphabet[alphabet.index(text[-1]) | 1]
    candidates = [
        text.replace("bkg_", "lst_"),
        text.upper(),
        text[:-1],
        "bkg_" + "!" * 26,
        "12345",
        text[:-1] + non_canonical_last,
    ]
    for candidate in candidates:
        with pytest.raises(DomainError) as exc:
            parse_public_id(candidate, PublicIdPrefix.BOOKING)
        assert exc.value.code is ErrorCode.NOT_FOUND
