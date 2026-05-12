"""FastAPI 공통 의존성 — DB connection, store provider 등.

테스트에서는 `app.dependency_overrides[get_evidence_store] = ...`로 교체.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status

from the_commons.db.session import get_connection
from the_commons.library.store import EvidenceStore, PostgresEvidenceStore
from the_commons.reciprocity.event_store import (
    InMemoryReciprocityEventStore,
    PostgresReciprocityEventStore,
    ReciprocityEventStore,
)

# 모듈 전역 in-memory store — production은 dependency override 또는 Postgres 사용
_inmemory_reciprocity = InMemoryReciprocityEventStore()


async def get_evidence_store() -> AsyncIterator[EvidenceStore]:
    """production용 — PostgresEvidenceStore (active connection 자동 lifetime)."""
    try:
        async with get_connection() as conn:
            yield PostgresEvidenceStore(conn)
    except Exception as exc:  # noqa: BLE001 — production fallback
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"DB 연결 실패: {exc}",
        ) from exc


async def get_reciprocity_store(
    store: EvidenceStore = Depends(get_evidence_store),
) -> ReciprocityEventStore:
    """production은 같은 connection으로 Postgres, dev/test는 in-memory singleton."""
    # PostgresEvidenceStore면 같은 connection 공유
    conn = getattr(store, "_conn", None)
    if conn is not None:
        return PostgresReciprocityEventStore(conn)
    return _inmemory_reciprocity


# 단위 테스트가 이 typing alias를 import해서 override 가능
EvidenceStoreDep = Depends(get_evidence_store)
