"""pytest 공용 fixture + 전역 격리 처리."""

import pytest
from fastapi.testclient import TestClient

from the_commons.api import dependencies as api_dependencies
from the_commons.api.rate_limit import ingest_bucket, recommend_bucket
from the_commons.llm.cost_meter import meter
from the_commons.main import app
from the_commons.reciprocity.event_store import InMemoryReciprocityEventStore


@pytest.fixture(autouse=True)
def _reset_module_singletons() -> None:
    """매 test 시작 시 module-level state 초기화.

    A.13 — rate-limit bucket, cost meter
    F.3 — api.dependencies._inmemory_reciprocity (Postgres 없는 환경의 fallback)
    """
    recommend_bucket.reset()
    ingest_bucket.reset()
    meter.reset()
    # F.3 — _inmemory_reciprocity가 test 간 누적되면 verdict / find_verifier_for가
    # 이전 test 영향 받음. 매 test 새 instance로 교체.
    api_dependencies._inmemory_reciprocity = InMemoryReciprocityEventStore()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient — sync 요청용."""
    return TestClient(app)
