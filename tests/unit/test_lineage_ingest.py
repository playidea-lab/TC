"""lineage forward-compat — envelope.lineage 수용·검증·저장 (matchmaker는 안 읽음)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_evidence_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.models import Evidence, LineageEdge
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.main import app


def _envelope(eid: str = "ev-l1", lineage: list[dict] | None = None) -> dict:
    body: dict = {
        "evidence_id": eid,
        "tier": "real",
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "config": {"recipe_id": "rf"},
            "metrics": {"AUC": 0.84},
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": None},
            "contract_version": "2.0",
        },
    }
    if lineage is not None:
        body["lineage"] = lineage
    return body


@pytest.fixture
def store() -> InMemoryEvidenceStore:
    return InMemoryEvidenceStore()


@pytest.fixture
def client(store):
    async def _store() -> AsyncIterator[EvidenceStore]:
        yield store

    async def _claims():
        return VerifiedClaims(
            contributor_id="t", issuer="cq.pilab.kr", audience="the-commons",
            raw_claims={"sub": "t"},
        )

    app.dependency_overrides[get_evidence_store] = _store
    app.dependency_overrides[require_contributor] = _claims
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_lineage_absent_ingest_unaffected(client, store) -> None:
    r = client.post("/ingest", json={"evidence": _envelope("ev-a")})
    assert r.status_code == 201
    assert store.lineage_edges() == []


def test_lineage_single_edge_persisted(client, store) -> None:
    import asyncio

    # 먼저 target evidence 시드
    asyncio.run(store.insert(Evidence.model_validate(_envelope("ev-target"))))

    body = _envelope(
        "ev-source",
        lineage=[{"type": "derives_from", "target_evidence_id": "ev-target"}],
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 201
    edges = store.lineage_edges()
    assert len(edges) == 1
    assert edges[0]["source_evidence_id"] == "ev-source"
    assert edges[0]["target_evidence_id"] == "ev-target"
    assert edges[0]["edge_type"] == "derives_from"


def test_lineage_target_missing_rejected(client, store) -> None:
    body = _envelope(
        "ev-orphan",
        lineage=[{"type": "reproduces", "target_evidence_id": "ev-does-not-exist"}],
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 400
    assert "target_evidence_id" in r.json()["detail"]
    # 거부 시 envelope 자체도 저장 안 됨(트랜잭션 일관성 일부 — 적어도 lineage 미적재)
    assert store.lineage_edges() == []


def test_lineage_self_loop_rejected(client, store) -> None:
    body = _envelope(
        "ev-self",
        lineage=[{"type": "compared_to", "target_evidence_id": "ev-self"}],
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 400
    assert "self-loop" in r.json()["detail"].lower() or "자기" in r.json()["detail"]


def test_lineage_invalid_type_rejected_by_pydantic(client) -> None:
    body = _envelope(
        "ev-bad-type",
        lineage=[{"type": "wrong_kind", "target_evidence_id": "ev-x"}],
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 400  # Pydantic enum 검증 실패(schema 단계)


def test_le4_same_pcq_record_different_evidence_id_both_legal(client, store) -> None:
    # 같은 pcq_record content를 두 evidence_id로 — R10: 둘 다 합법
    body1 = _envelope("ev-twin-a")
    body2 = _envelope("ev-twin-b")  # pcq_record 동일 → integrity hash 동일
    r1 = client.post("/ingest", json={"evidence": body1})
    r2 = client.post("/ingest", json={"evidence": body2})
    assert r1.status_code == 201
    assert r2.status_code == 201


def test_lineage_multiple_edges_all_persisted(client, store) -> None:
    import asyncio

    for tid in ("ev-tx", "ev-ty"):
        asyncio.run(store.insert(Evidence.model_validate(_envelope(tid))))

    body = _envelope(
        "ev-multi",
        lineage=[
            {"type": "derives_from", "target_evidence_id": "ev-tx"},
            {"type": "reproduces", "target_evidence_id": "ev-ty"},
        ],
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 201
    edges = store.lineage_edges()
    assert len(edges) == 2
    types = {e["edge_type"] for e in edges}
    assert types == {"derives_from", "reproduces"}


def test_lineage_edge_pydantic_round_trip() -> None:
    edge = LineageEdge(type="derives_from", target_evidence_id="ev-x")
    dumped = edge.model_dump()
    assert dumped["type"] == "derives_from"
    assert dumped["target_evidence_id"] == "ev-x"
