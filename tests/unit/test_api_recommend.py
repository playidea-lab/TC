"""POST /recommend e2e — fake embedder/reranker/index 주입."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_evidence_store
from the_commons.api.recommend import (
    get_embedder,
    get_reranker,
    get_vector_index,
)
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.llm.protocol import RankedCandidate
from the_commons.main import app
from the_commons.matchmaker.retriever import InMemoryVectorIndex


class _FakeEmbedder:
    """항상 같은 vector를 반환 — retrieve가 결정적이 되도록."""

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeReranker:
    """candidate 순서 그대로 top_n 반환."""

    async def rerank(
        self, query: str, candidates: list[str], top_n: int = 5
    ) -> list[RankedCandidate]:
        return [
            RankedCandidate(index=i, score=1.0 - i * 0.1, reasoning=f"#{i}")
            for i in range(min(top_n, len(candidates)))
        ]


def _seeded_evidence(eid: str, vector: list[float] = None, tier: str = "real") -> dict:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
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
    if tier == "synthetic":
        rec["synthetic_source"] = {
            "source_model": "gemini-flash-2.5",
            "prompt_hash": "x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    return rec


@pytest.fixture
def seeded_corpus() -> tuple[InMemoryEvidenceStore, InMemoryVectorIndex]:
    """5개 evidence를 store + index에 시드 (corpus 충분)."""
    store = InMemoryEvidenceStore()
    index = InMemoryVectorIndex()
    return store, index


@pytest.fixture
def fake_claims() -> VerifiedClaims:
    return VerifiedClaims(
        contributor_id="t",
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": "t"},
    )


@pytest.fixture
def wired_client(
    seeded_corpus: tuple[InMemoryEvidenceStore, InMemoryVectorIndex],
    fake_claims: VerifiedClaims,
) -> TestClient:
    store, index = seeded_corpus
    embedder = _FakeEmbedder()
    reranker = _FakeReranker()

    async def _override_store() -> AsyncIterator[EvidenceStore]:
        yield store

    async def _override_embedder():
        return embedder

    async def _override_reranker():
        return reranker

    async def _override_index():
        return index

    async def _override_claims():
        return fake_claims

    app.dependency_overrides[get_evidence_store] = _override_store
    app.dependency_overrides[get_embedder] = _override_embedder
    app.dependency_overrides[get_reranker] = _override_reranker
    app.dependency_overrides[get_vector_index] = _override_index
    app.dependency_overrides[require_contributor] = _override_claims
    try:
        with TestClient(app) as client:
            yield client, store, index
    finally:
        app.dependency_overrides.clear()


_QUERY_BODY = {
    "query": {
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
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
}


def test_recommend_with_empty_corpus_returns_heuristic_fallback(
    wired_client,
) -> None:
    """corpus 비어있으면 휴리스틱 fallback + weak_heuristic 라벨."""
    client, _, _ = wired_client
    response = client.post("/recommend", json=_QUERY_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["corpus_context"]["real_count"] == 0
    assert body["corpus_context"]["synthetic_count"] == 0
    assert len(body["candidates"]) > 0
    assert all(c["confidence"] == "weak_heuristic" for c in body["candidates"])
    # 휴리스틱은 evidence_ids 비어있음
    assert all(c["evidence_ids"] == [] for c in body["candidates"])


def test_recommend_with_seeded_corpus_returns_real_backed_candidates(
    wired_client,
) -> None:
    """corpus가 충분하면 evidence_ids 포함된 응답."""
    client, store, index = wired_client

    # 5개 evidence 시드 (corpus 충분 → fallback 안 함)
    import asyncio

    async def _seed():
        for i in range(5):
            rec_dict = _seeded_evidence(f"ev-{i}")
            ev = Evidence.model_validate(rec_dict)
            await store.insert(ev)
            index.add(f"ev-{i}", [1.0, 0.0, 0.0], tier="real")

    asyncio.run(_seed())

    response = client.post("/recommend", json=_QUERY_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["corpus_context"]["real_count"] == 5
    assert body["corpus_context"]["synthetic_count"] == 0
    assert len(body["candidates"]) == 5
    assert all(c["confidence"] == "strong" for c in body["candidates"])
    # 각 후보는 근거 evidence_id를 갖는다
    for c in body["candidates"]:
        assert len(c["evidence_ids"]) == 1
        assert c["evidence_ids"][0].startswith("ev-")


def test_recommend_synthetic_dominant_corpus_returns_warning_label(
    wired_client,
) -> None:
    """synthetic이 real보다 많으면 synthetic_dominant 라벨."""
    client, store, index = wired_client

    import asyncio

    async def _seed():
        # 1 real + 6 synthetic = synthetic dominant
        for i in range(7):
            tier = "real" if i == 0 else "synthetic"
            rec_dict = _seeded_evidence(f"ev-{i}", tier=tier)
            ev = Evidence.model_validate(rec_dict)
            await store.insert(ev)
            index.add(f"ev-{i}", [1.0, 0.0, 0.0], tier=tier)

    asyncio.run(_seed())

    response = client.post("/recommend", json=_QUERY_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["corpus_context"]["synthetic_count"] == 6
    assert body["corpus_context"]["real_count"] == 1
    assert all(c["confidence"] == "synthetic_dominant" for c in body["candidates"])


def test_recommend_response_includes_template_version(wired_client) -> None:
    """응답에 사용된 template_version이 명시되어야 한다 (검증·재현 가능성)."""
    client, _, _ = wired_client
    response = client.post("/recommend", json=_QUERY_BODY)
    assert response.status_code == 200
    assert response.json()["template_version"] == "v1"
