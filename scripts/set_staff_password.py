"""Create a staff account, or set the username/password of an existing one.

Staff sign in at /api/v1/auth/staff-login with a username and password; only
clients and drivers use SMS OTP.

    python scripts/set_staff_password.py --username admin --role super_admin
    python scripts/set_staff_password.py --username admin --password 'S3cret!'

The password is prompted for (hidden) when --password is omitted, which keeps
it out of your shell history. --phone is only needed when creating a brand new
account, since users.phone is NOT NULL.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers mappers)
from app.core.config import settings
from app.core.security import hash_password
from app.models import User
from app.services.auth_service import STAFF_ROLES, normalize_phone, normalize_username

MIN_PASSWORD_LENGTH = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a staff login")
    parser.add_argument("--username", required=True, help="Login name, case-insensitive")
    parser.add_argument("--password", help="Omit to be prompted without echo")
    parser.add_argument(
        "--role",
        default="super_admin",
        choices=sorted(STAFF_ROLES),
        help="Only used when creating a new account (default: super_admin)",
    )
    parser.add_argument("--phone", help="Required only when creating a new account")
    return parser.parse_args()


def resolve_password(supplied: str | None) -> str:
    password = supplied or getpass.getpass("Password: ")
    if not supplied:
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode("utf-8")) > 72:
        raise SystemExit("Password must be at most 72 bytes (bcrypt limit)")
    return password


def main() -> None:
    args = parse_args()
    username = normalize_username(args.username)
    if len(username) < 3:
        raise SystemExit("Username must be at least 3 characters")
    password = resolve_password(args.password)

    engine = create_engine(settings.database_url)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        user = db.scalar(select(User).where(User.username == username))
        if user is None and args.phone:
            # Allow attaching a username to an account that already exists by phone.
            normalized_phone = normalize_phone(args.phone)
            if not isinstance(normalized_phone, str):
                raise SystemExit("Invalid Uzbekistan phone number")
            user = db.scalar(select(User).where(User.phone == normalized_phone))

        if user is None:
            if not args.phone:
                raise SystemExit("No such staff user. Pass --phone to create a new account.")
            user = User(
                phone=normalize_phone(args.phone),
                username=username,
                role=args.role,
                status="active",
                is_phone_verified=True,
            )
            db.add(user)
            action = "Created"
        else:
            if user.role not in STAFF_ROLES:
                raise SystemExit(
                    f"User {user.phone} has role '{user.role}'. Refusing to set a staff "
                    "password on a client or driver account."
                )
            user.username = username
            user.status = "active"
            action = "Updated"

        user.password_hash = hash_password(password)
        db.add(user)
        db.commit()
        print(f"{action} staff login: {username} ({user.role}, {user.phone})")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
