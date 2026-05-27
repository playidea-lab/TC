"""POST /recommend — matchmaker LLM-free 추천 (retrieve + 유사도 후보 제시).

LLM 처방(synth/prior/reranker)은 제거됐다(KR7). 추천은 retrieve(로컬 임베딩)+유사도
후보이고 처방(next_config)이 없다 — 판단은 환류(tc_knowledge/tc_lineage)를 읽은 에이전트.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from the_commons.api.dependencies import get_evidence_store, get_reciprocity_store
from the_commons.api.rate_limit import (
    check_and_consume,
    client_rate_key,
    recommend_bucket,
)
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.ingestion.cluster_impact import compute_problem_cluster_bucket
from the_commons.library.store import EvidenceStore
from the_commons.llm.cost_meter import meter
from the_commons.llm.gemini import GeminiEmbedding2Provider
from the_commons.llm.protocol import EmbeddingProvider
from the_commons.matchmaker.composer import ComposedCandidate, CorpusContext
from the_commons.matchmaker.retriever import PgvectorVectorIndex, VectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService
from the_commons.reciprocity.event_store import ReciprocityEventStore
from the_commons.reciprocity.loop_closure import record_loop_closures
from the_commons.settings import settings

router = APIRouter(tags=["recommend"])


class RecommendRequest(BaseModel):
    """POST /recommend body — query only. round_id/force_explore는 호환용(LLM 합성 제거로 미사용)."""  # noqa: E501

    query: QueryFeatures
    round_id: str | None = None
    force_explore: bool = False


class CandidateOut(BaseModel):
    recipe_id: str
    expected_metric: dict[str, Any] | None
    evidence_ids: list[str]
    confidence: str
    reasoning: str
    # LLM-free 추천에선 항상 None(호환 유지). 처방·정책 메타는 더 이상 산출하지 않는다.
    next_config: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None


class CorpusContextOut(BaseModel):
    real_count: int
    synthetic_count: int


class RecommendResponse(BaseModel):
    corpus_context: CorpusContextOut
    candidates: list[CandidateOut]
    template_version: str


# ----------------------------------------------------------------------------
# Dependencies (production wiring)
# ----------------------------------------------------------------------------


async def get_embedder() -> EmbeddingProvider:
    """production embedder. settings.embedding_provider=local이면 BGE-m3(LLM-free).
    test는 dependency_overrides로 교체."""
    if settings.embedding_provider == "local":
        from the_commons.llm.local_embedding import shared_local_embedder

        return shared_local_embedder()
    return GeminiEmbedding2Provider()


async def get_vector_index(
    store: EvidenceStore = Depends(get_evidence_store),  # noqa: B008 — FastAPI 표준
) -> VectorIndex:
    """production vector index — Postgres store의 connection을 공유."""
    if hasattr(store, "_conn"):
        return PgvectorVectorIndex(store._conn)  # noqa: SLF001 — internal wiring
    raise RuntimeError("VectorIndex 구성 불가 — Postgres store 필요")


async def get_matchmaker_service(
    embedder: EmbeddingProvider = Depends(get_embedder),
    vector_index: VectorIndex = Depends(get_vector_index),
    store: EvidenceStore = Depends(get_evidence_store),
) -> MatchmakerService:
    return MatchmakerService(embedder=embedder, vector_index=vector_index, store=store)


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    request: Request,
    body: RecommendRequest,
    claims: VerifiedClaims = Depends(require_contributor),
    service: MatchmakerService = Depends(get_matchmaker_service),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
) -> RecommendResponse:
    """query → retrieve+유사도 후보 + corpus context. 각 cited evidence에 loop_closure 기록."""
    check_and_consume(recommend_bucket, client_rate_key(request, claims))

    # gemini embedder 옵션 사용 시 일일 cost ceiling (embedding_provider=local이면 항상 통과)
    if meter.is_over_budget(settings.gemini_daily_budget_usd):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="daily LLM cost budget exceeded — try again after UTC midnight",
            headers={"Retry-After": "3600"},
        )

    result = await service.recommend(
        body.query, round_id=body.round_id, force_explore=body.force_explore
    )

    consumer_origin = _resolve_origin(claims)
    cited_ids = [eid for c in result.candidates for eid in c.evidence_ids]
    cluster_bucket = compute_problem_cluster_bucket(body.query.model_dump(mode="json"))

    await record_loop_closures(
        reciprocity,
        consumer_contributor_id=claims.contributor_id,
        consumer_origin=consumer_origin,
        cited_evidence_ids=cited_ids,
        cluster_bucket=cluster_bucket,
    )

    return RecommendResponse(
        corpus_context=_corpus_to_out(result.corpus_context),
        candidates=[_candidate_to_out(c) for c in result.candidates],
        template_version=result.template_version,
    )


def _resolve_origin(claims: VerifiedClaims) -> str:
    """JWT claim에서 outreach_origin 추출. v0.1엔 raw_claims['origin'] fallback 'external'."""
    origin = claims.raw_claims.get("origin")
    if origin in ("internal", "external"):
        return str(origin)
    return "external"


def _corpus_to_out(c: CorpusContext) -> CorpusContextOut:
    return CorpusContextOut(real_count=c.real_count, synthetic_count=c.synthetic_count)


def _candidate_to_out(c: ComposedCandidate) -> CandidateOut:
    return CandidateOut(
        recipe_id=c.recipe_id,
        expected_metric=c.expected_metric,
        evidence_ids=list(c.evidence_ids),
        confidence=c.confidence,
        reasoning=c.reasoning,
        next_config=c.next_config,
        policy=c.policy,
    )
