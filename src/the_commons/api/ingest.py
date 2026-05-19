"""POST /ingest — pcq 2.x evidence를 받아 검증·정화·저장 + embedding + reciprocity."""

import contextlib

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from the_commons.api.dependencies import (
    get_embedder,
    get_evidence_store,
    get_reciprocity_store,
)
from the_commons.api.rate_limit import (
    check_and_consume,
    client_rate_key,
    ingest_bucket,
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
from the_commons.llm.cost_meter import meter
from the_commons.llm.protocol import EmbeddingProvider
from the_commons.matchmaker.serializer import default_registry
from the_commons.reciprocity.event_store import ReciprocityEventStore
from the_commons.reciprocity.promote_contradict import evaluate_and_record
from the_commons.settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_evidence(
    request: Request,
    body: IngestRequest,
    claims: VerifiedClaims = Depends(require_contributor),
    store: EvidenceStore = Depends(get_evidence_store),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
    embedder: EmbeddingProvider = Depends(get_embedder),
) -> IngestResponse:
    # rate limit — contributor 또는 IP (X-Forwarded-For 옵션은 settings에서)
    check_and_consume(ingest_bucket, client_rate_key(request, claims))

    # Gemini cost ceiling — daily budget 도달 시 503 (Gemini embedding 호출 차단)
    if meter.is_over_budget(settings.gemini_daily_budget_usd):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="daily LLM cost budget exceeded — try again after UTC midnight",
            headers={"Retry-After": "3600"},
        )
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

    # 1.5. integrity server-derive (R6 — 1.x record는 integrity 부재; 부착해야
    #      validator·store가 정상 동작. envelope 외부 변경 없음).
    pcq_inner = cleaned.get("pcq_record")
    if isinstance(pcq_inner, dict) and not pcq_inner.get("integrity"):
        from the_commons.library.content_hash import compute_integrity

        pcq_inner = dict(pcq_inner)
        pcq_inner["integrity"] = compute_integrity(pcq_inner)
        cleaned = dict(cleaned)
        cleaned["pcq_record"] = pcq_inner

    # 2. attribution + integrity 검증
    try:
        validate_attribution(cleaned)
    except AttributionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"attribution 검증 실패: {exc}",
        ) from exc

    # 2.5. verifier silent strip — synthetic_source.verifier는 server-derived.
    #     contributor가 보낸 값은 무시. content_hash 계산엔 어차피 제외.
    if isinstance(cleaned.get("synthetic_source"), dict):
        cleaned["synthetic_source"]["verifier"] = None

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

    # 4.5. embedding 생성 + 저장 (실패는 graceful — record는 살아있음).
    # 실패 시 connection이 aborted 상태일 수 있으므로 rollback으로 정리.
    try:
        registry = default_registry()
        description = registry.serialize_evidence(
            evidence, version=settings.template_version
        )
        vector = await embedder.embed(description)
        await store.update_embedding(evidence.evidence_id, vector)
    except Exception as exc:  # noqa: BLE001 — 외부 LLM 실패는 retrieve 영향만
        logger.warning(
            "embedding_failed",
            evidence_id=evidence.evidence_id,
            error=str(exc),
            error_type=type(exc).__name__,
            note="record is stored but not retrievable until re-embed",
        )
        conn = getattr(store, "_conn", None)
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.rollback()

    # 5. cluster bucket 계산
    cluster_bucket = compute_problem_cluster_bucket(cleaned)
    pcq = evidence.pcq_record
    modality = pcq.data_fingerprint.modality if pcq.data_fingerprint else None
    band = pcq.data_fingerprint.sample_count_band if pcq.data_fingerprint else None
    goal = pcq.intent.goal if pcq.intent else None

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
