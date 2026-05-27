"""K1·K2 e2e narrative — v0.1 success metric 핵심 시연.

비전 약속이 동작하는 한 사이클을 endpoint 호출로 자동 검증:
1. corpus를 synthetic으로 시드 (M5 seed pipeline 시뮬레이션)
2. K1이 /recommend → /ingest (real evidence 기증)
3. K1 ingest 응답에 promote/contradict + 가능 시 retirement 포함
4. K2가 /recommend → K1의 evidence가 응답에 포함 (loop closure)
5. 3 vision event 모두 ≥ 1 → verdict success
"""

import asyncio
from collections.abc import AsyncIterator

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
from the_commons.library.content_hash import compute_integrity
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.llm.protocol import RankedCandidate
from the_commons.main import app
from the_commons.matchmaker.retriever import InMemoryVectorIndex
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore
from the_commons.reciprocity.verdict_report import build_verdict_report
from the_commons.seed.synthetic_generator import (
    SeedSpec,
    SyntheticPrediction,
    build_synthetic_record,
)

QUERY_BODY = {
    "query": {
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "data_fingerprint": {
            "modality": "tabular",
            "sample_count_band": "10k-100k",
            "schema_summary": {},
            "statistical_moments": {},
        },
        "intent": {
            "goal": "sota_challenge",
            "expected_baseline": {"metric": "AUC", "value": 0.85},
            "tolerance": {"direction": "higher_is_better", "margin": 0.05},
        },
    }
}


def _real_record(evidence_id: str, *, metric: float, contributor: str) -> dict:
    rec = {
        "evidence_id": evidence_id,
        "tier": "real",
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {
                "goal": "sota_challenge",
                "expected_baseline": {"metric": "AUC", "value": 0.85},
                "tolerance": {"direction": "higher_is_better", "margin": 0.05},
            },
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "10k-100k",
                "schema_summary": {},
                "statistical_moments": {},
            },
            "config": {"recipe_id": "lightgbm"},
            "metrics": {"AUC": metric},
            "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
            "attribution": {"operator": contributor},
            "contract_version": "2.0",
        },
    }
    rec["pcq_record"]["integrity"] = compute_integrity(rec["pcq_record"])
    return rec


def _seeded_synthetic() -> dict:
    """LightGBM이 AUC 0.85 정도일 거라는 LLM 예측을 그대로 시드."""
    spec = SeedSpec(
        modality="tabular",
        sample_count_band="10k-100k",
        intent_goal="sota_challenge",
        recipe_id="lightgbm",
        framework="lightgbm",
    )
    prediction = SyntheticPrediction(
        expected_metric_name="AUC",
        expected_metric_value=0.85,
        estimated_runtime_sec=180,
        hyperparams={"lr": 0.05},
        reasoning="LightGBM strong baseline",
    )
    return build_synthetic_record(
        spec,
        prediction,
        source_model="gemini-flash-2.5",
        prompt_hash="sha256:narrative",
        evidence_id_suffix="narrative-1",
    )


# ----------------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------------


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


# ----------------------------------------------------------------------------
# Test
# ----------------------------------------------------------------------------


@pytest.fixture
def narrative_setup():
    """K1·K2가 같은 cluster에 들어가도록 corpus를 synthetic으로 시드."""
    evidence_store = InMemoryEvidenceStore()
    reciprocity_store = InMemoryReciprocityEventStore()
    index = InMemoryVectorIndex()

    # 1. synthetic seed (corpus가 매치메이커 활성화될 정도로 다수)
    async def _seed():
        syn = _seeded_synthetic()
        ev = Evidence.model_validate(syn)
        await evidence_store.insert(ev)
        index.add(ev.evidence_id, [1.0, 0.0, 0.0], tier="synthetic")

        # 추가 3개로 vector index 채움 — pcq_record에 diversifier 주입해 hash 다르게
        for i in range(3):
            extra = dict(syn)
            extra["evidence_id"] = f"ev-syn-extra-{i}"
            extra_pcq = dict(syn["pcq_record"])
            extra_pcq["config"] = dict(syn["pcq_record"]["config"])
            extra_pcq["config"]["seed"] = i  # diversifier
            extra_pcq["integrity"] = compute_integrity(extra_pcq)
            extra["pcq_record"] = extra_pcq
            extra_ev = Evidence.model_validate(extra)
            await evidence_store.insert(extra_ev)
            index.add(extra_ev.evidence_id, [1.0, 0.0, 0.0], tier="synthetic")

    asyncio.run(_seed())

    claims = VerifiedClaims(
        contributor_id="k",
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": "k", "origin": "external"},
    )

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
        client = TestClient(app)
        yield client, evidence_store, reciprocity_store, index
    finally:
        app.dependency_overrides.clear()


def test_full_loop_k1_k2_produces_three_vision_events(narrative_setup) -> None:
    """K1·K2 narrative가 3-event verdict success를 만든다."""
    client, evidence_store, reciprocity_store, index = narrative_setup

    # === Phase 1 — K1이 추천 받음 + 실행 + 기증 ===
    k1_recommend = client.post("/recommend", json=QUERY_BODY)
    assert k1_recommend.status_code == 200
    # synthetic 5건 시드돼 있어 추천 받음 (synthetic_dominant 라벨일 수 있음)

    k1_real = _real_record("ev-real-k1", metric=0.86, contributor="k1")
    k1_ingest = client.post("/ingest", json={"evidence": k1_real})
    assert k1_ingest.status_code == 201

    # K1 ingest 응답에 cluster impact 확인
    impact = k1_ingest.json()["cluster_impact"]
    # synthetic 시드 5건과 일치 → promote events 발생해야
    assert len(impact["promoted_synthetic_ids"]) >= 1

    # K1 evidence를 index에 추가 (production은 ingest 단계에서 같이 임베딩됨).
    # add는 sync — async 래퍼 불필요. 동일 vector면 stable sort라 5번째 위치.
    index.add("ev-real-k1", [1.0, 0.0, 0.0], tier="real")

    # === Phase 2 — K2가 비슷한 query → K1 evidence가 응답에 포함 ===
    k2_recommend = client.post("/recommend", json=QUERY_BODY)
    assert k2_recommend.status_code == 200

    # 응답의 candidates 중 K1의 evidence_id가 cited되어야
    cited_ids: set[str] = set()
    for c in k2_recommend.json()["candidates"]:
        cited_ids.update(c["evidence_ids"])
    assert "ev-real-k1" in cited_ids, (
        f"K2 응답에 K1 evidence 미포함 — loop closure 검증 불가. cited={cited_ids}"
    )

    # === Phase 3 — verdict report 확인 ===
    verdict = asyncio.run(build_verdict_report(reciprocity_store))

    # 두 사이클 안에 다음 event 모두 발생해야:
    # - loop_closure (K1 recommend + K2 recommend에서 각각 발생)
    # - promote (K1 ingest 시 synthetic seed 평가)
    counts = verdict.counts
    assert counts["loop_closure"] >= 1, f"loop_closure event 부족: {counts}"
    assert counts["promote"] >= 1, f"promote event 부족: {counts}"

    # success branch: 두 axis 모두 ≥ 1 → success
    assert verdict.is_success, (
        f"3-event verdict가 success 아님: branch={verdict.branch}, counts={counts}"
    )
    # external origin event 1건 이상 → strengthened
    assert verdict.strengthened, "external origin event 부족 — strengthened 불가"
