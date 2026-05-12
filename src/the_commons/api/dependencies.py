"""FastAPI 공통 의존성 — DB connection, evidence store provider 등.

테스트에서는 `app.dependency_overrides[get_evidence_store] = ...`로 교체.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status

from the_commons.db.session import get_connection
from the_commons.library.store import EvidenceStore, PostgresEvidenceStore


async def get_evidence_store() -> AsyncIterator[EvidenceStore]:
    """production용 — PostgresEvidenceStore (active connection 자동 lifetime)."""
    try:
        async with get_connection() as conn:
            yield PostgresEvidenceStore(conn)
    except Exception as exc:  # noqa: BLE001 — production fallback
        # connection 실패는 503 (서비스 일시 unavailable)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"DB 연결 실패: {exc}",
        ) from exc


# 단위 테스트가 이 typing alias를 import해서 override 가능
EvidenceStoreDep = Depends(get_evidence_store)
