"""Database engine, session factory and portable helpers (PostgreSQL in production, SQLite in tests)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, TypeDecorator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime given; use UTC-aware datetimes")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def configure(url: str) -> AsyncEngine:
    global _engine, _sessions
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {}
    _engine = create_async_engine(url, **kwargs)
    _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def engine() -> AsyncEngine:
    if _engine is None:
        from .config import get_settings

        configure(get_settings().database_url)
    return _engine


def sessions() -> async_sessionmaker[AsyncSession]:
    engine()
    return _sessions


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessions()() as s:
        yield s


async def create_all() -> None:
    """Tests / local SQLite only. Production schema is managed by Alembic migrations."""
    from . import models  # noqa: F401  (register tables)

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def upsert(session: AsyncSession, table, rows: Iterable[Mapping], keys: list[str],
           update: list[str] | None = None):
    """INSERT … ON CONFLICT (keys) DO UPDATE/NOTHING, on PostgreSQL or SQLite."""
    rows = list(rows)
    if not rows:
        return None
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(table).values(rows)
    if update:
        stmt = stmt.on_conflict_do_update(index_elements=keys,
                                          set_={c: getattr(stmt.excluded, c) for c in update})
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=keys)
    return session.execute(stmt)
