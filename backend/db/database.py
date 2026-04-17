import os
import logging
from sqlalchemy import text
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()

# Engine and session are lazily initialized on first call to init_db()
# so that module-level import doesn't fail if aiosqlite isn't installed yet.
_engine = None
_AsyncSessionLocal = None

def _get_engine():
    global _engine
    if _engine is None:
        raw = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///alpaca_quant.db")
        # Auto-fix plain sqlite:// to async dialect
        if raw.startswith("sqlite://") and "aiosqlite" not in raw:
            raw = raw.replace("sqlite://", "sqlite+aiosqlite://", 1)
        _engine = create_async_engine(raw, echo=False)
    return _engine

def _get_session_factory():
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(_get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _AsyncSessionLocal

async def get_db():
    async with _get_session_factory()() as session:
        yield session

async def _get_existing_columns(conn, table_name: str) -> set[str]:
    result = await conn.execute(text(f"PRAGMA table_info(\"{table_name}\")"))
    return {row[1] for row in result.fetchall()}


def _compile_column_type(column) -> str:
    return column.type.compile(dialect=sqlite_dialect.dialect())


async def _add_missing_columns(conn):
    columns_added: list[str] = []
    for table in Base.metadata.sorted_tables:
        table_name = table.name
        existing = await _get_existing_columns(conn, table_name)
        missing = [col for col in table.columns if col.name not in existing]
        if not missing:
            continue

        for column in missing:
            coltype = _compile_column_type(column)
            ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {coltype}'

            if not column.nullable:
                default_clause = None
                if column.default is not None and hasattr(column.default, 'arg'):
                    default_val = column.default.arg
                    if isinstance(default_val, str):
                        default_clause = f"DEFAULT '{default_val}'"
                    else:
                        default_clause = f"DEFAULT {default_val}"
                elif column.server_default is not None:
                    default_clause = str(column.server_default.arg)

                if default_clause is None:
                    logger.warning(
                        "[DB] Cannot add non-nullable column %s.%s without default; skipping",
                        table_name, column.name
                    )
                    continue

                ddl = f"{ddl} NOT NULL {default_clause}"

            await conn.execute(text(ddl))
            columns_added.append(f"{table_name}.{column.name}")
            logger.info("[DB] Added missing column %s.%s", table_name, column.name)

    if columns_added:
        logger.info("[DB] Schema migration complete. Added columns: %s", ", ".join(columns_added))
    else:
        logger.info("[DB] Schema migration complete. No missing columns found.")


async def init_db():
    """Creates all ORM tables. Called once during FastAPI startup."""
    import db.models  # noqa: F401 — SignalRecord, ExecutionRecord, BotAmend
    engine = _get_engine()
    async with engine.begin() as conn:
        logger.info("[DB] Initializing schema at: %s", engine.url)
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)
