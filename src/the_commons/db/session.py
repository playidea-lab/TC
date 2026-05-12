"""PostgreSQL async connection pool. pgvector type adapter 등록 포함."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from the_commons.settings import settings

_pool: AsyncConnectionPool | None = None


async def _configure(conn: psycopg.AsyncConnection) -> None:
    """connection 초기화 — pgvector 타입 어댑터 등록."""
    await register_vector_async(conn)


async def init_pool() -> AsyncConnectionPool:
    """Async connection pool을 lazy-init.

    이미 초기화돼 있으면 기존 인스턴스 반환.
    """
    global _pool
    if _pool is not None:
        return _pool

    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=10,
        open=False,
        configure=_configure,
    )
    await _pool.open()
    return _pool


async def close_pool() -> None:
    """앱 종료 시 호출. pool 자원 정리."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_connection() -> AsyncIterator[psycopg.AsyncConnection]:
    """connection 컨텍스트 매니저. async with로 사용."""
    pool = await init_pool()
    async with pool.connection() as conn:
        yield conn
