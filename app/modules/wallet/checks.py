"""Read-only pre-deploy checks and worker entry points for the wallet (decision 29, BR #9).

    python -m app.modules.wallet.checks legacy-rate
        Exit 0: system_settings.driver_commission_rate converts exactly to a positive bps rate
        (or is absent -> 15% default). Exit 1: migration 0036 would refuse it. Exit 2: DB unreadable.
        Read-only; safe for A10a's pre-deploy check against the production database.

    python -m app.modules.wallet.checks reconcile [--date YYYY-MM-DD]
        Worker/ops entry point: computes and stores the reconciliation run for the date (A7 schedules
        it later). Exit 0 when clean, 1 when mismatches were found.

Uses ``ELCHI_DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.orm import Session

LEGACY_DEFAULT_RATE = Decimal("0.15")


class LegacyRateError(ValueError):
    """The legacy rate cannot become the global standard policy (0036 would stop)."""


def parse_legacy_rate(raw: str | None) -> int:
    """Same rule as migration 0036 ``_parse_legacy_rate``: exact whole bps, 1..10000; None -> 1500."""
    try:
        rate = LEGACY_DEFAULT_RATE if raw is None else Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise LegacyRateError(f"driver_commission_rate={raw!r} is not a decimal") from exc
    if not rate.is_finite():
        raise LegacyRateError(f"driver_commission_rate={raw!r} is not a decimal")
    scaled = rate * 10000
    if scaled != scaled.to_integral_value() or not (0 <= scaled <= 10000):
        raise LegacyRateError(f"driver_commission_rate={raw!r} is not a whole bps rate")
    bps = int(scaled)
    if bps == 0:
        raise LegacyRateError("driver_commission_rate is 0; a standard policy cannot be 0 bps (Q1)")
    return bps


def read_legacy_rate(session: Session) -> str | None:
    present = session.execute(text("SELECT to_regclass('public.system_settings') IS NOT NULL")).scalar_one()
    if not present:
        return None
    return session.execute(
        text("SELECT value FROM system_settings WHERE key = 'driver_commission_rate'")
    ).scalar_one_or_none()


def check_legacy_rate(session: Session) -> tuple[bool, str]:
    raw = read_legacy_rate(session)
    try:
        bps = parse_legacy_rate(raw)
    except LegacyRateError as exc:
        return False, str(exc)
    source = "default (no row)" if raw is None else f"value {raw!r}"
    return True, f"legacy rate {source} -> {bps} bps"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.wallet.checks")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("legacy-rate")
    rec = sub.add_parser("reconcile")
    rec.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal

    if args.command == "legacy-rate":
        try:
            with SessionLocal() as session:
                ok, message = check_legacy_rate(session)
                session.rollback()
        except Exception as exc:  # noqa: BLE001 - reported as "cannot check"
            print(f"cannot check: {exc}", file=sys.stderr)
            return 2
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    from app.modules.wallet.service import run_reconciliation

    with SessionLocal() as session:
        report = run_reconciliation(session, run_date=args.date)
        session.commit()
    print(json.dumps({"date": report.run_date.isoformat(), "wallets_checked": report.wallets_checked,
                      "mismatch_count": report.mismatch_count}))
    return 0 if report.mismatch_count == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
