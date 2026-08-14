"""Create the two accounts an app-store reviewer signs in with.

Reviewers cannot receive an SMS to an Uzbek number, so both accounts are on the
ELCHI_REVIEW_LOGIN_PHONES allowlist and accept ELCHI_REVIEW_LOGIN_OTP instead of
a real code. The driver is created already approved — a reviewer who lands on a
"documents pending" wall sees none of the app and rejects the submission.

    python scripts/seed_review_accounts.py

Set both env vars first, e.g. in .env.production:

    ELCHI_REVIEW_LOGIN_PHONES=+998900000010,+998900000011
    ELCHI_REVIEW_LOGIN_OTP=4321
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers mappers)
from app.core.config import settings
from app.models import ClientProfile, DriverProfile, User
from app.services.auth_service import normalize_phone

CLIENT_NAME = "Play Review Client"
DRIVER_NAME = "Play Review Driver"


def upsert_user(db, phone: str, role: str, full_name: str) -> User:
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(phone=phone, role=role)
        db.add(user)
    user.role = role
    user.status = "active"
    user.is_phone_verified = True
    user.full_name = full_name
    db.add(user)
    db.flush()
    return user


def main() -> None:
    raw = [p.strip() for p in settings.review_login_phones.split(",") if p.strip()]
    if len(raw) < 2:
        raise SystemExit(
            "Set ELCHI_REVIEW_LOGIN_PHONES to two numbers (client,driver) first."
        )
    if not settings.review_login_otp:
        raise SystemExit("Set ELCHI_REVIEW_LOGIN_OTP first.")

    phones = []
    for value in raw[:2]:
        normalized = normalize_phone(value)
        if not isinstance(normalized, str):
            raise SystemExit(f"Not a valid Uzbekistan number: {value}")
        phones.append(normalized)

    client_phone, driver_phone = phones

    engine = create_engine(settings.database_url)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        client = upsert_user(db, client_phone, "client", CLIENT_NAME)
        if db.scalar(select(ClientProfile).where(ClientProfile.user_id == client.id)) is None:
            db.add(ClientProfile(user_id=client.id))

        driver = upsert_user(db, driver_phone, "driver", DRIVER_NAME)
        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == driver.id))
        if profile is None:
            profile = DriverProfile(user_id=driver.id)
            db.add(profile)
        # Pre-approved so the reviewer sees the working driver app rather than
        # a verification queue.
        profile.full_name = DRIVER_NAME
        profile.verification_status = "approved"
        profile.is_available = True
        profile.car_model = "Chevrolet Cobalt"
        profile.car_color = "Oq"
        profile.plate_number = "01A999AA"
        profile.plate_number_normalized = "01A999AA"
        db.add(profile)

        db.commit()

        print("Review accounts ready. Give these to the store reviewer:\n")
        print(f"  Client  {client_phone}   code {settings.review_login_otp}")
        print(f"  Driver  {driver_phone}   code {settings.review_login_otp}")
        print("\nClear ELCHI_REVIEW_LOGIN_* once the app is approved.")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
