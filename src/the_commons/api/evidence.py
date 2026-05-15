"""GET /evidence/{id} + GET /evidence (list) — Library L1 read endpoints."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from the_commons.api.dependencies import (
    get_evidence_store,
    get_reciprocity_store,
)
from the_commons.api.schemas import EvidenceReadResponse
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore
from the_commons.reciprocity.event_store import ReciprocityEventStore

router = APIRouter(tags=["evidence"])


class EvidenceListResponse(BaseModel):
    """GET /evidence 응답 — 페이지 + 전체 매칭 카운트."""

    evidences: list[Evidence]
    total: int = Field(description="필터 조건을 만족하는 전체 evidence 수")
    limit: int
    offset: int


@router.get("/evidence", response_model=EvidenceListResponse)
async def list_evidence(
    tier: Literal["real", "synthetic"] | None = Query(default=None),
    modality: str | None = Query(default=None),
    sample_count_band: str | None = Query(default=None),
    intent_goal: str | None = Query(default=None),
    contributor_id: str | None = Query(default=None),
    deprecated: bool | None = Query(
        default=False,
        description="False=활성 only (기본), True=deprecated only, None=둘 다",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
) -> EvidenceListResponse:
    """필터로 evidence 검색. 페이지네이션 limit/offset, 정렬 created_at DESC."""
    _ = claims
    evidences, total = await store.list_evidence(
        tier=tier,
        modality=modality,
        sample_count_band=sample_count_band,
        intent_goal=intent_goal,
        contributor_id=contributor_id,
        deprecated=deprecated,
        limit=limit,
        offset=offset,
    )
    return EvidenceListResponse(
        evidences=evidences, total=total, limit=limit, offset=offset
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceReadResponse)
async def read_evidence(
    evidence_id: str,
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
) -> EvidenceReadResponse:
    """ID로 evidence 한 건 반환. synthetic이면 verifier를 event store에서 derive.

    record 자체는 L1 immutable. verifier는 응답 시 read-time JOIN으로 채워짐.
    """
    _ = claims
    evidence = await store.get_by_id(evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"evidence not found: {evidence_id}",
        )

    # synthetic tier만 verifier derive (real은 검증 대상이 아니라 검증자)
    if evidence.tier == "synthetic" and evidence.synthetic_source is not None:
        verifier = await reciprocity.find_verifier_for(evidence_id)
        if verifier is not None:
            # Pydantic model_copy로 immutable 사본에 derived field만 갱신
            evidence = evidence.model_copy(
                update={
                    "synthetic_source": evidence.synthetic_source.model_copy(
                        update={"verifier": verifier}
                    )
                }
            )

    return EvidenceReadResponse(evidence=evidence)
