"""endpoint ↔ reciprocity·retirement integration 검증.

ingest → promote/contradicts + retirement event 발생
recommend → loop_closure event 발생
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import (
    get_evidence_store,
    get_reciprocity_store,
)
from the_commons.api.recommend import (
    get_embedder,
    get_vector_index,
)
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.llm.protocol import RankedCandidate
from the_commons.main import app
from the_commons.matchmaker.retriever import InMemoryVectorIndex
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore

# ============================================================================
# Helpers
# ============================================================================


def _record(
    *,
    evidence_id: str,
    tier: str = "real",
    metric: float = 0.86,
    goal: str = "sota_challenge",
    expected_baseline: float | None = None,
) -> dict:
    """signed pcq 2.x record."""
    intent: dict = {"goal": goal, "expected_baseline": None, "tolerance": None}
    if expected_baseline is not None:
        intent["expected_baseline"] = {"metric": "AUC", "value": expected_baseline}
        intent["tolerance"] = {"direction": "higher_is_better", "margin": 0.05}

    rec = {
        "evidence_id": evidence_id,
        "tier": tier,
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": intent,
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "10k-100k",
                "schema_summary": {},
                "statistical_moments": {},
            },
            "config": {"recipe_id": "lightgbm"},
            "metrics": {"AUC": metric},
            "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
            "attribution": {"operator": "test-user"},
            "contract_version": "2.0",
        },
    }
    if tier == "synthetic":
        rec["synthetic_source"] = {
            "source_model": "gemini-flash-2.5",
            "prompt_hash": "sha256:x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    return rec


@pytest.fixture
def evidence_store() -> InMemoryEvidenceStore:
    return InMemoryEvidenceStore()


@pytest.fixture
def reciprocity_store() -> InMemoryReciprocityEventStore:
    return InMemoryReciprocityEventStore()


@pytest.fixture
def claims() -> VerifiedClaims:
    return VerifiedClaims(
        contributor_id="test-user",
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": "test-user", "origin": "external"},
    )


@pytest.fixture
def client(
    evidence_store: InMemoryEvidenceStore,
    reciprocity_store: InMemoryReciprocityEventStore,
    claims: VerifiedClaims,
) -> TestClient:
    """ingest용 client — evidence store + reciprocity store override."""

    async def _override_store() -> AsyncIterator[EvidenceStore]:
        yield evidence_store

    async def _override_reciprocity():
        return reciprocity_store

    async def _override_claims():
        return claims

    app.dependency_overrides[get_evidence_store] = _override_store
    app.dependency_overrides[get_reciprocity_store] = _override_reciprocity
    app.dependency_overrides[require_contributor] = _override_claims
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# /ingest → reciprocity
# ============================================================================


def test_real_ingest_records_promote_event_when_matching_synthetic_exists(
    client: TestClient,
    evidence_store: InMemoryEvidenceStore,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """synthetic이 미리 있는 cluster에 real이 들어가면 promote event 1건 기록."""
    # 1. 같은 cluster에 synthetic 시드 (expected AUC=0.85, real=0.86 → promote)
    syn = _record(
        evidence_id="ev-syn-a",
        tier="synthetic",
        metric=0.85,
        expected_baseline=0.85,
    )
    import asyncio

    asyncio.run(evidence_store.insert(Evidence.model_validate(syn)))

    # 2. real ingest
    real = _record(evidence_id="ev-real-a", tier="real", metric=0.86, expected_baseline=0.85)
    response = client.post("/ingest", json={"evidence": real})

    assert response.status_code == 201
    body = response.json()
    assert body["cluster_impact"]["promoted_synthetic_ids"] == ["ev-syn-a"]
    assert body["cluster_impact"]["contradicted_synthetic_ids"] == []

    # 3. reciprocity event 확인
    promote_events = [e for e in reciprocity_store.events if e.event_type == "promote"]
    assert len(promote_events) == 1
    assert promote_events[0].primary_evidence_id == "ev-real-a"
    assert promote_events[0].related_evidence_ids == ["ev-syn-a"]


def test_real_ingest_records_contradicts_when_outside_margin(
    client: TestClient,
    evidence_store: InMemoryEvidenceStore,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """real이 synthetic 예측과 tolerance 밖이면 contradicts."""
    syn = _record(
        evidence_id="ev-syn-b",
        tier="synthetic",
        metric=0.85,
        expected_baseline=0.85,
    )
    import asyncio

    asyncio.run(evidence_store.insert(Evidence.model_validate(syn)))

    # real=0.70은 0.85±0.05 밖 → contradicts
    real = _record(evidence_id="ev-real-b", tier="real", metric=0.70, expected_baseline=0.85)
    response = client.post("/ingest", json={"evidence": real})

    assert response.status_code == 201
    body = response.json()
    assert body["cluster_impact"]["contradicted_synthetic_ids"] == ["ev-syn-b"]

    contradicts_events = [
        e for e in reciprocity_store.events if e.event_type == "contradicts"
    ]
    assert len(contradicts_events) == 1


def test_third_real_triggers_synthetic_retirement(
    client: TestClient,
    evidence_store: InMemoryEvidenceStore,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """real이 threshold(3) 도달하면 같은 cluster active synthetic 모두 deprecate."""
    import asyncio

    # 같은 cluster에 synthetic 2개 시드
    for i in range(2):
        syn = _record(
            evidence_id=f"ev-syn-{i}",
            tier="synthetic",
            metric=0.85,
            expected_baseline=0.85,
        )
        asyncio.run(evidence_store.insert(Evidence.model_validate(syn)))

    # real 3건 순차 ingest
    last_body = None
    for i in range(3):
        real = _record(evidence_id=f"ev-real-{i}", tier="real", metric=0.86)
        response = client.post("/ingest", json={"evidence": real})
        assert response.status_code == 201
        last_body = response.json()

    # 3번째 real이 retirement 트리거
    assert last_body is not None
    retired = set(last_body["cluster_impact"]["retired_synthetic_ids"])
    assert retired == {"ev-syn-0", "ev-syn-1"}


def test_synthetic_ingest_does_not_trigger_reciprocity(
    client: TestClient,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """tier=synthetic ingest는 promote/contradicts 평가 안 함."""
    syn = _record(
        evidence_id="ev-syn-only",
        tier="synthetic",
        metric=0.85,
        expected_baseline=0.85,
    )
    response = client.post("/ingest", json={"evidence": syn})
    assert response.status_code == 201
    assert reciprocity_store.events == []


# ============================================================================
# /recommend → loop_closure
# ============================================================================


class _FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeReranker:
    async def rerank(
        self, query: str, candidates: list[str], top_n: int = 5
    ) -> list[RankedCandidate]:
        return [
            RankedCandidate(index=i, score=1.0 - i * 0.1, reasoning=f"#{i}")
            for i in range(min(top_n, len(candidates)))
        ]


@pytest.fixture
def recommend_client(
    evidence_store: InMemoryEvidenceStore,
    reciprocity_store: InMemoryReciprocityEventStore,
    claims: VerifiedClaims,
):
    """recommend 전용 client — full matchmaker dependency override."""
    index = InMemoryVectorIndex()

    async def _override_store() -> AsyncIterator[EvidenceStore]:
        yield evidence_store

    async def _override_reciprocity():
        return reciprocity_store

    async def _override_embedder():
        return _FakeEmbedder()

    async def _override_reranker():
        return _FakeReranker()

    async def _override_index():
        return index

    async def _override_claims():
        return claims

    app.dependency_overrides[get_evidence_store] = _override_store
    app.dependency_overrides[get_reciprocity_store] = _override_reciprocity
    app.dependency_overrides[get_embedder] = _override_embedder
    app.dependency_overrides[get_vector_index] = _override_index
    app.dependency_overrides[require_contributor] = _override_claims
    try:
        with TestClient(app) as c:
            yield c, index
    finally:
        app.dependency_overrides.clear()


def test_recommend_records_loop_closure_per_cited_evidence(
    recommend_client,
    evidence_store: InMemoryEvidenceStore,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """응답에 evidence_ids가 N개 포함되면 loop_closure event N건 기록."""
    import asyncio

    client, index = recommend_client

    # 5개 real evidence 시드 (corpus 충분 → fallback 안 함)
    async def _seed():
        for i in range(5):
            rec = _record(evidence_id=f"ev-{i}", tier="real")
            await evidence_store.insert(Evidence.model_validate(rec))
            index.add(f"ev-{i}", [1.0, 0.0, 0.0], tier="real")

    asyncio.run(_seed())

    body = {
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
    response = client.post("/recommend", json=body)
    assert response.status_code == 200

    loop_events = [
        e for e in reciprocity_store.events if e.event_type == "loop_closure"
    ]
    # 5 candidates → 5 loop_closure events
    assert len(loop_events) == 5
    assert {e.primary_evidence_id for e in loop_events} == {
        "ev-0", "ev-1", "ev-2", "ev-3", "ev-4"
    }
    assert all(e.origin == "external" for e in loop_events)


def test_recommend_with_empty_corpus_records_zero_loop_closures(
    recommend_client,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """corpus 비어있어 휴리스틱 fallback이면 loop_closure 0건 (evidence 미인용)."""
    client, _ = recommend_client

    body = {
        "query": {
            "worker_spec": {"cpu_cores": 16, "ram_gb": 32, "has_gpu": False},
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "1k-10k",
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
    response = client.post("/recommend", json=body)
    assert response.status_code == 200
    assert reciprocity_store.events == []
