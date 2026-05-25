"""MatchmakerService v1 ε-novelty mix 분기 통합 테스트.

policy + within_synth + novelty_synth 의존성이 모두 주입된 경우, composed[0]에
next_config과 policy 메타가 채워진다. cold-start 분기는 policy.branch="cold_start"
마커만 박힘 (합성 호출 없음).
"""

import asyncio

import pytest

from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore
from the_commons.matchmaker.infogain.reranker import InfoGainReranker
from the_commons.matchmaker.policy import FixedEpsilonPolicy
from the_commons.matchmaker.retriever import InMemoryVectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService
from the_commons.matchmaker.synthesizer import (
    NoveltyRecipeSynthesizer,
    WithinRecipeSynthesizer,
)


class _OkEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _UnusedReranker:
    async def rerank(self, query, candidates, top_n=5):  # noqa: ANN001
        raise AssertionError("infogain 주입 시 LLMReranker는 호출되면 안 됨")


class _StubPriorLLM:
    """infogain용 LLM stub — Beta prior만 반환."""

    async def complete(self, prompt: str) -> str:
        return '{"alpha": 1.0, "beta": 1.0}'


class _StubSynthesisLLM:
    """synthesizer용 LLM — 항상 같은 JSON 응답.

    prompt에 "novelty"라는 단어가 있으면 novelty 응답, 아니면 within 응답.
    """

    async def complete(self, prompt: str) -> str:
        if "novelty" in prompt.lower() or "existing recipes" in prompt:
            return (
                '{"recipe_id": "rf-deep", '
                '"next_config": {"max_depth": 20, "n_estimators": 500}, '
                '"reasoning": "novelty branch — corpus 밖 새 recipe"}'
            )
        return (
            '{"recipe_id": "<must_be_ignored>", '
            '"next_config": {"max_depth": 7, "n_estimators": 100}, '
            '"reasoning": "within-recipe branch"}'
        )


def _query(goal: str = "exploration") -> QueryFeatures:
    return QueryFeatures.model_validate(
        {
            "worker_spec": {"cpu_cores": 16, "ram_gb": 32, "has_gpu": False},
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "10k-100k",
            },
            "intent": {
                "goal": goal,
                "expected_baseline": {"metric": "AUC"},
                "tolerance": {"direction": "higher_is_better"},
            },
        }
    )


@pytest.fixture
def seeded() -> tuple[InMemoryEvidenceStore, InMemoryVectorIndex]:
    store = InMemoryEvidenceStore()
    index = InMemoryVectorIndex()

    async def _seed() -> None:
        for i, (recipe, auc) in enumerate(
            [
                ("rf", 0.9),
                ("rf", 0.8),
                ("xgb", 0.4),
                ("rf", 0.85),
                ("xgb", 0.5),
                ("svm", 0.6),
            ]
        ):
            rec = {
                "evidence_id": f"ev-{i}",
                "tier": "real",
                "outreach_origin": "external",
                "synthetic_source": None,
                "pcq_record": {
                    "intent": {
                        "goal": "exploration",
                        "expected_baseline": {"metric": "AUC"},
                        "tolerance": {"direction": "higher_is_better"},
                    },
                    "data_fingerprint": {
                        "modality": "tabular",
                        "sample_count_band": "10k-100k",
                    },
                    "config": {"recipe_id": recipe, "n_estimators": 100},
                    "metrics": {"AUC": auc},
                    "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
                    "attribution": {"operator": None},
                    "contract_version": "2.0",
                },
            }
            await store.insert(Evidence.model_validate(rec))
            index.add(f"ev-{i}", [1.0, 0.0, 0.0], tier="real")

    asyncio.run(_seed())
    return store, index


def _build_v1_service(
    store: InMemoryEvidenceStore,
    index: InMemoryVectorIndex,
    *,
    eps: float = 0.1,
) -> MatchmakerService:
    return MatchmakerService(
        embedder=_OkEmbedder(),
        vector_index=index,
        reranker=_UnusedReranker(),
        store=store,
        infogain_reranker=InfoGainReranker(llm=_StubPriorLLM()),
        policy=FixedEpsilonPolicy(eps=eps),
        within_synth=WithinRecipeSynthesizer(llm=_StubSynthesisLLM()),
        novelty_synth=NoveltyRecipeSynthesizer(llm=_StubSynthesisLLM()),
    )


# ---------- 분기 활성화 ----------


async def test_v1_exploit_branch_fills_next_config_and_policy(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """ε=0이면 항상 exploit. composed[0]에 within-recipe synth 결과가 박힘."""
    store, index = seeded
    service = _build_v1_service(store, index, eps=0.0)
    result = await service.recommend(_query(), round_id="r-1")

    assert len(result.candidates) > 0
    top = result.candidates[0]
    assert top.next_config is not None
    assert top.next_config["max_depth"] == 7  # within 분기 응답 (novelty 키워드 없음)
    assert top.policy is not None
    assert top.policy["branch"] == "exploit"
    assert top.policy["epsilon"] == 0.0
    assert top.policy["wild_card_fired"] is False
    assert "fixed" in top.policy["version"]


async def test_v1_explore_branch_uses_novelty_recipe(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """ε=1이면 항상 explore. composed[0]의 recipe_id가 LLM novelty 응답으로 교체."""
    store, index = seeded
    service = _build_v1_service(store, index, eps=1.0)
    result = await service.recommend(_query(), round_id="r-1")

    top = result.candidates[0]
    assert top.policy is not None
    assert top.policy["branch"] == "explore"
    assert top.policy["wild_card_fired"] is True
    assert top.next_config is not None
    # novelty 응답이 들어감 (recipe_id 교체)
    assert top.recipe_id == "rf-deep"
    assert top.next_config["max_depth"] == 20
    # novelty는 backing evidence 없음
    assert top.evidence_ids == []


async def test_v1_force_explore_overrides_coin(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """force_explore=True면 ε 동전을 무시하고 explore 강제 (cold-start/stagnation용)."""
    store, index = seeded
    # eps=0이면 원래 항상 exploit인데, force_explore가 그걸 뒤집어야
    service = _build_v1_service(store, index, eps=0.0)
    result = await service.recommend(_query(), round_id="r-1", force_explore=True)
    top = result.candidates[0]
    assert top.policy is not None
    assert top.policy["branch"] == "explore"
    assert top.policy["forced"] is True


async def test_v1_no_force_respects_coin(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """force_explore=False(기본)면 ε 동전대로 — eps=0이면 exploit."""
    store, index = seeded
    service = _build_v1_service(store, index, eps=0.0)
    result = await service.recommend(_query(), round_id="r-1")
    top = result.candidates[0]
    assert top.policy["branch"] == "exploit"
    assert top.policy["forced"] is False


async def test_v1_deterministic_branch_for_same_round(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """같은 (corpus, round_id, intent)는 같은 분기 — 재현성 보장."""
    store, index = seeded
    service = _build_v1_service(store, index, eps=0.5)
    a = await service.recommend(_query(), round_id="round-stable")
    b = await service.recommend(_query(), round_id="round-stable")
    assert a.candidates[0].policy["branch"] == b.candidates[0].policy["branch"]


async def test_v1_cold_start_marks_policy_branch() -> None:
    """corpus 비어있을 때 cold-start 분기 + policy.branch="cold_start" 마킹."""
    empty_store = InMemoryEvidenceStore()
    empty_index = InMemoryVectorIndex()
    service = _build_v1_service(empty_store, empty_index, eps=0.5)
    result = await service.recommend(_query(), round_id="r-1")

    assert len(result.candidates) > 0
    top = result.candidates[0]
    assert top.policy is not None
    assert top.policy["branch"] == "cold_start"
    assert top.policy["wild_card_fired"] is False
    assert top.next_config is None  # cold-start는 휴리스틱 recipe만, next_config 없음


# ---------- backwards compatibility ----------


async def test_v0_compat_no_synth_no_next_config(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """policy/synth 미주입 시 기존 v0.1 흐름 — next_config/policy 모두 None."""
    store, index = seeded
    service = MatchmakerService(
        embedder=_OkEmbedder(),
        vector_index=index,
        reranker=_UnusedReranker(),
        store=store,
        infogain_reranker=InfoGainReranker(llm=_StubPriorLLM()),
        # policy/within_synth/novelty_synth 미주입
    )
    result = await service.recommend(_query())

    for c in result.candidates:
        assert c.next_config is None
        assert c.policy is None


# ---------- intent.description → synthesizer (category 회귀 방지) ----------


async def test_v1_synth_receives_intent_description(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """intent.description(extra='allow')이 synthesizer 프롬프트로 흐른다.

    버그: 기존엔 query.intent.goal("exploration")만 synth에 전달돼 실제 의도(카테고리·
    방향)가 합성에서 사라지고 corpus 과거 분포로 회귀했다. description을 함께 넘겨
    LLM이 카테고리/방향을 반영하게 한다.
    """
    store, index = seeded
    captured: dict[str, str] = {}

    class _CaptureLLM:
        async def complete(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return ('{"recipe_id": "<ignored>", '
                    '"next_config": {"max_depth": 7}, "reasoning": "r"}')

    service = MatchmakerService(
        embedder=_OkEmbedder(),
        vector_index=index,
        reranker=_UnusedReranker(),
        store=store,
        infogain_reranker=InfoGainReranker(llm=_StubPriorLLM()),
        policy=FixedEpsilonPolicy(eps=0.0),  # 항상 exploit → within_synth
        within_synth=WithinRecipeSynthesizer(llm=_CaptureLLM()),
        novelty_synth=NoveltyRecipeSynthesizer(llm=_CaptureLLM()),
    )
    query = QueryFeatures.model_validate(
        {
            "worker_spec": {"cpu_cores": 16, "ram_gb": 32, "has_gpu": False},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "intent": {
                "goal": "exploration",
                "description": "MVTec screw anomaly detection, beat 0.86",
                "expected_baseline": {"metric": "AUC"},
                "tolerance": {"direction": "higher_is_better"},
            },
        }
    )
    await service.recommend(query, round_id="r-1")
    assert "screw" in captured["prompt"].lower()
