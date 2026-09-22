"""Self-service account deletion.

Required by both stores: Google Play requires in-app deletion plus a public web
request route, and Apple requires deletion initiated inside the app.

The approach is anonymise-and-retain rather than hard delete. Orders are shared
business records — a driver's completed job is also the client's history, and
both carry financial obligations — so the rows stay while the identity attached
to them is stripped. What can only belong to the departing user (documents,
sessions, notifications, offered routes) is removed outright.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, event, func, or_, select

from sqlalchemy.orm import Session, object_session

from app.utils.file_access import normalize_storage_key, resolve_upload_path
from app.models import (
    Dispute,
    DriverDocument,
    DriverProfile,
    DriverRoute,
    Notification,
    Order,
    OtpCode,
    RefreshSession,
    User,
)
from app.services.audit_service import write_audit_log
from app.services.dispute_service import ACTIVE_DISPUTE_STATUSES
from app.services.driver_locks import lock_orders_for_account, lock_user_for_key_change
from app.utils.api_response import error_response

logger = logging.getLogger("elchi.account")

# An order in any of these states is still in flight. Someone mid-delivery
# cannot disappear — the counterparty is relying on them.
IN_FLIGHT_ORDER_STATUSES = {
    "published",
    "bidding",
    "accepted",
    "picked_up",
    "in_transit",
    "delivered",
}


def _tombstone_phone(user_id: int) -> str:
    """Frees the real number for re-registration while keeping the column
    unique and obviously non-personal."""
    return f"deleted-{user_id}"


def _remove_upload(file_url: str) -> None:
    """Delete a stored upload. Best-effort: a missing file must not abort the
    deletion, since the user's request matters more than tidy storage."""
    # Uploads live in nested key paths (type/YYYY/MM[/uID]/name.ext). The key is
    # validated and confined to the upload root before anything is unlinked.
    key = normalize_storage_key(file_url)
    path = resolve_upload_path(key)
    if path is None:
        return
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:  # pragma: no cover - filesystem edge cases
        logger.warning("Could not remove upload %s: %s", key, exc)


_PENDING_REMOVALS_KEY = "elchi_pending_upload_removals"


def _on_after_commit(session: Session) -> None:
    # after_commit also fires when a SAVEPOINT is released; files go only when the root transaction commits.
    if session.in_nested_transaction():
        return
    pending = session.info.pop(_PENDING_REMOVALS_KEY, [])
    for file_urls, _chain in pending:
        for file_url in file_urls:
            try:
                _remove_upload(file_url)
            except Exception:  # noqa: BLE001 - the DB commit already happened; never fail it afterwards
                logger.exception("Could not remove upload after account deletion")


def _on_after_soft_rollback(session: Session, previous_transaction) -> None:  # noqa: ANN001
    # A rollback of the transaction (root or savepoint) that contained the deletion cancels its file removals.
    pending = session.info.get(_PENDING_REMOVALS_KEY)
    if pending:
        session.info[_PENDING_REMOVALS_KEY] = [
            entry for entry in pending if not any(tx is previous_transaction for tx in entry[1])
        ]


def schedule_upload_removal_after_commit(db: Session, user: User, file_urls: list[str]) -> None:
    """L6: remove uploads only after the enclosing root transaction really commits.

    Registered on the real ``Session`` (``object_session(user)``), so it works both for the v1 route (its own
    ``db.commit()``) and for the v2 idempotent runner, which commits after ``delete_own_account`` returns through
    ``_DeferredCommitSession``. A rollback of the root or of any savepoint enclosing the deletion drops them.
    """
    if not file_urls:
        return
    session = object_session(user) or db
    if not session.info.get("elchi_upload_removal_listeners"):
        event.listen(session, "after_commit", _on_after_commit)
        event.listen(session, "after_soft_rollback", _on_after_soft_rollback)
        session.info["elchi_upload_removal_listeners"] = True
    chain = []
    tx = session.get_nested_transaction() or session.get_transaction()
    while tx is not None:
        chain.append(tx)
        tx = tx.parent
    session.info.setdefault(_PENDING_REMOVALS_KEY, []).append((list(file_urls), tuple(chain)))


def blocking_orders(db: Session, user: User) -> int:
    """Count the user's still-active orders, as client or as assigned driver."""
    stmt = select(Order).where(Order.status.in_(IN_FLIGHT_ORDER_STATUSES))
    if user.role == "driver":
        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
        if profile is None:
            return 0
        stmt = stmt.where(Order.assigned_driver_id == profile.id)
    else:
        stmt = stmt.where(Order.client_id == user.id)
    return len(db.scalars(stmt).all())


def blocking_disputes(db: Session, user: User) -> int:
    """Count disputed orders and open/under-review disputes the user is party to.

    A dispute needs both parties reachable until staff close it, so the account
    cannot be anonymised while one is unresolved — as client or as driver.
    """
    if user.role == "driver":
        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
        party_filter = Order.assigned_driver_id == profile.id if profile is not None else None
    else:
        party_filter = Order.client_id == user.id

    disputed_orders = 0
    if party_filter is not None:
        disputed_orders = db.scalar(
            select(func.count(Order.id)).where(Order.status == "disputed", party_filter)
        ) or 0

    dispute_party = Dispute.opened_by_user_id == user.id
    if party_filter is not None:
        dispute_party = or_(dispute_party, party_filter)
    open_disputes = db.scalar(
        select(func.count(Dispute.id))
        .join(Order, Order.id == Dispute.order_id)
        .where(Dispute.status.in_(ACTIVE_DISPUTE_STATUSES), dispute_party)
    ) or 0
    return disputed_orders + open_disputes


def delete_own_account(db: Session, user: User) -> dict[str, Any] | JSONResponse:
    """Anonymise the account and purge everything that is exclusively theirs."""
    if user.role in {"operator", "admin", "super_admin"}:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "STAFF_DELETE_FORBIDDEN",
            "Xodim hisobini o'chirish uchun administratorga murojaat qiling",
        )

    # Locks (app/services/driver_locks.py), taken up front, before the checks, in order:
    #   1. the account's orders (as client or assigned driver), FOR UPDATE, id order.
    #      Deletion rewrites client order rows and orders precede users globally, so
    #      admin cancel / rating (hold an order, then insert rows referencing this
    #      user) wait here instead of deadlocking.
    #   2. users FOR UPDATE, 3. driver_profiles FOR UPDATE: this transaction changes
    #      unique columns (users.phone/username, driver_profiles.plate_number), so the
    #      rows are taken in their final mode; no lock upgrade at flush (N-A).
    #   4. (A4, not wired yet) v2 bookings — see the insertion point below.
    #   5. wallet_accounts FOR UPDATE via the wallet service (A3).
    # Everything else that writes this account locks users before any other row:
    # select-driver/create_bid/block_driver (NO KEY UPDATE), admin client block
    # (NO KEY UPDATE), driver self-service (KEY SHARE), token refresh (FOR SHARE).
    # They either commit first (and are counted below) or wait here holding nothing
    # and then see the deleted status (404 / 403 / USER_INACTIVE).
    lock_orders_for_account(db, user)
    lock_user_for_key_change(db, user.id)
    profile = db.scalar(
        select(DriverProfile)
        .where(DriverProfile.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    active = blocking_orders(db, user)
    if active:
        return error_response(
            status.HTTP_409_CONFLICT,
            "ACTIVE_ORDERS_EXIST",
            "Tugallanmagan buyurtmalaringiz bor. Ular yakunlangach hisobni o'chirish mumkin",
        )
    if blocking_disputes(db, user):
        return error_response(
            status.HTTP_409_CONFLICT,
            "ACTIVE_DISPUTES_EXIST",
            "Hal qilinmagan nizolaringiz bor. Ular yopilgach hisobni o'chirish mumkin",
        )
    # v2 bookings (A4, N4 / ADR-0006 D5): open obligations as client or driver. Called
    # after the users/profile locks and the v1 order/dispute checks above, before the
    # wallet lock below; lock=True takes FOR SHARE on those bookings. Accept starts by
    # locking users, so it cannot slip a booking in between this check and the commit.
    # Lock order: orders -> users -> driver_profiles -> bookings -> wallet_accounts.
    # Returns an empty state when the bookings table is absent (legacy SQLite suite).
    from app.modules.bookings import service as bookings_service

    bookings_state = bookings_service.blocking_state_for_user(db, user.id, lock=True)
    if bookings_state.blocks_deletion:
        return error_response(
            status.HTTP_409_CONFLICT,
            "ACTIVE_BOOKINGS_EXIST",
            "Tugallanmagan safar yoki jo'natma bronlaringiz bor. Ular yakunlangach hisobni o'chirish mumkin",
            bookings_state.as_details(),
        )

    # A12 (wave 3, §17.8): open v2 disputes on the account's bookings and open SOS tickets block deletion too.
    # Lock order: ... -> bookings -> disputes_v2 / support_tickets (FOR SHARE) -> wallet_accounts. Same v1 error
    # code and message as the v1 dispute check; ``details`` is additive. Zeros when the tables are absent.
    from app.modules.trust_support import service as trust_service

    trust_state = trust_service.blocking_state_for_user(db, user.id, lock=True)
    if trust_state.blocks_deletion:
        return error_response(
            status.HTTP_409_CONFLICT,
            "ACTIVE_DISPUTES_EXIST",
            "Hal qilinmagan nizolaringiz bor. Ular yopilgach hisobni o'chirish mumkin",
            trust_state.as_details(),
        )

    from app.modules.wallet.service import blocking_state_for_user

    # BR N4 (ADR-0006 D5) / A3 wave 1.5 BR #10: v2 wallet facts via the wallet service,
    # which locks this user's wallet_accounts rows FOR UPDATE (id order) so a concurrent
    # top-up approval, hold or adjustment serializes with the deletion. It writes
    # nothing and returns zeros when the wallet tables are absent.
    wallet_state = blocking_state_for_user(db, user.id, lock=True)
    if wallet_state.blocks_deletion:
        return error_response(
            status.HTTP_409_CONFLICT,
            "WALLET_BALANCE_EXISTS",
            "Komissiya balansingiz, faol hold yoki kutilayotgan to'ldirish so'rovi bor. Ular yopilgach hisobni o'chirish mumkin",
            wallet_state.as_details(),
        )

    # Files are removed only after the commit: a rollback must not leave
    # document rows pointing at files that are already gone.
    files_to_remove: list[str] = []
    old_phone = user.phone
    old_role = user.role
    try:
        # Key-column changes first (users.phone/username, driver_profiles.plate_number).
        # The rows are already locked FOR UPDATE above, so this flush needs no lock
        # upgrade (driver_locks.py).
        user.phone = _tombstone_phone(user.id)
        user.username = None
        user.password_hash = None
        user.full_name = None
        user.is_phone_verified = False
        user.status = "deleted"
        db.add(user)
        if profile is not None:
            profile.is_available = False
            profile.car_model = None
            profile.car_color = None
            # plate_number is unique and plate_number_normalized is its indexed
            # derivative — clear both so the plate can be registered again.
            profile.plate_number = None
            profile.plate_number_normalized = None
            db.add(profile)
        db.flush()

        # Then revoke access and purge what is exclusively theirs.
        db.execute(delete(RefreshSession).where(RefreshSession.user_id == user.id))
        db.execute(delete(Notification).where(Notification.user_id == user.id))
        db.execute(delete(OtpCode).where(OtpCode.phone == old_phone))

        if profile is not None:
            documents = db.scalars(
                select(DriverDocument).where(DriverDocument.driver_id == profile.id)
            ).all()
            files_to_remove.extend(document.file_url for document in documents)
            db.execute(delete(DriverDocument).where(DriverDocument.driver_id == profile.id))
            # Stop matching this driver to new orders.
            db.execute(delete(DriverRoute).where(DriverRoute.driver_id == profile.id))

        # The client's own contact details on past orders are theirs to erase;
        # the order rows themselves are retained as business records (already
        # locked above).
        if old_role == "client":
            for order in db.scalars(select(Order).where(Order.client_id == user.id)).all():
                order.sender_phone = ""
                order.receiver_phone = ""
                order.comment = None
                db.add(order)

        write_audit_log(
            db,
            user,
            "users",
            user.id,
            "account_deleted",
            old_value={"phone": old_phone, "role": old_role},
            new_value={"status": "deleted"},
        )

        # L6: files go only after the root transaction commits (v1: the commit below; v2 DELETE /me: the idempotent
        # runner's commit, since _DeferredCommitSession.commit only flushes). A rollback keeps them.
        schedule_upload_removal_after_commit(db, user, files_to_remove)
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info("Account deleted: user_id=%s role=%s", user.id, user.role)
    return {
        "deleted": True,
        "message": "Hisobingiz o'chirildi. Telefon raqamingiz qayta ro'yxatdan o'tish uchun bo'sh",
    }
