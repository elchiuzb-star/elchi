"""Store-review account isolation for the v1 API.

App-store reviewers sign in with the phones listed in ELCHI_REVIEW_LOGIN_PHONES.
Those accounts must never reach real users or real money:

- a review client's published order is matched and shown only to review drivers;
- a review driver only sees, bids on and can be assigned to review clients' orders;
- no SMS is ever sent to a review phone.

Identification is by the configured phone allowlist only (no schema change).
Limitation: removing a phone from the allowlist turns that account back into a
normal user, and its existing orders/bids become visible to real counterparties.
Isolation depends only on the phone list, not on ELCHI_REVIEW_LOGIN_OTP, so
clearing the fixed code alone does not un-isolate the accounts.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.models import Bid, Dispute, DriverProfile, Order, User

CLOSED_ORDER_STATUSES = frozenset({"cancelled", "confirmed"})
OPEN_DISPUTE_STATUSES = ("open", "under_review")


def review_account_phones() -> frozenset[str]:
    """Normalized phones on the review allowlist (empty when unset).

    Parsed once per distinct setting value (cached); changing the setting,
    e.g. in tests or after a reload, yields a fresh parse.
    """
    return _parse_review_phones(settings.review_login_phones or "")


@lru_cache(maxsize=8)
def _parse_review_phones(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    # Imported lazily: auth_service imports sms_service, which imports this module.
    from app.services.auth_service import normalize_phone

    phones: set[str] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        normalized = normalize_phone(item)
        if isinstance(normalized, str):
            phones.add(normalized)
    return frozenset(phones)


def is_review_account_phone(phone: str | None) -> bool:
    if not phone:
        return False
    return phone in review_account_phones()


def is_review_user_id(db: Session, user_id: int | None) -> bool:
    if user_id is None or not review_account_phones():
        return False
    user = db.get(User, user_id)
    return user is not None and is_review_account_phone(user.phone)


def is_review_driver_profile(db: Session, profile: DriverProfile | None) -> bool:
    if profile is None:
        return False
    return is_review_user_id(db, profile.user_id)


def is_review_order(db: Session, order: Order) -> bool:
    """An order is review traffic if its client or its assigned driver is a review account."""
    if not review_account_phones():
        return False
    if is_review_user_id(db, order.client_id):
        return True
    if order.assigned_driver_id is None:
        return False
    return is_review_driver_profile(db, db.get(DriverProfile, order.assigned_driver_id))


def review_order_ids(db: Session, orders: list[Order]) -> set[int]:
    """Batched is_review_order for a page of orders: two queries, not two per row."""
    phones = review_account_phones()
    if not phones or not orders:
        return set()
    client_ids = {order.client_id for order in orders}
    driver_ids = {order.assigned_driver_id for order in orders if order.assigned_driver_id is not None}
    review_users = set(db.scalars(select(User.id).where(User.id.in_(client_ids), User.phone.in_(sorted(phones)))))
    review_profiles: set[int] = set()
    if driver_ids:
        review_profiles = set(
            db.scalars(
                select(DriverProfile.id)
                .join(User, User.id == DriverProfile.user_id)
                .where(DriverProfile.id.in_(driver_ids), User.phone.in_(sorted(phones)))
            )
        )
    return {
        order.id
        for order in orders
        if order.client_id in review_users or order.assigned_driver_id in review_profiles
    }


def review_account_open_items(db: Session, phone: str) -> dict[str, Any]:
    """Decision 39: what must be closed before a phone leaves the review allowlist.

    Removing a phone from ELCHI_REVIEW_LOGIN_PHONES turns the account into a
    normal user; any order, bid or dispute still open would then become visible
    to real counterparties. Read-only.
    """
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        return {"phone": phone, "user_id": None, "open_orders": [], "active_bids": [], "open_disputes": []}
    profile_id = db.scalar(select(DriverProfile.id).where(DriverProfile.user_id == user.id))
    party = [Order.client_id == user.id]
    if profile_id is not None:
        party.append(Order.assigned_driver_id == profile_id)
    orders = list(
        db.scalars(select(Order).where(or_(*party), Order.status.not_in(sorted(CLOSED_ORDER_STATUSES))).order_by(Order.id))
    )
    bids: list[Bid] = []
    if profile_id is not None:
        bids = list(db.scalars(select(Bid).where(Bid.driver_id == profile_id, Bid.status == "active").order_by(Bid.id)))
    disputes = list(
        db.scalars(
            select(Dispute)
            .join(Order, Order.id == Dispute.order_id)
            .where(Dispute.status.in_(OPEN_DISPUTE_STATUSES), or_(Dispute.opened_by_user_id == user.id, *party))
            .order_by(Dispute.id)
        )
    )
    return {
        "phone": phone,
        "user_id": user.id,
        "open_orders": [{"id": o.id, "order_number": o.order_number, "status": o.status} for o in orders],
        "active_bids": [{"id": b.id, "order_id": b.order_id} for b in bids],
        "open_disputes": [{"id": d.id, "order_id": d.order_id, "status": d.status} for d in disputes],
    }


def review_pairing_allowed(db: Session, client_user_id: int | None, driver_user_id: int | None) -> bool:
    """A client and a driver may interact only if both or neither are review accounts."""
    if not review_account_phones():
        return True
    return is_review_user_id(db, client_user_id) == is_review_user_id(db, driver_user_id)


def client_id_matches_review_side(client_id_column: ColumnElement, review: bool) -> ColumnElement | None:
    """SQL filter keeping only orders whose client is on the same side as `review`.

    Returns None when no filter is needed (allowlist empty).
    """
    phones = review_account_phones()
    if not phones:
        return None
    review_client_ids = select(User.id).where(User.phone.in_(sorted(phones)))
    if review:
        return client_id_column.in_(review_client_ids)
    return client_id_column.not_in(review_client_ids)


def user_phone_matches_review_side(phone_column: ColumnElement, review: bool) -> ColumnElement | None:
    """SQL filter on a users.phone column; None when the allowlist is empty."""
    phones = review_account_phones()
    if not phones:
        return None
    if review:
        return phone_column.in_(sorted(phones))
    return phone_column.not_in(sorted(phones))
