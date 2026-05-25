"""LLM-free MatchmakerService — retrieve+유사도 후보(처방 없음) + cold-start.

KR7 cleanup 후 service는 LLM 처방(synth/prior/reranker) 없이 retrieve→similarity→compose만
한다. 추천은 후보 제시(next_config 없음)이고 판단은 에이전트가 환류로.
"""

import asyncio

import pytest

from the_commons.library.models import Evidence
from the_commons.library.store import InMemoryEvidenceStore
from the_commons.matchmaker.retriever import InMemoryVectorIndex
from the_commons.matchmaker.serializer import QueryFeatures
from the_commons.matchmaker.service import MatchmakerService


class _OkEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FailEmbedder:
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedder down")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedder down")


def _query() -> QueryFeatures:
    return QueryFeatures.model_validate(
        {
            "worker_spec": {"cpu_cores": 16, "ram_gb": 32, "has_gpu": False},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
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
            [("rf", 0.9), ("rf", 0.8), ("xgb", 0.4), ("rf", 0.85), ("xgb", 0.5), ("svm", 0.6)]
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
                    "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
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


def _service(
    store: InMemoryEvidenceStore, index: InMemoryVectorIndex, embedder=None
) -> MatchmakerService:  # noqa: ANN001
    return MatchmakerService(embedder=embedder or _OkEmbedder(), vector_index=index, store=store)


async def test_recommend_similarity_candidates_no_prescription(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """retrieve+유사도 후보 — 처방(next_config)·정책 메타 없음."""
    store, index = seeded
    result = await _service(store, index).recommend(_query())
    assert len(result.candidates) > 0
    for c in result.candidates:
        assert c.next_config is None
        assert c.policy is None


async def test_recommend_cold_start_when_corpus_empty() -> None:
    """corpus 비면 휴리스틱 cold-start 후보 (real_count 0)."""
    result = await _service(InMemoryEvidenceStore(), InMemoryVectorIndex()).recommend(_query())
    assert len(result.candidates) > 0
    assert result.corpus_context.real_count == 0


async def test_recommend_cold_start_on_embedder_failure(
    seeded: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
) -> None:
    """embedder 장애 시 cold-start로 graceful degrade."""
    store, index = seeded
    result = await _service(store, index, embedder=_FailEmbedder()).recommend(_query())
    assert result.corpus_context.real_count == 0
