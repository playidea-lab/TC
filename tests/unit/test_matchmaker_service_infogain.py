"""MatchmakerService ↔ InfoGainReranker 결선 단위 테스트.

- infogain_reranker 주입 시 step7이 그 결과로 compose된다.
- InfoGainReranker 예외 → 기존 similarity fallback (graceful degrade 불변).
- recommend 응답 reasoning에 사후·정보이득 문자열이 흐른다 (RR5).
"""

import asyncio
from datetime import UTC, datetime

import pytest

from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore
from the_commons.llm.protocol import RankedCandidate
from the_commons.matchmaker.infogain.reranker import InfoGainReranker
from the_commons.matchmaker.retriever import InMemoryVectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService


class _OkEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _UnusedReranker:
    async def rerank(self, query, candidates, top_n=5):  # noqa: ANN001
        raise AssertionError("infogain 주입 시 LLMReranker는 호출되면 안 됨")


class _StubPriorLLM:
    async def complete(self, prompt: str) -> str:
        return '{"alpha": 1.0, "beta": 1.0}'


class _ExplodingInfoGain:
    async def rerank(self, query, hits, records, top_n=5):  # noqa: ANN001
        raise RuntimeError("infogain down")


def _query() -> QueryFeatures:
    return QueryFeatures.model_validate(
        {
            "worker_spec": {"cpu_cores": 16, "ram_gb": 32, "has_gpu": False},
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "10k-100k",
            },
            "intent": {
                "goal": "exploration",
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
                    "config": {"recipe_id": recipe},
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


async def test_infogain_path_used_when_injected(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    store, index = seeded
    service = MatchmakerService(
        embedder=_OkEmbedder(),
        vector_index=index,
        reranker=_UnusedReranker(),  # 호출되면 AssertionError
        store=store,
        infogain_reranker=InfoGainReranker(llm=_StubPriorLLM()),
    )
    result = await service.recommend(_query())
    assert len(result.candidates) > 0
    # RR5: reasoning에 사후·정보이득 흔적
    joined = " ".join(c.reasoning.lower() for c in result.candidates)
    assert "gain" in joined
    assert "mean" in joined


async def test_infogain_exception_falls_back_to_similarity(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    store, index = seeded
    service = MatchmakerService(
        embedder=_OkEmbedder(),
        vector_index=index,
        reranker=_UnusedReranker(),
        store=store,
        infogain_reranker=_ExplodingInfoGain(),
    )
    result = await service.recommend(_query())
    assert len(result.candidates) > 0
    joined = " ".join(c.reasoning.lower() for c in result.candidates)
    assert "similarity" in joined  # _similarity_ordered_ranking degrade
