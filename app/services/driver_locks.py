"""Row-lock helpers and the lock order for v1 (legacy) order/driver/account paths.

Lock order (spec §15, ADR-0017 §12-13). Every v1 path takes a subset, in this
order, ids ascending, and takes each row in its *final* mode up front:

    orders -> bids -> users -> driver_profiles
           -> refresh_sessions / notifications / otp_codes / driver_documents / driver_routes
           -> (v2, via A3 wallet service) wallet_accounts

Lock modes:
- FOR NO KEY UPDATE (``key_share=True``) on users/driver_profiles when the
  transaction changes only non-key columns (status, availability, full_name).
  PostgreSQL takes FOR KEY SHARE on the referenced row for every INSERT of a row
  with a foreign key to it (notifications.user_id, audit_logs.actor_id,
  refresh_sessions.user_id, bids.driver_id, driver_documents.driver_id, ...).
  FOR KEY SHARE conflicts with FOR UPDATE but not with FOR NO KEY UPDATE, so a
  plain FOR UPDATE would block unrelated inserts and create deadlocks.
- FOR UPDATE, taken up front, when the transaction will change a column with a
  unique index (users.phone/username, driver_profiles.plate_number): such an
  UPDATE needs FOR UPDATE anyway, and upgrading NO KEY UPDATE -> FOR UPDATE in the
  middle of a transaction waits for key-share holders that may in turn wait for
  rows this transaction already holds (N-A). Users of this mode: account deletion
  (users + profile), admin vehicle edit that changes the plate (profile), driver
  self-service profile edit that changes the plate (profile).
- FOR KEY SHARE on users for self-service writes that insert rows referencing
  the user but do not change it (document upload, route edits, availability,
  OTP request), and FOR SHARE for token refresh (see below). Both are taken
  *before* touching any other row, so a concurrent account deletion (users FOR
  UPDATE) makes them wait while they hold nothing, and they never wait for a row
  deletion holds.

Who takes what:
- client cancel / publish / update, driver create_bid / update_bid / reject,
  select-driver, admin assign/cancel/status: orders first; bids by id; create_bid,
  update_bid, select-driver and admin assign then lock the driver's users row and
  driver_profiles row (NO KEY UPDATE) and re-check eligibility inside the locks.
- admin_driver_service (block/approve/reject/vehicle): users (NO KEY UPDATE) ->
  driver_profiles (NO KEY UPDATE, or FOR UPDATE for a plate change) -> routes /
  refresh_sessions / documents. Never orders or bids.
- admin client block/unblock (api/v1/admin_clients.py): users NO KEY UPDATE, then
  404 CLIENT_NOT_FOUND for a deleted client. Admin driver mutations return 404
  for a deleted driver after their users/profile locks.
- driver self-service (driver_service): users (KEY SHARE, or NO KEY UPDATE when
  full_name changes) -> driver_profiles (NO KEY UPDATE, or FOR UPDATE for a plate
  change) -> documents / routes, then the account must still be active.
- account deletion: the account's orders (as client or assigned driver) -> users
  FOR UPDATE -> driver_profiles FOR UPDATE -> wallet_accounts (A3, lock=True) ->
  sessions / notifications / otp / documents / routes. Orders come first because
  deletion rewrites order rows: users -> orders would reverse orders -> users and
  deadlock with admin cancel / rating, which hold an order and insert rows
  referencing the user.
- OTP request/verify: users by phone (KEY SHARE / NO KEY UPDATE) before any
  otp_codes write (deletion deletes otp_codes after locking the user).
- token refresh: users FOR SHARE -> refresh_sessions FOR UPDATE. FOR SHARE
  conflicts with block_driver's NO KEY UPDATE, so a refresh and a block serialize:
  a refresh that commits first has its new session revoked by the block, and a
  refresh that runs after the block sees the blocked status (N-B). Logout keeps
  KEY SHARE (it only revokes).

v2: v2 commands never lock v1 orders/bids/driver_profiles (Q4), so v1 "orders
before users" cannot form a cycle with v2 "users first". A3 approve_topup locks
wallet_accounts -> topup_requests and only *reads* the driver's users row (no
lock, no insert or FK change referencing it), so it never waits for deletion's
users/profile locks; deletion waits for approve_topup at wallet_accounts while
holding nothing approve_topup needs (N-C).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models import Bid, DriverProfile, Order, User

LockMode = Literal["update", "no_key_update", "share", "key_share"]


def with_lock(stmt: Select, mode: LockMode) -> Select:
    """Apply a PostgreSQL row-lock mode (ignored by SQLite)."""
    if mode == "update":
        return stmt.with_for_update()
    if mode == "no_key_update":
        return stmt.with_for_update(key_share=True)
    if mode == "share":
        return stmt.with_for_update(read=True)
    if mode == "key_share":
        return stmt.with_for_update(read=True, key_share=True)
    raise ValueError(f"unknown lock mode {mode!r}")


def lock_order_row(db: Session, order_id: int) -> Order | None:
    """SELECT ... FOR UPDATE on an order, refreshing any stale identity-map copy."""
    return db.scalar(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    )


def lock_order_bids(db: Session, order_id: int, *, active_only: bool = False) -> list[Bid]:
    """Lock an order's bids in id order. Caller must already hold the order lock."""
    stmt = select(Bid).where(Bid.order_id == order_id)
    if active_only:
        stmt = stmt.where(Bid.status == "active")
    return list(db.scalars(stmt.order_by(Bid.id).with_for_update().execution_options(populate_existing=True)))


def lock_bid_row(db: Session, bid_id: int) -> Bid | None:
    """Lock one bid. Caller must already hold its order's lock."""
    return db.scalar(select(Bid).where(Bid.id == bid_id).with_for_update().execution_options(populate_existing=True))


def lock_user_row(db: Session, user_id: int, mode: LockMode = "no_key_update") -> User | None:
    """Lock a users row (default FOR NO KEY UPDATE, see module docstring)."""
    return db.scalar(with_lock(select(User).where(User.id == user_id), mode).execution_options(populate_existing=True))


def lock_user_key_share(db: Session, user_id: int) -> User | None:
    return lock_user_row(db, user_id, "key_share")


def lock_user_share(db: Session, user_id: int) -> User | None:
    """FOR SHARE: serializes with block_driver (NO KEY UPDATE) and deletion (FOR UPDATE)."""
    return lock_user_row(db, user_id, "share")


def lock_user_for_key_change(db: Session, user_id: int) -> User | None:
    """FOR UPDATE up front for a transaction that will change users.phone/username."""
    return lock_user_row(db, user_id, "update")


def lock_user_by_phone(db: Session, phone: str, mode: LockMode) -> User | None:
    return db.scalar(with_lock(select(User).where(User.phone == phone), mode).execution_options(populate_existing=True))


def lock_driver_user_and_profile(
    db: Session,
    profile_id: int,
    *,
    user_mode: LockMode = "no_key_update",
    profile_mode: LockMode = "no_key_update",
) -> tuple[DriverProfile | None, User | None]:
    """Lock the driver's users row, then the driver_profiles row.

    Both rows are re-read (populate_existing) so callers check committed state.
    driver_profiles.user_id is immutable, so the unlocked read used to find it
    cannot go stale. Pass profile_mode="update" when the plate will change.
    """
    profile = db.get(DriverProfile, profile_id)
    if profile is None:
        return None, None
    user = lock_user_row(db, profile.user_id, user_mode)
    profile = db.scalar(
        with_lock(select(DriverProfile).where(DriverProfile.id == profile_id), profile_mode).execution_options(
            populate_existing=True
        )
    )
    return profile, user


def lock_orders_for_account(db: Session, user: User) -> list[int]:
    """Lock every order of the account (as client or as assigned driver), id order.

    Used by account deletion before its users lock (orders -> users).
    """
    party = [Order.client_id == user.id]
    profile_id = db.scalar(select(DriverProfile.id).where(DriverProfile.user_id == user.id))
    if profile_id is not None:
        party.append(Order.assigned_driver_id == profile_id)
    return list(db.scalars(select(Order.id).where(or_(*party)).order_by(Order.id).with_for_update()))
