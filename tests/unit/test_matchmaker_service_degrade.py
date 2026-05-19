"""matchmaker service의 외부 LLM 실패 graceful degrade 검증."""

import pytest

from the_commons.library.store import InMemoryEvidenceStore
from the_commons.llm.protocol import RankedCandidate
from the_commons.matchmaker.retriever import InMemoryVectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService


class _FailingEmbedder:
    """embed가 항상 raise — 외부 LLM 장애 시뮬레이션."""

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedder down")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedder down")


class _OkEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FailingReranker:
    async def rerank(
        self, query: str, candidates: list[str], top_n: int = 5
    ) -> list[RankedCandidate]:
        raise RuntimeError("reranker down")


def _query() -> QueryFeatures:
    return QueryFeatures.model_validate(
        {
            "worker_spec": {"cpu_cores": 16, "ram_gb": 32, "has_gpu": False},
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "10k-100k",
                "schema_summary": {},
                "statistical_moments": {},
            },
            "intent": {
                "goal": "exploration",
                "expected_baseline": None,
                "tolerance": None,
            },
        }
    )


async def test_embedder_failure_falls_back_to_cold_start() -> None:
    """embed 실패 시 cold_start_candidates를 weak_heuristic으로 응답."""
    service = MatchmakerService(
        embedder=_FailingEmbedder(),
        vector_index=InMemoryVectorIndex(),
        reranker=_FailingReranker(),  # 안 불려야 함
        store=InMemoryEvidenceStore(),
    )

    result = await service.recommend(_query())

    assert result.corpus_context.real_count == 0
    assert result.corpus_context.synthetic_count == 0
    assert len(result.candidates) > 0
    assert all(c.confidence == "weak_heuristic" for c in result.candidates)
    assert all(c.evidence_ids == [] for c in result.candidates)


@pytest.fixture
def seeded_index_and_store() -> tuple[InMemoryEvidenceStore, InMemoryVectorIndex]:
    """5건 evidence를 store + index에 시드해 corpus를 dense하게."""
    import asyncio

    from the_commons.library.models import Evidence

    store = InMemoryEvidenceStore()
    index = InMemoryVectorIndex()

    async def _seed():
        for i in range(5):
            rec = {
                "evidence_id": f"ev-{i}",
                "tier": "real",
                "outreach_origin": "external",
                "synthetic_source": None,
                "pcq_record": {
                    "intent": {
                        "goal": "exploration",
                        "expected_baseline": None,
                        "tolerance": None,
                    },
                    "data_fingerprint": {
                        "modality": "tabular",
                        "sample_count_band": "10k-100k",
                        "schema_summary": {},
                        "statistical_moments": {},
                    },
                    "config": {"recipe_id": "lightgbm"},
                    "metrics": {"AUC": 0.85},
                    "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
                    "attribution": {"operator": None},
                    "contract_version": "2.0",
                },
            }
            await store.insert(Evidence.model_validate(rec))
            index.add(f"ev-{i}", [1.0, 0.0, 0.0], tier="real")

    asyncio.run(_seed())
    return store, index


async def test_reranker_failure_falls_back_to_similarity_ranking(
    seeded_index_and_store: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """rerank 실패 시 retrieval similarity 순서로 응답 + degrade reasoning."""
    store, index = seeded_index_and_store
    service = MatchmakerService(
        embedder=_OkEmbedder(),
        vector_index=index,
        reranker=_FailingReranker(),
        store=store,
    )

    result = await service.recommend(_query())

    # corpus dense → cold-start 아닌 정상 retrieve path
    assert result.corpus_context.real_count == 5
    assert len(result.candidates) == 5
    # reasoning에 "reranker unavailable" 명시
    assert all("reranker unavailable" in c.reasoning for c in result.candidates)
    # confidence는 strong (corpus dense)
    assert all(c.confidence == "strong" for c in result.candidates)
