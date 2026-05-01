"""
Alembic migration environment.

Pulls the database URL from config.settings so no credentials are hardcoded.
Strips the +aiosqlite async driver prefix for the synchronous migration context —
Alembic does not need async; the application uses aiosqlite at runtime only.
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure backend/ is on sys.path so project imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.database import Base         # noqa: E402
import db.models  # noqa: F401 — registers all ORM models with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_DEFAULT_DB_URL = "sqlite:///./alpaca_quant.db"


def _sync_url() -> str:
    """Return a sync-dialect URL for Alembic.

    Tries to load settings but falls back to the default SQLite path when
    required credentials (Alpaca keys) are not present in the environment —
    migrations only need the database URL, not trading credentials.
    """
    try:
        from config import settings  # noqa: PLC0415
        url = settings.database_url
    except Exception:
        url = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)
    return url.replace("+aiosqlite", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,   # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,   # required for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
