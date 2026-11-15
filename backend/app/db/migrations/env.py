from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  (registers all tables)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import make_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection") or make_engine(_url())
    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    # SQLite batch migrations recreate tables (copy + DROP + RENAME). With foreign keys ON, the
    # DROP of a referenced table would cascade or fail, so disable them for the migration. The
    # PRAGMA is a no-op inside a transaction: run it on the raw DBAPI connection before BEGIN.
    sqlite = connection.dialect.name == "sqlite"
    if not sqlite:
        _migrate(connection)
        return
    raw = connection.connection.dbapi_connection
    raw.execute("PRAGMA foreign_keys=OFF")
    if raw.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
        # A transaction was already open: table rebuilds would fire ON DELETE CASCADE/SET NULL.
        raise RuntimeError("Cannot disable SQLite foreign keys (open transaction?); refusing to migrate")
    try:
        _migrate(connection)
    finally:
        raw.execute("PRAGMA foreign_keys=ON")
    # Only reached when the migration succeeded, so a failure is never masked.
    violations = raw.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"Foreign key violations after migration: {violations[:5]}")


def _migrate(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite ALTER TABLE support
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
