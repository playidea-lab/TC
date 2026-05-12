"""POST /ingest — pcq 2.x evidence를 받아 검증·정화·저장 + reciprocity event 발동."""

from fastapi import APIRouter, Depends, HTTPException, status

from the_commons.api.dependencies import (
    get_evidence_store,
    get_reciprocity_store,
)
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
from the_commons.reciprocity.event_store import ReciprocityEventStore
from the_commons.reciprocity.promote_contradict import evaluate_and_record
from the_commons.settings import settings

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
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
) -> IngestResponse:
    """ingestion 파이프라인:
    PHI 차단 → attribution → schema → store → promote/contradicts → retirement check.
    """
    raw = body.evidence

    # 1. PHI 자동 차단
    try:
        cleaned = block_phi(raw)
    except PHIViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PHI 차단 위반: {exc}",
        ) from exc

    # 2. attribution
    try:
        validate_attribution(cleaned)
    except AttributionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"attribution 검증 실패: {exc}",
        ) from exc

    # 3. schema
    try:
        evidence = Evidence.model_validate(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"schema 검증 실패: {exc}",
        ) from exc

    # 4. 저장
    try:
        await store.insert(evidence)
    except EvidenceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    # 5. cluster bucket 계산
    cluster_bucket = compute_problem_cluster_bucket(cleaned)
    modality = evidence.data_fingerprint.modality
    band = evidence.data_fingerprint.sample_count_band
    goal = evidence.intent.goal

    # 6. real evidence가 들어왔을 때: promote/contradicts evaluation + retirement
    promoted_ids: list[str] = []
    contradicted_ids: list[str] = []
    retired_ids: list[str] = []

    if evidence.tier == "real":
        # 6a. active synthetic 조회 + 평가
        active_synthetics = await store.list_active_synthetics_in_bucket(
            modality=modality, sample_count_band=band, intent_goal=goal
        )
        if active_synthetics:
            synthetic_dicts = [s.model_dump(mode="json") for s in active_synthetics]
            grouped = await evaluate_and_record(
                reciprocity,
                new_real_record=cleaned,
                candidate_synthetic_records=synthetic_dicts,
                origin=evidence.outreach_origin,
            )
            promoted_ids = grouped["promote"]
            contradicted_ids = grouped["contradicts"]

        # 6b. real_count 임계값 체크 → 같은 cluster active synthetic 전부 deprecate
        real_count = await store.count_real_in_bucket(
            modality=modality, sample_count_band=band, intent_goal=goal
        )
        if real_count >= settings.retirement_real_threshold:
            still_active = await store.list_active_synthetics_in_bucket(
                modality=modality, sample_count_band=band, intent_goal=goal
            )
            for syn in still_active:
                await store.mark_deprecated(
                    syn.evidence_id,
                    reason=(
                        f"cluster {cluster_bucket} real_count={real_count} "
                        f"(threshold {settings.retirement_real_threshold})"
                    ),
                )
                retired_ids.append(syn.evidence_id)

    _ = claims

    return IngestResponse(
        evidence_id=evidence.evidence_id,
        tier=evidence.tier,
        cluster_impact=ClusterImpact(
            promoted_synthetic_ids=promoted_ids,
            contradicted_synthetic_ids=contradicted_ids,
            retired_synthetic_ids=retired_ids,
            cluster_bucket=cluster_bucket,
        ),
    )
