"""FastAPI 공통 의존성 — DB connection, store provider 등.

테스트에서는 `app.dependency_overrides[get_evidence_store] = ...`로 교체.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status

from the_commons.db.session import get_connection
from the_commons.library.store import EvidenceStore, PostgresEvidenceStore
from the_commons.llm.gemini import GeminiEmbedding2Provider
from the_commons.llm.protocol import EmbeddingProvider
from the_commons.reciprocity.event_store import (
    InMemoryReciprocityEventStore,
    PostgresReciprocityEventStore,
    ReciprocityEventStore,
)
from the_commons.settings import settings

# 모듈 전역 in-memory store — production은 dependency override 또는 Postgres 사용
_inmemory_reciprocity = InMemoryReciprocityEventStore()


async def get_evidence_store() -> AsyncIterator[EvidenceStore]:
    """production용 — PostgresEvidenceStore (active connection 자동 lifetime).

    endpoint가 직접 던진 HTTPException은 그대로 통과시키고, 그 외 connection
    실패 등만 503으로 감싼다.
    """
    try:
        async with get_connection() as conn:
            yield PostgresEvidenceStore(conn)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — connection-level fallback
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


async def get_embedder() -> EmbeddingProvider:
    """production embedder. settings.embedding_provider=local이면 BGE-m3(LLM-free).
    test는 dependency_overrides로 교체."""
    if settings.embedding_provider == "local":
        from the_commons.llm.local_embedding import shared_local_embedder

        return shared_local_embedder()
    return GeminiEmbedding2Provider()


# 단위 테스트가 이 typing alias를 import해서 override 가능
EvidenceStoreDep = Depends(get_evidence_store)
