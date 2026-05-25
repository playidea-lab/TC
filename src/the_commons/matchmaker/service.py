"""matchmaker service — LLM-free recommend 흐름.

serialize query → embed(로컬 BGE-m3) → retrieve → fetch records → similarity 순서 →
compose. cold start(corpus sparse 또는 embedder 실패) 시 heuristic fallback.

LLM 처방(synthesizer/infogain prior/reranker)은 제거됐다(KR7 cleanup) — 추천은
retrieve+유사도 후보 제시(처방 next_config 없음)이고, 판단은 환류(tc_knowledge/
tc_lineage)를 읽은 에이전트가 한다. idea: tc-cumulative-knowledge.
"""

from dataclasses import dataclass

import structlog

from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore
from the_commons.llm.protocol import EmbeddingProvider, RankedCandidate
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
    """LLM-free recommend orchestrator — retrieve + 유사도 후보 제시(처방 없음)."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        vector_index: VectorIndex,
        store: EvidenceStore,
    ) -> None:
        self._embedder = embedder
        self._vector_index = vector_index
        self._store = store
        self._registry = default_registry()
        self._template_version = settings.template_version

    async def recommend(
        self,
        query: QueryFeatures,
        *,
        round_id: str | None = None,
        force_explore: bool = False,
    ) -> RecommendResult:
        """retrieve + 유사도 후보. round_id/force_explore는 LLM 합성 제거로 미사용(호환)."""
        _ = (round_id, force_explore)
        query_text = self._registry.serialize_query(query, version=self._template_version)

        # embed — 실패 시 cold-start fallback
        try:
            query_vector = await self._embedder.embed(query_text)
        except Exception as exc:  # noqa: BLE001 — embedder 장애 대비
            logger.warning(
                "embedder_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="cold_start",
            )
            return await self._cold_start(query)

        hits = await self._vector_index.search(query_vector, top_k=settings.retrieve_top_k)
        if is_corpus_too_sparse(hits):
            return await self._cold_start(query)

        records = await self._fetch_evidence(hits)
        ranked = _similarity_ordered_ranking(hits, settings.recommend_top_n)
        context = summarize_corpus(hits)
        confidence = classify_confidence(context, is_heuristic_fallback=False)
        composed = compose_candidates(ranked, fetched_evidence=records, confidence=confidence)
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
        """corpus가 비었거나 embedder가 죽었을 때 휴리스틱 후보 반환(처방 없음)."""
        heuristics = cold_start_candidates(
            modality=query.data_fingerprint.modality,
            intent_goal=query.intent.goal,
            top_n=settings.recommend_top_n,
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
                next_config=None,
                policy=None,
            )
            for h in heuristics
        ]
        return RecommendResult(
            corpus_context=context,
            candidates=composed,
            template_version=self._template_version,
        )


def _similarity_ordered_ranking(hits: list[RetrievedHit], top_n: int) -> list[RankedCandidate]:
    """vector cosine similarity 순서 ranking (LLM-free)."""
    return [
        RankedCandidate(
            index=i,
            score=hit.similarity,
            reasoning="ranked by retrieval similarity",
        )
        for i, hit in enumerate(hits[:top_n])
    ]
