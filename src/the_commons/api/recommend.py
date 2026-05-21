"""POST /recommend — matchmaker stage 1+2 호출."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from the_commons.api.dependencies import (
    get_evidence_store,
    get_reciprocity_store,
)
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
from the_commons.llm.gemini import (
    GeminiEmbedding2Provider,
    GeminiFlash25Reranker,
)
from the_commons.llm.openai import OpenAIChatLLM
from the_commons.llm.protocol import EmbeddingProvider, LLMReranker
from the_commons.matchmaker.composer import ComposedCandidate, CorpusContext
from the_commons.matchmaker.infogain.llm_prior import PriorLLM
from the_commons.matchmaker.infogain.reranker import InfoGainReranker
from the_commons.matchmaker.policy import ExplorationPolicy, FixedEpsilonPolicy
from the_commons.matchmaker.retriever import PgvectorVectorIndex, VectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService
from the_commons.matchmaker.synthesizer import (
    NoveltyRecipeSynthesizer,
    WithinRecipeSynthesizer,
)
from the_commons.reciprocity.event_store import ReciprocityEventStore
from the_commons.reciprocity.loop_closure import record_loop_closures
from the_commons.settings import settings

router = APIRouter(tags=["recommend"])


class RecommendRequest(BaseModel):
    """POST /recommend body — query only (config·metrics는 evidence 시점에).

    v1 (cq-tc-autonomous-experiment-loop): round_id optional. cq의 폐루프가 매
    round 고유 ID를 보내면 같은 (corpus, round_id, intent) 입력에 같은 분기.
    없으면 server-side uuid4 fallback (단발 호출 호환).
    """

    query: QueryFeatures
    round_id: str | None = None


class CandidateOut(BaseModel):
    recipe_id: str
    expected_metric: dict[str, Any] | None
    evidence_ids: list[str]
    confidence: str
    reasoning: str
    # v1 (cq-tc-autonomous-experiment-loop): cq가 받아 학습에 그대로 주입할 hyperparams.
    # cold-start나 기존 호환 클라이언트 위해 optional.
    next_config: dict[str, Any] | None = None
    # ε-novelty mix 정책 메타데이터 — envelope.attribution.policy로 박힘.
    # {branch: "exploit"|"explore"|"cold_start", epsilon: float, version: str, wild_card_fired: bool}
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
    """production embedder. test는 dependency_overrides로 교체."""
    return GeminiEmbedding2Provider()


async def get_reranker() -> LLMReranker:
    """production reranker (infogain 미가용 시 fallback). test는 override."""
    return GeminiFlash25Reranker()


async def get_infogain_reranker() -> InfoGainReranker:
    """production 정보이득 reranker. test는 dependency_overrides로 교체.

    Gemini 무료 quota 회피 위해 prior LLM을 OpenAI로. meter.record로 비용 보고 —
    prior 호출도 일일 cost ceiling에 포함 (계측 누락 = ceiling 우회 방지).
    """
    llm: PriorLLM = OpenAIChatLLM()
    return InfoGainReranker(llm=llm)


async def get_vector_index(
    store: EvidenceStore = Depends(get_evidence_store),  # noqa: B008 — FastAPI 표준
) -> VectorIndex:
    """production vector index — Postgres store의 connection을 공유."""
    # PostgresEvidenceStore는 self._conn 보유. pgvector 검색도 같은 conn 사용.
    if hasattr(store, "_conn"):
        return PgvectorVectorIndex(store._conn)  # noqa: SLF001 — internal wiring
    raise RuntimeError("VectorIndex 구성 불가 — Postgres store 필요")


async def get_exploration_policy() -> ExplorationPolicy:
    """v1: 고정 ε ε-novelty mix. v2부터 settings.exploration_policy 분기."""
    return FixedEpsilonPolicy(eps=settings.exploration_epsilon)


async def get_within_synth() -> WithinRecipeSynthesizer:
    """exploit 분기 합성기. OpenAI generation (Gemini quota 회피)."""
    return WithinRecipeSynthesizer(llm=OpenAIChatLLM())


async def get_novelty_synth() -> NoveltyRecipeSynthesizer:
    """explore 분기 합성기. OpenAI generation (Gemini quota 회피)."""
    return NoveltyRecipeSynthesizer(llm=OpenAIChatLLM())


async def get_matchmaker_service(
    embedder: EmbeddingProvider = Depends(get_embedder),
    vector_index: VectorIndex = Depends(get_vector_index),
    reranker: LLMReranker = Depends(get_reranker),
    store: EvidenceStore = Depends(get_evidence_store),
    infogain_reranker: InfoGainReranker = Depends(get_infogain_reranker),
    policy: ExplorationPolicy = Depends(get_exploration_policy),
    within_synth: WithinRecipeSynthesizer = Depends(get_within_synth),
    novelty_synth: NoveltyRecipeSynthesizer = Depends(get_novelty_synth),
) -> MatchmakerService:
    return MatchmakerService(
        embedder=embedder,
        vector_index=vector_index,
        reranker=reranker,
        store=store,
        infogain_reranker=infogain_reranker,
        policy=policy,
        within_synth=within_synth,
        novelty_synth=novelty_synth,
    )


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
    """query → top-N recipe 추천 + 근거 evidence IDs + corpus context.

    응답에 포함된 evidence_id 각각에 대해 loop_closure event 자동 기록.
    """
    # rate limit — /recommend가 가장 비싼 endpoint (Gemini 호출)
    check_and_consume(recommend_bucket, client_rate_key(request, claims))

    # Gemini daily cost ceiling — 도달 시 503
    if meter.is_over_budget(settings.gemini_daily_budget_usd):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="daily LLM cost budget exceeded — try again after UTC midnight",
            headers={"Retry-After": "3600"},
        )

    result = await service.recommend(body.query, round_id=body.round_id)

    # consumer origin을 claim에서 추출 — v0.1엔 모두 'external'로 처리 가능 (CQ가 식별)
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
