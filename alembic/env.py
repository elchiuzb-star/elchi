import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.modules import import_models

# Register every wired v2 model so target_metadata (and the ORM drift check) covers them.
import_models()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Decision Q36: migrations run as the owner/migrator role when ELCHI_MIGRATION_DATABASE_URL is
# set; the app keeps its NOSUPERUSER role in ELCHI_DATABASE_URL. Unset -> previous behaviour.
MIGRATION_DATABASE_URL = (os.environ.get("ELCHI_MIGRATION_DATABASE_URL") or "").strip() or settings.database_url

# ConfigParser interpolation: escape '%' so URL-encoded passwords survive set_main_option.
config.set_main_option("sqlalchemy.url", MIGRATION_DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata

# BR finding #21: one migration runner at a time on PostgreSQL (session-level advisory lock).
# Constant key "elchimig" (shared with A10a ops tooling); SQLite and other dialects skip it.
MIGRATION_ADVISORY_LOCK_KEY = 0x656C636869_6D6967



LINEAGE_TABLE = "alembic_revision_lineage"


def record_revision_lineage(connection) -> None:  # noqa: ANN001 - SQLAlchemy Connection
    """Q50: persist the migration graph (revision -> parent) this runner ships with.

    Readiness (decision 32) must tell "the database is ahead of me, but safely so" from "I do not know this
    schema at all". An image can only walk its own script files, so after a rollback it cannot recognise a newer
    revision and has to answer 503. With the lineage in the database, any image reads the chain from the DB
    instead - so this writes every edge it knows, not only the ones applied right now, and skips silently when
    the table does not exist yet (older schema) or the role may not write it.
    """
    if connection.dialect.name != "postgresql":
        return
    try:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(config)
        edges: list[tuple[str, str | None]] = []
        for entry in script.walk_revisions("base", "heads"):
            parents = entry.down_revision
            if parents is None:
                edges.append((entry.revision, None))
            elif isinstance(parents, str):
                edges.append((entry.revision, parents))
            else:
                edges.extend((entry.revision, parent) for parent in parents)
        if not edges:
            return
        exists = connection.execute(text("SELECT to_regclass('public.' || :name)"), {"name": LINEAGE_TABLE}).scalar()
        if exists is None:
            return
        connection.execute(
            text(
                f"INSERT INTO public.{LINEAGE_TABLE} (revision, down_revision) "
                "VALUES (:revision, :down_revision) ON CONFLICT DO NOTHING"
            ),
            [{"revision": revision, "down_revision": parent} for revision, parent in edges],
        )
        connection.commit()
    except Exception as exc:  # noqa: BLE001 - never fail a migration run over bookkeeping
        print(f"alembic/env.py: revision lineage not recorded ({exc.__class__.__name__}: {exc})")


def run_migrations_offline() -> None:
    context.configure(
        url=MIGRATION_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        use_lock = connection.dialect.name == "postgresql"
        if use_lock:
            # Blocks until any concurrent runner finishes; committed so the migration transaction
            # below starts clean (the lock is session-level and survives the commit).
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_ADVISORY_LOCK_KEY})
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
            # Q50: the graph is recorded after the migrations committed, in its own transaction.
            record_revision_lineage(connection)
        finally:
            if use_lock:
                if connection.in_transaction():
                    connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_ADVISORY_LOCK_KEY})
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
