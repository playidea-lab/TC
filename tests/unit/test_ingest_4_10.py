"""pcq v4.10.0 Reproducibility Pack ingest e2e — 3 신규 필드 + 미지 필드 + PHI 분기."""

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_evidence_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.main import app


def _envelope(eid: str, pcq_extra: dict | None = None, envelope_extra: dict | None = None) -> dict:
    body: dict = {
        "evidence_id": eid,
        "tier": "real",
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {"goal": "exploration"},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "config": {"recipe_id": "rf"},
            "metrics": {"AUC": 0.84},
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": "op-1"},
            "contract_version": "2.0",
        },
    }
    if pcq_extra:
        body["pcq_record"].update(pcq_extra)
    if envelope_extra:
        body.update(envelope_extra)
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


# ---- 시나리오 1: 3 신규 필드 모두 present ---------------------------------


def test_ingest_with_all_3_new_fields(client, store) -> None:
    body = _envelope(
        "ev-410-full",
        pcq_extra={
            "code": {
                "content_sha256": "abc123",
                "scope": {"kind": "entry_script"},
            },
            "seeds": {"main": 42, "data": "rng-A"},
            "data_ref": {
                "uri": "s3://b/d.parquet",
                "content_sha256": "deadbeef",
                "size_bytes": 1024,
            },
        },
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 201, r.text

    # GET round-trip 시 3 필드 보존
    g = client.get("/evidence/ev-410-full")
    assert g.status_code == 200
    pcq = g.json()["evidence"]["pcq_record"]
    assert pcq["code"]["content_sha256"] == "abc123"
    assert pcq["code"]["scope"]["kind"] == "entry_script"
    assert pcq["seeds"] == {"main": 42, "data": "rng-A"}
    assert pcq["data_ref"]["content_sha256"] == "deadbeef"


# ---- 시나리오 2: 부분 present (code만) ------------------------------------


def test_ingest_with_code_only(client, store) -> None:
    body = _envelope(
        "ev-410-code-only",
        pcq_extra={
            "code": {
                "content_sha256": "xyz789",
                "scope": {"kind": "file_list", "files": ["a.py", "b.py"]},
            }
        },
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 201

    g = client.get("/evidence/ev-410-code-only")
    pcq = g.json()["evidence"]["pcq_record"]
    assert pcq["code"]["scope"]["files"] == ["a.py", "b.py"]
    assert pcq.get("seeds") is None
    assert pcq.get("data_ref") is None


# ---- 시나리오 3: PcqRecord 미지 필드 보존 (extra='allow') -----------------


def test_ingest_preserves_unknown_pcq_field(client, store) -> None:
    body = _envelope(
        "ev-410-unknown",
        pcq_extra={"future_attestation": {"tee_quote": "xyz", "rekor_uuid": "abc"}},
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 201

    g = client.get("/evidence/ev-410-unknown")
    pcq = g.json()["evidence"]["pcq_record"]
    assert pcq.get("future_attestation") == {"tee_quote": "xyz", "rekor_uuid": "abc"}, (
        "extra='allow' 전환으로 미지 필드 round-trip 보존되어야 함"
    )


# ---- 시나리오 4: PHI stripped (data_ref.content_sha256=None) ---------------


def test_ingest_phi_stripped_data_ref(client, store) -> None:
    body = _envelope(
        "ev-410-phi",
        pcq_extra={
            "data_ref": {"uri": "phi://patient/db", "content_sha256": None}
        },
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 201

    g = client.get("/evidence/ev-410-phi")
    pcq = g.json()["evidence"]["pcq_record"]
    assert pcq["data_ref"]["content_sha256"] is None
    assert pcq["data_ref"]["uri"] == "phi://patient/db"


# ---- 시나리오 5: Evidence envelope 미지 top-level → HTTP 422 --------------


def test_envelope_rejects_unknown_top_level_field(client) -> None:
    """Evidence (TC scope) extra='forbid' 유지 — R10 envelope boundary."""
    body = _envelope("ev-bad-env", envelope_extra={"future_tc_field": {"x": 1}})
    r = client.post("/ingest", json={"evidence": body})
    # Evidence envelope extra='forbid' — TC 기존 API가 schema validation 실패를 400으로 응답
    assert r.status_code == 400, (
        f"Evidence envelope이 forbid를 유지해야 함 (TC R10 scope). got {r.status_code}: {r.text}"
    )
    assert "extra_forbidden" in r.text or "Extra inputs" in r.text


# ---- 시나리오 6: code present without scope.kind → HTTP 422 ----------------


def test_ingest_rejects_code_without_scope_kind(client) -> None:
    body = _envelope(
        "ev-bad-code",
        pcq_extra={"code": {"content_sha256": "abc", "scope": {}}},  # kind 누락
    )
    r = client.post("/ingest", json={"evidence": body})
    assert r.status_code == 400
