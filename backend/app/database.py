import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

_engine_kwargs = {"pool_pre_ping": True}
if os.environ.get("TESTING"):
    _engine_kwargs = {"poolclass": NullPool}

# Managed poolers (Neon pgbouncer) require disabling asyncpg's prepared-statement cache,
# and pinning search_path (pooled server conns can leak session state like search_path='').
_connect_args = {}
if "-pooler" in settings.database_url or "neon.tech" in settings.database_url:
    _connect_args["statement_cache_size"] = 0
    _connect_args["server_settings"] = {"search_path": "public"}

engine = create_async_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
