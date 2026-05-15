"""matchmaker service — recommend 흐름 orchestration.

serialize query → embed → retrieve → fetch records → serialize each →
listwise rerank → compose. cold start 또는 외부 LLM 실패 시 heuristic fallback.
"""

from dataclasses import dataclass

import structlog

from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore
from the_commons.llm.protocol import EmbeddingProvider, LLMReranker, RankedCandidate
from the_commons.matchmaker.composer import (
    ComposedCandidate,
    CorpusContext,
    classify_confidence,
    compose_candidates,
    summarize_corpus,
)
from the_commons.matchmaker.retriever import (
    RetrievedHit,
    VectorIndex,
    cold_start_candidates,
    is_corpus_too_sparse,
)
from the_commons.matchmaker.serializer import QueryFeatures, default_registry
from the_commons.settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RecommendResult:
    """matchmaker service의 응답. API layer가 그대로 직렬화."""

    corpus_context: CorpusContext
    candidates: list[ComposedCandidate]
    template_version: str


class MatchmakerService:
    """matchmaker 컴포넌트들의 orchestrator. 의존성은 생성 시 주입."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        vector_index: VectorIndex,
        reranker: LLMReranker,
        store: EvidenceStore,
    ) -> None:
        self._embedder = embedder
        self._vector_index = vector_index
        self._reranker = reranker
        self._store = store
        self._registry = default_registry()
        self._template_version = settings.template_version

    async def recommend(self, query: QueryFeatures) -> RecommendResult:
        """end-to-end recommend 흐름. 외부 LLM 실패는 graceful degrade."""
        # 1. serialize query
        query_text = self._registry.serialize_query(query, version=self._template_version)

        # 2. embed — 실패 시 cold-start fallback
        try:
            query_vector = await self._embedder.embed(query_text)
        except Exception as exc:  # noqa: BLE001 — 외부 LLM 장애 대비
            logger.warning(
                "embedder_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="cold_start",
            )
            return await self._cold_start(query)

        # 3. retrieve top-K
        hits = await self._vector_index.search(query_vector, top_k=settings.retrieve_top_k)

        # 4. cold start fallback
        if is_corpus_too_sparse(hits):
            return await self._cold_start(query)

        # 5. fetch evidence records
        records = await self._fetch_evidence(hits)

        # 6. serialize each evidence
        candidate_texts = [
            self._registry.serialize_evidence(ev, version=self._template_version)
            for ev in records
        ]

        # 7. listwise rerank — 실패 시 similarity 순서로 fallback
        try:
            ranked = await self._reranker.rerank(
                query=query_text,
                candidates=candidate_texts,
                top_n=settings.recommend_top_n,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reranker_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="similarity_order",
            )
            ranked = _similarity_ordered_ranking(hits, settings.recommend_top_n)

        # 8. compose
        context = summarize_corpus(hits)
        confidence = classify_confidence(context, is_heuristic_fallback=False)
        composed = compose_candidates(
            ranked, fetched_evidence=records, confidence=confidence
        )

        return RecommendResult(
            corpus_context=context,
            candidates=composed,
            template_version=self._template_version,
        )

    async def _fetch_evidence(self, hits: list[RetrievedHit]) -> list[Evidence]:
        """RetrievedHit list → Evidence list (없는 ID는 skip)."""
        records: list[Evidence] = []
        for hit in hits:
            ev = await self._store.get_by_id(hit.evidence_id)
            if ev is not None:
                records.append(ev)
        return records

    async def _cold_start(self, query: QueryFeatures) -> RecommendResult:
        """corpus가 비어있거나 embedder가 죽었을 때 휴리스틱 후보 반환."""
        modality = query.data_fingerprint.modality
        intent_goal = query.intent.goal
        heuristics = cold_start_candidates(
            modality=modality, intent_goal=intent_goal, top_n=settings.recommend_top_n
        )

        context = CorpusContext(real_count=0, synthetic_count=0)
        confidence = classify_confidence(context, is_heuristic_fallback=True)

        composed = [
            ComposedCandidate(
                recipe_id=h.recipe_id,
                expected_metric=None,
                evidence_ids=[],
                confidence=confidence,
                reasoning=h.description,
            )
            for h in heuristics
        ]
        return RecommendResult(
            corpus_context=context,
            candidates=composed,
            template_version=self._template_version,
        )


def _similarity_ordered_ranking(
    hits: list[RetrievedHit], top_n: int
) -> list[RankedCandidate]:
    """reranker가 죽었을 때 vector cosine similarity로 fallback ranking."""
    return [
        RankedCandidate(
            index=i,
            score=hit.similarity,
            reasoning="reranker unavailable — ranked by retrieval similarity",
        )
        for i, hit in enumerate(hits[:top_n])
    ]
