"""Wallet domain API (A3): prepaid commission balance, holds, ledger, top-ups, policies.

Every function takes the caller's ``Session`` and never commits (spec §15: one
transaction per command, orchestrated by A4 for accept/cancel/amend).

Money rules enforced here *and* in PostgreSQL (migrations 0036/0041):
* available = posted - held; CHECK forbids negative available unless a non-production
  seed wallet has ``test_overdraft_allowed`` (trigger forbids it on a production marker).
* One hold per (booking, charge_kind); amendments adjust it (D10).
* Capture posts Dr driver liability / Cr commission revenue and resolves the hold in the
  same transaction; a repeated capture is a no-op (AC20).
* Reversals: several partial ones, sum <= captured, checked under the wallet lock (D4).
* Ledger rows are immutable; each transaction is balanced (deferred constraint trigger);
  the wallet balance cache must equal the ledger at commit (deferred trigger).
* A top-up screenshot is not money: only an approval with a unique source reference posts.
* Legacy ``orders.system_fee`` never enters the ledger (§18.2): nothing here reads it.

Lock order (ADR-0017): callers lock users/trips/listings/threads/bookings first; this
module then locks ``wallet_accounts`` and only after that ``wallet_holds`` /
``topup_requests`` / ``ledger_adjustment_requests`` (id ASC within a group). Users rows are
never locked here (other modules lock them ``FOR NO KEY UPDATE``).

Authorization: staff commands take ``actor_capabilities`` (server-computed, A1) and check
capabilities, never role names. ``capture_fee``/``release_fee``/``hold_fee``/``adjust_hold`` are
capability-free building blocks for A4's orchestrator; A4 enforces ``finance.fee_finalize`` on the
operator ``finalize_fee`` command before calling them (Q17).

Staging (BR #13): outside production ``wallet_required=false`` skips only the balance check; the
fee is still held, so the wallet needs ``test_overdraft_allowed`` (see docs/ops/FINANCE_REFUNDS.md §2).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from itertools import groupby

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import (
    Capability,
    ChargeKind,
    CommissionPolicyKind,
    CommissionStatus,
    Currency,
    EventType,
    FeatureFlagKey,
    Role,
    ServiceType,
    TopupStatus,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.money import (
    TWO_PERSON_APPROVAL_THRESHOLD_MINOR,
    balance_check_required,
    commission_minor,
    hold_adjustment_minor,
    net_after_commission_minor,
    validate_fee_bps,
    validate_minor_amount,
    validate_policy_terms,
    validate_reversal,
)
from app.contracts.state_machines import COMMISSION, TOPUP
from app.contracts.timeutil import ensure_aware_utc, to_iso_utc, utc_now
from app.modules.platform.service import (
    DeploymentEnvironment,
    app_environment,
    constraint_name_of,
    enqueue_event,
    get_db_marker_state,
    is_production,
    q48_gate_status,
    sqlstate_of,
    table_exists,
)
from app.modules.wallet.models import (
    CommissionPolicy,
    LedgerAccount,
    LedgerAccountBalance,
    LedgerAdjustmentRequest,
    LedgerEntry,
    LedgerTransaction,
    ReconciliationRun,
    TopupRequest,
    WalletAccount,
    WalletHold,
)
from app.modules.wallet.policy import PolicyCandidate, select_policy

# --- configuration (pilot defaults; see report: move to policy/settings via A0a) -----------------
# Top-ups, manual adjustments and reversals strictly above this amount need a second, different
# staff member (Q17). Single source: app.contracts.money (BR #11); the old name stays as an alias.
LARGE_AMOUNT_THRESHOLD_MINOR = TWO_PERSON_APPROVAL_THRESHOLD_MINOR
# Decision 30: sub-threshold adjustments by one requester on one wallet inside this window are signalled.
SPLIT_SIGNAL_WINDOW = timedelta(hours=24)
SPLIT_SIGNAL_MIN_COUNT = 3
# Allowed clock skew for "effective_from >= now" (the DB trigger backstop allows 5 minutes).
POLICY_CLOCK_TOLERANCE = timedelta(seconds=60)
# Holds are escalated to an operator after 48 h; never auto-captured or auto-released (§9.5).
HOLD_ESCALATE_AFTER = timedelta(hours=48)

ACCOUNT_CASH_BANK = "cash_bank"
ACCOUNT_CASH_DESK = "cash_desk"
ACCOUNT_COMMISSION_REVENUE = "commission_revenue"
ACCOUNT_MANUAL_ADJUSTMENTS = "manual_adjustments"
SOURCE_TYPE_ACCOUNT = {"bank_statement": ACCOUNT_CASH_BANK, "cashier_receipt": ACCOUNT_CASH_DESK}
TOPUP_METHODS = frozenset({"bank_transfer", "cash_desk"})

HOLD_ACTIVE = "active"
HOLD_CAPTURED = "captured"
HOLD_RELEASED = "released"
ADJ_PENDING = "pending_second_approval"
ADJ_POSTED = "posted"
ADJ_REJECTED = "rejected"
ADJ_WITHDRAWN = "withdrawn"
DEBIT = "debit"
# Wave 1.6 N5: checks that only block *new* business (quotes/holds). Obligations on existing money
# (capture, release, reversal, adjustment processing, top-ups) keep working; readiness still reports them.
NEW_BUSINESS_ONLY_CHECKS = frozenset({"global_standard_active_now", "q48_money_gate"})
# Q55: allowed business sources of a ledger posting (DB-validated at COMMIT, migration 0052).
LEDGER_SOURCE_TYPES = frozenset({"topup_request", "ledger_adjustment_request", "wallet_hold"})
CREDIT = "credit"
# Q69 (wave 2.1): only an active user whose effective roles (legacy users.role + active user_roles, as in
# identity.capabilities.effective_roles) include one of these approves top-ups and approves/rejects/posts
# adjustments. Same rule in the DB (0055, CONSTRAINT approver_not_finance_staff).
FINANCE_APPROVER_ROLES = frozenset({Role.FINANCE.value, Role.SUPER_ADMIN.value})
# Q70 (wave 2.1): in production, money ENTERING wallets (top-up approvals, plain credit adjustments) and amendment
# hold increases wait for the Q48 gate, like new holds. Named integrator interpretation: debit adjustments (Q31
# refunds of a remaining prepaid balance) and commission reversals (N5 obligations on a real capture) are NOT
# gated. DB backstop 0055 (CONSTRAINT q48_gate_money_refused).
Q48_GATE_CHECK = "q48_money_gate"
Q70_DEBIT_ADJUSTMENTS_GATED = False
Q70_COMMISSION_REVERSALS_GATED = False

__all__ = [
    "AccountBlockingState",
    "AdjustmentOutcome",
    "CaptureResult",
    "FeeQuote",
    "HoldResult",
    "InvariantCheck",
    "LARGE_AMOUNT_THRESHOLD_MINOR",
    "LedgerLine",
    "ProductionInvariantReport",
    "ReconciliationReport",
    "ReversalResult",
    "WalletSnapshot",
    "adjust_hold",
    "approve_adjustment",
    "approve_topup",
    "assert_production_invariants",
    "blocking_state_for_user",
    "capture_fee",
    "create_policy",
    "create_topup",
    "current_global_standard",
    "driver_account_code",
    "end_policy",
    "get_or_create_wallet",
    "get_wallet",
    "hold_fee",
    "is_finance_approver",
    "money_in_gated",
    "list_ledger_lines",
    "list_policies",
    "lock_wallet",
    "quote_fee",
    "reconcile",
    "reject_topup",
    "release_fee",
    "replace_global_standard",
    "request_adjustment",
    "require_money_invariants",
    "resolve_policy",
    "reverse_fee",
    "set_test_overdraft_allowed",
    "SplitAdjustmentSignal",
    "confirm_policy",
    "reject_adjustment",
    "run_reconciliation",
    "split_adjustment_signals",
    "withdraw_adjustment",
]


# --- result types -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WalletSnapshot:
    id: int
    public_id: str
    driver_user_id: int
    currency: str
    posted_balance_minor: int
    held_minor: int
    available_minor: int
    pending_topups_minor: int
    version: int
    as_of: datetime


@dataclass(frozen=True, slots=True)
class HoldResult:
    hold_id: int
    wallet_id: int
    booking_id: int
    amount_minor: int
    delta_minor: int
    status: str
    commission_status: CommissionStatus
    changed: bool


@dataclass(frozen=True, slots=True)
class CaptureResult:
    hold_id: int
    transaction_id: int
    captured_minor: int
    commission_status: CommissionStatus
    already_captured: bool


@dataclass(frozen=True, slots=True)
class ReversalResult:
    transaction: LedgerTransaction
    reversed_minor: int
    remaining_minor: int
    commission_status: CommissionStatus


@dataclass(frozen=True, slots=True)
class FeeQuote:
    policy_id: int
    policy_public_id: str
    policy_kind: CommissionPolicyKind
    fee_bps: int
    total_minor: int
    commission_minor: int
    net_minor: int
    currency: str = Currency.UZS.value


@dataclass(frozen=True, slots=True)
class AdjustmentOutcome:
    status: str  # "posted" | "pending_second_approval"
    request: LedgerAdjustmentRequest | None
    transaction: LedgerTransaction | None


@dataclass(frozen=True, slots=True)
class LedgerLine:
    transaction_id: int
    transaction_public_id: str
    occurred_at: datetime
    kind: str
    direction: str
    amount_minor: int
    balance_after_minor: int
    reference_kind: str
    reference_key: str
    entry_id: int


@dataclass(frozen=True, slots=True)
class InvariantCheck:
    name: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable (Q57): readiness shows notices as info only."""
        return {"name": self.name, "ok": self.ok, "detail": dict(self.detail)}


@dataclass(frozen=True, slots=True)
class ProductionInvariantReport:
    """Structured result for readiness (A10a) and the money-command guard (BR N1).

    ``ok`` False means: readiness reports ``production_invariants: fail`` and raises an
    alert (``alert`` True) but must NOT fail the whole API; money commands refuse with
    ``503 PRODUCTION_INVARIANTS_FAILED``.
    """

    ok: bool
    is_production: bool
    app_environment: str
    db_environment: str | None
    checks: tuple[InvariantCheck, ...]
    # Informational only (never affect ``ok``), e.g. ``unconfirmed_seed_policy_active`` (Q28).
    notices: tuple[InvariantCheck, ...] = ()

    @property
    def alert(self) -> bool:
        return not self.ok

    @property
    def failed(self) -> list[str]:
        return [check.name for check in self.checks if not check.ok]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "pass" if self.ok else "fail",
            "is_production": self.is_production,
            "app_environment": self.app_environment,
            "db_environment": self.db_environment,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "notices": [{"name": c.name, "detail": c.detail} for c in self.notices],
        }


@dataclass(frozen=True, slots=True)
class AccountBlockingState:
    """Read-only wallet facts that block account deletion (BR N4, ADR-0006 D5)."""

    has_wallet: bool
    posted_balance_minor: int
    held_minor: int
    active_holds_count: int
    pending_topups_count: int
    pending_topups_minor: int
    pending_adjustments_count: int

    @property
    def blocks_deletion(self) -> bool:
        return bool(
            self.posted_balance_minor != 0
            or self.held_minor != 0
            or self.active_holds_count
            or self.pending_topups_count
            or self.pending_adjustments_count
        )

    def as_details(self) -> dict[str, int]:
        return {
            "wallet_posted_minor": self.posted_balance_minor,
            "active_holds_minor": self.held_minor,
            "active_holds_count": self.active_holds_count,
            "pending_topups_count": self.pending_topups_count,
            "pending_adjustments_count": self.pending_adjustments_count,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    run_date: date
    wallets_checked: int
    mismatches: list[dict[str, Any]]
    unbalanced_transactions: list[dict[str, Any]]
    overdraft_wallets: list[dict[str, Any]]
    is_production: bool
    # Q55: postings without a valid business source (should always be empty).
    orphan_postings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def mismatch_count(self) -> int:
        overdraft = len(self.overdraft_wallets) if self.is_production else 0
        return len(self.mismatches) + len(self.unbalanced_transactions) + overdraft + len(self.orphan_postings)


# --- helpers -------------------------------------------------------------------------------------------


def _require_capability(capabilities: Collection[Capability | str], capability: Capability) -> None:
    if capability not in {Capability(c) for c in capabilities}:
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": capability.value})


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:  # SQLite returns naive UTC values
        from app.contracts.timeutil import UTC

        return value.replace(tzinfo=UTC)
    return ensure_aware_utc(value)


def is_finance_approver(session: Session, user_id: int | None) -> bool:
    """Q69: active user holding ``finance`` or ``super_admin`` (primary role or active ``user_roles`` row)."""
    if user_id is None:
        return False
    row = session.execute(text("SELECT role, status FROM users WHERE id = :id"), {"id": user_id}).one_or_none()
    if row is None or row.status != "active":
        return False
    if row.role in FINANCE_APPROVER_ROLES:
        return True
    if not table_exists(session, "user_roles"):
        return False
    return bool(session.execute(
        text("SELECT count(*) FROM user_roles WHERE user_id = :id AND status = 'active' "
             "AND role IN ('finance', 'super_admin')"),
        {"id": user_id},
    ).scalar_one())


def _require_finance_approver(session: Session, user_id: int | None) -> None:
    if not is_finance_approver(session, user_id):
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "approver_not_finance_staff"})


def money_in_gated(direction: str, reversal_of_transaction_id: int | None) -> bool:
    """Q70: which adjustments need the Q48 gate in production (plain credits only; see constants)."""
    if direction == DEBIT:
        return Q70_DEBIT_ADJUSTMENTS_GATED
    if reversal_of_transaction_id is not None:
        return Q70_COMMISSION_REVERSALS_GATED
    return True


def _require_q48_gate(report: ProductionInvariantReport) -> None:
    """Q70 / amendment hold increases: refuse while the production Q48 gate fails (``hold_fee`` uses the same check)."""
    if report.is_production and Q48_GATE_CHECK in report.failed:
        raise DomainError(ErrorCode.PRODUCTION_INVARIANTS_FAILED, details={"failed": [Q48_GATE_CHECK]})


def _audit(session: Session, actor_user_id: int | None, entity_type: str, entity_id: int, action: str,
           new_value: dict[str, Any], reason: str | None = None) -> None:
    from fastapi.encoders import jsonable_encoder

    from app.models import AuditLog

    session.add(
        AuditLog(
            actor_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details=jsonable_encoder({"new_value": new_value, "reason": reason, "module": "wallet"}),
        )
    )


def driver_account_code(driver_user_id: int) -> str:
    return f"driver_prepaid:{driver_user_id}"


def wallet_public_id(wallet: WalletAccount) -> str:
    return format_public_id(PublicIdPrefix.WALLET, wallet.public_id)


def _dialect_insert(session: Session):
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def _system_account(session: Session, code: str, currency: str = Currency.UZS.value) -> LedgerAccount:
    account = session.execute(
        select(LedgerAccount).where(LedgerAccount.code == code, LedgerAccount.currency == currency)
    ).scalar_one_or_none()
    if account is None:
        # Seeded by migration 0041; created lazily only where migrations never ran (SQLite suite).
        kind = {"cash_bank": "asset", "cash_desk": "asset", "commission_revenue": "revenue",
                "manual_adjustments": "contra"}[code]
        insert = _dialect_insert(session)
        session.execute(
            insert(LedgerAccount).values(code=code, kind=kind, currency=currency)
            .on_conflict_do_nothing(index_elements=["code", "currency"])
        )
        account = session.execute(
            select(LedgerAccount).where(LedgerAccount.code == code, LedgerAccount.currency == currency)
        ).scalar_one()
    return account


def _commission_status_of(hold: WalletHold) -> CommissionStatus:
    if hold.status == HOLD_ACTIVE:
        return CommissionStatus.HELD
    if hold.status == HOLD_RELEASED:
        return CommissionStatus.RELEASED
    if hold.reversed_minor == 0:
        return CommissionStatus.CAPTURED
    if hold.reversed_minor < hold.captured_minor:
        return CommissionStatus.PARTIALLY_REVERSED
    return CommissionStatus.REVERSED


def _wallet_required_flag(session: Session, corridor_id: int | None) -> bool:
    """``wallet_required`` from A2's flag service; strictest value (True) if unavailable."""
    try:
        from app.modules.geo import service as geo_service  # type: ignore[attr-defined]
    except ImportError:
        return True
    is_flag_enabled = getattr(geo_service, "is_flag_enabled", None)
    if is_flag_enabled is None:
        return True
    return bool(is_flag_enabled(session, FeatureFlagKey.WALLET_REQUIRED, corridor_id=corridor_id))


def _capabilities_of(session: Session, user_id: int) -> frozenset[Capability]:
    """Server-computed capabilities of another user via A1 ``identity.get_capabilities``. Fails closed."""
    try:
        from app.modules.identity.service import get_capabilities
    except ImportError:  # pragma: no cover - identity ships in wave 1
        return frozenset()
    try:
        result = get_capabilities(session, user_id)
    except DomainError:
        return frozenset()
    return frozenset(Capability(value) for value in getattr(result, "capabilities", ()))


def _is_global_standard(policy: CommissionPolicy) -> bool:
    return (
        policy.kind == CommissionPolicyKind.STANDARD.value
        and policy.scope_corridor_id is None
        and policy.scope_service_type is None
    )


def _require_confirmed_policy(session: Session, policy: CommissionPolicy, *, production: bool | None = None) -> None:
    """Decision 28: in production the migration seed (``created_by IS NULL``) needs a super_admin confirm."""
    if policy.created_by is not None or policy.confirmed_by is not None:
        return
    if production is None:
        production = is_production(session)
    if production:
        code = getattr(ErrorCode, "COMMISSION_POLICY_UNCONFIRMED", ErrorCode.SERVICE_UNAVAILABLE)
        raise DomainError(code, details={"reason": "commission_policy_unconfirmed"})


# --- production invariants (BR N1) -----------------------------------------------------------------


def assert_production_invariants(session: Session) -> ProductionInvariantReport:
    """Evaluate production money invariants without raising. Used by readiness and guards.

    Fail closed (wave 1.5 BR #2/#3): an ``ELCHI_ENVIRONMENT`` outside the allowlist, or a migrated
    database without a marker row, counts as production and fails the report.
    """
    checks: list[InvariantCheck] = []
    try:
        app_env: DeploymentEnvironment | None = app_environment()
    except ValueError:
        app_env = None
        checks.append(InvariantCheck("app_environment_valid", False, {"reason": "unknown_environment"}))
    marker = get_db_marker_state(session)
    db_env = marker.environment
    is_prod = (
        app_env is None
        or app_env is DeploymentEnvironment.PRODUCTION
        or db_env is DeploymentEnvironment.PRODUCTION
        or marker.missing
    )

    if marker.missing:
        checks.append(InvariantCheck("environment_marker", False, {"reason": "marker_missing"}))
    elif not marker.table_present:
        checks.append(InvariantCheck("environment_marker", not is_prod, {"reason": "marker_table_missing"}))
    elif is_prod and app_env is not db_env:
        checks.append(
            InvariantCheck("environment_marker", False,
                           {"reason": "mismatch", "app": None if app_env is None else app_env.value, "db": db_env.value})
        )
    else:
        checks.append(InvariantCheck("environment_marker", True, {"db": db_env.value}))

    if table_exists(session, WalletAccount.__tablename__):
        overdraft_ids = list(
            session.execute(
                select(WalletAccount.id).where(WalletAccount.test_overdraft_allowed.is_(True)).order_by(WalletAccount.id).limit(20)
            ).scalars()
        )
        checks.append(
            InvariantCheck("no_test_overdraft_wallets", not (is_prod and overdraft_ids),
                           {"count_sample": len(overdraft_ids)} if overdraft_ids else {})
        )
        if is_prod:
            negative = session.execute(
                select(func.count()).select_from(WalletAccount)
                .where(WalletAccount.posted_balance_minor - WalletAccount.held_minor < 0)
            ).scalar_one()
            checks.append(InvariantCheck("no_negative_available", negative == 0, {"count": negative} if negative else {}))

    if is_prod:
        # Q56: the Q48 launch gate. Blocks new business (holds) only; obligations keep working.
        gate = q48_gate_status(session)
        checks.append(InvariantCheck("q48_money_gate", gate.ok, {"failed": gate.failed}))

    if is_prod and table_exists(session, "feature_flag_values"):
        # Read-only readiness probe of A2's table (A2: expose a service function; see report).
        disabled = session.execute(
            text("SELECT count(*) FROM feature_flag_values WHERE flag_key = 'wallet_required' AND enabled = false")
        ).scalar_one()
        checks.append(InvariantCheck("wallet_required_locked_true", disabled == 0, {"count": disabled} if disabled else {}))

    notices: list[InvariantCheck] = []
    if table_exists(session, CommissionPolicy.__tablename__):
        # BR #6: new quotes and holds need a global standard covering now (readiness reports it).
        current = current_global_standard(session)
        checks.append(InvariantCheck("global_standard_active_now", current is not None))
        if current is not None and current.created_by is None and current.confirmed_by is None:
            # Q28 info: production quotes/holds stay blocked until a super_admin confirms or replaces it.
            notices.append(InvariantCheck("unconfirmed_seed_policy_active", True,
                                          {"blocks_production_quotes_and_holds": is_prod}))

    ok = all(check.ok for check in checks)
    return ProductionInvariantReport(
        ok=ok,
        is_production=is_prod,
        app_environment="invalid" if app_env is None else app_env.value,
        db_environment=None if db_env is None else db_env.value,
        checks=tuple(checks),
        notices=tuple(notices),
    )


def require_money_invariants(session: Session, *, new_business: bool = False) -> ProductionInvariantReport:
    """Refuse money commands while production invariants fail (N1).

    ``new_business=False`` (obligations on existing money) ignores ``NEW_BUSINESS_ONLY_CHECKS``
    (wave 1.6 N5): a missing global standard must not stop capture, release, reversals or adjustments.
    """
    report = assert_production_invariants(session)
    failed = [name for name in report.failed if new_business or name not in NEW_BUSINESS_ONLY_CHECKS]
    if failed:
        raise DomainError(ErrorCode.PRODUCTION_INVARIANTS_FAILED, details={"failed": failed})
    return report


def set_test_overdraft_allowed(session: Session, wallet_id: int, allowed: bool, *, actor_user_id: int | None) -> WalletAccount:
    """Non-production seed helper (Q1). Refused on production (service + DB trigger)."""
    report = assert_production_invariants(session)
    if allowed and report.is_production:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "test_overdraft_forbidden_in_production"})
    wallet = lock_wallet(session, wallet_id)
    wallet.test_overdraft_allowed = allowed
    wallet.version += 1
    wallet.updated_at = utc_now()
    session.flush()
    _audit(session, actor_user_id, "wallet_accounts", wallet.id, "test_overdraft_set", {"allowed": allowed})
    return wallet


# --- wallets ------------------------------------------------------------------------------------------


def get_or_create_wallet(session: Session, driver_user_id: int, *, currency: str = Currency.UZS.value) -> WalletAccount:
    wallet = session.execute(
        select(WalletAccount).where(WalletAccount.driver_user_id == driver_user_id, WalletAccount.currency == currency)
    ).scalar_one_or_none()
    if wallet is not None:
        return wallet
    insert = _dialect_insert(session)
    code = driver_account_code(driver_user_id)
    session.execute(
        insert(LedgerAccount)
        .values(code=code, kind="liability", owner_user_id=driver_user_id, currency=currency)
        .on_conflict_do_nothing(index_elements=["code", "currency"])
    )
    account_id = session.execute(
        select(LedgerAccount.id).where(LedgerAccount.code == code, LedgerAccount.currency == currency)
    ).scalar_one()
    session.execute(
        insert(WalletAccount)
        .values(public_id=uuid.uuid4(), driver_user_id=driver_user_id, ledger_account_id=account_id, currency=currency)
        .on_conflict_do_nothing(index_elements=["driver_user_id", "currency"])
    )
    return session.execute(
        select(WalletAccount).where(WalletAccount.driver_user_id == driver_user_id, WalletAccount.currency == currency)
    ).scalar_one()


def lock_wallet(session: Session, wallet_id: int) -> WalletAccount:
    wallet = session.execute(
        select(WalletAccount).where(WalletAccount.id == wallet_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if wallet is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return wallet


def _pending_topups_minor(session: Session, wallet_id: int) -> int:
    return int(
        session.execute(
            select(func.coalesce(func.sum(TopupRequest.amount_minor), 0)).where(
                TopupRequest.wallet_id == wallet_id,
                TopupRequest.status.in_([TopupStatus.PENDING.value, TopupStatus.AWAITING_SECOND_APPROVAL.value]),
            )
        ).scalar_one()
    )


def get_wallet(session: Session, driver_user_id: int) -> WalletSnapshot:
    wallet = get_or_create_wallet(session, driver_user_id)
    return WalletSnapshot(
        id=wallet.id,
        public_id=wallet_public_id(wallet),
        driver_user_id=wallet.driver_user_id,
        currency=wallet.currency,
        posted_balance_minor=wallet.posted_balance_minor,
        held_minor=wallet.held_minor,
        available_minor=wallet.posted_balance_minor - wallet.held_minor,
        pending_topups_minor=_pending_topups_minor(session, wallet.id),
        version=wallet.version,
        as_of=utc_now(),
    )


def _touch(wallet: WalletAccount, *, posted_delta: int = 0, held_delta: int = 0) -> None:
    wallet.posted_balance_minor += posted_delta
    wallet.held_minor += held_delta
    wallet.version += 1
    wallet.updated_at = utc_now()


def _post_transaction(
    session: Session,
    *,
    reference_kind: str,
    reference_key: str,
    description: str,
    entries: Iterable[tuple[int, str, int]],
    wallet_id: int | None,
    booking_id: int | None = None,
    created_by: int | None = None,
    second_approver_id: int | None = None,
    evidence: dict[str, Any] | None = None,
    reversal_of_id: int | None = None,
    duplicate_error: ErrorCode = ErrorCode.VALIDATION_ERROR,
    source_type: str,
    source_id: int,
) -> LedgerTransaction:
    if source_type not in LEDGER_SOURCE_TYPES or not isinstance(source_id, int):
        raise ValueError(f"ledger posting needs a business source (Q55), got {source_type!r}/{source_id!r}")
    lines = list(entries)
    debit = sum(amount for _, direction, amount in lines if direction == DEBIT)
    credit = sum(amount for _, direction, amount in lines if direction == CREDIT)
    if len(lines) < 2 or debit != credit or any(amount <= 0 for _, _, amount in lines):
        raise DomainError(ErrorCode.LEDGER_UNBALANCED, details={"debit_minor": debit, "credit_minor": credit})
    transaction = LedgerTransaction(
        public_id=uuid.uuid4(),
        reference_kind=reference_kind,
        reference_key=reference_key,
        description=description,
        reversal_of_id=reversal_of_id,
        wallet_id=wallet_id,
        booking_id=booking_id,
        created_by=created_by,
        second_approver_id=second_approver_id,
        evidence=evidence or {},
        source_type=source_type,
        source_id=source_id,
    )
    try:
        with session.begin_nested():
            session.add(transaction)
            session.flush()
    except IntegrityError as exc:
        if constraint_name_of(exc) == "uq_ledger_transactions_reference" or sqlstate_of(exc) == "23505":
            raise DomainError(duplicate_error, details={"reference": f"{reference_kind}:{reference_key}"}) from exc
        raise
    for account_id, direction, amount in lines:
        session.add(LedgerEntry(transaction_id=transaction.id, account_id=account_id, direction=direction,
                                amount_minor=amount, currency=Currency.UZS.value))
    session.flush()
    return transaction


def _wallet_event(session: Session, wallet: WalletAccount, event_type: EventType, payload: dict[str, Any]) -> None:
    enqueue_event(
        session,
        EventEnvelope(
            event_type=event_type,
            aggregate_type="wallet",
            aggregate_public_id=wallet_public_id(wallet),
            aggregate_version=wallet.version,
            occurred_at=utc_now(),
            payload=payload,
        ),
        aggregate_id=wallet.id,
    )


def _balance_guard(wallet: WalletAccount, amount: int, *, check_balance: bool) -> None:
    available = wallet.posted_balance_minor - wallet.held_minor
    if amount <= available:
        return
    # No balance figures in details: the accept caller may be the client (Q16).
    if check_balance:
        raise DomainError(ErrorCode.INSUFFICIENT_COMMISSION_BALANCE)
    if not wallet.test_overdraft_allowed:
        raise DomainError(ErrorCode.INSUFFICIENT_COMMISSION_BALANCE, details={"reason": "overdraft_not_allowed"})


def _balance_check_required(session: Session, report: ProductionInvariantReport, corridor_id: int | None,
                            wallet_required: bool | None) -> bool:
    flag = _wallet_required_flag(session, corridor_id) if wallet_required is None else wallet_required
    try:
        return balance_check_required(is_production=report.is_production, wallet_required_flag=flag)
    except ValueError as exc:  # wallet_required=false in production is a configuration error
        raise DomainError(ErrorCode.PRODUCTION_INVARIANTS_FAILED,
                          details={"failed": ["wallet_required_locked_true"]}) from exc


def _hold_by_booking(session: Session, booking_id: int, *, lock: bool = False) -> WalletHold | None:
    query = select(WalletHold).where(WalletHold.booking_id == booking_id,
                                     WalletHold.charge_kind == ChargeKind.COMMISSION.value)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.execute(query).scalar_one_or_none()


def _lock_wallet_and_hold(session: Session, booking_id: int) -> tuple[WalletAccount, WalletHold]:
    unlocked = _hold_by_booking(session, booking_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"object": "wallet_hold"})
    wallet = lock_wallet(session, unlocked.wallet_id)
    hold = _hold_by_booking(session, booking_id, lock=True)
    if hold is None or hold.wallet_id != wallet.id:  # pragma: no cover - holds never move
        raise DomainError(ErrorCode.VERSION_CONFLICT)
    return wallet, hold


# --- holds (called by A4 inside its accept/cancel/amend/complete transaction) ---------------------


def hold_fee(
    session: Session,
    *,
    booking_id: int,
    booking_public_id: str,
    driver_user_id: int,
    total_minor: int,
    fee_bps: int,
    corridor_id: int | None = None,
    wallet_required: bool | None = None,
    fee_policy_id: int | None = None,
    now: datetime | None = None,
) -> HoldResult:
    """``∅ -> held`` (STATE_MACHINES §7). A 0 bps snapshot is ``exempt``: do not call (D3).

    ``fee_policy_id`` is the booking's snapshotted policy (internal id). It must match ``fee_bps``;
    in production it is required and an unconfirmed migration seed is refused (decision 28).
    """
    validate_fee_bps(fee_bps)
    if fee_bps == 0:
        raise ValueError("0 bps snapshot is exempt: no hold, no ledger (D3)")
    amount = commission_minor(total_minor, fee_bps)
    if amount <= 0:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "commission_rounds_to_zero"})
    report = require_money_invariants(session, new_business=True)
    check_balance = _balance_check_required(session, report, corridor_id, wallet_required)
    if fee_policy_id is None:
        if report.is_production:
            raise DomainError(ErrorCode.VALIDATION_ERROR,
                              details={"field": "fee_policy_id", "reason": "required_in_production"})
    else:
        policy = session.get(CommissionPolicy, fee_policy_id)
        if policy is None or policy.fee_bps != fee_bps:
            raise DomainError(ErrorCode.VALIDATION_ERROR,
                              details={"field": "fee_policy_id", "reason": "policy_snapshot_mismatch"})
        _require_confirmed_policy(session, policy, production=report.is_production)
    now = now or utc_now()

    wallet = lock_wallet(session, get_or_create_wallet(session, driver_user_id).id)
    existing = _hold_by_booking(session, booking_id, lock=True)
    if existing is not None:
        if (existing.wallet_id, existing.amount_minor, existing.fee_bps, existing.status) == (
            wallet.id, amount, fee_bps, HOLD_ACTIVE
        ):
            return HoldResult(existing.id, wallet.id, booking_id, amount, 0, existing.status, CommissionStatus.HELD, False)
        raise DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "hold_exists"})
    _balance_guard(wallet, amount, check_balance=check_balance)

    hold = WalletHold(
        wallet_id=wallet.id,
        booking_id=booking_id,
        booking_public_id=booking_public_id,
        charge_kind=ChargeKind.COMMISSION.value,
        fee_bps=fee_bps,
        amount_minor=amount,
        currency=wallet.currency,
        status=HOLD_ACTIVE,
        captured_minor=0,
        reversed_minor=0,
        escalate_at=now + HOLD_ESCALATE_AFTER,
    )
    session.add(hold)
    _touch(wallet, held_delta=amount)
    session.flush()
    _wallet_event(session, wallet, EventType.WALLET_HOLD_CREATED,
                  {"booking_id": booking_public_id, "amount_minor": amount, "currency": wallet.currency})
    return HoldResult(hold.id, wallet.id, booking_id, amount, amount, HOLD_ACTIVE, CommissionStatus.HELD, True)


def adjust_hold(
    session: Session,
    *,
    booking_id: int,
    new_total_minor: int,
    fee_bps: int,
    corridor_id: int | None = None,
    wallet_required: bool | None = None,
) -> HoldResult:
    """``held -> held`` on amendment accept (D10): same single hold, snapshot bps unchanged."""
    report = require_money_invariants(session)
    wallet, hold = _lock_wallet_and_hold(session, booking_id)
    COMMISSION.assert_transition(_commission_status_of(hold).value, CommissionStatus.HELD.value, "adjust_hold")
    if hold.fee_bps != fee_bps:
        raise DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "fee_bps_snapshot_mismatch"})
    new_amount = commission_minor(new_total_minor, hold.fee_bps)
    if new_amount <= 0:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "commission_rounds_to_zero"})
    delta = hold_adjustment_minor(hold.amount_minor, new_amount)
    if delta == 0:
        return HoldResult(hold.id, wallet.id, booking_id, hold.amount_minor, 0, hold.status, CommissionStatus.HELD, False)
    if delta > 0:
        _require_q48_gate(report)  # wave 2.1: a hold increase is new business like hold_fee (AC19, D10)
        _balance_guard(wallet, delta, check_balance=_balance_check_required(session, report, corridor_id, wallet_required))
    hold.amount_minor = new_amount
    hold.version += 1
    hold.updated_at = utc_now()
    _touch(wallet, held_delta=delta)
    session.flush()
    _wallet_event(session, wallet, EventType.WALLET_HOLD_ADJUSTED,
                  {"booking_id": hold.booking_public_id or str(booking_id), "amount_minor": new_amount,
                   "delta_minor": delta, "currency": wallet.currency})
    return HoldResult(hold.id, wallet.id, booking_id, new_amount, delta, hold.status, CommissionStatus.HELD, True)


def capture_fee(session: Session, *, booking_id: int, actor_user_id: int | None = None) -> CaptureResult:
    """``held -> captured`` in one transaction with the hold release; repeat is a no-op (AC20).

    Capability-free on purpose (system path of A4's ``complete``). The operator ``finalize_fee``
    command must be authorized by A4 with ``finance.fee_finalize`` before calling this.
    """
    require_money_invariants(session)
    wallet, hold = _lock_wallet_and_hold(session, booking_id)
    if hold.status == HOLD_CAPTURED:
        return CaptureResult(hold.id, int(hold.capture_transaction_id), hold.captured_minor,
                             _commission_status_of(hold), True)
    COMMISSION.assert_transition(_commission_status_of(hold).value, CommissionStatus.CAPTURED.value, "capture")
    amount = hold.amount_minor
    revenue = _system_account(session, ACCOUNT_COMMISSION_REVENUE, wallet.currency)
    transaction = _post_transaction(
        session,
        reference_kind="commission_capture",
        source_type="wallet_hold",
        source_id=hold.id,
        reference_key=f"commission:capture:{booking_id}",
        description=f"commission capture for booking {hold.booking_public_id or booking_id}",
        entries=[(wallet.ledger_account_id, DEBIT, amount), (revenue.id, CREDIT, amount)],
        wallet_id=wallet.id,
        booking_id=booking_id,
        created_by=actor_user_id,
        evidence={"fee_bps": hold.fee_bps},
    )
    now = utc_now()
    hold.status = HOLD_CAPTURED
    hold.captured_minor = amount
    hold.capture_transaction_id = transaction.id
    hold.resolved_at = now
    hold.version += 1
    hold.updated_at = now
    _touch(wallet, posted_delta=-amount, held_delta=-amount)
    session.flush()
    _wallet_event(session, wallet, EventType.COMMISSION_CAPTURED,
                  {"booking_id": hold.booking_public_id or str(booking_id), "amount_minor": amount,
                   "currency": wallet.currency, "fee_bps": hold.fee_bps})
    return CaptureResult(hold.id, transaction.id, amount, CommissionStatus.CAPTURED, False)


def release_fee(session: Session, *, booking_id: int) -> HoldResult:
    """``held -> released`` (cancel, confirmed no-show, operator ``finalize_fee``); repeat is a no-op.

    Capability-free building block; A4 enforces ``finance.fee_finalize`` for the operator path.
    """
    require_money_invariants(session)
    wallet, hold = _lock_wallet_and_hold(session, booking_id)
    if hold.status == HOLD_RELEASED:
        return HoldResult(hold.id, wallet.id, booking_id, hold.amount_minor, 0, hold.status, CommissionStatus.RELEASED, False)
    COMMISSION.assert_transition(_commission_status_of(hold).value, CommissionStatus.RELEASED.value, "release")
    now = utc_now()
    hold.status = HOLD_RELEASED
    hold.resolved_at = now
    hold.version += 1
    hold.updated_at = now
    _touch(wallet, held_delta=-hold.amount_minor)
    session.flush()
    _wallet_event(session, wallet, EventType.WALLET_HOLD_RELEASED,
                  {"booking_id": hold.booking_public_id or str(booking_id), "amount_minor": hold.amount_minor,
                   "currency": wallet.currency})
    return HoldResult(hold.id, wallet.id, booking_id, hold.amount_minor, -hold.amount_minor, HOLD_RELEASED,
                      CommissionStatus.RELEASED, True)


def reverse_fee(
    session: Session,
    *,
    booking_id: int,
    amount_minor: int,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    reason: str,
    evidence: dict[str, Any] | None = None,
    second_approver_id: int | None = None,
) -> ReversalResult:
    """``captured|partially_reversed -> partially_reversed|reversed`` (D4, AC25).

    Each call is a new balanced ledger transaction linked by ``reversal_of_id`` (not unique).
    The cumulative sum is checked under the wallet lock.

    Authorization (wave 1.5 BR #5, chosen option): the actor needs ``finance.adjustment``. A second
    approver is mandatory above ``TWO_PERSON_APPROVAL_THRESHOLD_MINOR`` and, whenever given, must be
    a different user whose server-computed capabilities (A1 ``identity.get_capabilities``) include
    ``finance.adjustment_approve``. HTTP callers reach reversals only through adjustment requests
    (W8 -> W16), which pass the approving user here.
    """
    _require_capability(actor_capabilities, Capability.FINANCE_ADJUSTMENT)
    validate_minor_amount(amount_minor, allow_zero=False)
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    if second_approver_id is not None:
        if (second_approver_id == actor_user_id
                or Capability.FINANCE_ADJUSTMENT_APPROVE not in _capabilities_of(session, second_approver_id)):
            raise DomainError(ErrorCode.SECOND_APPROVER_REQUIRED, details={"reason": "approver_not_eligible"})
    elif amount_minor > TWO_PERSON_APPROVAL_THRESHOLD_MINOR:
        raise DomainError(ErrorCode.SECOND_APPROVER_REQUIRED)
    require_money_invariants(session)
    wallet, hold = _lock_wallet_and_hold(session, booking_id)
    current = _commission_status_of(hold)
    if hold.status != HOLD_CAPTURED:
        COMMISSION.assert_transition(current.value, CommissionStatus.PARTIALLY_REVERSED.value, "reverse_partial")
    try:
        new_reversed = validate_reversal(hold.captured_minor, hold.reversed_minor, amount_minor)
    except ValueError as exc:
        raise DomainError(
            ErrorCode.REVERSAL_EXCEEDS_CAPTURED,
            details={"remaining_minor": hold.captured_minor - hold.reversed_minor},
        ) from exc
    target = CommissionStatus.REVERSED if new_reversed == hold.captured_minor else CommissionStatus.PARTIALLY_REVERSED
    COMMISSION.assert_transition(current.value, target.value,
                                 "reverse" if target is CommissionStatus.REVERSED else "reverse_partial")
    sequence = 1 + session.execute(
        select(func.count()).select_from(LedgerTransaction).where(
            LedgerTransaction.reversal_of_id == hold.capture_transaction_id
        )
    ).scalar_one()
    revenue = _system_account(session, ACCOUNT_COMMISSION_REVENUE, wallet.currency)
    transaction = _post_transaction(
        session,
        reference_kind="commission_reversal",
        source_type="wallet_hold",
        source_id=hold.id,
        reference_key=f"commission:reversal:{booking_id}:{sequence}",
        description=reason.strip(),
        entries=[(revenue.id, DEBIT, amount_minor), (wallet.ledger_account_id, CREDIT, amount_minor)],
        wallet_id=wallet.id,
        booking_id=booking_id,
        created_by=actor_user_id,
        second_approver_id=second_approver_id,
        evidence=evidence or {},
        reversal_of_id=hold.capture_transaction_id,
    )
    hold.reversed_minor = new_reversed
    hold.version += 1
    hold.updated_at = utc_now()
    _touch(wallet, posted_delta=amount_minor)
    session.flush()
    _audit(session, actor_user_id, "ledger_transactions", transaction.id, "commission_reversed",
           {"booking_id": booking_id, "amount_minor": amount_minor, "reversed_minor": new_reversed,
            "second_approver_id": second_approver_id}, reason)
    _wallet_event(session, wallet, EventType.COMMISSION_REVERSED,
                  {"booking_id": hold.booking_public_id or str(booking_id), "amount_minor": amount_minor,
                   "currency": wallet.currency, "reversal_kind": "full" if target is CommissionStatus.REVERSED else "partial"})
    return ReversalResult(transaction, new_reversed, hold.captured_minor - new_reversed, target)


# --- manual adjustments (W8 / W16) ------------------------------------------------------------------


def _post_adjustment(
    session: Session,
    request: LedgerAdjustmentRequest,
    *,
    approver_id: int | None,
    requester_capabilities: Collection[Capability | str],
) -> LedgerTransaction:
    # Wave 1.6 N6: every posting path (plain adjustment or reversal) re-checks the requester's authority.
    _require_capability(requester_capabilities, Capability.FINANCE_ADJUSTMENT)
    wallet = lock_wallet(session, request.wallet_id)
    if request.reversal_of_transaction_id is not None:
        capture = session.get(LedgerTransaction, request.reversal_of_transaction_id)
        if capture is None or capture.reference_kind != "commission_capture" or capture.booking_id is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reversal_of_transaction_id"})
        return reverse_fee(
            session,
            booking_id=capture.booking_id,
            amount_minor=request.amount_minor,
            actor_user_id=request.requested_by,
            actor_capabilities=requester_capabilities,
            reason=request.reason,
            evidence=request.evidence,
            second_approver_id=approver_id,
        ).transaction
    contra = _system_account(session, ACCOUNT_MANUAL_ADJUSTMENTS, wallet.currency)
    if request.direction == CREDIT:
        entries = [(contra.id, DEBIT, request.amount_minor), (wallet.ledger_account_id, CREDIT, request.amount_minor)]
        posted_delta = request.amount_minor
    else:
        _balance_guard(wallet, request.amount_minor, check_balance=True)
        entries = [(wallet.ledger_account_id, DEBIT, request.amount_minor), (contra.id, CREDIT, request.amount_minor)]
        posted_delta = -request.amount_minor
    transaction = _post_transaction(
        session,
        reference_kind="adjustment",
        source_type="ledger_adjustment_request",
        source_id=request.id,
        reference_key=f"adjustment:{request.public_id}",
        description=request.reason,
        entries=entries,
        wallet_id=wallet.id,
        booking_id=request.booking_id,
        created_by=request.requested_by,
        second_approver_id=approver_id,
        evidence=request.evidence,
    )
    _touch(wallet, posted_delta=posted_delta)
    session.flush()
    return transaction


def request_adjustment(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    wallet_id: int,
    direction: str,
    amount_minor: int,
    reason: str,
    evidence_file_ids: list[str] | None = None,
    booking_id: int | None = None,
    reversal_of_transaction_id: int | None = None,
) -> AdjustmentOutcome:
    """Small adjustments post immediately; large ones wait for a different approver (Q17, W16)."""
    _require_capability(actor_capabilities, Capability.FINANCE_ADJUSTMENT)
    validate_minor_amount(amount_minor, allow_zero=False)
    if direction not in (DEBIT, CREDIT):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "direction"})
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    if reversal_of_transaction_id is not None and direction != CREDIT:
        # A commission reversal gives commission back to the driver.
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "direction", "expected": CREDIT})
    if amount_minor <= LARGE_AMOUNT_THRESHOLD_MINOR:
        _require_finance_approver(session, actor_user_id)  # Q69: posted on the requester's own authority
    report = require_money_invariants(session)
    if money_in_gated(direction, reversal_of_transaction_id):
        _require_q48_gate(report)  # Q70
    wallet = lock_wallet(session, wallet_id)
    request = LedgerAdjustmentRequest(
        public_id=uuid.uuid4(),
        wallet_id=wallet.id,
        direction=direction,
        amount_minor=amount_minor,
        currency=wallet.currency,
        reason=reason.strip(),
        evidence={"file_ids": list(evidence_file_ids or [])},
        booking_id=booking_id,
        reversal_of_transaction_id=reversal_of_transaction_id,
        status=ADJ_PENDING,
        requested_by=actor_user_id,
    )
    session.add(request)
    session.flush()
    if amount_minor > LARGE_AMOUNT_THRESHOLD_MINOR:
        _audit(session, actor_user_id, "ledger_adjustment_requests", request.id, "adjustment_requested",
               {"amount_minor": amount_minor, "direction": direction}, reason)
        return AdjustmentOutcome(ADJ_PENDING, request, None)
    transaction = _post_adjustment(session, request, approver_id=None, requester_capabilities=actor_capabilities)
    request.status = ADJ_POSTED
    request.decided_at = utc_now()
    request.ledger_transaction_id = transaction.id
    request.version += 1
    request.updated_at = utc_now()
    session.flush()
    _audit(session, actor_user_id, "ledger_transactions", transaction.id, "adjustment_posted",
           {"amount_minor": amount_minor, "direction": direction}, reason)
    return AdjustmentOutcome(ADJ_POSTED, request, transaction)


def approve_adjustment(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    adjustment_request_id: int,
    expected_version: int,
    note: str | None = None,
) -> AdjustmentOutcome:
    _require_capability(actor_capabilities, Capability.FINANCE_ADJUSTMENT_APPROVE)
    _require_finance_approver(session, actor_user_id)  # Q69
    report = require_money_invariants(session)
    unlocked = session.get(LedgerAdjustmentRequest, adjustment_request_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if money_in_gated(unlocked.direction, unlocked.reversal_of_transaction_id):
        _require_q48_gate(report)  # Q70 (direction/reversal link are immutable)
    lock_wallet(session, unlocked.wallet_id)
    request = session.execute(
        select(LedgerAdjustmentRequest).where(LedgerAdjustmentRequest.id == adjustment_request_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if request.status != ADJ_PENDING:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "ledger_adjustment", "from": request.status, "to": ADJ_POSTED})
    if request.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": request.version})
    if request.requested_by == actor_user_id:
        raise DomainError(ErrorCode.SECOND_APPROVER_REQUIRED)
    # The requester's authority is re-checked at posting time (roles may have changed since the request).
    transaction = _post_adjustment(session, request, approver_id=actor_user_id,
                                   requester_capabilities=_capabilities_of(session, request.requested_by))
    request.status = ADJ_POSTED
    request.decided_at = utc_now()
    request.approved_by = actor_user_id
    request.ledger_transaction_id = transaction.id
    request.version += 1
    request.updated_at = utc_now()
    session.flush()
    _audit(session, actor_user_id, "ledger_transactions", transaction.id, "adjustment_second_approved",
           {"adjustment_request_id": request.id, "amount_minor": request.amount_minor}, note)
    return AdjustmentOutcome(ADJ_POSTED, request, transaction)


def reject_adjustment(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    adjustment_request_id: int,
    expected_version: int,
    reason: str,
) -> LedgerAdjustmentRequest:
    """``pending_second_approval -> rejected`` with a reason (wave 1.5 BR #4, W17).

    A pending request that must never post is closed here; rejected requests do not block
    account deletion. No ledger effect.
    """
    _require_capability(actor_capabilities, Capability.FINANCE_ADJUSTMENT_APPROVE)
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    _require_finance_approver(session, actor_user_id)  # Q69
    unlocked = session.get(LedgerAdjustmentRequest, adjustment_request_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    lock_wallet(session, unlocked.wallet_id)
    request = session.execute(
        select(LedgerAdjustmentRequest).where(LedgerAdjustmentRequest.id == adjustment_request_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if request.status != ADJ_PENDING:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "ledger_adjustment", "from": request.status, "to": ADJ_REJECTED})
    if request.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": request.version})
    if request.requested_by == actor_user_id:
        # Q49: rejection is a second person's decision; the requester withdraws instead (W17a).
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "requester_must_withdraw"})
    now = utc_now()
    request.status = ADJ_REJECTED
    request.rejected_by = actor_user_id
    request.reject_reason = reason.strip()
    request.decided_at = now
    request.version += 1
    request.updated_at = now
    session.flush()
    _audit(session, actor_user_id, "ledger_adjustment_requests", request.id, "adjustment_rejected",
           {"amount_minor": request.amount_minor, "direction": request.direction}, reason)
    return request


def withdraw_adjustment(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    adjustment_request_id: int,
    expected_version: int,
    reason: str | None = None,
) -> LedgerAdjustmentRequest:
    """``pending_second_approval -> withdrawn`` by the requester only (Q49, proposed W17a).

    No ledger effect; withdrawn requests do not block account deletion.
    """
    _require_capability(actor_capabilities, Capability.FINANCE_ADJUSTMENT)
    unlocked = session.get(LedgerAdjustmentRequest, adjustment_request_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    lock_wallet(session, unlocked.wallet_id)
    request = session.execute(
        select(LedgerAdjustmentRequest).where(LedgerAdjustmentRequest.id == adjustment_request_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if request.requested_by != actor_user_id:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "only_requester_may_withdraw"})
    if request.status != ADJ_PENDING:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "ledger_adjustment", "from": request.status, "to": ADJ_WITHDRAWN})
    if request.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": request.version})
    now = utc_now()
    request.status = ADJ_WITHDRAWN
    request.decided_at = now
    request.version += 1
    request.updated_at = now
    session.flush()
    _audit(session, actor_user_id, "ledger_adjustment_requests", request.id, "adjustment_withdrawn",
           {"amount_minor": request.amount_minor, "direction": request.direction}, reason)
    return request


# --- top-ups -------------------------------------------------------------------------------------------


def create_topup(
    session: Session,
    *,
    driver_user_id: int,
    amount_minor: int,
    method: str,
    payer_reference: str | None = None,
    evidence_file_id: str | None = None,
    note: str | None = None,
) -> TopupRequest:
    """Pending request only: a screenshot is not money, balances do not change (AC24)."""
    validate_minor_amount(amount_minor, allow_zero=False)
    if method not in TOPUP_METHODS:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "method"})
    wallet = get_or_create_wallet(session, driver_user_id)
    topup = TopupRequest(
        public_id=uuid.uuid4(),
        driver_user_id=driver_user_id,
        wallet_id=wallet.id,
        amount_minor=amount_minor,
        currency=wallet.currency,
        method=method,
        payer_reference=payer_reference,
        evidence_file_id=evidence_file_id,
        note=note,
        status=TopupStatus.PENDING.value,
    )
    session.add(topup)
    session.flush()
    return topup


def _lock_topup(session: Session, topup_id: int) -> tuple[WalletAccount, TopupRequest]:
    unlocked = session.get(TopupRequest, topup_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    wallet = lock_wallet(session, unlocked.wallet_id)
    topup = session.execute(
        select(TopupRequest).where(TopupRequest.id == topup_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    return wallet, topup


def approve_topup(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    topup_id: int,
    expected_version: int,
    source_type: str,
    source_reference: str,
    received_amount_minor: int,
    received_at: datetime,
    note: str | None = None,
) -> TopupRequest:
    """``pending -> approved`` (<= threshold) or ``pending -> awaiting_second_approval -> approved``.

    The ledger reference ``topup:<source_type>:<source_reference>`` is unique and the partial
    unique index on ``topup_requests`` rejects a second request with the same source (AC23).
    """
    _require_capability(actor_capabilities, Capability.FINANCE_TOPUP_APPROVE)
    validate_minor_amount(received_amount_minor, allow_zero=False, name="received_amount_minor")
    if source_type not in SOURCE_TYPE_ACCOUNT:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "source_type"})
    reference = (source_reference or "").strip()
    if not reference:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "source_reference"})
    received_at = ensure_aware_utc(received_at, field="received_at")
    _require_finance_approver(session, actor_user_id)  # Q69 (first and second approval)
    _require_q48_gate(require_money_invariants(session))  # Q70 (first and second approval)
    wallet, topup = _lock_topup(session, topup_id)
    if topup.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": topup.version})
    if actor_user_id == topup.driver_user_id:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "self_approval"})
    # BR #10: checked under the wallet lock. Account deletion takes the same wallet lock
    # (blocking_state_for_user(lock=True)) after locking the user, so no credit lands on a deleted account.
    driver_status = session.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": topup.driver_user_id}
    ).scalar_one_or_none()
    if driver_status is None or driver_status == "deleted":
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "driver_account_deleted"})
    now = utc_now()

    if topup.status == TopupStatus.PENDING.value:
        duplicate = session.execute(
            select(TopupRequest.id).where(
                TopupRequest.source_type == source_type,
                TopupRequest.source_reference == reference,
                TopupRequest.status.in_([TopupStatus.AWAITING_SECOND_APPROVAL.value, TopupStatus.APPROVED.value]),
            )
        ).first()
        if duplicate is not None:
            raise DomainError(ErrorCode.TOPUP_REFERENCE_DUPLICATE)
        large = received_amount_minor > LARGE_AMOUNT_THRESHOLD_MINOR
        topup.source_type = source_type
        topup.source_reference = reference
        topup.received_amount_minor = received_amount_minor
        topup.received_at = received_at
        topup.first_approver_id = actor_user_id
        if large:
            TOPUP.assert_transition(topup.status, TopupStatus.AWAITING_SECOND_APPROVAL.value, "approve_first")
            topup.status = TopupStatus.AWAITING_SECOND_APPROVAL.value
            topup.version += 1
            topup.updated_at = now
            _flush_topup(session)
            _audit(session, actor_user_id, "topup_requests", topup.id, "topup_first_approved",
                   {"received_amount_minor": received_amount_minor, "source_type": source_type}, note)
            return topup
        TOPUP.assert_transition(topup.status, TopupStatus.APPROVED.value, "approve")
        return _post_topup(session, wallet, topup, actor_user_id=actor_user_id, second_approver_id=None, note=note)

    if topup.status == TopupStatus.AWAITING_SECOND_APPROVAL.value:
        if actor_user_id == topup.first_approver_id:
            raise DomainError(ErrorCode.SECOND_APPROVER_REQUIRED)
        mismatched = [
            name for name, expected, given in (
                ("source_type", topup.source_type, source_type),
                ("source_reference", topup.source_reference, reference),
                ("received_amount_minor", topup.received_amount_minor, received_amount_minor),
            ) if expected != given
        ]
        if mismatched:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "second_approval_mismatch", "fields": mismatched})
        TOPUP.assert_transition(topup.status, TopupStatus.APPROVED.value, "approve_second")
        return _post_topup(session, wallet, topup, actor_user_id=int(topup.first_approver_id),
                           second_approver_id=actor_user_id, note=note)

    TOPUP.assert_transition(topup.status, TopupStatus.APPROVED.value, "approve")
    raise AssertionError("unreachable")  # pragma: no cover


def _flush_topup(session: Session) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if constraint_name_of(exc) == "uq_topup_requests_source_reference" or sqlstate_of(exc) == "23505":
            raise DomainError(ErrorCode.TOPUP_REFERENCE_DUPLICATE) from exc
        raise


def _post_topup(session: Session, wallet: WalletAccount, topup: TopupRequest, *, actor_user_id: int,
                second_approver_id: int | None, note: str | None) -> TopupRequest:
    now = utc_now()
    amount = int(topup.received_amount_minor)
    cash = _system_account(session, SOURCE_TYPE_ACCOUNT[str(topup.source_type)], wallet.currency)
    transaction = _post_transaction(
        session,
        reference_kind="topup",
        source_type="topup_request",
        source_id=topup.id,
        reference_key=f"{topup.source_type}:{topup.source_reference}",
        description=f"top-up {format_public_id(PublicIdPrefix.TOPUP, topup.public_id)}",
        entries=[(cash.id, DEBIT, amount), (wallet.ledger_account_id, CREDIT, amount)],
        wallet_id=wallet.id,
        created_by=actor_user_id,
        second_approver_id=second_approver_id,
        evidence={"topup_id": topup.id, "received_at": to_iso_utc(_aware(topup.received_at)), "note": note},
        duplicate_error=ErrorCode.TOPUP_REFERENCE_DUPLICATE,
    )
    topup.status = TopupStatus.APPROVED.value
    topup.second_approver_id = second_approver_id
    topup.ledger_transaction_id = transaction.id
    topup.decided_at = now
    topup.version += 1
    topup.updated_at = now
    _touch(wallet, posted_delta=amount)
    _flush_topup(session)
    _audit(session, second_approver_id or actor_user_id, "topup_requests", topup.id, "topup_approved",
           {"received_amount_minor": amount, "ledger_transaction_id": transaction.id,
            "first_approver_id": topup.first_approver_id, "second_approver_id": second_approver_id}, note)
    enqueue_event(
        session,
        EventEnvelope(
            event_type=EventType.TOPUP_APPROVED,
            aggregate_type="topup",
            aggregate_public_id=format_public_id(PublicIdPrefix.TOPUP, topup.public_id),
            aggregate_version=topup.version,
            occurred_at=now,
            payload={"topup_id": format_public_id(PublicIdPrefix.TOPUP, topup.public_id),
                     "amount_minor": amount, "currency": wallet.currency},
        ),
        aggregate_id=topup.id,
    )
    return topup


def reject_topup(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    topup_id: int,
    expected_version: int,
    reason: str,
) -> TopupRequest:
    _require_capability(actor_capabilities, Capability.FINANCE_TOPUP_APPROVE)
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    _, topup = _lock_topup(session, topup_id)
    if topup.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": topup.version})
    TOPUP.assert_transition(topup.status, TopupStatus.REJECTED.value, "reject")
    now = utc_now()
    topup.status = TopupStatus.REJECTED.value
    topup.rejected_by = actor_user_id
    topup.reject_reason = reason.strip()
    topup.decided_at = now
    topup.version += 1
    topup.updated_at = now
    session.flush()
    _audit(session, actor_user_id, "topup_requests", topup.id, "topup_rejected", {}, reason)
    return topup


# --- commission policies -----------------------------------------------------------------------------


def _candidate(policy: CommissionPolicy) -> PolicyCandidate:
    return PolicyCandidate(
        id=policy.id,
        kind=CommissionPolicyKind(policy.kind),
        scope_corridor_id=policy.scope_corridor_id,
        scope_service_type=None if policy.scope_service_type is None else ServiceType(policy.scope_service_type),
        fee_bps=policy.fee_bps,
        effective_from=_aware(policy.effective_from),
        effective_to=_aware(policy.effective_to),
    )


def resolve_policy(
    session: Session, *, corridor_id: int | None, service_type: ServiceType | str | None, at: datetime | None = None
) -> CommissionPolicy:
    """Campaign beats standard; then the most specific scope (Q19, ADR-0009 §2)."""
    at = ensure_aware_utc(at or utc_now(), field="at")
    service = None if service_type is None else ServiceType(service_type).value
    rows = session.execute(
        select(CommissionPolicy).where(
            CommissionPolicy.effective_from <= at,
            or_(CommissionPolicy.effective_to.is_(None), CommissionPolicy.effective_to > at),
            or_(CommissionPolicy.scope_corridor_id.is_(None), CommissionPolicy.scope_corridor_id == corridor_id),
            or_(CommissionPolicy.scope_service_type.is_(None), CommissionPolicy.scope_service_type == service),
        )
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    chosen = select_policy((_candidate(row) for row in rows), corridor_id=corridor_id, service_type=service_type, at=at)
    if chosen is None:
        raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "no_commission_policy"})
    return by_id[chosen.id]


def quote_fee(
    session: Session,
    *,
    corridor_id: int | None,
    service_type: ServiceType | str,
    total_minor: int,
    at: datetime | None = None,
) -> FeeQuote:
    """Fee quote snapshotted on proposal versions (AC43): policy id, bps, commission, net."""
    validate_minor_amount(total_minor, name="total_minor")
    policy = resolve_policy(session, corridor_id=corridor_id, service_type=service_type, at=at)
    _require_confirmed_policy(session, policy)  # decision 28 (production only)
    commission = commission_minor(total_minor, policy.fee_bps)
    return FeeQuote(
        policy_id=policy.id,
        policy_public_id=format_public_id(PublicIdPrefix.COMMISSION_POLICY, policy.public_id),
        policy_kind=CommissionPolicyKind(policy.kind),
        fee_bps=policy.fee_bps,
        total_minor=total_minor,
        commission_minor=commission,
        net_minor=net_after_commission_minor(total_minor, policy.fee_bps),
    )


def current_global_standard(session: Session, at: datetime | None = None) -> CommissionPolicy | None:
    at = ensure_aware_utc(at or utc_now(), field="at")
    return session.execute(
        select(CommissionPolicy).where(
            CommissionPolicy.kind == CommissionPolicyKind.STANDARD.value,
            CommissionPolicy.scope_corridor_id.is_(None),
            CommissionPolicy.scope_service_type.is_(None),
            CommissionPolicy.effective_from <= at,
            or_(CommissionPolicy.effective_to.is_(None), CommissionPolicy.effective_to > at),
        ).order_by(CommissionPolicy.effective_from.desc())
    ).scalars().first()


def list_policies(
    session: Session,
    *,
    active_at: datetime | None = None,
    kind: CommissionPolicyKind | str | None = None,
    after_id: int | None = None,
    limit: int = 20,
) -> list[CommissionPolicy]:
    query = select(CommissionPolicy)
    if active_at is not None:
        at = ensure_aware_utc(active_at, field="active_at")
        query = query.where(CommissionPolicy.effective_from <= at,
                            or_(CommissionPolicy.effective_to.is_(None), CommissionPolicy.effective_to > at))
    if kind is not None:
        query = query.where(CommissionPolicy.kind == CommissionPolicyKind(kind).value)
    if after_id is not None:
        query = query.where(CommissionPolicy.id < after_id)
    return list(session.execute(query.order_by(CommissionPolicy.id.desc()).limit(limit)).scalars())


def _overlaps(session: Session, *, kind: str, corridor_id: int | None, service_type: str | None,
              start: datetime, end: datetime | None, exclude_id: int | None = None) -> bool:
    query = select(CommissionPolicy.id).where(
        CommissionPolicy.kind == kind,
        CommissionPolicy.scope_corridor_id.is_(None) if corridor_id is None else CommissionPolicy.scope_corridor_id == corridor_id,
        CommissionPolicy.scope_service_type.is_(None) if service_type is None else CommissionPolicy.scope_service_type == service_type,
        or_(CommissionPolicy.effective_to.is_(None), CommissionPolicy.effective_to > start),
    )
    if end is not None:
        query = query.where(CommissionPolicy.effective_from < end)
    if exclude_id is not None:
        query = query.where(CommissionPolicy.id != exclude_id)
    return session.execute(query.limit(1)).first() is not None


def _flush_policy(session: Session) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if sqlstate_of(exc) == "23P01":
            raise DomainError(ErrorCode.COMMISSION_POLICY_OVERLAP) from exc
        message = str(getattr(exc, "orig", exc))
        if "retroactive" in message:
            raise DomainError(ErrorCode.COMMISSION_POLICY_RETROACTIVE) from exc
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "policy_constraint"}) from exc


def _policy_event(session: Session, policy: CommissionPolicy, event_type: EventType, payload: dict[str, Any]) -> None:
    enqueue_event(
        session,
        EventEnvelope(
            event_type=event_type,
            aggregate_type="commission_policy",
            aggregate_public_id=format_public_id(PublicIdPrefix.COMMISSION_POLICY, policy.public_id),
            aggregate_version=policy.version,
            occurred_at=utc_now(),
            payload=payload,
        ),
        aggregate_id=policy.id,
    )


def create_policy(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    kind: CommissionPolicyKind | str,
    corridor_id: int | None,
    service_type: ServiceType | str | None,
    fee_bps: int,
    effective_from: datetime,
    effective_to: datetime | None,
    campaign_name: str | None,
    reason: str,
    corridor_public_id: str | None = None,
    now: datetime | None = None,
) -> CommissionPolicy:
    """Only ``finance.commission_policy_manage`` (super_admin, Q2). Immutable once written."""
    _require_capability(actor_capabilities, Capability.FINANCE_COMMISSION_POLICY_MANAGE)
    try:
        kind = CommissionPolicyKind(kind)
        service = None if service_type is None else ServiceType(service_type).value
        validate_policy_terms(kind, fee_bps, effective_from, effective_to)
    except (ValueError, TypeError) as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": str(exc)}) from exc
    if kind is CommissionPolicyKind.CAMPAIGN and not (campaign_name or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "campaign_name"})
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    now = ensure_aware_utc(now or utc_now())
    start = ensure_aware_utc(effective_from)
    end = None if effective_to is None else ensure_aware_utc(effective_to)
    if start < now - POLICY_CLOCK_TOLERANCE:
        raise DomainError(ErrorCode.COMMISSION_POLICY_RETROACTIVE)
    # BR #7: small clock skew is clamped to now; the DB trigger applies the same tolerance and clamp.
    start = max(start, now)
    if end is not None and end <= start:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "effective_to"})
    if _overlaps(session, kind=kind.value, corridor_id=corridor_id, service_type=service, start=start, end=end):
        raise DomainError(ErrorCode.COMMISSION_POLICY_OVERLAP)
    policy = CommissionPolicy(
        public_id=uuid.uuid4(),
        kind=kind.value,
        scope_corridor_id=corridor_id,
        scope_service_type=service,
        fee_bps=fee_bps,
        effective_from=start,
        effective_to=end,
        campaign_name=(campaign_name or "").strip() or None,
        reason=reason.strip(),
        created_by=actor_user_id,
        version=1,
    )
    session.add(policy)
    _flush_policy(session)
    session.refresh(policy, ["effective_from", "effective_to", "scope_key"])  # trigger clamp (BR #7)
    start = _aware(policy.effective_from)
    _audit(session, actor_user_id, "commission_policies", policy.id, "commission_policy_created",
           {"kind": kind.value, "fee_bps": fee_bps, "corridor_id": corridor_id, "service_type": service,
            "effective_from": to_iso_utc(start), "effective_to": None if end is None else to_iso_utc(end),
            "campaign_name": policy.campaign_name}, reason)
    _policy_event(session, policy, EventType.COMMISSION_POLICY_CREATED, {
        "policy_id": format_public_id(PublicIdPrefix.COMMISSION_POLICY, policy.public_id),
        "kind": kind.value,
        "fee_bps": fee_bps,
        "scope_corridor_id": corridor_public_id,
        "scope_service_type": service,
        "effective_from": to_iso_utc(start),
        "effective_to": None if end is None else to_iso_utc(end),
    })
    return policy


def end_policy(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    policy_id: int,
    expected_version: int,
    effective_to: datetime,
    reason: str,
    now: datetime | None = None,
    _allow_global_standard_end: bool = False,
) -> CommissionPolicy:
    """One-time end in the future, shortening only (ADR-0009 §1). Open bookings keep snapshots.

    The global standard cannot be ended here (BR #6): use ``replace_global_standard``, which starts
    the successor at the same instant. A deferred DB trigger enforces the same rule.
    """
    _require_capability(actor_capabilities, Capability.FINANCE_COMMISSION_POLICY_MANAGE)
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    now = ensure_aware_utc(now or utc_now())
    end = ensure_aware_utc(effective_to, field="effective_to")
    policy = session.execute(
        select(CommissionPolicy).where(CommissionPolicy.id == policy_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if policy is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if policy.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": policy.version})
    current_end = _aware(policy.effective_to)
    if policy.ended_by is not None or (current_end is not None and current_end <= now):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "commission_policy", "reason": "already_ended"})
    if end < now - POLICY_CLOCK_TOLERANCE:
        raise DomainError(ErrorCode.COMMISSION_POLICY_RETROACTIVE)
    end = max(end, now)  # BR #7 clamp (mirrors the trigger)
    if end <= _aware(policy.effective_from) or (current_end is not None and end > current_end):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "effective_to"})
    if _is_global_standard(policy) and not _allow_global_standard_end:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "commission_policy", "reason": "global_standard_requires_successor"})
    policy.effective_to = end
    policy.ended_by = actor_user_id
    policy.ended_reason = reason.strip()
    policy.version += 1
    policy.updated_at = now
    _flush_policy(session)
    # The trigger may clamp effective_to to the DB transaction time (BR #7); use the stored value.
    session.refresh(policy, ["effective_to"])
    end = _aware(policy.effective_to)
    _audit(session, actor_user_id, "commission_policies", policy.id, "commission_policy_ended",
           {"effective_to": to_iso_utc(end)}, reason)
    _policy_event(session, policy, EventType.COMMISSION_POLICY_ENDED, {
        "policy_id": format_public_id(PublicIdPrefix.COMMISSION_POLICY, policy.public_id),
        "effective_to": to_iso_utc(end),
    })
    return policy


def replace_global_standard(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    fee_bps: int,
    reason: str,
    effective_from: datetime | None = None,
    now: datetime | None = None,
) -> CommissionPolicy:
    """End the current global standard and start its successor at the same instant, atomically.

    The only way to end a global standard (BR #6). ``effective_from`` defaults to now (v1 PATCH,
    ADR-0009 §9) and may schedule a future switch; the current standard then ends at that instant.
    """
    _require_capability(actor_capabilities, Capability.FINANCE_COMMISSION_POLICY_MANAGE)
    if fee_bps == 0:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "zero_rate_requires_campaign"})
    now = ensure_aware_utc(now or utc_now())
    start = now if effective_from is None else ensure_aware_utc(effective_from, field="effective_from")
    if start < now - POLICY_CLOCK_TOLERANCE:
        raise DomainError(ErrorCode.COMMISSION_POLICY_RETROACTIVE)
    start = max(start, now)
    for _ in range(3):
        current = current_global_standard(session, start)
        if current is None:
            break
        locked = session.execute(
            select(CommissionPolicy).where(CommissionPolicy.id == current.id).with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        if locked.ended_by is not None:
            continue  # a concurrent replace ended it; re-resolve the new current policy
        if locked.fee_bps == fee_bps and effective_from is None:
            return locked
        if _aware(locked.effective_from) >= start:
            raise DomainError(ErrorCode.COMMISSION_POLICY_OVERLAP, details={"reason": "current_policy_not_started"})
        ended = end_policy(session, actor_user_id=actor_user_id, actor_capabilities=actor_capabilities,
                           policy_id=locked.id, expected_version=locked.version, effective_to=start, reason=reason,
                           now=now, _allow_global_standard_end=True)
        # The successor must start exactly where the stored (possibly DB-clamped) end is (deferred trigger).
        start = max(start, _aware(ended.effective_to))
        now = max(now, start) if effective_from is None else now
        break
    else:
        raise DomainError(ErrorCode.VERSION_CONFLICT)
    return create_policy(
        session,
        actor_user_id=actor_user_id,
        actor_capabilities=actor_capabilities,
        kind=CommissionPolicyKind.STANDARD,
        corridor_id=None,
        service_type=None,
        fee_bps=fee_bps,
        effective_from=start,
        effective_to=None,
        campaign_name=None,
        reason=reason,
        now=now,
    )


def confirm_policy(
    session: Session,
    *,
    actor_user_id: int,
    actor_capabilities: Collection[Capability | str],
    policy_id: int,
    expected_version: int,
    reason: str,
) -> CommissionPolicy:
    """Decision 28 (W19): a super_admin explicitly confirms the migration-seeded rate, once.

    Until then production quotes and holds on that policy fail. Alternatively a super_admin
    replaces it with a new standard (``replace_global_standard``).
    """
    _require_capability(actor_capabilities, Capability.FINANCE_COMMISSION_POLICY_MANAGE)
    if not reason or not reason.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    policy = session.execute(
        select(CommissionPolicy).where(CommissionPolicy.id == policy_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if policy is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if policy.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": policy.version})
    if policy.created_by is not None or policy.confirmed_by is not None:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                          details={"machine": "commission_policy", "reason": "not_an_unconfirmed_seed"})
    now = utc_now()
    policy.confirmed_by = actor_user_id
    policy.confirmed_at = now
    policy.version += 1
    policy.updated_at = now
    _flush_policy(session)
    _audit(session, actor_user_id, "commission_policies", policy.id, "commission_policy_confirmed",
           {"fee_bps": policy.fee_bps}, reason)
    return policy


# --- reads: ledger lines, reconciliation, account deletion --------------------------------------------


def list_ledger_lines(session: Session, *, wallet_id: int, before_entry_id: int | None = None, limit: int = 20) -> list[LedgerLine]:
    wallet = session.get(WalletAccount, wallet_id)
    if wallet is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    signed = func.sum(_signed_amount()).over(order_by=LedgerEntry.id)
    inner = (
        select(
            LedgerEntry.id.label("entry_id"),
            LedgerEntry.direction,
            LedgerEntry.amount_minor,
            LedgerEntry.created_at,
            LedgerEntry.transaction_id,
            signed.label("balance_after"),
        )
        .where(LedgerEntry.account_id == wallet.ledger_account_id)
        .subquery()
    )
    query = (
        select(inner, LedgerTransaction.public_id, LedgerTransaction.reference_kind, LedgerTransaction.reference_key)
        .join(LedgerTransaction, LedgerTransaction.id == inner.c.transaction_id)
        .order_by(inner.c.entry_id.desc())
        .limit(limit)
    )
    if before_entry_id is not None:
        query = query.where(inner.c.entry_id < before_entry_id)
    kind_map = {"topup": "topup", "commission_capture": "commission_capture",
                "commission_reversal": "reversal", "adjustment": "adjustment"}
    lines = []
    for row in session.execute(query).mappings():
        lines.append(LedgerLine(
            transaction_id=row["transaction_id"],
            transaction_public_id=format_public_id(PublicIdPrefix.LEDGER_TRANSACTION, row["public_id"]),
            occurred_at=_aware(row["created_at"]),
            kind=kind_map[row["reference_kind"]],
            direction=row["direction"],
            amount_minor=row["amount_minor"],
            balance_after_minor=int(row["balance_after"]),
            reference_kind=row["reference_kind"],
            reference_key=row["reference_key"],
            entry_id=row["entry_id"],
        ))
    return lines


def _signed_amount():
    """Liability view: credits increase a driver balance, debits decrease it."""
    return case((LedgerEntry.direction == CREDIT, LedgerEntry.amount_minor), else_=-LedgerEntry.amount_minor)


def reconcile(session: Session, *, run_date: date | None = None) -> ReconciliationReport:
    """Nightly check: wallet cache vs ledger, active holds, unbalanced transactions, overdraft wallets."""
    run_date = run_date or utc_now().date()
    report_env = assert_production_invariants(session)
    credit_sum = func.coalesce(func.sum(_signed_amount()), 0)
    ledger_by_account = dict(session.execute(select(LedgerEntry.account_id, credit_sum).group_by(LedgerEntry.account_id)).all())
    holds_by_wallet = dict(session.execute(
        select(WalletHold.wallet_id, func.sum(WalletHold.amount_minor))
        .where(WalletHold.status == HOLD_ACTIVE).group_by(WalletHold.wallet_id)
    ).all())
    # BR #8: the trigger-maintained running balance is compared with the full ledger sum here.
    running = None
    latest_entry: dict[int, int] = {}
    if session.get_bind().dialect.name == "postgresql":
        running = dict(session.execute(select(LedgerAccountBalance.account_id, LedgerAccountBalance.balance_minor)).all())
        # Wave 1.6 N1: the immutable running total on the latest entry of each driver account.
        latest_entry = dict(session.execute(text(
            "SELECT DISTINCT ON (account_id) account_id, running_balance_minor FROM ledger_entries "
            "WHERE account_seq IS NOT NULL ORDER BY account_id, account_seq DESC"
        )).all())
    mismatches: list[dict[str, Any]] = []
    overdraft: list[dict[str, Any]] = []
    wallets = session.execute(select(WalletAccount).order_by(WalletAccount.id)).scalars().all()
    for wallet in wallets:
        ledger_balance = int(ledger_by_account.get(wallet.ledger_account_id, 0))
        running_balance = None if running is None else int(running.get(wallet.ledger_account_id, 0))
        latest_running = None if running is None else int(latest_entry.get(wallet.ledger_account_id, 0) or 0)
        held = int(holds_by_wallet.get(wallet.id, 0) or 0)
        if (ledger_balance != wallet.posted_balance_minor or held != wallet.held_minor
                or (running_balance is not None and running_balance != ledger_balance)
                or (latest_running is not None and latest_running != ledger_balance)):
            mismatches.append({"wallet_id": wallet_public_id(wallet), "posted_minor": wallet.posted_balance_minor,
                               "ledger_minor": ledger_balance, "running_balance_minor": running_balance,
                               "latest_entry_running_minor": latest_running,
                               "held_minor": wallet.held_minor, "active_holds_minor": held})
        if wallet.test_overdraft_allowed:
            overdraft.append({"wallet_id": wallet_public_id(wallet)})
    debit_total = func.sum(case((LedgerEntry.direction == DEBIT, LedgerEntry.amount_minor), else_=0))
    credit_total = func.sum(case((LedgerEntry.direction == CREDIT, LedgerEntry.amount_minor), else_=0))
    unbalanced = [
        {"transaction_id": row.transaction_id, "currency": row.currency, "debit_minor": int(row.d), "credit_minor": int(row.c)}
        for row in session.execute(
            select(LedgerEntry.transaction_id, LedgerEntry.currency, debit_total.label("d"), credit_total.label("c"))
            .group_by(LedgerEntry.transaction_id, LedgerEntry.currency)
            .having(debit_total != credit_total)
        )
    ]
    orphans: list[dict[str, Any]] = []
    if session.get_bind().dialect.name == "postgresql" and session.execute(
        text("SELECT to_regprocedure('public.ledger_transaction_source_problem(bigint)') IS NOT NULL")
    ).scalar_one():
        orphans = [
            {"transaction_id": format_public_id(PublicIdPrefix.LEDGER_TRANSACTION, row.public_id), "problem": row.problem}
            for row in session.execute(text(
                "SELECT public_id, problem FROM (SELECT id, public_id, public.ledger_transaction_source_problem(id) "
                "AS problem FROM ledger_transactions) s WHERE problem IS NOT NULL ORDER BY id LIMIT 500"
            ))
        ]
    report = ReconciliationReport(run_date, len(wallets), mismatches, unbalanced, overdraft, report_env.is_production,
                                  orphans)
    details = {"mismatches": mismatches, "unbalanced_transactions": unbalanced, "overdraft_wallets": overdraft,
               "orphan_postings": orphans, "is_production": report_env.is_production}
    run = session.execute(select(ReconciliationRun).where(ReconciliationRun.run_date == run_date)).scalar_one_or_none()
    if run is None:
        session.add(ReconciliationRun(run_date=run_date, wallets_checked=len(wallets),
                                      mismatch_count=report.mismatch_count, details=details))
    else:
        run.wallets_checked = len(wallets)
        run.mismatch_count = report.mismatch_count
        run.details = details
        run.updated_at = utc_now()
    session.flush()
    return report


def run_reconciliation(session: Session, *, run_date: date | None = None) -> ReconciliationReport:
    """Worker entry point (BR #9; A7 schedules it). Computes and stores the run; caller commits."""
    return reconcile(session, run_date=run_date)


def blocking_state_for_user(session: Session, user_id: int, *, lock: bool = False) -> AccountBlockingState:
    """Wallet facts that must block v1/v2 account deletion (BR N4). Never writes.

    ``lock=True`` (wave 1.5 BR #10): locks the user's wallet rows ``FOR UPDATE`` (id ASC) so a
    concurrent top-up approval, hold or adjustment serializes with the deletion. Lock order:
    the caller has locked the user first (users -> wallet_accounts). Only *pending* top-ups and
    adjustment requests block; rejected or posted ones do not.
    """
    empty = AccountBlockingState(False, 0, 0, 0, 0, 0, 0)
    if not table_exists(session, WalletAccount.__tablename__):
        return empty
    query = select(WalletAccount).where(WalletAccount.driver_user_id == user_id).order_by(WalletAccount.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    wallets = session.execute(query).scalars().all()
    if not wallets:
        return empty
    ids = [w.id for w in wallets]
    active_holds = session.execute(
        select(func.count()).select_from(WalletHold).where(WalletHold.wallet_id.in_(ids), WalletHold.status == HOLD_ACTIVE)
    ).scalar_one()
    pending = session.execute(
        select(func.count(), func.coalesce(func.sum(TopupRequest.amount_minor), 0)).where(
            TopupRequest.wallet_id.in_(ids),
            TopupRequest.status.in_([TopupStatus.PENDING.value, TopupStatus.AWAITING_SECOND_APPROVAL.value]),
        )
    ).one()
    pending_adjustments = session.execute(
        select(func.count()).select_from(LedgerAdjustmentRequest).where(
            and_(LedgerAdjustmentRequest.wallet_id.in_(ids), LedgerAdjustmentRequest.status == ADJ_PENDING)
        )
    ).scalar_one()
    return AccountBlockingState(
        has_wallet=True,
        posted_balance_minor=sum(w.posted_balance_minor for w in wallets),
        held_minor=sum(w.held_minor for w in wallets),
        active_holds_count=int(active_holds),
        pending_topups_count=int(pending[0]),
        pending_topups_minor=int(pending[1]),
        pending_adjustments_count=int(pending_adjustments),
    )


# --- decision 30: split-adjustment signals (report only, no limit) -----------------------------------


@dataclass(frozen=True, slots=True)
class SplitAdjustmentSignal:
    wallet_id: int
    requested_by: int
    window_start: datetime
    window_end: datetime
    count: int
    amount_minor: int
    adjustment_request_ids: tuple[int, ...]


def split_adjustment_signals(
    session: Session,
    *,
    since: datetime,
    until: datetime,
    threshold_minor: int = TWO_PERSON_APPROVAL_THRESHOLD_MINOR,
) -> list[SplitAdjustmentSignal]:
    """Flag possible splitting around the two-person threshold. A signal, never a block.

    Per (wallet, requester), sub-threshold adjustment requests (posted or pending) inside a 24 h
    window form a signal when two or more of them sum above the threshold, or when there are
    ``SPLIT_SIGNAL_MIN_COUNT`` or more. Windows are maximal and do not overlap.
    """
    since = ensure_aware_utc(since, field="since")
    until = ensure_aware_utc(until, field="until")
    rows = session.execute(
        select(LedgerAdjustmentRequest)
        .where(
            LedgerAdjustmentRequest.created_at >= since - SPLIT_SIGNAL_WINDOW,
            LedgerAdjustmentRequest.created_at < until,
            LedgerAdjustmentRequest.amount_minor <= threshold_minor,
            LedgerAdjustmentRequest.status.not_in([ADJ_REJECTED, ADJ_WITHDRAWN]),
        )
        .order_by(LedgerAdjustmentRequest.wallet_id, LedgerAdjustmentRequest.requested_by,
                  LedgerAdjustmentRequest.created_at, LedgerAdjustmentRequest.id)
    ).scalars().all()
    signals: list[SplitAdjustmentSignal] = []
    for (wallet_id, requester), group in groupby(rows, key=lambda r: (r.wallet_id, r.requested_by)):
        items = list(group)
        times = [_aware(item.created_at) for item in items]
        i = 0
        while i < len(items):
            j = i
            while j + 1 < len(items) and times[j + 1] < times[i] + SPLIT_SIGNAL_WINDOW:
                j += 1
            window = items[i : j + 1]
            total = sum(item.amount_minor for item in window)
            if len(window) >= 2 and (total > threshold_minor or len(window) >= SPLIT_SIGNAL_MIN_COUNT) and times[j] >= since:
                signals.append(SplitAdjustmentSignal(
                    wallet_id=wallet_id, requested_by=requester, window_start=times[i], window_end=times[j],
                    count=len(window), amount_minor=total, adjustment_request_ids=tuple(item.id for item in window),
                ))
                i = j + 1
            else:
                i += 1
    return signals
