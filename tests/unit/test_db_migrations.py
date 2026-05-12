"""DB migration 파일들의 정합성 검증 (실제 DB 불필요).

실제 schema 적용 검증은 integration test에서 docker-compose로 PostgreSQL을
띄운 후 별도 수행한다.
"""

from pathlib import Path

import pytest

MIGRATIONS_DIR = (
    Path(__file__).parent.parent.parent / "src" / "the_commons" / "db" / "migrations"
)


def test_migrations_dir_exists() -> None:
    """마이그레이션 디렉토리가 존재해야 한다."""
    assert MIGRATIONS_DIR.is_dir()


def test_migrations_contain_at_least_one_sql_file() -> None:
    """최소 한 개의 .sql 파일이 있어야 한다."""
    sql_files = list(MIGRATIONS_DIR.glob("*.sql"))
    assert len(sql_files) >= 1


def test_init_migration_creates_pgvector_extension() -> None:
    """001_init.sql이 pgvector extension 활성화 + 핵심 테이블을 생성해야 한다."""
    init_sql = (MIGRATIONS_DIR / "001_init.sql").read_text()

    # pgvector extension
    assert "CREATE EXTENSION IF NOT EXISTS vector" in init_sql

    # 핵심 테이블 6개
    required_tables = [
        "evidence",
        "cluster",
        "evidence_cluster",
        "retirement_audit",
        "reciprocity_event",
        "recipe",
        "heuristic_rule",
        "schema_migration",
    ]
    for table in required_tables:
        assert f"CREATE TABLE {table}" in init_sql, f"table {table} 누락"


def test_init_migration_enforces_synthetic_attribution() -> None:
    """synthetic tier evidence는 synthetic_source attribution이 강제되어야 한다."""
    init_sql = (MIGRATIONS_DIR / "001_init.sql").read_text()
    assert "synthetic_attribution_required" in init_sql
    assert "tier = 'real' OR synthetic_source IS NOT NULL" in init_sql


def test_indexes_migration_creates_hnsw_for_embedding() -> None:
    """002_indexes.sql이 vector HNSW 인덱스를 생성해야 한다."""
    idx_sql = (MIGRATIONS_DIR / "002_indexes.sql").read_text()
    assert "USING hnsw" in idx_sql
    assert "vector_cosine_ops" in idx_sql


def test_migration_filenames_are_sorted_numerically() -> None:
    """파일명이 번호 prefix로 정렬 가능해야 한다 (001_*, 002_* 형식)."""
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for sql_file in sql_files:
        # 첫 3글자가 숫자여야 한다
        assert sql_file.stem[:3].isdigit(), f"파일명 {sql_file.name}이 번호로 시작 X"


@pytest.mark.parametrize(
    "enum_def",
    [
        "CREATE TYPE evidence_tier AS ENUM ('real', 'synthetic')",
        "CREATE TYPE evidence_origin AS ENUM ('internal', 'external')",
        "CREATE TYPE reciprocity_event_type AS ENUM "
        "('loop_closure', 'promote', 'contradicts')",
    ],
)
def test_init_migration_defines_required_enums(enum_def: str) -> None:
    """필수 enum 타입이 정의되어 있어야 한다."""
    init_sql = (MIGRATIONS_DIR / "001_init.sql").read_text()
    assert enum_def in init_sql
