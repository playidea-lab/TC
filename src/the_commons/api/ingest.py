"""POST /ingest — pcq 2.x evidence를 받아 검증·정화·저장."""

from fastapi import APIRouter, Depends, HTTPException, status

from the_commons.api.dependencies import get_evidence_store
from the_commons.api.schemas import ClusterImpact, IngestRequest, IngestResponse
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.ingestion.attribution_validator import (
    AttributionError,
    validate_attribution,
)
from the_commons.ingestion.cluster_impact import compute_problem_cluster_bucket
from the_commons.ingestion.phi_blocker import PHIViolationError, block_phi
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceAlreadyExistsError, EvidenceStore

router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_evidence(
    body: IngestRequest,
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
) -> IngestResponse:
    """ingestion 파이프라인: PHI 차단 → attribution 검증 → 저장 → cluster impact 응답."""
    raw = body.evidence

    # 1. PHI 자동 차단·정화
    try:
        cleaned = block_phi(raw)
    except PHIViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PHI 차단 위반: {exc}",
        ) from exc

    # 2. attribution 검증 (content_hash·tier 일관성·pcq 버전)
    try:
        validate_attribution(cleaned)
    except AttributionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"attribution 검증 실패: {exc}",
        ) from exc

    # 3. Pydantic 파싱 (Evidence schema)
    try:
        evidence = Evidence.model_validate(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"schema 검증 실패: {exc}",
        ) from exc

    # 4. 저장 (immutable)
    try:
        await store.insert(evidence)
    except EvidenceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    # 5. cluster impact (M1은 bucket label만, promote/contradict는 M3 retirement worker)
    cluster_bucket = compute_problem_cluster_bucket(cleaned)

    # claims는 디버깅·audit용 — production에선 contributor_id reference로도 활용 가능
    _ = claims

    return IngestResponse(
        evidence_id=evidence.evidence_id,
        tier=evidence.tier,
        cluster_impact=ClusterImpact(cluster_bucket=cluster_bucket),
    )
