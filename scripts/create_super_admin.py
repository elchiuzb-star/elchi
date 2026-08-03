from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models
from app.core.config import settings
from app.models import User
from app.services.auth_service import normalize_phone


def main() -> None:
    raw_phone = settings.super_admin_phone or input("Super admin phone: ").strip()
    normalized_phone = normalize_phone(raw_phone)
    if not isinstance(normalized_phone, str):
        raise SystemExit("Invalid Uzbekistan phone number")

    engine = create_engine(settings.database_url)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_factory()
    try:
        existing = db.scalar(select(User).where(User.phone == normalized_phone))
        if existing is not None:
            print(f"User already exists: {existing.phone} ({existing.role})")
            return
        user = User(
            phone=normalized_phone,
            role="super_admin",
            status="active",
            is_phone_verified=True,
        )
        db.add(user)
        db.commit()
        print(f"Created super_admin: {normalized_phone}")
        print(
            "This account has no login yet — staff cannot use SMS OTP. Set one with:\n"
            f"  python scripts/set_staff_password.py --username <name> --phone {normalized_phone}"
        )
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
