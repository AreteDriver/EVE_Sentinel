"""Async database session management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings
from backend.database.models import Base


def _get_async_url(url: str) -> str:
    """Convert sqlite:/// to sqlite+aiosqlite:///"""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


# Global engine and session factory (initialized on startup)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """
    Initialize database engine and create tables.

    Called during application startup.
    """
    global _engine, _session_factory

    async_url = _get_async_url(settings.database_url)

    _engine = create_async_engine(
        async_url,
        echo=False,  # Set True for SQL debugging
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections. Called during shutdown."""
    global _engine, _session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Get an async database session.

    Usage:
        async with get_session() as session:
            repo = ReportRepository(session)
            report = await repo.get_by_id(...)
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_session_dependency() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency for database sessions.

    Usage in endpoints:
        async def my_endpoint(session: AsyncSession = Depends(get_session_dependency)):
            ...
    """
    async with get_session() as session:
        yield session
