"""GET /metrics endpoint 검증."""

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from the_commons.api.dependencies import get_reciprocity_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.llm.cost_meter import meter
from the_commons.main import app
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore


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
def client(
    reciprocity_store: InMemoryReciprocityEventStore, claims: VerifiedClaims
) -> AsyncIterator[TestClient]:
    async def _reciprocity():
        return reciprocity_store

    async def _claims():
        return claims

    app.dependency_overrides[get_reciprocity_store] = _reciprocity
    app.dependency_overrides[require_contributor] = _claims
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_metrics_returns_zero_state_initially(client: TestClient) -> None:
    """meter·event store가 비어있으면 zero state 응답."""
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["cost"]["total_calls"] == 0
    assert body["cost"]["today_usd"] == 0.0
    assert body["cost"]["total_usd"] == 0.0
    assert body["events_by_type"]["loop_closure"] == 0
    assert body["events_by_type"]["promote"] == 0
    assert body["events_by_type"]["contradicts"] == 0


def test_metrics_reflects_cost_records(client: TestClient) -> None:
    """meter.record 후 응답에 cost 반영."""
    meter.record(
        "gemini-2.5-flash", "rerank", input_tokens=1_000_000, output_tokens=0
    )
    response = client.get("/metrics")
    body = response.json()
    assert body["cost"]["total_calls"] == 1
    assert body["cost"]["today_usd"] == pytest.approx(0.30)
    assert body["cost"]["by_model"]["gemini-2.5-flash"] == pytest.approx(0.30)
    assert body["cost"]["by_operation"]["rerank"] == pytest.approx(0.30)


def test_metrics_reflects_reciprocity_events(
    client: TestClient,
    reciprocity_store: InMemoryReciprocityEventStore,
) -> None:
    """event store에 기록된 event count 반영."""
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

    response = client.get("/metrics")
    body = response.json()
    assert body["events_by_type"]["loop_closure"] == 1
    assert body["events_by_type"]["promote"] == 1
    assert body["events_by_type"]["contradicts"] == 0


def test_metrics_requires_jwt(client: TestClient) -> None:
    """JWT 없으면 401 (require_contributor 적용 확인)."""
    # claims override 잠시 해제
    app.dependency_overrides.pop(require_contributor, None)
    response = client.get("/metrics")
    assert response.status_code == 401
