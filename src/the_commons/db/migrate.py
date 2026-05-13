"""SQL 마이그레이션 적용 스크립트.

`migrations/*.sql` 파일을 알파벳 순으로 적용한다. 이미 적용된 파일은
`schema_migration` 테이블 기록을 참고해 skip한다.

실행: `uv run python -m the_commons.db.migrate`
"""

import asyncio
import logging
from pathlib import Path

import psycopg

from the_commons.settings import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _applied_filenames(conn: psycopg.AsyncConnection) -> set[str]:
    """이미 적용된 마이그레이션 파일명 집합. 테이블 없으면 빈 set."""
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT filename FROM schema_migration")
            rows = await cur.fetchall()
            return {row[0] for row in rows}
    except psycopg.errors.UndefinedTable:
        # 트랜잭션 abort 상태 회복 — autocommit이라면 영향 없음
        await conn.rollback()
        return set()


async def apply_migrations() -> list[str]:
    """migrations/*.sql 적용. 적용된 파일명 list 반환."""
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.info("적용할 마이그레이션 없음")
        return []

    applied: list[str] = []
    # DDL은 autocommit이 안전 — CREATE EXTENSION / TYPE / TABLE 등을 단일
    # statement-per-execute로 처리.
    async with await psycopg.AsyncConnection.connect(
        settings.database_url, autocommit=True
    ) as conn:
        already = await _applied_filenames(conn)

        for sql_file in sql_files:
            if sql_file.name in already:
                logger.info("skip %s (이미 적용됨)", sql_file.name)
                continue

            logger.info("apply %s", sql_file.name)
            sql = sql_file.read_text()
            async with conn.cursor() as cur:
                await cur.execute(sql)
                # schema_migration 테이블은 첫 마이그레이션이 만들기 때문에
                # 등록은 그 이후에만 가능
                if await _schema_migration_exists(conn):
                    await cur.execute(
                        "INSERT INTO schema_migration (filename) VALUES (%s) "
                        "ON CONFLICT (filename) DO NOTHING",
                        (sql_file.name,),
                    )
            applied.append(sql_file.name)
            logger.info("  ✓ %s", sql_file.name)

    return applied


async def _schema_migration_exists(conn: psycopg.AsyncConnection) -> bool:
    """schema_migration 테이블 존재 여부."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables WHERE table_name = 'schema_migration'"
            ")"
        )
        row = await cur.fetchone()
        return bool(row and row[0])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    applied = asyncio.run(apply_migrations())
    print(f"적용 완료: {len(applied)} 파일")
