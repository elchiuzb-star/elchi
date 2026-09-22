"""Private upload storage: storage keys, signed download URLs, attachment rules.

Uploads (driver passport/selfie/license/car documents, cargo photos) are no
longer served by a public static mount. Every URL handed to a client is a
short-lived HMAC-signed link to ``GET /api/v1/files/{key}?exp=..&sig=..``.
The link is the credential, because v1 clients render these with a plain
``<img src>`` / RN ``<Image source={{uri}}>`` that cannot send a Bearer header.
Links are only minted inside responses that are already authorized for the
viewer, so visibility rules stay exactly where they were.

Storage key grammar (relative to ``settings.upload_dir``)::

    {upload_type}/{YYYY}/{MM}/u{uploader_id}/{name}.{ext}   # new uploads
    {upload_type}/{YYYY}/{MM}/{name}.{ext}                  # legacy uploads

DB columns keep the historical ``/uploads/<key>`` form so a rollback to the
previous release (which served ``/uploads`` statically) still renders files.
Values are normalized to a key at read time, so legacy rows, absolute URLs,
bare keys and previously issued signed URLs all resolve to the same key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from pathlib import Path
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit

from app.core.config import settings
from app.utils.file_validation import ALLOWED_DOCUMENT_EXTENSIONS, ALLOWED_UPLOAD_TYPES

_SIGNATURE_VERSION = "elchi-file-url-v1"
_FALLBACK_KEY_LABEL = b"elchi:file-url-signing-key:v1"
# Expiry is rounded up to this grid so the same file yields the same URL for a
# few minutes: RN/browser image caches keep working across list re-renders.
_EXPIRY_BUCKET_SECONDS = 300

KEY_PATTERN = re.compile(
    r"(?P<upload_type>" + "|".join(sorted(ALLOWED_UPLOAD_TYPES)) + r")"
    r"/(?P<year>\d{4})/(?P<month>\d{2})"
    r"/(?:u(?P<owner_id>[1-9]\d{0,18})/)?"
    r"(?P<name>[A-Za-z0-9_-]{1,64})\.(?P<ext>" + "|".join(sorted(ALLOWED_DOCUMENT_EXTENSIONS)) + r")"
)

# base64url without padding, ASCII only.
_SIGNATURE_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")

MIME_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
}


class FileReferenceError(ValueError):
    """A client-supplied file reference cannot be attached by this user."""


def _signing_key() -> bytes:
    explicit = settings.file_url_signing_key
    if explicit:
        return explicit.encode("utf-8")
    # Domain-separated derivation: never MAC with the raw JWT secret.
    return hmac.new(settings.secret_key.encode("utf-8"), _FALLBACK_KEY_LABEL, hashlib.sha256).digest()


def _ttl_seconds() -> int:
    return max(1, int(settings.file_url_ttl_seconds))


def _bucket_seconds() -> int:
    return min(_EXPIRY_BUCKET_SECONDS, _ttl_seconds())


def is_valid_key(key: str | None) -> bool:
    return bool(key) and KEY_PATTERN.fullmatch(key) is not None


def normalize_storage_key(value: str | None) -> str | None:
    """Map any stored/client value that points into our upload store to its key.

    Accepts ``/uploads/<key>``, ``https://host/uploads/<key>``,
    ``/api/v1/files/<key>?exp=..&sig=..`` (relative or absolute) and a bare key.
    Returns None for anything else, including traversal attempts.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > 2048:
        return None
    path = urlsplit(raw).path if "://" in raw or raw.startswith("/") or "?" in raw else raw
    path = unquote(path)

    download_prefix = f"{settings.api_v1_prefix.rstrip('/')}/files/"
    storage_prefix = f"{settings.public_upload_base_url.rstrip('/')}/"
    if path.startswith(download_prefix):
        key = path[len(download_prefix):]
    elif path.startswith(storage_prefix):
        key = path[len(storage_prefix):]
    elif path.startswith("/"):
        return None
    else:
        key = path
    return key if is_valid_key(key) else None


def key_owner_id(key: str) -> int | None:
    match = KEY_PATTERN.fullmatch(key)
    if match is None or match.group("owner_id") is None:
        return None
    return int(match.group("owner_id"))


def key_extension(key: str) -> str:
    match = KEY_PATTERN.fullmatch(key)
    return match.group("ext") if match else ""


def stored_value_for_key(key: str) -> str:
    """DB representation of a key (legacy ``/uploads/<key>`` form, rollback-safe)."""
    return f"{settings.public_upload_base_url.rstrip('/')}/{key}"


def resolve_upload_path(key: str | None) -> Path | None:
    """Absolute path for a key, guaranteed to be inside the upload root."""
    if not is_valid_key(key):
        return None
    root = Path(settings.upload_dir).resolve()
    candidate = (root / key).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        return None
    return candidate


def _signature(key: str, exp: int) -> str:
    message = f"{_SIGNATURE_VERSION}\n{key}\n{exp}".encode("utf-8")
    digest = hmac.new(_signing_key(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def sign_file_key(key: str, now: float | None = None) -> str:
    """Relative signed download URL for a valid storage key."""
    if not is_valid_key(key):
        raise ValueError("Invalid storage key")
    current = int(now if now is not None else time.time())
    bucket = _bucket_seconds()
    exp = -(-(current + _ttl_seconds()) // bucket) * bucket
    return f"{settings.api_v1_prefix.rstrip('/')}/files/{key}?exp={exp}&sig={_signature(key, exp)}"


def signed_file_url(stored_value: str | None) -> str | None:
    """Signed URL for a DB value, or None when it does not point into our store."""
    key = normalize_storage_key(stored_value)
    return sign_file_key(key) if key else None


def signed_url_expiry(now: float | None = None) -> int:
    """The ``exp`` a URL minted right now carries (the bucket grid `sign_file_key` rounds up to)."""
    current = int(now if now is not None else time.time())
    bucket = _bucket_seconds()
    return -(-(current + _ttl_seconds()) // bucket) * bucket


def media_ref(stored_value: str | None, now: float | None = None) -> dict[str, str] | None:
    """Everything a client needs to render one private upload, or None if there is nothing to render.

    The caller decides **whether** this viewer may see the file; this function only mints the link. The key is
    returned beside the URL because it is a stable identity for caching and support, and it grants nothing on
    its own: without ``exp``/``sig`` the download endpoint answers 403 (`verify_file_signature`).
    """
    key = normalize_storage_key(stored_value)
    if key is None:
        return None
    exp = signed_url_expiry(now)
    return {
        "file_id": key,
        "url": f"{settings.api_v1_prefix.rstrip('/')}/files/{key}?exp={exp}&sig={_signature(key, exp)}",
        "expires_at": datetime.fromtimestamp(exp, tz=UTC).isoformat().replace("+00:00", "Z"),
        "content_type": MIME_BY_EXTENSION.get(key_extension(key), "application/octet-stream"),
    }


def verify_file_signature(key: str, exp: str | None, sig: str | None, now: float | None = None) -> bool:
    if not is_valid_key(key) or not exp or not sig or len(exp) > 12 or len(sig) > 128:
        return False
    # isdigit() alone accepts non-ASCII digits such as "²" that int() rejects,
    # and compare_digest() raises on non-ASCII str: both must be 403, not 500.
    if not (exp.isascii() and exp.isdigit()) or _SIGNATURE_PATTERN.fullmatch(sig) is None:
        return False
    exp_value = int(exp)
    current = int(now if now is not None else time.time())
    if exp_value < current or exp_value - current > _ttl_seconds() + _bucket_seconds():
        return False
    return hmac.compare_digest(_signature(key, exp_value), sig)


def key_upload_type(key: str) -> str | None:
    match = KEY_PATTERN.fullmatch(key)
    return match.group("upload_type") if match else None


def resolve_attachment(
    value: str | None,
    *,
    user_id: int,
    expected_upload_type: str,
    current_stored: str | None = None,
) -> str | None:
    """Validate a client-supplied file reference and return the value to store.

    * empty -> None
    * the same file already stored on this record -> kept as is (edit forms send
      back what they were given, including legacy or expired signed URLs)
    * otherwise the key must be bound to ``user_id``, uploaded with the upload
      type of the attach target (a ``selfie`` upload is not a ``passport``) and
      exist on disk, so a user can never attach somebody else's upload.
    """
    if value is None or not value.strip():
        return None
    if current_stored is not None and value == current_stored:
        return current_stored
    key = normalize_storage_key(value)
    if key is None:
        raise FileReferenceError("Invalid file reference")
    if current_stored is not None and normalize_storage_key(current_stored) == key:
        return current_stored
    if key_owner_id(key) != user_id or key_upload_type(key) != expected_upload_type:
        raise FileReferenceError("Invalid file reference")
    path = resolve_upload_path(key)
    if path is None or not path.is_file():
        raise FileReferenceError("Invalid file reference")
    return stored_value_for_key(key)
