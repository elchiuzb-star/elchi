"""Protected phone identifier for acquisition-reward uniqueness (Q108, ADR-0023 §9).

* The HMAC key is derived from ``settings.secret_key`` with ``crypto.derive_subkey`` for one purpose and version; it
  lives only in process memory - never in the DB, a log line or an error detail.
* Rotation: a lookup computes the digest under every retained key version. A match under an old version adds the
  current-version digest to the **same** identity, so a rotation never forgets who already earned a reward.
* Retention: ``IdentityRetentionPolicy.after_deletion is None`` (Q108 not approved) purges an identity's digests when
  its account is deleted - no new durable anti-fraud data from deleted accounts. An approved period keeps them until
  ``retain_until``; ``purge_expired_identity_digests`` removes them afterwards.
* A digest match is never proof of one person (numbers are recycled): it only sends the *new-user reward* to review.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.crypto import derive_subkey
from app.contracts.promo import (
    PROMO_IDENTITY_KEY_VERSION,
    PROMO_IDENTITY_PURPOSE,
    IdentityRetentionPolicy,
    identity_digest,
    normalize_phone,
)
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions.models import PromoIdentity, PromoIdentityDigest

# Q108: no retention period is approved. Changing this needs the recorded legal basis (go-live checklist).
APPROVED_RETENTION = IdentityRetentionPolicy(after_deletion=None)


@dataclass(frozen=True)
class IdentityKeys:
    """Current key version plus retained older versions (for lookups only). Keys stay in memory."""

    current_version: int
    keys: Mapping[int, bytes]

    def __post_init__(self) -> None:
        if self.current_version not in self.keys:
            raise ValueError("the current key version must have a key")

    def __repr__(self) -> str:  # never print key material
        return f"IdentityKeys(current_version={self.current_version}, versions={sorted(self.keys)})"


def keys_from_secret(secret: str | bytes | None, *, current_version: int = PROMO_IDENTITY_KEY_VERSION,
                     retained_versions: tuple[int, ...] = ()) -> IdentityKeys | None:
    """Derive the identity keys; ``None`` when no usable secret is configured (then nobody enrolls - no fallback)."""
    if not secret or len(secret) < 32:
        return None
    versions = (current_version, *[v for v in retained_versions if v != current_version])
    return IdentityKeys(current_version, {v: derive_subkey(secret, PROMO_IDENTITY_PURPOSE, v) for v in versions})


def configured_keys() -> IdentityKeys | None:
    from app.core.config import settings

    return keys_from_secret(getattr(settings, "secret_key", None))


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    identity: PromoIdentity
    matched_previous_account: bool  # the digest belonged to an earlier (deleted) account -> review, never a block


def resolve_identity(session: Session, *, user_id: int, phone: str, window_started_at: datetime,
                     keys: IdentityKeys) -> ResolvedIdentity | None:
    """Find or create the identity of ``user_id``'s phone. ``None`` when the phone is not a real number."""
    normalized = normalize_phone(phone)
    if normalized is None:
        return None
    window_started_at = ensure_aware_utc(window_started_at, field="window_started_at")
    digests = {version: identity_digest(key, normalized) for version, key in keys.keys.items()}
    for attempt in range(2):
        rows = session.execute(
            select(PromoIdentityDigest).where(
                tuple_(PromoIdentityDigest.key_version, PromoIdentityDigest.digest).in_(list(digests.items()))
            )
        ).scalars().all()
        own = session.execute(select(PromoIdentity).where(PromoIdentity.current_user_id == user_id)).scalar_one_or_none()
        identity_ids = {row.identity_id for row in rows}
        savepoint = session.begin_nested()
        try:
            if not identity_ids:
                # first time this phone is seen (or its digests were purged under Q108)
                identity = own or PromoIdentity(current_user_id=user_id, first_window_started_at=window_started_at)
                session.add(identity)
                matched_previous = False
            else:
                identity = session.get(PromoIdentity, min(identity_ids))
                if identity.current_user_id == user_id:
                    matched_previous = False
                else:
                    # an earlier account (deleted, digests retained) or - should never happen - another live one
                    matched_previous = True
                    if identity.current_user_id is None and own is None:
                        # the same identity continues: its original window start is kept (Q106: no renewal)
                        identity.current_user_id = user_id
                        identity.updated_at = utc_now()
            session.flush()
            owns_identity = identity.current_user_id == user_id
            if owns_identity and not any(
                row.identity_id == identity.id and row.key_version == keys.current_version for row in rows
            ):
                session.add(PromoIdentityDigest(identity_id=identity.id, key_version=keys.current_version,
                                                digest=digests[keys.current_version]))
                session.flush()
        except IntegrityError:
            savepoint.rollback()
            if attempt == 0:
                continue  # a concurrent request created it; read again
            raise
        savepoint.commit()
        return ResolvedIdentity(identity, matched_previous)
    raise AssertionError("unreachable")  # pragma: no cover


def on_account_deleted(session: Session, *, user_id: int, policy: IdentityRetentionPolicy = APPROVED_RETENTION,
                       now: datetime | None = None) -> None:
    """Called by the account-deletion flow. Detaches the identity; purges its digests unless retention is approved."""
    from app.modules.platform.service import table_exists

    if not table_exists(session, "promo_identities"):
        return
    now = utc_now() if now is None else ensure_aware_utc(now, field="now")
    identity = session.execute(
        select(PromoIdentity).where(PromoIdentity.current_user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if identity is None:
        return
    identity.current_user_id = None
    identity.updated_at = now
    if policy.after_deletion is None:
        session.execute(delete(PromoIdentityDigest).where(PromoIdentityDigest.identity_id == identity.id))
        identity.retain_until = None
    else:
        identity.retain_until = now + policy.after_deletion
    session.flush()


def purge_expired_identity_digests(session: Session, *, now: datetime | None = None) -> int:
    """Remove digests of deleted accounts whose approved retention has ended. Returns how many were removed."""
    now = utc_now() if now is None else ensure_aware_utc(now, field="now")
    expired = select(PromoIdentity.id).where(PromoIdentity.current_user_id.is_(None), PromoIdentity.retain_until <= now)
    result = session.execute(delete(PromoIdentityDigest).where(PromoIdentityDigest.identity_id.in_(expired)))
    return int(result.rowcount or 0)
