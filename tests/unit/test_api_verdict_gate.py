"""GET /verdict 응답의 productization_gate 블록 — 결선 단위 테스트."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_evidence_store, get_reciprocity_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.main import app
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore
from the_commons.settings import settings


def _ev(eid: str, tier: str = "real") -> Evidence:
    rec = {
        "evidence_id": eid,
        "tier": tier,
        "outreach_origin": "external",
        "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
        "config": {"recipe_id": "rf"},
        "metrics": {"AUC": 0.85},
        "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
        "attribution": {
            "contributor_id": None,
            "content_hash": "",
            "created_at": datetime.now(UTC).isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    if tier == "synthetic":
        rec["synthetic_source"] = {
            "source_model": "gemini-2.5-flash",
            "prompt_hash": "sha256:x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
    return Evidence.model_validate(rec)


@pytest.fixture
def evidence_store() -> InMemoryEvidenceStore:
    return InMemoryEvidenceStore()


@pytest.fixture
def reciprocity_store() -> InMemoryReciprocityEventStore:
    return InMemoryReciprocityEventStore()


@pytest.fixture
def client(evidence_store, reciprocity_store):
    async def _store() -> AsyncIterator[EvidenceStore]:
        yield evidence_store

    async def _reciprocity():
        return reciprocity_store

    async def _claims():
        return VerifiedClaims(
            contributor_id="t",
            issuer="cq.pilab.kr",
            audience="the-commons",
            raw_claims={"sub": "t"},
        )

    app.dependency_overrides[get_evidence_store] = _store
    app.dependency_overrides[get_reciprocity_store] = _reciprocity
    app.dependency_overrides[require_contributor] = _claims
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_verdict_response_includes_gate_block(
    client, evidence_store, reciprocity_store
) -> None:
    async def _seed():
        for i in range(10):
            await evidence_store.insert(_ev(f"r{i}", "real"))
        await reciprocity_store.record(
            event_type="loop_closure",
            primary_evidence_id="r0",
            related_evidence_ids=[],
            origin="external",
        )

    asyncio.run(_seed())
    resp = client.get("/verdict")
    assert resp.status_code == 200
    body = resp.json()
    assert "productization_gate" in body
    g = body["productization_gate"]
    for k in (
        "c1_strengthened_success",
        "c2_corpus_density",
        "c3_quality",
        "tripped",
        "diagnostic",
        "forced_decision",
    ):
        assert k in g
    # 기존 verdict 필드 회귀 없음
    assert "branch" in body and "counts" in body and "strengthened" in body


def test_c3_unset_floor_yields_null_quality_and_not_tripped(
    client, evidence_store, reciprocity_store, monkeypatch
) -> None:
    # 기본 sentinel(floor=-1) → C3 측정 불가 → c3_quality null, 미트립
    monkeypatch.setattr(settings, "productization_promote_rate_floor", -1.0)

    async def _seed():
        for i in range(10):
            await evidence_store.insert(_ev(f"r{i}", "real"))

    asyncio.run(_seed())
    g = client.get("/verdict").json()["productization_gate"]
    assert g["c3_quality"] is None
    assert g["tripped"] is False
    assert "C3" in g["diagnostic"]


def test_synthetic_dominant_corpus_not_tripped(
    client, evidence_store, reciprocity_store, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "productization_promote_rate_floor", 0.5)
    monkeypatch.setattr(settings, "productization_min_reproductions", 2)

    async def _seed():
        await evidence_store.insert(_ev("r0", "real"))
        for i in range(8):
            await evidence_store.insert(_ev(f"s{i}", "synthetic"))
        await reciprocity_store.record(
            event_type="promote",
            primary_evidence_id="r0",
            related_evidence_ids=[],
            origin="external",
        )
        await reciprocity_store.record(
            event_type="promote",
            primary_evidence_id="r0",
            related_evidence_ids=[],
            origin="external",
        )

    asyncio.run(_seed())
    g = client.get("/verdict").json()["productization_gate"]
    assert g["c2_corpus_density"] is False
    assert g["tripped"] is False
