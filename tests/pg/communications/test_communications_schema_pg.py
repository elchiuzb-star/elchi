"""0059 schema: ORM drift, idempotent re-run, ``chat_message_immutable`` guard (A7)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.v2.web import db_error_to_domain_error
from app.contracts.errors import ErrorCode
from app.modules.platform.service import constraint_name_of
from tests.pg.communications.conftest import accepted_deal, post
from tests.pg.conftest import PgDatabase, run_alembic, script_heads

pytestmark = pytest.mark.pg


def test_communications_models_match_migrated_schema(pg_db: PgDatabase) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401
    import app.modules.bookings.models  # noqa: F401
    import app.modules.communications.models  # noqa: F401
    import app.modules.marketplace.models  # noqa: F401
    from app.db.base import Base
    from app.modules.communications.models import COMMUNICATIONS_TABLES

    def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
        if type_ == "table" and reflected and compare_to is None:
            return name in Base.metadata.tables
        return True

    with pg_db.engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_object": include_object, "compare_type": True, "compare_server_default": False}
        )
        diffs = compare_metadata(context, Base.metadata)

    def touches(diff: object) -> bool:
        for item in diff if isinstance(diff, list) else [diff]:
            for part in item:
                table = getattr(part, "table", None)
                name = getattr(table, "name", None) or getattr(part, "name", None)
                if name in COMMUNICATIONS_TABLES or part in COMMUNICATIONS_TABLES:
                    return True
        return False

    ours = [diff for diff in diffs if touches(diff)]
    assert ours == [], "\n".join(map(repr, ours))


def test_0059_upgrade_is_idempotent(pg_db: PgDatabase) -> None:
    heads = script_heads()
    assert len(heads) == 1, heads

    def snapshot() -> tuple:
        with pg_db.engine.connect() as conn:
            return (
                conn.execute(text("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                  "WHERE table_schema = 'public' ORDER BY 1, 2")).all(),
                conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")).all(),
                conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1")).all(),
                conn.execute(text("SELECT conname FROM pg_constraint ORDER BY 1")).all(),
            )

    before = snapshot()
    assert run_alembic(pg_db.url, "upgrade", "head").returncode == 0
    assert snapshot() == before
    stamp = run_alembic(pg_db.url, "stamp", "20260916_0058")
    assert stamp.returncode == 0, stamp.stdout + stamp.stderr
    again = run_alembic(pg_db.url, "upgrade", "20260916_0059")
    assert again.returncode == 0, again.stdout + again.stderr
    restore = run_alembic(pg_db.url, "stamp", heads[0])
    assert restore.returncode == 0, restore.stdout + restore.stderr
    assert snapshot() == before


def test_chat_message_content_is_immutable_in_the_database(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    posted, _ = post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="Salom, bekatdaman")
    message_id = posted.message.id

    for statement in (
        "UPDATE chat_messages SET text = 'tampered' WHERE id = :id",
        "UPDATE chat_messages SET author_side = 'driver' WHERE id = :id",
        "UPDATE chat_messages SET contact_filter_categories = '{\"phone\": 1}'::jsonb WHERE id = :id",
        "DELETE FROM chat_messages WHERE id = :id",
    ):
        with pytest.raises(DBAPIError) as info:
            with bw.db.engine.begin() as conn:
                conn.execute(text(statement), {"id": message_id})
        assert constraint_name_of(info.value) == "chat_message_immutable"
        mapped = db_error_to_domain_error(info.value)
        assert mapped.code is ErrorCode.INTEGRITY_CONFLICT and mapped.details == {"reason": "chat_message_immutable"}

    with bw.db.engine.begin() as conn:  # moderation columns are the only mutable ones
        conn.execute(text("UPDATE chat_messages SET moderation_status = 'hidden_by_staff', moderated_at = now() WHERE id = :id"),
                     {"id": message_id})
        assert conn.execute(text("SELECT text FROM chat_messages WHERE id = :id"), {"id": message_id}).scalar() == "Salom, bekatdaman"

    with pytest.raises(DBAPIError):
        with bw.db.engine.begin() as conn:
            conn.execute(text("UPDATE chat_messages SET attachment_file_id = 1 WHERE id = :id"), {"id": message_id})
