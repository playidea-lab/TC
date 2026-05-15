"""GET /evidence (list) + GET /verdict endpoint 검증."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import (
    get_evidence_store,
    get_reciprocity_store,
)
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.content_hash import compute_content_hash
from the_commons.library.models import Evidence
from the_commons.library.store import EvidenceStore, InMemoryEvidenceStore
from the_commons.main import app
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore


def _record(
    evidence_id: str,
    tier: str = "real",
    modality: str = "tabular",
    band: str = "10k-100k",
    goal: str = "exploration",
    contributor: str | None = None,
) -> dict:
    rec = {
        "evidence_id": evidence_id,
        "tier": tier,
        "outreach_origin": "external",
        "intent": {"goal": goal, "expected_baseline": None, "tolerance": None},
        "data_fingerprint": {
            "modality": modality,
            "sample_count_band": band,
            "schema_summary": {},
            "statistical_moments": {},
        },
        "config": {"recipe_id": "lightgbm"},
        "metrics": {"AUC": 0.85},
        "worker_spec": {"cpu_cores": 32, "ram_gb": 64, "has_gpu": True},
        "attribution": {
            "contributor_id": contributor,
            "content_hash": "",
            "created_at": datetime.now(UTC).isoformat(),
            "pcq_version": "2.0.0",
        },
        "synthetic_source": None,
    }
    if tier == "synthetic":
        rec["synthetic_source"] = {
            "source_model": "gemini-flash-2.5",
            "prompt_hash": "sha256:x",
            "generated_at": datetime.now(UTC).isoformat(),
            "verifier": None,
        }
    rec["attribution"]["content_hash"] = compute_content_hash(rec)
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
        contributor_id="t",
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": "t"},
    )


@pytest.fixture
def client(evidence_store, reciprocity_store, claims):
    async def _store() -> AsyncIterator[EvidenceStore]:
        yield evidence_store

    async def _reciprocity():
        return reciprocity_store

    async def _claims():
        return claims

    app.dependency_overrides[get_evidence_store] = _store
    app.dependency_overrides[get_reciprocity_store] = _reciprocity
    app.dependency_overrides[require_contributor] = _claims
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# GET /evidence (list)
# ============================================================================


def test_list_evidence_returns_all_with_no_filters(
    client: TestClient, evidence_store: InMemoryEvidenceStore
) -> None:
    """필터 없이 호출 시 active evidence 전부 반환."""
    import asyncio

    async def _seed():
        for i in range(3):
            await evidence_store.insert(Evidence.model_validate(_record(f"ev-{i}")))

    asyncio.run(_seed())

    response = client.get("/evidence")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["evidences"]) == 3


def test_list_evidence_filters_by_tier(
    client: TestClient, evidence_store: InMemoryEvidenceStore
) -> None:
    """tier=synthetic만 반환."""
    import asyncio

    async def _seed():
        await evidence_store.insert(Evidence.model_validate(_record("ev-r", tier="real")))
        await evidence_store.insert(
            Evidence.model_validate(_record("ev-s", tier="synthetic"))
        )

    asyncio.run(_seed())

    response = client.get("/evidence?tier=synthetic")
    body = response.json()
    assert body["total"] == 1
    assert body["evidences"][0]["evidence_id"] == "ev-s"


def test_list_evidence_filters_by_modality_and_goal(
    client: TestClient, evidence_store: InMemoryEvidenceStore
) -> None:
    """modality + intent_goal 조합 필터."""
    import asyncio

    async def _seed():
        await evidence_store.insert(
            Evidence.model_validate(
                _record("ev-t-expl", modality="tabular", goal="exploration")
            )
        )
        await evidence_store.insert(
            Evidence.model_validate(
                _record("ev-t-sota", modality="tabular", goal="sota_challenge")
            )
        )

    asyncio.run(_seed())

    response = client.get("/evidence?modality=tabular&intent_goal=sota_challenge")
    body = response.json()
    assert body["total"] == 1
    assert body["evidences"][0]["evidence_id"] == "ev-t-sota"


def test_list_evidence_pagination(
    client: TestClient, evidence_store: InMemoryEvidenceStore
) -> None:
    """limit + offset이 적용되고 total은 전체 매칭."""
    import asyncio

    async def _seed():
        for i in range(5):
            await evidence_store.insert(Evidence.model_validate(_record(f"ev-{i}")))

    asyncio.run(_seed())

    response = client.get("/evidence?limit=2&offset=1")
    body = response.json()
    assert body["total"] == 5
    assert len(body["evidences"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 1


def test_list_evidence_invalid_limit_returns_422(client: TestClient) -> None:
    """limit=0이나 limit>100은 422."""
    assert client.get("/evidence?limit=0").status_code == 422
    assert client.get("/evidence?limit=200").status_code == 422


# ============================================================================
# GET /verdict
# ============================================================================


def test_verdict_with_empty_store_returns_failure(client: TestClient) -> None:
    """event 0건 → branch=failure, strengthened=False."""
    response = client.get("/verdict")
    assert response.status_code == 200
    body = response.json()
    assert body["branch"] == "failure"
    assert body["is_success"] is False
    assert body["strengthened"] is False


def test_verdict_with_loop_closure_and_promote_returns_success(
    client: TestClient,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """loop_closure + promote → success + strengthened (external origin)."""
    import asyncio

    async def _seed():
        await reciprocity_store.record(
            event_type="loop_closure",
            primary_evidence_id="ev-a",
            related_evidence_ids=[],
            origin="external",
        )
        await reciprocity_store.record(
            event_type="promote",
            primary_evidence_id="ev-real",
            related_evidence_ids=["ev-syn"],
            origin="external",
        )

    asyncio.run(_seed())

    response = client.get("/verdict")
    body = response.json()
    assert body["branch"] == "success"
    assert body["is_success"] is True
    assert body["strengthened"] is True
    assert body["counts"]["loop_closure"] == 1
    assert body["counts"]["promote"] == 1
