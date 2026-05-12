"""matchmaker service — recommend 흐름 orchestration.

serialize query → embed → retrieve → fetch records → serialize each →
listwise rerank → compose. cold start 시 heuristic fallback.
"""

from dataclasses import dataclass

from the_commons.library.store import EvidenceStore
from the_commons.llm.protocol import EmbeddingProvider, LLMReranker
from the_commons.matchmaker.composer import (
    ComposedCandidate,
    CorpusContext,
    classify_confidence,
    compose_candidates,
    summarize_corpus,
)
from the_commons.matchmaker.retriever import (
    VectorIndex,
    cold_start_candidates,
    is_corpus_too_sparse,
)
from the_commons.matchmaker.serializer import QueryFeatures, default_registry
from the_commons.settings import settings


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
        """end-to-end recommend 흐름."""
        # 1. serialize query
        query_text = self._registry.serialize_query(query, version=self._template_version)

        # 2. embed
        query_vector = await self._embedder.embed(query_text)

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

        # 7. listwise rerank
        ranked = await self._reranker.rerank(
            query=query_text,
            candidates=candidate_texts,
            top_n=settings.recommend_top_n,
        )

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

    async def _fetch_evidence(self, hits):
        """RetrievedHit list → Evidence list (없는 ID는 skip)."""
        records = []
        for hit in hits:
            ev = await self._store.get_by_id(hit.evidence_id)
            if ev is not None:
                records.append(ev)
        return records

    async def _cold_start(self, query: QueryFeatures) -> RecommendResult:
        """corpus가 비어있을 때 휴리스틱 후보 반환."""
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
