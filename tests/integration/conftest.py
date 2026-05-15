"""integration test 공용 fixture.

실제 PostgreSQL + (옵션) Gemini API 사용. 환경이 준비되지 않으면 자동 skip.
"""

from collections.abc import AsyncIterator

import psycopg
import pytest
import pytest_asyncio

from the_commons.settings import settings


def _probe_database() -> bool:
    """DB connection 가능 여부 — 모든 integration test의 skip 기준."""
    try:
        conn = psycopg.connect(settings.database_url, connect_timeout=2)
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


DATABASE_AVAILABLE = _probe_database()


requires_db = pytest.mark.skipif(
    not DATABASE_AVAILABLE,
    reason=(
        "PostgreSQL이 필요한 integration test. "
        "`docker compose up -d` + `uv run python -m the_commons.db.migrate` 후 다시 시도."
    ),
)

requires_gemini = pytest.mark.skipif(
    not settings.google_api_key,
    reason="GOOGLE_API_KEY 미설정 — Gemini integration test skip.",
)


@pytest_asyncio.fixture
async def clean_db_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    """매 test 전에 evidence/cluster/reciprocity/retirement 테이블 truncate."""
    conn = await psycopg.AsyncConnection.connect(settings.database_url, autocommit=True)
    try:
        async with conn.cursor() as cur:
            # 004 migration에서 cluster / evidence_cluster drop됨.
            # retirement_audit.cluster_id는 TEXT bucket label로 변경.
            await cur.execute(
                "TRUNCATE evidence, retirement_audit, reciprocity_event, "
                "recipe, heuristic_rule RESTART IDENTITY CASCADE"
            )
        yield conn
    finally:
        await conn.close()
