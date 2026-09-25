"""ADR-0026 (Q147, D-4): read-only count of promo enrollments affected by the retired parcel proofs.

Uses the app's own database settings. Opens a READ ONLY transaction and prints only the environment name, whether the
host is local, the migration revision and counts - never a URL, credential, id or personal data. By default it refuses
a non-local host; `--allow-remote` is for an operator who is authorised to read that database.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import settings  # noqa: E402

url = make_url(settings.database_url)
local = (url.host or "") in {"localhost", "127.0.0.1", "::1"} and url.get_backend_name() == "postgresql"
print(f"environment={settings.environment} backend={url.get_backend_name()} local_host={local}")
if not local and "--allow-remote" not in sys.argv:
    raise SystemExit("not a local PostgreSQL database - not connecting (use --allow-remote only when authorised)")
engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
try:
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"alembic_revision={revision}")
        if conn.execute(text("SELECT to_regclass('public.promo_enrollments')")).scalar() is None:
            print("promo_enrollments: table absent (promotions migrations not applied here)")
        else:
            for row in conn.execute(text(
                    "SELECT service_type, status, count(*) FROM promo_enrollments GROUP BY 1, 2 ORDER BY 1, 2")):
                print(f"enrollments service={row[0]} status={row[1]} count={row[2]}")
            total = conn.execute(text(
                "SELECT count(*) FROM promo_enrollments WHERE service_type = 'parcel' AND status = 'promised'")).scalar()
            print(f"affected (parcel, promised) = {total}")
        conn.rollback()
finally:
    engine.dispose()
