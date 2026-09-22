"""List what must be closed before a phone leaves the store-review allowlist.

Decision 39: removing a phone from ELCHI_REVIEW_LOGIN_PHONES turns that account
into a normal user. Any order, active bid or open dispute it still has would
then become visible to real users. Close them first (admin cancel, dispute
resolution), re-run this check until it reports nothing, then edit the
allowlist.

Read-only. Exit code 0 when nothing is open, 1 otherwise.

    python scripts/check_review_account_orders.py              # every allowlisted phone
    python scripts/check_review_account_orders.py +998900000010
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401  (registers mappers)
from app.core.config import settings  # noqa: E402
from app.services.auth_service import normalize_phone  # noqa: E402
from app.services.review_accounts import review_account_open_items, review_account_phones  # noqa: E402


def main(argv: list[str]) -> int:
    if argv:
        phones = []
        for raw in argv:
            normalized = normalize_phone(raw)
            if not isinstance(normalized, str):
                print(f"Not a valid Uzbekistan number: {raw}")
                return 2
            phones.append(normalized)
    else:
        phones = sorted(review_account_phones())
        if not phones:
            print("ELCHI_REVIEW_LOGIN_PHONES is empty; nothing to check.")
            return 0

    engine = create_engine(settings.database_url)
    db = sessionmaker(bind=engine)()
    blocking = False
    try:
        for phone in phones:
            items = review_account_open_items(db, phone)
            open_count = len(items["open_orders"]) + len(items["active_bids"]) + len(items["open_disputes"])
            print(f"{phone} (user_id={items['user_id']}): {open_count} open item(s)")
            for key in ("open_orders", "active_bids", "open_disputes"):
                for row in items[key]:
                    print(f"  {key[:-1]}: {row}")
            blocking = blocking or open_count > 0
    finally:
        db.close()
        engine.dispose()
    if blocking:
        print("\nClose the items above before removing these phones from ELCHI_REVIEW_LOGIN_PHONES.")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
