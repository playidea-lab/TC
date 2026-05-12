"""POST /ingest + GET /evidence/{id} endpoint 통합 — DB 없이 in-memory store 주입."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_evidence_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.main import app


def _signed_record(
    *,
    evidence_id: str = "ev-test-1",
    tier: str = "real",
    metric_value: float = 0.84,
) -> dict:
    """공통 헬퍼 — content_hash까지 채운 발행 가능한 record."""
    base = {
        "evidence_id": evidence_id,
        "tier": tier,
        "outreach_origin": "external",
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
        "config": {"lr": 0.01},
        "metrics": {"AUC": metric_value},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {
            "contributor_id": None,
            "content_hash": "",
            "created_at": datetime.now(UTC).isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    if tier == "synthetic":
        base["synthetic_source"] = {
            "source_model": "gemini-flash-2.5",
            "prompt_hash": "sha256:promptabc",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    base["attribution"]["content_hash"] = compute_content_hash(base)
    return base


@pytest.fixture
def in_memory_store() -> InMemoryEvidenceStore:
    return InMemoryEvidenceStore()


@pytest.fixture
def fake_claims() -> VerifiedClaims:
    return VerifiedClaims(
        contributor_id="test-user",
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": "test-user"},
    )


@pytest.fixture
def authed_client(
    in_memory_store: InMemoryEvidenceStore,
    fake_claims: VerifiedClaims,
) -> TestClient:
    """auth/store dependency를 모두 fake로 override한 client."""

    async def _override_store() -> AsyncIterator[EvidenceStore]:
        yield in_memory_store

    async def _override_claims() -> VerifiedClaims:
        return fake_claims

    app.dependency_overrides[get_evidence_store] = _override_store
    app.dependency_overrides[require_contributor] = _override_claims
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_ingest_persists_record_and_returns_cluster_bucket(
    authed_client: TestClient,
) -> None:
    """올바른 record가 들어오면 201 + cluster bucket label 반환."""
    record = _signed_record()
    response = authed_client.post("/ingest", json={"evidence": record})

    assert response.status_code == 201
    body = response.json()
    assert body["evidence_id"] == "ev-test-1"
    assert body["tier"] == "real"
    assert body["cluster_impact"]["cluster_bucket"] == "tabular-exploration-10k-100k"


def test_ingest_then_read_returns_same_evidence(authed_client: TestClient) -> None:
    """ingest 후 같은 ID로 GET 호출 시 동일 evidence 반환."""
    record = _signed_record(evidence_id="ev-read-1")
    authed_client.post("/ingest", json={"evidence": record})

    response = authed_client.get("/evidence/ev-read-1")
    assert response.status_code == 200
    fetched = response.json()["evidence"]
    assert fetched["evidence_id"] == "ev-read-1"
    assert fetched["metrics"]["AUC"] == 0.84


def test_ingest_rejects_phi_violation(authed_client: TestClient) -> None:
    """raw_samples 같은 PHI는 400으로 거부."""
    record = _signed_record()
    record["data_fingerprint"]["raw_samples"] = [[1, 2, 3]]
    # content_hash는 의도적으로 재계산 안 함 (어차피 PHI 검사가 먼저)
    response = authed_client.post("/ingest", json={"evidence": record})
    assert response.status_code == 400
    assert "PHI" in response.json()["detail"]


def test_ingest_rejects_content_hash_mismatch(authed_client: TestClient) -> None:
    """attribution.content_hash 변조는 400."""
    record = _signed_record()
    record["metrics"]["AUC"] = 0.99  # 사후 변조
    response = authed_client.post("/ingest", json={"evidence": record})
    assert response.status_code == 400
    assert "content_hash" in response.json()["detail"]


def test_ingest_rejects_synthetic_without_source(authed_client: TestClient) -> None:
    """tier=synthetic인데 synthetic_source 없으면 400."""
    record = _signed_record(tier="synthetic")
    record["synthetic_source"] = None
    record["attribution"]["content_hash"] = compute_content_hash(record)
    response = authed_client.post("/ingest", json={"evidence": record})
    assert response.status_code == 400
    assert "synthetic_source" in response.json()["detail"]


def test_ingest_returns_conflict_on_duplicate_id(authed_client: TestClient) -> None:
    """같은 evidence_id 재제출은 409 Conflict."""
    record = _signed_record(evidence_id="ev-dup")
    first = authed_client.post("/ingest", json={"evidence": record})
    assert first.status_code == 201
    second = authed_client.post("/ingest", json={"evidence": record})
    assert second.status_code == 409


def test_read_unknown_evidence_returns_404(authed_client: TestClient) -> None:
    """없는 ID는 404."""
    response = authed_client.get("/evidence/ev-does-not-exist")
    assert response.status_code == 404


def test_ingest_persists_synthetic_with_attribution(authed_client: TestClient) -> None:
    """synthetic_source가 채워진 record는 정상 저장 + tier=synthetic 응답."""
    record = _signed_record(evidence_id="ev-syn-1", tier="synthetic")
    response = authed_client.post("/ingest", json={"evidence": record})
    assert response.status_code == 201
    assert response.json()["tier"] == "synthetic"
