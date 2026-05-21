"""matchmaker service — recommend 흐름 orchestration.

serialize query → embed → retrieve → fetch records → serialize each →
listwise rerank → compose. cold start 또는 외부 LLM 실패 시 heuristic fallback.

v1 (cq-tc-autonomous-experiment-loop): policy + within/novelty synthesizer 의존성을
주입하면 composed candidate[0]에 next_config + policy 메타가 채워진다. 미주입 시
기존 v0.1 흐름 그대로 (backwards compatible).
"""

import dataclasses
import uuid
from collections import defaultdict
from dataclasses import dataclass

import structlog

from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore
from the_commons.llm.protocol import EmbeddingProvider, LLMReranker, RankedCandidate
from the_commons.matchmaker.composer import (
    ComposedCandidate,
    CorpusContext,
    _extract_primary_metric,
    _extract_recipe_id,
    classify_confidence,
    compose_candidates,
    summarize_corpus,
)
from the_commons.matchmaker.infogain.reranker import InfoGainReranker
from the_commons.matchmaker.policy import Branch, ExplorationPolicy
from the_commons.matchmaker.retriever import (
    RetrievedHit,
    VectorIndex,
    cold_start_candidates,
    is_corpus_too_sparse,
)
from the_commons.matchmaker.serializer import QueryFeatures, default_registry
from the_commons.matchmaker.synthesizer import (
    EvidenceSummary,
    NextConfigProposal,
    NoveltyRecipeSynthesizer,
    RecipeStats,
    WithinRecipeSynthesizer,
)
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
        infogain_reranker: InfoGainReranker | None = None,
        policy: ExplorationPolicy | None = None,
        within_synth: WithinRecipeSynthesizer | None = None,
        novelty_synth: NoveltyRecipeSynthesizer | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_index = vector_index
        self._reranker = reranker
        self._store = store
        # infogain_reranker 주입 시 step7은 정보이득 경로 (v0.1 listwise 대체).
        # 미주입 시 기존 LLMReranker listwise 경로 유지 (degrade 계약 보존).
        self._infogain = infogain_reranker
        # v1 ε-novelty mix — 세 의존성이 모두 주입되어야 next_config 합성이 활성화.
        self._policy = policy
        self._within_synth = within_synth
        self._novelty_synth = novelty_synth
        self._registry = default_registry()
        self._template_version = settings.template_version

    async def recommend(
        self, query: QueryFeatures, *, round_id: str | None = None
    ) -> RecommendResult:
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

        # 6+7. rerank — 정보이득 경로(주입 시) 또는 기존 listwise.
        #      어느 경로든 실패 시 similarity 순서로 graceful degrade.
        if self._infogain is not None:
            try:
                ranked = await self._infogain.rerank(
                    query_text, hits, records, settings.recommend_top_n
                )
            except Exception as exc:  # noqa: BLE001 — 외부/수치 장애 대비
                logger.warning(
                    "infogain_reranker_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    fallback="similarity_order",
                )
                ranked = _similarity_ordered_ranking(
                    hits, settings.recommend_top_n
                )
        else:
            candidate_texts = [
                self._registry.serialize_evidence(
                    ev, version=self._template_version
                )
                for ev in records
            ]
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
                ranked = _similarity_ordered_ranking(
                    hits, settings.recommend_top_n
                )

        # 8. compose
        context = summarize_corpus(hits)
        confidence = classify_confidence(context, is_heuristic_fallback=False)
        composed = compose_candidates(
            ranked, fetched_evidence=records, confidence=confidence
        )

        # 9. v1 ε-novelty mix: 세 의존성이 모두 있을 때만 합성 활성화.
        #    composed[0]에 next_config/policy를 채워 cq가 그대로 학습에 주입.
        if (
            self._policy is not None
            and self._within_synth is not None
            and self._novelty_synth is not None
            and composed
        ):
            composed = await self._synthesize_first(
                composed, records, hits, query, round_id=round_id
            )

        return RecommendResult(
            corpus_context=context,
            candidates=composed,
            template_version=self._template_version,
        )

    async def _synthesize_first(
        self,
        composed: list[ComposedCandidate],
        records: list[Evidence],
        hits: list[RetrievedHit],
        query: QueryFeatures,
        *,
        round_id: str | None,
    ) -> list[ComposedCandidate]:
        """composed[0]에 next_config + policy 메타를 채운다.

        세 의존성(policy/within_synth/novelty_synth)이 모두 주입된 경우에만 호출됨.
        나머지 candidate는 그대로 (cq는 첫 candidate만 실행).
        """
        assert self._policy is not None
        assert self._within_synth is not None
        assert self._novelty_synth is not None

        effective_round = round_id or uuid.uuid4().hex
        intent_goal = query.intent.goal

        branch: Branch = self._policy.choose_branch(
            corpus_size=len(hits),
            round_id=effective_round,
            intent=intent_goal,
        )

        top = composed[0]
        proposal: NextConfigProposal
        if branch == "explore":
            corpus_recipes = _summarize_recipes(records)
            proposal = await self._novelty_synth.propose(
                corpus_recipes=corpus_recipes, intent=intent_goal
            )
        else:
            # exploit: composed[0]의 recipe_id가 infogain rerank의 top.
            top_recipe = top.recipe_id
            recipe_evidences = [
                ev for ev in records if _extract_recipe_id(ev) == top_recipe
            ]
            summaries = [
                EvidenceSummary(
                    evidence_id=ev.evidence_id,
                    config=dict(ev.pcq_record.config),
                    metrics=dict(ev.pcq_record.metrics),
                )
                for ev in recipe_evidences
            ]
            proposal = await self._within_synth.propose(
                recipe_id=top_recipe, evidences=summaries, intent=intent_goal
            )

        # 정책 인스턴스의 실제 ε를 박는다 (v2 가변 정책 호환). 정책에 eps 속성이
        # 없으면 settings fallback.
        eps_value = getattr(self._policy, "eps", settings.exploration_epsilon)
        policy_meta = {
            "branch": branch,
            "epsilon": eps_value,
            "version": self._policy.version,
            "wild_card_fired": branch == "explore",
            "round_id": effective_round,
        }

        new_top = dataclasses.replace(
            top,
            next_config=proposal.next_config,
            policy=policy_meta,
            # explore 분기는 recipe_id가 corpus 밖이라 LLM 응답으로 교체.
            recipe_id=proposal.recipe_id if branch == "explore" else top.recipe_id,
            evidence_ids=(
                proposal.evidence_ids if branch == "explore" else list(top.evidence_ids)
            ),
            reasoning=proposal.reasoning or top.reasoning,
        )
        return [new_top, *composed[1:]]

    async def _fetch_evidence(self, hits: list[RetrievedHit]) -> list[Evidence]:
        """RetrievedHit list → Evidence list (없는 ID는 skip)."""
        records: list[Evidence] = []
        for hit in hits:
            ev = await self._store.get_by_id(hit.evidence_id)
            if ev is not None:
                records.append(ev)
        return records

    async def _cold_start(self, query: QueryFeatures) -> RecommendResult:
        """corpus가 비어있거나 embedder가 죽었을 때 휴리스틱 후보 반환.

        v1: policy 의존성이 있어도 cold-start 분기는 합성기 호출 없이 휴리스틱
        그대로. policy 메타만 branch="cold_start"로 마킹해 envelope에 박힐 수 있게.
        """
        modality = query.data_fingerprint.modality
        intent_goal = query.intent.goal
        heuristics = cold_start_candidates(
            modality=modality, intent_goal=intent_goal, top_n=settings.recommend_top_n
        )

        context = CorpusContext(real_count=0, synthetic_count=0)
        confidence = classify_confidence(context, is_heuristic_fallback=True)

        policy_meta: dict | None
        if self._policy is not None:
            eps_value = getattr(self._policy, "eps", settings.exploration_epsilon)
            policy_meta = {
                "branch": "cold_start",
                "epsilon": eps_value,
                "version": self._policy.version,
                "wild_card_fired": False,
            }
        else:
            policy_meta = None

        composed = [
            ComposedCandidate(
                recipe_id=h.recipe_id,
                expected_metric=None,
                evidence_ids=[],
                confidence=confidence,
                reasoning=h.description,
                next_config=None,
                policy=policy_meta,
            )
            for h in heuristics
        ]
        return RecommendResult(
            corpus_context=context,
            candidates=composed,
            template_version=self._template_version,
        )


def _summarize_recipes(records: list[Evidence]) -> list[RecipeStats]:
    """records를 recipe_id로 그룹화 → NoveltyRecipeSynthesizer 입력 형태로.

    best_metric은 evidence의 첫 numeric metric의 max — recipe별로 단일 값.
    metric_name은 첫 evidence의 첫 metric 이름 (mixed metric corpus면 첫 것만).
    """
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for ev in records:
        grouped[_extract_recipe_id(ev)].append(ev)

    stats: list[RecipeStats] = []
    for recipe_id, evs in grouped.items():
        primary = _extract_primary_metric(evs[0]) if evs else None
        metric_name = primary["name"] if primary else "metric"
        values = [
            _extract_primary_metric(ev)["value"]  # type: ignore[index]
            for ev in evs
            if _extract_primary_metric(ev) is not None
        ]
        best = max(values) if values else None
        stats.append(
            RecipeStats(
                recipe_id=recipe_id,
                tries=len(evs),
                best_metric=best,
                metric_name=metric_name,
            )
        )
    return stats


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
