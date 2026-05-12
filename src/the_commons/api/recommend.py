"""POST /recommend — matchmaker stage 1+2 호출."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from the_commons.api.dependencies import get_evidence_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.store import EvidenceStore
from the_commons.llm.gemini import GeminiEmbedding2Provider, GeminiFlash25Reranker
from the_commons.llm.protocol import EmbeddingProvider, LLMReranker
from the_commons.matchmaker.composer import ComposedCandidate, CorpusContext
from the_commons.matchmaker.retriever import PgvectorVectorIndex, VectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService

router = APIRouter(tags=["recommend"])


class RecommendRequest(BaseModel):
    """POST /recommend body — query only (config·metrics는 evidence 시점에)."""

    query: QueryFeatures


class CandidateOut(BaseModel):
    recipe_id: str
    expected_metric: dict[str, Any] | None
    evidence_ids: list[str]
    confidence: str
    reasoning: str


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
    """production reranker. test는 dependency_overrides로 교체."""
    return GeminiFlash25Reranker()


async def get_vector_index(
    store: EvidenceStore = Depends(get_evidence_store),  # noqa: B008 — FastAPI 표준
) -> VectorIndex:
    """production vector index — Postgres store의 connection을 공유."""
    # PostgresEvidenceStore는 self._conn 보유. pgvector 검색도 같은 conn 사용.
    if hasattr(store, "_conn"):
        return PgvectorVectorIndex(store._conn)  # noqa: SLF001 — internal wiring
    raise RuntimeError("VectorIndex 구성 불가 — Postgres store 필요")


async def get_matchmaker_service(
    embedder: EmbeddingProvider = Depends(get_embedder),
    vector_index: VectorIndex = Depends(get_vector_index),
    reranker: LLMReranker = Depends(get_reranker),
    store: EvidenceStore = Depends(get_evidence_store),
) -> MatchmakerService:
    return MatchmakerService(
        embedder=embedder,
        vector_index=vector_index,
        reranker=reranker,
        store=store,
    )


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    body: RecommendRequest,
    claims: VerifiedClaims = Depends(require_contributor),
    service: MatchmakerService = Depends(get_matchmaker_service),
) -> RecommendResponse:
    """query → top-N recipe 추천 + 근거 evidence IDs + corpus context."""
    _ = claims
    result = await service.recommend(body.query)

    return RecommendResponse(
        corpus_context=_corpus_to_out(result.corpus_context),
        candidates=[_candidate_to_out(c) for c in result.candidates],
        template_version=result.template_version,
    )


def _corpus_to_out(c: CorpusContext) -> CorpusContextOut:
    return CorpusContextOut(real_count=c.real_count, synthetic_count=c.synthetic_count)


def _candidate_to_out(c: ComposedCandidate) -> CandidateOut:
    return CandidateOut(
        recipe_id=c.recipe_id,
        expected_metric=c.expected_metric,
        evidence_ids=list(c.evidence_ids),
        confidence=c.confidence,
        reasoning=c.reasoning,
    )
