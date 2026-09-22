"""Deploy-time CLI for the DB environment marker (BR N1).

    python -m app.modules.platform.environment show
    python -m app.modules.platform.environment set production --by "deploy:2026-09-20:temur"

Uses ``ELCHI_DATABASE_URL``. Setting ``production`` fails (DB trigger) while any wallet
has ``test_overdraft_allowed = true``; leaving ``production`` always fails.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import DBAPIError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.platform.environment")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    setter = sub.add_parser("set")
    setter.add_argument("environment", choices=["production", "staging", "development", "test"])
    setter.add_argument("--by", required=True, help="who/what sets the marker (audit)")
    setter.add_argument("--note", default=None)
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal
    from app.modules.platform.service import app_environment, get_db_environment, set_db_environment

    with SessionLocal() as session:
        if args.command == "show":
            db_env = get_db_environment(session)
            try:
                app_value = app_environment().value
            except ValueError as exc:  # outside the allowlist: reported, never mapped to development
                app_value = f"<invalid: {exc}>"
            print(f"database marker: {db_env.value if db_env else '<missing>'}; app settings: {app_value}")
            return 0 if db_env is not None and not app_value.startswith("<invalid") else 1
        try:
            env = set_db_environment(session, args.environment, set_by=args.by, note=args.note)
            session.commit()
        except DBAPIError as exc:
            session.rollback()
            print(f"refused: {getattr(exc, 'orig', exc)}", file=sys.stderr)
            return 2
        print(f"database marker set to {env.value}")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
