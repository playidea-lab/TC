"""synthetic_source.verifier read-path — read 시점 server-derive (LE6)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_evidence_store, get_reciprocity_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.main import app
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore


def _synthetic(eid: str = "ev-syn") -> dict:
    return {
        "evidence_id": eid,
        "tier": "synthetic",
        "outreach_origin": "internal",
        "synthetic_source": {
            "source_model": "gemini-2.5-flash",
            "prompt_hash": "sha256:x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        },
        "pcq_record": {
            "intent": {"goal": "exploration", "expected_baseline": None, "tolerance": None},
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "config": {"recipe_id": "lgbm"},
            "metrics": {"AUC": 0.85},
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": None},
            "contract_version": "2.0",
        },
    }


def _real(eid: str = "ev-real") -> dict:
    rec = _synthetic(eid)
    rec["tier"] = "real"
    rec["outreach_origin"] = "external"
    rec["synthetic_source"] = None
    return rec


@pytest.fixture
def stores():
    return InMemoryEvidenceStore(), InMemoryReciprocityEventStore()


@pytest.fixture
def client(stores):
    store, recip = stores

    async def _store() -> AsyncIterator[EvidenceStore]:
        yield store

    async def _recip():
        return recip

    async def _claims():
        return VerifiedClaims(
            contributor_id="t", issuer="cq.pilab.kr", audience="the-commons",
            raw_claims={"sub": "t"},
        )

    app.dependency_overrides[get_evidence_store] = _store
    app.dependency_overrides[get_reciprocity_store] = _recip
    app.dependency_overrides[require_contributor] = _claims
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_promote_event_fills_verifier_at_read_time(client, stores) -> None:
    store, recip = stores

    async def _seed():
        await store.insert(Evidence.model_validate(_synthetic("ev-s1")))
        await store.insert(Evidence.model_validate(_real("ev-r1")))
        await recip.record(
            event_type="promote",
            primary_evidence_id="ev-r1",
            related_evidence_ids=["ev-s1"],
            origin="external",
        )

    asyncio.run(_seed())
    r = client.get("/evidence/ev-s1")
    assert r.status_code == 200
    body = r.json()["evidence"]
    assert body["synthetic_source"]["verifier"] == "ev-r1"


def test_no_verifier_event_leaves_verifier_none(client, stores) -> None:
    store, _ = stores
    asyncio.run(store.insert(Evidence.model_validate(_synthetic("ev-s2"))))
    r = client.get("/evidence/ev-s2")
    assert r.status_code == 200
    assert r.json()["evidence"]["synthetic_source"]["verifier"] is None


def test_contradicts_event_also_fills_verifier(client, stores) -> None:
    """contradicts도 '검증자' 신호 — promote/contradicts 둘 다 verifier 자격."""
    store, recip = stores

    async def _seed():
        await store.insert(Evidence.model_validate(_synthetic("ev-s3")))
        await store.insert(Evidence.model_validate(_real("ev-r3")))
        await recip.record(
            event_type="contradicts",
            primary_evidence_id="ev-r3",
            related_evidence_ids=["ev-s3"],
            origin="external",
        )

    asyncio.run(_seed())
    r = client.get("/evidence/ev-s3")
    assert r.status_code == 200
    assert r.json()["evidence"]["synthetic_source"]["verifier"] == "ev-r3"
