import os
import logging
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

async def init_db():
    """Creates all ORM tables. Called once during FastAPI startup."""
    import db.models  # noqa: F401 — registers models with Base.metadata
    engine = _get_engine()
    async with engine.begin() as conn:
        logger.info("[DB] Initializing schema at: %s", engine.url)
        await conn.run_sync(Base.metadata.create_all)
