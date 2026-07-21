import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

_engine_kwargs = {
    # Neon is ~400ms RTT away: pre-ping added a full round trip to EVERY request.
    # Instead recycle connections well inside Neon's idle timeout (Prompt 18 speed fix).
    "pool_pre_ping": False,
    "pool_recycle": 280,
    # Prompt 18 load rehearsal: 300 concurrent users exhausted 10+20 conns on a
    # ~425ms-RTT Neon pooler (pgbouncer multiplexes these cheaply server-side).
    "pool_size": 40,
    "max_overflow": 110,
    "pool_timeout": 45,
}
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
